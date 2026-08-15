from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from scripts.build_yolo26n_v25_future_holdout import (
    FreezeContract,
    build_readiness,
    collect_metadata,
)


def _freeze() -> FreezeContract:
    return FreezeContract(
        freeze_sha256="a" * 64,
        selected_checkpoint_sha256="b" * 64,
        cutoff_utc="2026-08-15T09:48:31Z",
        threshold=0.20,
        confidence=0.001,
        imgsz=960,
        nms_iou=0.70,
        max_det=50,
    )


def _row(
    source_id: str,
    *,
    started_at: str = "2026-08-15T10:00:00Z",
    purpose: str = "production",
    camera_id: str = "camera-a",
) -> dict[str, object]:
    return {
        "id": source_id,
        "camera_id": camera_id,
        "started_at": started_at,
        "r2_key": f"terra-clips/clips/{source_id}.mp4",
        "clip_purpose": purpose,
    }


def test_readiness_uses_only_post_freeze_production_sources() -> None:
    result = build_readiness(
        freeze=_freeze(),
        rows=[
            _row("before", started_at="2026-08-15T09:48:30Z"),
            _row("at-cutoff", started_at="2026-08-15T09:48:31Z"),
            _row("test", purpose="test"),
            _row("eligible"),
        ],
    )

    assert result["status"] == "V25_FUTURE_MEDIA_READY"
    assert result["eligible_source_count"] == 1
    assert result["camera_count"] == 1
    assert result["camera_night_count"] == 1
    assert result["db_write_count"] == 0
    assert result["r2_get_count"] == 0
    assert result["r2_write_count"] == 0
    assert result["service_write_count"] == 0


def test_zero_rows_is_waiting_not_an_error() -> None:
    result = build_readiness(freeze=_freeze(), rows=[])

    assert result == {
        "schema": "yolo26n-v25-future-readiness-v1",
        "status": "WAITING_FOR_FUTURE_MEDIA",
        "freeze_sha256": "a" * 64,
        "selected_checkpoint_sha256": "b" * 64,
        "cutoff_utc": "2026-08-15T09:48:31Z",
        "eligible_source_count": 0,
        "camera_count": 0,
        "camera_night_count": 0,
        "frame_capacity": 0,
        "db_write_count": 0,
        "r2_get_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "production_model_write_count": 0,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("freeze_sha256", "short"),
        ("selected_checkpoint_sha256", "B" * 64),
        ("cutoff_utc", "2026-08-15 09:48:31"),
        ("threshold", True),
        ("threshold", 0.21),
        ("imgsz", True),
        ("imgsz", 640),
    ],
)
def test_freeze_contract_rejects_unpinned_or_changed_inference(
    field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        replace(_freeze(), **{field: value}).validate()


class _Query:
    def __init__(self, pages: list[tuple[int, list[dict[str, object]]]]) -> None:
        self._pages = pages
        self._range_start = 0

    def select(self, *_args: object, **_kwargs: object) -> "_Query":
        return self

    def gt(self, *_args: object) -> "_Query":
        return self

    def lte(self, *_args: object) -> "_Query":
        return self

    def eq(self, *_args: object) -> "_Query":
        return self

    @property
    def not_(self) -> "_Query":
        return self

    def is_(self, *_args: object) -> "_Query":
        return self

    def order(self, *_args: object) -> "_Query":
        return self

    def range(self, start: int, _end: int) -> "_Query":
        self._range_start = start
        return self

    def execute(self) -> SimpleNamespace:
        count, data = self._pages.pop(0)
        return SimpleNamespace(count=count, data=data)


class _Client:
    def __init__(self, pages: list[tuple[int, list[dict[str, object]]]]) -> None:
        self.query = _Query(pages)

    def table(self, name: str) -> _Query:
        assert name == "motion_clips"
        return self.query


def test_collect_metadata_rejects_count_drift_before_r2_get() -> None:
    client = _Client(
        [
            (2, [_row("one", started_at="2026-08-15T10:00:00Z")]),
            (3, [_row("two", started_at="2026-08-15T10:01:00Z")]),
        ]
    )

    with pytest.raises(ValueError, match="snapshot count"):
        collect_metadata(
            client,
            freeze=_freeze(),
            snapshot_through="2026-08-15T11:00:00Z",
            page_size=1,
        )


def test_collect_metadata_rejects_boolean_exact_count() -> None:
    client = _Client([(True, [_row("one")])])

    with pytest.raises(ValueError, match="exact count"):
        collect_metadata(
            client,
            freeze=_freeze(),
            snapshot_through="2026-08-15T11:00:00Z",
            page_size=1,
        )
