import csv
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image

import scripts.validate_yolo26n_v24b_future_holdout_export as validator


REVIEW_HEADER = [
    "sequence",
    "filename",
    "presence",
    "source_ref",
    "camera_id",
    "camera_night",
    "source_sequence",
    "image_sha256",
    "width",
    "height",
    "dhash",
]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _rectangle(*, points: list[object] | None = None, **extra: object) -> dict[str, object]:
    return {
        "type": "rectangle",
        "label_id": 1,
        "points": [1, 2, 10, 9] if points is None else points,
        **extra,
    }


def _contract() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, dict[str, object]],
    list[dict[str, object]],
]:
    records: list[dict[str, object]] = []
    images: list[dict[str, object]] = []
    metadata: dict[str, dict[str, object]] = {}
    review_rows: list[dict[str, object]] = []
    for ordinal in range(1, 121):
        sequence = f"H{ordinal:04d}"
        filename = f"{sequence}.jpg"
        image_sha256 = _digest(sequence)
        presence = "positive" if ordinal <= 60 else "negative"
        source_ordinal = (ordinal - 1) // 2 + 1
        boxes = [] if presence == "negative" else [_rectangle()]
        if ordinal == 1:
            boxes.append(_rectangle(points=[11, 1, 15, 8]))
        records.append(
            {
                "sequence": sequence,
                "filename": filename,
                "presence": presence,
                "image_sha256": image_sha256,
                "width": 16,
                "height": 12,
            }
        )
        images.append(
            {
                "frame": ordinal - 1,
                "path": f"images/{filename}",
                "width": 16,
                "height": 12,
                "image_sha256": image_sha256,
                "boxes": boxes,
            }
        )
        metadata[sequence] = {
            "filename": filename,
            "image_sha256": image_sha256,
            "width": 16,
            "height": 12,
        }
        review_rows.append(
            {
                "sequence": sequence,
                "filename": filename,
                "presence": presence,
                "source_ref": f"source-{source_ordinal:03d}",
                "camera_id": f"camera-{(ordinal - 1) % 3 + 1}",
                "camera_night": f"night-{(ordinal - 1) % 6 + 1}",
                "source_sequence": f"P{ordinal:04d}",
                "image_sha256": image_sha256,
                "width": "16",
                "height": "12",
                "dhash": "0" if ordinal % 2 else "7",
            }
        )
    manifest: dict[str, object] = {
        "schema": "yolo26n-v24b-future-holdout-v1",
        "status": "V24B_FUTURE_HOLDOUT_READY",
        "pool_ledger_sha256_pre": "1" * 64,
        "pool_ledger_sha256_post": "1" * 64,
        "presence_screen_sha256_pre": "2" * 64,
        "presence_screen_sha256_post": "2" * 64,
        "review_index_sha256": "3" * 64,
        "image_count": 120,
        "positive_count": 60,
        "negative_count": 60,
        "ambiguous_count": 0,
        "prediction_prefill_count": 0,
        "records": records,
        "db_write_count": 0,
        "r2_get_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }
    snapshot: dict[str, object] = {
        "schema": "cvat-task160-owner-snapshot-v1",
        "labels": [{"id": 1, "name": "gecko"}],
        "images": images,
    }
    return manifest, snapshot, metadata, review_rows


def _validate(
    manifest: dict[str, object],
    snapshot: dict[str, object],
    metadata: dict[str, dict[str, object]],
    review_rows: list[dict[str, object]],
    *,
    ambiguous_sequences: tuple[str, ...] = (),
) -> dict[str, object]:
    return validator.validate_export(
        candidate_manifest=manifest,
        snapshot=snapshot,
        image_metadata=metadata,
        review_index_rows=review_rows,
        ambiguous_sequences=ambiguous_sequences,
    )


def test_valid_contract_accepts_multiple_geckos_and_exact_positive_negative_split() -> None:
    manifest, snapshot, metadata, review_rows = _contract()

    result = _validate(manifest, snapshot, metadata, review_rows)

    assert result["status"] == "V24B_FUTURE_HOLDOUT_ACCEPTED"
    assert result["positive_image_count"] == 60
    assert result["negative_image_count"] == 60
    assert result["ambiguous_image_count"] == 0
    assert result["box_count"] == 61
    assert result["records"][0] == {
        "sequence": "H0001",
        "filename": "H0001.jpg",
        "presence": "positive",
        "image_sha256": "6033a296141f2a78147aa3db4e68bdec9ad49c9e3f46371065d4fd89018d5ced",
        "width": 16,
        "height": 12,
        "boxes": [
            {"label_id": 1, "points": [1.0, 2.0, 10.0, 9.0]},
            {"label_id": 1, "points": [11.0, 1.0, 15.0, 8.0]},
        ],
    }


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda value: value.update({"schema": "wrong"}), "manifest schema"),
        (lambda value: value.update({"status": "wrong"}), "manifest status"),
        (lambda value: value.update({"unexpected": 1}), "manifest fields"),
        (lambda value: value.update({"image_count": True}), "manifest count"),
        (lambda value: value.update({"positive_count": 59}), "positive count"),
        (lambda value: value.update({"negative_count": 61}), "negative count"),
        (lambda value: value.update({"ambiguous_count": 1}), "ambiguous count"),
        (lambda value: value.update({"prediction_prefill_count": 1}), "prediction prefill"),
        (lambda value: value["records"][0].update({"source_ref": "private"}), "record fields"),
        (lambda value: value["records"][0].update({"sequence": "H9999"}), "record order"),
        (lambda value: value["records"].reverse(), "record order"),
        (lambda value: value["records"][0].update({"width": True}), "dimensions"),
        (lambda value: value["records"][0].update({"presence": "ambiguous"}), "presence"),
    ],
)
def test_manifest_requires_exact_schema_status_counts_records_and_h_order(mutate, match) -> None:
    manifest, snapshot, metadata, review_rows = _contract()
    mutate(manifest)

    with pytest.raises(ValueError, match=match):
        _validate(manifest, snapshot, metadata, review_rows)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda value: value.update({"unexpected": 1}), "snapshot fields"),
        (lambda value: value["labels"].append({"id": 2, "name": "leaf"}), "label contract"),
        (lambda value: value["labels"][0].update({"id": True}), "label contract"),
        (lambda value: value["images"].reverse(), "snapshot image order"),
        (lambda value: value["images"][0].update({"frame": True}), "frame order"),
        (lambda value: value["images"][0].update({"path": "../H0001.jpg"}), "image path"),
        (lambda value: value["images"][0].update({"image_sha256": "f" * 64}), "image sha256"),
        (lambda value: value["images"][0].update({"height": 11}), "dimensions"),
        (lambda value: value["images"][0]["boxes"][0].update({"score": 0.9}), "rectangle fields"),
        (lambda value: value["images"][0]["boxes"][0].update({"source": "manual"}), "rectangle fields"),
        (lambda value: value["images"][0]["boxes"][0].update({"track_id": 1}), "rectangle fields"),
        (lambda value: value["images"][0]["boxes"][0].update({"attributes": []}), "rectangle fields"),
        (lambda value: value["images"][0]["boxes"][0].update({"rotation": 0}), "rectangle fields"),
        (lambda value: value["images"][0]["boxes"][0].update({"label_id": True}), "label contract"),
        (lambda value: value["images"][0]["boxes"][0].update({"points": [1, 2, 1, 9]}), "bbox"),
        (lambda value: value["images"][0]["boxes"][0].update({"points": [1, 2, 17, 9]}), "bbox"),
        (lambda value: value["images"][0]["boxes"][0].update({"points": [1, 2, float("nan"), 9]}), "bbox"),
        (lambda value: value["images"][0]["boxes"][0].update({"points": [1, 2, float("inf"), 9]}), "bbox"),
    ],
)
def test_snapshot_requires_exact_label_order_static_rectangles_hashes_and_dimensions(
    mutate, match
) -> None:
    manifest, snapshot, metadata, review_rows = _contract()
    mutate(snapshot)

    with pytest.raises(ValueError, match=match):
        _validate(manifest, snapshot, metadata, review_rows)


