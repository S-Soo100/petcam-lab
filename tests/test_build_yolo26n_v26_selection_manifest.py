from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.build_yolo26n_v26_recent_dense_queue import DenseFrame
import scripts.build_yolo26n_v26_selection_manifest as selection_manifest
from scripts.build_yolo26n_v26_selection_manifest import (
    build_selection_manifest,
    write_selection_once,
)
from scripts.select_yolo26n_v26_stratified_queue import (
    StratifiedQueueContract,
    select_stratified_queue,
)


def _frame(index: int) -> DenseFrame:
    return DenseFrame(
        clip_ref="clip-a",
        camera_night="camera-a:2026-08-24",
        timestamp_ms=index * 500,
        image_sha256=hashlib.sha256(f"image:{index}".encode()).hexdigest(),
        dhash64=int.from_bytes(hashlib.sha256(f"dhash:{index}".encode()).digest()[:8], "big"),
        detection_count=0,
        max_confidence=0.0,
        motion_score=0.0,
        scene_score=0.0,
        feedback_band=False,
    )


def _write_enriched_source(root: Path, *, feedback_band: bool | None = None) -> Path:
    clip_root = root / "clips" / "private-a"
    clip_root.mkdir(parents=True)
    row: dict[str, object] = {
        "clip_ref": "clip-a",
        "camera_night": "camera-a:2026-08-24",
        "timestamp_ms": 0,
        "image_sha256": "a" * 64,
        "dhash64": 1,
        "detection_count": 0,
        "max_confidence": 0.0,
        "motion_score": 1.0,
        "scene_score": 2.0,
    }
    if feedback_band is not None:
        row["feedback_band"] = feedback_band
    ledger = clip_root / "ledger.jsonl"
    ledger.write_text(json.dumps(row, sort_keys=True) + "\n")
    ledger_sha256 = hashlib.sha256(ledger.read_bytes()).hexdigest()
    clip_completion = {
        "status": "GME_JOIN_COMPLETE",
        "clip_ref": "clip-a",
        "private_ref": "private-a",
        "detector_identity": "d" * 64,
        "row_count": 1,
        "ledger_sha256": ledger_sha256,
    }
    (clip_root / "completion.private.json").write_text(
        json.dumps(clip_completion, sort_keys=True) + "\n"
    )
    final = {
        "status": "GME_JOIN_COMPLETE",
        "detector_identity": "d" * 64,
        "clip_count": 1,
        "row_count": 1,
        "clips": [clip_completion],
    }
    (root / "completion.private.json").write_text(json.dumps(final, sort_keys=True) + "\n")
    return ledger


def test_private_manifest_has_selection_lineage_without_prediction_boxes() -> None:
    selection = select_stratified_queue(
        [_frame(index) for index in range(5)],
        contract=StratifiedQueueContract(
            coverage_per_clip=1,
            uncertainty_count=0,
            hard_negative_count=0,
            iid_random_count=1,
            gold_count=1,
            seed="test-seed",
        ),
    )

    manifest = build_selection_manifest(
        selection,
        private_refs={"clip-a": "private-a"},
        dense_lineage_sha256="a" * 64,
        protected_lineage_sha256="b" * 64,
        contract=StratifiedQueueContract(
            coverage_per_clip=1,
            uncertainty_count=0,
            hard_negative_count=0,
            iid_random_count=1,
            gold_count=1,
            seed="test-seed",
        ),
    )

    assert manifest["aggregate"]["unique_image_count"] == 2
    assert manifest["aggregate"]["review_task_count"] == 3
    assert set(manifest["records"][0]) == {
        "camera_night",
        "clip_ref",
        "double_review",
        "dhash64",
        "image_sha256",
        "private_ref",
        "reasons",
        "stratum",
        "timestamp_ms",
    }
    assert "detections" not in manifest["records"][0]
    assert len(manifest["selection_sha256"]) == 64


def test_selection_writer_never_overwrites(tmp_path: Path) -> None:
    destination = tmp_path / "selection.private.json"
    write_selection_once(destination, {"status": "one"})
    with pytest.raises(FileExistsError):
        write_selection_once(destination, {"status": "two"})


def test_selection_rejects_tampered_enriched_ledger_before_reading_frames(
    tmp_path: Path,
) -> None:
    ledger = _write_enriched_source(tmp_path)
    with ledger.open("a") as handle:
        handle.write("{}\n")

    with pytest.raises(ValueError, match="enriched ledger SHA"):
        selection_manifest.load_validated_enriched_frames(tmp_path)


def test_selection_preserves_explicit_feedback_band_signal(tmp_path: Path) -> None:
    _write_enriched_source(tmp_path, feedback_band=True)

    _completion, frames, _private_refs = selection_manifest.load_validated_enriched_frames(
        tmp_path
    )

    assert frames[0].feedback_band is True


def test_selection_defaults_missing_feedback_band_to_false_with_warning(
    tmp_path: Path,
) -> None:
    _write_enriched_source(tmp_path)

    with pytest.warns(UserWarning, match="feedback_band"):
        _completion, frames, _private_refs = (
            selection_manifest.load_validated_enriched_frames(tmp_path)
        )

    assert frames[0].feedback_band is False


def test_selection_rejects_invalid_enriched_per_clip_status(tmp_path: Path) -> None:
    _write_enriched_source(tmp_path, feedback_band=False)
    completion_path = tmp_path / "clips" / "private-a" / "completion.private.json"
    completion = json.loads(completion_path.read_text())
    completion["status"] = "PARTIAL"
    completion_path.write_text(json.dumps(completion, sort_keys=True) + "\n")

    with pytest.raises(ValueError, match="enriched per-clip status"):
        selection_manifest.load_validated_enriched_frames(tmp_path)


def test_selection_rejects_enriched_ledger_row_count_drift(tmp_path: Path) -> None:
    _write_enriched_source(tmp_path, feedback_band=False)
    completion_path = tmp_path / "clips" / "private-a" / "completion.private.json"
    completion = json.loads(completion_path.read_text())
    completion["row_count"] = 2
    completion_path.write_text(json.dumps(completion, sort_keys=True) + "\n")
    final_path = tmp_path / "completion.private.json"
    final = json.loads(final_path.read_text())
    final["row_count"] = 2
    final["clips"][0]["row_count"] = 2
    final_path.write_text(json.dumps(final, sort_keys=True) + "\n")

    with pytest.raises(ValueError, match="enriched ledger row count"):
        selection_manifest.load_validated_enriched_frames(tmp_path)
