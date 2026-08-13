from __future__ import annotations

import csv
import hashlib
import io
import json
import stat
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from PIL import Image

import scripts.build_yolo26n_v24b_future_holdout as builder


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _private_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _jpeg(*, descending: bool, salt: int = 0) -> bytes:
    image = Image.new("RGB", (18, 12))
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            value = (255 - x * 13 if descending else x * 13) % 256
            pixels[x, y] = (value, (value + salt) % 256, (y * 17 + salt) % 256)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=95)
    image.close()
    return output.getvalue()


def _frame(
    ordinal: int,
    *,
    source: str | None = None,
    camera: str | None = None,
    night: str | None = None,
    dhash: int | None = None,
) -> builder.FutureFrame:
    return builder.FutureFrame(
        source_ref=source or f"source-{ordinal:04d}",
        camera_id=camera or f"camera-{ordinal % 3}",
        camera_night=night or f"night-{ordinal % 6}",
        recorded_at=f"2026-08-14T{ordinal % 24:02d}:00:00Z",
        image_sha256=hashlib.sha256(f"image-{ordinal}".encode()).hexdigest(),
        dhash=ordinal if dhash is None else dhash,
        local_name=f"P{ordinal:04d}",
    )


def _assert_caps(frames: tuple[builder.FutureFrame, ...]) -> None:
    assert max(Counter(frame.source_ref for frame in frames).values()) <= 2
    assert max(Counter(frame.camera_night for frame in frames).values()) <= 20
    assert len({frame.camera_id for frame in frames}) >= 3
    assert len({frame.camera_night for frame in frames}) >= 6
    by_source: dict[str, list[builder.FutureFrame]] = defaultdict(list)
    for frame in frames:
        by_source[frame.source_ref].append(frame)
    assert all(
        (left.dhash ^ right.dhash).bit_count() > 2
        for rows in by_source.values()
        for index, left in enumerate(rows)
        for right in rows[index + 1 :]
    )


def test_blind_pool_is_reverse_order_deterministic_and_enforces_all_caps() -> None:
    frames: list[builder.FutureFrame] = []
    for source_index in range(18):
        source = f"private-source-{source_index:02d}"
        camera = f"camera-{source_index % 3}"
        night = f"night-{source_index % 6}"
        frames.extend(
            [
                _frame(
                    source_index * 3 + 1,
                    source=source,
                    camera=camera,
                    night=night,
                    dhash=0,
                ),
                _frame(
                    source_index * 3 + 2,
                    source=source,
                    camera=camera,
                    night=night,
                    dhash=1,
                ),
                _frame(
                    source_index * 3 + 3,
                    source=source,
                    camera=camera,
                    night=night,
                    dhash=(1 << 64) - 1,
                ),
            ]
        )

    selected = builder.choose_blind_reserve_pool(frames, seed="future-v1", limit=24)
    reversed_selected = builder.choose_blind_reserve_pool(
        list(reversed(frames)), seed="future-v1", limit=24
    )

    assert len(selected) == 24
    assert [row.local_name for row in selected] == [
        row.local_name for row in reversed_selected
    ]
    _assert_caps(selected)


def test_exact_holdout_uses_feasibility_not_greedy_for_overlapping_nights() -> None:
    pool: list[builder.FutureFrame] = []
    presence: list[dict[str, str]] = []
    ordinal = 1
    # A positive-first greedy pass consumes shared nights 1..3 and leaves no
    # capacity for negatives.  A feasible solution reserves those nights for
    # negatives and takes positives from nights 4..6.
    for label, nights in (
        ("positive", range(3)),
        ("positive", range(3, 6)),
        ("negative", range(3)),
    ):
        for night_index in nights:
            for _ in range(20):
                frame = _frame(
                    ordinal,
                    source=f"source-{ordinal:04d}",
                    camera=f"camera-{night_index % 3}",
                    night=f"night-{night_index}",
                )
                pool.append(frame)
                presence.append({"sequence": frame.local_name, "presence": label})
                ordinal += 1

    selected = builder.choose_exact_holdout(pool, presence)

    assert len(selected) == 120
    _assert_caps(selected)
    label_by_sequence = {row["sequence"]: row["presence"] for row in presence}
    assert Counter(label_by_sequence[row.local_name] for row in selected) == {
        "positive": 60,
        "negative": 60,
    }
    assert {
        row.camera_night
        for row in selected
        if label_by_sequence[row.local_name] == "positive"
    } == {"night-3", "night-4", "night-5"}


