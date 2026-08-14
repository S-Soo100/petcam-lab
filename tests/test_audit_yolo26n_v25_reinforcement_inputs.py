from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import csv
import io
from pathlib import Path

import pytest
from PIL import Image

import scripts.audit_yolo26n_v25_reinforcement_inputs as audit


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _accepted_record(index: int, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "source_relpath": f"operational/private-{index:04d}/frame.jpg",
        "source_clip_ref": f"private-clip-{index:04d}",
        "camera_night_ref": f"private-night-{index:04d}",
        "image_sha256": _sha(f"gate-image-{index}"),
        "dhash64": f"{index:016x}",
        "width": 100,
        "height": 80,
        "boxes_xywh": [[10.0, 12.0, 30.0, 20.0]],
        "box_count": 1,
        "positive": True,
    }
    row.update(overrides)
    return row


def _accepted_manifest(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema": "yolo26n-gate-operational-reviewed-candidates-v24-v1",
        "status": "V24_GATE_REVIEWED_CANDIDATES_READY",
        "selected_count": len(records),
        "positive_count": sum(row["positive"] is True for row in records),
        "negative_count": sum(row["positive"] is False for row in records),
        "quarantined_positive_count": 0,
        "source_clip_count": len({str(row["source_clip_ref"]) for row in records}),
        "owner_verdict_sha256": "a" * 64,
        "selected_records": records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def _review_evidence(
    records: list[dict[str, object]],
) -> tuple[dict[str, object], dict[str, object], dict[str, int]]:
    positives = [dict(row, sequence=f"P{index + 1:04d}") for index, row in enumerate(records) if row["positive"] is True]
    negative_count = sum(row["positive"] is False for row in records)
    sample = {
        "schema": "yolo26n-gate-operational-owner-audit-v24-v1",
        "status": "V24_GATE_POSITIVE_FULL_REVIEW_REQUIRED",
        "accepted_count": len(records) - int(bool(positives)),
        "positive_count": len(positives),
        "positive_needs_fix_count": int(bool(positives)),
        "negative_count": negative_count,
        "negative_mislabeled_count": 0,
        "owner_verdict_sha256": "b" * 64,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }
    full = {
        "schema": "yolo26n-gate-operational-full-policy-review-result-v24-v1",
        "status": "V24_GATE_POSITIVE_FULL_REVIEW_ACCEPTED",
        "review_class": "positive",
        "review_count": len(positives),
        "accepted_count": len(positives),
        "quarantined_count": 0,
        "minimum_accepted": min(1, len(positives)),
        "accepted_records": positives,
        "quarantined_records": [],
        "owner_verdict_sha256": "a" * 64,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }
    contract = {
        "sample_positive": len(positives),
        "sample_negative": negative_count,
        "sample_positive_needs_fix": int(bool(positives)),
        "sample_negative_mislabeled": 0,
        "sample_accepted": len(records) - int(bool(positives)),
        "full_review": len(positives),
        "full_accepted": len(positives),
        "full_quarantined": 0,
        "minimum_accepted": min(1, len(positives)),
        "selected_positive": len(positives),
        "selected_negative": negative_count,
        "selected_source_clip": len({str(row["source_clip_ref"]) for row in records}),
    }
    return sample, full, contract


def _audit_gate_inclusion(**kwargs):
    selected = kwargs["accepted_review"]["selected_records"]
    sample, full, contract = _review_evidence(selected)
    return audit.audit_gate_inclusion(
        sample_audit_summary=sample,
        positive_full_review_result=full,
        expected_review_contract=contract,
        **kwargs,
    )


def _dataset_manifest(
    gate_records: list[dict[str, object]],
    *,
    extra_records: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    records: list[dict[str, object]] = []
    for index, row in enumerate(gate_records):
        records.append(
            {
                "sequence": f"G{index + 1:04d}",
                "split": "train",
                "image_path": f"images/train/G{index + 1:04d}.jpg",
                "label_path": f"labels/train/G{index + 1:04d}.txt",
                "image_sha256": row["image_sha256"],
                "box_count": row["box_count"],
                "positive": row["positive"],
                "source_dataset": "gate-operational-v24",
                "camera_night_group": row["camera_night_ref"],
                "final_holdout_eligible": False,
            }
        )
    records.extend(extra_records or [])
    counts = {
        "train": sum(row["split"] == "train" for row in records),
        "val": sum(row["split"] == "val" for row in records),
        "test": sum(row["split"] == "test" for row in records),
    }
    return {
        "schema": "yolo26n-owner-dataset-v24",
        "image_count": len(records),
        "split_counts": counts,
        "source_dataset_counts": {
            "gate-operational-v24": len(gate_records),
            "base-v23": len(records) - len(gate_records),
        },
        "records": records,
        "gate_operational_added_count": len(gate_records),
        "future_holdout_required": True,
        "evaluation_tier": "development",
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def _historical(
    rows: list[dict[str, str]],
    *,
    unique_count: int | None = None,
) -> dict[str, object]:
    return {
        "schema": "yolo26n-v24b-historical-fingerprint-exclusions-v1",
        "status": "V24B_HISTORICAL_FINGERPRINTS_FROZEN",
        "freeze_sha256": "a" * 64,
        "artifact_sha256": {
            "dataset": "b" * 64,
            "internal-test151": "c" * 64,
            "owner-external60": "d" * 64,
            "owner-external-snapshot": "e" * 64,
        },
        "role_counts": {
            "dataset": 1762,
            "internal-test151": 151,
            "owner-external60": 60,
        },
        "unique_image_count": len(rows) if unique_count is None else unique_count,
        "fingerprint_policy": {
            "algorithm": "dhash64",
            "version": "pillow-rgb-luma-9x8-box-right-gt-left-v1",
            "pillow_version": "12.2.0",
            "scope": "global-historical",
            "hamming_reject_max_distance": 2,
        },
        "records": rows,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }


def _private_json(path: Path, value: object) -> Path:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _baseline() -> tuple[
    list[dict[str, object]], dict[str, object], dict[str, object]
]:
    accepted = [_accepted_record(0), _accepted_record(1, positive=False, box_count=0, boxes_xywh=[])]
    dataset = _dataset_manifest(accepted)
    historical = _historical(
        [
            {"image_sha256": str(row["image_sha256"]), "dhash64": str(row["dhash64"])}
            for row in accepted
        ]
    )
    return accepted, dataset, historical


def test_all_reviewed_gate_records_already_in_train_returns_ready_zero() -> None:
    accepted, dataset, historical = _baseline()

    result = _audit_gate_inclusion(
        accepted_review=_accepted_manifest(accepted),
        v24_dataset=dataset,
        historical_fingerprints=historical,
        expected_selected_count=2,
        expected_dataset_counts={"train": 2, "val": 0, "test": 0},
        expected_historical_unique_count=2,
    )

    assert result["schema"] == "yolo26n-v25-reinforcement-input-audit-v1"
    assert result["status"] == "V25_HISTORICAL_AUDIT_READY"
    assert result["counts"] == {
        "accepted_review": 2,
        "already_in_v24_train": 2,
        "new_train_eligible": 0,
        "protected_exact_overlap": 0,
        "protected_perceptual_overlap": 0,
    }
    assert result["new_train_eligible_records"] == []
    assert result["db_write_count"] == result["r2_write_count"] == 0


def test_reviewed_record_missing_from_train_is_new_candidate_only_when_globally_novel() -> None:
    accepted, dataset, historical = _baseline()
    novel = _accepted_record(2, dhash64="f0f0f0f0f0f0f0f0")
    reviewed = _accepted_manifest([*accepted, novel])

    result = _audit_gate_inclusion(
        accepted_review=reviewed,
        v24_dataset=dataset,
        historical_fingerprints=historical,
        expected_selected_count=3,
        expected_dataset_counts={"train": 2, "val": 0, "test": 0},
        expected_historical_unique_count=2,
    )

    assert result["counts"]["new_train_eligible"] == 1
    assert result["new_train_eligible_records"] == [novel]


@pytest.mark.parametrize(
    ("distance", "expected_exact", "expected_perceptual", "expected_new"),
    [(0, 1, 0, 0), (2, 0, 1, 0), (3, 0, 0, 1)],
)
def test_global_historical_exact_and_dhash_two_three_boundary(
    distance: int,
    expected_exact: int,
    expected_perceptual: int,
    expected_new: int,
) -> None:
    candidate_bits = (1 << distance) - 1 if distance else 0
    candidate = _accepted_record(4, dhash64=f"{candidate_bits:016x}")
    historical_sha = str(candidate["image_sha256"]) if distance == 0 else _sha("protected")
    result = _audit_gate_inclusion(
        accepted_review=_accepted_manifest([candidate]),
        v24_dataset=_dataset_manifest([]),
        historical_fingerprints=_historical(
            [{"image_sha256": historical_sha, "dhash64": "0000000000000000"}]
        ),
        expected_selected_count=1,
        expected_dataset_counts={"train": 0, "val": 0, "test": 0},
        expected_historical_unique_count=1,
    )

    assert result["counts"]["protected_exact_overlap"] == expected_exact
    assert result["counts"]["protected_perceptual_overlap"] == expected_perceptual
    assert result["counts"]["new_train_eligible"] == expected_new


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row.update(source_relpath="roboflow/private/frame.jpg"),
        lambda row: row.update(source_clip_ref=""),
        lambda row: row.update(camera_night_ref=""),
        lambda row: row.update(boxes_xywh=[[95.0, 10.0, 10.0, 10.0]]),
        lambda row: row.update(box_count=True),
        lambda row: row.update(positive="yes"),
    ],
)
def test_reviewed_gate_record_contract_is_strict(mutate) -> None:
    record = _accepted_record(0)
    mutate(record)
    with pytest.raises(ValueError, match="reviewed Gate record contract mismatch"):
        _audit_gate_inclusion(
            accepted_review=_accepted_manifest([record]),
            v24_dataset=_dataset_manifest([]),
            historical_fingerprints=_historical([]),
            expected_selected_count=1,
            expected_dataset_counts={"train": 0, "val": 0, "test": 0},
            expected_historical_unique_count=0,
        )


def test_non_train_v24_overlap_is_never_already_train_or_new_candidate() -> None:
    record = _accepted_record(0)
    protected = {
        "sequence": "V0001",
        "split": "val",
        "image_path": "images/val/V0001.jpg",
        "label_path": "labels/val/V0001.txt",
        "image_sha256": record["image_sha256"],
        "box_count": 1,
        "positive": True,
        "source_dataset": "base-v23",
        "camera_night_group": "protected-night",
        "final_holdout_eligible": False,
    }
    result = _audit_gate_inclusion(
        accepted_review=_accepted_manifest([record]),
        v24_dataset=_dataset_manifest([], extra_records=[protected]),
        historical_fingerprints=_historical(
            [{"image_sha256": str(record["image_sha256"]), "dhash64": str(record["dhash64"])}]
        ),
        expected_selected_count=1,
        expected_dataset_counts={"train": 0, "val": 1, "test": 0},
        expected_historical_unique_count=1,
    )

    assert result["counts"]["already_in_v24_train"] == 0
    assert result["counts"]["protected_exact_overlap"] == 1
    assert result["counts"]["new_train_eligible"] == 0


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda value: value.update(schema="wrong"), "accepted review contract mismatch"),
        (lambda value: value.update(selected_count=999), "accepted review contract mismatch"),
        (lambda value: value.update(status="PENDING"), "accepted review contract mismatch"),
    ],
)
def test_accepted_review_manifest_is_exact(mutate, match: str) -> None:
    accepted, dataset, historical = _baseline()
    manifest = _accepted_manifest(accepted)
    mutate(manifest)
    with pytest.raises(ValueError, match=match):
        _audit_gate_inclusion(
            accepted_review=manifest,
            v24_dataset=dataset,
            historical_fingerprints=historical,
            expected_selected_count=2,
            expected_dataset_counts={"train": 2, "val": 0, "test": 0},
            expected_historical_unique_count=2,
        )


