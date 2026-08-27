from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.join_yolo26n_v25_gme_artifacts as join_artifacts
from scripts.join_yolo26n_v25_gme_artifacts import enrich_dense_rows


def _dense(timestamp_ms: int) -> dict[str, object]:
    return {
        "clip_ref": "clip-a",
        "camera_night": "camera-a:2026-08-24",
        "frame_index": timestamp_ms // 100,
        "timestamp_ms": timestamp_ms,
        "image_sha256": f"{timestamp_ms:064x}",
        "dhash64": timestamp_ms,
        "motion_score": 1.0,
        "scene_score": 2.0,
        "detector_status": "pending",
    }


def _write_dense_source(root: Path) -> Path:
    clip_root = root / "clips" / "private-a"
    clip_root.mkdir(parents=True)
    ledger = clip_root / "ledger.jsonl"
    ledger.write_text(json.dumps(_dense(0), sort_keys=True) + "\n")
    ledger_sha256 = hashlib.sha256(ledger.read_bytes()).hexdigest()
    source_sha256 = "a" * 64
    clip_completion = {
        "status": "DENSE_CLIP_COMPLETE",
        "clip_ref": "clip-a",
        "camera_night": "camera-a:2026-08-24",
        "source_size_bytes": 100,
        "source_sha256": source_sha256,
        "sample_fps": 2.0,
        "sampled_frame_count": 1,
        "ledger_sha256": ledger_sha256,
    }
    (clip_root / "completion.private.json").write_text(
        json.dumps(clip_completion, sort_keys=True) + "\n"
    )
    final = {
        "status": "DENSE_EXTRACTION_COMPLETE",
        "source_manifest_sha256": "b" * 64,
        "source_lineage_sha256": "c" * 64,
        "clip_count": 1,
        "sampled_frame_count": 1,
        "sample_fps": 2.0,
        "clips": [
            {
                "private_ref": "private-a",
                "clip_ref": "clip-a",
                "source_sha256": source_sha256,
                "ledger_sha256": ledger_sha256,
                "sampled_frame_count": 1,
            }
        ],
    }
    (root / "completion.private.json").write_text(json.dumps(final, sort_keys=True) + "\n")
    return ledger


def test_join_matches_nearest_track_point_and_counts_unique_tracks() -> None:
    rows = [_dense(0), _dense(500), _dense(1000)]
    track_points = [
        {
            "timestamp_sec": 0.49,
            "track_id": "track-a",
            "confidence": 0.4,
            "bbox_norm": [0.1, 0.2, 0.3, 0.4],
            "provenance": "detected",
        },
        {
            "timestamp_sec": 0.51,
            "track_id": "track-a",
            "confidence": 0.8,
            "bbox_norm": [0.2, 0.2, 0.3, 0.4],
            "provenance": "detected",
        },
        {
            "timestamp_sec": 0.50,
            "track_id": "track-b",
            "confidence": 0.7,
            "bbox_norm": [0.5, 0.5, 0.2, 0.2],
            "provenance": "interpolated",
        },
    ]

    enriched = enrich_dense_rows(rows, track_points, tolerance_ms=60)

    assert enriched[0]["detection_count"] == 0
    assert enriched[1]["detection_count"] == 2
    assert enriched[1]["max_confidence"] == 0.8
    assert [box["track_id"] for box in enriched[1]["detections"]] == ["track-a", "track-b"]
    assert enriched[2]["detection_count"] == 0
    assert all(row["detector_status"] == "joined-v2.5-gme-artifact" for row in enriched)


def test_join_does_not_stretch_detection_past_time_tolerance() -> None:
    rows = [_dense(500)]
    track_points = [
        {
            "timestamp_sec": 0.57,
            "track_id": "track-a",
            "confidence": 0.9,
            "bbox_norm": [0.1, 0.1, 0.2, 0.2],
            "provenance": "detected",
        }
    ]

    assert enrich_dense_rows(rows, track_points, tolerance_ms=60)[0]["detection_count"] == 0


def test_join_rejects_malformed_track_point_instead_of_treating_it_as_negative() -> None:
    with pytest.raises(ValueError, match="track point"):
        enrich_dense_rows([_dense(0)], [{"timestamp_sec": 0.0}], tolerance_ms=60)


def test_join_rejects_invalid_tolerance() -> None:
    with pytest.raises(ValueError, match="tolerance"):
        enrich_dense_rows([_dense(0)], [], tolerance_ms=-1)


def test_join_rejects_tampered_dense_ledger_before_loading_remote_artifacts(
    tmp_path: Path,
) -> None:
    ledger = _write_dense_source(tmp_path)
    with ledger.open("a") as handle:
        handle.write("{}\n")

    with pytest.raises(ValueError, match="dense ledger SHA"):
        join_artifacts.load_validated_dense_inputs(tmp_path)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("status", "PARTIAL", "dense completion status"),
        ("clip_count", 2, "dense completion clip count"),
        ("sampled_frame_count", 2, "dense completion row count"),
    ],
)
def test_join_rejects_invalid_dense_final_contract(
    tmp_path: Path,
    field: str,
    value: object,
    error: str,
) -> None:
    _write_dense_source(tmp_path)
    final_path = tmp_path / "completion.private.json"
    final = json.loads(final_path.read_text())
    final[field] = value
    final_path.write_text(json.dumps(final, sort_keys=True) + "\n")

    with pytest.raises(ValueError, match=error):
        join_artifacts.load_validated_dense_inputs(tmp_path)


def test_join_rejects_dense_clip_directory_outside_final_clip_set(tmp_path: Path) -> None:
    _write_dense_source(tmp_path)
    (tmp_path / "clips" / "unlisted-private-ref").mkdir()

    with pytest.raises(ValueError, match="dense clip set"):
        join_artifacts.load_validated_dense_inputs(tmp_path)


def test_join_rejects_invalid_dense_per_clip_status(tmp_path: Path) -> None:
    _write_dense_source(tmp_path)
    completion_path = tmp_path / "clips" / "private-a" / "completion.private.json"
    completion = json.loads(completion_path.read_text())
    completion["status"] = "PARTIAL"
    completion_path.write_text(json.dumps(completion, sort_keys=True) + "\n")

    with pytest.raises(ValueError, match="dense per-clip status"):
        join_artifacts.load_validated_dense_inputs(tmp_path)


def test_join_rejects_dense_ledger_row_count_drift(tmp_path: Path) -> None:
    _write_dense_source(tmp_path)
    completion_path = tmp_path / "clips" / "private-a" / "completion.private.json"
    completion = json.loads(completion_path.read_text())
    completion["sampled_frame_count"] = 2
    completion_path.write_text(json.dumps(completion, sort_keys=True) + "\n")
    final_path = tmp_path / "completion.private.json"
    final = json.loads(final_path.read_text())
    final["sampled_frame_count"] = 2
    final["clips"][0]["sampled_frame_count"] = 2
    final_path.write_text(json.dumps(final, sort_keys=True) + "\n")

    with pytest.raises(ValueError, match="dense ledger row count"):
        join_artifacts.load_validated_dense_inputs(tmp_path)
