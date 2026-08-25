from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path

from PIL import Image
import pytest

from scripts.build_yolo26n_gate_operational_candidates_v24 import (
    build_gate_candidate_plan,
    build_gate_lineage_rows,
    collect_image_metadata,
    select_policy_audit,
    validate_full_policy_review,
    validate_owner_policy_audit,
    write_candidate_bundle,
    write_full_policy_review_bundle,
)


SEED = "yolo26n-gate-operational-reuse-v24-v1"


def _sha(index: int) -> str:
    return f"{index:064x}"[-64:]


def _document(
    rows: list[tuple[str, int]],
    *,
    annotations: dict[int, list[list[float]]],
) -> dict[str, object]:
    images = [
        {
            "id": image_id,
            "file_name": file_name,
            "width": 100,
            "height": 80,
        }
        for file_name, image_id in rows
    ]
    annotation_rows: list[dict[str, object]] = []
    annotation_id = 1
    for image_id, boxes in annotations.items():
        for box in boxes:
            annotation_rows.append(
                {
                    "id": annotation_id,
                    "image_id": image_id,
                    "category_id": 1,
                    "bbox": box,
                    "iscrowd": 0,
                }
            )
            annotation_id += 1
    return {
        "images": images,
        "annotations": annotation_rows,
        "categories": [{"id": 1, "name": "gecko"}],
    }


def _metadata(rows: list[tuple[str, int]]) -> dict[str, dict[str, object]]:
    return {
        file_name: {
            "image_sha256": _sha(image_id),
            "dhash64": f"{image_id:016x}"[-16:],
            "decoded_width": 100,
            "decoded_height": 80,
        }
        for file_name, image_id in rows
    }


def _lineage(rows: list[tuple[str, int]]) -> list[dict[str, str]]:
    return [
        {
            "source_relpath": file_name,
            "source_clip_ref": file_name.split("/")[1],
            "camera_night_ref": f"night-{image_id:02d}",
        }
        for file_name, image_id in rows
        if file_name.startswith("operational/")
    ]


def test_selector_rejects_non_operational_and_quarantines_oob_bbox() -> None:
    rows = [
        ("operational/clip-a/f000.jpg", 1),
        ("operational/clip-b/f000.jpg", 2),
        ("roboflow/day/f000.jpg", 3),
    ]
    document = _document(
        rows,
        annotations={
            1: [[10.0, 10.0, 30.0, 20.0]],
            2: [[-1.0, 10.0, 30.0, 20.0]],
            3: [[10.0, 10.0, 30.0, 20.0]],
        },
    )

    plan = build_gate_candidate_plan(
        coco_documents=[document],
        image_metadata=_metadata(rows),
        protected_records=[],
        lineage_rows=_lineage(rows),
        seed=SEED,
    )

    assert plan["source_counts"] == {"operational": 2}
    assert plan["exclusion_counts"]["non_operational_source"] == 1
    assert plan["exclusion_counts"]["invalid_bbox_quarantine"] == 1
    assert plan["selected_count"] == 1
    assert plan["selected_records"][0]["source_relpath"] == rows[0][0]


def test_selector_excludes_sha_source_night_and_unresolved_lineage() -> None:
    rows = [
        ("operational/clip-sha/f000.jpg", 1),
        ("operational/clip-source/f000.jpg", 2),
        ("operational/clip-night/f000.jpg", 3),
        ("operational/clip-unresolved/f000.jpg", 4),
        ("operational/clip-perceptual/f000.jpg", 5),
    ]
    document = _document(rows, annotations={})
    lineage_rows = _lineage(rows[:3] + rows[4:])
    lineage_rows[2]["camera_night_ref"] = "protected-night"

    plan = build_gate_candidate_plan(
        coco_documents=[document],
        image_metadata=_metadata(rows),
        protected_records=[
            {
                "image_sha256": _sha(1),
                "dhash64": "ffffffffffffffff",
                "source_clip_ref": "other-source",
                "camera_night_ref": "other-night",
            },
            {
                "image_sha256": _sha(99),
                "dhash64": "0000000000000004",
                "source_clip_ref": "clip-source",
                "camera_night_ref": "protected-night",
            },
            {
                "image_sha256": _sha(98),
                "dhash64": "0000000000000004",
                "source_clip_ref": "other-perceptual-source",
                "camera_night_ref": "other-perceptual-night",
            },
        ],
        lineage_rows=lineage_rows,
        seed=SEED,
    )

    assert plan["selected_count"] == 0
    assert plan["exclusion_counts"] == {
        "camera_night_overlap": 1,
        "exact_sha_overlap": 1,
        "protected_dhash_overlap": 1,
        "source_clip_overlap": 1,
        "unresolved_lineage": 1,
    }


