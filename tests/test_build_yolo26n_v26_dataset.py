from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

import scripts.build_yolo26n_v26_dataset as dataset_builder
from scripts.build_yolo26n_v26_dataset import build_recent_split_plan, materialize_v26_dataset


KST = timezone(timedelta(hours=9))
FINAL_GT_SHA_FIELDS = (
    "primary_export_sha256",
    "double_review_export_sha256",
    "adjudication_export_sha256",
    "adjudication_index_sha256",
    "review_index_sha256",
    "selection_sha256",
)


def test_dataset_cli_help_is_directly_executable() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/build_yolo26n_v26_dataset.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--dense-completion" in completed.stdout
    assert "--enriched-completion" in completed.stdout
    assert "--parent-integrity-manifest" in completed.stdout


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _inputs(
    *, clips_per_camera: int = 6
) -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    str,
    dict[str, object],
    str,
    str,
]:
    records: list[dict[str, object]] = []
    selected: list[dict[str, object]] = []
    sources: list[dict[str, object]] = []
    dense_clips: list[dict[str, object]] = []
    ordinal = 0
    for camera_index in range(2):
        camera = f"camera-{camera_index}"
        night = f"camera-{camera_index}:2026-08-24"
        base = datetime(2026, 8, 24, 20, 0, tzinfo=KST)
        for clip_index in range(clips_per_camera):
            ordinal += 1
            clip = f"clip-{camera_index}-{clip_index}"
            # 3분 간격이라 각 clip은 독립 episode가 된다.
            started = base + timedelta(minutes=3 * clip_index)
            image_sha = f"{ordinal:064x}"
            dhash = f"{ordinal * 0x1111111111111111 & ((1 << 64) - 1):016x}"
            present = ordinal % 2 == 0
            records.append(
                {
                    "blind_filename": f"frame_{ordinal:024x}.jpg",
                    "boxes": [[10.0, 20.0, 110.0, 220.0]] if present else [],
                    "camera_night": night,
                    "clip_ref": clip,
                    "decision": "present" if present else "absent",
                    "decision_source": "primary",
                    "height": 720,
                    "image_sha256": image_sha,
                    "materialization_reason": "selected",
                    "reasons": ["coverage"],
                    "stratum": "coverage",
                    "tags": [],
                    "timestamp_ms": 1_000,
                    "width": 960,
                }
            )
            selected.append(
                {
                    "camera_night": night,
                    "clip_ref": clip,
                    "dhash64": dhash,
                    "image_sha256": image_sha,
                    "timestamp_ms": 1_000,
                    "stratum": "coverage",
                    "reasons": ["coverage"],
                    "double_review": ordinal <= 2,
                    "private_ref": f"private-{ordinal}",
                }
            )
            sources.append(
                {
                    "camera_id": camera,
                    "clip_id": clip,
                    "duration_sec": 60.0,
                    "started_at": started.isoformat(),
                    "object_status": "available",
                    "r2_key": f"clips/{clip}.mp4",
                    "size_bytes": 100 + ordinal,
                }
            )
            dense_clips.append(
                {
                    "clip_ref": clip,
                    "private_ref": f"private-{ordinal}",
                    "source_sha256": hashlib.sha256(clip.encode()).hexdigest(),
                    "ledger_sha256": hashlib.sha256(f"ledger:{clip}".encode()).hexdigest(),
                    "sampled_frame_count": 120,
                }
            )

    dense_completion_sha256 = "a" * 64
    enriched_completion_sha256 = "b" * 64
    selection_payload = {
        "schema": "yolo26n-v26-recent-dense-selection-v1",
        "status": "SELECTION_FROZEN",
        "dense_lineage_sha256": enriched_completion_sha256,
        "protected_lineage_sha256": "2" * 64,
        "contract": {},
        "aggregate": {
            "unique_image_count": len(selected),
            "review_task_count": len(selected) + 2,
            "double_review_count": 2,
            "excluded_protected_count": 0,
            "clip_count": len(selected),
            "strata_counts": {"coverage": len(selected)},
        },
        "records": selected,
    }
    selection = {
        **selection_payload,
        "selection_sha256": _canonical_sha(selection_payload),
    }
    review_records = [
        {
            "review_round": "primary",
            "historical_dhash64": row["dhash64"],
            "blind_filename": records[index]["blind_filename"],
            **row,
        }
        for index, row in enumerate(selected)
    ]
    review_records.extend(
        {
            **review_records[index],
            "review_round": "double-review",
            "review_filename": f"double_{index}.jpg",
        }
        for index in range(2)
    )
    for row in review_records:
        # 실제 blind review index는 camera-night를 노출하지 않는다.
        row.pop("camera_night", None)
    review_index = {
        "schema": "yolo26n-v26-blind-review-index-v1",
        "selection_sha256": selection["selection_sha256"],
        "primary_count": len(selected),
        "double_review_count": 2,
        "records": review_records,
    }
    final_gt = {
        "schema": "yolo26n-v26-final-human-gt-v1",
        "status": "V26_HUMAN_GT_VALIDATED",
        "primary_export_sha256": "3" * 64,
        "double_review_export_sha256": "4" * 64,
        "adjudication_export_sha256": "5" * 64,
        "adjudication_index_sha256": "6" * 64,
        "review_index_sha256": "7" * 64,
        "selection_sha256": selection["selection_sha256"],
        "records": records,
    }
    source_window_sha256 = "8" * 64
    source_window = {
        "aggregate": {"accessible_clip_count": len(sources)},
        "lineage_sha256": "9" * 64,
        "sources": sources,
    }
    dense_completion = {
        "status": "DENSE_EXTRACTION_COMPLETE",
        "source_manifest_sha256": source_window_sha256,
        "source_lineage_sha256": source_window["lineage_sha256"],
        "clip_count": len(dense_clips),
        "sampled_frame_count": 120 * len(dense_clips),
        "sample_fps": 2.0,
        "clips": dense_clips,
    }
    enriched_completion = {
        "status": "GME_JOIN_COMPLETE",
        "dense_completion_sha256": dense_completion_sha256,
        "clip_count": len(dense_clips),
        "row_count": 120 * len(dense_clips),
        "detection_frame_count": 0,
        "clips": [
            {
                "clip_ref": row["clip_ref"],
                "private_ref": row["private_ref"],
                "row_count": row["sampled_frame_count"],
            }
            for row in dense_clips
        ],
    }
    return (
        final_gt,
        review_index,
        source_window,
        dense_completion,
        selection,
        source_window_sha256,
        enriched_completion,
        dense_completion_sha256,
        enriched_completion_sha256,
    )


