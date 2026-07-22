"""Local VLM evidence 후보 selector — 순수 결정론 로직 (Gate B1 Task 1).

이 모듈은 DB·네트워크·모델을 전혀 건드리지 않는다. production Python Evidence 와
activity assessment 에서 뽑아낸 `SourceRow` 만 입력받아, 6 strata 후보를
**결정론적으로** 분류·episode dedup·우선순위화한다 (설계
`docs/superpowers/specs/2026-07-22-local-vlm-evidence-web-gt-design.md` §6).

핵심 계약
- 모델 출력(prediction/reasoning/label)은 입력 필드로 받지 않는다. `SourceRow` 는
  frozen+slots dataclass 라 미지 kwarg 는 TypeError 로 거부된다.
- 같은 snapshot 이면 입력 순서와 무관하게 동일한 후보 JSON bytes·SHA 를 낸다.
- priority_score 는 검수 우선순위일 뿐 GT 가 아니다. selector version 을 identity 에
  고정해, 공식이 바뀌면 새 selector version 을 강제한다.

JS/TS 비유: `SourceRow`/`Candidate` 는 `readonly` 인터페이스(frozen dataclass ≈ `Object.freeze`),
`build_episode_candidates` 는 순수 reducer 라 같은 입력 → 같은 출력이다.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

# selector version — identity·manifest 에 고정. 규칙/공식이 바뀌면 여기부터 올린다.
SELECTOR_VERSION = "local-vlm-evidence-selector-v1"

# v2 identity — multi-match 적격 + scarcity-first 배정(B1R Task 3/4). v1 artifact/SHA 를 덮어쓰지 않는다.
SELECTOR_VERSION_V2 = "local-vlm-evidence-selector-v2"

# canonical study strata (설계 §6.2)
STRATA: tuple[str, ...] = (
    "absent",
    "big_move",
    "rest_micro",
    "lick_water_food",
    "wheel_object",
    "hardcase",
)

# 한 episode 가 여러 strata 후보일 때 고른다 (설계 §6.3). hardcase 가 가장 강함.
STRATUM_CONFLICT_PRIORITY: tuple[str, ...] = (
    "hardcase",
    "wheel_object",
    "lick_water_food",
    "rest_micro",
    "big_move",
    "absent",
)

# 사람 행동 GT 중 lick/water/food retrieval 신호 (frozen — evidence GT 로 복사 금지)
LICK_FOOD_ACTIONS = frozenset(
    {"licking", "drinking", "eating_paste", "eating_prey", "prey_capture", "hand_feeding"}
)

# 쳇바퀴/사물 retrieval 신호 (사람 current_gt·behavior 에서만)
WHEEL_OBJECT_SIGNALS = frozenset(
    {"wheel", "wheel_running", "running_wheel", "wheel_object", "using_wheel"}
)

# hardcase GT quality 태그 (normalize 후). retrieval 신호일 뿐 evidence 로 복사 금지.
HARDCASE_GT_TAGS = frozenset({"ir", "occluded", "edge", "blur", "reflection", "far"})

EPISODE_GAP = timedelta(minutes=30)


# ---------------------------------------------------------------------------
# data models
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class SourceRow:
    """production evidence + activity + 사람 신호를 합친 후보 입력 (모델 출력 없음)."""

    clip_id: str
    camera_id: str
    captured_at: datetime
    duration_sec: float
    run_id: str
    assessment_id: str | None
    prelabel_id: str | None
    activity_decision: str | None
    gecko_visible: bool | None
    visibility_confidence: float | None
    frames_sampled: int | None
    level0_status: str
    level1_status: str
    global_motion_series: tuple[float, ...]
    roi_motion_series: tuple[float, ...]
    excursion_count: int
    human_actions: frozenset[str]
    current_gt: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class Candidate:
    clip_id: str
    stratum: str
    priority_score: float
    reason_codes: tuple[str, ...]
    episode_key: str
    source_run_id: str
    source_assessment_id: str | None
    selection_identity_sha256: str


@dataclass(frozen=True, slots=True)
class Quantiles:
    """level0=='ok' 전수에서 뽑은 corpus 임계값 (설계 §6.2 rest_micro/big_move 게이트)."""

    global_p90_q50: float
    global_p90_q75: float
    roi_p90_q50: float


# ---------------------------------------------------------------------------
# canonical metrics
# ---------------------------------------------------------------------------
def series_values(points: object) -> tuple[float, ...]:
    """motion series(jsonb `[{t,value}]` 또는 bare number 배열) -> value tuple.

    DB check(`value numeric>=0`)와 동치인 방어를 순수 로직에서도 강제한다:
    bool/string/NaN/inf/음수는 ValueError. bool 은 int 하위형이라 명시적으로 거부.
    """
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
        raise ValueError(f"series must be a sequence, got {type(points).__name__}")
    out: list[float] = []
    for point in points:
        if isinstance(point, Mapping):
            if "value" not in point:
                raise ValueError("series point object missing 'value'")
            value = point["value"]
        else:
            value = point
        if isinstance(value, bool):
            raise ValueError("series value must not be bool")
        if not isinstance(value, (int, float)):
            raise ValueError(f"series value must be int|float, got {type(value).__name__}")
        fvalue = float(value)
        if not math.isfinite(fvalue):
            raise ValueError("series value must be finite (no NaN/inf)")
        if fvalue < 0:
            raise ValueError("series value must be >= 0")
        out.append(fvalue)
    return tuple(out)


def nearest_rank(values: Sequence[float], q: float) -> float:
    """결정론적 nearest-rank 백분위. 정렬 후 rank=ceil(q*N), [1,N] clamp."""
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    rank = math.ceil(q * n)
    if rank < 1:
        rank = 1
    if rank > n:
        rank = n
    return ordered[rank - 1]


def source_metrics(row: SourceRow) -> dict[str, float]:
    return {
        "global_p50": nearest_rank(row.global_motion_series, 0.50),
        "global_p90": nearest_rank(row.global_motion_series, 0.90),
        "roi_p50": nearest_rank(row.roi_motion_series, 0.50),
        "roi_p90": nearest_rank(row.roi_motion_series, 0.90),
        "excursion_count": float(row.excursion_count),
    }


def compute_quantiles(rows: Sequence[SourceRow]) -> Quantiles:
    """level0=='ok' 인 row 만으로 global/roi p90 분포의 임계값 계산 (설계 §6.2)."""
    eligible = [r for r in rows if r.level0_status == "ok"]
    global_p90 = [source_metrics(r)["global_p90"] for r in eligible]
    roi_p90 = [source_metrics(r)["roi_p90"] for r in eligible]
    return Quantiles(
        global_p90_q50=nearest_rank(global_p90, 0.50),
        global_p90_q75=nearest_rank(global_p90, 0.75),
        roi_p90_q50=nearest_rank(roi_p90, 0.50),
    )


# ---------------------------------------------------------------------------
# 사람 retrieval 신호 추출 (evidence GT 로 복사 금지 — 후보 탐색 보조만)
# ---------------------------------------------------------------------------
_GT_ACTION_KEYS = ("action", "primary_action", "actions", "behavior", "behaviors", "label", "labels")
_GT_OBJECT_KEYS = ("object", "objects", "object_candidates", "detected_objects")
_GT_QUALITY_KEYS = ("quality", "quality_tag", "quality_tags", "tags", "hardcase_tags")


def _flatten_tokens(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip().lower()]
    if isinstance(value, Mapping):
        tokens: list[str] = []
        for item in value.values():
            tokens.extend(_flatten_tokens(item))
        return tokens
    if isinstance(value, (list, tuple, set, frozenset)):
        tokens = []
        for item in value:
            tokens.extend(_flatten_tokens(item))
        return tokens
    return []


def _gt_tokens(current_gt: Mapping[str, object] | None, keys: Sequence[str]) -> frozenset[str]:
    if not current_gt:
        return frozenset()
    tokens: list[str] = []
    for key in keys:
        if key in current_gt:
            tokens.extend(_flatten_tokens(current_gt[key]))
    return frozenset(t for t in tokens if t)


def _human_action_tokens(row: SourceRow) -> frozenset[str]:
    tokens = {a.strip().lower() for a in row.human_actions if a}
    tokens |= _gt_tokens(row.current_gt, _GT_ACTION_KEYS)
    return frozenset(tokens)


def _wheel_tokens(row: SourceRow) -> frozenset[str]:
    tokens = _gt_tokens(row.current_gt, _GT_OBJECT_KEYS) | _human_action_tokens(row)
    return frozenset(tokens)


def _hardcase_gt_tags(row: SourceRow) -> frozenset[str]:
    tokens = _gt_tokens(row.current_gt, _GT_QUALITY_KEYS)
    return frozenset(t for t in tokens if t in HARDCASE_GT_TAGS)


# ---------------------------------------------------------------------------
# strata predicates (단일 배정, 우선순위 순)
# ---------------------------------------------------------------------------
def _hardcase_reasons(row: SourceRow) -> tuple[str, ...]:
    reasons: list[str] = []
    if row.activity_decision == "unknown":
        reasons.append("activity_unknown")
    if row.level1_status == "no_bbox" and row.gecko_visible is True:
        reasons.append("no_bbox_though_visible")
    if row.frames_sampled is not None and row.frames_sampled < 6:
        reasons.append("frames_lt_6")
    gt_tags = _hardcase_gt_tags(row)
    for tag in sorted(gt_tags):
        reasons.append(f"gt_{tag}")
    return tuple(reasons)


# --- per-stratum reason 계산 (v1 chain 과 v2 multi-match 가 공유) ---
# 각 함수는 해당 stratum 의 reason tuple 을 반환하고, 비적격이면 () 를 반환한다.
# reason tuple 은 v1 `_classify` 가 만들던 것과 **바이트 동일** (기존 SHA·회귀 보존).
def _wheel_reasons(row: SourceRow) -> tuple[str, ...]:
    if _wheel_tokens(row) & WHEEL_OBJECT_SIGNALS:
        return ("human_wheel_signal",)
    return ()


def _lick_reasons(row: SourceRow) -> tuple[str, ...]:
    lick = _human_action_tokens(row) & LICK_FOOD_ACTIONS
    return tuple(f"human_{a}" for a in sorted(lick)) if lick else ()


def _rest_reasons(row: SourceRow, q: Quantiles, metrics: dict | None = None) -> tuple[str, ...]:
    if metrics is None:
        metrics = source_metrics(row)
    localized = (
        row.gecko_visible is True
        and metrics["roi_p90"] >= q.roi_p90_q50
        and metrics["global_p90"] <= q.global_p90_q50
    )
    reasons: list[str] = []
    if localized:
        reasons.append("localized_roi_motion")
    if row.activity_decision == "exclude_static":
        reasons.append("exclude_static")
    return tuple(reasons)


def _big_reasons(row: SourceRow, q: Quantiles, metrics: dict | None = None) -> tuple[str, ...]:
    if metrics is None:
        metrics = source_metrics(row)
    big_active = row.activity_decision == "active" and metrics["global_p90"] >= q.global_p90_q75
    reasons: list[str] = []
    if big_active:
        reasons.append("active_high_global")
    if row.excursion_count > 0:
        reasons.append("has_excursion")
    return tuple(reasons)


def _absent_reasons(row: SourceRow) -> tuple[str, ...]:
    reasons: list[str] = []
    if row.activity_decision == "exclude_absent":
        reasons.append("exclude_absent")
    if row.gecko_visible is False:
        reasons.append("gecko_not_visible")
    return tuple(reasons)


# stratum -> reason 계산 함수 (hardcase 는 metrics 불필요). classify_eligible_strata 가 순회.
def _stratum_reason_fns(row: SourceRow, q: Quantiles, metrics: dict) -> dict[str, tuple[str, ...]]:
    return {
        "hardcase": _hardcase_reasons(row),
        "wheel_object": _wheel_reasons(row),
        "lick_water_food": _lick_reasons(row),
        "rest_micro": _rest_reasons(row, q, metrics),
        "big_move": _big_reasons(row, q, metrics),
        "absent": _absent_reasons(row),
    }


def _classify(row: SourceRow, q: Quantiles) -> tuple[str, tuple[str, ...]] | None:
    """단일 stratum + reason_codes. 매칭 없으면 None (설계 §6.2 우선순위 체인).

    v1 재현용 — STRATUM_CONFLICT_PRIORITY 순으로 **첫 적격** stratum 하나만 반환한다.
    """
    metrics = source_metrics(row)
    reason_map = _stratum_reason_fns(row, q, metrics)
    for stratum in STRATUM_CONFLICT_PRIORITY:
        reasons = reason_map[stratum]
        if reasons:
            return stratum, reasons
    return None


def classify_eligible_strata(row: SourceRow, q: Quantiles) -> dict[str, tuple[str, ...]]:
    """v2 multi-match — 여섯 predicate 를 **독립**으로 평가해 적격 stratum 전부 반환(B1R Task 3).

    v1(`_classify`)은 hardcase-first 단일 배정이라 어디에나 들어가는 hardcase 가 absent/rest/lick/wheel
    같은 희소군을 흡수해 굶겼다. v2 는 각 stratum reason 을 elif 가 아닌 독립 if 로 계산해, 실제 신호가
    있으면 하나의 clip 이 여러 strata 에 동시 적격일 수 있게 한다. 반환 dict 는 frozen STRATA 순서.
    """
    metrics = source_metrics(row)
    reason_map = _stratum_reason_fns(row, q, metrics)
    return {name: reason_map[name] for name in STRATA if reason_map[name]}


def _selection_identity(clip_id: str, stratum: str, reason_codes: tuple[str, ...],
                        run_id: str, assessment_id: str | None) -> str:
    """clip 선택의 provenance identity SHA-256. episode/priority(=pool 상대)는 제외."""
    payload = {
        "selector_version": SELECTOR_VERSION,
        "clip_id": clip_id,
        "stratum": stratum,
        "reason_codes": list(reason_codes),
        "source_run_id": run_id,
        "source_assessment_id": assessment_id,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def classify_stratum(row: SourceRow, q: Quantiles) -> str | None:
    """단일 row 의 stratum 이름만 반환(reason 없이). per-clip 분포 진단용 공개 헬퍼."""
    result = _classify(row, q)
    return result[0] if result is not None else None


def classify_candidate(row: SourceRow, q: Quantiles) -> Candidate | None:
    """단일 row -> Candidate (episode_key 미정=''), priority_score 는 pool 정렬 전 placeholder(1.0)."""
    result = _classify(row, q)
    if result is None:
        return None
    stratum, reason_codes = result
    return Candidate(
        clip_id=row.clip_id,
        stratum=stratum,
        priority_score=1.0,
        reason_codes=reason_codes,
        episode_key="",
        source_run_id=row.run_id,
        source_assessment_id=row.assessment_id,
        selection_identity_sha256=_selection_identity(
            row.clip_id, stratum, reason_codes, row.run_id, row.assessment_id
        ),
    )


# ---------------------------------------------------------------------------
# episode clustering (rolling 30-min gap, camera 별)
# ---------------------------------------------------------------------------
def _canonical_ts(value: datetime) -> str:
    utc = value.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def episode_key(camera_id: str, first_captured_at: datetime) -> str:
    return f"{camera_id}|{_canonical_ts(first_captured_at)}"


def cluster_episodes(rows: Sequence[SourceRow]) -> dict[str, str]:
    """clip_id -> episode_key. camera 별 시간순, 직전 clip 과 gap<=30분이면 같은 episode."""
    by_camera: dict[str, list[SourceRow]] = defaultdict(list)
    for r in rows:
        by_camera[r.camera_id].append(r)

    result: dict[str, str] = {}
    for camera_id, cam_rows in by_camera.items():
        ordered = sorted(cam_rows, key=lambda r: (r.captured_at, r.clip_id))
        start: datetime | None = None
        prev: datetime | None = None
        for r in ordered:
            if prev is None or (r.captured_at - prev) > EPISODE_GAP:
                start = r.captured_at
            assert start is not None
            result[r.clip_id] = episode_key(camera_id, start)
            prev = r.captured_at
    return result


# ---------------------------------------------------------------------------
# deterministic ordering within a stratum (best-first)
# ---------------------------------------------------------------------------
def _conf(row: SourceRow) -> float:
    return row.visibility_confidence if row.visibility_confidence is not None else 0.0


def _stratum_sort_passes(stratum: str):
    """stratum 별 (keyfn, reverse) 를 가장 유의미한 것부터 반환 (설계 §6.2 sort key)."""
    if stratum == "hardcase":
        return [
            (lambda r: len(_hardcase_reasons(r)), True),   # reason count desc
            (lambda r: _conf(r), False),                    # visibility confidence asc
        ]
    if stratum in ("wheel_object", "lick_water_food"):
        return [
            (lambda r: len(_human_action_tokens(r) | _wheel_tokens(r)), True),  # human-signal count desc
            (lambda r: r.captured_at, True),                                     # captured_at desc
        ]
    if stratum == "rest_micro":
        return [
            (lambda r: source_metrics(r)["roi_p90"] - source_metrics(r)["global_p90"], True),
        ]
    if stratum == "big_move":
        return [
            (lambda r: source_metrics(r)["global_p90"], True),   # global_p90 desc
            (lambda r: float(r.excursion_count), True),          # excursion count desc
        ]
    if stratum == "absent":
        return [
            (lambda r: 1 if r.activity_decision == "exclude_absent" else 0, True),  # explicit first
            (lambda r: _conf(r), True),                                             # visibility confidence desc
        ]
    return []


def _order_rows(rows: Sequence[SourceRow], stratum: str) -> list[SourceRow]:
    """stable multi-key 정렬로 best-first. tie-break: captured_at DESC, clip_id DESC."""
    items = list(rows)
    passes = _stratum_sort_passes(stratum) + [
        (lambda r: r.captured_at, True),
        (lambda r: r.clip_id, True),
    ]
    # least-significant 부터 적용해야 stable sort 로 most-significant 가 우선한다.
    for keyfn, reverse in reversed(passes):
        items.sort(key=keyfn, reverse=reverse)
    return items


# ---------------------------------------------------------------------------
# 전체 파이프라인 — classify + cluster + conflict resolve + rank
# ---------------------------------------------------------------------------
def build_episode_candidates(rows: Sequence[SourceRow]) -> list[Candidate]:
    """순수 결정론 파이프라인. episode 당 1 clip, stratum 내부 정규화 priority_score.

    입력 순서와 무관하게 동일한 후보 리스트를 낸다.
    """
    q = compute_quantiles(rows)
    episodes = cluster_episodes(rows)
    rows_by_id = {r.clip_id: r for r in rows}

    # 1) 분류된 clip 을 episode 별로 모은다.
    per_episode: dict[str, list[SourceRow]] = defaultdict(list)
    per_episode_stratum: dict[str, dict[str, list[SourceRow]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        result = _classify(r, q)
        if result is None:
            continue
        stratum, _ = result
        ep = episodes[r.clip_id]
        per_episode[ep].append(r)
        per_episode_stratum[ep][stratum].append(r)

    # 2) episode 당 conflict priority 로 stratum 하나 고르고 대표 clip 선택.
    episode_reps: dict[str, list[SourceRow]] = defaultdict(list)  # stratum -> rep rows
    episode_rep_key: dict[str, str] = {}  # clip_id -> episode_key
    for ep, strata_map in per_episode_stratum.items():
        chosen_stratum = next(s for s in STRATUM_CONFLICT_PRIORITY if s in strata_map)
        rep = _order_rows(strata_map[chosen_stratum], chosen_stratum)[0]
        episode_reps[chosen_stratum].append(rep)
        episode_rep_key[rep.clip_id] = ep

    # 3) stratum 별 정렬 후 priority_score 정규화 -> 최종 Candidate.
    candidates: list[Candidate] = []
    for stratum in STRATA:
        ranked = _order_rows(episode_reps.get(stratum, []), stratum)
        n = len(ranked)
        for rank, r in enumerate(ranked):
            result = _classify(r, q)
            assert result is not None
            _, reason_codes = result
            score = 1.0 - (rank / max(n - 1, 1))
            candidates.append(
                Candidate(
                    clip_id=r.clip_id,
                    stratum=stratum,
                    priority_score=score,
                    reason_codes=reason_codes,
                    episode_key=episode_rep_key[r.clip_id],
                    source_run_id=r.run_id,
                    source_assessment_id=r.assessment_id,
                    selection_identity_sha256=_selection_identity(
                        r.clip_id, stratum, reason_codes, r.run_id, r.assessment_id
                    ),
                )
            )
    return candidates


# ---------------------------------------------------------------------------
# canonical serialization (pool SHA 정본)
# ---------------------------------------------------------------------------
def candidate_to_dict(c: Candidate) -> dict[str, object]:
    return {
        "clip_id": c.clip_id,
        "stratum": c.stratum,
        "priority_score": c.priority_score,
        "reason_codes": list(c.reason_codes),
        "episode_key": c.episode_key,
        "source_run_id": c.source_run_id,
        "source_assessment_id": c.source_assessment_id,
        "selection_identity_sha256": c.selection_identity_sha256,
    }


def _stratum_index(stratum: str) -> int:
    return STRATA.index(stratum)


def candidates_canonical_json(candidates: Sequence[Candidate]) -> str:
    """입력 순서 무관 canonical JSON. stratum 순 -> priority desc -> clip_id 로 안정 정렬."""
    ordered = sorted(
        candidates,
        key=lambda c: (_stratum_index(c.stratum), -c.priority_score, c.clip_id),
    )
    payload = {
        "selector_version": SELECTOR_VERSION,
        "candidates": [candidate_to_dict(c) for c in ordered],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def candidates_sha256(candidates: Sequence[Candidate]) -> str:
    return hashlib.sha256(candidates_canonical_json(candidates).encode("utf-8")).hexdigest()
