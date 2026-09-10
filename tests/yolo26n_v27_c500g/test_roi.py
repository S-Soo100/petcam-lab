"""Task 4 — train-only ROI profile 검증, crop, 원본 좌표 round-trip."""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pytest

from scripts.yolo26n_v27_c500g.contracts import Box, RoiRect
from scripts.yolo26n_v27_c500g.roi import (
    ROI_PROFILE_SCHEMA,
    crop_frame,
    full_box_to_roi,
    profile_digest,
    roi_box_to_full,
    validate_roi_profile,
)
from tests.yolo26n_v27_c500g.factories import SHA_A, ZERO_WRITES


def _digest(cam: str) -> str:
    return hashlib.sha256(f"camera:{cam}".encode()).hexdigest()


def _rects(shift: float = 0.0) -> dict[str, dict[str, float]]:
    return {
        "left": {"x1": 0.02 + shift, "y1": 0.05, "x2": 0.32 + shift, "y2": 0.98},
        "middle": {"x1": 0.35, "y1": 0.05, "x2": 0.65, "y2": 0.98},
        "right": {"x1": 0.68, "y1": 0.05, "x2": 0.98, "y2": 0.98},
    }


def _profile(**over) -> dict[str, object]:
    cameras = {_digest(c): _rects() for c in ("cam01", "cam02", "cam03")}
    body = {
        "schema": ROI_PROFILE_SCHEMA, "status": "V27_ROI_PROFILE_READY", "test_sheet_sha256": SHA_A,
        "frame_width": 2880, "frame_height": 1620, "padding_px": 24,
        "calibration_provenance": "v27_train", "day_verified": True, "ir_verified": True,
        "cameras": cameras, **ZERO_WRITES,
    }
    body.update(over)
    body["profile_sha256"] = profile_digest(body)
    return body


def _roles(*, holdout_camera: str | None = None) -> dict[str, object]:
    rows = []
    for c in ("cam01", "cam02", "cam03"):
        rows.append({"source_ref": f"recordings/{c}/night=2026-09-05/slot", "source_sha256": SHA_A,
                     "anonymous_camera_digest": _digest(c), "camera_night": "x", "role": "v26_holdout" if c == holdout_camera else "v27_train"})
    return {"schema": "yolo26n-v27-c500g-role-freeze-v1", "status": "V27_ROLE_FREEZE_READY", "rows": rows}


def test_profile_digest_is_canonical_over_geometry_only():
    a = _profile()
    b = _profile(status="something-else")
    assert a["profile_sha256"] == b["profile_sha256"]
    c = _profile(padding_px=25)
    assert c["profile_sha256"] != a["profile_sha256"]


def test_validate_returns_roi_profile_with_three_rects_per_camera():
    profile = validate_roi_profile(_profile(), _roles(), calibration_sources=[f"recordings/cam0{i}/night=2026-09-05/slot" for i in (1, 2, 3)])
    assert set(profile.cameras) == {_digest("cam01"), _digest("cam02"), _digest("cam03")}
    assert set(profile.cameras[_digest("cam01")]) == {"left", "middle", "right"}
    assert isinstance(profile.cameras[_digest("cam01")]["left"], RoiRect)


def test_validate_requires_exactly_three_named_rects():
    body = _profile()
    del body["cameras"][_digest("cam02")]["right"]
    body["profile_sha256"] = profile_digest(body)
    with pytest.raises(ValueError, match="exactly 3"):
        validate_roi_profile(body, _roles(), calibration_sources=[])


def test_validate_rejects_overlapping_or_unordered_rects():
    body = _profile()
    body["cameras"][_digest("cam01")]["middle"]["x1"] = 0.20  # 왼쪽과 겹침
    body["profile_sha256"] = profile_digest(body)
    with pytest.raises(ValueError, match="overlap"):
        validate_roi_profile(body, _roles(), calibration_sources=[])


def test_validate_rejects_calibration_frames_from_protected_roles():
    roles = _roles(holdout_camera="cam02")
    with pytest.raises(ValueError, match="holdout"):
        validate_roi_profile(_profile(), roles, calibration_sources=["recordings/cam02/night=2026-09-05/slot"])


def test_validate_rejects_digest_drift_and_missing_verification():
    body = _profile()
    body["profile_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="profile_sha256"):
        validate_roi_profile(body, _roles(), calibration_sources=[])
    with pytest.raises(ValueError, match="ir_verified"):
        validate_roi_profile(_profile(ir_verified=False), _roles(), calibration_sources=[])


def test_validate_requires_cameras_to_match_roles():
    body = _profile()
    body["cameras"][_digest("cam09")] = body["cameras"].pop(_digest("cam03"))
    body["profile_sha256"] = profile_digest(body)
    with pytest.raises(ValueError, match="camera"):
        validate_roi_profile(body, _roles(), calibration_sources=[])


# ── crop / round-trip ──────────────────────────────────────────────

def test_crop_frame_returns_padded_region_and_origin():
    frame = np.zeros((1620, 2880, 3), dtype=np.uint8)
    frame[100:200, 300:400] = 255
    rect = RoiRect(300 / 2880, 100 / 1620, 400 / 2880, 200 / 1620)
    crop, origin = crop_frame(frame, rect, padding_px=10)
    assert origin == (290, 90)
    assert crop.shape == (120, 120, 3)
    assert crop[10:110, 10:110].min() == 255 and crop[0, 0, 0] == 0


def test_crop_frame_clamps_padding_at_frame_edges():
    frame = np.zeros((1620, 2880, 3), dtype=np.uint8)
    rect = RoiRect(0.0, 0.0, 100 / 2880, 100 / 1620)
    crop, origin = crop_frame(frame, rect, padding_px=50)
    assert origin == (0, 0)
    assert crop.shape == (150, 150, 3)


def test_roi_box_round_trip_is_within_one_pixel():
    rect = RoiRect(0.35, 0.05, 0.65, 0.98)
    original = Box(41.0, 52.0, 131.0, 202.0)
    full = roi_box_to_full(original, rect, padding_px=12, frame_width=2880, frame_height=1620)
    assert full.x1 == pytest.approx(0.35 * 2880 - 12 + 41.0, abs=1e-6)
    restored = full_box_to_roi(full, rect, padding_px=12, frame_width=2880, frame_height=1620)
    assert max(abs(getattr(original, f) - getattr(restored, f)) for f in ("x1", "y1", "x2", "y2")) <= 1.0


def test_full_box_to_roi_rejects_box_outside_crop():
    rect = RoiRect(0.35, 0.05, 0.65, 0.98)
    with pytest.raises(ValueError, match="outside"):
        full_box_to_roi(Box(10.0, 10.0, 50.0, 50.0), rect, padding_px=0, frame_width=2880, frame_height=1620)