def _build_plan(
    final_gt: dict[str, object],
    review_index: dict[str, object],
    source_window: dict[str, object],
    dense_completion: dict[str, object],
    selection: dict[str, object],
    source_window_sha256: str,
    enriched_completion: dict[str, object],
    dense_completion_sha256: str,
    enriched_completion_sha256: str,
) -> dict[str, object]:
    count = len(final_gt["records"])
    return build_recent_split_plan(
        final_gt,
        review_index,
        source_window,
        dense_completion,
        selection_manifest=selection,
        source_window_sha256=source_window_sha256,
        dense_completion_sha256=dense_completion_sha256,
        enriched_completion=enriched_completion,
        enriched_completion_sha256=enriched_completion_sha256,
        expected_recent_count=count,
        expected_dense_clip_count=count,
        expected_double_review_count=2,
        minimum_absent_count=count // 2,
        minimum_absent_fraction=0.5,
        expected_decision_source_counts={"primary": count},
        expected_strata={"coverage": count},
    )


def test_recent_split_is_deterministic_episode_grouped_and_camera_stratified() -> None:
    inputs = _inputs()
    first = _build_plan(*inputs)
    second = _build_plan(*inputs)

    assert first == second
    assert first["validation_fraction"] == 0.2
    assert first["recent_split_counts"]["train"] > first["recent_split_counts"]["val"] > 0
    assert set(first["camera_night_split_counts"]) == {
        "camera-0:2026-08-24",
        "camera-1:2026-08-24",
    }
    for counts in first["camera_night_split_counts"].values():
        assert counts["train"] > 0
        assert counts["val"] > 0
    by_episode: dict[str, set[str]] = {}
    for row in first["recent_records"]:
        by_episode.setdefault(row["episode_id"], set()).add(row["split"])
    assert all(len(splits) == 1 for splits in by_episode.values())