def test_selector_is_reversed_input_deterministic_and_caps_clip_at_two() -> None:
    rows = [
        ("operational/clip-a/f000.jpg", 1),
        ("operational/clip-a/f001.jpg", 2),
        ("operational/clip-a/f002.jpg", 3),
        ("operational/clip-a/f003.jpg", 4),
    ]
    annotations = {
        1: [[10.0, 10.0, 30.0, 20.0]],
        2: [[12.0, 10.0, 30.0, 20.0]],
        3: [[14.0, 10.0, 30.0, 20.0]],
    }
    document = _document(rows, annotations=annotations)
    reverse_document = _document(list(reversed(rows)), annotations=annotations)

    kwargs = {
        "image_metadata": _metadata(rows),
        "protected_records": [],
        "lineage_rows": _lineage(rows),
        "seed": SEED,
    }
    forward = build_gate_candidate_plan(coco_documents=[document], **kwargs)
    reverse = build_gate_candidate_plan(coco_documents=[reverse_document], **kwargs)

    assert forward["selected_records"] == reverse["selected_records"]
    assert len(forward["selected_records"]) == 2
    assert Counter(row["positive"] for row in forward["selected_records"]) == {
        True: 1,
        False: 1,
    }
    assert Counter(
        row["source_clip_ref"] for row in forward["selected_records"]
    ) == {"clip-a": 2}


def test_selector_returns_shortage_below_exact_minimums() -> None:
    rows = [(f"operational/clip-{index}/f000.jpg", index) for index in range(1, 5)]
    plan = build_gate_candidate_plan(
        coco_documents=[_document(rows, annotations={})],
        image_metadata=_metadata(rows),
        protected_records=[],
        lineage_rows=_lineage(rows),
        seed=SEED,
    )

    assert plan["status"] == "V24_GATE_REUSE_SHORTAGE"
    assert plan["shortfall"] == {
        "negative": 96,
        "positive": 150,
        "source_clip": 196,
        "total": 296,
    }


def test_policy_audit_selects_exact_40_positive_and_20_negative() -> None:
    records = []
    for index in range(1, 81):
        records.append(
            {
                "source_relpath": f"operational/clip-{index:03d}/f000.jpg",
                "source_clip_ref": f"clip-{index:03d}",
                "camera_night_ref": f"night-{index:03d}",
                "image_sha256": _sha(index),
                "dhash64": f"{index:016x}",
                "positive": index <= 50,
                "box_count": 2 if index <= 5 else int(index <= 50),
                "width": 100,
                "height": 80,
                "boxes_xywh": [[10.0, 10.0, 30.0, 20.0]] if index <= 50 else [],
            }
        )

    selected = select_policy_audit(records, seed=SEED)

    assert len(selected) == 60
    assert Counter(row["positive"] for row in selected) == {True: 40, False: 20}
    assert len({row["source_clip_ref"] for row in selected}) == 60
    assert [row["sequence"] for row in selected] == [
        f"G{index:04d}" for index in range(1, 61)
    ]


def test_collect_image_metadata_binds_sha_dimensions_and_dhash(tmp_path: Path) -> None:
    relative = "operational/clip-a/f000.jpg"
    image_path = tmp_path / relative
    image_path.parent.mkdir(parents=True)
    image = Image.new("RGB", (11, 7), "black")
    for x in range(6, 11):
        for y in range(7):
            image.putpixel((x, y), (255, 255, 255))
    image.save(image_path, format="JPEG", quality=95)

    first = collect_image_metadata(tmp_path, [relative])
    second = collect_image_metadata(tmp_path, [relative])

    assert first == second
    assert first[relative]["image_sha256"] == hashlib.sha256(
        image_path.read_bytes()
    ).hexdigest()
    assert first[relative]["decoded_width"] == 11
    assert first[relative]["decoded_height"] == 7
    assert len(first[relative]["dhash64"]) == 16


@pytest.mark.parametrize(
    "relative",
    ["../outside.jpg", "/absolute.jpg", "roboflow/f000.jpg", "operational/f000.png"],
)
def test_collect_image_metadata_rejects_paths_outside_contract(
    tmp_path: Path, relative: str
) -> None:
    with pytest.raises(ValueError, match="path contract"):
        collect_image_metadata(tmp_path, [relative])


