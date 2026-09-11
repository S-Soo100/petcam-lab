"""Task 5 — prediction-independent, train-only ROI 파일럿 큐.

흐름: `select_pilot_requests`(메타데이터만, 픽셀 0) → `extract_review_items`(train 영상 decode → ROI crop → 익명 JPEG).

설계 요점
- 한 timestamp 의 세 ROI 판단을 한 source group 으로 묶는다(설계 §… full-frame representation 판정용).
  그래서 600 = 200 timestamp × 3 ROI, 카메라당 66–67 timestamp, 사육장(카메라×ROI) 66–67 장.
- timestamp 순위는 sha256(seed | source_sha | offset_ms). 소스(30분 슬롯)당 최대 1 timestamp → 같은 소스 5분 간격 규칙 자동 충족.
- 시간대 4 층(20–22 / 22–02 / 02–05 / 05–08 KST)을 카메라별로 ±1 균형. `dish_visible` 태그가 있으면 사육장별 10% 하한을
  먼저 채운다(없으면 하한 계산 제외). 부족하면 다른 사육장으로 조용히 채우지 않고 `SelectionShortage`.
- location_stratum 은 크롭 위치(가운데 ROI=central, 좌우 ROI=edge) — 프레임 가장자리 crop 오류 측정용. 예측 정보 0.
- 추출: cv2.VideoCapture 는 `finally` 로 release. exact JPEG SHA 전역 중복 제거 + 같은 (source, ROI) 5분 이내 dHash≤2 근사 중복 제거.
  IR/컬러는 채널 spread 평균 ≤4 → ir (sampling stratum 일 뿐 GT 아님).
- 공개 큐 manifest 에는 source ref·timestamp 가 없다. 연결 정보는 0600 lineage 에만.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np

from scripts.yolo26n_v27_c500g.contracts import WRITE_COUNT_FIELDS, FrameRequest, ReviewItem, Role, RoiProfile
from scripts.yolo26n_v27_c500g.private_io import canonical_json_bytes, write_private_json_new, write_private_zip_new
from scripts.yolo26n_v27_c500g.roi import ROI_NAMES, crop_bounds, crop_frame

KST = ZoneInfo("Asia/Seoul")
TIME_BANDS: tuple[str, ...] = ("20-22", "22-02", "02-05", "05-08")
CANDIDATE_MARGIN_SEC = 30
CANDIDATE_STEP_SEC = 60
MIN_SAME_SOURCE_GAP_MS = 5 * 60 * 1000
DISH_FLOOR_FRACTION = 0.10
IR_CHANNEL_SPREAD_MAX = 4.0
DHASH_MAX_DISTANCE = 2
REVIEW_QUEUE_SCHEMA = "yolo26n-v27-c500g-review-queue-v1"
LINEAGE_SCHEMA = "yolo26n-v27-c500g-private-lineage-v1"
EXTRACT_REPORT_SCHEMA = "yolo26n-v27-c500g-extract-report-v1"
PILOT_SUMMARY_SCHEMA = "yolo26n-v27-c500g-pilot-selection-summary-v1"
_ZERO_WRITES = {field: 0 for field in WRITE_COUNT_FIELDS}


class SelectionShortage(ValueError):
    """층 quota 를 train pool 에서 채울 수 없음 — 다른 사육장/역할로 채우지 않고 멈춘다."""


class DecodeError(RuntimeError):
    """영상 열기/seek/decode 실패."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    source_ref: str
    source_sha256: str
    camera_digest: str
    camera_night: str
    timestamp_ms: int
    band: str
    rank: str


