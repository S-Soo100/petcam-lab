"""YOLO26n v2.5의 독립 Future Holdout 후보를 준비한다.

이 모듈의 readiness 단계는 Supabase metadata SELECT만 허용한다. 영상 GET과
모든 운영 쓰기는 후속 reserve 단계가 별도 계약을 통과한 뒤에만 가능하다.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, UnidentifiedImageError


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


@dataclass(frozen=True)
class FutureFrame:
    source_ref: str
    camera_id: str
    camera_night: str
    frame_index: int
    image_sha256: str
    dhash64: int
    jpeg_bytes: bytes

    def validate(self) -> "FutureFrame":
        if not all(
            isinstance(value, str) and value
            for value in (self.source_ref, self.camera_id, self.camera_night)
        ):
            raise ValueError("future frame lineage is incomplete")
        if type(self.frame_index) is not int or self.frame_index < 0:
            raise ValueError("future frame index is invalid")
        if _LOWER_SHA256.fullmatch(self.image_sha256) is None:
            raise ValueError("future frame image SHA is invalid")
        if type(self.dhash64) is not int or not 0 <= self.dhash64 < 2**64:
            raise ValueError("future frame dHash is invalid")
        if not isinstance(self.jpeg_bytes, bytes) or not self.jpeg_bytes:
            raise ValueError("future frame JPEG is missing")
        if hashlib.sha256(self.jpeg_bytes).hexdigest() != self.image_sha256:
            raise ValueError("future frame JPEG SHA does not match pinned bytes")
        return self


@dataclass(frozen=True)
class FinalHoldoutFrame:
    sequence: str
    presence: str
    frame: FutureFrame


def build_exposure_fingerprints(
    records: Sequence[Mapping[str, object]],
) -> dict[str, tuple[object, ...]]:
    image_shas: set[str] = set()
    dhashes: set[int] = set()
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("historical fingerprint record is invalid")
        image_sha = record.get("image_sha256")
        dhash = record.get("dhash64")
        if not isinstance(image_sha, str) or _LOWER_SHA256.fullmatch(image_sha) is None:
            raise ValueError("historical fingerprint image SHA is invalid")
        if not isinstance(dhash, str) or re.fullmatch(r"[0-9a-f]{16}", dhash) is None:
            raise ValueError("historical fingerprint dHash is invalid")
        image_shas.add(image_sha)
        dhashes.add(int(dhash, 16))
    return {
        "image_sha256": tuple(sorted(image_shas)),
        "dhash64": tuple(sorted(dhashes)),
    }


def hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _seed_rank(frame: FutureFrame, seed: str) -> str:
    identity = (
        f"{seed}\0{frame.camera_night}\0{frame.source_ref}\0"
        f"{frame.frame_index}\0{frame.image_sha256}"
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def select_reserve(
    frames: Sequence[FutureFrame],
    *,
    exposed_sha: set[str] | None = None,
    exposed_dhash: set[int] | None = None,
    limit: int = 400,
    seed: str = "yolo26n-v25-future-holdout-v1",
    source_cap: int = 2,
    night_cap: int = 24,
) -> tuple[FutureFrame, ...]:
    if any(type(value) is not int or value < 1 for value in (limit, source_cap, night_cap)):
        raise ValueError("reserve caps must be positive integers")
    if not isinstance(seed, str) or not seed:
        raise ValueError("reserve seed is missing")
    exposed_sha = exposed_sha or set()
    exposed_dhash = exposed_dhash or set()
    if any(_LOWER_SHA256.fullmatch(value) is None for value in exposed_sha):
        raise ValueError("exposed image SHA is invalid")
    if any(type(value) is not int or not 0 <= value < 2**64 for value in exposed_dhash):
        raise ValueError("exposed dHash is invalid")

    validated = sorted(
        (frame.validate() for frame in frames),
        key=lambda frame: (
            frame.image_sha256,
            frame.camera_night,
            frame.source_ref,
            frame.frame_index,
        ),
    )
    ranked: list[FutureFrame] = []
    seen_input_sha: set[str] = set()
    for frame in validated:
        if frame.image_sha256 in seen_input_sha:
            continue
        seen_input_sha.add(frame.image_sha256)
        if frame.image_sha256 in exposed_sha:
            continue
        if any(hamming(frame.dhash64, old) <= 2 for old in exposed_dhash):
            continue
        ranked.append(frame)
    ranked.sort(key=lambda frame: (_seed_rank(frame, seed), frame.image_sha256))

    chosen: list[FutureFrame] = []
    source_counts: Counter[str] = Counter()
    night_counts: Counter[str] = Counter()
    source_dhashes: dict[str, list[int]] = {}
    for frame in ranked:
        if source_counts[frame.source_ref] >= source_cap:
            continue
        if night_counts[frame.camera_night] >= night_cap:
            continue
        if any(
            hamming(frame.dhash64, prior) <= 2
            for prior in source_dhashes.get(frame.source_ref, [])
        ):
            continue
        chosen.append(frame)
        source_counts[frame.source_ref] += 1
        night_counts[frame.camera_night] += 1
        source_dhashes.setdefault(frame.source_ref, []).append(frame.dhash64)
        if len(chosen) == limit:
            break
    return tuple(chosen)


def _normalized_jpeg(payload: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            if image.format != "JPEG":
                raise ValueError("future frame is not JPEG")
            output = io.BytesIO()
            image.convert("RGB").save(output, format="JPEG", quality=95, optimize=False)
            return output.getvalue()
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("future frame JPEG decode failed") from error


def _write_new(path: Path, payload: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
    path.chmod(mode)


def publish_presence_bundle(
    frames: Sequence[FutureFrame],
    output_dir: Path,
    *,
    model_version: str,
) -> dict[str, object]:
    """익명 presence ZIP과 private provenance를 no-overwrite로 발행한다."""

    if not frames:
        raise ValueError("presence queue cannot be empty")
    if not isinstance(model_version, str) or not model_version:
        raise ValueError("model version is missing")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "presence-screen.csv"
    zip_path = output_dir / "cvat-presence.zip"
    manifest_path = output_dir / "reserve-manifest.private.json"
    if any(path.exists() for path in (csv_path, zip_path, manifest_path)):
        raise FileExistsError("presence bundle output exists")

    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer, lineterminator="\n")
    writer.writerow(["sequence", "presence"])
    public: list[tuple[str, bytes]] = []
    private_records: list[dict[str, object]] = []
    for index, frame in enumerate(frames, start=1):
        frame.validate()
        sequence = f"P{index:04d}"
        filename = f"{sequence}.jpg"
        jpeg = _normalized_jpeg(frame.jpeg_bytes)
        writer.writerow([sequence, ""])
        public.append((filename, jpeg))
        private_records.append(
            {
                "sequence": sequence,
                "filename": filename,
                "source_ref": frame.source_ref,
                "camera_id": frame.camera_id,
                "camera_night": frame.camera_night,
                "frame_index": frame.frame_index,
                "source_image_sha256": frame.image_sha256,
                "public_image_sha256": hashlib.sha256(jpeg).hexdigest(),
                "dhash64": f"{frame.dhash64:016x}",
            }
        )
    csv_bytes = csv_buffer.getvalue().encode("utf-8")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for filename, jpeg in public:
            archive.writestr(filename, jpeg)
        archive.writestr("presence-screen.csv", csv_bytes)
    manifest = {
        "schema": "yolo26n-v25-future-reserve-v1",
        "status": "V25_PRESENCE_QUEUE_READY",
        "model_version": model_version,
        "record_count": len(private_records),
        "records": private_records,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "production_model_write_count": 0,
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True) + "\n").encode("utf-8")

    created: list[Path] = []
    try:
        _write_new(csv_path, csv_bytes, 0o600)
        created.append(csv_path)
        _write_new(zip_path, zip_buffer.getvalue(), 0o600)
        created.append(zip_path)
        _write_new(manifest_path, manifest_bytes, 0o600)
        created.append(manifest_path)
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return {
        "status": "V25_PRESENCE_QUEUE_READY",
        "public_frame_count": len(public),
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


def materialize_reserve(
    frames: Sequence[FutureFrame],
    output_dir: Path,
    *,
    model_version: str,
) -> dict[str, object]:
    """계획 문서의 reserve materialization 진입점."""

    return publish_presence_bundle(frames, output_dir, model_version=model_version)


def _presence_rows(payload: bytes, expected_count: int) -> tuple[str, ...]:
    if not isinstance(payload, bytes):
        raise ValueError("presence sheet must be raw bytes")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("presence sheet must be UTF-8") from error
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != ["sequence", "presence"]:
        raise ValueError("presence sheet header is invalid")
    rows = list(reader)
    if len(rows) != expected_count:
        raise ValueError("presence sequence count mismatch")
    values: list[str] = []
    for index, row in enumerate(rows, start=1):
        if set(row) != {"sequence", "presence"}:
            raise ValueError("presence sheet row is invalid")
        if row["sequence"] != f"P{index:04d}":
            raise ValueError("presence sequence order mismatch")
        value = row["presence"]
        if value not in {"positive", "negative", "ambiguous"}:
            raise ValueError("presence value is invalid")
        values.append(value)
    return tuple(values)


def build_final_holdout(
    reserve: Sequence[FutureFrame],
    presence_csv: bytes,
    *,
    positive_count: int = 100,
    negative_count: int = 100,
    source_cap: int = 2,
    night_cap: int = 24,
    minimum_cameras: int = 3,
    minimum_nights: int = 6,
) -> tuple[FinalHoldoutFrame, ...]:
    """사람 presence 동결 뒤 prediction 없이 균형 holdout을 확정한다."""

    strict_counts = (
        positive_count,
        negative_count,
        source_cap,
        night_cap,
        minimum_cameras,
        minimum_nights,
    )
    if any(type(value) is not int or value < 1 for value in strict_counts):
        raise ValueError("final holdout counts must be positive integers")
    validated = tuple(frame.validate() for frame in reserve)
    values = _presence_rows(presence_csv, len(validated))
    indexed = list(zip(validated, values, strict=True))
    positives = [(frame, value) for frame, value in indexed if value == "positive"]
    negatives = [(frame, value) for frame, value in indexed if value == "negative"]
    if len(positives) < positive_count or len(negatives) < negative_count:
        raise ValueError("balanced holdout shortage")

    selected_ids = {
        id(frame)
        for frame, _value in positives[:positive_count] + negatives[:negative_count]
    }
    selected = [(frame, value) for frame, value in indexed if id(frame) in selected_ids]
    if len(selected) != positive_count + negative_count:
        raise ValueError("balanced holdout selection is not exact")

    source_counts = Counter(frame.source_ref for frame, _value in selected)
    night_counts = Counter(frame.camera_night for frame, _value in selected)
    cameras = {frame.camera_id for frame, _value in selected}
    if source_counts and max(source_counts.values()) > source_cap:
        raise ValueError("final holdout source cap exceeded")
    if night_counts and max(night_counts.values()) > night_cap:
        raise ValueError("final holdout night cap exceeded")
    if len(cameras) < minimum_cameras or len(night_counts) < minimum_nights:
        raise ValueError("final holdout diversity shortage")
    image_shas = [frame.image_sha256 for frame, _value in selected]
    if len(set(image_shas)) != len(image_shas):
        raise ValueError("final holdout contains duplicate images")

    return tuple(
        FinalHoldoutFrame(
            sequence=f"H{index:04d}", presence=value, frame=frame
        )
        for index, (frame, value) in enumerate(selected, start=1)
    )


def publish_final_holdout(
    final: Sequence[FinalHoldoutFrame], output_dir: Path
) -> dict[str, object]:
    if len(final) != 200:
        raise ValueError("final holdout must contain exactly 200 frames")
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "cvat-upload.zip"
    review_path = output_dir / "review-index.csv"
    manifest_path = output_dir / "future-holdout-manifest.private.json"
    if any(path.exists() for path in (zip_path, review_path, manifest_path)):
        raise FileExistsError("final holdout output exists")

    review_buffer = io.StringIO(newline="")
    review_writer = csv.writer(review_buffer, lineterminator="\n")
    review_writer.writerow(["sequence", "filename", "instruction"])
    zip_buffer = io.BytesIO()
    private_records: list[dict[str, object]] = []
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for index, row in enumerate(final, start=1):
            expected = f"H{index:04d}"
            if row.sequence != expected or row.presence not in {"positive", "negative"}:
                raise ValueError("final holdout row order is invalid")
            row.frame.validate()
            filename = f"{expected}.jpg"
            jpeg = _normalized_jpeg(row.frame.jpeg_bytes)
            archive.writestr(filename, jpeg)
            review_writer.writerow(
                [expected, filename, "게코가 보이면 각 개체의 보이는 몸 영역에 bbox"]
            )
            private_records.append(
                {
                    "sequence": expected,
                    "filename": filename,
                    "presence": row.presence,
                    "source_ref": row.frame.source_ref,
                    "camera_id": row.frame.camera_id,
                    "camera_night": row.frame.camera_night,
                    "frame_index": row.frame.frame_index,
                    "source_image_sha256": row.frame.image_sha256,
                    "public_image_sha256": hashlib.sha256(jpeg).hexdigest(),
                }
            )
    manifest = {
        "schema": "yolo26n-v25-future-holdout-v1",
        "status": "V25_FUTURE_HOLDOUT_READY",
        "record_count": 200,
        "presence_counts": {"positive": 100, "negative": 100},
        "records": private_records,
        "prediction_exposed": False,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
        "production_model_write_count": 0,
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    review_bytes = review_buffer.getvalue().encode()
    created: list[Path] = []
    try:
        _write_new(zip_path, zip_buffer.getvalue(), 0o600)
        created.append(zip_path)
        _write_new(review_path, review_bytes, 0o600)
        created.append(review_path)
        _write_new(manifest_path, manifest_bytes, 0o600)
        created.append(manifest_path)
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return {
        "status": "V25_FUTURE_HOLDOUT_READY",
        "frame_count": 200,
        "db_write_count": 0,
        "r2_write_count": 0,
        "service_write_count": 0,
    }


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
