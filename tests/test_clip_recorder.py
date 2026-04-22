"""
backend.clip_recorder 의 INSERT + mirror 훅 단위 테스트.

## 검증 목표
- 미러 매핑 없음 → 기존 동작 유지 (camera_clips INSERT 1회).
- 미러 1개 → 원본 + 미러 총 2회 INSERT, user_id / camera_id / pet_id 교체 정확도.
- 미러 조회 실패 → 원본은 성공, 미러 스킵, warning 로그.
- 미러 INSERT 실패 → 원본 성공 유지 (best-effort), warning 로그.
- (회귀) 원본 INSERT 실패 → pending queue enqueue, 미러 시도 안 함.

## 왜 이 5 개?
- mirror 훅이 "네트워크 장애 / DB 에러 / 매핑 부재" 세 축에서 모두 원본 동작을
  망치지 않아야 함. best-effort 속성이 핵심이라 실패 경로가 중요.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from backend.clip_recorder import make_clip_recorder, make_flush_insert_fn
from backend.pending_inserts import PendingInsertQueue


# ─── FakeSupabase (chained call 흉내) ────────────────────────────────────────


class _FakeResponse:
    def __init__(self, data: Any) -> None:
        self.data = data


class _TableOp:
    """단일 `.table(name)` 호출의 누적 상태 (select/eq/single/insert → execute).

    `raise_on` 에 해당 (table, op) 가 걸려 있으면 실패 주입. list 로 주면
    순차 pop — 첫 insert 성공, 두 번째 실패 같은 시나리오 가능.
    """

    def __init__(self, parent: "_FakeSupabase", name: str) -> None:
        self._parent = parent
        self._name = name
        self._rows = list(parent.tables.get(name, []))
        self._op: str | None = None
        self._insert_row: dict[str, Any] | None = None

    def select(self, *_args: Any, **_kwargs: Any) -> "_TableOp":
        self._op = "select"
        return self

    def eq(self, key: str, val: Any) -> "_TableOp":
        self._rows = [r for r in self._rows if r.get(key) == val]
        return self

    def single(self) -> "_TableOp":
        self._op = "single"
        return self

    def insert(self, row: dict[str, Any]) -> "_TableOp":
        self._op = "insert"
        self._insert_row = row
        return self

    def execute(self) -> _FakeResponse:
        spec = self._parent.raise_on.get((self._name, self._op))
        if spec is not None:
            if isinstance(spec, list):
                # 순차 시나리오: 첫 호출엔 None, 두 번째엔 예외, 식으로
                nxt = spec.pop(0) if spec else None
                if nxt is not None:
                    raise nxt
            else:
                raise spec

        if self._op == "insert":
            assert self._insert_row is not None
            self._parent.inserts.append((self._name, self._insert_row))
            self._parent.tables.setdefault(self._name, []).append(self._insert_row)
            return _FakeResponse([self._insert_row])
        if self._op == "single":
            return _FakeResponse(self._rows[0] if self._rows else None)
        return _FakeResponse(self._rows)


class _FakeSupabase:
    """`.table(name).select().eq().[single().]execute()` + `.insert().execute()` 지원."""

    def __init__(
        self,
        *,
        cameras: list[dict[str, Any]] | None = None,
        clip_mirrors: list[dict[str, Any]] | None = None,
    ) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "cameras": list(cameras or []),
            "clip_mirrors": list(clip_mirrors or []),
            "camera_clips": [],
        }
        self.inserts: list[tuple[str, dict[str, Any]]] = []
        self.raise_on: dict[tuple[str, str | None], Any] = {}

    def table(self, name: str) -> _TableOp:
        return _TableOp(self, name)


# ─── 공통 fixtures / 상수 ───────────────────────────────────────────────────

SRC_USER = "44444444-4444-4444-4444-444444444444"
SRC_CAM = "11111111-1111-1111-1111-111111111111"
MIRROR_USER = "33333333-3333-3333-3333-333333333333"
MIRROR_CAM = "22222222-2222-2222-2222-222222222222"
MIRROR_PET = "55555555-5555-5555-5555-555555555555"


@pytest.fixture
def pending_queue(tmp_path: Path) -> PendingInsertQueue:
    return PendingInsertQueue(tmp_path / "pending.jsonl")


def _clip_payload() -> dict[str, Any]:
    """캡처 워커가 넘기는 필드 형태. camera_id 는 SRC_CAM 고정."""
    return {
        "camera_id": SRC_CAM,
        "started_at": "2026-04-22T00:00:00+00:00",
        "duration_sec": 60.0,
        "has_motion": False,
        "motion_frames": 0,
        "file_path": "storage/clips/2026-04-22/cam-a/000000_idle.mp4",
        "file_size": 1024,
        "codec": "avc1",
        "width": 1920,
        "height": 1080,
        "fps": 12.0,
        "thumbnail_path": "storage/clips/2026-04-22/cam-a/000000_idle.jpg",
    }


def _mirror_row() -> dict[str, Any]:
    return {
        "source_camera_id": SRC_CAM,
        "mirror_camera_id": MIRROR_CAM,
        "mirror_user_id": MIRROR_USER,
    }


def _pending_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text("utf-8").splitlines() if line.strip())


# ─── tests ──────────────────────────────────────────────────────────────────


def test_no_mirror_mapping_results_in_single_insert(
    pending_queue: PendingInsertQueue,
) -> None:
    """clip_mirrors 비어있으면 camera_clips INSERT 1번만 실행 (회귀 보호)."""
    fake = _FakeSupabase(clip_mirrors=[])
    record = make_clip_recorder(fake, pending_queue, SRC_USER, None)

    record(_clip_payload())

    assert len(fake.inserts) == 1
    table, row = fake.inserts[0]
    assert table == "camera_clips"
    assert row["user_id"] == SRC_USER
    assert row["camera_id"] == SRC_CAM
    assert row["pet_id"] is None


def test_mirror_one_target_copies_with_mapped_fields(
    pending_queue: PendingInsertQueue,
) -> None:
    """미러 1 개: 원본 + 미러 총 2 회 INSERT. user/camera/pet 교체 확인."""
    fake = _FakeSupabase(
        cameras=[{"id": MIRROR_CAM, "pet_id": MIRROR_PET}],
        clip_mirrors=[_mirror_row()],
    )
    record = make_clip_recorder(fake, pending_queue, SRC_USER, None)

    record(_clip_payload())

    assert len(fake.inserts) == 2
    original = fake.inserts[0][1]
    mirror = fake.inserts[1][1]

    # 원본
    assert original["user_id"] == SRC_USER
    assert original["camera_id"] == SRC_CAM
    assert original["pet_id"] is None

    # 미러 — 3 필드 교체
    assert mirror["user_id"] == MIRROR_USER
    assert mirror["camera_id"] == MIRROR_CAM
    assert mirror["pet_id"] == MIRROR_PET
    # 나머지 영상 필드는 원본 그대로 (file_path 공유 → 디스크 증가 0)
    assert mirror["file_path"] == original["file_path"]
    assert mirror["thumbnail_path"] == original["thumbnail_path"]
    assert mirror["duration_sec"] == original["duration_sec"]
    assert mirror["codec"] == original["codec"]


def test_mirror_lookup_failure_preserves_original(
    pending_queue: PendingInsertQueue, caplog: pytest.LogCaptureFixture
) -> None:
    """clip_mirrors 조회 실패 → 원본만 INSERT, 미러 스킵, warning 로그."""
    fake = _FakeSupabase(clip_mirrors=[_mirror_row()])
    fake.raise_on[("clip_mirrors", "select")] = RuntimeError("jwks down")

    record = make_clip_recorder(fake, pending_queue, SRC_USER, None)

    with caplog.at_level(logging.WARNING, logger="backend.clip_recorder"):
        record(_clip_payload())

    # 원본 INSERT 1 건만 성사
    assert len(fake.inserts) == 1
    assert fake.inserts[0][0] == "camera_clips"
    assert fake.inserts[0][1]["user_id"] == SRC_USER
    # 미러 스킵 경고
    assert "clip_mirrors lookup failed" in caplog.text
    # 큐에 enqueue 된 건 없음 (원본은 성공했으므로)
    assert _pending_count(pending_queue._path) == 0


def test_mirror_insert_failure_is_best_effort(
    pending_queue: PendingInsertQueue, caplog: pytest.LogCaptureFixture
) -> None:
    """미러 INSERT 실패 → 원본 이미 성공했으니 warning 만. 큐 영향 없음."""
    fake = _FakeSupabase(
        cameras=[{"id": MIRROR_CAM, "pet_id": MIRROR_PET}],
        clip_mirrors=[_mirror_row()],
    )
    # 첫 insert (원본) 성공, 두 번째 insert (미러) 실패
    fake.raise_on[("camera_clips", "insert")] = [None, Exception("dup key")]

    record = make_clip_recorder(fake, pending_queue, SRC_USER, None)

    with caplog.at_level(logging.WARNING, logger="backend.clip_recorder"):
        record(_clip_payload())

    # inserts 기록은 원본만 (미러 insert 는 execute 에서 raise)
    assert len(fake.inserts) == 1
    assert fake.inserts[0][1]["user_id"] == SRC_USER
    # 미러 실패 경고
    assert "clip mirror INSERT failed" in caplog.text
    # pending queue 영향 없음 — 미러 실패는 enqueue 대상 아님
    assert _pending_count(pending_queue._path) == 0


def test_original_insert_failure_enqueues_and_skips_mirror(
    pending_queue: PendingInsertQueue, caplog: pytest.LogCaptureFixture
) -> None:
    """원본 INSERT 실패 → pending 큐에 들어가고 미러 시도 자체를 건너뜀."""
    fake = _FakeSupabase(clip_mirrors=[_mirror_row()])
    fake.raise_on[("camera_clips", "insert")] = Exception("db down")

    record = make_clip_recorder(fake, pending_queue, SRC_USER, None)

    with caplog.at_level(logging.WARNING, logger="backend.clip_recorder"):
        record(_clip_payload())

    # 원본 실패 → 큐에 1 건
    assert _pending_count(pending_queue._path) == 1
    # 미러 경로 안 탐 — lookup 조차 안 함
    assert "clip_mirrors lookup" not in caplog.text
    assert "clip mirror" not in caplog.text
    # 큐에 들어간 row 는 user_id 가 주입된 상태여야 (flush 시 바로 INSERT 가능)
    line = Path(pending_queue._path).read_text("utf-8").splitlines()[0]
    queued = json.loads(line)
    assert queued["user_id"] == SRC_USER
    assert queued["camera_id"] == SRC_CAM


def test_flush_insert_fn_mirrors_on_success() -> None:
    """재시도 성공 시에도 미러 훅 발동 (재시작 gap 재발 방지)."""
    fake = _FakeSupabase(
        cameras=[{"id": MIRROR_CAM, "pet_id": MIRROR_PET}],
        clip_mirrors=[_mirror_row()],
    )
    insert_one = make_flush_insert_fn(fake)
    queued_row = {**_clip_payload(), "user_id": SRC_USER, "pet_id": None}

    ok = insert_one(queued_row)

    assert ok is True
    # 원본 재시도 + 미러 총 2 회
    assert len(fake.inserts) == 2
    assert fake.inserts[0][1]["user_id"] == SRC_USER
    assert fake.inserts[0][1]["camera_id"] == SRC_CAM
    assert fake.inserts[1][1]["user_id"] == MIRROR_USER
    assert fake.inserts[1][1]["camera_id"] == MIRROR_CAM
    assert fake.inserts[1][1]["pet_id"] == MIRROR_PET


def test_flush_insert_fn_skips_mirror_on_original_failure() -> None:
    """재시도 자체 실패면 False + 미러 시도 안 함."""
    fake = _FakeSupabase(clip_mirrors=[_mirror_row()])
    fake.raise_on[("camera_clips", "insert")] = Exception("still down")

    insert_one = make_flush_insert_fn(fake)
    queued_row = {**_clip_payload(), "user_id": SRC_USER, "pet_id": None}

    ok = insert_one(queued_row)

    assert ok is False
    # INSERT 자체가 raise 됐으니 inserts 비어있고 미러 lookup 도 없음
    assert fake.inserts == []
