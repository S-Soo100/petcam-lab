from __future__ import annotations

from dataclasses import replace
import hashlib
from types import SimpleNamespace

import pytest

from scripts.build_yolo26n_v25_future_holdout import (
    FreezeContract,
    FutureFrame,
    build_exposure_fingerprints,
    build_readiness,
    collect_metadata,
    publish_presence_bundle,
    select_reserve,
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


def _jpeg(color: tuple[int, int, int]) -> bytes:
    from io import BytesIO

    from PIL import Image

    output = BytesIO()
    Image.new("RGB", (8, 6), color).save(output, format="JPEG")
    return output.getvalue()


def _frame(
    name: str,
    *,
    dhash64: int = 0,
    source_ref: str | None = None,
    camera_night: str = "camera-a:2026-08-16",
) -> FutureFrame:
    payload = _jpeg((sum(name.encode()) % 255, 30, 40))
    return FutureFrame(
        source_ref=source_ref or f"source-{name}",
        camera_id=camera_night.split(":", 1)[0],
        camera_night=camera_night,
        frame_index=0,
        image_sha256=hashlib.sha256(payload).hexdigest(),
        dhash64=dhash64,
        jpeg_bytes=payload,
    )


def test_exposure_fingerprints_reject_malformed_and_deduplicate() -> None:
    result = build_exposure_fingerprints(
        [
            {"image_sha256": "c" * 64, "dhash64": "0000000000000001"},
            {"image_sha256": "c" * 64, "dhash64": "0000000000000001"},
        ]
    )
    assert result == {"image_sha256": ("c" * 64,), "dhash64": (1,)}

    with pytest.raises(ValueError, match="fingerprint"):
        build_exposure_fingerprints([{"image_sha256": "bad", "dhash64": "1"}])


def test_reserve_excludes_all_exposed_sha_and_near_duplicate() -> None:
    frames = [
        _frame("a", dhash64=0),
        _frame("b", dhash64=0b11),
        _frame("c", dhash64=0b1111),
    ]

    chosen = select_reserve(
        frames,
        exposed_sha={frames[0].image_sha256},
        exposed_dhash={0},
        limit=10,
        seed="future-v25",
    )

    assert [frame.image_sha256 for frame in chosen] == [frames[2].image_sha256]


def test_reserve_is_reverse_input_deterministic_and_enforces_caps() -> None:
    frames = [
        _frame(
            chr(97 + index),
            dhash64=0xF << (index * 4),
            source_ref=f"source-{index // 3}",
            camera_night="camera-a:2026-08-16",
        )
        for index in range(9)
    ]

    forward = select_reserve(frames, limit=8, seed="fixed", source_cap=2, night_cap=5)
    reverse = select_reserve(
        list(reversed(frames)), limit=8, seed="fixed", source_cap=2, night_cap=5
    )

    assert [frame.image_sha256 for frame in forward] == [
        frame.image_sha256 for frame in reverse
    ]
    assert len(forward) == 5
    assert max(
        sum(frame.source_ref == source for frame in forward)
        for source in {frame.source_ref for frame in forward}
    ) <= 2


def test_public_reserve_has_only_blind_names_and_presence_sheet(tmp_path) -> None:
    frames = [
        _frame("d", dhash64=8, source_ref="secret-source"),
        _frame("e", dhash64=16, source_ref="other-source"),
    ]

    result = publish_presence_bundle(frames, tmp_path, model_version="v2.5-secret")

    assert result["status"] == "V25_PRESENCE_QUEUE_READY"
    assert result["public_frame_count"] == 2
    assert (tmp_path / "presence-screen.csv").read_text() == (
        "sequence,presence\nP0001,\nP0002,\n"
    )
    import zipfile

    with zipfile.ZipFile(tmp_path / "cvat-presence.zip") as archive:
        assert archive.namelist() == ["P0001.jpg", "P0002.jpg", "presence-screen.csv"]
        public_bytes = b"".join(archive.read(name) for name in archive.namelist())
    assert b"secret-source" not in public_bytes
    assert b"other-source" not in public_bytes
    assert b"v2.5-secret" not in public_bytes


def test_reserve_rejects_jpeg_bytes_that_do_not_match_pinned_sha() -> None:
    frame = replace(_frame("f", dhash64=32), image_sha256="f" * 64)

    with pytest.raises(ValueError, match="JPEG SHA"):
        select_reserve([frame])
