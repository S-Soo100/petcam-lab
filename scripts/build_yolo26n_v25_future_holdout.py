"""YOLO26n v2.5의 독립 Future Holdout 후보를 준비한다.

이 모듈의 readiness 단계는 Supabase metadata SELECT만 허용한다. 영상 GET과
모든 운영 쓰기는 후속 reserve 단계가 별도 계약을 통과한 뒤에만 가능하다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence


_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        raise ValueError("timestamp must be an exact UTC ISO-8601 value")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError("timestamp must be UTC")
    return parsed


def _strict_float(value: object, expected: float, name: str) -> None:
    if type(value) is not float or value != expected:
        raise ValueError(f"{name} must remain frozen at {expected}")


@dataclass(frozen=True)
class FreezeContract:
    freeze_sha256: str
    selected_checkpoint_sha256: str
    cutoff_utc: str
    threshold: float
    confidence: float
    imgsz: int
    nms_iou: float
    max_det: int

    def validate(self) -> "FreezeContract":
        if _LOWER_SHA256.fullmatch(self.freeze_sha256) is None:
            raise ValueError("freeze SHA must be lowercase SHA-256")
        if _LOWER_SHA256.fullmatch(self.selected_checkpoint_sha256) is None:
            raise ValueError("checkpoint SHA must be lowercase SHA-256")
        _parse_utc(self.cutoff_utc)
        _strict_float(self.threshold, 0.20, "threshold")
        _strict_float(self.confidence, 0.001, "confidence")
        if type(self.imgsz) is not int or self.imgsz != 960:
            raise ValueError("imgsz must remain frozen at 960")
        _strict_float(self.nms_iou, 0.70, "nms_iou")
        if type(self.max_det) is not int or self.max_det != 50:
            raise ValueError("max_det must remain frozen at 50")
        return self


@dataclass(frozen=True)
class FutureSource:
    source_ref: str
    camera_id: str
    started_at: str
    camera_night: str
    r2_key: str

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> "FutureSource":
        source_ref = row.get("id")
        camera_id = row.get("camera_id")
        started_at = row.get("started_at")
        r2_key = row.get("r2_key")
        if not all(isinstance(value, str) and value for value in (source_ref, camera_id, started_at, r2_key)):
            raise ValueError("future source identity is incomplete")
        started = _parse_utc(started_at)
        return cls(
            source_ref=source_ref,
            camera_id=camera_id,
            started_at=started_at,
            camera_night=f"{camera_id}:{started.date().isoformat()}",
            r2_key=r2_key,
        )


def _eligible_sources(
    *, freeze: FreezeContract, rows: Sequence[Mapping[str, object]]
) -> tuple[FutureSource, ...]:
    freeze.validate()
    cutoff = _parse_utc(freeze.cutoff_utc)
    selected: list[FutureSource] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("future metadata row is invalid")
        if row.get("clip_purpose") != "production":
            continue
        source = FutureSource.from_row(row)
        if _parse_utc(source.started_at) <= cutoff:
            continue
        if source.source_ref in seen:
            raise ValueError("future source identity is duplicated")
        seen.add(source.source_ref)
        selected.append(source)
    return tuple(sorted(selected, key=lambda source: (source.started_at, source.source_ref)))


def build_readiness(
    *, freeze: FreezeContract, rows: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    eligible = _eligible_sources(freeze=freeze, rows=rows)
    cameras = {source.camera_id for source in eligible}
    nights = {source.camera_night for source in eligible}
    return {
        "schema": "yolo26n-v25-future-readiness-v1",
        "status": "V25_FUTURE_MEDIA_READY" if eligible else "WAITING_FOR_FUTURE_MEDIA",
        "freeze_sha256": freeze.freeze_sha256,
        "selected_checkpoint_sha256": freeze.selected_checkpoint_sha256,
        "cutoff_utc": freeze.cutoff_utc,
        "eligible_source_count": len(eligible),
        "camera_count": len(cameras),
        "camera_night_count": len(nights),
        "frame_capacity": len(eligible) * 2,
        "db_write_count": 0,
        "r2_get_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "production_model_write_count": 0,
    }


def collect_metadata(
    client: object,
    *,
    freeze: FreezeContract,
    snapshot_through: str,
    page_size: int = 1000,
) -> list[Mapping[str, object]]:
    """한 snapshot의 metadata만 읽고, 페이지 drift면 영상 GET 전에 중단한다."""

    freeze.validate()
    cutoff = _parse_utc(freeze.cutoff_utc)
    upper = _parse_utc(snapshot_through)
    if upper <= cutoff:
        raise ValueError("snapshot cutoff must be after the selection freeze")
    if type(page_size) is not int or page_size < 1:
        raise ValueError("page_size must be a positive integer")

    rows: list[Mapping[str, object]] = []
    seen: set[str] = set()
    previous: tuple[datetime, str] | None = None
    expected_total: int | None = None
    start = 0
    while expected_total is None or start < expected_total:
        response = (
            client.table("motion_clips")
            .select("id,camera_id,started_at,r2_key,clip_purpose", count="exact")
            .gt("started_at", freeze.cutoff_utc)
            .lte("started_at", snapshot_through)
            .eq("clip_purpose", "production")
            .not_.is_("r2_key", "null")
            .order("started_at")
            .order("id")
            .range(start, start + page_size - 1)
            .execute()
        )
        count = getattr(response, "count", None)
        if type(count) is not int or count < 0:
            raise ValueError("pagination exact count is missing")
        if expected_total is None:
            expected_total = count
        elif count != expected_total:
            raise ValueError("pagination snapshot count changed")

        page = getattr(response, "data", None)
        if not isinstance(page, list):
            raise ValueError("pagination page is invalid")
        expected_page = min(page_size, max(0, expected_total - start))
        if len(page) != expected_page:
            raise ValueError("pagination snapshot page count mismatch")
        for raw in page:
            if not isinstance(raw, Mapping):
                raise ValueError("pagination row is invalid")
            source = FutureSource.from_row(raw)
            started = _parse_utc(source.started_at)
            key = (started, source.source_ref)
            if (
                source.source_ref in seen
                or started <= cutoff
                or started > upper
                or (previous is not None and key <= previous)
            ):
                raise ValueError("pagination snapshot identity drift")
            if raw.get("clip_purpose") != "production":
                raise ValueError("pagination returned a non-production source")
            seen.add(source.source_ref)
            previous = key
            rows.append(raw)
        start += len(page)
        if expected_total == 0:
            break

    if expected_total is None or len(rows) != expected_total:
        raise ValueError("pagination snapshot count mismatch")
    return rows
