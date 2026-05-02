"""
backend.encode_upload_worker 단위 테스트.

## 검증 목표
- 정상 path: 인코딩 + R2 mp4 + 썸네일 업로드 → recorder 가 R2 메타 채워서 호출됨
- 인코딩 실패 → recorder 가 r2_key=NULL 로 호출됨 (원본 size 는 보존)
- R2 mp4 실패 → r2_key=NULL, encoded_file_size=NULL
- R2 썸네일만 실패 → r2_key 채움, thumbnail_r2_key=NULL
- queue full → enqueue 즉시 fallback recorder
- stop() 시 진행 중·대기 중 모두 drain
- clip_id 가 valid UUID4 + R2 key 에 포함됨
- R2 key 규약: `clips/{cam}/{YYYY-MM-DD}/{stem}_{clip_id}.mp4`
- mirror clip_id 분리: 원본 row 만 id 가짐, mirror 로직은 clip_recorder 에서 검증

## monkeypatch 전략
ffmpeg / R2 의 실제 호출을 안 하기 위해 모듈의 `encode_lightweight` / `upload_clip`
를 fake 로 교체. fake 는 recorder spy 와 같은 dict 에 호출 기록 누적.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from backend.encode_upload_worker import (
    DEFAULT_QUEUE_MAXSIZE,
    EncodeUploadWorker,
)


# ─── helpers ────────────────────────────────────────────────────────────


def _clip_payload(
    storage_dir: Path,
    camera_id: str = "cam-1",
    date: str = "2026-05-02",
    hhmmss_tag: str = "153012_motion",
    with_thumb: bool = True,
    file_size: int = 1_700_000,
) -> dict[str, Any]:
    """캡처 워커가 생성할 법한 dict 모양 그대로."""
    cam_dir = storage_dir / "clips" / date / camera_id
    cam_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = cam_dir / f"{hhmmss_tag}.mp4"
    mp4_path.write_bytes(b"\x00" * file_size)  # 더미

    thumb_path = None
    if with_thumb:
        thumb_path = cam_dir / f"{hhmmss_tag}.jpg"
        thumb_path.write_bytes(b"\x00" * 30_000)

    return {
        "camera_id": camera_id,
        "started_at": f"{date}T15:30:12+00:00",
        "duration_sec": 60.0,
        "has_motion": "motion" in hhmmss_tag,
        "motion_frames": 120,
        "file_path": str(mp4_path),
        "file_size": file_size,
        "codec": "avc1",
        "width": 640,
        "height": 360,
        "fps": 12.0,
        "thumbnail_path": str(thumb_path) if thumb_path else None,
    }


class _Spy:
    """recorder spy + monkeypatched encode/upload 콜 누적."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.encode_calls: list[tuple[Path, Path]] = []
        self.upload_calls: list[tuple[Path, str, str]] = []  # (local, key, ctype)

    def make_recorder(self) -> Callable[[dict[str, Any]], None]:
        def rec(payload: dict[str, Any]) -> None:
            self.records.append(payload)

        return rec


def _patch_encode(monkeypatch: pytest.MonkeyPatch, spy: _Spy, success: bool) -> None:
    """
    `encode_lightweight` 를 spy 로 교체. success=True 면 dst 파일 만들고 True 반환.
    """

    def fake(src: Path, dst: Path, crf: int = 26, preset: str = "veryfast") -> bool:
        spy.encode_calls.append((src, dst))
        if success:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b"\x00" * 530_000)  # 인코딩본 size
            return True
        return False

    monkeypatch.setattr(
        "backend.encode_upload_worker.encode_lightweight", fake
    )


def _patch_upload(
    monkeypatch: pytest.MonkeyPatch,
    spy: _Spy,
    *,
    fail_keys: tuple[str, ...] = (),
) -> None:
    """`upload_clip` 교체. fail_keys 에 매치되는 prefix 면 ClientError 던짐."""
    from botocore.exceptions import ClientError

    def fake(local_path: Path, r2_key: str, content_type: str = "video/mp4") -> int:
        spy.upload_calls.append((local_path, r2_key, content_type))
        if any(r2_key.startswith(p) for p in fail_keys):
            raise ClientError(
                {"Error": {"Code": "InternalError", "Message": "boom"}},
                "PutObject",
            )
        return local_path.stat().st_size

    monkeypatch.setattr("backend.encode_upload_worker.upload_clip", fake)