def test_historical_fingerprint_coverage_and_policy_are_exact() -> None:
    accepted, dataset, historical = _baseline()
    historical["fingerprint_policy"] = {
        **historical["fingerprint_policy"],
        "hamming_reject_max_distance": 3,
    }
    with pytest.raises(ValueError, match="historical fingerprint contract mismatch"):
        _audit_gate_inclusion(
            accepted_review=_accepted_manifest(accepted),
            v24_dataset=dataset,
            historical_fingerprints=historical,
            expected_selected_count=2,
            expected_dataset_counts={"train": 2, "val": 0, "test": 0},
            expected_historical_unique_count=2,
        )


def test_private_audit_publish_is_0600_no_overwrite(tmp_path: Path) -> None:
    accepted, dataset, historical = _baseline()
    result = _audit_gate_inclusion(
        accepted_review=_accepted_manifest(accepted),
        v24_dataset=dataset,
        historical_fingerprints=historical,
        expected_selected_count=2,
        expected_dataset_counts={"train": 2, "val": 0, "test": 0},
        expected_historical_unique_count=2,
    )
    output = tmp_path / "audit.private.json"

    digest = audit.publish_private_audit(audit=result, output=output)

    assert digest == hashlib.sha256(output.read_bytes()).hexdigest()
    assert stat.S_IMODE(output.lstat().st_mode) == 0o600
    assert json.loads(output.read_bytes())["status"] == "V25_HISTORICAL_AUDIT_READY"
    with pytest.raises(FileExistsError):
        audit.publish_private_audit(audit=result, output=output)