def test_near_duplicate_images_are_forced_into_the_same_split() -> None:
    inputs = list(_inputs(clips_per_camera=10))
    review_index = inputs[1]
    primary = [row for row in review_index["records"] if row["review_round"] == "primary"]
    primary[0]["historical_dhash64"] = "0000000000000000"
    primary[1]["historical_dhash64"] = "0000000000000001"

    plan = _build_plan(*inputs)
    split_by_sha = {row["image_sha256"]: row["split"] for row in plan["recent_records"]}
    final_gt = inputs[0]
    assert split_by_sha[final_gt["records"][0]["image_sha256"]] == split_by_sha[final_gt["records"][1]["image_sha256"]]
    assert plan["cross_split_dhash_leq8_count"] == 0


def test_same_source_sha_is_forced_into_one_split_component() -> None:
    inputs = list(_inputs(clips_per_camera=10))
    baseline = _build_plan(*inputs)
    train = next(row for row in baseline["recent_records"] if row["split"] == "train")
    val = next(row for row in baseline["recent_records"] if row["split"] == "val")
    dense = inputs[3]
    by_clip = {row["clip_ref"]: row for row in dense["clips"]}
    by_clip[val["clip_ref"]]["source_sha256"] = by_clip[train["clip_ref"]]["source_sha256"]

    plan = _build_plan(*inputs)
    rows = {row["clip_ref"]: row for row in plan["recent_records"]}
    assert rows[train["clip_ref"]]["split"] == rows[val["clip_ref"]]["split"]
    assert rows[train["clip_ref"]]["source_sha256"] == rows[val["clip_ref"]]["source_sha256"]
    assert plan["cross_split_source_sha256_count"] == 0