async def _run_worker_with_payload(
    storage_dir: Path,
    payload: dict[str, Any],
    spy: _Spy,
    *,
    concurrency: int = 1,
    queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE,
) -> EncodeUploadWorker:
    """worker start → enqueue 1건 → 처리 완료까지 대기 → return worker."""
    encoded_dir = storage_dir / "encoded"
    worker = EncodeUploadWorker(
        encoded_dir=encoded_dir,
        concurrency=concurrency,
        queue_maxsize=queue_maxsize,
    )
    worker.start()
    callback = worker.make_enqueue_callback(spy.make_recorder())
    callback(payload)
    # call_soon_threadsafe → put_nowait 가 다음 iteration 에 실행되도록 양보.
    await asyncio.sleep(0)
    assert worker._queue is not None
    await asyncio.wait_for(worker._queue.join(), timeout=5.0)
    return worker


# ─── 정상 path ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_success_path_full_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """인코딩 + mp4 upload + thumbnail upload 모두 성공 → record 1건, 모든 R2 메타 채움."""
    spy = _Spy()
    _patch_encode(monkeypatch, spy, success=True)
    _patch_upload(monkeypatch, spy)

    payload = _clip_payload(tmp_path)
    worker = await _run_worker_with_payload(tmp_path, payload, spy)
    await worker.stop(timeout=2.0)

    assert len(spy.records) == 1
    rec = spy.records[0]

    # clip_id 가 valid UUID4 + DB 에 박힌 id 와 R2 key 에 일관되게 들어감
    assert "id" in rec
    clip_id = rec["id"]
    uuid.UUID(clip_id, version=4)  # raise 안 나야 함

    # R2 key 규약: clips/{cam}/{date}/{stem}_{clip_id}.mp4
    assert rec["r2_key"] == f"clips/cam-1/2026-05-02/153012_motion_{clip_id}.mp4"
    assert (
        rec["thumbnail_r2_key"]
        == f"thumbnails/cam-1/2026-05-02/153012_motion_{clip_id}.jpg"
    )
    assert rec["encoded_file_size"] == 530_000
    assert rec["original_file_size"] == 1_700_000

    # 원본 캡처 필드도 보존돼야 함 (camera_id, file_path 등)
    assert rec["camera_id"] == "cam-1"
    assert rec["file_path"] == payload["file_path"]
    assert rec["has_motion"] is True

    # encode + upload 가 정확히 호출됐는지
    assert len(spy.encode_calls) == 1
    src, dst = spy.encode_calls[0]
    assert src == Path(payload["file_path"])
    assert (
        dst
        == tmp_path / "encoded" / "2026-05-02" / "cam-1" / f"153012_motion_{clip_id}.mp4"
    )

    # mp4 + thumb 두 번 upload (mp4 먼저, thumb 다음)
    assert len(spy.upload_calls) == 2
    mp4_call = spy.upload_calls[0]
    thumb_call = spy.upload_calls[1]
    assert mp4_call[2] == "video/mp4"
    assert thumb_call[2] == "image/jpeg"


@pytest.mark.asyncio
async def test_success_path_no_thumbnail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """thumbnail_path=None 케이스 → 썸네일 upload 호출 없음, thumbnail_r2_key=None."""
    spy = _Spy()
    _patch_encode(monkeypatch, spy, success=True)
    _patch_upload(monkeypatch, spy)

    payload = _clip_payload(tmp_path, with_thumb=False)
    payload["thumbnail_path"] = None
    worker = await _run_worker_with_payload(tmp_path, payload, spy)
    await worker.stop(timeout=2.0)

    assert len(spy.records) == 1
    rec = spy.records[0]
    assert rec["r2_key"] is not None
    assert rec["thumbnail_r2_key"] is None
    # mp4 만 upload (썸네일 호출 없음)
    assert len(spy.upload_calls) == 1
    assert spy.upload_calls[0][2] == "video/mp4"


# ─── 실패 path (단일 정책: r2_key=NULL fallback) ─────────────────────────