def test_collect_image_metadata_rejects_duplicate_and_invalid_bytes(
    tmp_path: Path,
) -> None:
    relative = "operational/clip-a/f000.jpg"
    image_path = tmp_path / relative
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"not-a-jpeg")

    with pytest.raises(ValueError, match="decode failed"):
        collect_image_metadata(tmp_path, [relative])

    Image.new("RGB", (4, 4), "white").save(image_path, format="JPEG")
    with pytest.raises(ValueError, match="path contract"):
        collect_image_metadata(tmp_path, [relative, relative])


def _audit_rows() -> list[dict[str, object]]:
    return [
        {
            "sequence": f"G{index:04d}",
            "positive": index <= 40,
            "source_clip_ref": f"clip-{index:03d}",
            "expected_policy": "review",
        }
        for index in range(1, 61)
    ]


def test_owner_policy_audit_accepts_exact_40_positive_and_20_negative() -> None:
    index_rows = _audit_rows()
    verdict_rows = [
        {"sequence": row["sequence"], "verdict": "accept"} for row in index_rows
    ]

    summary = validate_owner_policy_audit(index_rows, verdict_rows)

    assert summary["status"] == "V24_GATE_AUDIT_ACCEPTED"
    assert summary["positive_count"] == 40
    assert summary["negative_count"] == 20
    assert summary["db_write_count"] == 0


@pytest.mark.parametrize("bad", ["", "yes", True, 1, "fix_box", "wrong_negative"])
def test_owner_policy_audit_rejects_unknown_verdict(bad: object) -> None:
    index_rows = _audit_rows()
    verdict_rows = [
        {"sequence": row["sequence"], "verdict": "accept"} for row in index_rows
    ]
    verdict_rows[0]["verdict"] = bad

    with pytest.raises(ValueError, match="verdict"):
        validate_owner_policy_audit(index_rows, verdict_rows)


def test_owner_policy_audit_requires_full_review_after_any_policy_error() -> None:
    index_rows = _audit_rows()
    verdict_rows = [
        {"sequence": row["sequence"], "verdict": "accept"} for row in index_rows
    ]
    verdict_rows[0]["verdict"] = "positive_needs_fix"
    verdict_rows[-1]["verdict"] = "negative_mislabeled"

    summary = validate_owner_policy_audit(index_rows, verdict_rows)

    assert summary["status"] == "V24_GATE_POSITIVE_AND_NEGATIVE_FULL_REVIEW_REQUIRED"
    assert summary["positive_needs_fix_count"] == 1
    assert summary["negative_mislabeled_count"] == 1


def test_policy_audit_allocates_shared_clips_without_duplicate_sources() -> None:
    records: list[dict[str, object]] = []
    for index in range(1, 41):
        for positive in (True, False):
            records.append(
                {
                    "source_clip_ref": f"shared-{index:03d}",
                    "image_sha256": _sha(index * 2 + int(positive)),
                    "positive": positive,
                    "box_count": int(positive),
                }
            )
    for index in range(41, 61):
        records.append(
            {
                "source_clip_ref": f"negative-{index:03d}",
                "image_sha256": _sha(index * 2),
                "positive": False,
                "box_count": 0,
            }
        )

    selected = select_policy_audit(records, seed=SEED)

    assert len(selected) == 60
    assert Counter(row["positive"] for row in selected) == {True: 40, False: 20}
    assert len({row["source_clip_ref"] for row in selected}) == 60