def test_final_gt_requires_provenance_quality_and_record_contracts() -> None:
    inputs = list(_inputs())

    broken = copy.deepcopy(inputs)
    broken[0]["primary_export_sha256"] = "not-a-sha"
    with pytest.raises(ValueError, match="final human GT.*SHA"):
        _build_plan(*broken)

    broken = copy.deepcopy(inputs)
    broken[0]["records"][0]["decision_source"] = "model"
    with pytest.raises(ValueError, match="decision source"):
        _build_plan(*broken)

    broken = copy.deepcopy(inputs)
    broken[0]["records"][0]["stratum"] = "unknown"
    with pytest.raises(ValueError, match="strat"):
        _build_plan(*broken)

    broken = copy.deepcopy(inputs)
    for row in broken[0]["records"]:
        if row["camera_night"] == "camera-0:2026-08-24":
            row["decision"] = "present"
            row["boxes"] = [[10.0, 20.0, 110.0, 220.0]]
    with pytest.raises(ValueError, match="camera-night.*absent"):
        build_recent_split_plan(
            broken[0], broken[1], broken[2], broken[3],
            selection_manifest=broken[4],
            source_window_sha256=broken[5],
            enriched_completion=broken[6],
            dense_completion_sha256=broken[7],
            enriched_completion_sha256=broken[8],
            expected_recent_count=12,
            expected_dense_clip_count=12,
            expected_double_review_count=2,
            minimum_absent_count=1,
            minimum_absent_fraction=0.1,
            expected_decision_source_counts={"primary": 12},
            expected_strata={"coverage": 12},
        )

    broken = copy.deepcopy(inputs)
    absent = next(row for row in broken[0]["records"] if row["decision"] == "absent")
    absent["decision"] = "present"
    absent["boxes"] = [[10.0, 20.0, 110.0, 220.0]]
    with pytest.raises(ValueError, match="absent.*minimum|absent fraction"):
        _build_plan(*broken)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda dense: dense.__setitem__("status", "INCOMPLETE"), "dense completion status"),
        (lambda dense: dense.__setitem__("clip_count", dense["clip_count"] - 1), "dense completion count"),
        (lambda dense: dense.__setitem__("source_manifest_sha256", "f" * 64), "source manifest SHA"),
        (lambda dense: dense["clips"].pop(), "dense completion count"),
    ],
)
def test_dense_completion_contract_is_fail_closed(mutation, message: str) -> None:
    inputs = list(_inputs())
    mutation(inputs[3])
    with pytest.raises(ValueError, match=message):
        _build_plan(*inputs)


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("selection", "enriched completion SHA"),
        ("enriched", "dense completion SHA"),
        ("dense", "source lineage"),
    ],
)
def test_raw_lineage_chain_is_fail_closed(target: str, message: str) -> None:
    inputs = list(_inputs())
    if target == "selection":
        inputs[4]["dense_lineage_sha256"] = "f" * 64
        payload = {key: value for key, value in inputs[4].items() if key != "selection_sha256"}
        inputs[4]["selection_sha256"] = _canonical_sha(payload)
        inputs[1]["selection_sha256"] = inputs[4]["selection_sha256"]
    elif target == "enriched":
        inputs[6]["dense_completion_sha256"] = "f" * 64
    else:
        inputs[3]["source_lineage_sha256"] = "f" * 64
    with pytest.raises(ValueError, match=message):
        _build_plan(*inputs)


def test_recent_split_rejects_invalid_gt_or_lineage_mismatch() -> None:
    inputs = list(_inputs())
    broken = copy.deepcopy(inputs)
    broken[0]["records"][2]["decision"] = "present"
    broken[0]["records"][2]["boxes"] = []
    with pytest.raises(ValueError, match="present.*bbox"):
        _build_plan(*broken)

    broken = copy.deepcopy(inputs)
    broken[1]["records"] = broken[1]["records"][:-3]
    with pytest.raises(ValueError, match="review index"):
        _build_plan(*broken)


def test_recent_split_rejects_missing_source_clip() -> None:
    inputs = list(_inputs())
    inputs[2]["sources"].pop()
    with pytest.raises(ValueError, match="source window"):
        _build_plan(*inputs)


def test_final_gt_artifact_hashes_are_checked_against_actual_files(tmp_path: Path) -> None:
    final_gt, *_ = _inputs()
    artifacts: dict[str, Path] = {}
    for index, field in enumerate(FINAL_GT_SHA_FIELDS):
        path = tmp_path / f"artifact-{index}"
        if field == "selection_sha256":
            selection_payload = {"schema": "selection-fixture"}
            final_gt[field] = _canonical_sha(selection_payload)
            path.write_text(
                json.dumps(
                    {**selection_payload, "selection_sha256": final_gt[field]},
                    sort_keys=True,
                    indent=2,
                )
            )
            assert hashlib.sha256(path.read_bytes()).hexdigest() != final_gt[field]
        else:
            path.write_bytes(f"artifact:{field}".encode())
            final_gt[field] = hashlib.sha256(path.read_bytes()).hexdigest()
        artifacts[field] = path

    dataset_builder.verify_final_gt_artifacts(final_gt, artifacts)
    artifacts["selection_sha256"].write_bytes(b"tampered")
    with pytest.raises(ValueError, match="selection_sha256"):
        dataset_builder.verify_final_gt_artifacts(final_gt, artifacts)