@pytest.mark.asyncio
async def test_encode_failure_records_with_null_r2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ffmpeg 실패 → upload 호출 없음, recorder 는 r2_key=NULL 로 호출됨."""
    spy = _Spy()
    _patch_encode(monkeypatch, spy, success=False)
    _patch_upload(monkeypatch, spy)

    payload = _clip_payload(tmp_path)
    worker = await _run_worker_with_payload(tmp_path, payload, spy)
    await worker.stop(timeout=2.0)

    assert len(spy.records) == 1
    rec = spy.records[0]
    assert rec["r2_key"] is None
    assert rec["thumbnail_r2_key"] is None
    assert rec["encoded_file_size"] is None
    # original_file_size 는 보존돼야 백필 스크립트가 식별 가능
    assert rec["original_file_size"] == 1_700_000
    # id 는 그래도 발급됨 (fallback 도 같은 정책)
    uuid.UUID(rec["id"], version=4)
    # upload 시도 자체가 없었어야 함
    assert spy.upload_calls == []


@pytest.mark.asyncio
async def test_mp4_upload_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mp4 R2 업로드 실패 → 썸네일 upload 시도 안 함, r2_key/thumbnail_r2_key 모두 NULL."""
    spy = _Spy()
    _patch_encode(monkeypatch, spy, success=True)
    _patch_upload(monkeypatch, spy, fail_keys=("clips/",))

    payload = _clip_payload(tmp_path)
    worker = await _run_worker_with_payload(tmp_path, payload, spy)
    await worker.stop(timeout=2.0)

    rec = spy.records[0]
    assert rec["r2_key"] is None
    assert rec["thumbnail_r2_key"] is None
    assert rec["encoded_file_size"] is None
    # mp4 만 시도, 썸네일은 mp4 실패로 skip
    assert len(spy.upload_calls) == 1
    assert spy.upload_calls[0][2] == "video/mp4"


@pytest.mark.asyncio
async def test_thumbnail_only_failure_keeps_mp4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """썸네일만 실패 → r2_key 는 채워지고, thumbnail_r2_key 만 NULL."""
    spy = _Spy()
    _patch_encode(monkeypatch, spy, success=True)
    _patch_upload(monkeypatch, spy, fail_keys=("thumbnails/",))

    payload = _clip_payload(tmp_path)
    worker = await _run_worker_with_payload(tmp_path, payload, spy)
    await worker.stop(timeout=2.0)

    rec = spy.records[0]
    assert rec["r2_key"] is not None
    assert rec["thumbnail_r2_key"] is None
    # encoded_file_size 는 mp4 success 로 채워져야 함
    assert rec["encoded_file_size"] == 530_000


# ─── queue full / shutdown ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queue_full_immediate_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """maxsize=1 + 인코딩 의도적 지연 → 두 번째 enqueue 는 즉시 fallback 으로 record."""
    spy = _Spy()

    # 첫 작업이 영원히 안 끝나게 — 큐를 막는다
    encode_started = asyncio.Event()
    encode_release = asyncio.Event()

    def slow_encode(src: Path, dst: Path, crf: int = 26, preset: str = "veryfast") -> bool:
        spy.encode_calls.append((src, dst))
        encode_started.set()
        # asyncio.to_thread 안에서 호출됨 → blocking sleep 으로 await 대신 event 흉내
        # 메인 루프에서 set 할 때까지 대기. 짧은 polling.
        import time as _t

        while not encode_release.is_set():
            _t.sleep(0.01)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"\x00" * 100)
        return True

    monkeypatch.setattr(
        "backend.encode_upload_worker.encode_lightweight", slow_encode
    )
    _patch_upload(monkeypatch, spy)

    encoded_dir = tmp_path / "encoded"
    worker = EncodeUploadWorker(
        encoded_dir=encoded_dir, concurrency=1, queue_maxsize=1
    )
    worker.start()
    callback = worker.make_enqueue_callback(spy.make_recorder())

    # 1) 첫 enqueue → worker 가 dequeue 해서 slow_encode 진입 (큐 비어짐)
    callback(_clip_payload(tmp_path, hhmmss_tag="000001_motion"))
    await asyncio.wait_for(encode_started.wait(), timeout=2.0)
    assert spy.records == []

    # 2) worker 가 slow_encode 안에 갇혀있는 동안 두 번 더 enqueue.
    #    1개는 큐(maxsize=1)에 들어가고, 그 다음은 QueueFull → fallback 즉시 record.
    callback(_clip_payload(tmp_path, hhmmss_tag="000002_motion"))
    callback(_clip_payload(tmp_path, hhmmss_tag="000003_motion"))
    await asyncio.sleep(0.1)  # call_soon_threadsafe 가 처리되게 양보

    # fallback record 1건 (000003) 가 있어야 한다 — r2_key=NULL.
    fallbacks = [r for r in spy.records if r["r2_key"] is None]
    assert len(fallbacks) == 1
    assert fallbacks[0]["original_file_size"] == 1_700_000

    # 첫 작업 풀어주고 shutdown
    encode_release.set()
    await worker.stop(timeout=5.0)

    # 첫 (000001) + 큐에 들어가있던 (000002) 둘 다 정상 처리돼야 함
    successes = [r for r in spy.records if r["r2_key"] is not None]
    assert len(successes) == 2


