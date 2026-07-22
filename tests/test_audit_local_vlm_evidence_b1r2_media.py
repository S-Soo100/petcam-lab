"""Gate B1R2 Task 1 — R2 media availability partition (순수 로직 + inventory 계약 테스트).

DB/R2 를 실제로 건드리지 않는다. `scripts/audit_local_vlm_evidence_b1r2_media.py` 의
- 5-state coverage partition (design §4 우선순위: active run > R2 absent(source_expired) > job status),
- 기존 성공 run 은 R2 object 없어도 evidence_succeeded 유지,
- R2 object 없으면 (run 없을 때) source_expired,
- `list_available_mp4_keys` pagination 전량 + 중간 오류 시 partial 미반환(fail-closed),
- `availability_sha256` 정렬·입력순서 무관
만 검증한다.

RED 단계: 아직 모듈이 없으므로 import 실패로 떨어진다.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from scripts.audit_local_vlm_evidence_b1r2_media import (
    ALGORITHM_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    MediaAuditError,
    MediaCoverageRow,
    availability_sha256,
    list_available_mp4_keys,
    partition_media_coverage,
    select_canary,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def clip(clip_id: str, key: str | None = None, camera_id: str = "cam",
         started_at: str = "2026-07-22T00:00:00Z", duration_sec: float = 60.0) -> dict:
    return {
        "id": clip_id,
        "camera_id": camera_id,
        "started_at": started_at,
        "duration_sec": duration_sec,
        "r2_key": key if key is not None else f"clips/{clip_id}.mp4",
    }


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


# 5-state fixture — 각 상태 정확히 하나.
FIVE_STATE_FIXTURE = [
    clip("succ", key="clips/succ.mp4"),      # active run → evidence_succeeded (R2 없어도)
    clip("open", key="clips/open.mp4"),      # no run, R2 present, failed_retryable → open
    clip("silent", key="clips/silent.mp4"),  # no run, R2 present, no job → silent
    clip("term", key="clips/term.mp4"),      # no run, R2 present, failed_terminal → terminal
    clip("expired", key="clips/expired.mp4"),  # no run, R2 absent → source_expired
]
RUNS = [ok_run("succ")]
JOBS = [
    job("open", "failed_retryable", "r2_download_failed"),
    job("term", "failed_terminal", "decode_no_frames"),
    job("expired", "failed_retryable", "r2_download_failed"),  # job 있어도 R2 absent 가 우선
]
AVAILABLE = {"clips/open.mp4", "clips/silent.mp4", "clips/term.mp4"}  # succ/expired 는 없음


# ---------------------------------------------------------------------------
# FakeR2 — boto3 list_objects_v2 paginator 인터페이스 모방
# ---------------------------------------------------------------------------
def objects(n: int) -> int:
    """페이지당 object 수 마커 (FakeR2 가 고유 key 부여)."""
    return n


class _FakePaginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **_kwargs):
        offset = 0
        for page in self._pages:
            if isinstance(page, Exception):
                raise page
            contents = [
                {"Key": f"clips/o{offset + i}.mp4", "Size": 100}
                for i in range(page)
            ]
            offset += page
            yield {"Contents": contents}


class FakeR2:
    def __init__(self, pages):
        self._pages = pages

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return _FakePaginator(self._pages)


class _RawPaginator:
    """size/확장자 필터 검증용 — 임의 Contents 를 그대로 yield."""

    def __init__(self, contents):
        self._contents = contents

    def paginate(self, **_kwargs):
        yield {"Contents": self._contents}


class RawR2:
    def __init__(self, contents):
        self._contents = contents

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return _RawPaginator(self._contents)


# ---------------------------------------------------------------------------
# plan Step 1 RED tests
# ---------------------------------------------------------------------------
def test_existing_run_wins_when_object_is_missing():
    snap, rows = partition_media_coverage(
        [clip("a", key="clips/a.mp4")], runs=[ok_run("a")], jobs=[], available_keys=set()
    )
    assert rows[0].status == "evidence_succeeded"
    assert (snap.evidence_succeeded, snap.source_expired) == (1, 0)


def test_missing_object_without_run_is_source_expired():
    snap, rows = partition_media_coverage(
        [clip("a", key="clips/a.mp4")], runs=[], jobs=[], available_keys=set()
    )
    assert rows[0].status == "source_expired"
    assert snap.source_expired == 1


def test_partition_is_exhaustive_and_exclusive():
    snap, rows = partition_media_coverage(FIVE_STATE_FIXTURE, RUNS, JOBS, AVAILABLE)
    assert len(rows) == snap.study_total == (
        snap.evidence_succeeded + snap.media_available_open
        + snap.media_available_silent + snap.media_available_terminal
        + snap.source_expired
    )
    assert len({row.clip_id for row in rows}) == len(rows)
    by_id = {r.clip_id: r.status for r in rows}
    assert by_id == {
        "succ": "evidence_succeeded",
        "open": "media_available_open",
        "silent": "media_available_silent",
        "term": "media_available_terminal",
        "expired": "source_expired",
    }


def test_inventory_paginates_beyond_1000_and_discards_partial_error():
    assert len(list_available_mp4_keys(FakeR2(pages=[objects(1000), objects(7)]), "b", "clips/")) == 1007
    with pytest.raises(MediaAuditError, match="inventory_failed"):
        list_available_mp4_keys(FakeR2(pages=[objects(1000), RuntimeError("boom")]), "b", "clips/")


# ---------------------------------------------------------------------------
# 추가 계약
# ---------------------------------------------------------------------------
def test_inventory_excludes_non_mp4_and_zero_size():
    r2 = RawR2([
        {"Key": "clips/keep.mp4", "Size": 10},
        {"Key": "clips/empty.mp4", "Size": 0},      # size 0 제외
        {"Key": "clips/thumb.jpg", "Size": 500},    # 비-mp4 제외
        {"Key": "clips/nosize.mp4"},                # Size 누락 제외
    ])
    keys = list_available_mp4_keys(r2, "b", "clips/")
    assert keys == {"clips/keep.mp4"}


def test_source_expired_dominates_open_job_when_object_absent():
    # failed_retryable job 있어도 R2 object 없으면 복구 불가 → source_expired
    snap, rows = partition_media_coverage(
        [clip("a", key="clips/a.mp4")],
        runs=[],
        jobs=[job("a", "failed_retryable", "r2_download_failed")],
        available_keys=set(),
    )
    assert rows[0].status == "source_expired"
    assert snap.media_available_open == 0


def test_terminal_job_with_present_object_is_media_available_terminal():
    snap, rows = partition_media_coverage(
        [clip("a", key="clips/a.mp4")],
        runs=[],
        jobs=[job("a", "failed_terminal", "decode_no_frames")],
        available_keys={"clips/a.mp4"},
    )
    assert rows[0].status == "media_available_terminal"
    assert (snap.media_available_terminal, snap.media_available_silent) == (1, 0)


def test_availability_sha_is_order_independent():
    snap_a, rows_a = partition_media_coverage(FIVE_STATE_FIXTURE, RUNS, JOBS, AVAILABLE)
    shuffled = list(reversed(FIVE_STATE_FIXTURE))
    snap_b, rows_b = partition_media_coverage(shuffled, RUNS, JOBS, AVAILABLE)
    assert snap_a.availability_sha256 == snap_b.availability_sha256
    assert availability_sha256(rows_a) == availability_sha256(rows_b) == snap_a.availability_sha256


def test_camera_date_status_distribution_is_recorded():
    clips = [
        clip("a", key="clips/a.mp4", camera_id="camA", started_at="2026-07-01T10:00:00Z"),
        clip("b", key="clips/b.mp4", camera_id="camA", started_at="2026-07-01T11:00:00Z"),
    ]
    snap, _ = partition_media_coverage(clips, runs=[], jobs=[], available_keys=set())
    # 둘 다 R2 absent → source_expired, 같은 camera/date 로 묶임
    assert snap.camera_date_status_counts["camA|2026-07-01|source_expired"] == 2


def test_row_holds_no_r2_key():
    _snap, rows = partition_media_coverage([clip("a", key="clips/secret-key.mp4")],
                                           runs=[], jobs=[], available_keys=set())
    row = rows[0]
    assert isinstance(row, MediaCoverageRow)
    # 사적 key 는 row 에 저장하지 않는다 (design §5.2)
    assert not any("secret-key" in str(v) for v in vars(row).values() if isinstance(v, str)) \
        if hasattr(row, "__dict__") else True
    assert "r2_key" not in (getattr(row, "__slots__", ()) or ())


def test_cutoff_excludes_new_live_clip():
    clips = [clip("old", started_at="2026-07-22T00:00:00Z"),
             clip("new", started_at="2026-07-22T00:00:01Z")]
    snap, rows = partition_media_coverage(clips, runs=[], jobs=[], available_keys=set(),
                                          cutoff=ts("2026-07-22T00:00:00Z"))
    assert snap.study_total == 1
    assert {r.clip_id for r in rows} == {"old"}


def test_ineligible_when_no_r2_key_or_zero_duration():
    clips = [
        clip("noR2", key=""),
        clip("zeroDur", duration_sec=0),
        clip("good", key="clips/good.mp4"),
    ]
    snap, rows = partition_media_coverage(clips, runs=[], jobs=[], available_keys=set())
    assert snap.study_total == 1
    assert {r.clip_id for r in rows} == {"good"}


# ---------------------------------------------------------------------------
# canary 선택 (design §7) — media_available_silent 에서 camera/date round-robin 결정론적 30
# ---------------------------------------------------------------------------
def _silent_row(clip_id, camera_id, source_date, hour) -> MediaCoverageRow:
    return MediaCoverageRow(
        clip_id=clip_id, camera_id=camera_id,
        started_at=f"{source_date}T{hour:02d}:00:00+00:00",
        source_date=source_date, status="media_available_silent",
    )


# 3 cameras × 4 dates × 5 clips = 60 media_available_silent + 잡음(다른 상태) 몇 개.
_DATES = ("2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04")
POOL = [
    _silent_row(f"{cam}-{d}-{h}", cam, d, h)
    for cam in ("camA", "camB", "camC")
    for d in _DATES
    for h in range(5)
] + [
    MediaCoverageRow("noise-open", "camA", "2026-07-01T00:00:00+00:00", "2026-07-01",
                     "media_available_open"),
    MediaCoverageRow("noise-expired", "camB", "2026-07-02T00:00:00+00:00", "2026-07-02",
                     "source_expired"),
]


def shuffled(pool, seed):
    r = list(pool)
    random.Random(seed).shuffle(r)
    return r


def test_canary_is_deterministic_and_distributed():
    a = select_canary(shuffled(POOL, 1), limit=30)
    b = select_canary(shuffled(POOL, 2), limit=30)
    assert [x.clip_id for x in a] == [x.clip_id for x in b]  # 입력 순서 무관
    assert len({x.clip_id for x in a}) == 30
    assert len({x.camera_id for x in a}) >= 2
    assert len({x.source_date for x in a}) >= 3


def test_canary_only_picks_media_available_silent():
    picked = select_canary(POOL, limit=30)
    assert all(x.status == "media_available_silent" for x in picked)
    assert "noise-open" not in {x.clip_id for x in picked}
    assert "noise-expired" not in {x.clip_id for x in picked}


def test_canary_does_not_inflate_when_pool_small():
    small = [_silent_row(f"c{i}", "camA", "2026-07-01", i) for i in range(4)]
    picked = select_canary(small, limit=30)
    assert len(picked) == 4  # pool 이 작으면 확대하지 않고 있는 만큼만
