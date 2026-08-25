from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import zipfile
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

import scripts.build_yolo26n_v25_owner_hardcase_queue as builder
import scripts.validate_yolo26n_v25_blind_queue as validator


def _record(index: int) -> dict[str, object]:
    payload = builder.encode_jpeg(Image.new("RGB", (40, 30), (index, 0, 0)))
    return {
        "role": "owner-development-video",
        "source_video_sha256": hashlib.sha256(f"source-{index}".encode()).hexdigest(),
        "frame_index": index,
        "timestamp_sec": float(index),
        "image_sha256": hashlib.sha256(payload).hexdigest(),
        "dhash64": builder.historical_dhash64(payload),
        "width": 40,
        "height": 30,
        "jpeg_bytes": payload,
        "selection_reasons": ["uniform"],
        "predictions": [],
        "signals": ["suspected_miss", "source_diversity"],
    }


def _replace_queue_image_and_repinned_artifacts(queue: Path, payload: bytes) -> None:
    cvat = queue / "cvat"
    image = cvat / "images" / "V250001.jpg"
    image.write_bytes(payload)
    image.chmod(0o600)
    image_sha = hashlib.sha256(payload).hexdigest()
    manifest_path = cvat / "queue-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["records"][0]["image_sha256"] = image_sha
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o600)
    review_path = queue / "review-index.private.json"
    review = json.loads(review_path.read_bytes())
    review["records"][0]["image_sha256"] = image_sha
    review["records"][0]["dhash64"] = builder.historical_dhash64(payload)
    review_path.write_text(json.dumps(review), encoding="utf-8")
    review_path.chmod(0o600)
    members = {
        "queue-manifest.json": manifest_path.read_bytes(),
        "annotations.coco.json": (cvat / "annotations.coco.json").read_bytes(),
        "BBOX-RULES.md": (cvat / "BBOX-RULES.md").read_bytes(),
        "images/V250001.jpg": payload,
    }
    archive = queue / "cvat-upload.zip"
    archive.write_bytes(builder._zip_bytes(members))
    archive.chmod(0o600)


def test_validator_accepts_exact_bundle_zip_and_private_index(tmp_path: Path) -> None:
    queue = tmp_path / "queue-result"
    builder.build_blind_queue([_record(0), _record(1)], output_dir=queue)
    acceptance = tmp_path / "acceptance.private.json"

    result = validator.validate_blind_queue(
        queue_dir=queue,
        expected_queue_sha256=builder.directory_contract_sha256(queue),
        acceptance_output=acceptance,
        started_output=tmp_path / "acceptance.started.private.json",
    )

    assert result["status"] == "V25_BLIND_QUEUE_ACCEPTED"
    assert result["queue_count"] == 2
    assert stat.S_IMODE(acceptance.lstat().st_mode) == 0o600
    with zipfile.ZipFile(queue / "cvat-upload.zip") as archive:
        assert sorted(archive.namelist()) == [
            "BBOX-RULES.md",
            "annotations.coco.json",
            "images/V250001.jpg",
            "images/V250002.jpg",
            "queue-manifest.json",
        ]


def test_validator_rejects_public_prediction_metadata(tmp_path: Path) -> None:
    queue = tmp_path / "queue-result"
    builder.build_blind_queue([_record(0)], output_dir=queue)
    manifest = queue / "cvat" / "queue-manifest.json"
    payload = json.loads(manifest.read_bytes())
    payload["predictions"] = []
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    manifest.chmod(0o600)
    with pytest.raises(ValueError, match="public queue manifest"):
        validator.validate_blind_queue(
            queue_dir=queue,
            expected_queue_sha256=builder.directory_contract_sha256(queue),
            acceptance_output=tmp_path / "must-not-exist.private.json",
            started_output=tmp_path / "acceptance.started.private.json",
        )


def test_validator_rejects_jpeg_exif_even_when_all_sha_pins_match(
    tmp_path: Path,
) -> None:
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[0x010E] = "private-metadata"
    Image.new("RGB", (40, 30), "black").save(buffer, format="JPEG", exif=exif)
    payload = buffer.getvalue()
    queue = tmp_path / "queue-result"
    builder.build_blind_queue([_record(0)], output_dir=queue)
    _replace_queue_image_and_repinned_artifacts(queue, payload)

    with pytest.raises(ValueError, match="metadata"):
        validator.validate_blind_queue(
            queue_dir=queue,
            expected_queue_sha256=builder.directory_contract_sha256(queue),
            acceptance_output=tmp_path / "must-not-exist.private.json",
            started_output=tmp_path / "acceptance.started.private.json",
        )


