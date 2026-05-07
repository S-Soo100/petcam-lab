"""backend.vlm.worker.VlmWorker 단위 테스트.

## 검증 범위
- 폴링 RPC `fn_vlm_pending_clips` 가 처리완료 / 실패-기록 클립 제외 + LIMIT 적용
- INSERT path: 정상 / 영구에러 / 일시에러 / UNIQUE race
- 종 불일치 → confidence=0 + reasoning 프리픽스
- run_once 가 통계 누적

## Gemini / R2 모킹
실제 SDK 호출 없이 monkeypatch 로 `download_clip_bytes` / `classify_clip` 교체.
google.api_core.exceptions 의 ResourceExhausted/InvalidArgument 등은 raise 직접.

## Supabase 모킹
- `.rpc('fn_vlm_pending_clips', {'p_limit': N}).execute()` — DB NOT EXISTS 흉내 (worker
  poll_clips 가 사용).
- `.table('behavior_logs').insert(...).execute()` — INSERT 결과 / UNIQUE 23505 raise.
실 PostgREST 동작을 다 흉내내진 않고 테스트가 필요로 하는 호출만 지원.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from google.api_core import exceptions as gax


# ────────────────────────────────────────────────────────────────────────────
# Fake Supabase — VlmWorker 가 호출하는 패턴만 지원
# ────────────────────────────────────────────────────────────────────────────


class _Resp:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _InsertExec:
    def __init__(self, recorder: "_FakeSupabase", payload: dict[str, Any]) -> None:
        self._recorder = recorder
        self._payload = payload

    def execute(self) -> _Resp:
        if self._recorder._raise_on_insert is not None:
            raise self._recorder._raise_on_insert
        if self._recorder._raise_once_on_insert is not None:
            exc = self._recorder._raise_once_on_insert
            self._recorder._raise_once_on_insert = None
            raise exc
        self._recorder._inserts.append(self._payload)
        return _Resp([self._payload])


class _FakeBehaviorLogsTable:
    def __init__(self, recorder: "_FakeSupabase") -> None:
        self._recorder = recorder

    def insert(self, payload: dict[str, Any]) -> _InsertExec:
        return _InsertExec(self._recorder, payload)


class _RpcExec:
    """`.rpc('fn_vlm_pending_clips', {'p_limit': N}).execute()` 흉내.

    실제 RPC 가 PostgreSQL NOT EXISTS subquery 로 했던 일을 in-memory 로 재현:
      - has_motion = true
      - r2_key NOT NULL
      - behavior_logs 에 source IN ('vlm', 'vlm_failed') row 없음
      - LIMIT N (oldest-first 는 테스트가 입력 순서로 대신 검증)
    """

    def __init__(self, recorder: "_FakeSupabase", limit: int) -> None:
        self._recorder = recorder
        self._limit = limit

    def execute(self) -> _Resp:
        done = {
            bl["clip_id"]
            for bl in self._recorder._behavior_logs
            if bl.get("source") in ("vlm", "vlm_failed")
        }
        rows = [
            c
            for c in self._recorder._camera_clips
            if c.get("has_motion", True)
            and c.get("r2_key") is not None
            and c["id"] not in done
        ]
        return _Resp(rows[: self._limit])


class _FakeSupabase:
    def __init__(
        self,
        camera_clips: list[dict[str, Any]],
        behavior_logs: list[dict[str, Any]] | None = None,
    ) -> None:
        self._camera_clips = camera_clips
        self._behavior_logs = behavior_logs or []
        self._inserts: list[dict[str, Any]] = []
        self._raise_on_insert: Exception | None = None
        self._raise_once_on_insert: Exception | None = None

    def table(self, name: str) -> Any:
        if name == "behavior_logs":
            return _FakeBehaviorLogsTable(self)
        raise AssertionError(f"테스트가 예상하지 못한 테이블: {name}")

    def rpc(self, name: str, params: dict[str, Any]) -> Any:
        if name == "fn_vlm_pending_clips":
            return _RpcExec(self, int(params.get("p_limit", 10)))
        raise AssertionError(f"테스트가 예상하지 못한 RPC: {name}")


# ────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ────────────────────────────────────────────────────────────────────────────


def _make_clip(
    *,
    clip_id: str,
    r2_key: str | None = "clips/x.mp4",
    species_id: str | None = "crested-gecko",
    has_motion: bool = True,
) -> dict[str, Any]:
    """RPC `fn_vlm_pending_clips` 응답 shape — flat species_id (LEFT JOIN pets)."""
    return {
        "id": clip_id,
        "r2_key": r2_key,
        "pet_id": "pet-1",
        "species_id": species_id,
        "has_motion": has_motion,
    }


def _make_vlm_result(action: str = "moving", confidence: float = 0.9) -> Any:
    from backend.vlm.gemini_client import VlmResult

    return VlmResult(
        action=action,
        confidence=confidence,
        reasoning="test reasoning",
        model_id="gemini-2.5-flash",
        tokens_input=100,
        tokens_output=20,
    )


@pytest.fixture
def patch_io(monkeypatch):
    """download / classify 를 noop 으로 갈아끼움. 각 테스트가 필요시 override."""
    monkeypatch.setattr(
        "backend.vlm.worker.download_clip_bytes", lambda r2_key: b"\x00" * 1024
    )
    monkeypatch.setattr(
        "backend.vlm.worker.classify_clip",
        lambda *, video_bytes, system_prompt: _make_vlm_result(),
    )
    monkeypatch.setattr(
        "backend.vlm.worker.build_system_prompt",
        lambda species: f"system prompt for {species}",
    )


# ────────────────────────────────────────────────────────────────────────────
# poll_clips 테스트
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_poll_clips_filters_processed_clips(patch_io):
    """이미 source='vlm' 또는 'vlm_failed' 인 clip 은 폴링에서 제외."""
    from backend.vlm.worker import VlmWorker

    clips = [
        _make_clip(clip_id="c1"),
        _make_clip(clip_id="c2"),
        _make_clip(clip_id="c3"),
    ]
    behavior_logs = [
        {"clip_id": "c1", "source": "vlm"},
        {"clip_id": "c2", "source": "vlm_failed"},
    ]
    sb = _FakeSupabase(clips, behavior_logs)
    worker = VlmWorker(sb=sb, poll_limit=10)

    pending = await worker.poll_clips()
    assert [c["id"] for c in pending] == ["c3"]


@pytest.mark.asyncio
async def test_poll_clips_respects_limit(patch_io):
    """LIMIT N 적용 — 미처리 클립이 N개 초과여도 N개만."""
    from backend.vlm.worker import VlmWorker

    clips = [_make_clip(clip_id=f"c{i}") for i in range(20)]
    sb = _FakeSupabase(clips, behavior_logs=[])
    worker = VlmWorker(sb=sb, poll_limit=3)

    pending = await worker.poll_clips()
    assert len(pending) == 3


@pytest.mark.asyncio
async def test_poll_clips_excludes_null_r2_key(patch_io):
    """r2_key NULL 인 클립은 제외 (encode 미완료)."""
    from backend.vlm.worker import VlmWorker

    clips = [
        _make_clip(clip_id="c1", r2_key=None),
        _make_clip(clip_id="c2", r2_key="clips/c2.mp4"),
    ]
    sb = _FakeSupabase(clips, behavior_logs=[])
    worker = VlmWorker(sb=sb, poll_limit=10)

    pending = await worker.poll_clips()
    assert [c["id"] for c in pending] == ["c2"]


# ────────────────────────────────────────────────────────────────────────────
# process_clip 테스트 — 정상 / 영구 / 일시 / 종 불일치 / UNIQUE
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_clip_inserts_vlm_row_on_success(patch_io):
    from backend.vlm.worker import VlmWorker

    sb = _FakeSupabase([])
    worker = VlmWorker(sb=sb)

    outcome = await worker.process_clip(_make_clip(clip_id="c1"))
    assert outcome == "vlm"
    assert len(sb._inserts) == 1
    inserted = sb._inserts[0]
    assert inserted["clip_id"] == "c1"
    assert inserted["source"] == "vlm"
    assert inserted["action"] == "moving"
    assert inserted["confidence"] == 0.9
    assert inserted["verified"] is False
    assert inserted["vlm_model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_process_clip_inserts_vlm_failed_on_permanent_error(monkeypatch):
    from backend.vlm.worker import VlmWorker

    def _raise(**_kw: Any) -> Any:
        raise gax.InvalidArgument("bad request — schema mismatch")

    monkeypatch.setattr("backend.vlm.worker.download_clip_bytes", lambda k: b"x")
    monkeypatch.setattr("backend.vlm.worker.classify_clip", _raise)
    monkeypatch.setattr(
        "backend.vlm.worker.build_system_prompt", lambda species: "x"
    )

    sb = _FakeSupabase([])
    worker = VlmWorker(sb=sb)

    outcome = await worker.process_clip(_make_clip(clip_id="c1"))
    assert outcome == "vlm_failed"
    assert len(sb._inserts) == 1
    assert sb._inserts[0]["source"] == "vlm_failed"
    assert "[PERMANENT_ERROR]" in sb._inserts[0]["reasoning"]


@pytest.mark.asyncio
async def test_process_clip_returns_transient_on_rate_limit(monkeypatch):
    from backend.vlm.worker import VlmWorker

    def _raise(**_kw: Any) -> Any:
        raise gax.ResourceExhausted("429 quota")

    monkeypatch.setattr("backend.vlm.worker.download_clip_bytes", lambda k: b"x")
    monkeypatch.setattr("backend.vlm.worker.classify_clip", _raise)
    monkeypatch.setattr(
        "backend.vlm.worker.build_system_prompt", lambda species: "x"
    )

    sb = _FakeSupabase([])
    worker = VlmWorker(sb=sb)

    outcome = await worker.process_clip(_make_clip(clip_id="c1"))
    assert outcome == "transient"
    # 일시 에러는 INSERT 안 함 — 다음 사이클 재시도 가능해야.
    assert sb._inserts == []


@pytest.mark.asyncio
async def test_process_clip_returns_transient_on_r2_download_error(monkeypatch):
    from backend.vlm.worker import VlmWorker

    def _raise_download(_k: str) -> bytes:
        raise RuntimeError("R2 connection reset")

    monkeypatch.setattr("backend.vlm.worker.download_clip_bytes", _raise_download)
    monkeypatch.setattr(
        "backend.vlm.worker.build_system_prompt", lambda species: "x"
    )

    sb = _FakeSupabase([])
    worker = VlmWorker(sb=sb)

    outcome = await worker.process_clip(_make_clip(clip_id="c1"))
    assert outcome == "transient"
    assert sb._inserts == []


@pytest.mark.asyncio
async def test_process_clip_validates_species_mismatch(monkeypatch):
    """leopard 에 eating_paste 응답 → confidence=0 + [VALIDATION] prefix."""
    from backend.vlm.worker import VlmWorker

    monkeypatch.setattr("backend.vlm.worker.download_clip_bytes", lambda k: b"x")
    monkeypatch.setattr(
        "backend.vlm.worker.classify_clip",
        lambda *, video_bytes, system_prompt: _make_vlm_result(
            action="eating_paste", confidence=0.95
        ),
    )
    monkeypatch.setattr(
        "backend.vlm.worker.build_system_prompt", lambda species: "x"
    )

    sb = _FakeSupabase([])
    worker = VlmWorker(sb=sb)

    outcome = await worker.process_clip(
        _make_clip(clip_id="c1", species_id="leopard-gecko")
    )
    assert outcome == "vlm"
    inserted = sb._inserts[0]
    assert inserted["confidence"] == 0.0
    assert inserted["reasoning"].startswith("[VALIDATION]")


@pytest.mark.asyncio
async def test_process_clip_returns_duplicate_on_unique_violation(patch_io):
    """다른 워커가 먼저 INSERT 한 race — 23505 catch + skip."""
    from backend.vlm.worker import VlmWorker

    sb = _FakeSupabase([])

    class _Pgrest23505(Exception):
        def __str__(self) -> str:
            return "duplicate key value violates unique constraint (23505)"

    sb._raise_on_insert = _Pgrest23505()

    worker = VlmWorker(sb=sb)
    outcome = await worker.process_clip(_make_clip(clip_id="c1"))
    assert outcome == "duplicate"


# ────────────────────────────────────────────────────────────────────────────
# run_once 테스트 — 통계 누적
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_once_aggregates_stats(patch_io):
    from backend.vlm.worker import VlmWorker

    clips = [_make_clip(clip_id=f"c{i}") for i in range(3)]
    sb = _FakeSupabase(clips, behavior_logs=[])
    worker = VlmWorker(sb=sb, poll_limit=10)

    stats = await worker.run_once()
    assert stats.polled == 3
    assert stats.succeeded == 3
    assert stats.failed_permanent == 0
    assert worker.total_stats.succeeded == 3


@pytest.mark.asyncio
async def test_run_once_returns_zero_when_no_pending(patch_io):
    """모든 clip 이 이미 처리됨 → 폴링 0건 + INSERT 0건."""
    from backend.vlm.worker import VlmWorker

    clips = [_make_clip(clip_id="c1"), _make_clip(clip_id="c2")]
    behavior_logs = [
        {"clip_id": "c1", "source": "vlm"},
        {"clip_id": "c2", "source": "vlm"},
    ]
    sb = _FakeSupabase(clips, behavior_logs)
    worker = VlmWorker(sb=sb, poll_limit=10)

    stats = await worker.run_once()
    assert stats.polled == 0
    assert sb._inserts == []