def test_positive_requires_a_box_and_negative_forbids_boxes() -> None:
    manifest, snapshot, metadata, review_rows = _contract()
    snapshot["images"][0]["boxes"] = []
    with pytest.raises(ValueError, match="positive image"):
        _validate(manifest, snapshot, metadata, review_rows)

    manifest, snapshot, metadata, review_rows = _contract()
    snapshot["images"][60]["boxes"] = [_rectangle()]
    with pytest.raises(ValueError, match="negative image"):
        _validate(manifest, snapshot, metadata, review_rows)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda rows: rows[0].update({"extra": "bad"}), "review index fields"),
        (lambda rows: rows.reverse(), "review index order"),
        (lambda rows: rows[0].update({"filename": "wrong.jpg"}), "review index manifest"),
        (lambda rows: rows[0].update({"image_sha256": "f" * 64}), "review index manifest"),
        (lambda rows: rows[0].update({"source_ref": ""}), "source identity"),
        (lambda rows: rows[0].update({"camera_id": ""}), "source identity"),
        (lambda rows: rows[0].update({"camera_night": ""}), "source identity"),
        (lambda rows: rows[0].update({"source_sequence": ""}), "source identity"),
        (lambda rows: rows[0].update({"dhash": "-1"}), "dhash"),
        (lambda rows: rows[0].update({"dhash": "01"}), "dhash"),
    ],
)
def test_review_index_is_exact_ordered_private_identity_sot(mutate, match) -> None:
    manifest, snapshot, metadata, review_rows = _contract()
    mutate(review_rows)

    with pytest.raises(ValueError, match=match):
        _validate(manifest, snapshot, metadata, review_rows)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda rows: [row.update({"camera_id": "one-camera"}) for row in rows], "3 cameras"),
        (lambda rows: [row.update({"camera_night": f"night-{index % 5}"}) for index, row in enumerate(rows)], "6 nights"),
        (lambda rows: rows[2].update({"source_ref": rows[0]["source_ref"]}), "source cap"),
        (lambda rows: rows[20].update({"camera_night": rows[0]["camera_night"]}), "night cap"),
        (lambda rows: rows[1].update({"dhash": "3"}), "dHash distance"),
    ],
)
def test_review_index_rechecks_camera_night_source_and_dhash_caps(mutate, match) -> None:
    manifest, snapshot, metadata, review_rows = _contract()
    mutate(review_rows)

    with pytest.raises(ValueError, match=match):
        _validate(manifest, snapshot, metadata, review_rows)