def _write_cvat_zip(
    path: Path, images: list[tuple[str, int, int, list[list[float]]]]
) -> None:
    lines = ["<annotations>"]
    for ordinal, (name, width, height, boxes) in enumerate(images):
        lines.append(
            f'<image id="{ordinal}" name="{name}" width="{width}" height="{height}">'
        )
        for x1, y1, x2, y2 in boxes:
            lines.append(
                '<box label="gecko" occluded="0" source="manual" '
                f'xtl="{x1}" ytl="{y1}" xbr="{x2}" ybr="{y2}" z_order="0"/>'
            )
        lines.append("</image>")
    lines.append("</annotations>")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("annotations.xml", "".join(lines))


def _semantic_inputs(tmp_path: Path) -> tuple[dict[str, object], dict[str, Path]]:
    final_gt, review_index, *_rest = _inputs()
    primary_rows = [
        row for row in review_index["records"] if row["review_round"] == "primary"
    ]
    double_rows = [
        row for row in review_index["records"] if row["review_round"] == "double-review"
    ]
    primary = tmp_path / "primary.zip"
    double = tmp_path / "double.zip"
    adjudication = tmp_path / "adjudication.zip"
    final_by_sha = {row["image_sha256"]: row for row in final_gt["records"]}
    _write_cvat_zip(
        primary,
        [
            (
                row["blind_filename"],
                final_by_sha[row["image_sha256"]]["width"],
                final_by_sha[row["image_sha256"]]["height"],
                final_by_sha[row["image_sha256"]]["boxes"],
            )
            for row in primary_rows
        ],
    )
    first = double_rows[0]
    adjudicated_box = [[30.0, 40.0, 130.0, 240.0]]
    _write_cvat_zip(
        double,
        [
            (
                row["review_filename"],
                960,
                720,
                adjudicated_box if row is first else final_by_sha[row["image_sha256"]]["boxes"],
            )
            for row in double_rows
        ],
    )
    _write_cvat_zip(adjudication, [("adjudication_0.jpg", 960, 720, adjudicated_box)])
    chosen = final_by_sha[first["image_sha256"]]
    chosen.update(
        decision="present", boxes=adjudicated_box, decision_source="adjudication"
    )
    selection_path = tmp_path / "selection.json"
    selection = _rest[2]
    selection_path.write_text(json.dumps(selection))
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review_index))
    adjudication_index = {
        "schema": "yolo26n-v26-human-gt-adjudication-v1",
        "count": 1,
        "source_primary_export_sha256": hashlib.sha256(primary.read_bytes()).hexdigest(),
        "source_double_review_export_sha256": hashlib.sha256(double.read_bytes()).hexdigest(),
        "selection_sha256": selection["selection_sha256"],
        "records": [
            {
                "adjudication_filename": "adjudication_0.jpg",
                "double_review_filename": first["review_filename"],
                "primary_filename": first["blind_filename"],
                "image_sha256": first["image_sha256"],
                "reasons": ["presence-disagreement"],
            }
        ],
    }
    adjudication_index_path = tmp_path / "adjudication-index.json"
    adjudication_index_path.write_text(json.dumps(adjudication_index))
    artifacts = {
        "primary_export_sha256": primary,
        "double_review_export_sha256": double,
        "adjudication_export_sha256": adjudication,
        "adjudication_index_sha256": adjudication_index_path,
        "review_index_sha256": review_path,
        "selection_sha256": selection_path,
    }
    for field, path in artifacts.items():
        if field == "selection_sha256":
            final_gt[field] = selection["selection_sha256"]
        else:
            final_gt[field] = hashlib.sha256(path.read_bytes()).hexdigest()
    return final_gt, artifacts


def test_final_gt_is_semantically_reconstructed_from_cvat_and_indices(
    tmp_path: Path,
) -> None:
    final_gt, artifacts = _semantic_inputs(tmp_path)
    dataset_builder.validate_final_gt_semantics(final_gt, artifacts)

    final_gt["records"][0]["boxes"] = [[1.0, 2.0, 3.0, 4.0]]
    with pytest.raises(ValueError, match="final GT semantic mismatch"):
        dataset_builder.validate_final_gt_semantics(final_gt, artifacts)