def test_candidate_bundle_is_private_blind_and_no_overwrite(tmp_path: Path) -> None:
    image_root = tmp_path / "images"
    records: list[dict[str, object]] = []
    for index in range(1, 61):
        relative = f"operational/clip-{index:03d}/f000.jpg"
        image_path = image_root / relative
        image_path.parent.mkdir(parents=True)
        Image.new("RGB", (20, 20), "white").save(image_path, format="JPEG")
        records.append(
            {
                "source_relpath": relative,
                "source_clip_ref": f"clip-{index:03d}",
                "camera_night_ref": f"night-{index:03d}",
                "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                "dhash64": f"{index:016x}",
                "positive": index <= 40,
                "box_count": int(index <= 40),
                "width": 20,
                "height": 20,
                "boxes_xywh": [[2.0, 3.0, 8.0, 9.0]] if index <= 40 else [],
            }
        )
    plan = {
        "schema": "yolo26n-gate-operational-candidates-v24-plan-v1",
        "status": "V24_GATE_CANDIDATES_READY",
        "seed": SEED,
        "exclusion_counts": {"invalid_bbox_quarantine": 16},
        "selected_records": records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }
    output = tmp_path / "bundle"

    result = write_candidate_bundle(plan, image_root=image_root, output_dir=output)

    assert result["status"] == "V24_GATE_HUMAN_AUDIT_REQUIRED"
    assert len(list((output / "audit-frames").glob("G*.jpg"))) == 60
    with (output / "audit-index.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == ["sequence", "filename", "expected_policy"]
    assert rows[0] == {
        "sequence": "G0001",
        "filename": "G0001.jpg",
        "expected_policy": "review",
    }
    with (output / "owner-verdict.csv").open(newline="", encoding="utf-8") as handle:
        verdict_rows = list(csv.DictReader(handle))
    assert list(verdict_rows[0]) == ["sequence", "verdict"]
    assert verdict_rows[0] == {"sequence": "G0001", "verdict": ""}
    assert len(verdict_rows) == 60
    assert "source" not in (output / "audit-index.csv").read_text(encoding="utf-8")
    manifest = json.loads(
        (output / "candidate-manifest.private.json").read_text(encoding="utf-8")
    )
    assert manifest["selected_count"] == 60
    for private_file in output.glob("*.private.json"):
        assert os.stat(private_file).st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_candidate_bundle(plan, image_root=image_root, output_dir=output)


def test_gate_lineage_uses_db_camera_and_activity_night() -> None:
    clip_id = "12345678-1234-4234-9234-123456789abc"
    source = f"operational/20260720-233000_{clip_id}/f000.jpg"

    rows = build_gate_lineage_rows(
        [source, "operational/legacy01/f000.jpg"],
        [
            {
                "id": clip_id,
                "camera_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "started_at": "2026-07-20T14:30:00+00:00",
            }
        ],
    )

    assert len(rows) == 1
    assert rows[0]["source_relpath"] == source
    assert rows[0]["source_clip_ref"] == clip_id
    assert len(rows[0]["camera_night_ref"]) == 16


def test_full_positive_review_bundle_contains_every_positive_only(tmp_path: Path) -> None:
    image_root = tmp_path / "images"
    records: list[dict[str, object]] = []
    for index, positive in enumerate((True, False, True), 1):
        relative = f"operational/clip-{index:03d}/f000.jpg"
        image_path = image_root / relative
        image_path.parent.mkdir(parents=True)
        Image.new("RGB", (20, 20), "white").save(image_path, format="JPEG")
        records.append(
            {
                "source_relpath": relative,
                "source_clip_ref": f"clip-{index:03d}",
                "camera_night_ref": f"night-{index:03d}",
                "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                "dhash64": f"{index:016x}",
                "positive": positive,
                "box_count": int(positive),
                "width": 20,
                "height": 20,
                "boxes_xywh": [[2.0, 3.0, 8.0, 9.0]] if positive else [],
            }
        )
    output = tmp_path / "positive-review"

    result = write_full_policy_review_bundle(
        records,
        audit_summary={"status": "V24_GATE_POSITIVE_FULL_REVIEW_REQUIRED"},
        review_class="positive",
        image_root=image_root,
        output_dir=output,
    )

    assert result["status"] == "V24_GATE_POSITIVE_FULL_REVIEW_PENDING"
    assert result["review_count"] == 2
    assert sorted(path.name for path in (output / "review-frames").glob("*.jpg")) == [
        "P0001.jpg",
        "P0002.jpg",
    ]
    with (output / "owner-verdict.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {"sequence": "P0001", "verdict": ""},
        {"sequence": "P0002", "verdict": ""},
    ]


def test_full_positive_review_quarantines_every_needs_fix_row() -> None:
    records = [
        {
            "sequence": f"P{index:04d}",
            "positive": True,
            "source_clip_ref": f"clip-{index:04d}",
            "image_sha256": _sha(index),
        }
        for index in range(1, 4)
    ]
    verdicts = [
        {"sequence": "P0001", "verdict": "accept"},
        {"sequence": "P0002", "verdict": "positive_needs_fix"},
        {"sequence": "P0003", "verdict": "accept"},
    ]

    result = validate_full_policy_review(
        records, verdicts, review_class="positive", minimum_accepted=2
    )

    assert result["status"] == "V24_GATE_POSITIVE_FULL_REVIEW_ACCEPTED"
    assert result["accepted_count"] == 2
    assert result["quarantined_count"] == 1
    assert [row["sequence"] for row in result["accepted_records"]] == [
        "P0001",
        "P0003",
    ]