def test_builder_and_validator_reject_non_jpeg_with_text_metadata(
    tmp_path: Path,
) -> None:
    buffer = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private-note", "must-not-leak")
    Image.new("RGB", (40, 30), "black").save(
        buffer, format="PNG", pnginfo=metadata
    )
    payload = buffer.getvalue()
    invalid = _record(0)
    invalid.update(
        {
            "jpeg_bytes": payload,
            "image_sha256": hashlib.sha256(payload).hexdigest(),
            "dhash64": builder.historical_dhash64(payload),
        }
    )
    with pytest.raises(ValueError, match="JPEG"):
        builder.build_blind_queue([invalid], output_dir=tmp_path / "builder-reject")

    queue = tmp_path / "queue-result"
    builder.build_blind_queue([_record(0)], output_dir=queue)
    _replace_queue_image_and_repinned_artifacts(queue, payload)

    with pytest.raises(ValueError, match="JPEG"):
        validator.validate_blind_queue(
            queue_dir=queue,
            expected_queue_sha256=builder.directory_contract_sha256(queue),
            acceptance_output=tmp_path / "must-not-exist.private.json",
            started_output=tmp_path / "acceptance.started.private.json",
        )


def test_validator_requires_exact_canonical_bbox_rules_bytes(tmp_path: Path) -> None:
    queue = tmp_path / "queue-result"
    builder.build_blind_queue([_record(0)], output_dir=queue)
    cvat = queue / "cvat"
    rules = cvat / "BBOX-RULES.md"
    rules.write_bytes(rules.read_bytes() + b"\nextra instruction\n")
    rules.chmod(0o600)
    members = {
        "queue-manifest.json": (cvat / "queue-manifest.json").read_bytes(),
        "annotations.coco.json": (cvat / "annotations.coco.json").read_bytes(),
        "BBOX-RULES.md": rules.read_bytes(),
        "images/V250001.jpg": (cvat / "images" / "V250001.jpg").read_bytes(),
    }
    archive = queue / "cvat-upload.zip"
    archive.write_bytes(builder._zip_bytes(members))
    archive.chmod(0o600)

    with pytest.raises(ValueError, match="bbox rules"):
        validator.validate_blind_queue(
            queue_dir=queue,
            expected_queue_sha256=builder.directory_contract_sha256(queue),
            acceptance_output=tmp_path / "must-not-exist.private.json",
            started_output=tmp_path / "acceptance.started.private.json",
        )


def test_validator_rejects_content_identical_queue_directory_aba(
    tmp_path: Path, monkeypatch
) -> None:
    queue = tmp_path / "queue-result"
    builder.build_blind_queue([_record(0)], output_dir=queue)
    queue_sha = builder.directory_contract_sha256(queue)
    saved = tmp_path / "owned-queue"
    original_write = validator._secure_write_private_bytes_new

    def publish_then_swap(path: Path, payload: bytes):
        artifact = original_write(path, payload)
        if path.name == "acceptance.private.json":
            os.rename(queue, saved)
            shutil.copytree(saved, queue, copy_function=shutil.copy2)
        return artifact

    monkeypatch.setattr(validator, "_secure_write_private_bytes_new", publish_then_swap)
    with pytest.raises(ValueError, match="identity changed"):
        validator.validate_blind_queue(
            queue_dir=queue,
            expected_queue_sha256=queue_sha,
            acceptance_output=tmp_path / "acceptance.private.json",
            started_output=tmp_path / "acceptance.started.private.json",
        )
    assert saved.is_dir()


def test_validator_quarantines_owned_acceptance_after_late_queue_change(
    tmp_path: Path, monkeypatch
) -> None:
    queue = tmp_path / "queue-result"
    builder.build_blind_queue([_record(0)], output_dir=queue)
    queue_sha = builder.directory_contract_sha256(queue)
    acceptance = tmp_path / "acceptance.private.json"
    original = validator._secure_write_private_bytes_new

    def publish_then_fail(path: Path, payload: bytes):
        artifact = original(path, payload)
        if path == acceptance:
            monkeypatch.setattr(
                builder, "directory_contract_sha256", lambda _root: "0" * 64
            )
        return artifact

    monkeypatch.setattr(validator, "_secure_write_private_bytes_new", publish_then_fail)
    with pytest.raises(ValueError, match="changed at acceptance"):
        validator.validate_blind_queue(
            queue_dir=queue,
            expected_queue_sha256=queue_sha,
            acceptance_output=acceptance,
            started_output=tmp_path / "acceptance.started.private.json",
        )
    assert not acceptance.exists()


def test_validator_rejects_fifo_as_non_regular_without_reading(
    tmp_path: Path,
) -> None:
    root = tmp_path / "queue"
    root.mkdir(mode=0o700)
    fifo = root / "blocked.private"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(ValueError, match="regular"):
        validator._assert_private_tree(root)


def test_validator_cli_requires_queue_and_sha_contract() -> None:
    parser = validator.build_parser()
    help_text = parser.format_help()
    assert "--queue-dir" in help_text
    assert "--expected-queue-sha256" in help_text
    assert "--acceptance-output" in help_text