def test_exact_holdout_searches_for_diverse_feasible_solution_instead_of_rejecting_first_optimum() -> None:
    pool: list[builder.FutureFrame] = []
    presence: list[dict[str, str]] = []
    ordinal = 1
    for night_index in range(6):
        for label in ("positive", "negative"):
            frame = _frame(
                ordinal,
                source=f"source-{ordinal:04d}",
                camera=f"camera-{night_index % 3}",
                night=f"night-{night_index}",
            )
            pool.append(frame)
            presence.append({"sequence": frame.local_name, "presence": label})
            ordinal += 1

    selected = builder.choose_exact_holdout(
        pool, presence, positive_count=3, negative_count=3
    )

    assert len(selected) == 6
    _assert_caps(selected)


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda rows: rows[:-1], "exactly one"),
        (lambda rows: [*rows, dict(rows[0])], "exactly one"),
        (
            lambda rows: [
                {**row, "presence": "Positive"} if index == 0 else row
                for index, row in enumerate(rows)
            ],
            "positive, negative, or ambiguous",
        ),
        (
            lambda rows: [
                {**row, "model_confidence": "0.9"} if index == 0 else row
                for index, row in enumerate(rows)
            ],
            "sequence,presence",
        ),
    ],
)
def test_presence_rows_require_exact_columns_values_and_one_row_per_sequence(
    mutate, match: str
) -> None:
    pool = tuple(_frame(index) for index in range(1, 7))
    rows = [
        {
            "sequence": frame.local_name,
            "presence": "positive" if index < 3 else "negative",
        }
        for index, frame in enumerate(pool)
    ]

    with pytest.raises(ValueError, match=match):
        builder.choose_exact_holdout(
            pool,
            mutate(rows),
            positive_count=3,
            negative_count=3,
        )


def _freeze(tmp_path: Path) -> Path:
    return _private_json(
        tmp_path / "v24b-postprocess-freeze.private.json",
        {
            "schema": "yolo26n-v24b-postprocess-freeze-v1",
            "status": "V24B_POSTPROCESS_FROZEN",
            "frozen_at": "2026-08-13T10:00:00Z",
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
        },
    )


def _metadata_source(index: int, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "source_ref": f"future-source-{index:02d}",
        "camera_id": f"camera-{index % 3}",
        "camera_night": f"future-night-{index:02d}",
        "recorded_at": f"2026-08-14T{index % 24:02d}:00:00Z",
        "clip_purpose": "production",
        "r2_key": f"terra-clips/clips/future-source-{index:02d}.mp4",
        "image_sha256": hashlib.sha256(f"future-{index}".encode()).hexdigest(),
        "derivation_refs": [f"future-parent-{index}"],
    }
    row.update(overrides)
    return row


