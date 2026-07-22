"""Gate B1R Task 1 — fixed-cutoff Python Evidence coverage 감사 (순수 로직 테스트).

DB 를 건드리지 않는다. `scripts/audit_local_vlm_evidence_b1r_coverage.py` 의
- 고정 cutoff eligibility (started_at <= cutoff, playable),
- eligible clip 을 succeeded/terminal/open/silent 로 나누는 partition,
- coverage closure 등식
만 검증한다 (설계 §5.2, §6 완료 등식).

RED 단계: 아직 모듈이 없으므로 import 실패로 떨어진다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from scripts.audit_local_vlm_evidence_b1r_coverage import (
    ALGORITHM_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    CoverageSnapshot,
    build_snapshot,
    evaluate_coverage_closure,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


FAR_FUTURE = ts("2099-01-01T00:00:00Z")


def clip(clip_id: str, started_at: str = "2026-07-22T00:00:00Z", **over) -> dict:
    base = {
        "id": clip_id,
        "camera_id": "cam",
        "started_at": started_at,
        "duration_sec": 60.0,
        "r2_key": f"clips/{clip_id}.mp4",
    }
    base.update(over)
    return base


def ok_run(clip_id: str, **over) -> dict:
    base = {
        "clip_id": clip_id,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "level0_status": "ok",
    }
    base.update(over)
    return base


def job(clip_id: str, status: str, failure_code=None, **over) -> dict:
    base = {
        "clip_id": clip_id,
        "status": status,
        "failure_code": failure_code,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
    }
    base.update(over)
    return base


def terminal_job(clip_id: str, failure_code: str = "decode_no_frames") -> dict:
    return job(clip_id, "failed_terminal", failure_code=failure_code)


def snapshot(*, eligible: int, succeeded: int = 0, terminal: int = 0,
             queued: int = 0, processing: int = 0, failed_retryable: int = 0,
             silent: int = 0) -> CoverageSnapshot:
    return CoverageSnapshot(
        cutoff_started_at="2026-07-22T00:00:00+00:00",
        range_start_date="2026-07-22",
        range_end_date="2026-07-22",
        eligible=eligible,
        succeeded_with_active_run=succeeded,
        allowlisted_terminal=terminal,
        queued=queued,
        processing=processing,
        failed_retryable=failed_retryable,
        silent_missing=silent,
        terminal_by_code={},
        camera_date_counts={},
    )


# ---------------------------------------------------------------------------
# plan Step 1 RED tests
# ---------------------------------------------------------------------------
def test_cutoff_excludes_new_live_clip():
    rows = [clip("old", "2026-07-22T00:00:00Z"), clip("new", "2026-07-22T00:00:01Z")]
    snap = build_snapshot(rows, jobs=[], runs=[], cutoff=ts("2026-07-22T00:00:00Z"))
    assert snap.eligible == 1
    assert snap.silent_missing == 1


def test_closure_requires_no_open_or_silent_missing():
    assert evaluate_coverage_closure(snapshot(eligible=2, succeeded=1, terminal=1)) == "COVERAGE_CLOSED"
    assert evaluate_coverage_closure(snapshot(eligible=2, succeeded=1, terminal=0, silent=1)) == "COVERAGE_OPEN"
    assert evaluate_coverage_closure(snapshot(eligible=2, succeeded=1, terminal=0, queued=1)) == "COVERAGE_OPEN"


def test_terminal_is_not_counted_as_success():
    snap = build_snapshot([clip("a"), clip("b")], [terminal_job("b")], [ok_run("a")], cutoff=FAR_FUTURE)
    assert snap.succeeded_with_active_run == 1
    assert snap.allowlisted_terminal == 1


# ---------------------------------------------------------------------------
# 추가 계약 — partition 완전성 / eligibility / active identity
# ---------------------------------------------------------------------------
def test_partition_sums_to_eligible():
    rows = [clip(c) for c in ("run1", "term1", "q1", "p1", "fr1", "sil1")]
    jobs = [
        terminal_job("term1"),
        job("q1", "queued"),
        job("p1", "processing"),
        job("fr1", "failed_retryable"),
    ]
    runs = [ok_run("run1")]
    snap = build_snapshot(rows, jobs, runs, cutoff=FAR_FUTURE)
    assert snap.eligible == 6
    total = (snap.succeeded_with_active_run + snap.allowlisted_terminal
             + snap.queued + snap.processing + snap.failed_retryable + snap.silent_missing)
    assert total == snap.eligible
    assert (snap.queued, snap.processing, snap.failed_retryable) == (1, 1, 1)
    assert snap.silent_missing == 1
    assert snap.terminal_by_code == {"decode_no_frames": 1}


def test_ineligible_when_no_r2_key_or_zero_duration():
    rows = [
        clip("noR2", r2_key=""),
        clip("nullR2", r2_key=None),
        clip("zeroDur", duration_sec=0),
        clip("good"),
    ]
    snap = build_snapshot(rows, jobs=[], runs=[], cutoff=FAR_FUTURE)
    assert snap.eligible == 1  # only "good"
    assert snap.silent_missing == 1


def test_nonmatching_run_identity_is_not_active():
    rows = [clip("a"), clip("b")]
    runs = [
        ok_run("a", algorithm_version="croi-temporal-v0"),  # wrong algo → not active
        ok_run("b", level0_status="no_decodable_frames"),   # not ok → not active
    ]
    snap = build_snapshot(rows, [], runs, cutoff=FAR_FUTURE)
    assert snap.succeeded_with_active_run == 0
    assert snap.silent_missing == 2


def test_active_run_only_counts_within_cutoff():
    rows = [clip("old", "2026-07-22T00:00:00Z")]
    # a run exists for a clip beyond cutoff — must not leak into eligible accounting
    runs = [ok_run("old"), ok_run("future_clip")]
    snap = build_snapshot(rows, [], runs, cutoff=ts("2026-07-22T00:00:00Z"))
    assert snap.eligible == 1
    assert snap.succeeded_with_active_run == 1
    assert snap.silent_missing == 0
