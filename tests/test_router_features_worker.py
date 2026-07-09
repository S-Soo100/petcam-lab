from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from backend.router_features import (
    RouterFeatureWorker,
    extract_motion_features,
)


class _Resp:
    def __init__(self, data: Any) -> None:
        self.data = data


class _Exec:
    def __init__(self, table: "_Table") -> None:
        self.table = table
        self.filters: list[tuple[str, str, Any]] = []
        self.limit_value: int | None = None
        self.single_value = False
        self.update_payload: dict[str, Any] | None = None
        self.order_column: str | None = None

    def select(self, *_args: Any, **_kwargs: Any) -> "_Exec":
        return self

    def eq(self, column: str, value: Any) -> "_Exec":
        self.filters.append(("eq", column, value))
        return self

    def gte(self, column: str, value: Any) -> "_Exec":
        self.filters.append(("gte", column, value))
        return self

    def lte(self, column: str, value: Any) -> "_Exec":
        self.filters.append(("lte", column, value))
        return self

    def order(self, column: str, *, desc: bool = False) -> "_Exec":
        self.order_column = column
        self.order_desc = desc
        return self

    def limit(self, value: int) -> "_Exec":
        self.limit_value = value
        return self

    def single(self) -> "_Exec":
        self.single_value = True
        return self

    def update(self, payload: dict[str, Any]) -> "_Exec":
        self.update_payload = payload
        return self

    def execute(self) -> _Resp:
        if self.update_payload is not None:
            rows = self._filtered_rows()
            for row in rows:
                row.update(self.update_payload)
            return _Resp(rows)

        rows = self._filtered_rows()
        if self.order_column:
            rows.sort(key=lambda r: r[self.order_column], reverse=getattr(self, "order_desc", False))
        if self.limit_value is not None:
            rows = rows[: self.limit_value]
        if self.single_value:
            return _Resp(rows[0] if rows else None)
        return _Resp(rows)

    def _filtered_rows(self) -> list[dict[str, Any]]:
        rows = list(self.table.rows)
        for op, column, value in self.filters:
            if op == "eq":
                rows = [row for row in rows if row.get(column) == value]
            elif op == "gte":
                rows = [row for row in rows if row.get(column) >= value]
            elif op == "lte":
                rows = [row for row in rows if row.get(column) <= value]
        return rows


class _Table:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def select(self, *args: Any, **kwargs: Any) -> _Exec:
        return _Exec(self).select(*args, **kwargs)

    def update(self, payload: dict[str, Any]) -> _Exec:
        return _Exec(self).update(payload)


class _FakeSupabase:
    def __init__(self) -> None:
        self.clip_router_features = [
            {
                "clip_id": "old-1",
                "camera_id": "cam-1",
                "started_at": "2026-07-09T00:50:00Z",
                "processing_status": "ready",
                "active_motion_ratio": 0.2,
            },
            {
                "clip_id": "clip-1",
                "camera_id": "cam-1",
                "started_at": "2026-07-09T01:00:00Z",
                "processing_status": "pending",
                "active_motion_ratio": None,
            },
        ]
        self.camera_clips = [
            {
                "id": "clip-1",
                "camera_id": "cam-1",
                "started_at": "2026-07-09T01:00:00Z",
                "duration_sec": 2.0,
                "r2_key": None,
                "file_path": "",
                "has_motion": True,
                "motion_frames": 1,
                "width": 64,
                "height": 48,
                "fps": 8.0,
            }
        ]

    def table(self, name: str) -> _Table:
        if name == "clip_router_features":
            return _Table(self.clip_router_features)
        if name == "camera_clips":
            return _Table(self.camera_clips)
        raise AssertionError(name)


def _write_motion_video(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        8.0,
        (64, 48),
    )
    try:
        for idx in range(16):
            frame = np.zeros((48, 64, 3), dtype=np.uint8)
            x = 4 + idx * 2
            frame[16:28, x : x + 10] = 255
            writer.write(frame)
    finally:
        writer.release()


def test_extract_motion_features_detects_bursts(tmp_path: Path) -> None:
    video_path = tmp_path / "motion.mp4"
    _write_motion_video(video_path)

    features = extract_motion_features(video_path, sample_frames=16, duration_hint=2.0)

    assert features.motion_peak > 0
    assert features.active_motion_ratio > 0
    assert features.motion_burst_count >= 1
    assert features.evidence_reliability in {"low", "medium", "high"}


@pytest.mark.asyncio
async def test_worker_updates_pending_row_with_ready_features(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "motion.mp4"
    _write_motion_video(video_path)

    sb = _FakeSupabase()
    sb.camera_clips[0]["file_path"] = str(video_path)
    worker = RouterFeatureWorker(sb=sb, poll_limit=5, sample_frames=16)

    stats = await worker.run_once()

    row = sb.clip_router_features[1]
    assert stats.polled == 1
    assert stats.succeeded == 1
    assert row["processing_status"] == "ready"
    assert row["motion_peak"] > 0
    assert row["window_clip_count_10m"] == 1
    assert row["recent_activity_baseline"] == 0.2


@pytest.mark.asyncio
async def test_worker_handles_legacy_clip_with_null_camera_id(tmp_path: Path) -> None:
    video_path = tmp_path / "legacy.mp4"
    _write_motion_video(video_path)

    sb = _FakeSupabase()
    sb.clip_router_features[1]["camera_id"] = None
    sb.camera_clips[0]["camera_id"] = None
    sb.camera_clips[0]["file_path"] = str(video_path)
    worker = RouterFeatureWorker(sb=sb, poll_limit=5, sample_frames=16)

    stats = await worker.run_once()

    row = sb.clip_router_features[1]
    assert stats.succeeded == 1
    assert row["processing_status"] == "ready"
    assert row["motion_peak"] > 0
    assert row["window_clip_count_10m"] is None
    assert row["recent_activity_baseline"] is None
