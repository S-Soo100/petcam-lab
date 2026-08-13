from __future__ import annotations

import csv
import hashlib
import io
import json
import stat
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import scripts.build_yolo26n_v24b_future_holdout as builder
import scripts.evaluate_yolo26n_v24b_future_holdout as future_evaluator
import scripts.validate_yolo26n_v24b_future_holdout_export as export_validator


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _private_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


_ROLE_COUNTS = {
    "dataset": 1762,
    "internal-test151": 151,
    "owner-external60": 60,
}


def _lineage_record(prefix: str, index: int) -> dict[str, object]:
    return {
        "source_ref": f"{prefix}-source-{index:04d}",
        "image_sha256": hashlib.sha256(f"{prefix}-image-{index}".encode()).hexdigest(),
        "camera_night": f"{prefix}-night-{index:04d}",
        "derivation_refs": [f"{prefix}-derivation-{index:04d}"],
    }


def _overlap_ledger(
    path: Path,
    *,
    role: str,
    first_record: dict[str, object] | None = None,
) -> Path:
    count = _ROLE_COUNTS[role]
    records = [_lineage_record(role, index) for index in range(count)]
    if first_record is not None:
        records[0] = first_record
    return _private_json(
        path,
        {
            "schema": "yolo26n-v24b-future-overlap-ledger-v1",
            "status": "V24B_FUTURE_OVERLAP_FROZEN",
            "role": role,
            "record_count": count,
            "records": records,
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
        },
    )


def _overlap_ledgers(
    tmp_path: Path,
    *,
    dataset_first: dict[str, object] | None = None,
) -> dict[str, Path]:
    return {
        "dataset_source_json": _overlap_ledger(
            tmp_path / "dataset-overlap.private.json",
            role="dataset",
            first_record=dataset_first,
        ),
        "internal_test151_source_json": _overlap_ledger(
            tmp_path / "internal-test151-overlap.private.json",
            role="internal-test151",
        ),
        "owner_external60_source_json": _overlap_ledger(
            tmp_path / "owner-external60-overlap.private.json",
            role="owner-external60",
        ),
    }


def _artifact_identity(role: str, index: int) -> tuple[str, str]:
    prefix = {
        "dataset": "D",
        "internal-test151": "T",
        "owner-external60": "O",
    }[role]
    sequence = f"{prefix}{index + 1:05d}"
    image_sha = hashlib.sha256(f"{role}-actual-{index}".encode()).hexdigest()
    return sequence, image_sha