def _rank(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def time_band_for(moment: datetime) -> str | None:
    """KST 시각 → 시간대 층. 야간 창(20:00–08:00) 밖이면 None."""
    hour = moment.astimezone(KST).hour
    if 20 <= hour < 22:
        return "20-22"
    if hour >= 22 or hour < 2:
        return "22-02"
    if 2 <= hour < 5:
        return "02-05"
    if 5 <= hour < 8:
        return "05-08"
    return None


def enclosure_digest(camera_digest: str, roi_name: str) -> str:
    return hashlib.sha256(f"enclosure:{camera_digest}:{roi_name}".encode("utf-8")).hexdigest()


def location_stratum(roi_name: str) -> str:
    return "central" if roi_name == "middle" else "edge"


def _train_candidates(inventory: Mapping[str, object], roles: Mapping[str, object], *, seed: str,
                      exclude_sources: frozenset[str]) -> dict[str, list[_Candidate]]:
    rows = roles.get("rows")
    if not isinstance(rows, list):
        raise ValueError("roles manifest has no rows")
    role_rows = {str(row["source_ref"]): row for row in rows}
    per_camera: dict[str, list[_Candidate]] = defaultdict(list)
    for record in inventory.get("records", []):  # type: ignore[union-attr]
        ref = str(record["source_ref"])
        row = role_rows.get(ref)
        if row is None or Role(str(row["role"])) is not Role.V27_TRAIN or ref in exclude_sources:
            continue
        start = datetime.fromisoformat(str(record["scheduled_start_utc"]).replace("Z", "+00:00"))
        duration = float(record["duration_sec"])
        best: dict[str, _Candidate] = {}
        offset = CANDIDATE_MARGIN_SEC
        while offset <= duration - CANDIDATE_MARGIN_SEC:
            band = time_band_for(start + timedelta(seconds=offset))
            if band is not None:
                timestamp_ms = offset * 1000
                candidate = _Candidate(
                    ref, str(record["source_sha256"]), str(row["anonymous_camera_digest"]), str(row["camera_night"]),
                    timestamp_ms, band, _rank(seed, str(record["source_sha256"]), str(timestamp_ms)),
                )
                if band not in best or candidate.rank < best[band].rank:
                    best[band] = candidate
            offset += CANDIDATE_STEP_SEC
        per_camera[str(row["anonymous_camera_digest"])].extend(best.values())
    return per_camera


def _split_even(total: int, keys: Sequence[str], priority: Sequence[str]) -> dict[str, int]:
    base, extra = divmod(total, len(keys))
    counts = {key: base for key in keys}
    for key in priority[:extra]:
        counts[key] += 1
    return counts


def select_pilot_requests(
    inventory: Mapping[str, object],
    roles: Mapping[str, object],
    profile: RoiProfile,
    *,
    target: int = 600,
    seed: str,
    dish_tags: Mapping[str, Mapping[str, object]] | None = None,
    exclude_sources: Iterable[str] = (),
) -> list[FrameRequest]:
    """train role 에서만 `target` 개 ROI 요청(= target/3 timestamp × 3 ROI)을 seed-결정적으로 층화 선택."""
    if target <= 0 or target % 3:
        raise ValueError("target must be a positive multiple of 3 (three ROI per timestamp)")
    if not seed:
        raise ValueError("seed must be a non-empty string")
    excluded = frozenset(exclude_sources)
    per_camera = _train_candidates(inventory, roles, seed=seed, exclude_sources=excluded)
    cameras = sorted(profile.cameras)
    unknown = set(per_camera) - set(cameras)
    if unknown:
        raise ValueError("train sources belong to a camera without ROI profile")
    groups_total = target // 3
    camera_quota = _split_even(groups_total, cameras, sorted(cameras, key=lambda c: _rank(seed, "camera", c)))
    tags = dish_tags or {}

    selected: dict[str, list[_Candidate]] = {}
    for camera in cameras:
        candidates = sorted(per_camera.get(camera, []), key=lambda c: c.rank)
        quota = camera_quota[camera]
        band_quota = _split_even(quota, TIME_BANDS, sorted(TIME_BANDS, key=lambda b: _rank(seed, camera, b)))
        chosen: list[_Candidate] = []
        used_sources: set[str] = set()
        band_count: Counter[str] = Counter()

        def take(candidate: _Candidate) -> None:
            chosen.append(candidate)
            used_sources.add(candidate.source_ref)
            band_count[candidate.band] += 1

        # 1) dish_visible 하한: 태그가 있는 사육장만, 시간대 quota 안에서 먼저 채운다.
        if tags:
            floor = math.ceil(DISH_FLOOR_FRACTION * quota)
            for roi_name in ROI_NAMES:
                tagged = [c for c in candidates if tags.get(c.source_ref, {}).get(roi_name) is True]
                if not tagged:
                    continue
                have = sum(1 for c in chosen if tags.get(c.source_ref, {}).get(roi_name) is True)
                for candidate in tagged:
                    if have >= floor:
                        break
                    if candidate.source_ref in used_sources or band_count[candidate.band] >= band_quota[candidate.band]:
                        continue
                    take(candidate)
                    have += 1
                if have < floor:
                    raise SelectionShortage(
                        f"dish_visible floor unmet for camera {camera[:12]} roi {roi_name}: {have} < {floor}"
                    )
        # 2) 시간대 quota 채우기 (순위순, 소스당 1회).
        for candidate in candidates:
            if len(chosen) >= quota:
                break
            if candidate.source_ref in used_sources or band_count[candidate.band] >= band_quota[candidate.band]:
                continue
            take(candidate)
        # 3) 특정 시간대 pool 이 모자라면 같은 카메라 다른 시간대로만 보충(요약에서 불균형으로 드러남).
        for candidate in candidates:
            if len(chosen) >= quota:
                break
            if candidate.source_ref not in used_sources:
                take(candidate)
        if len(chosen) < quota:
            raise SelectionShortage(
                f"camera {camera[:12]} train pool yields {len(chosen)} timestamps but quota is {quota}; "
                "not filling from other enclosures or roles"
            )
        selected[camera] = chosen

    requests: list[FrameRequest] = []
    for camera in cameras:
        for candidate in sorted(selected[camera], key=lambda c: (TIME_BANDS.index(c.band), c.rank)):
            for roi_name in ROI_NAMES:
                requests.append(
                    FrameRequest(
                        request_id="req-" + _rank(seed, candidate.source_sha256, str(candidate.timestamp_ms), roi_name)[:16],
                        source_ref=candidate.source_ref,
                        source_sha256=candidate.source_sha256,
                        anonymous_camera_digest=camera,
                        camera_night=candidate.camera_night,
                        enclosure_digest=enclosure_digest(camera, roi_name),
                        roi_name=roi_name,
                        timestamp_ms=candidate.timestamp_ms,
                        time_band=candidate.band,
                        location_stratum=location_stratum(roi_name),
                        role=Role.V27_TRAIN,
                        roi_profile_sha256=profile.profile_sha256,
                    )
                )
    return requests


def summarize_selection(requests: Sequence[FrameRequest], *, dish_tags: Mapping[str, Mapping[str, object]] | None = None) -> dict[str, object]:
    """aggregate 요약(콘솔·RESULTS 용). source ref 없음."""
    tags = dish_tags or {}
    enclosures: dict[str, dict[str, object]] = {}
    cameras: dict[str, Counter[str]] = defaultdict(Counter)
    nights: dict[str, set[str]] = defaultdict(set)
    for request in requests:
        entry = enclosures.setdefault(
            request.enclosure_digest,
            {"camera": request.anonymous_camera_digest, "roi_name": request.roi_name, "location_stratum": request.location_stratum,
             "count": 0, "bands": Counter(), "dish_tagged": 0},
        )
        entry["count"] += 1  # type: ignore[operator]
        entry["bands"][request.time_band] += 1  # type: ignore[index]
        if tags.get(request.source_ref, {}).get(request.roi_name) is True:
            entry["dish_tagged"] += 1  # type: ignore[operator]
        nights[request.enclosure_digest].add(request.camera_night)
        if request.roi_name == ROI_NAMES[0]:
            cameras[request.anonymous_camera_digest][request.time_band] += 1
    for digest, entry in enclosures.items():
        entry["bands"] = {band: entry["bands"][band] for band in TIME_BANDS}  # type: ignore[index]
        entry["camera_nights"] = len(nights[digest])
    band_balanced = all(max(c[b] for b in TIME_BANDS) - min(c[b] for b in TIME_BANDS) <= 1 for c in cameras.values())
    return {
        "schema": PILOT_SUMMARY_SCHEMA,
        "request_count": len(requests),
        "source_group_count": len({(r.source_ref, r.timestamp_ms) for r in requests}),
        "enclosures": enclosures,
        "cameras": {cam: {"timestamps": sum(c.values()), "bands": {b: c[b] for b in TIME_BANDS}} for cam, c in cameras.items()},
        "band_balanced": band_balanced,
        "dish_tags_supplied": bool(tags),
    }


# ── pixel side ────────────────────────────────────────────────────

def decode_frame_at(source_path: Path | str, timestamp_ms: int, *, capture_factory=None) -> np.ndarray:
    """영상의 `timestamp_ms` 위치 프레임 하나를 decode. 실패해도 capture 는 반드시 release."""
    factory = capture_factory or cv2.VideoCapture
    cap = factory(str(source_path))
    try:
        if not cap.isOpened():
            raise DecodeError(f"cannot open video: {Path(source_path).name}")
        cap.set(cv2.CAP_PROP_POS_MSEC, float(timestamp_ms))
        ok, frame = cap.read()
        if not ok or frame is None:
            raise DecodeError(f"decode failed at {timestamp_ms} ms")
        return frame
    finally:
        cap.release()


def lighting_stratum(bgr: np.ndarray) -> str:
    spread = bgr.max(axis=2).astype(np.int16) - bgr.min(axis=2).astype(np.int16)
    return "ir" if float(spread.mean()) <= IR_CHANNEL_SPREAD_MAX else "color"


def dhash(image: np.ndarray) -> int:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = small[:, 1:] > small[:, :-1]
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bit)
    return value


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def extract_review_items(
    requests: Sequence[FrameRequest],
    source_root: Path | str,
    profile: RoiProfile,
    output_dir: Path | str,
    *,
    seed: str,
    sequence_prefix: str = "P",
    capture_factory=None,
    jpeg_quality: int = 95,
) -> dict[str, object]:
    """요청을 timestamp 별로 한 번씩 decode 해 ROI crop JPEG 를 만들고 익명 큐 ZIP + 0600 lineage 를 쓴다."""
    if len(sequence_prefix) != 1 or not sequence_prefix.isupper():
        raise ValueError("sequence_prefix must be one uppercase letter")
    groups: dict[tuple[str, int], list[FrameRequest]] = {}
    for request in requests:
        groups.setdefault((request.source_ref, request.timestamp_ms), []).append(request)

    kept: list[dict[str, object]] = []
    seen_sha: set[str] = set()
    recent: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    dropped_exact = dropped_near = 0
    failures: list[dict[str, object]] = []
    for (source_ref, timestamp_ms), members in groups.items():
        path = Path(source_root) / source_ref / "video.mp4"
        try:
            frame = decode_frame_at(path, timestamp_ms, capture_factory=capture_factory)
        except DecodeError as error:
            failures.append({"request_ids": [m.request_id for m in members], "error": str(error)})
            continue
        if frame.shape[:2] != (profile.frame_height, profile.frame_width):
            raise ValueError("decoded frame size differs from ROI profile frame size")
        for request in members:
            rect = profile.cameras[request.anonymous_camera_digest][request.roi_name]
            crop, _ = crop_frame(frame, rect, profile.padding_px)
            ok, buffer = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
            if not ok:
                raise DecodeError("jpeg encode failed")
            payload = buffer.tobytes()
            sha = hashlib.sha256(payload).hexdigest()
            if sha in seen_sha:
                dropped_exact += 1
                continue
            digest = dhash(crop)
            key = (source_ref, request.roi_name)
            if any(abs(timestamp_ms - t) <= MIN_SAME_SOURCE_GAP_MS and hamming(digest, h) <= DHASH_MAX_DISTANCE for t, h in recent[key]):
                dropped_near += 1
                continue
            seen_sha.add(sha)
            recent[key].append((timestamp_ms, digest))
            kept.append({
                "request": request, "payload": payload, "sha": sha, "width": int(crop.shape[1]), "height": int(crop.shape[0]),
                "full_xy": crop_bounds(rect, profile.padding_px, profile.frame_width, profile.frame_height),
                "lighting": lighting_stratum(crop),
            })

    kept.sort(key=lambda k: _rank(seed, k["request"].request_id))  # type: ignore[union-attr]
    items: list[dict[str, object]] = []
    lineage_rows: list[dict[str, object]] = []
    zip_entries: list[tuple[str, bytes]] = []
    for number, entry in enumerate(kept, start=1):
        sequence = f"V27{sequence_prefix}{number:04d}"
        request: FrameRequest = entry["request"]  # type: ignore[assignment]
        items.append(ReviewItem(sequence, f"{sequence}.jpg", str(entry["sha"]), int(entry["width"]), int(entry["height"])).to_json())
        zip_entries.append((f"{sequence}.jpg", entry["payload"]))  # type: ignore[arg-type]
        lineage_rows.append({
            "anonymous_sequence": sequence, "request_id": request.request_id, "source_ref": request.source_ref,
            "source_sha256": request.source_sha256, "anonymous_camera_digest": request.anonymous_camera_digest,
            "camera_night": request.camera_night, "enclosure_digest": request.enclosure_digest, "roi_name": request.roi_name,
            "timestamp_ms": request.timestamp_ms, "time_band": request.time_band, "location_stratum": request.location_stratum,
            "roi_profile_sha256": request.roi_profile_sha256, "full_xy": list(entry["full_xy"]),  # type: ignore[arg-type]
            "image_sha256": entry["sha"], "lighting_stratum": entry["lighting"],
        })
    status = "REVIEW_QUEUE_READY" if len(items) == len(requests) else "REVIEW_QUEUE_SHORT"
    queue = {"schema": REVIEW_QUEUE_SCHEMA, "status": status, "test_sheet_sha256": profile.test_sheet_sha256, "items": items, **_ZERO_WRITES}
    lineage = {"schema": LINEAGE_SCHEMA, "status": "LINEAGE_READY", "test_sheet_sha256": profile.test_sheet_sha256,
               "roi_profile_sha256": profile.profile_sha256, "items": lineage_rows, **_ZERO_WRITES}
    report = {
        "schema": EXTRACT_REPORT_SCHEMA, "status": status, "sequence_prefix": sequence_prefix, "requested": len(requests),
        "kept": len(items), "dropped_exact_duplicate": dropped_exact, "dropped_near_duplicate": dropped_near,
        "decode_failure_count": len(failures), "lighting_counts": dict(Counter(str(e["lighting"]) for e in kept)),
        "roi_profile_sha256": profile.profile_sha256, "jpeg_quality": int(jpeg_quality),
    }
    out = Path(output_dir)
    write_private_zip_new(out / "review-queue.zip", zip_entries + [("review-queue.public.json", canonical_json_bytes(queue))])
    write_private_json_new(out / "review-queue.public.json", queue)
    write_private_json_new(out / "lineage.private.json", lineage)
    write_private_json_new(out / "extract-report.private.json", {**report, "decode_failures": failures})
    return {"queue": queue, "lineage": lineage, "report": report, "zip_path": out / "review-queue.zip"}


