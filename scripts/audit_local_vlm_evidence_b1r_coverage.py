"""Gate B1R Task 1 — 고정 cutoff Python Evidence coverage 감사 (production SELECT-only).

목적: 역사 `motion_clips` 의 active Python Evidence 완주 여부를 **고정 watermark(cutoff)** 기준으로
재현 가능하게 측정한다. cutoff 이하 eligible clip 만 분모로 쓰고, 이후 신규 live clip 은 분모에
넣지 않는다(설계 §5.2). B1 의 기존 audit/probe artifact 는 건드리지 않고 B1R namespace 만 쓴다.

핵심 계약
- production 은 **read-only**. 이 파일에는 `.insert/.update/.delete/.upsert/.rpc` 를 두지 않는다.
- eligible = `duration_sec > 0` 이고 `r2_key` 가 비어있지 않은 `motion_clips` 중 `started_at <= cutoff`.
- 각 eligible clip 은 아래 우선순위로 정확히 한 bucket 에 들어간다(중복 없이 partition):
    1) active run(schema=python-evidence-raw-v1, algo=croi-temporal-v1, level0='ok') 있음 → succeeded
    2) active run 없고 active-identity job 이 `failed_terminal` → allowlisted_terminal
    3) active run 없고 open job(queued/processing/failed_retryable) → 해당 open bucket
    4) active run 도 job 도 없음 → silent_missing
- 완료 등식: eligible == succeeded + terminal AND silent_missing == 0 AND (queued+processing+failed_retryable)==0.
- aggregate 만 Git tracked. clip ID / R2 key / signed URL / raw evidence JSON 은 산출물에 넣지 않는다.

TS/Node 비유: SELECT adapter(=repository) → 순수 partition(=pure service) → renderer(=presenter) →
CLI(=controller). DB 접근은 adapter 에만 있고 partition/closure 는 dict 로 테스트한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

# 스크립트 직접 실행(`uv run python scripts/...`) 시 sys.path[0]=scripts/ 라 `backend` 를 못 찾는다.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path[:0] = [str(_REPO_ROOT)]

# active evidence identity — runtime import 로 실측한 값과 1:1 (RUNTIME-SNAPSHOT.md).
EVIDENCE_SCHEMA_VERSION = "python-evidence-raw-v1"
ALGORITHM_VERSION = "croi-temporal-v1"

_OPEN_STATUSES = ("queued", "processing", "failed_retryable")

COVERAGE_CLOSED = "COVERAGE_CLOSED"
COVERAGE_OPEN = "COVERAGE_OPEN"


class CoverageAuditError(RuntimeError):
    """fail-closed: 시간 파싱 실패, pagination 계약 위반 등."""


@dataclass(frozen=True, slots=True)
class CoverageSnapshot:
    cutoff_started_at: str
    range_start_date: str
    range_end_date: str
    eligible: int
    succeeded_with_active_run: int
    allowlisted_terminal: int
    queued: int
    processing: int
    failed_retryable: int
    silent_missing: int
    terminal_by_code: Mapping[str, int]
    camera_date_counts: Mapping[str, int]


# ---------------------------------------------------------------------------
# 시간/eligibility helpers (순수)
# ---------------------------------------------------------------------------
def _parse_ts(value: object) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:  # 침묵 실패 금지
            raise CoverageAuditError(f"invalid timestamp: {value!r}") from exc
    else:
        raise CoverageAuditError(f"unsupported timestamp type: {type(value)!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _utc_date(value: object) -> str:
    return _parse_ts(value).date().isoformat()


def _is_playable(clip: Mapping) -> bool:
    r2 = clip.get("r2_key")
    if not isinstance(r2, str) or not r2.strip():
        return False
    dur = clip.get("duration_sec")
    try:
        return float(dur) > 0
    except (TypeError, ValueError):
        return False


def _is_active_run(run: Mapping) -> bool:
    return (
        run.get("evidence_schema_version") == EVIDENCE_SCHEMA_VERSION
        and run.get("algorithm_version") == ALGORITHM_VERSION
        and run.get("level0_status") == "ok"
    )


def _is_active_identity(job: Mapping) -> bool:
    return (
        job.get("evidence_schema_version") == EVIDENCE_SCHEMA_VERSION
        and job.get("algorithm_version") == ALGORITHM_VERSION
    )


# ---------------------------------------------------------------------------
# 순수 partition + closure
# ---------------------------------------------------------------------------
def build_snapshot(rows: Sequence[Mapping], jobs: Sequence[Mapping],
                   runs: Sequence[Mapping], cutoff) -> CoverageSnapshot:
    """cutoff 이하 eligible clip 을 succeeded/terminal/open/silent 로 partition."""
    cutoff_dt = _parse_ts(cutoff)

    eligible_rows = [
        r for r in rows
        if _is_playable(r) and r.get("started_at") is not None
        and _parse_ts(r["started_at"]) <= cutoff_dt
    ]
    eligible_ids = {r["id"] for r in eligible_rows}

    # active run 을 가진 clip (eligible 로 한정 — 미래 clip run 은 분모에 넣지 않음).
    active_run_ids = {
        run["clip_id"] for run in runs
        if run.get("clip_id") in eligible_ids and _is_active_run(run)
    }

    # active identity job 을 clip 단위로 (unique(clip,schema,algo) 라 clip 당 최대 1개).
    job_by_clip: dict[str, Mapping] = {}
    for j in jobs:
        cid = j.get("clip_id")
        if cid in eligible_ids and _is_active_identity(j):
            job_by_clip[cid] = j

    succeeded = 0
    terminal = 0
    open_counts = {"queued": 0, "processing": 0, "failed_retryable": 0}
    silent = 0
    terminal_by_code: Counter = Counter()

    for cid in eligible_ids:
        if cid in active_run_ids:
            succeeded += 1
            continue
        j = job_by_clip.get(cid)
        if j is None:
            silent += 1
            continue
        status = j.get("status")
        if status == "failed_terminal":
            terminal += 1
            terminal_by_code[j.get("failure_code") or "unknown"] += 1
        elif status in open_counts:
            open_counts[status] += 1
        else:
            # succeeded 상태인데 active run 이 없음(정상 데이터에선 없음) 또는 미지 status.
            # fail-closed: accounted 로 세지 않고 재시도 필요로 취급해 closure 를 OPEN 으로 유지.
            open_counts["failed_retryable"] += 1

    dates = sorted(_utc_date(r["started_at"]) for r in eligible_rows)
    cam_date: Counter = Counter()
    for r in eligible_rows:
        cam_date[f"{r['camera_id']}|{_utc_date(r['started_at'])}"] += 1

    return CoverageSnapshot(
        cutoff_started_at=cutoff_dt.isoformat(),
        range_start_date=(dates[0] if dates else ""),
        range_end_date=(dates[-1] if dates else ""),
        eligible=len(eligible_ids),
        succeeded_with_active_run=succeeded,
        allowlisted_terminal=terminal,
        queued=open_counts["queued"],
        processing=open_counts["processing"],
        failed_retryable=open_counts["failed_retryable"],
        silent_missing=silent,
        terminal_by_code=dict(sorted(terminal_by_code.items())),
        camera_date_counts=dict(sorted(cam_date.items())),
    )


def evaluate_coverage_closure(s: CoverageSnapshot) -> str:
    accounted = s.succeeded_with_active_run + s.allowlisted_terminal
    open_jobs = s.queued + s.processing + s.failed_retryable
    if accounted == s.eligible and s.silent_missing == 0 and open_jobs == 0:
        return COVERAGE_CLOSED
    return COVERAGE_OPEN


# ---------------------------------------------------------------------------
# SELECT-only adapters (production READ)
# ---------------------------------------------------------------------------
def _resp_data(resp) -> list:
    data = getattr(resp, "data", None)
    if data is None and isinstance(resp, dict):
        data = resp.get("data")
    return data or []


def _paginate(client, table: str, columns: str, *, order_column: str = "id",
              page_size: int = 1000, filters=None) -> list[dict]:
    """명시적 range pagination — Supabase 기본 1000행 상한을 넘겨 전량 조회. builder 는 매 페이지 새로 만든다."""
    rows: list[dict] = []
    offset = 0
    while True:
        query = client.table(table).select(columns)
        for method, col, val in filters or ():
            query = getattr(query, method)(col, val)
        query = query.order(order_column).range(offset, offset + page_size - 1)
        data = _resp_data(query.execute())
        rows.extend(data)
        if len(data) < page_size:
            break
        offset += page_size
    return rows


def load_motion_clips(client, cutoff) -> list[dict]:
    cutoff_dt = _parse_ts(cutoff)
    return _paginate(
        client, "motion_clips", "id,camera_id,started_at,duration_sec,r2_key",
        order_column="id",
        filters=[("lte", "started_at", cutoff_dt.isoformat()), ("gt", "duration_sec", 0)],
    )


def load_active_jobs(client) -> list[dict]:
    return _paginate(
        client, "python_evidence_jobs",
        "clip_id,status,failure_code,evidence_schema_version,algorithm_version",
        order_column="clip_id",
        filters=[
            ("eq", "evidence_schema_version", EVIDENCE_SCHEMA_VERSION),
            ("eq", "algorithm_version", ALGORITHM_VERSION),
        ],
    )


def load_active_runs(client) -> list[dict]:
    return _paginate(
        client, "clip_python_evidence_runs",
        "clip_id,evidence_schema_version,algorithm_version,level0_status",
        order_column="clip_id",
        filters=[
            ("eq", "evidence_schema_version", EVIDENCE_SCHEMA_VERSION),
            ("eq", "algorithm_version", ALGORITHM_VERSION),
            ("eq", "level0_status", "ok"),
        ],
    )


# ---------------------------------------------------------------------------
# artifact writers
# ---------------------------------------------------------------------------
def aggregate_payload(snap: CoverageSnapshot, verdict: str, watermark: str) -> dict:
    return {
        "coverage_verdict": verdict,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "query_watermark": watermark,
        "cutoff_started_at": snap.cutoff_started_at,
        "range_start_date": snap.range_start_date,
        "range_end_date": snap.range_end_date,
        "eligible": snap.eligible,
        "succeeded_with_active_run": snap.succeeded_with_active_run,
        "allowlisted_terminal": snap.allowlisted_terminal,
        "queued": snap.queued,
        "processing": snap.processing,
        "failed_retryable": snap.failed_retryable,
        "silent_missing": snap.silent_missing,
        "terminal_by_code": dict(snap.terminal_by_code),
        "camera_date_counts": dict(snap.camera_date_counts),
    }


def render_report(snap: CoverageSnapshot, verdict: str, watermark: str) -> str:
    open_jobs = snap.queued + snap.processing + snap.failed_retryable
    accounted = snap.succeeded_with_active_run + snap.allowlisted_terminal
    cameras = len({key.split("|", 1)[0] for key in snap.camera_date_counts})
    dates = len({key.split("|", 1)[1] for key in snap.camera_date_counts})
    lines = [
        "# B1R Python Evidence Coverage (SELECT-only)",
        "",
        f"- coverage_verdict: **{verdict}**",
        f"- evidence identity: `{EVIDENCE_SCHEMA_VERSION}` / `{ALGORITHM_VERSION}`",
        f"- cutoff_started_at: `{snap.cutoff_started_at}`",
        f"- query_watermark: `{watermark}`",
        f"- range: {snap.range_start_date} .. {snap.range_end_date}",
        "",
        "## 완료 등식",
        "",
        "```text",
        f"eligible                    = {snap.eligible}",
        f"succeeded_with_active_run   = {snap.succeeded_with_active_run}",
        f"allowlisted_terminal        = {snap.allowlisted_terminal}",
        f"accounted (succ+terminal)   = {accounted}",
        f"queued/processing/retryable = {snap.queued}/{snap.processing}/{snap.failed_retryable} (open={open_jobs})",
        f"silent_missing              = {snap.silent_missing}",
        "```",
        "",
        f"- eligible == succeeded + terminal ? **{snap.eligible == accounted}**",
        f"- silent_missing == 0 ? **{snap.silent_missing == 0}** · open == 0 ? **{open_jobs == 0}**",
        f"- terminal_by_code: {dict(snap.terminal_by_code) or '-'}",
        f"- camera 수: {cameras} · date 수: {dates}",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI (SELECT-only)
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="B1R 고정 cutoff Python Evidence coverage 감사 (read-only)")
    p.add_argument("--cutoff-started-at", required=True, help="이 시각 이하 clip 만 분모(ISO-8601)")
    p.add_argument("--json-out", required=True, help="tracked aggregate JSON 경로")
    p.add_argument("--report-out", required=True, help="사람용 markdown 경로")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    from backend.supabase_client import get_supabase_client

    client = get_supabase_client()
    cutoff = args.cutoff_started_at
    rows = load_motion_clips(client, cutoff)
    jobs = load_active_jobs(client)
    runs = load_active_runs(client)

    snap = build_snapshot(rows, jobs, runs, cutoff)
    verdict = evaluate_coverage_closure(snap)
    watermark = datetime.now(timezone.utc).isoformat()

    json_path = Path(args.json_out)
    report_path = Path(args.report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(
        json.dumps(aggregate_payload(snap, verdict, watermark), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_report(snap, verdict, watermark), encoding="utf-8")

    print(f"[b1r-coverage] coverage_verdict={verdict} eligible={snap.eligible} "
          f"succeeded={snap.succeeded_with_active_run} terminal={snap.allowlisted_terminal} "
          f"open={snap.queued + snap.processing + snap.failed_retryable} "
          f"silent_missing={snap.silent_missing}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