def test_any_owner_ambiguous_row_requests_reserve_replacement_without_accepting() -> None:
    manifest, snapshot, metadata, review_rows = _contract()

    with pytest.raises(ValueError, match="V24B_FUTURE_HOLDOUT_RESERVE_REPLACEMENT_REQUIRED"):
        _validate(
            manifest,
            snapshot,
            metadata,
            review_rows,
            ambiguous_sequences=("H0001",),
        )


@dataclass
class CliFixture:
    args: list[str]
    manifest_path: Path
    review_index_path: Path
    snapshot_path: Path
    ambiguous_path: Path
    review_frames_dir: Path
    normalized_output: Path
    summary_output: Path
    lock_path: Path
    manifest_sha256: str
    review_index_sha256: str


def _write_jpeg(path: Path, ordinal: int) -> str:
    image = Image.new("RGB", (16, 12), color=(ordinal % 251, ordinal % 239, ordinal % 227))
    for bit in range(8):
        image.putpixel((bit, ordinal % 12), ((ordinal * bit) % 255, bit * 17, 255 - bit))
    image.save(path, format="JPEG")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_review_index(path: Path, rows: list[dict[str, object]]) -> str:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    path.chmod(0o600)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cli_fixture(tmp_path: Path) -> CliFixture:
    manifest, snapshot, _metadata, review_rows = _contract()
    manifest_path = tmp_path / "future-holdout-manifest.private.json"
    review_index_path = tmp_path / "review-index.private.csv"
    snapshot_path = tmp_path / "cvat-normalized-snapshot.private.json"
    ambiguous_path = tmp_path / "owner-ambiguous.csv"
    review_frames_dir = tmp_path / "review-frames"
    private_dir = tmp_path / "private"
    normalized_output = private_dir / "future-holdout-gt.private.json"
    summary_output = private_dir / "future-holdout-acceptance.private.json"
    lock_path = private_dir / ".future-holdout-export.started.private.json"
    review_frames_dir.mkdir(mode=0o700)
    private_dir.mkdir(mode=0o700)
    for ordinal in range(1, 121):
        sequence = f"H{ordinal:04d}"
        image_sha256 = _write_jpeg(review_frames_dir / f"{sequence}.jpg", ordinal)
        manifest["records"][ordinal - 1]["image_sha256"] = image_sha256
        snapshot["images"][ordinal - 1]["image_sha256"] = image_sha256
        review_rows[ordinal - 1]["image_sha256"] = image_sha256
    review_index_sha256 = _write_review_index(review_index_path, review_rows)
    manifest["review_index_sha256"] = review_index_sha256
    manifest_path.write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    manifest_path.chmod(0o600)
    snapshot_path.write_text(json.dumps(snapshot, separators=(",", ":")), encoding="utf-8")
    snapshot_path.chmod(0o600)
    ambiguous_path.write_text("sequence\n", encoding="utf-8")
    ambiguous_path.chmod(0o600)
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    args = [
        "--candidate-manifest",
        str(manifest_path),
        "--expected-manifest-sha256",
        manifest_sha256,
        "--review-index",
        str(review_index_path),
        "--expected-review-index-sha256",
        review_index_sha256,
        "--snapshot",
        str(snapshot_path),
        "--owner-ambiguous",
        str(ambiguous_path),
        "--review-frames-dir",
        str(review_frames_dir),
        "--normalized-output",
        str(normalized_output),
        "--summary-output",
        str(summary_output),
    ]
    return CliFixture(
        args=args,
        manifest_path=manifest_path,
        review_index_path=review_index_path,
        snapshot_path=snapshot_path,
        ambiguous_path=ambiguous_path,
        review_frames_dir=review_frames_dir,
        normalized_output=normalized_output,
        summary_output=summary_output,
        lock_path=lock_path,
        manifest_sha256=manifest_sha256,
        review_index_sha256=review_index_sha256,
    )