def test_final_gt_rejects_selection_review_image_set_mismatch(tmp_path: Path) -> None:
    final_gt, artifacts = _semantic_inputs(tmp_path)
    review_path = artifacts["review_index_sha256"]
    review = json.loads(review_path.read_text())
    primary = next(row for row in review["records"] if row["review_round"] == "primary")
    primary["image_sha256"] = "f" * 64
    review_path.write_text(json.dumps(review))
    final_gt["review_index_sha256"] = hashlib.sha256(review_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="selection/review image lineage"):
        dataset_builder.validate_final_gt_semantics(final_gt, artifacts)


def test_double_review_set_must_match_selection_exactly(tmp_path: Path) -> None:
    final_gt, artifacts = _semantic_inputs(tmp_path)
    review_path = artifacts["review_index_sha256"]
    review = json.loads(review_path.read_text())
    doubles = [row for row in review["records"] if row["review_round"] == "double-review"]
    doubles[1]["image_sha256"] = doubles[0]["image_sha256"]
    review_path.write_text(json.dumps(review))
    final_gt["review_index_sha256"] = hashlib.sha256(review_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="double-review selection set"):
        dataset_builder.validate_final_gt_semantics(final_gt, artifacts)


def test_adjudication_index_reasons_and_lineage_are_fail_closed(tmp_path: Path) -> None:
    final_gt, artifacts = _semantic_inputs(tmp_path)
    index_path = artifacts["adjudication_index_sha256"]
    index = json.loads(index_path.read_text())
    index["records"][0]["reasons"] = ["unsupported-reason"]
    index_path.write_text(json.dumps(index))
    final_gt["adjudication_index_sha256"] = hashlib.sha256(index_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="adjudication.*reason"):
        dataset_builder.validate_final_gt_semantics(final_gt, artifacts)


def test_adjudication_index_must_cover_every_computed_conflict(tmp_path: Path) -> None:
    final_gt, artifacts = _semantic_inputs(tmp_path)
    index_path = artifacts["adjudication_index_sha256"]
    index = json.loads(index_path.read_text())
    index["records"] = []
    index["count"] = 0
    index_path.write_text(json.dumps(index))
    final_gt["adjudication_index_sha256"] = hashlib.sha256(index_path.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="adjudication conflict set"):
        dataset_builder.validate_final_gt_semantics(final_gt, artifacts)


def _jpeg() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (32, 24), (40, 80, 120)).save(output, format="JPEG")
    return output.getvalue()


