"""Local VLM 후보 가용성 SELECT probe — production 읽기 전용 (Gate B1 Task 2).

production DB 를 **SELECT 전용**으로 읽어 6 strata broad candidate pool·분포·verdict·
pool SHA 를 만든다. write/migration/RPC/모델 호출은 전혀 하지 않는다.

핵심 계약 (설계 §6, plan Gate B1 Task 2)
- 후보 정본은 `motion_clips` 다. `camera_clips` 는 조회하지 않고 mirror 하지도 않는다.
- clip 당 evidence run 은 (schema=python-evidence-raw-v1, algo=croi-temporal-v1, level0=ok)
  1개만 사용한다. 0=missing_evidence 제외, 2=AMBIGUOUS_EVIDENCE fail-closed.
- `r2_key` 는 재생 가능성 판정에만 in-memory 로 쓰고 산출물·SourceRow 에는 남기지 않는다.
- prediction/reasoning/clip_vlm_jobs/signed URL/user email/secret 은 select 하지 않는다.

이 스크립트는 write flag 가 없다 (구조적으로 read-only).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from scripts.local_vlm_evidence_candidates import (
    SELECTOR_VERSION,
    STRATA,
    Candidate,
    SourceRow,
    build_episode_candidates,
    candidate_to_dict,
    candidates_sha256,
    classify_stratum,
    compute_quantiles,
    series_values,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# evidence run 필수 identity (설계 §6.1)
REQUIRED_SCHEMA = "python-evidence-raw-v1"
REQUIRED_ALGO = "croi-temporal-v1"

# verdict 라벨 (설계 §4 Gate B1)
DATA_AVAILABLE = "DATA_AVAILABLE"
DATA_AVAILABLE_LOW_MARGIN = "DATA_AVAILABLE_LOW_MARGIN"
BLOCKED_DATA_INSUFFICIENT = "BLOCKED_DATA_INSUFFICIENT"

POOL_CAP = 60
STRATUM_TARGET = 30
DEV_PER_STRATUM = 20
HOLDOUT_PER_STRATUM = 10

# bounded column projection — 절대 이 목록 밖을 select 하지 않는다.
RUN_COLUMNS = (
    "id,clip_id,prelabel_id,evidence_schema_version,algorithm_version,"
    "level0_status,level1_status,frames_sampled,global_motion_series,"
    "roi_motion_series,motion_excursions,created_at,source_prelabel_identity"
)
MOTION_COLUMNS = "id,camera_id,started_at,duration_sec,r2_key"
ASSESS_COLUMNS = "id,clip_id,prelabel_id,decision,policy_version,created_at"
PRELABEL_COLUMNS = "id,clip_id,gecko_visible,visibility_confidence,frames_sampled"
SESSION_COLUMNS = "clip_id,current_gt,stage,completed_at"
BEHAVIOR_COLUMNS = "clip_id,action,source,created_at"


class ProbeError(RuntimeError):
    """probe 계약 위반 — 산출물 없이 abort."""


class AmbiguousEvidenceError(ProbeError):
    """한 clip 에 필수 identity 를 만족하는 evidence run 이 2개 이상 — 조용히 고르지 않고 fail."""


# ---------------------------------------------------------------------------
# SELECT-only adapters
# ---------------------------------------------------------------------------
def _resp_data(resp) -> list:
    data = getattr(resp, "data", None)
    if data is None and isinstance(resp, dict):
        data = resp.get("data")
    return data or []


def _paginate(client, table: str, columns: str, order_column: str = "id",
              page_size: int = 1000, eq_filters: Sequence[tuple[str, object]] | None = None) -> list[dict]:
    """명시적 range pagination. builder 는 매 페이지 새로 만든다(1회 소비)."""
    rows: list[dict] = []
    offset = 0
    while True:
        query = client.table(table).select(columns)
        for col, val in eq_filters or ():
            query = query.eq(col, val)
        query = query.order(order_column).range(offset, offset + page_size - 1)
        data = _resp_data(query.execute())
        rows.extend(data)
        if len(data) < page_size:
            break
        offset += page_size
    return rows


def _load_by_ids(client, table: str, columns: str, id_column: str, ids: Sequence,
                 batch: int = 200, eq_filters: Sequence[tuple[str, object]] | None = None) -> list[dict]:
    out: list[dict] = []
    unique = sorted({i for i in ids if i is not None})
    for i in range(0, len(unique), batch):
        chunk = unique[i : i + batch]
        query = client.table(table).select(columns).in_(id_column, chunk)
        for col, val in eq_filters or ():
            query = query.eq(col, val)
        out.extend(_resp_data(query.order(id_column).execute()))
    return out


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _parse_ts(value: object) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_playable(motion: dict) -> bool:
    r2 = motion.get("r2_key")
    if not isinstance(r2, str) or not r2.strip():
        return False
    dur = motion.get("duration_sec")
    try:
        return float(dur) > 0
    except (TypeError, ValueError):
        return False


def _excursion_count(payload: object) -> int:
    if isinstance(payload, list):
        return len(payload)
    return 0


def _matches_required(run: dict) -> bool:
    return (
        run.get("evidence_schema_version") == REQUIRED_SCHEMA
        and run.get("algorithm_version") == REQUIRED_ALGO
        and run.get("level0_status") == "ok"
    )


# ---------------------------------------------------------------------------
# load_sources — production SELECT -> SourceRow (playable + matched evidence only)
# ---------------------------------------------------------------------------
def load_sources(client) -> list[SourceRow]:
    runs = _paginate(client, "clip_python_evidence_runs", RUN_COLUMNS)

    matched_runs: dict[str, dict] = {}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        if _matches_required(run):
            grouped[run["clip_id"]].append(run)
    for clip_id, run_list in grouped.items():
        if len(run_list) > 1:
            raise AmbiguousEvidenceError(
                f"clip {clip_id!r} has {len(run_list)} runs matching required evidence identity"
            )
        matched_runs[clip_id] = run_list[0]

    clip_ids = sorted(matched_runs)
    if not clip_ids:
        return []

    motion_rows = _load_by_ids(client, "motion_clips", MOTION_COLUMNS, "id", clip_ids)
    motion_by_id = {m["id"]: m for m in motion_rows}

    assessments = _load_by_ids(client, "clip_activity_assessments", ASSESS_COLUMNS, "clip_id", clip_ids)
    assess_by_clip: dict[str, list[dict]] = defaultdict(list)
    for a in assessments:
        assess_by_clip[a["clip_id"]].append(a)

    prelabel_ids = [matched_runs[c].get("prelabel_id") for c in clip_ids]
    prelabel_ids += [a.get("prelabel_id") for a in assessments]
    prelabels = _load_by_ids(client, "clip_prelabels", PRELABEL_COLUMNS, "id", prelabel_ids)
    prelabel_by_id = {p["id"]: p for p in prelabels}

    sessions = _load_by_ids(client, "clip_labeling_sessions", SESSION_COLUMNS, "clip_id", clip_ids)
    session_by_clip: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        session_by_clip[s["clip_id"]].append(s)

    behavior = _load_by_ids(client, "behavior_logs", BEHAVIOR_COLUMNS, "clip_id", clip_ids,
                            eq_filters=[("source", "human")])
    actions_by_clip: dict[str, set[str]] = defaultdict(set)
    for b in behavior:
        action = b.get("action")
        if action:
            actions_by_clip[b["clip_id"]].add(str(action))

    sources: list[SourceRow] = []
    for clip_id in clip_ids:
        motion = motion_by_id.get(clip_id)
        if motion is None or not _is_playable(motion):
            continue  # not_playable / no motion_clip row
        run = matched_runs[clip_id]

        # latest assessment (created_at desc, id tie-break) — 없으면 None
        assess = None
        alist = assess_by_clip.get(clip_id)
        if alist:
            assess = sorted(alist, key=lambda a: (str(a.get("created_at") or ""), str(a.get("id") or "")))[-1]

        prelabel_id = run.get("prelabel_id") or (assess or {}).get("prelabel_id")
        prelabel = prelabel_by_id.get(prelabel_id) if prelabel_id else None

        # latest session (completed_at desc) for current_gt
        current_gt = None
        slist = session_by_clip.get(clip_id)
        if slist:
            sess = sorted(slist, key=lambda s: str(s.get("completed_at") or ""))[-1]
            gt = sess.get("current_gt")
            if isinstance(gt, dict):
                current_gt = gt

        frames = None
        if prelabel is not None and prelabel.get("frames_sampled") is not None:
            frames = int(prelabel["frames_sampled"])
        elif run.get("frames_sampled") is not None:
            frames = int(run["frames_sampled"])

        sources.append(
            SourceRow(
                clip_id=clip_id,
                camera_id=str(motion["camera_id"]),
                captured_at=_parse_ts(motion["started_at"]),
                duration_sec=float(motion["duration_sec"]),
                run_id=str(run["id"]),
                assessment_id=(str(assess["id"]) if assess else None),
                prelabel_id=(str(prelabel_id) if prelabel_id else None),
                activity_decision=(assess.get("decision") if assess else None),
                gecko_visible=(bool(prelabel["gecko_visible"]) if prelabel and prelabel.get("gecko_visible") is not None else None),
                visibility_confidence=(float(prelabel["visibility_confidence"]) if prelabel and prelabel.get("visibility_confidence") is not None else None),
                frames_sampled=frames,
                level0_status=str(run["level0_status"]),
                level1_status=str(run["level1_status"]),
                global_motion_series=series_values(run.get("global_motion_series") or []),
                roi_motion_series=series_values(run.get("roi_motion_series") or []),
                excursion_count=_excursion_count(run.get("motion_excursions")),
                human_actions=frozenset(actions_by_clip.get(clip_id, set())),
                current_gt=current_gt,
            )
        )
    return sources


# ---------------------------------------------------------------------------
# availability assembly
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StratumAvailability:
    stratum: str
    episode_count: int
    pool_size: int
    verdict: str
    camera_distribution: dict
    date_distribution: dict
    single_camera_ratio: float
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class AvailabilityResult:
    selector_version: str
    strata: tuple[StratumAvailability, ...]
    overall_verdict: str
    camera_count: int
    date_count: int
    pool_sha256: str
    manifest_emitted: bool
    manifest: tuple[dict, ...] | None
    pool: tuple[Candidate, ...]
    excluded_counts: dict
    per_clip_stratum_distribution: dict
    total_episodes: int
    total_source_rows: int


def _date(row: SourceRow) -> str:
    return row.captured_at.date().isoformat()


def _stratum_verdict(count: int) -> str:
    if count >= 45:
        return DATA_AVAILABLE
    if count >= STRATUM_TARGET:
        return DATA_AVAILABLE_LOW_MARGIN
    return BLOCKED_DATA_INSUFFICIENT


def _round_robin(ranked: Sequence[Candidate], rows_by_id: dict[str, SourceRow], k: int) -> list[Candidate]:
    """camera 균형 우선 deterministic round-robin. 각 camera 안에서는 priority 순."""
    by_camera: dict[str, list[Candidate]] = defaultdict(list)
    for c in ranked:  # ranked is best-first
        by_camera[rows_by_id[c.clip_id].camera_id].append(c)
    cameras = sorted(by_camera)
    cursors = {cam: 0 for cam in cameras}
    selected: list[Candidate] = []
    while len(selected) < k:
        progressed = False
        for cam in cameras:
            if cursors[cam] < len(by_camera[cam]):
                selected.append(by_camera[cam][cursors[cam]])
                cursors[cam] += 1
                progressed = True
                if len(selected) == k:
                    break
        if not progressed:
            break
    return selected


def _build_manifest(final_by_stratum: dict[str, list[Candidate]]) -> list[dict]:
    """stratum 30개를 selection_identity_sha256 오름차순 -> dev20/holdout10, position 부여."""
    manifest: list[dict] = []
    position = 0
    for stratum in STRATA:
        selected = final_by_stratum[stratum]
        ordered = sorted(selected, key=lambda c: c.selection_identity_sha256)
        for local_idx, cand in enumerate(ordered):
            split = "dev" if local_idx < DEV_PER_STRATUM else "fresh_holdout"
            row = candidate_to_dict(cand)
            row.update({"split": split, "position": position})
            manifest.append(row)
            position += 1
    return manifest


def build_availability(rows: Sequence[SourceRow]) -> AvailabilityResult:
    # per-clip 분류 분포 (episode dedup 이전) — dedup 흡수 vs 진짜 미분류 구분용
    q = compute_quantiles(rows)
    per_clip = Counter()
    for r in rows:
        per_clip[classify_stratum(r, q) or "unclassified"] += 1

    cands = build_episode_candidates(rows)
    rows_by_id = {r.clip_id: r for r in rows}

    by_stratum: dict[str, list[Candidate]] = defaultdict(list)
    for c in cands:  # build_episode_candidates: STRATA order, ranked best-first within stratum
        by_stratum[c.stratum].append(c)

    strata_av: list[StratumAvailability] = []
    retained_pool: list[Candidate] = []
    final_by_stratum: dict[str, list[Candidate]] = {}

    for stratum in STRATA:
        ranked = by_stratum.get(stratum, [])
        episode_count = len(ranked)
        pool = ranked[:POOL_CAP]
        retained_pool.extend(pool)

        cam_dist = Counter(rows_by_id[c.clip_id].camera_id for c in pool)
        date_dist = Counter(_date(rows_by_id[c.clip_id]) for c in pool)

        blockers: list[str] = []
        if episode_count >= STRATUM_TARGET:
            selection = _round_robin(ranked, rows_by_id, STRATUM_TARGET)
            final_by_stratum[stratum] = selection
            sel_cam = Counter(rows_by_id[c.clip_id].camera_id for c in selection)
            single_ratio = (max(sel_cam.values()) / len(selection)) if selection else 1.0
            if single_ratio > 0.60:
                blockers.append("single_camera_over_60pct")
        else:
            single_ratio = (max(cam_dist.values()) / episode_count) if episode_count else 1.0
            if episode_count > 0:
                blockers.append("below_target_30")
            else:
                blockers.append("no_candidates")

        strata_av.append(
            StratumAvailability(
                stratum=stratum,
                episode_count=episode_count,
                pool_size=len(pool),
                verdict=_stratum_verdict(episode_count),
                camera_distribution=dict(sorted(cam_dist.items())),
                date_distribution=dict(sorted(date_dist.items())),
                single_camera_ratio=round(single_ratio, 4),
                blockers=tuple(blockers),
            )
        )

    camera_count = len({rows_by_id[c.clip_id].camera_id for c in cands})
    date_count = len({_date(rows_by_id[c.clip_id]) for c in cands})
    pool_sha256 = candidates_sha256(retained_pool)

    all_ge_target = all(s.episode_count >= STRATUM_TARGET for s in strata_av)
    diversity_ok = camera_count >= 2 and date_count >= 3 and all(not s.blockers for s in strata_av)
    manifest_emitted = all_ge_target and diversity_ok
    manifest = tuple(_build_manifest(final_by_stratum)) if manifest_emitted else None

    verdict_rank = {DATA_AVAILABLE: 2, DATA_AVAILABLE_LOW_MARGIN: 1, BLOCKED_DATA_INSUFFICIENT: 0}
    overall_verdict = min((s.verdict for s in strata_av), key=lambda v: verdict_rank[v])

    total_episodes = sum(s.episode_count for s in strata_av)
    classified_clips = sum(v for k, v in per_clip.items() if k != "unclassified")
    excluded_counts = {
        # 진짜로 어느 stratum 도 못 받은 clip (stratum None)
        "unclassified_clips": per_clip.get("unclassified", 0),
        # 분류는 됐지만 30분 episode dedup 으로 대표 1개에 흡수된 clip
        "episode_deduped_clips": classified_clips - total_episodes,
    }

    return AvailabilityResult(
        selector_version=SELECTOR_VERSION,
        strata=tuple(strata_av),
        overall_verdict=overall_verdict,
        camera_count=camera_count,
        date_count=date_count,
        pool_sha256=pool_sha256,
        manifest_emitted=manifest_emitted,
        manifest=manifest,
        pool=tuple(retained_pool),
        excluded_counts=excluded_counts,
        per_clip_stratum_distribution=dict(sorted(per_clip.items())),
        total_episodes=total_episodes,
        total_source_rows=len(rows),
    )


# ---------------------------------------------------------------------------
# artifact writers
# ---------------------------------------------------------------------------
def aggregate_payload(result: AvailabilityResult, watermark: str) -> dict:
    """tracked aggregate — counts/분포/selector version/pool SHA/verdict 만. per-clip·r2_key 없음."""
    return {
        "selector_version": result.selector_version,
        "query_watermark": watermark,
        "overall_verdict": result.overall_verdict,
        "camera_count": result.camera_count,
        "date_count": result.date_count,
        "pool_sha256": result.pool_sha256,
        "manifest_emitted": result.manifest_emitted,
        "total_source_rows": result.total_source_rows,
        "total_episodes": result.total_episodes,
        "excluded_counts": result.excluded_counts,
        "per_clip_stratum_distribution": result.per_clip_stratum_distribution,
        "strata": [
            {
                "stratum": s.stratum,
                "episode_count": s.episode_count,
                "pool_size": s.pool_size,
                "verdict": s.verdict,
                "single_camera_ratio": s.single_camera_ratio,
                "camera_distribution": s.camera_distribution,
                "date_distribution": s.date_distribution,
                "blockers": list(s.blockers),
            }
            for s in result.strata
        ],
    }


def pool_payload(result: AvailabilityResult) -> dict:
    """git-ignored per-clip artifact. clip_id·provenance·identity 포함, r2_key/signed URL 없음."""
    return {
        "selector_version": result.selector_version,
        "pool_sha256": result.pool_sha256,
        "manifest_emitted": result.manifest_emitted,
        "pool": [candidate_to_dict(c) for c in result.pool],
        "manifest": list(result.manifest) if result.manifest else None,
    }


def render_report(result: AvailabilityResult, watermark: str) -> str:
    lines = [
        "# Local VLM Evidence 후보 가용성 (B1 SELECT-only)",
        "",
        f"- selector_version: `{result.selector_version}`",
        f"- query_watermark: `{watermark}`",
        f"- overall_verdict: **{result.overall_verdict}**",
        f"- camera_count: {result.camera_count} · date_count: {result.date_count}",
        f"- pool_sha256: `{result.pool_sha256}`",
        f"- manifest_emitted: {result.manifest_emitted}",
        f"- total_source_rows: {result.total_source_rows} → total_episodes: {result.total_episodes}",
        f"- excluded_counts: {result.excluded_counts}",
        f"- per_clip_stratum_distribution: {result.per_clip_stratum_distribution}",
        "",
        "| stratum | episodes | verdict | single-camera% | blockers |",
        "|---|---:|---|---:|---|",
    ]
    for s in result.strata:
        lines.append(
            f"| {s.stratum} | {s.episode_count} | {s.verdict} | "
            f"{s.single_camera_ratio * 100:.1f}% | {', '.join(s.blockers) or '-'} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_csv(result: AvailabilityResult, path: Path) -> None:
    """owner 편의 CSV — clip ID·position·labeling URL 만. signed URL·selection reason 없음."""
    if not result.manifest:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["position", "clip_id", "labeling_url"])
        for row in result.manifest:
            writer.writerow([row["position"], row["clip_id"], f"/labeling/evidence/{row['position']}"])


# ---------------------------------------------------------------------------
# CLI (SELECT-only; write flag 없음)
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local VLM 후보 가용성 SELECT-only probe (read-only)")
    p.add_argument("--aggregate-out", required=True, help="tracked aggregate JSON 경로")
    p.add_argument("--pool-out", required=True, help="git-ignored per-clip pool JSON 경로 (storage/)")
    p.add_argument("--report-out", required=True, help="사람용 verdict markdown 경로")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    from backend.supabase_client import get_supabase_client

    client = get_supabase_client()
    rows = load_sources(client)
    result = build_availability(rows)
    watermark = datetime.now(timezone.utc).isoformat()

    aggregate_path = Path(args.aggregate_out)
    pool_path = Path(args.pool_out)
    report_path = Path(args.report_out)
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
    pool_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    aggregate_path.write_text(
        json.dumps(aggregate_payload(result, watermark), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    pool_path.write_text(
        json.dumps(pool_payload(result), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_report(result, watermark), encoding="utf-8")
    write_csv(result, pool_path.with_suffix(".csv"))

    print(f"[probe] overall_verdict={result.overall_verdict} "
          f"pool_sha256={result.pool_sha256} manifest_emitted={result.manifest_emitted}", file=sys.stderr)
    for s in result.strata:
        print(f"[probe] {s.stratum}: episodes={s.episode_count} verdict={s.verdict}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