def _replace_arg(args: list[str], flag: str, value: str) -> None:
    args[args.index(flag) + 1] = value


def test_cli_pins_inputs_and_atomically_writes_private_normalized_gt_and_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = _cli_fixture(tmp_path)

    validator.main(fixture.args)

    normalized = json.loads(fixture.normalized_output.read_text(encoding="utf-8"))
    summary = json.loads(fixture.summary_output.read_text(encoding="utf-8"))
    assert summary == {
        "schema": "yolo26n-v24b-future-holdout-acceptance-v1",
        "status": "V24B_FUTURE_HOLDOUT_ACCEPTED",
        "candidate_manifest_sha256": fixture.manifest_sha256,
        "review_index_sha256": fixture.review_index_sha256,
        "image_count": 120,
        "positive_image_count": 60,
        "negative_image_count": 60,
        "ambiguous_image_count": 0,
        "box_count": 61,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "git_write_count": 0,
    }
    assert normalized["schema"] == "yolo26n-v24b-future-holdout-gt-v1"
    assert normalized["status"] == "V24B_FUTURE_HOLDOUT_ACCEPTED"
    assert normalized["records"][0]["sequence"] == "H0001"
    assert normalized["records"][119]["sequence"] == "H0120"
    assert normalized["records"][0]["boxes"] == [
        {"label_id": 1, "points": [1.0, 2.0, 10.0, 9.0]},
        {"label_id": 1, "points": [11.0, 1.0, 15.0, 8.0]},
    ]
    for path in (fixture.normalized_output, fixture.summary_output, fixture.lock_path):
        assert path.stat().st_mode & 0o777 == 0o600
    combined = fixture.normalized_output.read_text() + fixture.summary_output.read_text()
    assert "source_ref" not in combined
    assert "camera_id" not in combined
    assert "camera_night" not in combined
    assert "source_sequence" not in combined
    assert "source-" not in capsys.readouterr().out


@pytest.mark.parametrize("attack", ["duplicate", "nan", "infinity", "boolean"])
def test_cli_rejects_duplicate_keys_nonfinite_numbers_and_boolean_counts(
    attack: str, tmp_path: Path
) -> None:
    fixture = _cli_fixture(tmp_path)
    text = fixture.manifest_path.read_text(encoding="utf-8")
    if attack == "duplicate":
        text = text.replace('"schema":', '"schema":"duplicate","schema":', 1)
    elif attack == "nan":
        text = text.replace('"image_count":120', '"image_count":NaN', 1)
    elif attack == "infinity":
        text = text.replace('"image_count":120', '"image_count":Infinity', 1)
    else:
        text = text.replace('"image_count":120', '"image_count":true', 1)
    fixture.manifest_path.write_text(text, encoding="utf-8")
    fixture.manifest_path.chmod(0o600)
    _replace_arg(
        fixture.args,
        "--expected-manifest-sha256",
        hashlib.sha256(fixture.manifest_path.read_bytes()).hexdigest(),
    )

    with pytest.raises(ValueError):
        validator.main(fixture.args)

    assert not fixture.normalized_output.exists()
    assert not fixture.summary_output.exists()