def _materialization_inputs(
    tmp_path: Path,
) -> tuple[Path, dict[str, object], dict[str, object], dict[str, object], Path]:
    parent = tmp_path / "parent"
    records = []
    regression_digest = hashlib.sha256()
    ordinal = 0
    for split, count in (("train", 4), ("val", 2), ("test", 1)):
        for _ in range(count):
            ordinal += 1
            sequence = f"P{ordinal:03d}"
            payload = _jpeg() + bytes([ordinal])
            label_payload = b"0 0.500000000 0.500000000 0.500000000 0.500000000\n"
            image_path = parent / "images" / split / f"{sequence}.jpg"
            label_path = parent / "labels" / split / f"{sequence}.txt"
            image_path.parent.mkdir(parents=True, exist_ok=True)
            label_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(payload)
            label_path.write_bytes(label_payload)
            if split in {"val", "test"}:
                regression_digest.update(payload)
                regression_digest.update(label_payload)
            records.append(
                {
                    "sequence": sequence,
                    "split": split,
                    "image_path": f"images/{split}/{sequence}.jpg",
                    "label_path": f"labels/{split}/{sequence}.txt",
                    "image_sha256": hashlib.sha256(payload).hexdigest(),
                    "box_count": 1,
                    "positive": True,
                    "source_dataset": "v25-test-parent",
                }
            )
    parent_manifest = {
        "schema": "yolo26n-owner-dataset-v25",
        "status": "V25_DATASET_READY",
        "split_counts": {"train": 4, "val": 2, "test": 1},
        "image_count": 7,
        "parent_val_test_sha256": regression_digest.hexdigest(),
        "records": records,
    }
    integrity_manifest = {
        "schema": "yolo26n-v25-parent-integrity-v1",
        "status": "V25_PARENT_INTEGRITY_APPROVED",
        "parent_manifest_sha256": _canonical_sha(parent_manifest),
        "parent_val_test_sha256": regression_digest.hexdigest(),
        "image_count": 7,
        "split_counts": {"train": 4, "val": 2, "test": 1},
        "records": [
            {
                "sequence": row["sequence"],
                "split": row["split"],
                "image_path": row["image_path"],
                "label_path": row["label_path"],
                "image_sha256": row["image_sha256"],
                "label_sha256": hashlib.sha256(
                    (parent / row["label_path"]).read_bytes()
                ).hexdigest(),
                "box_count": row["box_count"],
            }
            for row in records
        ],
    }
    integrity_manifest["records_sha256"] = _canonical_sha(
        integrity_manifest["records"]
    )
    recent_payloads = [_jpeg() + b"recent-a", _jpeg() + b"recent-b"]
    recent_records = []
    zip_path = tmp_path / "recent.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for ordinal, (payload, split) in enumerate(
            zip(recent_payloads, ("train", "val")), start=1
        ):
            filename = f"frame_{ordinal:024x}.jpg"
            archive.writestr(f"images/{filename}", payload)
            recent_records.append(
                {
                    "absolute_timestamp_ms": ordinal,
                    "blind_filename": filename,
                    "boxes": [],
                    "camera_night": "camera:2026-08-24",
                    "clip_ref": f"clip-{ordinal}",
                    "decision": "absent",
                    "dhash64": f"{ordinal:016x}",
                    "episode_id": f"episode-{ordinal}",
                    "height": 24,
                    "image_sha256": hashlib.sha256(payload).hexdigest(),
                    "source_sha256": hashlib.sha256(f"source-{ordinal}".encode()).hexdigest(),
                    "split": split,
                    "timestamp_ms": 0,
                    "width": 32,
                }
            )
    split_plan = {
        "schema": "yolo26n-v26-recent-split-plan-v1",
        "status": "V26_RECENT_SPLIT_READY",
        "recent_image_count": 2,
        "recent_split_counts": {"train": 1, "val": 1},
        "recent_records": recent_records,
    }
    return parent, parent_manifest, integrity_manifest, split_plan, zip_path


def test_materialize_keeps_v25_regression_and_all_byte_hashes_pinned(
    tmp_path: Path,
) -> None:
    parent, parent_manifest, integrity_manifest, split_plan, zip_path = _materialization_inputs(tmp_path)
    output = tmp_path / "v26"

    result = materialize_v26_dataset(
        parent_dataset=parent,
        parent_manifest=parent_manifest,
        parent_integrity_manifest=integrity_manifest,
        recent_split_plan=split_plan,
        recent_zip=zip_path,
        output_dir=output,
        expected_parent_splits={"train": 4, "val": 2, "test": 1},
    )

    assert result["active_split_counts"] == {"train": 5, "val": 1}
    manifest = json.loads((output / "manifest.private.json").read_text())
    assert manifest["source_commit"] == subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert manifest["builder_sha256"] == hashlib.sha256(
        Path("scripts/build_yolo26n_v26_dataset.py").read_bytes()
    ).hexdigest()
    assert manifest["regression_split_counts"] == {"regression-val": 2, "regression-test": 1}
    assert len(list((output / "images" / "regression-val").glob("*.jpg"))) == 2
    assert len(list((output / "images" / "regression-test").glob("*.jpg"))) == 1
    assert "regression" not in (output / "data.yaml").read_text()
    assert manifest["data_yaml_sha256"] == hashlib.sha256(
        (output / "data.yaml").read_bytes()
    ).hexdigest()
    parent_manifest_sha = _canonical_sha(parent_manifest)
    for record in manifest["records"]:
        assert hashlib.sha256((output / record["image_path"]).read_bytes()).hexdigest() == record["image_sha256"]
        assert hashlib.sha256((output / record["label_path"]).read_bytes()).hexdigest() == record["label_sha256"]
        if record["source_dataset"] == "v25-test-parent":
            assert record["parent_manifest_sha256"] == parent_manifest_sha
    with pytest.raises(FileExistsError):
        materialize_v26_dataset(
            parent_dataset=parent,
            parent_manifest=parent_manifest,
            parent_integrity_manifest=integrity_manifest,
            recent_split_plan=split_plan,
            recent_zip=zip_path,
            output_dir=output,
            expected_parent_splits={"train": 4, "val": 2, "test": 1},
        )