NEGATIVE_EXPANSION_MIN_GAP_MS = 10 * 60 * 1000
NEGATIVE_EXPANSION_PER_SLOT_MAX = 2


def select_negative_expansion(
    human_gt: Mapping[str, object],
    lineage: Mapping[str, object],
    inventory: Mapping[str, object],
    roles: Mapping[str, object],
    profile: RoiProfile,
    *,
    target: int = 600,
    seed: str,
    used_timestamps: Iterable[tuple[str, int]] = (),
    per_slot_max: int = NEGATIVE_EXPANSION_PER_SLOT_MAX,
    include_adjacent: bool = True,
) -> list[FrameRequest]:
    """재층화 negative-expansion-v1: 사람이 `absent` 로 판정한 슬롯(+같은 밤 인접 슬롯)에서 새 timestamp 를 뽑는다.

    예측 모델 없이 사람 판정만 쓴다. 숨은 개체는 오래 숨어 있으므로 같은 슬롯·인접 슬롯의 다른 시각도 absent 일 확률이 높다.
    같은 timestamp 의 세 ROI 를 모두 요청(형제 규칙). 슬롯당 최대 `per_slot_max` 개, 기존 timestamp 와 5분·새 timestamp 끼리 10분 간격.
    absent 판정마다 라운드 로빈으로 뽑아 특정 슬롯에 몰리지 않게 한다. 부족하면 SelectionShortage.
    """
    if target <= 0 or target % 3:
        raise ValueError("target must be a positive multiple of 3 (three ROI per timestamp)")
    lineage_by = {str(row["anonymous_sequence"]): row for row in lineage["items"]}  # type: ignore[index]
    absent_rows = [lineage_by[str(item["anonymous_sequence"])] for item in human_gt["items"] if item["status"] == "absent"]  # type: ignore[index]
    if not absent_rows:
        raise SelectionShortage("negative expansion has no absent judgments to expand from")
    records = {str(rec["source_ref"]): rec for rec in inventory["records"]}  # type: ignore[index]
    role_rows = {str(row["source_ref"]): row for row in roles["rows"]}  # type: ignore[index]
    by_cam_night: dict[tuple[str, str], list[str]] = defaultdict(list)
    for ref in records:
        parts = ref.split("/")
        by_cam_night[(parts[1], parts[2])].append(ref)
    for refs in by_cam_night.values():
        refs.sort()

    def neighbourhood(ref: str) -> list[str]:
        parts = ref.split("/")
        ordered = by_cam_night[(parts[1], parts[2])]
        index = ordered.index(ref)
        out = [ref]
        if include_adjacent:
            if index > 0:
                out.append(ordered[index - 1])
            if index + 1 < len(ordered):
                out.append(ordered[index + 1])
        return out

    def slot_candidates(ref: str) -> list[tuple[str, int]]:
        rec, row = records.get(ref), role_rows.get(ref)
        if rec is None or row is None or Role(str(row["role"])) is not Role.V27_TRAIN:
            return []
        start = datetime.fromisoformat(str(rec["scheduled_start_utc"]).replace("Z", "+00:00"))
        duration = float(rec["duration_sec"])
        found: list[tuple[str, int]] = []
        offset = CANDIDATE_MARGIN_SEC
        while offset <= duration - CANDIDATE_MARGIN_SEC:
            if time_band_for(start + timedelta(seconds=offset)) is not None:
                timestamp_ms = offset * 1000
                found.append((_rank(seed, "neg", str(rec["source_sha256"]), str(timestamp_ms)), timestamp_ms))
            offset += CANDIDATE_STEP_SEC
        return sorted(found)

    used_by_slot: dict[str, set[int]] = defaultdict(set)
    for ref, timestamp_ms in used_timestamps:
        used_by_slot[ref].add(int(timestamp_ms))
    chosen_by_slot: dict[str, list[int]] = defaultdict(list)
    chosen: list[tuple[str, int]] = []

    def acceptable(ref: str, timestamp_ms: int) -> bool:
        if len(chosen_by_slot[ref]) >= per_slot_max:
            return False
        if any(abs(timestamp_ms - old) < MIN_SAME_SOURCE_GAP_MS for old in used_by_slot[ref]):
            return False
        return all(abs(timestamp_ms - new) >= NEGATIVE_EXPANSION_MIN_GAP_MS for new in chosen_by_slot[ref])

    judgments = sorted(absent_rows, key=lambda r: _rank(seed, str(r["source_sha256"]), str(r["timestamp_ms"]), str(r["roi_name"])))
    queues: list[list[tuple[str, int]]] = []
    for row in judgments:
        sequence: list[tuple[str, int]] = []
        for ref in neighbourhood(str(row["source_ref"])):
            sequence.extend((ref, timestamp_ms) for _, timestamp_ms in slot_candidates(ref))
        queues.append(sequence)
    needed = target // 3
    progress = True
    while len(chosen) < needed and progress:
        progress = False
        for sequence in queues:
            while sequence:
                ref, timestamp_ms = sequence.pop(0)
                if acceptable(ref, timestamp_ms):
                    chosen.append((ref, timestamp_ms))
                    chosen_by_slot[ref].append(timestamp_ms)
                    progress = True
                    break
            if len(chosen) >= needed:
                break
    if len(chosen) < needed:
        raise SelectionShortage(f"negative expansion pool supports {len(chosen)} timestamps but {needed} are needed")

    requests: list[FrameRequest] = []
    for ref, timestamp_ms in chosen:
        rec, row = records[ref], role_rows[ref]
        start = datetime.fromisoformat(str(rec["scheduled_start_utc"]).replace("Z", "+00:00"))
        band = time_band_for(start + timedelta(milliseconds=timestamp_ms)) or "unknown"
        camera = str(row["anonymous_camera_digest"])
        for roi_name in ROI_NAMES:
            requests.append(
                FrameRequest(
                    request_id="req-" + _rank(seed, "neg", str(rec["source_sha256"]), str(timestamp_ms), roi_name)[:16],
                    source_ref=ref, source_sha256=str(rec["source_sha256"]), anonymous_camera_digest=camera,
                    camera_night=str(row["camera_night"]), enclosure_digest=enclosure_digest(camera, roi_name), roi_name=roi_name,
                    timestamp_ms=timestamp_ms, time_band=band, location_stratum=location_stratum(roi_name), role=Role.V27_TRAIN,
                    roi_profile_sha256=profile.profile_sha256,
                )
            )
    return requests


def select_double_review(items: Sequence[Mapping[str, object]], *, count: int = 60) -> list[str]:
    """blind double-review 대상: image SHA 의 SHA 순위 상위 `count` 개 (예측·시간 정보 무관)."""
    ranked = sorted(items, key=lambda item: hashlib.sha256(str(item["image_sha256"]).encode("utf-8")).hexdigest())
    return [str(item["anonymous_sequence"]) for item in ranked[:count]]