@pytest.mark.parametrize("which", ["manifest", "review_index"])
def test_manifest_and_review_index_require_independent_raw_sha_and_candidate_cross_pin(
    which: str, tmp_path: Path
) -> None:
    fixture = _cli_fixture(tmp_path)
    flag = (
        "--expected-manifest-sha256"
        if which == "manifest"
        else "--expected-review-index-sha256"
    )
    _replace_arg(fixture.args, flag, "f" * 64)

    with pytest.raises(ValueError, match="sha256 mismatch"):
        validator.main(fixture.args)

    assert not fixture.normalized_output.exists()
    assert not fixture.summary_output.exists()


def test_candidate_manifest_review_index_sha_must_equal_independent_pin(tmp_path: Path) -> None:
    fixture = _cli_fixture(tmp_path)
    manifest = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
    manifest["review_index_sha256"] = "f" * 64
    fixture.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    fixture.manifest_path.chmod(0o600)
    _replace_arg(
        fixture.args,
        "--expected-manifest-sha256",
        hashlib.sha256(fixture.manifest_path.read_bytes()).hexdigest(),
    )

    with pytest.raises(ValueError, match="review index sha256 mismatch"):
        validator.main(fixture.args)


@pytest.mark.parametrize("which", ["manifest", "review_index"])
def test_private_manifest_and_review_index_require_mode_0600(which: str, tmp_path: Path) -> None:
    fixture = _cli_fixture(tmp_path)
    path = fixture.manifest_path if which == "manifest" else fixture.review_index_path
    path.chmod(0o644)

    with pytest.raises(ValueError, match="0600"):
        validator.main(fixture.args)