def test_inventory_filters_freeze_purpose_firmware_and_all_overlap_dimensions(
    tmp_path: Path,
) -> None:
    freeze = _freeze(tmp_path)
    existing = _private_json(
        tmp_path / "existing.private.json",
        {
            "records": [
                {
                    "source_ref": "used-source",
                    "image_sha256": "a" * 64,
                    "camera_night_ref": "used-night",
                    "derivation_refs": ["used-parent"],
                }
            ]
        },
    )
    rows = [_metadata_source(index) for index in range(12)]
    rows.extend(
        [
            _metadata_source(30, recorded_at="2026-08-13T10:00:00Z"),
            _metadata_source(31, clip_purpose="test"),
            _metadata_source(32, r2_key="firmware-dev/source-32.mp4"),
            _metadata_source(33, source_ref="used-source"),
            _metadata_source(34, image_sha256="a" * 64),
            _metadata_source(35, camera_night="used-night"),
            _metadata_source(36, derivation_refs=["used-parent"]),
        ]
    )
    select_calls: list[str] = []

    def metadata_select(frozen_after: str):
        select_calls.append(frozen_after)
        return list(reversed(rows))

    output = tmp_path / "future-attempt"
    result = builder.run_inventory(
        freeze=freeze,
        output=output,
        existing_source_json=[existing],
        metadata_select=metadata_select,
        seed="future-v1",
        reserve_limit=24,
        required_count=12,
    )

    assert result == {
        "status": "V24B_FUTURE_INVENTORY_READY",
        "eligible_source_count": 12,
        "selected_source_count": 12,
        "frame_capacity": 24,
        "db_write_count": 0,
        "r2_get_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }
    assert select_calls == ["2026-08-13T10:00:00Z"]
    ledger_path = output / "inventory-selection.private.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger_path.stat().st_mode & 0o777 == 0o600
    assert {row["source_ref"] for row in ledger["sources"]} == {
        f"future-source-{index:02d}" for index in range(12)
    }
    assert ledger["excluded_counts"] == {
        "derivation_overlap": 1,
        "firmware_development": 1,
        "freeze_boundary": 1,
        "image_overlap": 1,
        "night_overlap": 1,
        "purpose": 1,
        "source_overlap": 1,
    }


def test_inventory_shortage_stops_before_any_r2_boundary_or_artifact(
    tmp_path: Path,
) -> None:
    output = tmp_path / "shortage-attempt"
    get_calls = 0

    def forbidden_get(_key: str) -> bytes:
        nonlocal get_calls
        get_calls += 1
        raise AssertionError("inventory must not call R2 GET")

    result = builder.run_inventory(
        freeze=_freeze(tmp_path),
        output=output,
        existing_source_json=[],
        metadata_select=lambda _after: [_metadata_source(index) for index in range(4)],
        seed="future-v1",
        reserve_limit=24,
        required_count=12,
        r2_get=forbidden_get,
    )

    assert result["status"] == "V24B_FUTURE_HOLDOUT_SHORTAGE"
    assert result["r2_get_count"] == get_calls == 0
    assert not (output / "blind-pool").exists()
    assert not (output / "final-cvat").exists()
    assert not list(output.rglob("*.zip"))


def test_inventory_rejects_symlinked_private_freeze_before_select(
    tmp_path: Path,
) -> None:
    target = _freeze(tmp_path)
    link = tmp_path / "freeze-link.private.json"
    link.symlink_to(target)
    select_calls = 0

    def metadata_select(_after: str):
        nonlocal select_calls
        select_calls += 1
        return []

    with pytest.raises(ValueError, match="regular|symlink"):
        builder.run_inventory(
            freeze=link,
            output=tmp_path / "attempt",
            existing_source_json=[],
            metadata_select=metadata_select,
            seed="future-v1",
        )

    assert select_calls == 0


def _inventory_ledger(tmp_path: Path, *, source_count: int = 6) -> Path:
    output = tmp_path / "attempt"
    sources = [_metadata_source(index) for index in range(source_count)]
    _private_json(
        output / "inventory-selection.private.json",
        {
            "schema": "yolo26n-v24b-future-inventory-v1",
            "status": "V24B_FUTURE_INVENTORY_READY",
            "seed": "future-v1",
            "reserve_limit": source_count * 2,
            "required_count": source_count * 2,
            "sources": sources,
            "db_write_count": 0,
            "r2_get_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
            "git_write_count": 0,
        },
    )
    return output


def _extractor(payload: bytes, source: dict[str, object]):
    salt = int(str(source["source_ref"]).rsplit("-", 1)[1])
    return (
        builder.ExtractedFrame(
            frame_index=10,
            jpeg_bytes=_jpeg(descending=False, salt=salt),
            width=18,
            height=12,
        ),
        builder.ExtractedFrame(
            frame_index=20,
            jpeg_bytes=_jpeg(descending=True, salt=salt),
            width=18,
            height=12,
        ),
    )


def _materialized(tmp_path: Path) -> tuple[Path, list[tuple[str, bytes]]]:
    output = _inventory_ledger(tmp_path)
    gets: list[tuple[str, bytes]] = []

    def r2_get(key: str) -> bytes:
        payload = f"mp4-bytes:{key}".encode()
        gets.append((key, payload))
        return payload

    result = builder.materialize_pool(
        output=output,
        r2_get=r2_get,
        extract_frames=_extractor,
    )
    assert result["status"] == "V24B_FUTURE_POOL_READY"
    return output, gets


def test_materialize_gets_each_mp4_once_and_pins_source_and_jpeg_identity(
    tmp_path: Path,
) -> None:
    output, gets = _materialized(tmp_path)

    assert len(gets) == len({key for key, _payload in gets}) == 6
    ledger_path = output / "blind-pool/pool-ledger.private.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger_path.stat().st_mode & 0o777 == 0o600
    assert all(
        source["source_mp4_sha256"] == _sha(payload)
        for source, (_key, payload) in zip(ledger["sources"], gets, strict=True)
    )
    assert len(ledger["frames"]) == 12
    assert all(frame["width"] == 18 and frame["height"] == 12 for frame in ledger["frames"])
    for frame in ledger["frames"]:
        path = output / "blind-pool/images" / f"{frame['sequence']}.jpg"
        payload = path.read_bytes()
        assert _sha(payload) == frame["image_sha256"]
        with Image.open(io.BytesIO(payload)) as image:
            assert image.size == (frame["width"], frame["height"])

    screen = (output / "blind-pool/presence-screen.csv").read_text(encoding="utf-8")
    assert screen.splitlines()[0] == "sequence,presence"
    assert screen.splitlines()[1] == "P0001,"
    assert all(line.endswith(",") for line in screen.splitlines()[1:])
    with zipfile.ZipFile(output / "blind-pool/presence-screen.zip") as archive:
        assert set(archive.namelist()) == {
            "presence-screen.csv",
            *(f"images/P{index:04d}.jpg" for index in range(1, 13)),
        }
        public_payload = b"\n".join(archive.read(name) for name in archive.namelist())
    assert b"future-source" not in public_payload
    assert b"confidence" not in public_payload
    assert b"prediction" not in public_payload


def test_materialize_strips_source_identity_metadata_from_owner_facing_jpeg(
    tmp_path: Path,
) -> None:
    output = _inventory_ledger(tmp_path)

    def metadata_frame(payload: bytes, source: dict[str, object]):
        salt = int(str(source["source_ref"]).rsplit("-", 1)[1])
        image = Image.open(io.BytesIO(_jpeg(descending=False, salt=salt)))
        exif = image.getexif()
        exif[270] = f"source_ref={source['source_ref']}"
        encoded = io.BytesIO()
        image.save(encoded, format="JPEG", quality=95, exif=exif)
        image.close()
        first = builder.ExtractedFrame(10, encoded.getvalue(), 18, 12)
        second = _extractor(payload, source)[1]
        return first, second

    result = builder.materialize_pool(
        output=output,
        r2_get=lambda key: f"mp4:{key}".encode(),
        extract_frames=metadata_frame,
    )

    assert result["status"] == "V24B_FUTURE_POOL_READY"
    for path in (output / "blind-pool/images").glob("*.jpg"):
        payload = path.read_bytes()
        assert b"source_ref" not in payload
        assert b"future-source" not in payload
        with Image.open(io.BytesIO(payload)) as image:
            assert not image.getexif()


@pytest.mark.parametrize(
    "attack, match",
    [
        (
            lambda: builder.ExtractedFrame(
                frame_index=1,
                jpeg_bytes=b"not-an-image",
                width=18,
                height=12,
            ),
            "decode",
        ),
        (
            lambda: builder.ExtractedFrame(
                frame_index=1,
                jpeg_bytes=_jpeg(descending=False),
                width=19,
                height=12,
            ),
            "dimension",
        ),
    ],
)
def test_materialize_rejects_decode_or_dimension_attack_without_publication(
    tmp_path: Path, attack, match: str
) -> None:
    output = _inventory_ledger(tmp_path)

    with pytest.raises(ValueError, match=match):
        builder.materialize_pool(
            output=output,
            r2_get=lambda _key: b"mp4",
            extract_frames=lambda _payload, _source: (attack(),),
        )

    assert not (output / "blind-pool").exists()
    assert not (output / "pool-ledger.private.json").exists()


def test_materialize_detects_inventory_pre_post_identity_change(
    tmp_path: Path,
) -> None:
    output = _inventory_ledger(tmp_path)
    inventory = output / "inventory-selection.private.json"

    def mutating_extractor(payload: bytes, source: dict[str, object]):
        inventory.write_text("{}\n", encoding="utf-8")
        inventory.chmod(0o600)
        return _extractor(payload, source)

    with pytest.raises(ValueError, match="inventory.*changed"):
        builder.materialize_pool(
            output=output,
            r2_get=lambda key: f"mp4:{key}".encode(),
            extract_frames=mutating_extractor,
        )

    assert not (output / "blind-pool").exists()
    assert not (output / "pool-ledger.private.json").exists()


def test_materialize_detects_same_bytes_inventory_inode_replacement(
    tmp_path: Path,
) -> None:
    output = _inventory_ledger(tmp_path)
    inventory = output / "inventory-selection.private.json"

    def replacing_extractor(payload: bytes, source: dict[str, object]):
        original = inventory.read_bytes()
        replacement = inventory.with_name("replacement.private.json")
        replacement.write_bytes(original)
        replacement.chmod(0o600)
        replacement.replace(inventory)
        return _extractor(payload, source)

    with pytest.raises(ValueError, match="inventory.*changed"):
        builder.materialize_pool(
            output=output,
            r2_get=lambda key: f"mp4:{key}".encode(),
            extract_frames=replacing_extractor,
        )

    assert (output / ".locks/materialize-pool.started.private.json").is_file()
    assert not (output / "blind-pool").exists()


def test_materialize_claims_before_first_get_and_preserves_started_lock_on_failure(
    tmp_path: Path,
) -> None:
    output = _inventory_ledger(tmp_path)
    lock = output / ".locks/materialize-pool.started.private.json"

    def failing_get(_key: str) -> bytes:
        assert lock.is_file()
        assert lock.stat().st_mode & 0o777 == 0o600
        raise RuntimeError("simulated R2 interruption")

    with pytest.raises(RuntimeError, match="R2 interruption"):
        builder.materialize_pool(
            output=output,
            r2_get=failing_get,
            extract_frames=_extractor,
        )

    assert lock.is_file()
    assert not (output / "blind-pool").exists()
    assert not (output / "pool-ledger.private.json").exists()


def test_extracted_image_overlap_from_existing_dataset_causes_shortage(
    tmp_path: Path,
) -> None:
    colliding_sha = _sha(_jpeg(descending=False, salt=0))
    existing = _private_json(
        tmp_path / "existing-images.private.json",
        {"records": [{"image_sha256": colliding_sha}]},
    )
    rows = []
    for index in range(6):
        row = _metadata_source(index)
        row.pop("image_sha256")
        rows.append(row)
    output = tmp_path / "future-attempt"
    inventory = builder.run_inventory(
        freeze=_freeze(tmp_path),
        output=output,
        existing_source_json=[existing],
        metadata_select=lambda _after: rows,
        seed="future-v1",
        reserve_limit=12,
        required_count=12,
    )
    assert inventory["status"] == "V24B_FUTURE_INVENTORY_READY"

    result = builder.materialize_pool(
        output=output,
        r2_get=lambda key: f"mp4:{key}".encode(),
        extract_frames=_extractor,
    )

    assert result["status"] == "V24B_FUTURE_HOLDOUT_SHORTAGE"
    assert not (output / "blind-pool").exists()
    assert not (output / "pool-ledger.private.json").exists()


def test_materialize_shortage_returns_status_without_pool_zip_or_cvat(
    tmp_path: Path,
) -> None:
    output = _inventory_ledger(tmp_path)

    result = builder.materialize_pool(
        output=output,
        r2_get=lambda key: f"mp4:{key}".encode(),
        extract_frames=lambda payload, source: (_extractor(payload, dict(source))[0],),
    )

    assert result["status"] == "V24B_FUTURE_HOLDOUT_SHORTAGE"
    assert result["r2_get_count"] == 6
    assert not (output / "blind-pool").exists()
    assert not (output / "pool-ledger.private.json").exists()
    assert not list(output.rglob("*.zip"))


def _write_presence(output: Path, *, positive: int, negative: int, ambiguous: int = 0) -> Path:
    path = output / "owner-presence.csv"
    rows = [
        *("positive" for _ in range(positive)),
        *("negative" for _ in range(negative)),
        *("ambiguous" for _ in range(ambiguous)),
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sequence", "presence"])
        writer.writeheader()
        for index, presence in enumerate(rows, 1):
            writer.writerow({"sequence": f"P{index:04d}", "presence": presence})
    path.chmod(0o600)
    return path


def test_build_final_creates_exact_generic_unprefilled_bundle_atomically(
    tmp_path: Path,
) -> None:
    output, _gets = _materialized(tmp_path)
    presence = _write_presence(output, positive=6, negative=6)

    result = builder.build_final(
        output=output,
        presence_screen=presence,
        positive_count=6,
        negative_count=6,
    )

    assert result == {
        "status": "V24B_FUTURE_HOLDOUT_READY",
        "image_count": 12,
        "positive_count": 6,
        "negative_count": 6,
        "db_write_count": 0,
        "r2_get_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }
    final = output / "final-cvat"
    assert sorted(path.name for path in (final / "images").glob("*.jpg")) == [
        f"H{index:04d}.jpg" for index in range(1, 13)
    ]
    with zipfile.ZipFile(final / "cvat-upload.zip") as archive:
        assert archive.namelist() == [f"H{index:04d}.jpg" for index in range(1, 13)]
        public_payload = b"\n".join(archive.read(name) for name in archive.namelist())
    assert b"future-source" not in public_payload
    assert not any(path.suffix in {".txt", ".xml"} for path in final.rglob("*"))
    review_rows = list(
        csv.DictReader((final / "review-index.csv").open(encoding="utf-8"))
    )
    assert len(review_rows) == 12
    assert review_rows[0]["sequence"] == "H0001"
    assert review_rows[0]["filename"] == "H0001.jpg"
    assert {row["presence"] for row in review_rows} == {"positive", "negative"}
    assert all(row["source_ref"].startswith("future-source-") for row in review_rows)
    manifest = json.loads((final / "manifest.private.json").read_text(encoding="utf-8"))
    assert manifest["prediction_prefill_count"] == 0
    assert manifest["ambiguous_count"] == 0
    assert manifest["positive_count"] == manifest["negative_count"] == 6
    assert all(
        path.stat().st_mode & 0o777 == 0o600
        for path in (
            final / "review-index.csv",
            final / "manifest.private.json",
            final / "cvat-upload.zip",
            output / ".locks/build-final.started.private.json",
        )
    )


def test_build_final_shortage_publishes_no_zip_cvat_or_final_artifact(
    tmp_path: Path,
) -> None:
    output, _gets = _materialized(tmp_path)
    presence = _write_presence(output, positive=5, negative=6, ambiguous=1)

    result = builder.build_final(
        output=output,
        presence_screen=presence,
        positive_count=6,
        negative_count=6,
    )

    assert result["status"] == "V24B_FUTURE_HOLDOUT_SHORTAGE"
    assert not (output / "final-cvat").exists()
    assert not (output / ".locks/build-final.started.private.json").exists()
    assert not list(output.glob("final-*.zip"))


def test_materialize_and_build_final_are_private_no_overwrite_one_shot(
    tmp_path: Path,
) -> None:
    output, _gets = _materialized(tmp_path)
    assert stat.S_IMODE((output / "blind-pool").stat().st_mode) == 0o700
    assert stat.S_IMODE((output / ".locks/materialize-pool.started.private.json").stat().st_mode) == 0o600

    with pytest.raises(FileExistsError):
        builder.materialize_pool(
            output=output,
            r2_get=lambda _key: b"must-not-read",
            extract_frames=_extractor,
        )

    presence = _write_presence(output, positive=6, negative=6)
    builder.build_final(
        output=output,
        presence_screen=presence,
        positive_count=6,
        negative_count=6,
    )
    with pytest.raises(FileExistsError):
        builder.build_final(
            output=output,
            presence_screen=presence,
            positive_count=6,
            negative_count=6,
        )


def test_private_writer_never_exposes_partial_final_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "artifact.private.json"
    real_write = builder.os.write
    observed: list[bool] = []

    def observing_write(descriptor: int, payload: bytes) -> int:
        observed.append(destination.exists())
        return real_write(descriptor, payload[: max(1, len(payload) // 2)])

    monkeypatch.setattr(builder.os, "write", observing_write)
    builder._write_private_json_new(destination, {"status": "COMPLETE", "n": 7})

    assert observed and not any(observed)
    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "status": "COMPLETE",
        "n": 7,
    }
    assert destination.stat().st_mode & 0o777 == 0o600


def test_build_final_preserves_started_lock_and_contested_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, _gets = _materialized(tmp_path)
    presence = _write_presence(output, positive=6, negative=6)
    lock = output / ".locks/build-final.started.private.json"
    destination = output / "final-cvat"
    marker = destination / "belongs-to-racer.txt"

    def contested_publish(_staging: Path, actual_destination: Path) -> None:
        assert lock.is_file()
        assert actual_destination == destination
        destination.mkdir()
        marker.write_text("do not delete", encoding="utf-8")
        raise FileExistsError("simulated publication race")

    monkeypatch.setattr(builder, "_publish_directory_new", contested_publish)

    with pytest.raises(FileExistsError, match="publication race"):
        builder.build_final(
            output=output,
            presence_screen=presence,
            positive_count=6,
            negative_count=6,
        )

    assert lock.is_file()
    assert marker.read_text(encoding="utf-8") == "do not delete"
