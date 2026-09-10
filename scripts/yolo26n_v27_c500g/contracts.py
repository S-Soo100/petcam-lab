"""Strict immutable contracts shared by the v2.7 preparation stages."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping


WRITE_COUNT_FIELDS = (
    "db_write_count",
    "r2_write_count",
    "service_write_count",
    "git_write_count",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ANONYMOUS_SEQUENCE_RE = re.compile(r"^V27[A-Z][0-9]{4,}$")


class Role(StrEnum):
    V26_HOLDOUT = "v26_holdout"
    V26_HOLDOUT_DATE_GUARD = "v26_holdout_date_guard"
    V27_TRAIN = "v27_train"
    V27_VAL = "v27_val"


class ReviewStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNCERTAIN = "uncertain"
    MEDIA_ERROR = "media_error"


class CalibrationProvenance(StrEnum):
    V27_TRAIN = "v27_train"
    PRE_STUDY_CALIBRATION = "pre_study_calibration"


class ProtectedRole(StrEnum):
    V26_HOLDOUT = "v26_holdout"
    V27_FUTURE_HOLDOUT = "v27_future_holdout"
    OLD_FIXED_TEST = "old_fixed_test"


def strict_object(
    value: object,
    required: Iterable[str],
    optional: Iterable[str] = (),
) -> dict[str, object]:
    """Return a shallow copy after exact-key and shared root validation.

    A mapping that carries ``schema`` is a persisted schema root. Root validation
    always requires all four forbidden-write counters, even if a caller forgets
    to repeat them in ``required``. This keeps later stage validators fail-closed.
    """
    if not isinstance(value, Mapping):
        raise ValueError("value must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ValueError("object keys must be strings")

    required_keys = set(required)
    optional_keys = set(optional)
    if "schema" in value or "schema" in required_keys:
        required_keys.update(WRITE_COUNT_FIELDS)

    missing = required_keys.difference(value)
    if missing:
        raise ValueError(f"missing required keys: {', '.join(sorted(missing))}")
    unknown = set(value).difference(required_keys | optional_keys)
    if unknown:
        raise ValueError(f"unknown keys: {', '.join(sorted(unknown))}")

    parsed = dict(value)
    if "schema" in parsed:
        _nonempty_string(parsed["schema"], "schema")
        for field in WRITE_COUNT_FIELDS:
            if type(parsed[field]) is not int or parsed[field] != 0:
                raise ValueError(f"{field} must be literal integer 0")
    if "test_sheet_sha256" in parsed:
        _sha256(parsed["test_sheet_sha256"], "test_sheet_sha256")
    return parsed


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field} must be a non-empty canonical string")
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be exactly 64 lowercase hexadecimal characters")
    return value


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _number(value: object, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    parsed = float(value)
    if not math.isfinite(parsed) or (minimum is not None and parsed < minimum):
        raise ValueError(f"{field} must be a finite number >= {minimum}")
    return parsed


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} must be a boolean")
    return value


def _role(value: object) -> Role:
    try:
        return Role(value)
    except (TypeError, ValueError) as error:
        raise ValueError("role must be a current Role value") from error


def _enum_value(value: object, enum_type: type[StrEnum], field: str) -> StrEnum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} has an unsupported value") from error


def _anonymous_sequence(value: object) -> str:
    parsed = _nonempty_string(value, "anonymous_sequence")
    if _ANONYMOUS_SEQUENCE_RE.fullmatch(parsed) is None:
        raise ValueError(
            "anonymous_sequence must be V27 + uppercase queue code + at least 4 digits"
        )
    return parsed


def _box(value: object, field: str = "box") -> "Box":
    if isinstance(value, Box):
        return value
    if isinstance(value, Mapping):
        return Box.from_json(value)
    raise ValueError(f"{field} must be a Box or strict box object")


def _boxes(value: object) -> tuple["Box", ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("boxes must be a sequence")
    return tuple(_box(item, "boxes item") for item in value)


def _frozen_runs(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("runs must be a sequence")
    frozen: list[Mapping[str, object]] = []
    for candidate in value:
        run = strict_object(candidate, {"seed", "initializer", "status"})
        frozen.append(
            MappingProxyType(
                {
                    "seed": _positive_int(run["seed"], "run seed"),
                    "initializer": _nonempty_string(
                        run["initializer"], "run initializer"
                    ),
                    "status": _nonempty_string(run["status"], "run status"),
                }
            )
        )
    return tuple(frozen)


def _frozen_cameras(
    value: object,
) -> Mapping[str, Mapping[str, "RoiRect"]]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("cameras must be a non-empty object")
    cameras: dict[str, Mapping[str, RoiRect]] = {}
    for camera, rect_values in value.items():
        camera_name = _nonempty_string(camera, "camera digest")
        if not isinstance(rect_values, Mapping):
            raise ValueError("camera ROI values must be an object")
        rects: dict[str, RoiRect] = {}
        for name, candidate in rect_values.items():
            roi_name = _nonempty_string(name, "ROI name")
            rects[roi_name] = (
                candidate
                if isinstance(candidate, RoiRect)
                else RoiRect.from_json(candidate)
            )
        cameras[camera_name] = MappingProxyType(rects)
    return MappingProxyType(cameras)


def _validate_root_instance(value: object) -> None:
    _nonempty_string(getattr(value, "schema"), "schema")
    _nonempty_string(getattr(value, "status"), "status")
    _sha256(getattr(value, "test_sheet_sha256"), "test_sheet_sha256")
    for field in WRITE_COUNT_FIELDS:
        count = getattr(value, field)
        if type(count) is not int or count != 0:
            raise ValueError(f"{field} must be literal integer 0")


@dataclass(frozen=True, slots=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        coordinates = tuple(
            _number(value, "box coordinate")
            for value in (self.x1, self.y1, self.x2, self.y2)
        )
        if coordinates[2] <= coordinates[0] or coordinates[3] <= coordinates[1]:
            raise ValueError("box must have positive finite area")
        for field, value in zip(("x1", "y1", "x2", "y2"), coordinates, strict=True):
            object.__setattr__(self, field, value)

    @classmethod
    def from_json(cls, value: object) -> "Box":
        raw = strict_object(value, {"x1", "y1", "x2", "y2"})
        return cls(raw["x1"], raw["y1"], raw["x2"], raw["y2"])  # type: ignore[arg-type]

    def to_json(self) -> dict[str, float]:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_ref: str
    source_sha256: str
    anonymous_camera_digest: str
    camera_night: str
    scheduled_start_utc: str
    duration_sec: float
    width: int
    height: int
    fps: float
    codec: str
    role: Role

    def __post_init__(self) -> None:
        scheduled = _nonempty_string(self.scheduled_start_utc, "scheduled_start_utc")
        if not scheduled.endswith("Z"):
            raise ValueError("scheduled_start_utc must be canonical UTC ending in Z")
        codec = _nonempty_string(self.codec, "codec").lower()
        if codec not in {"hevc", "h264"}:
            raise ValueError("codec must be hevc or h264")
        normalized = {
            "source_ref": _nonempty_string(self.source_ref, "source_ref"),
            "source_sha256": _sha256(self.source_sha256, "source_sha256"),
            "anonymous_camera_digest": _nonempty_string(
                self.anonymous_camera_digest, "anonymous_camera_digest"
            ),
            "camera_night": _nonempty_string(self.camera_night, "camera_night"),
            "scheduled_start_utc": scheduled,
            "duration_sec": _number(self.duration_sec, "duration_sec", minimum=0.0),
            "width": _positive_int(self.width, "width"),
            "height": _positive_int(self.height, "height"),
            "fps": _number(self.fps, "fps", minimum=0.0),
            "codec": codec,
            "role": _role(self.role),
        }
        for field, value in normalized.items():
            object.__setattr__(self, field, value)

    @classmethod
    def from_json(cls, value: object) -> "SourceRecord":
        raw = strict_object(
            value,
            {
                "source_ref",
                "source_sha256",
                "anonymous_camera_digest",
                "camera_night",
                "scheduled_start_utc",
                "duration_sec",
                "width",
                "height",
                "fps",
                "codec",
                "role",
            },
        )
        return cls(**raw)  # type: ignore[arg-type]

    def to_json(self) -> dict[str, object]:
        return {
            "source_ref": self.source_ref,
            "source_sha256": self.source_sha256,
            "anonymous_camera_digest": self.anonymous_camera_digest,
            "camera_night": self.camera_night,
            "scheduled_start_utc": self.scheduled_start_utc,
            "duration_sec": self.duration_sec,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "codec": self.codec,
            "role": self.role.value,
        }


@dataclass(frozen=True, slots=True)
class RoiRect:
    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        box = Box(self.x1, self.y1, self.x2, self.y2)
        if min(box.x1, box.y1) < 0.0 or max(box.x2, box.y2) > 1.0:
            raise ValueError("ROI rect must be within normalized [0,1] bounds")
        for field in ("x1", "y1", "x2", "y2"):
            object.__setattr__(self, field, getattr(box, field))

    @classmethod
    def from_json(cls, value: object) -> "RoiRect":
        raw = strict_object(value, {"x1", "y1", "x2", "y2"})
        return cls(raw["x1"], raw["y1"], raw["x2"], raw["y2"])  # type: ignore[arg-type]

    def to_json(self) -> dict[str, float]:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}


@dataclass(frozen=True, slots=True)
class RoiProfile:
    schema: str
    status: str
    test_sheet_sha256: str
    profile_sha256: str
    frame_width: int
    frame_height: int
    padding_px: int
    calibration_provenance: CalibrationProvenance
    day_verified: bool
    ir_verified: bool
    cameras: Mapping[str, Mapping[str, RoiRect]]
    db_write_count: int = 0
    r2_write_count: int = 0
    service_write_count: int = 0
    git_write_count: int = 0

    def __post_init__(self) -> None:
        _validate_root_instance(self)
        normalized = {
            "profile_sha256": _sha256(self.profile_sha256, "profile_sha256"),
            "frame_width": _positive_int(self.frame_width, "frame_width"),
            "frame_height": _positive_int(self.frame_height, "frame_height"),
            "padding_px": _nonnegative_int(self.padding_px, "padding_px"),
            "calibration_provenance": _enum_value(
                self.calibration_provenance,
                CalibrationProvenance,
                "calibration_provenance",
            ),
            "day_verified": _boolean(self.day_verified, "day_verified"),
            "ir_verified": _boolean(self.ir_verified, "ir_verified"),
            "cameras": _frozen_cameras(self.cameras),
        }
        for field, value in normalized.items():
            object.__setattr__(self, field, value)

    @classmethod
    def from_json(cls, value: object) -> "RoiProfile":
        raw = strict_object(
            value,
            {
                "schema",
                "status",
                "test_sheet_sha256",
                "profile_sha256",
                "frame_width",
                "frame_height",
                "padding_px",
                "calibration_provenance",
                "day_verified",
                "ir_verified",
                "cameras",
            },
        )
        return cls(**raw)  # type: ignore[arg-type]

    def to_json(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "status": self.status,
            "test_sheet_sha256": self.test_sheet_sha256,
            "profile_sha256": self.profile_sha256,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "padding_px": self.padding_px,
            "calibration_provenance": self.calibration_provenance.value,
            "day_verified": self.day_verified,
            "ir_verified": self.ir_verified,
            "cameras": {
                camera: {name: rect.to_json() for name, rect in rects.items()}
                for camera, rects in self.cameras.items()
            },
            **self._write_counts(),
        }

    def _write_counts(self) -> dict[str, int]:
        return {field: getattr(self, field) for field in WRITE_COUNT_FIELDS}


@dataclass(frozen=True, slots=True)
class FrameRequest:
    request_id: str
    source_ref: str
    source_sha256: str
    anonymous_camera_digest: str
    camera_night: str
    enclosure_digest: str
    roi_name: str
    timestamp_ms: int
    time_band: str
    location_stratum: str
    role: Role
    roi_profile_sha256: str

    def __post_init__(self) -> None:
        normalized = {
            "request_id": _nonempty_string(self.request_id, "request_id"),
            "source_ref": _nonempty_string(self.source_ref, "source_ref"),
            "source_sha256": _sha256(self.source_sha256, "source_sha256"),
            "anonymous_camera_digest": _nonempty_string(
                self.anonymous_camera_digest, "anonymous_camera_digest"
            ),
            "camera_night": _nonempty_string(self.camera_night, "camera_night"),
            "enclosure_digest": _nonempty_string(
                self.enclosure_digest, "enclosure_digest"
            ),
            "roi_name": _nonempty_string(self.roi_name, "roi_name"),
            "timestamp_ms": _nonnegative_int(self.timestamp_ms, "timestamp_ms"),
            "time_band": _nonempty_string(self.time_band, "time_band"),
            "location_stratum": _nonempty_string(
                self.location_stratum, "location_stratum"
            ),
            "role": _role(self.role),
            "roi_profile_sha256": _sha256(
                self.roi_profile_sha256, "roi_profile_sha256"
            ),
        }
        for field, value in normalized.items():
            object.__setattr__(self, field, value)

    @classmethod
    def from_json(cls, value: object) -> "FrameRequest":
        fields = {
            "request_id",
            "source_ref",
            "source_sha256",
            "anonymous_camera_digest",
            "camera_night",
            "enclosure_digest",
            "roi_name",
            "timestamp_ms",
            "time_band",
            "location_stratum",
            "role",
            "roi_profile_sha256",
        }
        raw = strict_object(value, fields)
        return cls(**raw)  # type: ignore[arg-type]

    def to_json(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "source_ref": self.source_ref,
            "source_sha256": self.source_sha256,
            "anonymous_camera_digest": self.anonymous_camera_digest,
            "camera_night": self.camera_night,
            "enclosure_digest": self.enclosure_digest,
            "roi_name": self.roi_name,
            "timestamp_ms": self.timestamp_ms,
            "time_band": self.time_band,
            "location_stratum": self.location_stratum,
            "role": self.role.value,
            "roi_profile_sha256": self.roi_profile_sha256,
        }


@dataclass(frozen=True, slots=True)
class ReviewItem:
    anonymous_sequence: str
    image_name: str
    image_sha256: str
    width: int
    height: int

    def __post_init__(self) -> None:
        sequence = _anonymous_sequence(self.anonymous_sequence)
        image_name = _nonempty_string(self.image_name, "image_name")
        if image_name != f"{sequence}.jpg":
            raise ValueError("image_name must exactly match <anonymous_sequence>.jpg")
        normalized = {
            "anonymous_sequence": sequence,
            "image_name": image_name,
            "image_sha256": _sha256(self.image_sha256, "image_sha256"),
            "width": _positive_int(self.width, "width"),
            "height": _positive_int(self.height, "height"),
        }
        for field, value in normalized.items():
            object.__setattr__(self, field, value)

    @classmethod
    def from_json(cls, value: object) -> "ReviewItem":
        raw = strict_object(
            value,
            {"anonymous_sequence", "image_name", "image_sha256", "width", "height"},
        )
        return cls(**raw)  # type: ignore[arg-type]

    def to_json(self) -> dict[str, object]:
        return {
            "anonymous_sequence": self.anonymous_sequence,
            "image_name": self.image_name,
            "image_sha256": self.image_sha256,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class HumanBox:
    anonymous_sequence: str
    box: Box
    label: str = "gecko"
    source: str = "manual"

    def __post_init__(self) -> None:
        sequence = _anonymous_sequence(self.anonymous_sequence)
        label = _nonempty_string(self.label, "label")
        source = _nonempty_string(self.source, "source")
        if label != "gecko" or source != "manual":
            raise ValueError("HumanBox requires a manual gecko rectangle")
        object.__setattr__(self, "anonymous_sequence", sequence)
        object.__setattr__(self, "box", _box(self.box))
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "source", source)

    @classmethod
    def from_json(cls, value: object) -> "HumanBox":
        raw = strict_object(value, {"anonymous_sequence", "box", "label", "source"})
        return cls(**raw)  # type: ignore[arg-type]

    def to_json(self) -> dict[str, object]:
        return {
            "anonymous_sequence": self.anonymous_sequence,
            "label": self.label,
            "source": self.source,
            "box": self.box.to_json(),
        }


@dataclass(frozen=True, slots=True)
class TeacherFreeze:
    schema: str
    status: str
    test_sheet_sha256: str
    freeze_cutoff_utc: str
    selected_checkpoint_sha256: str
    imgsz: int
    raw_confidence: float
    nms_iou: float
    evaluation_threshold: float
    temporal_fps: int
    fixed_test_passed: bool
    runs: tuple[Mapping[str, object], ...]
    db_write_count: int = 0
    r2_write_count: int = 0
    service_write_count: int = 0
    git_write_count: int = 0

    def __post_init__(self) -> None:
        _validate_root_instance(self)
        cutoff = _nonempty_string(self.freeze_cutoff_utc, "freeze_cutoff_utc")
        if not cutoff.endswith("Z"):
            raise ValueError("freeze_cutoff_utc must be canonical UTC ending in Z")
        normalized = {
            "freeze_cutoff_utc": cutoff,
            "selected_checkpoint_sha256": _sha256(
                self.selected_checkpoint_sha256, "selected_checkpoint_sha256"
            ),
            "imgsz": _positive_int(self.imgsz, "imgsz"),
            "raw_confidence": _number(
                self.raw_confidence, "raw_confidence", minimum=0.0
            ),
            "nms_iou": _number(self.nms_iou, "nms_iou", minimum=0.0),
            "evaluation_threshold": _number(
                self.evaluation_threshold, "evaluation_threshold", minimum=0.0
            ),
            "temporal_fps": _positive_int(self.temporal_fps, "temporal_fps"),
            "fixed_test_passed": _boolean(
                self.fixed_test_passed, "fixed_test_passed"
            ),
            "runs": _frozen_runs(self.runs),
        }
        for field, value in normalized.items():
            object.__setattr__(self, field, value)

    @classmethod
    def from_json(cls, value: object) -> "TeacherFreeze":
        raw = strict_object(
            value,
            {
                "schema",
                "status",
                "test_sheet_sha256",
                "freeze_cutoff_utc",
                "selected_checkpoint_sha256",
                "imgsz",
                "raw_confidence",
                "nms_iou",
                "evaluation_threshold",
                "temporal_fps",
                "fixed_test_passed",
                "runs",
            },
        )
        return cls(**raw)  # type: ignore[arg-type]

    def to_json(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "status": self.status,
            "test_sheet_sha256": self.test_sheet_sha256,
            "freeze_cutoff_utc": self.freeze_cutoff_utc,
            "selected_checkpoint_sha256": self.selected_checkpoint_sha256,
            "imgsz": self.imgsz,
            "raw_confidence": self.raw_confidence,
            "nms_iou": self.nms_iou,
            "evaluation_threshold": self.evaluation_threshold,
            "temporal_fps": self.temporal_fps,
            "fixed_test_passed": self.fixed_test_passed,
            "runs": [dict(run) for run in self.runs],
            **{field: getattr(self, field) for field in WRITE_COUNT_FIELDS},
        }


@dataclass(frozen=True, slots=True)
class PredictionRow:
    source_ref: str
    source_sha256: str
    camera_night: str
    role: Role
    timestamp_ms: int
    confidence: float
    box: Box
    selection_reason: str

    def __post_init__(self) -> None:
        confidence = _number(self.confidence, "confidence", minimum=0.0)
        if confidence > 1.0:
            raise ValueError("confidence must be <= 1")
        normalized = {
            "source_ref": _nonempty_string(self.source_ref, "source_ref"),
            "source_sha256": _sha256(self.source_sha256, "source_sha256"),
            "camera_night": _nonempty_string(self.camera_night, "camera_night"),
            "role": _role(self.role),
            "timestamp_ms": _nonnegative_int(self.timestamp_ms, "timestamp_ms"),
            "confidence": confidence,
            "box": _box(self.box),
            "selection_reason": _nonempty_string(
                self.selection_reason, "selection_reason"
            ),
        }
        for field, value in normalized.items():
            object.__setattr__(self, field, value)

    @classmethod
    def from_json(cls, value: object) -> "PredictionRow":
        raw = strict_object(
            value,
            {
                "source_ref",
                "source_sha256",
                "camera_night",
                "role",
                "timestamp_ms",
                "confidence",
                "box",
                "selection_reason",
            },
        )
        return cls(**raw)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    sequence: str
    image_path: str
    image_sha256: str
    width: int
    height: int
    boxes: tuple[Box, ...]
    camera_night: str
    role: Role
    provenance: str

    def __post_init__(self) -> None:
        image_path = _nonempty_string(self.image_path, "image_path")
        if (
            image_path.startswith("/")
            or ".." in image_path.split("/")
            or "\\" in image_path
        ):
            raise ValueError("image_path must be a safe relative POSIX path")
        normalized = {
            "sequence": _nonempty_string(self.sequence, "sequence"),
            "image_path": image_path,
            "image_sha256": _sha256(self.image_sha256, "image_sha256"),
            "width": _positive_int(self.width, "width"),
            "height": _positive_int(self.height, "height"),
            "boxes": _boxes(self.boxes),
            "camera_night": _nonempty_string(self.camera_night, "camera_night"),
            "role": _role(self.role),
            "provenance": _nonempty_string(self.provenance, "provenance"),
        }
        for field, value in normalized.items():
            object.__setattr__(self, field, value)

    @classmethod
    def from_json(cls, value: object) -> "DatasetRecord":
        raw = strict_object(
            value,
            {
                "sequence",
                "image_path",
                "image_sha256",
                "width",
                "height",
                "boxes",
                "camera_night",
                "role",
                "provenance",
            },
        )
        return cls(**raw)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ProtectedLedger:
    schema: str
    status: str
    test_sheet_sha256: str
    role: ProtectedRole
    source_sha256: tuple[str, ...]
    db_write_count: int = 0
    r2_write_count: int = 0
    service_write_count: int = 0
    git_write_count: int = 0

    def __post_init__(self) -> None:
        _validate_root_instance(self)
        if not isinstance(self.source_sha256, (list, tuple)) or not self.source_sha256:
            raise ValueError("source_sha256 must be a non-empty sequence")
        object.__setattr__(
            self,
            "role",
            _enum_value(self.role, ProtectedRole, "protected role"),
        )
        object.__setattr__(
            self,
            "source_sha256",
            tuple(_sha256(value, "source_sha256") for value in self.source_sha256),
        )

    @classmethod
    def from_json(cls, value: object) -> "ProtectedLedger":
        raw = strict_object(
            value,
            {"schema", "status", "test_sheet_sha256", "role", "source_sha256"},
        )
        return cls(**raw)  # type: ignore[arg-type]

    def to_json(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "status": self.status,
            "test_sheet_sha256": self.test_sheet_sha256,
            "role": self.role.value,
            "source_sha256": list(self.source_sha256),
            **{field: getattr(self, field) for field in WRITE_COUNT_FIELDS},
        }
