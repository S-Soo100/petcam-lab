"""Gate B1R2 Task 1/2 — R2 media availability 감사 (production SELECT + R2 list read-only).

목적: 역사 `motion_clips` 중 **R2 object 가 실제로 남아 있는** clip 만 복구 대상으로 삼고, 삭제된
원본은 `source_expired` 로 정직하게 분리한다. B1R 의 `eligible` 은 DB `r2_key` 존재만 봐서 소실분을
과대계상했다(보고서 §4). B1R2 는 날짜를 추정하지 않고 bucket inventory 를 직접 읽어 존재 여부를 고정한다.

핵심 계약 (design §3~5)
- production 은 **read-only**. `.insert/.update/.delete/.upsert/.rpc`, R2 `put/delete/copy` 를 두지 않는다.
- study_total = `duration_sec > 0` 이고 `r2_key` 가 비어있지 않은 `motion_clips` 중 `started_at <= cutoff`.
- 각 clip 은 아래 우선순위로 정확히 한 상태(design §4):
    1) evidence_succeeded — active identity run(level0='ok'). **R2 현재 존재 여부 무관.**
    2) (run 없음) R2 object 없음 → source_expired. DB key 남아 있어도 복구 불가.
    3) (run 없음, R2 존재) open job(queued/processing/failed_retryable) → media_available_open
    4) (run 없음, R2 존재) failed_terminal job → media_available_terminal
    5) (run 없음, R2 존재) job 없음 → media_available_silent
- 등식: study_total = succeeded + open + silent + terminal + source_expired.
- recoverable_total = study_total − source_expired. recoverable_coverage_closed ⇔ open==0 ∧ silent==0.
- tracked aggregate 에는 상태별 수량·camera/date 분포·available/expired 비율·SHA 만. clip_id/R2 key/URL 금지.
- private JSONL 에는 clip_id,camera_id,started_at,source_date,status 만. R2 key 는 어디에도 복제 안 함.

TS/Node 비유: R2 list = 외부 object store 스캔(=repository) → 순수 partition(=service) → aggregate/manifest
writer(=presenter) → CLI(=controller). key 는 in-memory 실행 시점에만 있고 산출물엔 남기지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

# 스크립트 직접 실행 시 sys.path[0]=scripts/ 라 `backend` 를 못 찾는다.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path[:0] = [str(_REPO_ROOT)]

# active evidence identity — RUNTIME-SNAPSHOT.md 실측값과 1:1.
EVIDENCE_SCHEMA_VERSION = "python-evidence-raw-v1"
ALGORITHM_VERSION = "croi-temporal-v1"

_OPEN_STATUSES = ("queued", "processing", "failed_retryable")

_STATUSES = (
    "evidence_succeeded",
    "media_available_open",
    "media_available_silent",
    "media_available_terminal",
    "source_expired",
)
# HEAD 표본이 "R2 present" 라고 판정해야 하는 상태 (inventory 존재 확정 상태).
_R2_PRESENT_STATUSES = frozenset(
    {"media_available_open", "media_available_silent", "media_available_terminal"}
)


class MediaAuditError(RuntimeError):
    """fail-closed: pagination 중간 오류, HEAD 403/5xx, 시간 파싱 실패 등."""


@dataclass(frozen=True, slots=True)
class MediaCoverageRow:
    clip_id: str
    camera_id: str
    started_at: str
    source_date: str
    status: str


@dataclass(frozen=True, slots=True)
class MediaCoverageSnapshot:
    cutoff_started_at: str
    study_total: int
    evidence_succeeded: int
    media_available_open: int
    media_available_silent: int
    media_available_terminal: int
    source_expired: int
    camera_date_status_counts: Mapping[str, int]
    availability_sha256: str


# ---------------------------------------------------------------------------
# 순수 helpers
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
        except ValueError as exc:
            raise MediaAuditError(f"invalid timestamp: {value!r}") from exc
    else:
        raise MediaAuditError(f"unsupported timestamp type: {type(value)!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _utc_iso(value: object) -> str:
    return _parse_ts(value).isoformat()


def _utc_date(value: object) -> str:
    return _parse_ts(value).date().isoformat()


def _is_playable(clip: Mapping) -> bool:
    r2 = clip.get("r2_key")
    if not isinstance(r2, str) or not r2.strip():
        return False
    try:
        return float(clip.get("duration_sec")) > 0
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
# R2 inventory (list_objects_v2 paginator, read-only)
# ---------------------------------------------------------------------------
def scan_available_mp4(client, bucket: str, prefix: str):
    """paginator 전량을 읽고 `.mp4` 이며 size>0 인 key set + 통계를 반환.

    중간 오류/truncation 계약 위반은 partial 을 반환하지 않고 MediaAuditError(fail-closed).
    """
    keys: set[str] = set()
    object_count = 0
    total_bytes = 0
    page_count = 0
    paginator = client.get_paginator("list_objects_v2")
    try:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            page_count += 1
            for obj in page.get("Contents", []) or []:
                object_count += 1
                key = obj.get("Key", "")
                size = obj.get("Size")
                if isinstance(size, (int, float)):
                    total_bytes += int(size)
                if (
                    isinstance(key, str)
                    and key.endswith(".mp4")
                    and isinstance(size, (int, float))
                    and size > 0
                ):
                    keys.add(key)
    except MediaAuditError:
        raise
    except Exception as exc:  # 침묵 실패 금지: partial 반환 대신 fail-closed
        raise MediaAuditError(f"inventory_failed: {type(exc).__name__}") from exc
    return keys, object_count, len(keys), total_bytes, page_count


def list_available_mp4_keys(client, bucket: str, prefix: str) -> set[str]:
    """available (.mp4 ∧ size>0) key set 만 반환 (thin wrapper)."""
    return scan_available_mp4(client, bucket, prefix)[0]


# ---------------------------------------------------------------------------
# 순수 partition
# ---------------------------------------------------------------------------
def _classify(clip_id: str, r2_key: str, active_run_ids: set,
              job: Mapping | None, available_keys: set) -> str:
    if clip_id in active_run_ids:
        return "evidence_succeeded"
    if r2_key not in available_keys:
        # DB key 는 남아 있어도 R2 object 부재 = 복구 불가. open job 이 있어도 우선.
        return "source_expired"
    if job is None:
        return "media_available_silent"
    if job.get("status") == "failed_terminal":
        return "media_available_terminal"
    # queued/processing/failed_retryable, 그 외 비-terminal 이상상태 → open (fail-closed, closure OPEN 유지)
    return "media_available_open"


def availability_sha256(rows: Sequence[MediaCoverageRow]) -> str:
    payload = "\n".join(
        f"{r.clip_id}\t{r.status}" for r in sorted(rows, key=lambda x: x.clip_id)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def partition_media_coverage(clips: Sequence[Mapping], runs: Sequence[Mapping] = (),
                             jobs: Sequence[Mapping] = (), available_keys=frozenset(),
                             *, cutoff=None):
    """study_total clip 을 5 상태로 partition. (snapshot, rows) 반환. clips 는 이미 로드된 dict."""
    cutoff_dt = _parse_ts(cutoff) if cutoff is not None else None
    available = set(available_keys)

    eligible = []
    for c in clips:
        if not _is_playable(c) or c.get("started_at") is None:
            continue
        if cutoff_dt is not None and _parse_ts(c["started_at"]) > cutoff_dt:
            continue
        eligible.append(c)
    eligible_ids = {c["id"] for c in eligible}

    active_run_ids = {
        r["clip_id"] for r in runs
        if r.get("clip_id") in eligible_ids and _is_active_run(r)
    }
    job_by_clip: dict[str, Mapping] = {}
    for j in jobs:
        cid = j.get("clip_id")
        if cid in eligible_ids and _is_active_identity(j):
            job_by_clip[cid] = j

    rows: list[MediaCoverageRow] = []
    for c in sorted(eligible, key=lambda x: x["id"]):
        cid = c["id"]
        status = _classify(cid, c["r2_key"], active_run_ids, job_by_clip.get(cid), available)
        rows.append(MediaCoverageRow(
            clip_id=cid,
            camera_id=c["camera_id"],
            started_at=_utc_iso(c["started_at"]),
            source_date=_utc_date(c["started_at"]),
            status=status,
        ))

    counts = Counter(r.status for r in rows)
    cam_date: Counter = Counter()
    for r in rows:
        cam_date[f"{r.camera_id}|{r.source_date}|{r.status}"] += 1

    snap = MediaCoverageSnapshot(
        cutoff_started_at=(cutoff_dt.isoformat() if cutoff_dt else ""),
        study_total=len(rows),
        evidence_succeeded=counts.get("evidence_succeeded", 0),
        media_available_open=counts.get("media_available_open", 0),
        media_available_silent=counts.get("media_available_silent", 0),
        media_available_terminal=counts.get("media_available_terminal", 0),
        source_expired=counts.get("source_expired", 0),
        camera_date_status_counts=dict(sorted(cam_date.items())),
        availability_sha256=availability_sha256(rows),
    )
    return snap, rows


def select_canary(rows: Sequence[MediaCoverageRow], *, limit: int = 30) -> list[MediaCoverageRow]:
    """media_available_silent 에서 (camera_id, source_date) round-robin 으로 결정론적 canary 선택.

    design §7: 오래된 순으로만 뽑지 않는다. bucket 순서·bucket 내부(started_at,clip_id) 정렬이 고정이라
    입력 순서와 무관하게 같은 결과. pool 이 limit 미만이면 확대하지 않고 있는 만큼만(성공처럼 위장 금지).
    """
    silent = [r for r in rows if r.status == "media_available_silent"]
    buckets: dict[tuple, list[MediaCoverageRow]] = {}
    for r in silent:
        buckets.setdefault((r.camera_id, r.source_date), []).append(r)
    for key in buckets:
        buckets[key].sort(key=lambda r: (r.started_at, r.clip_id))
    ordered_keys = sorted(buckets)
    cursors = {k: 0 for k in ordered_keys}
    picked: list[MediaCoverageRow] = []
    while len(picked) < limit:
        progressed = False
        for k in ordered_keys:
            if len(picked) >= limit:
                break
            c = cursors[k]
            if c < len(buckets[k]):
                picked.append(buckets[k][c])
                cursors[k] = c + 1
                progressed = True
        if not progressed:
            break  # pool 소진 — 확대하지 않는다
    return picked


def recoverable_total(snap: MediaCoverageSnapshot) -> int:
    return snap.study_total - snap.source_expired


def recoverable_coverage_closed(snap: MediaCoverageSnapshot) -> bool:
    return snap.media_available_open == 0 and snap.media_available_silent == 0


# ---------------------------------------------------------------------------
# bounded HEAD 표본 검증 (design §5.3) — inventory 판정 vs 실제 HEAD 일치 확인
# ---------------------------------------------------------------------------
def _head_present(client, bucket: str, key: str) -> bool:
    """HEAD 성공→present, 404/NoSuchKey→absent, 403/5xx/timeout→MediaAuditError. key 는 노출 안 함."""
    from backend.r2_uploader import ClientError

    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code in ("404", "NoSuchKey", "NotFound") or status == 404:
            return False
        raise MediaAuditError(f"head_failed code={code} status={status}") from exc


def bounded_head_verify(client, bucket: str, rows: Sequence[MediaCoverageRow],
                        key_by_clip: Mapping[str, str], *, per_bucket: int = 6) -> dict:
    """camera/date 별 available/expired 표본 HEAD 로 inventory 판정을 교차확인. key 는 출력 안 함."""
    def _sample(status_pred):
        buckets: dict[tuple, list[MediaCoverageRow]] = {}
        for r in rows:
            if status_pred(r.status):
                buckets.setdefault((r.camera_id, r.source_date), []).append(r)
        picked: list[MediaCoverageRow] = []
        for bkey in sorted(buckets):
            group = sorted(buckets[bkey], key=lambda x: (x.started_at, x.clip_id))
            picked.extend(group[:per_bucket])
        return picked

    result = {
        "available_checked": 0, "available_present": 0, "available_mismatch": 0,
        "expired_checked": 0, "expired_absent": 0, "expired_mismatch": 0,
    }
    for r in _sample(lambda s: s in _R2_PRESENT_STATUSES):
        key = key_by_clip.get(r.clip_id)
        if key is None:
            raise MediaAuditError("head_sample_missing_key")
        result["available_checked"] += 1
        if _head_present(client, bucket, key):
            result["available_present"] += 1
        else:
            result["available_mismatch"] += 1
    for r in _sample(lambda s: s == "source_expired"):
        key = key_by_clip.get(r.clip_id)
        if key is None:
            raise MediaAuditError("head_sample_missing_key")
        result["expired_checked"] += 1
        if _head_present(client, bucket, key):
            result["expired_mismatch"] += 1
        else:
            result["expired_absent"] += 1
    result["mismatch_total"] = result["available_mismatch"] + result["expired_mismatch"]
    return result


# ---------------------------------------------------------------------------
# SELECT-only adapters (production READ) — B1R coverage audit 와 동일 패턴
# ---------------------------------------------------------------------------
def _resp_data(resp) -> list:
    data = getattr(resp, "data", None)
    if data is None and isinstance(resp, dict):
        data = resp.get("data")
    return data or []


def _paginate(client, table: str, columns: str, *, order_column: str = "id",
              page_size: int = 1000, filters=None) -> list[dict]:
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
def aggregate_payload(snap: MediaCoverageSnapshot, *, prefix: str, inventory: dict,
                      query_watermark: str, head: dict | None) -> dict:
    return {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "cutoff_started_at": snap.cutoff_started_at,
        "r2_prefix": prefix,
        "study_total": snap.study_total,
        "evidence_succeeded": snap.evidence_succeeded,
        "media_available_open": snap.media_available_open,
        "media_available_silent": snap.media_available_silent,
        "media_available_terminal": snap.media_available_terminal,
        "source_expired": snap.source_expired,
        "recoverable_total": recoverable_total(snap),
        "recoverable_coverage_closed": recoverable_coverage_closed(snap),
        "partition_equation_holds": snap.study_total == (
            snap.evidence_succeeded + snap.media_available_open
            + snap.media_available_silent + snap.media_available_terminal
            + snap.source_expired
        ),
        "availability_sha256": snap.availability_sha256,
        "camera_date_status_counts": dict(snap.camera_date_status_counts),
        "r2_inventory": inventory,
        "query_watermark": query_watermark,
        "head_sample": head,
    }


def write_private_manifest(rows: Sequence[MediaCoverageRow], path: Path) -> None:
    """gitignored JSONL. clip_id,camera_id,started_at,source_date,status 만. R2 key 없음."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for r in sorted(rows, key=lambda x: x.clip_id):
        lines.append(json.dumps({
            "clip_id": r.clip_id,
            "camera_id": r.camera_id,
            "started_at": r.started_at,
            "source_date": r.source_date,
            "status": r.status,
        }, ensure_ascii=False, sort_keys=True))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def render_report(snap: MediaCoverageSnapshot, *, prefix: str, inventory: dict,
                  head: dict | None) -> str:
    eq = snap.study_total == (
        snap.evidence_succeeded + snap.media_available_open + snap.media_available_silent
        + snap.media_available_terminal + snap.source_expired
    )
    # camera/date 별 available vs expired 요약 (available = R2 present 3상태).
    per_cd_avail: Counter = Counter()
    per_cd_expired: Counter = Counter()
    for key, n in snap.camera_date_status_counts.items():
        cam, date, status = key.split("|", 2)
        if status in _R2_PRESENT_STATUSES:
            per_cd_avail[f"{cam}|{date}"] += n
        elif status == "source_expired":
            per_cd_expired[f"{cam}|{date}"] += n
    cd_lines = []
    for cd in sorted(set(per_cd_avail) | set(per_cd_expired)):
        cd_lines.append(f"| {cd} | {per_cd_avail.get(cd, 0)} | {per_cd_expired.get(cd, 0)} |")

    lines = [
        "# B1R2 R2 Media Availability (SELECT + R2 list, read-only)",
        "",
        f"- evidence identity: `{EVIDENCE_SCHEMA_VERSION}` / `{ALGORITHM_VERSION}`",
        f"- cutoff_started_at: `{snap.cutoff_started_at}`",
        f"- r2_prefix: `{prefix}`",
        "",
        "## study_total 5-상태 partition",
        "",
        "```text",
        f"study_total            = {snap.study_total}",
        f"evidence_succeeded     = {snap.evidence_succeeded}",
        f"media_available_open   = {snap.media_available_open}",
        f"media_available_silent = {snap.media_available_silent}",
        f"media_available_terminal = {snap.media_available_terminal}",
        f"source_expired         = {snap.source_expired}",
        "```",
        "",
        f"- 합계 등식 성립 ? **{eq}**",
        f"- recoverable_total (study−expired) = {recoverable_total(snap)}",
        f"- recoverable_coverage_closed (open==0 ∧ silent==0) ? **{recoverable_coverage_closed(snap)}**",
        f"- availability_sha256: `{snap.availability_sha256}`",
        "",
        "## R2 inventory",
        "",
        "```text",
        f"prefix        = {prefix}",
        f"object_count  = {inventory.get('object_count')}",
        f"mp4_available = {inventory.get('mp4_available')}",
        f"total_bytes   = {inventory.get('total_bytes')}",
        f"page_count    = {inventory.get('page_count')}",
        f"started_at    = {inventory.get('started_at')}",
        f"finished_at   = {inventory.get('finished_at')}",
        "```",
        "",
        "## camera/date 별 available vs source_expired",
        "",
        "| camera|date | available | source_expired |",
        "|---|---:|---:|",
        *cd_lines,
        "",
    ]
    if head is not None:
        lines += [
            "## bounded HEAD 표본 (inventory 교차확인)",
            "",
            "```text",
            f"available: checked={head['available_checked']} present={head['available_present']} mismatch={head['available_mismatch']}",
            f"expired:   checked={head['expired_checked']} absent={head['expired_absent']} mismatch={head['expired_mismatch']}",
            f"mismatch_total = {head['mismatch_total']}",
            "```",
            "",
        ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI (SELECT + R2 list read-only)
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="B1R2 R2 media availability 감사 (read-only)")
    p.add_argument("--cutoff-started-at", required=True, help="이 시각 이하 clip 만 분모(ISO-8601)")
    p.add_argument("--aggregate-out", required=True, help="tracked aggregate JSON")
    p.add_argument("--private-manifest-out", required=True, help="gitignored per-clip JSONL")
    p.add_argument("--report-out", required=True, help="사람용 markdown")
    # production r2_key 실측(2026-07-22): 16797/16797 clip 이 `terra-clips/clips/…`. 가정 금지, 검증값 사용.
    p.add_argument("--prefix", default="terra-clips/clips/", help="R2 production clip prefix")
    p.add_argument("--head-sample-per-bucket", type=int, default=6, help="camera/date 당 HEAD 표본 수")
    p.add_argument("--skip-head", action="store_true", help="HEAD 표본 검증 생략 (pure list only)")
    p.add_argument("--canary-out", default=None, help="canary private JSONL 경로(미지정 시 생성 안 함)")
    p.add_argument("--canary-limit", type=int, default=30, help="canary 수(design §7 = 30)")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    from backend.r2_uploader import get_r2_bucket, get_r2_client
    from backend.supabase_client import get_supabase_client

    sb = get_supabase_client()
    r2 = get_r2_client()
    bucket = get_r2_bucket()

    inv_start = datetime.now(timezone.utc)
    keys, object_count, mp4_available, total_bytes, page_count = scan_available_mp4(
        r2, bucket, args.prefix
    )
    inv_end = datetime.now(timezone.utc)
    inventory = {
        "object_count": object_count,
        "mp4_available": mp4_available,
        "total_bytes": total_bytes,
        "page_count": page_count,
        "started_at": inv_start.isoformat(),
        "finished_at": inv_end.isoformat(),
    }

    clips = load_motion_clips(sb, args.cutoff_started_at)
    jobs = load_active_jobs(sb)
    runs = load_active_runs(sb)
    query_watermark = datetime.now(timezone.utc).isoformat()

    snap, rows = partition_media_coverage(clips, runs, jobs, keys, cutoff=args.cutoff_started_at)

    # in-memory clip 의 r2_key — HEAD 조회에만 쓰고 산출물엔 남기지 않는다(design §5.2).
    key_by_clip = {c["id"]: c["r2_key"] for c in clips if _is_playable(c)}

    # bounded HEAD 표본 (available/expired vs inventory 교차확인).
    head = None
    if not args.skip_head:
        head = bounded_head_verify(r2, bucket, rows, key_by_clip,
                                   per_bucket=args.head_sample_per_bucket)

    agg_path = Path(args.aggregate_out)
    man_path = Path(args.private_manifest_out)
    rep_path = Path(args.report_out)
    agg_path.parent.mkdir(parents=True, exist_ok=True)
    rep_path.parent.mkdir(parents=True, exist_ok=True)

    agg_path.write_text(
        json.dumps(aggregate_payload(snap, prefix=args.prefix, inventory=inventory,
                                     query_watermark=query_watermark, head=head),
                   indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_private_manifest(rows, man_path)
    rep_path.write_text(render_report(snap, prefix=args.prefix, inventory=inventory, head=head),
                        encoding="utf-8")

    # canary manifest (private JSONL) — media_available_silent 에서 결정론적 round-robin 선택.
    canary_msg = "canary=off"
    if args.canary_out:
        canary = select_canary(rows, limit=args.canary_limit)
        # design §7.4: 선택 직전 bounded HEAD 로 canary object 가 여전히 존재하는지 재확인.
        canary_head_present = canary_head_absent = 0
        if not args.skip_head:
            for r in canary:
                key = key_by_clip.get(r.clip_id)
                if key is None:
                    raise MediaAuditError("canary_missing_key")
                if _head_present(r2, bucket, key):
                    canary_head_present += 1
                else:
                    canary_head_absent += 1
        write_private_manifest(canary, Path(args.canary_out))
        canary_sha = availability_sha256(canary)
        canary_cameras = len({r.camera_id for r in canary})
        canary_dates = len({r.source_date for r in canary})
        canary_msg = (
            f"canary_selected={len(canary)} canary_cameras={canary_cameras} "
            f"canary_dates={canary_dates} canary_head_present={canary_head_present}/{len(canary)} "
            f"canary_head_absent={canary_head_absent} canary_sha={canary_sha}"
        )

    eq = snap.study_total == (
        snap.evidence_succeeded + snap.media_available_open + snap.media_available_silent
        + snap.media_available_terminal + snap.source_expired
    )
    head_ok = head is None or head["mismatch_total"] == 0
    verdict = "B1R2_MEDIA_AUDIT_INVENTORY_OK" if (eq and head_ok) else "B1R2_BLOCKED_INVENTORY_INTEGRITY"
    head_msg = (
        f"head_avail={head['available_present']}/{head['available_checked']} "
        f"head_expired404={head['expired_absent']}/{head['expired_checked']} "
        f"head_mismatch={head['mismatch_total']}"
        if head is not None else "head=skipped"
    )
    print(
        f"[b1r2-media] {verdict} study_total={snap.study_total} "
        f"succeeded={snap.evidence_succeeded} open={snap.media_available_open} "
        f"silent={snap.media_available_silent} terminal={snap.media_available_terminal} "
        f"source_expired={snap.source_expired} "
        f"recoverable_closed={recoverable_coverage_closed(snap)} "
        f"mp4_available={mp4_available} objects={object_count} pages={page_count} "
        f"sha={snap.availability_sha256[:12]} {head_msg} {canary_msg}",
        file=sys.stderr,
    )
    return 0 if (eq and head_ok) else 2


if __name__ == "__main__":
    raise SystemExit(main())
