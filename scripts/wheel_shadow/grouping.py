"""precision-first 결정론 묶음 — 시간은 외곽 경계, 실제 묶음은 ROI motion + perceptual.

overlap 0 = 한 clip 은 최대 1 그룹. 애매하면 ungrouped (재현율보다 precision).
정렬 (started_at, clip_id) 로 입력 순서 무관 결정론.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from datetime import datetime

from .signatures import ClipSignature, hamming


@dataclasses.dataclass(frozen=True, slots=True)
class GroupingParams:
    # v1.1 boundary-fix: 두 시간 경계를 분리한다.
    #   - inter-clip gap: 앞 clip 과 현재 clip 사이 최대 간격
    #   - episode span: run 의 첫 clip 부터 현재 clip 까지 최대 전체 길이
    # 둘 중 하나라도 초과하면 새 run → 모든 그룹 전체 길이 ≤ max_episode_span_sec.
    max_inter_clip_gap_sec: float = 600.0
    max_episode_span_sec: float = 600.0
    wheel_motion_floor: float = 0.08  # ROI mean motion 하한 (wheel-active 게이트)
    hamming_threshold: int = 8        # dHash 근접 임계 (0~64)
    motion_tolerance: float = 0.08    # anchor 대비 ROI mean motion 허용차


@dataclasses.dataclass(frozen=True, slots=True)
class Group:
    group_id: str
    mode: str
    member_clip_ids: tuple[str, ...]
    representative_clip_ids: tuple[str, ...]
    started_at_first: str
    started_at_last: str


def _epoch(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


def _wheel_active(s: ClipSignature, p: GroupingParams) -> bool:
    return (
        s.evidence_quality == "ok"
        and not s.novelty
        and s.roi_motion_mean >= p.wheel_motion_floor
    )


def _similar(s: ClipSignature, anchor: ClipSignature, p: GroupingParams) -> bool:
    return (
        s.mode == anchor.mode
        and hamming(s.perceptual_hash, anchor.perceptual_hash) <= p.hamming_threshold
        and abs(s.roi_motion_mean - anchor.roi_motion_mean) <= p.motion_tolerance
    )


def group_clips(
    sigs: Sequence[ClipSignature],
    params: GroupingParams,
    select_reps: Callable[[list[ClipSignature]], tuple[str, ...]],
) -> tuple[list[Group], list[str]]:
    ordered = sorted(sigs, key=lambda s: (s.started_at, s.clip_id))
    runs: list[list[ClipSignature]] = []
    cur: list[ClipSignature] = []
    for s in ordered:
        if cur:
            inter_gap = _epoch(s.started_at) - _epoch(cur[-1].started_at)
            total_span = _epoch(s.started_at) - _epoch(cur[0].started_at)
            # 정확히 600초는 같은 run 포함, 초과만 분리(strict >).
            if (
                inter_gap > params.max_inter_clip_gap_sec
                or total_span > params.max_episode_span_sec
            ):
                runs.append(cur)
                cur = []
        cur.append(s)
    if cur:
        runs.append(cur)

    groups: list[Group] = []
    ungrouped: list[str] = []
    gi = 0
    for run in runs:
        groupable = [s for s in run if _wheel_active(s, params)]
        ungrouped.extend(s.clip_id for s in run if not _wheel_active(s, params))
        remaining = list(groupable)
        while remaining:
            # anchor = 최대 ROI motion peak, tie → 이른 시각 → clip_id
            anchor = sorted(
                remaining, key=lambda s: (-s.roi_motion_peak, s.started_at, s.clip_id)
            )[0]
            members = [s for s in remaining if _similar(s, anchor, params)]
            if len(members) >= 2:
                gi += 1
                members_sorted = sorted(members, key=lambda s: (s.started_at, s.clip_id))
                reps = select_reps(members)
                groups.append(
                    Group(
                        group_id=f"wheel_ep_{gi:03d}",
                        mode=anchor.mode,
                        member_clip_ids=tuple(m.clip_id for m in members_sorted),
                        representative_clip_ids=reps,
                        started_at_first=members_sorted[0].started_at,
                        started_at_last=members_sorted[-1].started_at,
                    )
                )
                members_ids = {m.clip_id for m in members}
                remaining = [s for s in remaining if s.clip_id not in members_ids]
            else:
                ungrouped.append(anchor.clip_id)
                remaining = [s for s in remaining if s.clip_id != anchor.clip_id]
    return groups, sorted(set(ungrouped))


def group_span_sec(group: Group) -> float:
    """그룹 전체 길이(첫 clip ~ 마지막 clip, 초)."""
    return _epoch(group.started_at_last) - _epoch(group.started_at_first)


def validate_group_spans(groups: Sequence[Group], max_span_sec: float) -> None:
    """모든 그룹 전체 길이 ≤ max_span_sec 강제. 위반 시 hard fail(원시 데이터 미노출)."""
    violations = [g.group_id for g in groups if group_span_sec(g) > max_span_sec]
    if violations:
        raise ValueError(
            f"group_span_contract_violation count={len(violations)}"
        )