def _actual_artifact(role: str) -> dict[str, object]:
    count = _ROLE_COUNTS[role]
    identities = [_artifact_identity(role, index) for index in range(count)]
    if role == "dataset":
        records: list[dict[str, object]] = []
        for index, (sequence, image_sha) in enumerate(identities):
            split = "train" if index < 1458 else "val" if index < 1611 else "test"
            source_dataset = (
                "gate-operational-v24" if split == "train" and index >= 889 else "base-v23"
            )
            records.append(
                {
                    "sequence": sequence,
                    "split": split,
                    "image_path": f"images/{split}/{sequence}.jpg",
                    "label_path": f"labels/{split}/{sequence}.txt",
                    "image_sha256": image_sha,
                    "box_count": 0,
                    "positive": False,
                    "source_dataset": source_dataset,
                    "camera_night_group": f"protected-night-{index:04d}",
                    "final_holdout_eligible": False,
                }
            )
        return {
            "schema": "yolo26n-owner-dataset-v24",
            "image_count": 1762,
            "split_counts": {"train": 1458, "val": 153, "test": 151},
            "box_count": 0,
            "box_counts": {"train": 0, "val": 0, "test": 0},
            "positive_image_count": 0,
            "positive_counts": {"train": 0, "val": 0, "test": 0},
            "source_dataset_counts": {
                "base-v23": 1193,
                "gate-operational-v24": 569,
            },
            "records": records,
            "gate_operational_added_count": 569,
            "parent_val_test_sha256": "a" * 64,
            "future_holdout_required": True,
            "evaluation_tier": "development",
            "db_write_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
        }
    if role == "internal-test151":
        records = [
            {
                "sequence": sequence,
                "image_sha256": image_sha,
                "width": 100,
                "height": 80,
                "gt_boxes": [],
                "predictions": [],
            }
            for sequence, image_sha in identities
        ]
        return {
            "schema": "yolo26n-v24-prediction-ledger-v1",
            "status": "V24_PREDICTIONS_READY",
            "dataset_schema": "yolo26n-owner-dataset-v24",
            "evaluation_tier": "development",
            "split": "test",
            "candidate": "warm-start",
            "source_commit": "a" * 40,
            "runner_sha256": "b" * 64,
            "dataset_manifest_sha256": "c" * 64,
            "checkpoint_sha256": "d" * 64,
            "inference": {
                "confidence": 0.001,
                "imgsz": 960,
                "nms_iou": 0.70,
                "max_det": 50,
                "device": "mps",
            },
            "image_count": 151,
            "gt_box_count": 0,
            "prediction_count": 0,
            "records": records,
            "threshold_freeze_sha256": "e" * 64,
        }
    records = [
        {
            "sequence": sequence,
            "image_sha256": image_sha,
            "gt_boxes": [],
            "predictions": [],
        }
        for sequence, image_sha in identities
    ]
    return {
        "schema": "yolo26n-owner-media-external-predictions-v1",
        "status": "PREDICTIONS_COMPLETE",
        "candidate": "warm-start",
        "model_version": "v24",
        "threshold": 0.35,
        "inference": {
            "confidence": 0.001,
            "imgsz": 960,
            "nms_iou": 0.70,
            "max_det": 50,
            "device": "mps",
        },
        "provenance": {
            "freeze_sha256": "a" * 64,
            "snapshot_sha256": "b" * 64,
            "summary_sha256": "c" * 64,
            "checkpoint_sha256": "d" * 64,
        },
        "records": records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def _protected_lineage(role: str) -> dict[str, object]:
    count = _ROLE_COUNTS[role]
    return {
        "schema": "yolo26n-v24b-protected-lineage-v1",
        "status": "V24B_PROTECTED_LINEAGE_FROZEN",
        "role": role,
        "record_count": count,
        "records": [
            {
                "sequence": _artifact_identity(role, index)[0],
                "image_sha256": _artifact_identity(role, index)[1],
                "source_ref": f"protected-source-{role}-{index:04d}",
                "camera_night": f"protected-night-{role}-{index:04d}",
                "derivation_refs": [f"protected-derivation-{role}-{index:04d}"],
            }
            for index in range(count)
        ],
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def _prepare_inputs(tmp_path: Path, role: str) -> dict[str, object]:
    artifact = _private_json(
        tmp_path / f"{role}-actual.private.json", _actual_artifact(role)
    )
    lineage = _private_json(
        tmp_path / f"{role}-lineage.private.json", _protected_lineage(role)
    )
    output = tmp_path / f"{role}-overlap.private.json"
    return {
        "role": role,
        "artifact": artifact,
        "expected_artifact_sha256": _sha(artifact.read_bytes()),
        "lineage_sot": lineage,
        "expected_lineage_sha256": _sha(lineage.read_bytes()),
        "output": output,
    }


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
    overlap_ledgers = _overlap_ledgers(
        tmp_path,
        dataset_first={
            "source_ref": "used-source",
            "image_sha256": "a" * 64,
            "camera_night": "used-night",
            "derivation_refs": ["used-parent"],
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

    def metadata_select(frozen_after: str, snapshot_through: str):
        select_calls.append(f"{frozen_after}|{snapshot_through}")
        return list(reversed(rows))

    output = tmp_path / "future-attempt"
    result = builder.run_inventory(
        freeze=freeze,
        output=output,
        **overlap_ledgers,
        metadata_select=metadata_select,
        seed="future-v1",
        reserve_limit=24,
        required_count=12,
        snapshot_through="2026-08-15T00:00:00Z",
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
    assert select_calls == ["2026-08-13T10:00:00Z|2026-08-15T00:00:00Z"]
    ledger_path = output / "inventory-selection.private.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger_path.stat().st_mode & 0o777 == 0o600
    assert ledger["freeze_sha256"] == _sha(freeze.read_bytes())
    assert len(ledger["freeze_sha256"]) == 64
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
        **_overlap_ledgers(tmp_path),
        metadata_select=lambda _after, _through: [
            _metadata_source(index) for index in range(4)
        ],
        seed="future-v1",
        reserve_limit=24,
        required_count=12,
        r2_get=forbidden_get,
        snapshot_through="2026-08-15T00:00:00Z",
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
            **_overlap_ledgers(tmp_path),
            metadata_select=metadata_select,
            seed="future-v1",
            snapshot_through="2026-08-15T00:00:00Z",
        )

    assert select_calls == 0


@pytest.mark.parametrize(
    "attack",
    [
        "wrong_schema",
        "wrong_status",
        "wrong_count",
        "empty_records",
        "missing_lineage",
        "extra_recursive_key",
        "wrong_role",
        "duplicate_role",
    ],
)
def test_inventory_rejects_noncanonical_overlap_ledgers_before_select(
    tmp_path: Path, attack: str
) -> None:
    ledgers = _overlap_ledgers(tmp_path)
    target = (
        ledgers["internal_test151_source_json"]
        if attack == "duplicate_role"
        else ledgers["dataset_source_json"]
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    if attack == "wrong_schema":
        payload["schema"] = "unknown"
    elif attack == "wrong_status":
        payload["status"] = "READY"
    elif attack == "wrong_count":
        payload["record_count"] -= 1
    elif attack == "empty_records":
        payload["records"] = []
    elif attack == "missing_lineage":
        del payload["records"][0]["derivation_refs"]
    elif attack == "extra_recursive_key":
        payload["records"][0]["nested"] = {
            "source_ref": "ambiguous-shadow-source"
        }
    elif attack == "wrong_role":
        payload["role"] = "unknown"
    elif attack == "duplicate_role":
        payload["role"] = "dataset"
        payload["record_count"] = _ROLE_COUNTS["dataset"]
    target.write_text(json.dumps(payload), encoding="utf-8")
    target.chmod(0o600)
    select_calls = 0

    def metadata_select(_after: str, _through: str):
        nonlocal select_calls
        select_calls += 1
        return []

    with pytest.raises(ValueError, match="overlap ledger"):
        builder.run_inventory(
            freeze=_freeze(tmp_path),
            output=tmp_path / "attempt",
            **ledgers,
            metadata_select=metadata_select,
            seed="future-v1",
            snapshot_through="2026-08-15T00:00:00Z",
        )

    assert select_calls == 0


def test_inventory_rejects_duplicate_role_paths_before_select(tmp_path: Path) -> None:
    ledgers = _overlap_ledgers(tmp_path)
    ledgers["internal_test151_source_json"] = ledgers["dataset_source_json"]
    select_calls = 0

    def metadata_select(_after: str, _through: str):
        nonlocal select_calls
        select_calls += 1
        return []

    with pytest.raises(ValueError, match="distinct by role"):
        builder.run_inventory(
            freeze=_freeze(tmp_path),
            output=tmp_path / "attempt",
            **ledgers,
            metadata_select=metadata_select,
            seed="future-v1",
            snapshot_through="2026-08-15T00:00:00Z",
        )

    assert select_calls == 0


@pytest.mark.parametrize(
    "role_argument",
    [
        "dataset_source_json",
        "internal_test151_source_json",
        "owner_external60_source_json",
    ],
)
def test_inventory_rejects_each_symlinked_overlap_role_before_select(
    tmp_path: Path, role_argument: str
) -> None:
    ledgers = _overlap_ledgers(tmp_path)
    target = ledgers[role_argument]
    link = target.with_name(f"{role_argument}-link.private.json")
    link.symlink_to(target)
    ledgers[role_argument] = link
    select_calls = 0

    def metadata_select(_after: str, _through: str):
        nonlocal select_calls
        select_calls += 1
        return []

    with pytest.raises(ValueError, match="symlink"):
        builder.run_inventory(
            freeze=_freeze(tmp_path),
            output=tmp_path / "attempt",
            **ledgers,
            metadata_select=metadata_select,
            seed="future-v1",
            snapshot_through="2026-08-15T00:00:00Z",
        )

    assert select_calls == 0


@pytest.mark.parametrize(
    "role", ["dataset", "internal-test151", "owner-external60"]
)
def test_prepare_overlap_adapts_each_actual_artifact_and_complete_lineage(
    tmp_path: Path, role: str
) -> None:
    kwargs = _prepare_inputs(tmp_path, role)

    result = builder.prepare_overlap(**kwargs)

    assert result == {
        "status": "V24B_FUTURE_OVERLAP_FROZEN",
        "role": role,
        "record_count": _ROLE_COUNTS[role],
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }
    output = kwargs["output"]
    assert isinstance(output, Path)
    normalized = json.loads(output.read_text(encoding="utf-8"))
    assert set(normalized) == {
        "schema",
        "status",
        "role",
        "record_count",
        "records",
        "db_write_count",
        "r2_write_count",
        "service_write_count",
    }
    assert len(normalized["records"]) == _ROLE_COUNTS[role]
    assert set(normalized["records"][0]) == {
        "source_ref",
        "image_sha256",
        "camera_night",
        "derivation_refs",
    }
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    lock = output.parent / ".locks" / f"{output.name}.prepare-overlap.started.private.json"
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600


def test_prepare_dataset_allows_sha_pinned_unknown_top_level_metadata(
    tmp_path: Path,
) -> None:
    kwargs = _prepare_inputs(tmp_path, "dataset")
    artifact = kwargs["artifact"]
    assert isinstance(artifact, Path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["producer_metadata"] = {"release": "independently-pinned"}
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    artifact.chmod(0o600)
    kwargs["expected_artifact_sha256"] = _sha(artifact.read_bytes())

    result = builder.prepare_overlap(**kwargs)

    assert result["record_count"] == 1762


@pytest.mark.parametrize("input_name", ["artifact", "lineage_sot"])
def test_prepare_overlap_rejects_duplicate_json_keys_in_each_input(
    tmp_path: Path, input_name: str
) -> None:
    kwargs = _prepare_inputs(tmp_path, "owner-external60")
    path = kwargs[input_name]
    assert isinstance(path, Path)
    text = path.read_text(encoding="utf-8")
    text = text.replace('"schema":', '"schema":"duplicate","schema":', 1)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    pin_name = (
        "expected_artifact_sha256"
        if input_name == "artifact"
        else "expected_lineage_sha256"
    )
    kwargs[pin_name] = _sha(path.read_bytes())

    with pytest.raises(ValueError, match="duplicate JSON key"):
        builder.prepare_overlap(**kwargs)

    assert not kwargs["output"].exists()


@pytest.mark.parametrize(
    "role, attack",
    [
        ("dataset", "wrong_schema"),
        ("dataset", "wrong_count"),
        ("dataset", "wrong_split"),
        ("dataset", "bool_count"),
        ("internal-test151", "wrong_status"),
        ("internal-test151", "wrong_split"),
        ("internal-test151", "wrong_count"),
        ("internal-test151", "wrong_provenance"),
        ("internal-test151", "malformed_record"),
        ("owner-external60", "wrong_status"),
        ("owner-external60", "wrong_count"),
        ("owner-external60", "wrong_provenance"),
        ("owner-external60", "nan_threshold"),
        ("owner-external60", "extra_root"),
    ],
)
def test_prepare_overlap_rejects_malformed_actual_artifact_without_output(
    tmp_path: Path, role: str, attack: str
) -> None:
    kwargs = _prepare_inputs(tmp_path, role)
    artifact = kwargs["artifact"]
    assert isinstance(artifact, Path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    if attack == "wrong_schema":
        payload["schema"] = "unknown"
    elif attack == "wrong_count":
        if role == "dataset":
            payload["image_count"] = 1761
        elif role == "internal-test151":
            payload["image_count"] = 150
        else:
            payload["records"] = payload["records"][:-1]
    elif attack == "wrong_split":
        if role == "dataset":
            payload["split_counts"] = {"train": 1458, "val": 152, "test": 152}
        else:
            payload["split"] = "val"
    elif attack == "bool_count":
        payload["image_count"] = True
    elif attack == "wrong_status":
        payload["status"] = "READY"
    elif attack == "wrong_provenance":
        if role == "internal-test151":
            payload["checkpoint_sha256"] = "z" * 64
        else:
            payload["provenance"]["freeze_sha256"] = True
    elif attack == "malformed_record":
        payload["records"][0]["width"] = True
    elif attack == "nan_threshold":
        payload["threshold"] = float("nan")
    elif attack == "extra_root":
        payload["source_ref"] = "ambiguous-extra-identity"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    artifact.chmod(0o600)
    kwargs["expected_artifact_sha256"] = _sha(artifact.read_bytes())

    with pytest.raises(ValueError, match="artifact"):
        builder.prepare_overlap(**kwargs)

    assert not kwargs["output"].exists()


@pytest.mark.parametrize(
    "attack", ["missing", "extra", "mismatch", "duplicate", "incomplete", "extra_key"]
)
def test_prepare_overlap_reports_exact_shortage_for_incomplete_lineage(
    tmp_path: Path, attack: str
) -> None:
    kwargs = _prepare_inputs(tmp_path, "owner-external60")
    lineage = kwargs["lineage_sot"]
    assert isinstance(lineage, Path)
    payload = json.loads(lineage.read_text(encoding="utf-8"))
    if attack == "missing":
        payload["records"] = payload["records"][:-1]
    elif attack == "extra":
        payload["records"].append(
            {
                "sequence": "O99999",
                "image_sha256": "f" * 64,
                "source_ref": "protected-extra-source",
                "camera_night": "protected-extra-night",
                "derivation_refs": ["protected-extra-derivation"],
            }
        )
    elif attack == "mismatch":
        payload["records"][0]["image_sha256"] = "f" * 64
    elif attack == "duplicate":
        payload["records"][1] = dict(payload["records"][0])
    elif attack == "incomplete":
        payload["records"][0]["source_ref"] = ""
    else:
        payload["records"][0]["nested"] = {"source_ref": "ambiguous-extra"}
    lineage.write_text(json.dumps(payload), encoding="utf-8")
    lineage.chmod(0o600)
    kwargs["expected_lineage_sha256"] = _sha(lineage.read_bytes())

    with pytest.raises(ValueError, match="^V24B_PROTECTED_LINEAGE_SHORTAGE$"):
        builder.prepare_overlap(**kwargs)

    assert not kwargs["output"].exists()


@pytest.mark.parametrize(
    "pin_name", ["expected_artifact_sha256", "expected_lineage_sha256"]
)
def test_prepare_overlap_requires_independent_exact_input_sha(
    tmp_path: Path, pin_name: str
) -> None:
    kwargs = _prepare_inputs(tmp_path, "owner-external60")
    kwargs[pin_name] = "0" * 64

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        builder.prepare_overlap(**kwargs)

    assert not kwargs["output"].exists()


@pytest.mark.parametrize("input_name", ["artifact", "lineage_sot"])
def test_prepare_overlap_rejects_symlinked_inputs_after_spending_started_lock(
    tmp_path: Path, input_name: str
) -> None:
    kwargs = _prepare_inputs(tmp_path, "owner-external60")
    target = kwargs[input_name]
    assert isinstance(target, Path)
    link = target.with_name(f"{input_name}-link.private.json")
    link.symlink_to(target)
    kwargs[input_name] = link

    with pytest.raises(ValueError, match="symlink"):
        builder.prepare_overlap(**kwargs)

    output = kwargs["output"]
    assert isinstance(output, Path)
    lock = output.parent / ".locks" / f"{output.name}.prepare-overlap.started.private.json"
    assert lock.is_file()
    assert not output.exists()


def test_prepare_overlap_claims_before_single_read_and_detects_same_bytes_aba(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _prepare_inputs(tmp_path, "owner-external60")
    artifact = kwargs["artifact"]
    lineage = kwargs["lineage_sot"]
    output = kwargs["output"]
    assert isinstance(artifact, Path)
    assert isinstance(lineage, Path)
    assert isinstance(output, Path)
    lock = output.parent / ".locks" / f"{output.name}.prepare-overlap.started.private.json"
    reads: Counter[Path] = Counter()
    real_read = builder._read_private_snapshot

    def replacing_read(path: Path):
        assert lock.is_file()
        reads[path] += 1
        snapshot = real_read(path)
        if path == artifact:
            replacement = artifact.with_name("same-bytes-replacement.private.json")
            replacement.write_bytes(snapshot.payload)
            replacement.chmod(0o600)
            replacement.replace(artifact)
        return snapshot

    monkeypatch.setattr(builder, "_read_private_snapshot", replacing_read)
    with pytest.raises(ValueError, match="artifact.*changed"):
        builder.prepare_overlap(**kwargs)

    assert reads == Counter({artifact: 1, lineage: 1})
    assert not output.exists()


def test_prepare_overlap_second_call_and_rival_lock_process_no_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _prepare_inputs(tmp_path, "owner-external60")
    builder.prepare_overlap(**kwargs)

    def forbidden_read(_path: Path):
        raise AssertionError("loser must not process inputs")

    monkeypatch.setattr(builder, "_read_private_snapshot", forbidden_read)
    with pytest.raises(FileExistsError):
        builder.prepare_overlap(**kwargs)

    rival_kwargs = _prepare_inputs(tmp_path / "rival", "owner-external60")
    rival_output = rival_kwargs["output"]
    assert isinstance(rival_output, Path)
    rival_lock = _private_json(
        rival_output.parent
        / ".locks"
        / f"{rival_output.name}.prepare-overlap.started.private.json",
        {"owner": "rival"},
    )
    with pytest.raises(FileExistsError):
        builder.prepare_overlap(**rival_kwargs)
    assert json.loads(rival_lock.read_text(encoding="utf-8")) == {"owner": "rival"}


def test_prepare_overlap_publish_failure_leaves_lock_but_no_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _prepare_inputs(tmp_path, "owner-external60")
    output = kwargs["output"]
    assert isinstance(output, Path)
    real_write = builder._write_private_json_new

    def failing_publish(path: Path, value: object) -> None:
        if path == output:
            raise RuntimeError("simulated normalized publish failure")
        real_write(path, value)

    monkeypatch.setattr(builder, "_write_private_json_new", failing_publish)
    with pytest.raises(RuntimeError, match="publish failure"):
        builder.prepare_overlap(**kwargs)

    lock = output.parent / ".locks" / f"{output.name}.prepare-overlap.started.private.json"
    assert lock.is_file()
    assert not output.exists()


def test_prepared_real_artifacts_feed_inventory_end_to_end(tmp_path: Path) -> None:
    normalized: dict[str, Path] = {}
    for role in _ROLE_COUNTS:
        kwargs = _prepare_inputs(tmp_path / role, role)
        builder.prepare_overlap(**kwargs)
        normalized[role] = kwargs["output"]

    select_calls = 0

    def metadata_select(_after: str, _through: str):
        nonlocal select_calls
        select_calls += 1
        return []

    result = builder.run_inventory(
        freeze=_freeze(tmp_path),
        output=tmp_path / "attempt",
        dataset_source_json=normalized["dataset"],
        internal_test151_source_json=normalized["internal-test151"],
        owner_external60_source_json=normalized["owner-external60"],
        metadata_select=metadata_select,
        seed="future-v1",
        snapshot_through="2026-08-15T00:00:00Z",
    )

    assert result["status"] == "V24B_FUTURE_HOLDOUT_SHORTAGE"
    assert select_calls == 1


def test_prepare_overlap_cli_runs_real_adapter_and_requires_lineage_pin(
    tmp_path: Path,
) -> None:
    kwargs = _prepare_inputs(tmp_path, "owner-external60")
    arguments = [
        "prepare-overlap",
        "--role",
        str(kwargs["role"]),
        "--artifact",
        str(kwargs["artifact"]),
        "--expected-artifact-sha256",
        str(kwargs["expected_artifact_sha256"]),
        "--lineage-sot",
        str(kwargs["lineage_sot"]),
        "--expected-lineage-sha256",
        str(kwargs["expected_lineage_sha256"]),
        "--output",
        str(kwargs["output"]),
    ]

    assert builder.main(arguments) == 0
    assert kwargs["output"].is_file()

    missing_pin = _prepare_inputs(tmp_path / "missing-pin", "owner-external60")
    with pytest.raises(SystemExit):
        builder.main(
            [
                "prepare-overlap",
                "--role",
                "owner-external60",
                "--artifact",
                str(missing_pin["artifact"]),
                "--expected-artifact-sha256",
                str(missing_pin["expected_artifact_sha256"]),
                "--lineage-sot",
                str(missing_pin["lineage_sot"]),
                "--output",
                str(missing_pin["output"]),
            ]
        )


def test_overlap_ledgers_are_single_read_and_same_bytes_replacement_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledgers = _overlap_ledgers(tmp_path)
    target = ledgers["dataset_source_json"]
    reads: Counter[Path] = Counter()
    real_read = builder._read_private_snapshot

    def counting_read(path: Path):
        reads[path] += 1
        return real_read(path)

    def replacing_select(_after: str, _through: str):
        replacement = target.with_name("replacement.private.json")
        replacement.write_bytes(target.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(target)
        return []

    monkeypatch.setattr(builder, "_read_private_snapshot", counting_read)
    with pytest.raises(ValueError, match="overlap ledger.*changed"):
        builder.run_inventory(
            freeze=_freeze(tmp_path),
            output=tmp_path / "attempt",
            **ledgers,
            metadata_select=replacing_select,
            seed="future-v1",
            snapshot_through="2026-08-15T00:00:00Z",
        )

    assert all(reads[path] == 1 for path in ledgers.values())


def test_overlap_ledger_allows_multiple_images_from_one_complete_source(
    tmp_path: Path,
) -> None:
    ledgers = _overlap_ledgers(tmp_path)
    dataset = ledgers["dataset_source_json"]
    payload = json.loads(dataset.read_text(encoding="utf-8"))
    payload["records"][1]["source_ref"] = payload["records"][0]["source_ref"]
    dataset.write_text(json.dumps(payload), encoding="utf-8")
    dataset.chmod(0o600)

    result = builder.run_inventory(
        freeze=_freeze(tmp_path),
        output=tmp_path / "attempt",
        **ledgers,
        metadata_select=lambda _after, _through: [],
        seed="future-v1",
        snapshot_through="2026-08-15T00:00:00Z",
    )

    assert result["status"] == "V24B_FUTURE_HOLDOUT_SHORTAGE"


def test_inventory_claims_before_select_and_failed_select_spends_attempt(
    tmp_path: Path,
) -> None:
    output = tmp_path / "attempt"
    lock = output / ".locks/inventory.started.private.json"
    select_calls = 0

    def failing_select(_after: str, _through: str):
        nonlocal select_calls
        select_calls += 1
        assert lock.is_file()
        assert lock.stat().st_mode & 0o777 == 0o600
        raise RuntimeError("simulated SELECT failure")

    kwargs = {
        "freeze": _freeze(tmp_path),
        "output": output,
        **_overlap_ledgers(tmp_path),
        "metadata_select": failing_select,
        "seed": "future-v1",
        "snapshot_through": "2026-08-15T00:00:00Z",
    }
    with pytest.raises(RuntimeError, match="SELECT failure"):
        builder.run_inventory(**kwargs)
    assert lock.is_file()

    with pytest.raises(FileExistsError):
        builder.run_inventory(**kwargs)
    assert select_calls == 1


def test_inventory_loser_never_selects_or_cleans_rival_lock(tmp_path: Path) -> None:
    output = tmp_path / "attempt"
    lock = _private_json(
        output / ".locks/inventory.started.private.json",
        {"owner": "rival"},
    )
    select_calls = 0

    def metadata_select(_after: str, _through: str):
        nonlocal select_calls
        select_calls += 1
        return []

    with pytest.raises(FileExistsError):
        builder.run_inventory(
            freeze=_freeze(tmp_path),
            output=output,
            **_overlap_ledgers(tmp_path),
            metadata_select=metadata_select,
            seed="future-v1",
            snapshot_through="2026-08-15T00:00:00Z",
        )

    assert select_calls == 0
    assert json.loads(lock.read_text(encoding="utf-8")) == {"owner": "rival"}


class _PagedQuery:
    def __init__(self, client: "_PagedClient") -> None:
        self.client = client
        self.orders: list[str] = []
        self.bounds: list[tuple[str, str, str]] = []
        self.requested: tuple[int, int] | None = None

    def select(self, columns: str, *, count: str):
        self.client.select_contracts.append((columns, count))
        return self

    def gt(self, field: str, value: str):
        self.bounds.append(("gt", field, value))
        return self

    def lte(self, field: str, value: str):
        self.bounds.append(("lte", field, value))
        return self

    @property
    def not_(self):
        return self

    def is_(self, field: str, value: str):
        self.bounds.append(("not-is", field, value))
        return self

    def order(self, field: str):
        self.orders.append(field)
        return self

    def range(self, start: int, end: int):
        self.requested = (start, end)
        return self

    def execute(self):
        assert self.requested is not None
        self.client.calls.append((self.requested, tuple(self.orders), tuple(self.bounds)))
        start, end = self.requested
        page = self.client.page_overrides.get(start, self.client.rows[start : end + 1])
        return SimpleNamespace(data=page, count=self.client.count)


class _PagedClient:
    def __init__(
        self,
        rows: list[dict[str, object]],
        *,
        count: int | None = None,
        page_overrides: dict[int, list[dict[str, object]]] | None = None,
    ) -> None:
        self.rows = rows
        self.count = len(rows) if count is None else count
        self.page_overrides = page_overrides or {}
        self.calls: list[tuple[object, ...]] = []
        self.select_contracts: list[tuple[str, str]] = []

    def table(self, name: str):
        assert name == "motion_clips"
        return _PagedQuery(self)


def _paged_rows(count: int) -> list[dict[str, object]]:
    return [
        {
            "id": f"id-{index:05d}",
            "camera_id": "camera-0",
            "started_at": "2026-08-14T01:00:00Z",
            "r2_key": f"terra-clips/clips/{index}.mp4",
            "clip_purpose": "production",
        }
        for index in range(count)
    ]


@pytest.mark.parametrize("count, expected_ranges", [(1000, [(0, 999)]), (2000, [(0, 999), (1000, 1999)])])
def test_paginated_select_covers_exact_page_boundaries_with_stable_order(
    count: int, expected_ranges: list[tuple[int, int]]
) -> None:
    client = _PagedClient(_paged_rows(count))

    rows = builder._paged_metadata_select(
        client,
        frozen_after="2026-08-13T10:00:00Z",
        snapshot_through="2026-08-15T00:00:00Z",
    )

    assert len(rows) == count
    assert [call[0] for call in client.calls] == expected_ranges
    assert all(call[1] == ("started_at", "id") for call in client.calls)
    assert all(
        call[2]
        == (
            ("gt", "started_at", "2026-08-13T10:00:00Z"),
            ("lte", "started_at", "2026-08-15T00:00:00Z"),
            ("not-is", "r2_key", "null"),
        )
        for call in client.calls
    )


@pytest.mark.parametrize("attack", ["missing", "duplicate", "out_of_order"])
def test_paginated_select_rejects_inconsistent_snapshot_pages(attack: str) -> None:
    rows = _paged_rows(1001)
    overrides: dict[int, list[dict[str, object]]] = {}
    if attack == "missing":
        overrides[1000] = []
    elif attack == "duplicate":
        overrides[1000] = [dict(rows[999])]
    else:
        overrides[1000] = [{**rows[1000], "id": "id-00001"}]
    client = _PagedClient(rows, count=1001, page_overrides=overrides)

    with pytest.raises(ValueError, match="pagination|snapshot"):
        builder._paged_metadata_select(
            client,
            frozen_after="2026-08-13T10:00:00Z",
            snapshot_through="2026-08-15T00:00:00Z",
        )


def test_metadata_selector_preserves_121st_camera_feasibility_and_reverse_order() -> None:
    rows: list[dict[str, object]] = []
    for index in range(120):
        row = _metadata_source(index)
        row.update(
            source_ref=f"source-{index:03d}",
            camera_id="camera-a" if index < 60 else "camera-b",
            camera_night=f"night-{index:03d}",
        )
        rows.append(row)
    camera_c = _metadata_source(121)
    camera_c.update(
        source_ref="camera-c-81",
        camera_id="camera-c",
        camera_night="night-120",
    )
    rows.append(camera_c)

    selected = builder._choose_metadata_sources(
        rows, seed="future-v1", max_sources=120, required_count=120
    )
    reversed_selected = builder._choose_metadata_sources(
        list(reversed(rows)), seed="future-v1", max_sources=120, required_count=120
    )

    assert len(selected) == 120
    assert "camera-c-81" in {row["source_ref"] for row in selected}
    assert [row["source_ref"] for row in selected] == [
        row["source_ref"] for row in reversed_selected
    ]


def _inventory_ledger(
    tmp_path: Path, *, source_count: int = 6, freeze_sha256: object = "f" * 64
) -> Path:
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
            "freeze_sha256": freeze_sha256,
            "sources": sources,
            "db_write_count": 0,
            "r2_get_count": 0,
            "r2_write_count": 0,
            "service_write_count": 0,
            "git_write_count": 0,
        },
    )
    return output


@pytest.mark.parametrize("mutation", ["missing", "boolean", "malformed"])
def test_materialize_rejects_invalid_inventory_freeze_before_first_r2_get(
    tmp_path: Path, mutation: str
) -> None:
    output = _inventory_ledger(tmp_path)
    inventory_path = output / "inventory-selection.private.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if mutation == "missing":
        del inventory["freeze_sha256"]
    elif mutation == "boolean":
        inventory["freeze_sha256"] = True
    else:
        inventory["freeze_sha256"] = "A" * 64
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    inventory_path.chmod(0o600)
    get_calls = 0

    def forbidden_get(_key: str) -> bytes:
        nonlocal get_calls
        get_calls += 1
        raise AssertionError("invalid freeze lineage must stop before R2 GET")

    with pytest.raises(ValueError, match="freeze.*SHA"):
        builder.materialize_pool(
            output=output,
            r2_get=forbidden_get,
            extract_frames=_extractor,
        )

    assert get_calls == 0
    assert not (output / ".locks/materialize-pool.started.private.json").exists()


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
    overlap_ledgers = _overlap_ledgers(
        tmp_path,
        dataset_first={
            "source_ref": "historical-source",
            "image_sha256": colliding_sha,
            "camera_night": "historical-night",
            "derivation_refs": ["historical-derivation"],
        },
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
        **overlap_ledgers,
        metadata_select=lambda _after, _through: rows,
        seed="future-v1",
        reserve_limit=12,
        required_count=12,
        snapshot_through="2026-08-15T00:00:00Z",
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


def test_materialize_quota_infeasibility_is_atomic_private_shortage(
    tmp_path: Path,
) -> None:
    output = _inventory_ledger(tmp_path)
    inventory_path = output / "inventory-selection.private.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    for source in inventory["sources"]:
        source["camera_id"] = "only-camera"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    inventory_path.chmod(0o600)

    result = builder.materialize_pool(
        output=output,
        r2_get=lambda key: f"mp4:{key}".encode(),
        extract_frames=_extractor,
    )

    assert result["status"] == "V24B_FUTURE_HOLDOUT_SHORTAGE"
    status_path = output / "materialize-shortage.private.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "V24B_FUTURE_HOLDOUT_SHORTAGE"
    assert status["db_write_count"] == status["r2_write_count"] == 0
    assert stat.S_IMODE(status_path.stat().st_mode) == 0o600
    assert (output / ".locks/materialize-pool.started.private.json").is_file()
    assert not (output / "blind-pool").exists()
    assert not (output / "final-cvat").exists()
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
    assert tuple(review_rows[0]) == export_validator.REVIEW_HEADER
    assert all(row["dhash"].isascii() and row["dhash"].isdecimal() for row in review_rows)
    assert {row["presence"] for row in review_rows} == {"positive", "negative"}
    assert all(row["source_ref"].startswith("future-source-") for row in review_rows)
    manifest = json.loads((final / "manifest.private.json").read_text(encoding="utf-8"))
    assert manifest["prediction_prefill_count"] == 0
    assert manifest["ambiguous_count"] == 0
    assert manifest["positive_count"] == manifest["negative_count"] == 6
    assert manifest["postprocess_freeze_sha256"] == "f" * 64
    review_bytes = (final / "review-index.csv").read_bytes()
    assert manifest["review_index_sha256"] == _sha(review_bytes)
    assert all("dhash" not in row and "source_ref" not in row for row in manifest["records"])
    assert b"dhash" not in public_payload
    assert all(
        path.stat().st_mode & 0o777 == 0o600
        for path in (
            final / "review-index.csv",
            final / "manifest.private.json",
            final / "cvat-upload.zip",
            output / ".locks/build-final.started.private.json",
        )
    )


@pytest.mark.parametrize("mutation", ["missing", "boolean", "malformed"])
def test_build_final_rejects_invalid_pool_freeze_before_lock_or_image_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    output, _gets = _materialized(tmp_path)
    ledger_path = output / "blind-pool/pool-ledger.private.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if mutation == "missing":
        del ledger["postprocess_freeze_sha256"]
    elif mutation == "boolean":
        ledger["postprocess_freeze_sha256"] = True
    else:
        ledger["postprocess_freeze_sha256"] = "g" * 64
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    ledger_path.chmod(0o600)
    presence = _write_presence(output, positive=6, negative=6)
    image_reads = 0
    real_read_bytes = builder._read_private_bytes

    def counting_read(path: Path) -> bytes:
        nonlocal image_reads
        if path.suffix == ".jpg":
            image_reads += 1
        return real_read_bytes(path)

    monkeypatch.setattr(builder, "_read_private_bytes", counting_read)
    with pytest.raises(ValueError, match="freeze.*SHA"):
        builder.build_final(
            output=output,
            presence_screen=presence,
            positive_count=6,
            negative_count=6,
        )

    assert image_reads == 0
    assert not (output / ".locks/build-final.started.private.json").exists()
    assert not (output / "final-cvat").exists()


def test_actual_pipeline_propagates_exact_freeze_sha_to_task6_manifest_gate(
    tmp_path: Path,
) -> None:
    freeze = _freeze(tmp_path)
    freeze_sha = _sha(freeze.read_bytes())
    output = tmp_path / "pipeline-attempt"
    inventory = builder.run_inventory(
        freeze=freeze,
        output=output,
        **_overlap_ledgers(tmp_path),
        metadata_select=lambda _after, _through: [
            _metadata_source(index) for index in range(60)
        ],
        seed="future-v1",
        reserve_limit=120,
        required_count=120,
        snapshot_through="2026-08-15T00:00:00Z",
    )
    assert inventory["status"] == "V24B_FUTURE_INVENTORY_READY"
    materialized = builder.materialize_pool(
        output=output,
        r2_get=lambda key: f"mp4:{key}".encode(),
        extract_frames=_extractor,
    )
    assert materialized["status"] == "V24B_FUTURE_POOL_READY"
    presence = _write_presence(output, positive=60, negative=60)

    final = builder.build_final(output=output, presence_screen=presence)

    assert final["status"] == "V24B_FUTURE_HOLDOUT_READY"
    manifest_path = output / "final-cvat/manifest.private.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["postprocess_freeze_sha256"] == freeze_sha
    assert len(
        future_evaluator._validate_holdout_manifest(
            manifest,
            freeze_sha256=freeze_sha,
        )
    ) == 120
    with pytest.raises(ValueError, match="freeze.*cross-pin"):
        future_evaluator._validate_holdout_manifest(
            manifest,
            freeze_sha256="0" * 64,
        )
    with zipfile.ZipFile(output / "final-cvat/cvat-upload.zip") as archive:
        assert archive.namelist() == [f"H{index:04d}.jpg" for index in range(1, 121)]


def test_actual_build_final_contract_is_consumed_by_task5_parser_via_task6_lineage_gate(
    tmp_path: Path,
) -> None:
    output = _inventory_ledger(tmp_path, source_count=60)
    result = builder.materialize_pool(
        output=output,
        r2_get=lambda key: f"mp4:{key}".encode(),
        extract_frames=_extractor,
    )
    assert result["status"] == "V24B_FUTURE_POOL_READY"
    presence = _write_presence(output, positive=60, negative=60)

    final_result = builder.build_final(output=output, presence_screen=presence)

    assert final_result["status"] == "V24B_FUTURE_HOLDOUT_READY"
    final = output / "final-cvat"
    manifest_bytes = (final / "manifest.private.json").read_bytes()
    review_bytes = (final / "review-index.csv").read_bytes()
    manifest = json.loads(manifest_bytes)
    records = future_evaluator._validate_holdout_manifest(
        manifest,
        freeze_sha256="f" * 64,
    )
    review_rows = export_validator._read_review_index(review_bytes)
    export_validator._validate_review_index(review_rows, records)
    manifest_sha = _sha(manifest_bytes)
    review_sha = _sha(review_bytes)
    assert manifest["review_index_sha256"] == review_sha
    assert manifest_sha != review_sha
    assert len(records) == len(review_rows) == 120
    assert len(manifest_sha) == 64


def test_build_final_rejects_review_index_mutation_before_manifest_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, _gets = _materialized(tmp_path)
    presence = _write_presence(output, positive=6, negative=6)
    real_write_json = builder._write_private_json_new

    def mutating_manifest_write(path: Path, value: object) -> None:
        if path.name == "manifest.private.json":
            review = path.parent / "review-index.csv"
            review.write_bytes(review.read_bytes() + b"\n")
            review.chmod(0o600)
        real_write_json(path, value)

    monkeypatch.setattr(builder, "_write_private_json_new", mutating_manifest_write)
    with pytest.raises(ValueError, match="review index.*changed"):
        builder.build_final(
            output=output,
            presence_screen=presence,
            positive_count=6,
            negative_count=6,
        )

    assert (output / ".locks/build-final.started.private.json").is_file()
    assert not (output / "final-cvat").exists()


def test_build_final_reads_completed_review_index_bytes_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, _gets = _materialized(tmp_path)
    presence = _write_presence(output, positive=6, negative=6)
    real_read = builder._read_private_snapshot
    review_reads = 0

    def counting_read(path: Path):
        nonlocal review_reads
        if path.name == "review-index.csv":
            review_reads += 1
        return real_read(path)

    monkeypatch.setattr(builder, "_read_private_snapshot", counting_read)
    builder.build_final(
        output=output,
        presence_screen=presence,
        positive_count=6,
        negative_count=6,
    )

    assert review_reads == 1


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


def test_inventory_cli_requires_and_forwards_all_three_role_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledgers = _overlap_ledgers(tmp_path)
    captured: dict[str, object] = {}

    def fake_inventory(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"status": "V24B_FUTURE_HOLDOUT_SHORTAGE"}

    monkeypatch.setattr(builder, "run_inventory", fake_inventory)
    arguments = [
        "inventory",
        "--freeze",
        str(_freeze(tmp_path)),
        "--output",
        str(tmp_path / "attempt"),
        "--dataset-source-json",
        str(ledgers["dataset_source_json"]),
        "--internal-test151-source-json",
        str(ledgers["internal_test151_source_json"]),
        "--owner-external60-source-json",
        str(ledgers["owner_external60_source_json"]),
    ]

    assert builder.main(arguments) == 0
    assert captured["dataset_source_json"] == ledgers["dataset_source_json"]
    assert captured["internal_test151_source_json"] == ledgers[
        "internal_test151_source_json"
    ]
    assert captured["owner_external60_source_json"] == ledgers[
        "owner_external60_source_json"
    ]
    with pytest.raises(SystemExit):
        builder.main(arguments[:-2])