@pytest.mark.parametrize(
    ("target", "key", "value", "match"),
    [
        ("sample", "negative_mislabeled_count", 1, "sample audit evidence"),
        ("full", "accepted_records", [], "positive full-review evidence"),
        ("accepted", "owner_verdict_sha256", "f" * 64, "positive full-review evidence"),
    ],
)
def test_review_evidence_cross_pins_are_required(
    target: str, key: str, value: object, match: str
) -> None:
    accepted, dataset, historical = _baseline()
    accepted_manifest = _accepted_manifest(accepted)
    sample, full, contract = _review_evidence(accepted)
    {"sample": sample, "full": full, "accepted": accepted_manifest}[target][key] = value

    with pytest.raises(ValueError, match=match):
        audit.audit_gate_inclusion(
            sample_audit_summary=sample,
            positive_full_review_result=full,
            accepted_review=accepted_manifest,
            v24_dataset=dataset,
            historical_fingerprints=historical,
            expected_selected_count=2,
            expected_dataset_counts={"train": 2, "val": 0, "test": 0},
            expected_historical_unique_count=2,
            expected_review_contract=contract,
        )


def test_run_private_audit_cross_pins_raw_inputs_and_dataset_fingerprint(
    tmp_path: Path,
) -> None:
    accepted, dataset, historical = _baseline()
    sample, full, contract = _review_evidence(accepted)
    paths = {
        "sample_audit_summary": _private_json(tmp_path / "sample.private.json", sample),
        "positive_full_review_result": _private_json(tmp_path / "full.private.json", full),
        "accepted_review": _private_json(
            tmp_path / "accepted.private.json", _accepted_manifest(accepted)
        ),
        "v24_dataset": _private_json(tmp_path / "dataset.private.json", dataset),
    }
    dataset_sha = hashlib.sha256(paths["v24_dataset"].read_bytes()).hexdigest()
    historical["artifact_sha256"]["dataset"] = dataset_sha
    paths["historical_fingerprints"] = _private_json(
        tmp_path / "historical.private.json", historical
    )
    expected = {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()
    }
    output = tmp_path / "input-audit.private.json"

    result = audit.run_private_audit(
        **paths,
        expected_sha256=expected,
        output=output,
        started_output=tmp_path / "audit.started.private.json",
        expected_selected_count=2,
        expected_dataset_counts={"train": 2, "val": 0, "test": 0},
        expected_historical_unique_count=2,
        expected_review_contract=contract,
    )

    assert result["status"] == "V25_HISTORICAL_AUDIT_READY"
    assert result["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert stat.S_IMODE(output.lstat().st_mode) == 0o600
    published = json.loads(output.read_bytes())
    assert published["input_sha256"] == expected


def test_run_private_audit_rejects_wrong_pin_without_leaking_path(tmp_path: Path) -> None:
    accepted, dataset, historical = _baseline()
    sample, full, contract = _review_evidence(accepted)
    paths = {
        "sample_audit_summary": _private_json(tmp_path / "sample.private.json", sample),
        "positive_full_review_result": _private_json(tmp_path / "full.private.json", full),
        "accepted_review": _private_json(
            tmp_path / "accepted.private.json", _accepted_manifest(accepted)
        ),
        "v24_dataset": _private_json(tmp_path / "dataset.private.json", dataset),
        "historical_fingerprints": _private_json(
            tmp_path / "historical.private.json", historical
        ),
    }
    expected = {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()
    }
    expected["accepted_review"] = "0" * 64

    with pytest.raises(ValueError, match="private input pin mismatch") as captured:
        audit.run_private_audit(
            **paths,
            expected_sha256=expected,
            output=tmp_path / "must-not-exist.private.json",
            started_output=tmp_path / "audit.started.private.json",
            expected_selected_count=2,
            expected_dataset_counts={"train": 2, "val": 0, "test": 0},
            expected_historical_unique_count=2,
            expected_review_contract=contract,
        )
    assert str(tmp_path) not in str(captured.value)


def _gate_origin_fixture(tmp_path: Path, records: list[dict[str, object]]):
    root = tmp_path / "gate"
    images = root / "coco" / "images"
    annotations = root / "coco" / "annotations"
    images.mkdir(parents=True)
    annotations.mkdir(parents=True)
    manifest_rows = []
    coco_images = []
    coco_annotations = []
    for image_id, row in enumerate(records, start=1):
        relative = Path(str(row["source_relpath"]))
        target = images / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new(
            "RGB", (int(row["width"]), int(row["height"])), (image_id, 0, 0)
        )
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        payload = buffer.getvalue()
        target.write_bytes(payload)
        row["image_sha256"] = hashlib.sha256(payload).hexdigest()
        manifest_rows.append(
            {
                "filename": relative.as_posix(),
                "source": "operational",
                "clip_id": relative.parts[1],
                "split": "train",
                "labeled": "yes",
                "domain": "",
            }
        )
        coco_images.append(
            {
                "id": image_id,
                "file_name": relative.as_posix(),
                "width": row["width"],
                "height": row["height"],
            }
        )
        for box_index, box in enumerate(row["boxes_xywh"], start=1):
            coco_annotations.append(
                {
                    "id": image_id * 100 + box_index,
                    "image_id": image_id,
                    "category_id": 1,
                    "bbox": box,
                    "area": box[2] * box[3],
                    "iscrowd": 0,
                }
            )
    manifest = root / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["filename", "source", "clip_id", "split", "labeled", "domain"],
        )
        writer.writeheader()
        writer.writerows(manifest_rows)
    coco = annotations / "train.json"
    coco.write_text(
        json.dumps(
            {
                "images": coco_images,
                "annotations": coco_annotations,
                "categories": [{"id": 1, "name": "gecko"}],
            }
        ),
        encoding="utf-8",
    )
    lineage = root / "gate-lineage.private.json"
    lineage.write_text(
        json.dumps(
            {
                "schema": "yolo26n-gate-lineage-v24-v1",
                "rows": [
                    {
                        "source_relpath": row["source_relpath"],
                        "source_clip_ref": row["source_clip_ref"],
                        "camera_night_ref": row["camera_night_ref"],
                    }
                    for row in records
                ],
                "db_write_count": 0,
                "r2_write_count": 0,
                "service_write_count": 0,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    lineage.chmod(0o600)
    expected = {
        "manifest": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "lineage": hashlib.sha256(lineage.read_bytes()).hexdigest(),
        "coco:train.json": hashlib.sha256(coco.read_bytes()).hexdigest(),
    }
    return root, manifest, [coco], lineage, expected


def test_gate_origin_requires_manifest_coco_and_raw_image_bijection(tmp_path: Path) -> None:
    records = [_accepted_record(0)]
    root, manifest, coco, lineage, expected = _gate_origin_fixture(tmp_path, records)

    evidence = audit.validate_gate_origin_artifacts(
        reviewed=records,
        gate_root=root,
        gate_manifest=manifest,
        gate_coco=coco,
        gate_lineage=lineage,
        expected_sha256=expected,
    )

    assert evidence["validated_count"] == 1
    assert evidence["license_role"] == "owner-operated/private-training"
    assert evidence["human_gt"] is True
    assert evidence["train_eligible_image_sha256"] == [records[0]["image_sha256"]]


@pytest.mark.parametrize("mutation", ["unlabeled", "wrong_box", "changed_bytes"])
def test_gate_origin_fails_closed_on_provenance_or_content_mismatch(
    tmp_path: Path, mutation: str
) -> None:
    records = [_accepted_record(0)]
    root, manifest, coco, lineage, expected = _gate_origin_fixture(tmp_path, records)
    if mutation == "unlabeled":
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(",yes,", ",no,"),
            encoding="utf-8",
        )
        expected["manifest"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    elif mutation == "wrong_box":
        payload = json.loads(coco[0].read_text(encoding="utf-8"))
        payload["annotations"][0]["bbox"][0] += 1
        coco[0].write_text(json.dumps(payload), encoding="utf-8")
        expected["coco:train.json"] = hashlib.sha256(coco[0].read_bytes()).hexdigest()
    else:
        image = root / "coco" / "images" / str(records[0]["source_relpath"])
        image.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Gate origin artifact contract mismatch"):
        audit.validate_gate_origin_artifacts(
            reviewed=records,
            gate_root=root,
                gate_manifest=manifest,
                gate_coco=coco,
                gate_lineage=lineage,
                expected_sha256=expected,
            )


def test_gate_origin_rejects_manifest_coco_set_or_lineage_mismatch(tmp_path: Path) -> None:
    records = [_accepted_record(0)]
    root, manifest, coco, lineage, expected = _gate_origin_fixture(tmp_path, records)
    with manifest.open("a", encoding="utf-8") as stream:
        stream.write("operational/extra/frame.png,operational,extra,train,yes,\n")
    expected["manifest"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Gate origin artifact contract mismatch"):
        audit.validate_gate_origin_artifacts(
            reviewed=records,
            gate_root=root,
            gate_manifest=manifest,
            gate_coco=coco,
            gate_lineage=lineage,
            expected_sha256=expected,
        )

    root, manifest, coco, lineage, expected = _gate_origin_fixture(tmp_path / "two", records)
    payload = json.loads(lineage.read_text(encoding="utf-8"))
    payload["rows"][0]["source_clip_ref"] = "wrong-private-ref"
    lineage.write_text(json.dumps(payload), encoding="utf-8")
    lineage.chmod(0o600)
    expected["lineage"] = hashlib.sha256(lineage.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Gate origin artifact contract mismatch"):
        audit.validate_gate_origin_artifacts(
            reviewed=records,
            gate_root=root,
            gate_manifest=manifest,
            gate_coco=coco,
            gate_lineage=lineage,
            expected_sha256=expected,
        )


def test_gate_origin_requires_lineage_for_unreviewed_operational_full_set(
    tmp_path: Path,
) -> None:
    reviewed = _accepted_record(0)
    unreviewed = _accepted_record(1)
    root, manifest, coco, lineage, expected = _gate_origin_fixture(
        tmp_path, [reviewed, unreviewed]
    )
    payload = json.loads(lineage.read_text(encoding="utf-8"))
    payload["rows"] = payload["rows"][:1]
    lineage.write_text(json.dumps(payload), encoding="utf-8")
    lineage.chmod(0o600)
    expected["lineage"] = hashlib.sha256(lineage.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="Gate origin artifact contract mismatch"):
        audit.validate_gate_origin_artifacts(
            reviewed=[reviewed],
            gate_root=root,
            gate_manifest=manifest,
            gate_coco=coco,
            gate_lineage=lineage,
            expected_sha256=expected,
        )


def test_gate_origin_rejects_duplicate_coco_image_or_annotation_ids(tmp_path: Path) -> None:
    records = [
        _accepted_record(0, positive=False, box_count=0, boxes_xywh=[]),
        _accepted_record(1, positive=False, box_count=0, boxes_xywh=[]),
    ]
    root, manifest, coco, lineage, expected = _gate_origin_fixture(tmp_path, records)
    payload = json.loads(coco[0].read_text(encoding="utf-8"))
    payload["images"][1]["id"] = payload["images"][0]["id"]
    coco[0].write_text(json.dumps(payload), encoding="utf-8")
    expected["coco:train.json"] = hashlib.sha256(coco[0].read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Gate origin artifact contract mismatch"):
        audit.validate_gate_origin_artifacts(
            reviewed=records,
            gate_root=root,
            gate_manifest=manifest,
            gate_coco=coco,
            gate_lineage=lineage,
            expected_sha256=expected,
        )


def test_gate_origin_rejects_manifest_to_coco_split_swap(tmp_path: Path) -> None:
    records = [_accepted_record(0)]
    root, manifest, coco, lineage, expected = _gate_origin_fixture(tmp_path, records)
    train_payload = json.loads(coco[0].read_text(encoding="utf-8"))
    coco[0].write_text(
        json.dumps(
            {
                "images": [],
                "annotations": [],
                "categories": [{"id": 1, "name": "gecko"}],
            }
        ),
        encoding="utf-8",
    )
    val = coco[0].with_name("val.json")
    val.write_text(json.dumps(train_payload), encoding="utf-8")
    expected = {
        **expected,
        "coco:train.json": hashlib.sha256(coco[0].read_bytes()).hexdigest(),
        "coco:val.json": hashlib.sha256(val.read_bytes()).hexdigest(),
    }
    with pytest.raises(ValueError, match="Gate origin artifact contract mismatch"):
        audit.validate_gate_origin_artifacts(
            reviewed=records,
            gate_root=root,
            gate_manifest=manifest,
            gate_coco=[coco[0], val],
            gate_lineage=lineage,
            expected_sha256=expected,
        )


@pytest.mark.parametrize(
    "invalid_box",
    [
        [float("nan"), 12.0, 30.0, 20.0],
        [10.0, float("inf"), 30.0, 20.0],
        [10.0, 12.0, 0.0, 20.0],
        [10.0, 12.0, 30.0, -1.0],
        [-0.1, 12.0, 30.0, 20.0],
        [80.0, 12.0, 30.0, 20.0],
        [10.0, 70.0, 30.0, 20.0],
    ],
)
def test_gate_origin_rejects_invalid_bbox_in_unreviewed_operational_full_set(
    tmp_path: Path, invalid_box: list[float]
) -> None:
    reviewed = _accepted_record(0)
    unreviewed = _accepted_record(1, boxes_xywh=[invalid_box])
    root, manifest, coco, lineage, expected = _gate_origin_fixture(
        tmp_path, [reviewed, unreviewed]
    )

    with pytest.raises(ValueError, match="Gate origin artifact contract mismatch"):
        audit.validate_gate_origin_artifacts(
            reviewed=[reviewed],
            gate_root=root,
            gate_manifest=manifest,
            gate_coco=coco,
            gate_lineage=lineage,
            expected_sha256=expected,
        )

def test_run_private_audit_quarantines_owned_output_after_late_input_change(
    tmp_path: Path, monkeypatch
) -> None:
    accepted, dataset, historical = _baseline()
    sample, full, contract = _review_evidence(accepted)
    paths = {
        "sample_audit_summary": _private_json(tmp_path / "sample.private.json", sample),
        "positive_full_review_result": _private_json(tmp_path / "full.private.json", full),
        "accepted_review": _private_json(tmp_path / "accepted.private.json", _accepted_manifest(accepted)),
        "v24_dataset": _private_json(tmp_path / "dataset.private.json", dataset),
    }
    historical["artifact_sha256"]["dataset"] = hashlib.sha256(paths["v24_dataset"].read_bytes()).hexdigest()
    paths["historical_fingerprints"] = _private_json(tmp_path / "historical.private.json", historical)
    expected = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    output = tmp_path / "audit.private.json"
    original = audit._assert_private_snapshot_unchanged
    calls = 0

    def fail_late(*args, **kwargs):
        nonlocal calls
        calls += 1
        if output.exists():
            raise ValueError("private input changed")
        return original(*args, **kwargs)

    monkeypatch.setattr(audit, "_assert_private_snapshot_unchanged", fail_late)
    with pytest.raises(ValueError, match="private input changed"):
        audit.run_private_audit(
            **paths,
            expected_sha256=expected,
            output=output,
            started_output=tmp_path / "audit.started.private.json",
            expected_selected_count=2,
            expected_dataset_counts={"train": 2, "val": 0, "test": 0},
            expected_historical_unique_count=2,
            expected_review_contract=contract,
        )
    assert calls > 0
    assert not output.exists()


def test_audit_cli_exposes_gate_origin_inputs() -> None:
    parser = audit.build_parser()
    help_text = parser.format_help()
    assert "--gate-root" in help_text
    assert "--gate-manifest" in help_text
    assert "--gate-coco" in help_text