@pytest.mark.asyncio
async def test_stop_drains_pending_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stop() 가 큐에 쌓인 모든 작업을 끝낸 후 종료해야 함."""
    spy = _Spy()
    _patch_encode(monkeypatch, spy, success=True)
    _patch_upload(monkeypatch, spy)

    encoded_dir = tmp_path / "encoded"
    worker = EncodeUploadWorker(
        encoded_dir=encoded_dir, concurrency=2, queue_maxsize=10
    )
    worker.start()
    callback = worker.make_enqueue_callback(spy.make_recorder())

    # 5건 한꺼번에 enqueue → worker 2 개가 나눠 처리
    for i in range(5):
        callback(
            _clip_payload(tmp_path, hhmmss_tag=f"00000{i}_motion")
        )

    await worker.stop(timeout=10.0)

    assert len(spy.records) == 5
    # 모두 성공 — r2_key 채워짐
    assert all(r["r2_key"] is not None for r in spy.records)


@pytest.mark.asyncio
async def test_enqueue_after_stop_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stop() 후 들어온 enqueue 는 worker 안 돌리고 즉시 fallback record."""
    spy = _Spy()
    _patch_encode(monkeypatch, spy, success=True)
    _patch_upload(monkeypatch, spy)

    encoded_dir = tmp_path / "encoded"
    worker = EncodeUploadWorker(encoded_dir=encoded_dir, concurrency=1)
    worker.start()
    callback = worker.make_enqueue_callback(spy.make_recorder())

    # 정상 enqueue 1건 처리
    callback(_clip_payload(tmp_path, hhmmss_tag="000001_motion"))
    await asyncio.sleep(0)
    assert worker._queue is not None
    await asyncio.wait_for(worker._queue.join(), timeout=3.0)
    await worker.stop(timeout=2.0)

    # stop 후 새 enqueue → fallback path 로 직접 record (encode 호출 안 일어남)
    encode_calls_before = len(spy.encode_calls)
    callback(_clip_payload(tmp_path, hhmmss_tag="000002_motion"))

    # fallback 은 sync 라 즉시 반영
    assert len(spy.records) == 2
    assert spy.records[1]["r2_key"] is None
    assert len(spy.encode_calls) == encode_calls_before  # encode 새로 호출 안 됨


# ─── 키 규약 회귀 테스트 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_r2_key_format_uses_started_at_when_path_unparseable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """경로가 표준 구조 아닐 때 started_at 의 ISO 앞 10자로 날짜 fallback."""
    spy = _Spy()
    _patch_encode(monkeypatch, spy, success=True)
    _patch_upload(monkeypatch, spy)

    # storage_dir 직접 두는 게 아니라 임의 위치 → parent.parent.name 이 날짜 아님
    odd_dir = tmp_path / "weird" / "subdir"
    odd_dir.mkdir(parents=True)
    mp4 = odd_dir / "153012_motion.mp4"
    mp4.write_bytes(b"\x00" * 1000)

    payload = {
        "camera_id": "cam-x",
        "started_at": "2026-04-15T15:30:12+00:00",
        "duration_sec": 60.0,
        "has_motion": True,
        "motion_frames": 100,
        "file_path": str(mp4),
        "file_size": 1000,
        "codec": "avc1",
        "width": 640,
        "height": 360,
        "fps": 12.0,
        "thumbnail_path": None,
    }

    encoded_dir = tmp_path / "encoded"
    worker = EncodeUploadWorker(encoded_dir=encoded_dir, concurrency=1)
    worker.start()
    callback = worker.make_enqueue_callback(spy.make_recorder())
    callback(payload)
    await asyncio.sleep(0)
    assert worker._queue is not None
    await asyncio.wait_for(worker._queue.join(), timeout=3.0)
    await worker.stop(timeout=2.0)

    rec = spy.records[0]
    # started_at 의 "2026-04-15" 가 R2 키 날짜로 사용됨
    assert "/2026-04-15/" in rec["r2_key"]