@pytest.mark.parametrize("which", ["manifest", "review_index"])
def test_private_manifest_and_review_index_reject_same_bytes_inode_replacement_aba(
    which: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _cli_fixture(tmp_path)
    target = fixture.manifest_path if which == "manifest" else fixture.review_index_path
    target_inode = target.stat().st_ino
    real_read = os.read
    replaced = False

    def replace_after_read(descriptor: int, size: int) -> bytes:
        nonlocal replaced
        payload = real_read(descriptor, size)
        if not replaced and os.fstat(descriptor).st_ino == target_inode:
            replacement = target.with_name(f".{target.name}.replacement")
            replacement.write_bytes(payload)
            replacement.chmod(0o600)
            os.replace(replacement, target)
            replaced = True
        return payload

    monkeypatch.setattr(validator.os, "read", replace_after_read)

    with pytest.raises(ValueError, match="changed during read"):
        validator.main(fixture.args)

    assert replaced
    assert not fixture.normalized_output.exists()
    assert not fixture.summary_output.exists()


@pytest.mark.parametrize("attack", ["symlink", "fifo", "oversize"])
def test_manifest_symlink_fifo_and_oversize_attacks_fail_without_output_or_hang(
    attack: str, tmp_path: Path
) -> None:
    fixture = _cli_fixture(tmp_path)
    original = fixture.manifest_path.read_bytes()
    fixture.manifest_path.unlink()
    if attack == "symlink":
        target = tmp_path / "target.private.json"
        target.write_bytes(original)
        target.chmod(0o600)
        fixture.manifest_path.symlink_to(target)
    elif attack == "fifo":
        os.mkfifo(fixture.manifest_path, mode=0o600)
    else:
        fixture.manifest_path.write_bytes(b" " * (2 * 1024 * 1024))
        fixture.manifest_path.chmod(0o600)
        _replace_arg(
            fixture.args,
            "--expected-manifest-sha256",
            hashlib.sha256(fixture.manifest_path.read_bytes()).hexdigest(),
        )

    with pytest.raises(ValueError):
        validator.main(fixture.args)

    assert not fixture.normalized_output.exists()
    assert not fixture.summary_output.exists()


def test_review_frame_scan_rejects_symlink_decode_failure_and_directory_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _cli_fixture(tmp_path)
    image_path = fixture.review_frames_dir / "H0001.jpg"
    image_inode = image_path.stat().st_ino
    real_read = os.read
    injected = False

    def add_file_after_first_image_read(descriptor: int, size: int) -> bytes:
        nonlocal injected
        payload = real_read(descriptor, size)
        if not injected and os.fstat(descriptor).st_ino == image_inode:
            extra = fixture.review_frames_dir / "extra.jpg"
            extra.write_bytes(payload)
            injected = True
        return payload

    monkeypatch.setattr(validator.os, "read", add_file_after_first_image_read)
    with pytest.raises(ValueError, match="review frames changed"):
        validator.main(fixture.args)
    assert injected


def test_review_frame_scan_rejects_review_directory_path_replacement_aba(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _cli_fixture(tmp_path)
    real_read_image = validator._read_directory_file
    replaced = False

    def replace_directory_path_after_first_read(*args: object, **kwargs: object) -> bytes:
        nonlocal replaced
        payload = real_read_image(*args, **kwargs)
        if not replaced:
            displaced = fixture.review_frames_dir.with_name("review-frames-displaced")
            fixture.review_frames_dir.rename(displaced)
            fixture.review_frames_dir.mkdir(mode=0o700)
            replaced = True
        return payload

    monkeypatch.setattr(validator, "_read_directory_file", replace_directory_path_after_first_read)

    with pytest.raises(ValueError, match="review frames changed"):
        validator.main(fixture.args)

    assert replaced
    assert not fixture.normalized_output.exists()
    assert not fixture.summary_output.exists()


def test_review_frame_hash_and_decode_use_the_same_single_read_bytes(tmp_path: Path) -> None:
    fixture = _cli_fixture(tmp_path)
    image_path = fixture.review_frames_dir / "H0001.jpg"
    invalid = b"not-a-jpeg"
    image_path.write_bytes(invalid)
    manifest = json.loads(fixture.manifest_path.read_text(encoding="utf-8"))
    snapshot = json.loads(fixture.snapshot_path.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(fixture.review_index_path.open(encoding="utf-8")))
    invalid_sha = hashlib.sha256(invalid).hexdigest()
    manifest["records"][0]["image_sha256"] = invalid_sha
    snapshot["images"][0]["image_sha256"] = invalid_sha
    rows[0]["image_sha256"] = invalid_sha
    fixture.review_index_sha256 = _write_review_index(fixture.review_index_path, rows)
    manifest["review_index_sha256"] = fixture.review_index_sha256
    fixture.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    fixture.manifest_path.chmod(0o600)
    fixture.snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    fixture.snapshot_path.chmod(0o600)
    _replace_arg(
        fixture.args,
        "--expected-review-index-sha256",
        fixture.review_index_sha256,
    )
    _replace_arg(
        fixture.args,
        "--expected-manifest-sha256",
        hashlib.sha256(fixture.manifest_path.read_bytes()).hexdigest(),
    )

    with pytest.raises(ValueError, match="JPEG decode"):
        validator.main(fixture.args)


def test_owner_ambiguous_accepts_only_empty_or_exact_header_and_rows_request_replacement(
    tmp_path: Path,
) -> None:
    fixture = _cli_fixture(tmp_path)
    fixture.ambiguous_path.write_text("sequence\nH0001\n", encoding="utf-8")
    fixture.ambiguous_path.chmod(0o600)

    with pytest.raises(ValueError, match="V24B_FUTURE_HOLDOUT_RESERVE_REPLACEMENT_REQUIRED"):
        validator.main(fixture.args)

    assert fixture.lock_path.exists()
    assert not fixture.normalized_output.exists()
    assert not fixture.summary_output.exists()


def test_existing_one_shot_lock_stops_before_any_input_read_and_preserves_rival(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _cli_fixture(tmp_path)
    fixture.lock_path.write_text('{"rival":true}\n', encoding="utf-8")
    fixture.lock_path.chmod(0o600)
    reads = 0

    def forbidden_read(*_args: object, **_kwargs: object) -> object:
        nonlocal reads
        reads += 1
        raise AssertionError("loser must not read inputs")

    monkeypatch.setattr(validator, "_read_regular_file", forbidden_read)

    with pytest.raises(FileExistsError, match="one-shot"):
        validator.main(fixture.args)

    assert reads == 0
    assert fixture.lock_path.read_text(encoding="utf-8") == '{"rival":true}\n'


def test_one_shot_lock_replacement_before_inputs_fails_and_preserves_rival(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _cli_fixture(tmp_path)
    real_link = os.link
    real_read_regular_file = validator._read_regular_file
    input_reads = 0

    def replace_lock_after_link(source: Path, target: Path) -> None:
        real_link(source, target)
        if Path(target) == fixture.lock_path:
            fixture.lock_path.unlink()
            fixture.lock_path.write_text('{"rival":true}\n', encoding="utf-8")
            fixture.lock_path.chmod(0o600)

    def count_input_reads(*args: object, **kwargs: object) -> bytes:
        nonlocal input_reads
        input_reads += 1
        return real_read_regular_file(*args, **kwargs)

    monkeypatch.setattr(validator, "_link_new", replace_lock_after_link)
    monkeypatch.setattr(validator, "_read_regular_file", count_input_reads)

    with pytest.raises(ValueError, match="lock ownership"):
        validator.main(fixture.args)

    assert input_reads == 0
    assert fixture.lock_path.read_text(encoding="utf-8") == '{"rival":true}\n'
    assert not fixture.normalized_output.exists()
    assert not fixture.summary_output.exists()


def test_second_output_publish_failure_rolls_back_owned_first_and_preserves_rival(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _cli_fixture(tmp_path)
    real_link = os.link

    def rival_before_summary_link(source: Path, target: Path) -> None:
        if Path(target) == fixture.summary_output:
            fixture.summary_output.write_text('{"rival":true}\n', encoding="utf-8")
            fixture.summary_output.chmod(0o600)
            raise FileExistsError("injected rival")
        real_link(source, target)

    monkeypatch.setattr(validator, "_link_new", rival_before_summary_link)

    with pytest.raises(FileExistsError, match="rival"):
        validator.main(fixture.args)

    assert not fixture.normalized_output.exists()
    assert fixture.summary_output.read_text(encoding="utf-8") == '{"rival":true}\n'
    assert not list(fixture.summary_output.parent.glob(".*.staging-*"))


def test_outputs_can_publish_to_two_distinct_existing_private_directories(
    tmp_path: Path,
) -> None:
    fixture = _cli_fixture(tmp_path)
    summary_parent = tmp_path / "summary-private"
    summary_parent.mkdir(mode=0o700)
    summary_output = summary_parent / "future-holdout-acceptance.private.json"
    _replace_arg(fixture.args, "--summary-output", str(summary_output))

    validator.main(fixture.args)

    assert json.loads(fixture.normalized_output.read_text(encoding="utf-8"))["status"] == (
        "V24B_FUTURE_HOLDOUT_ACCEPTED"
    )
    assert json.loads(summary_output.read_text(encoding="utf-8"))["status"] == (
        "V24B_FUTURE_HOLDOUT_ACCEPTED"
    )
    assert fixture.normalized_output.stat().st_mode & 0o777 == 0o600
    assert summary_output.stat().st_mode & 0o777 == 0o600


def test_second_staging_failure_cleans_first_staging_and_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _cli_fixture(tmp_path)
    real_write_staging = validator._write_staging_file

    def fail_summary_staging(path: Path, payload: bytes) -> Path:
        if path == fixture.summary_output:
            raise OSError("injected summary staging failure")
        return real_write_staging(path, payload)

    monkeypatch.setattr(validator, "_write_staging_file", fail_summary_staging)

    with pytest.raises(OSError, match="summary staging failure"):
        validator.main(fixture.args)

    assert not fixture.normalized_output.exists()
    assert not fixture.summary_output.exists()
    assert not list(fixture.normalized_output.parent.glob(".*.staging-*"))


def test_publish_rollback_never_unlinks_a_contested_public_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _cli_fixture(tmp_path)
    real_link = os.link
    real_unlink = Path.unlink
    public_unlinks = 0

    def rival_before_summary_link(source: Path, target: Path) -> None:
        if Path(target) == fixture.summary_output:
            fixture.summary_output.write_text('{"rival":true}\n', encoding="utf-8")
            fixture.summary_output.chmod(0o600)
            raise FileExistsError("injected rival")
        real_link(source, target)

    def forbid_public_unlink(path: Path, *args: object, **kwargs: object) -> None:
        nonlocal public_unlinks
        if path in {fixture.normalized_output, fixture.summary_output}:
            public_unlinks += 1
            raise AssertionError("contested public paths must not be unlinked")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(validator, "_link_new", rival_before_summary_link)
    monkeypatch.setattr(Path, "unlink", forbid_public_unlink)

    with pytest.raises(FileExistsError, match="rival"):
        validator.main(fixture.args)

    assert public_unlinks == 0
    assert not fixture.normalized_output.exists()
    assert fixture.summary_output.read_text(encoding="utf-8") == '{"rival":true}\n'
