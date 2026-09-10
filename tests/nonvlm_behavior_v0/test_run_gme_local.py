"""연구 러너의 순수 부분 — 계약 핀 검증·확장 artifact 조립·멱등 skip. gate 패키지 없이 duck-typed 로 검증.

실제 detector/analyze_clip 은 gate venv 에서만 import 되며(지연 import) 여기서는 호출하지 않는다.
"""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.nonvlm_behavior_v0.run_gme_local import (
    CONTRACT,
    ContractMismatch,
    assert_contract,
    build_extended_artifact,
    should_skip,
)


@dataclass
class _Analysis:
    status: str = "ok"
    duration_sec: float = 60.0
    decoded_frame_count: int = 1800
    analyzed_frame_count: int = 600
    source_fps: float = 30.0
    candidate_moving_sec_any_gecko: float = 12.5
    moving_gecko_seconds: float = 12.5
    visible_sec: float = 55.0
    unknown_sec: float = 5.0
    camera_motion_sec: float = 0.0
    max_simultaneous_geckos: int = 1
    frame_debug: tuple = ({"timestamp_sec": 0.0, "exposure_change": False, "camera_motion": False},)


def _permanent_gz(payload: dict) -> bytes:
    return gzip.compress(json.dumps(payload, sort_keys=True).encode())


def test_contract_pins_production_values():
    assert CONTRACT["analysis_fps"] == 10.0
    assert CONTRACT["anchor_interval_sec"] == 0.1
    assert CONTRACT["raw_confidence"] == 0.001
    assert CONTRACT["score_threshold"] == 0.15
    assert CONTRACT["image_size"] == 960
    assert CONTRACT["nms_iou"] == 0.70
    assert CONTRACT["post_nms_iou"] == 0.55
    assert CONTRACT["max_detections"] == 50
    assert CONTRACT["temporal_window_frames"] == 5
    assert CONTRACT["temporal_min_positive_frames"] == 3
    assert CONTRACT["algorithm_version"] == "gme-motion-v1"
    assert CONTRACT["model_version"] == "v2.6-warm-start-s28"
    assert len(CONTRACT["checkpoint_sha256"]) == 64
    assert len(CONTRACT["detector_identity"]) == 64


def test_assert_contract_raises_on_identity_mismatch():
    with pytest.raises(ContractMismatch, match="detector_identity"):
        assert_contract(detector_identity="0" * 64, algorithm_version="gme-motion-v1", engine_config_v26=True)


def test_assert_contract_raises_on_algorithm_mismatch():
    with pytest.raises(ContractMismatch, match="algorithm_version"):
        assert_contract(detector_identity=CONTRACT["detector_identity"], algorithm_version="gme-motion-v0", engine_config_v26=True)


def test_assert_contract_raises_when_engine_config_is_not_v26():
    with pytest.raises(ContractMismatch, match="engine_config"):
        assert_contract(detector_identity=CONTRACT["detector_identity"], algorithm_version="gme-motion-v1", engine_config_v26=False)


def test_assert_contract_passes_when_all_match():
    assert_contract(detector_identity=CONTRACT["detector_identity"], algorithm_version="gme-motion-v1", engine_config_v26=True)


def test_build_extended_artifact_carries_gme_payload_summary_and_provenance():
    payload = {"schema_version": "gme-artifact-v1", "intervals": [], "track_points": [], "duration_sec": 60.0}
    art = build_extended_artifact(
        analysis=_Analysis(), permanent_gzip=_permanent_gz(payload), filename="x.mp4",
        source_sha256="ab" * 32, elapsed_sec=12.3, run_id="run-1",
    )
    assert art["gme"] == payload
    assert art["summary"]["status"] == "ok"
    assert art["summary"]["candidate_moving_sec_any_gecko"] == 12.5
    assert art["summary"]["visible_sec"] == 55.0
    assert art["summary"]["max_simultaneous_geckos"] == 1
    assert art["source"] == {"filename": "x.mp4", "sha256": "ab" * 32}
    assert art["run"]["run_id"] == "run-1" and art["run"]["elapsed_sec"] == 12.3
    assert art["run"]["contract"] == CONTRACT
    assert art["frame_debug"][0]["timestamp_sec"] == 0.0


def test_should_skip_only_when_complete_artifact_exists(tmp_path: Path):
    out = tmp_path / "x.mp4.json.gz"
    assert should_skip(out) is False
    out.write_bytes(gzip.compress(b'{"summary": {"status": "ok"}}'))
    assert should_skip(out) is True
    out.write_bytes(gzip.compress(b'{"summary": {"status": "invalid_metadata"}}'))
    assert should_skip(out) is False  # 실패 artifact 는 재시도 대상