def test_materialize_rejects_parent_regression_label_byte_drift(tmp_path: Path) -> None:
    parent, parent_manifest, integrity_manifest, split_plan, zip_path = _materialization_inputs(tmp_path)
    regression = next(row for row in parent_manifest["records"] if row["split"] == "val")
    (parent / regression["label_path"]).write_text(
        "0 0.400000000 0.500000000 0.500000000 0.500000000\n"
    )

    with pytest.raises(ValueError, match="parent integrity.*label SHA|parent val/test SHA"):
        materialize_v26_dataset(
            parent_dataset=parent,
            parent_manifest=parent_manifest,
            parent_integrity_manifest=integrity_manifest,
            recent_split_plan=split_plan,
            recent_zip=zip_path,
            output_dir=tmp_path / "v26",
            expected_parent_splits={"train": 4, "val": 2, "test": 1},
        )


def test_materialize_rejects_declared_parent_label_sha_mismatch(tmp_path: Path) -> None:
    parent, parent_manifest, integrity_manifest, split_plan, zip_path = _materialization_inputs(tmp_path)
    integrity_manifest["records"][0]["label_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="parent.*(?:label SHA|integrity manifest)"):
        materialize_v26_dataset(
            parent_dataset=parent,
            parent_manifest=parent_manifest,
            parent_integrity_manifest=integrity_manifest,
            recent_split_plan=split_plan,
            recent_zip=zip_path,
            output_dir=tmp_path / "v26",
            expected_parent_splits={"train": 4, "val": 2, "test": 1},
        )


def test_materialize_rejects_parent_train_label_byte_drift(tmp_path: Path) -> None:
    parent, parent_manifest, integrity_manifest, split_plan, zip_path = _materialization_inputs(tmp_path)
    train = next(row for row in parent_manifest["records"] if row["split"] == "train")
    (parent / train["label_path"]).write_text("")

    with pytest.raises(ValueError, match="parent integrity.*label SHA"):
        materialize_v26_dataset(
            parent_dataset=parent,
            parent_manifest=parent_manifest,
            parent_integrity_manifest=integrity_manifest,
            recent_split_plan=split_plan,
            recent_zip=zip_path,
            output_dir=tmp_path / "v26",
            expected_parent_splits={"train": 4, "val": 2, "test": 1},
        )


def test_materialize_rejects_parent_integrity_records_digest_drift(
    tmp_path: Path,
) -> None:
    parent, parent_manifest, integrity_manifest, split_plan, zip_path = _materialization_inputs(tmp_path)
    integrity_manifest["records_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="parent integrity manifest contract"):
        materialize_v26_dataset(
            parent_dataset=parent,
            parent_manifest=parent_manifest,
            parent_integrity_manifest=integrity_manifest,
            recent_split_plan=split_plan,
            recent_zip=zip_path,
            output_dir=tmp_path / "v26-integrity-digest-drift",
            expected_parent_splits={"train": 4, "val": 2, "test": 1},
        )
