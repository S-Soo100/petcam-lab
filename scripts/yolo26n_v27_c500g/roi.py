"""Task 4 — ROI 프로파일 검증 · crop · 원본↔ROI 좌표 왕복.

왜 별도 모듈인가: ROI 사각형은 사람이 train role 썸네일을 보고 그린 값이라 "픽셀 접근 규칙"
(holdout 프레임으로 보정 금지)과 기하 규칙(카메라당 정확히 3개, 좌→중→우 겹침 없음)을
코드로 강제해야 한다. crop/좌표 변환은 모두 `crop_bounds` 하나에서 파생돼 왕복 오차가 없다.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping

import numpy as np

from scripts.yolo26n_v27_c500g.contracts import (
    Box,
    CalibrationProvenance,
    Role,
    RoiProfile,
    RoiRect,
)

ROI_PROFILE_SCHEMA = "yolo26n-v27-c500g-roi-profile-v1"
ROI_NAMES: tuple[str, ...] = ("left", "middle", "right")
# 보정 프레임으로 열어도 되는 role. holdout 계열은 픽셀 접근 자체가 금지.
CALIBRATION_ALLOWED_ROLES = frozenset({Role.V27_TRAIN})
_GEOMETRY_FIELDS = ("frame_width", "frame_height", "padding_px", "cameras")
_BOX_TOLERANCE_PX = 1.0


def profile_digest(body: Mapping[str, object]) -> str:
    """기하(프레임 크기·padding·사각형)만 canonical JSON 으로 해시. status 등 메타는 제외."""
    payload = {field: body.get(field) for field in _GEOMETRY_FIELDS}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_roi_profile(
    body: Mapping[str, object],
    roles: Mapping[str, object],
    *,
    calibration_sources: Iterable[str],
) -> RoiProfile:
    """ROI 프로파일 JSON 을 검증해 `RoiProfile` 로 승격한다.

    검사 순서: 스키마 → digest 일치 → IR/저녁 검증 플래그 → 보정 프레임 role 게이트 →
    카메라 집합이 role manifest 와 일치 → 카메라별 정확히 3개(left/middle/right) → 좌→중→우 겹침 없음.
    """
    if body.get("schema") != ROI_PROFILE_SCHEMA:
        raise ValueError(f"schema must be {ROI_PROFILE_SCHEMA}")
    expected = profile_digest(body)
    if body.get("profile_sha256") != expected:
        raise ValueError("profile_sha256 does not match geometry digest")
    if body.get("ir_verified") is not True:
        raise ValueError("ir_verified must be true (IR frames are the pilot majority)")
    if body.get("day_verified") is not True:
        raise ValueError("day_verified must be true (boundary checked on evening frame)")
    if body.get("calibration_provenance") != CalibrationProvenance.V27_TRAIN.value:
        raise ValueError("calibration_provenance must be v27_train for this attempt")

    rows = roles.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("roles manifest has no rows")
    role_by_source: dict[str, Role] = {}
    camera_digests: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("roles row must be an object")
        role_by_source[str(row["source_ref"])] = Role(str(row["role"]))
        camera_digests.add(str(row["anonymous_camera_digest"]))

    for source in calibration_sources:
        role = role_by_source.get(source)
        if role is None:
            raise ValueError(f"calibration source not in role manifest: {source}")
        if role not in CALIBRATION_ALLOWED_ROLES:
            raise ValueError(
                f"calibration source {source} has role {role.value} (holdout/protected); only v27_train frames may be opened"
            )

    cameras = body.get("cameras")
    if not isinstance(cameras, Mapping):
        raise ValueError("cameras must be an object")
    if set(cameras) != camera_digests:
        raise ValueError("profile camera digests do not match role manifest cameras")
    for camera, rects in cameras.items():
        if not isinstance(rects, Mapping) or set(rects) != set(ROI_NAMES) or len(rects) != 3:
            raise ValueError(f"camera {camera[:12]} must have exactly 3 ROI rects named {ROI_NAMES}")
        parsed = [RoiRect.from_json(rects[name]) for name in ROI_NAMES]
        for left, right, name in zip(parsed, parsed[1:], ROI_NAMES[1:], strict=False):
            if right.x1 < left.x2:
                raise ValueError(f"camera {camera[:12]} ROI '{name}' overlaps its left neighbour (x1 {right.x1:.4f} < x2 {left.x2:.4f})")

    return RoiProfile.from_json(body)


def crop_bounds(rect: RoiRect, padding_px: int, frame_width: int, frame_height: int) -> tuple[int, int, int, int]:
    """정규화 ROI + padding 을 원본 픽셀 정수 경계(x1, y1, x2, y2)로. 프레임 밖은 잘라낸다."""
    if padding_px < 0:
        raise ValueError("padding_px must be non-negative")
    x1 = max(0, round(rect.x1 * frame_width) - padding_px)
    y1 = max(0, round(rect.y1 * frame_height) - padding_px)
    x2 = min(frame_width, round(rect.x2 * frame_width) + padding_px)
    y2 = min(frame_height, round(rect.y2 * frame_height) + padding_px)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("ROI crop collapsed to zero area")
    return x1, y1, x2, y2


def crop_frame(frame: np.ndarray, rect: RoiRect, padding_px: int) -> tuple[np.ndarray, tuple[int, int]]:
    """프레임에서 ROI(+padding) 영역을 잘라 (crop, (x0, y0)) 반환. crop 은 view(복사 없음)."""
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = crop_bounds(rect, padding_px, width, height)
    return frame[y1:y2, x1:x2], (x1, y1)


def roi_box_to_full(box: Box, rect: RoiRect, *, padding_px: int, frame_width: int, frame_height: int) -> Box:
    """crop 좌표계 박스 → 원본 프레임 좌표계."""
    x0, y0, _, _ = crop_bounds(rect, padding_px, frame_width, frame_height)
    return Box(box.x1 + x0, box.y1 + y0, box.x2 + x0, box.y2 + y0)


def full_box_to_roi(box: Box, rect: RoiRect, *, padding_px: int, frame_width: int, frame_height: int) -> Box:
    """원본 프레임 좌표계 박스 → crop 좌표계. crop 밖(1px 허용)이면 ValueError."""
    x1, y1, x2, y2 = crop_bounds(rect, padding_px, frame_width, frame_height)
    tol = _BOX_TOLERANCE_PX
    if box.x1 < x1 - tol or box.y1 < y1 - tol or box.x2 > x2 + tol or box.y2 > y2 + tol:
        raise ValueError("box lies outside the ROI crop bounds")
    return Box(box.x1 - x1, box.y1 - y1, box.x2 - x1, box.y2 - y1)
