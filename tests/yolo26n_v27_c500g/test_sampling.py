"""Task 5 — prediction-independent, train-only 600 ROI 파일럿 큐 (선택 · 추출 · 익명화)."""
from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import pytest

from scripts.yolo26n_v27_c500g.contracts import ReviewItem, Role
from scripts.yolo26n_v27_c500g.roi import ROI_PROFILE_SCHEMA, crop_bounds, profile_digest, validate_roi_profile
from scripts.yolo26n_v27_c500g.sampling import (
    DecodeError,
    SelectionShortage,
    dhash,
    decode_frame_at,
    extract_review_items,
    hamming,
    lighting_stratum,
    select_double_review,
    select_pilot_requests,
    summarize_selection,
    time_band_for,
)
from tests.yolo26n_v27_c500g.factories import SHA_A, ZERO_WRITES

KST = ZoneInfo("Asia/Seoul")
CAMS = ("cam01", "cam02", "cam03")
TRAIN_NIGHTS = tuple(f"2026-08-{d:02d}" for d in range(20, 32)) + ("2026-09-01",)
HOLDOUT_NIGHT = "2026-09-04"
SEED = "v27-pilot-test-seed"


def _cam_digest(cam: str) -> str:
    return hashlib.sha256(f"camera:{cam}".encode()).hexdigest()


def _build(*, nights=TRAIN_NIGHTS, slots_per_night: int = 24, cams=CAMS, duration: float = 1770.0):
    records, rows = [], []
    for cam in cams:
        for night in (*nights, HOLDOUT_NIGHT):
            role = "v26_holdout" if night == HOLDOUT_NIGHT else "v27_train"
            base = datetime.strptime(night, "%Y-%m-%d").replace(hour=20, tzinfo=KST)
            camera_night = hashlib.sha256(f"{cam}|{night}".encode()).hexdigest()
            for i in range(slots_per_night):
                start = base + timedelta(minutes=30 * i)
                ref = f"recordings/{cam}/night={night}/{start.strftime('%Y%m%dT%H%M%S%z')}"
                sha = hashlib.sha256(ref.encode()).hexdigest()
                common = {"source_ref": ref, "source_sha256": sha, "anonymous_camera_digest": _cam_digest(cam),
                          "camera_night": camera_night, "role": role}
                records.append({**common, "scheduled_start_utc": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "duration_sec": duration, "width": 2880, "height": 1620, "fps": 10.0, "codec": "hevc",
                                "night_date": night, "partial": False, "scheduled_slot": True, "complete_slot": True,
                                "start_offset_sec": 0.0})
                rows.append({**common, "night_date": night, "complete": True, "scheduled_start_utc": records[-1]["scheduled_start_utc"],
                             "starts_after_v26_freeze": True})
    inventory = {"schema": "yolo26n-v27-c500g-source-inventory-v1", "status": "V27_SOURCE_INVENTORY_READY",
                 "test_sheet_sha256": SHA_A, "records": records, **ZERO_WRITES}
    roles = {"schema": "yolo26n-v27-c500g-role-freeze-v1", "status": "V27_VAL_SHORTAGE", "test_sheet_sha256": SHA_A,
             "rows": rows, **ZERO_WRITES}
    return inventory, roles


def _profile(roles, cams=CAMS):
    rects = {"left": {"x1": 0.02, "y1": 0.05, "x2": 0.32, "y2": 0.98},
             "middle": {"x1": 0.35, "y1": 0.05, "x2": 0.65, "y2": 0.98},
             "right": {"x1": 0.68, "y1": 0.05, "x2": 0.98, "y2": 0.98}}
    body = {"schema": ROI_PROFILE_SCHEMA, "status": "V27_ROI_PROFILE_READY", "test_sheet_sha256": SHA_A,
            "frame_width": 2880, "frame_height": 1620, "padding_px": 24, "calibration_provenance": "v27_train",
            "day_verified": True, "ir_verified": True, "cameras": {_cam_digest(c): json.loads(json.dumps(rects)) for c in cams},
            **ZERO_WRITES}
    body["profile_sha256"] = profile_digest(body)
    return validate_roi_profile(body, roles, calibration_sources=[])


@pytest.fixture(scope="module")
def world():
    inventory, roles = _build()
    return inventory, roles, _profile(roles)


@pytest.fixture(scope="module")
def pilot(world):
    inventory, roles, profile = world
    return select_pilot_requests(inventory, roles, profile, target=600, seed=SEED)


# ── selection ─────────────────────────────────────────────────────

def test_pilot_is_600_train_only_and_balanced(pilot):
    assert len(pilot) == 600
    assert set(Counter(r.enclosure_digest for r in pilot).values()) == {66, 67}
    assert {r.role for r in pilot} == {Role.V27_TRAIN}
    groups = Counter((r.source_ref, r.timestamp_ms) for r in pilot)
    assert set(groups.values()) == {3}  # 같은 timestamp 의 세 ROI 가 한 source group


def test_pilot_balances_time_bands_per_camera(pilot):
    per_cam_band = Counter((r.anonymous_camera_digest, r.time_band) for r in pilot if r.roi_name == "left")
    for cam in {r.anonymous_camera_digest for r in pilot}:
        counts = [per_cam_band[(cam, band)] for band in ("20-22", "22-02", "02-05", "05-08")]
        assert max(counts) - min(counts) <= 1, counts


def test_pilot_uses_each_source_at_most_once_per_roi(pilot):
    assert max(Counter((r.source_ref, r.roi_name) for r in pilot).values()) == 1


def test_pilot_never_touches_holdout_sources(pilot):
    assert not any(HOLDOUT_NIGHT in r.source_ref for r in pilot)


def test_pilot_is_deterministic_per_seed(world, pilot):
    inventory, roles, profile = world
    again = select_pilot_requests(inventory, roles, profile, target=600, seed=SEED)
    assert [r.to_json() for r in again] == [r.to_json() for r in pilot]
    other = select_pilot_requests(inventory, roles, profile, target=600, seed=SEED + "-b")
    assert {(r.source_ref, r.timestamp_ms) for r in other} != {(r.source_ref, r.timestamp_ms) for r in pilot}


def test_pilot_raises_instead_of_filling_from_other_enclosures():
    inventory, roles = _build(nights=TRAIN_NIGHTS[:2])  # 카메라당 48 슬롯 < 67 timestamp
    with pytest.raises(SelectionShortage, match="camera"):
        select_pilot_requests(inventory, roles, _profile(roles), target=600, seed=SEED)


def test_dish_tag_floor_is_enforced_per_enclosure(world):
    inventory, roles, profile = world
    tagged = [r["source_ref"] for r in inventory["records"] if r["role"] == "v27_train" and r["source_ref"].endswith("T230000+0900")]
    dish_tags = {ref: {"left": True, "middle": False, "right": True} for ref in tagged}
    rows = select_pilot_requests(inventory, roles, profile, target=600, seed=SEED, dish_tags=dish_tags)
    summary = summarize_selection(rows, dish_tags=dish_tags)
    for enclosure, stats in summary["enclosures"].items():
        if stats["roi_name"] in ("left", "right"):
            assert stats["dish_tagged"] >= 7, (enclosure, stats)
        else:
            assert stats["dish_tagged"] == 0
    assert summary["source_group_count"] == 200


def test_dish_tag_floor_shortage_raises(world):
    inventory, roles, profile = world
    one = next(r["source_ref"] for r in inventory["records"] if r["role"] == "v27_train")
    with pytest.raises(SelectionShortage, match="dish"):
        select_pilot_requests(inventory, roles, profile, target=600, seed=SEED, dish_tags={one: {"left": True}})


def test_exclude_sources_supports_disjoint_warmup(world, pilot):
    inventory, roles, profile = world
    used = {r.source_ref for r in pilot}
    warmup = select_pilot_requests(inventory, roles, profile, target=27, seed=SEED + "|warmup", exclude_sources=used)
    assert len(warmup) == 27
    assert used.isdisjoint(r.source_ref for r in warmup)


@pytest.mark.parametrize(
    "hhmm,expected",
    [("20:00", "20-22"), ("21:59", "20-22"), ("22:00", "22-02"), ("01:59", "22-02"), ("02:00", "02-05"),
     ("04:59", "02-05"), ("05:00", "05-08"), ("07:59", "05-08"), ("08:00", None), ("19:59", None)],
)
def test_time_band_boundaries(hhmm, expected):
    hour, minute = map(int, hhmm.split(":"))
    assert time_band_for(datetime(2026, 9, 1, hour, minute, tzinfo=KST)) == expected


# ── decode / hashing primitives ───────────────────────────────────

class FakeCapture:
    def __init__(self, frames, *, opened=True):
        self.frames, self.opened, self.released, self.pos = frames, opened, False, 0.0

    def isOpened(self):
        return self.opened

    def set(self, prop, value):
        self.pos = value
        return True

    def read(self):
        frame = self.frames(self.pos)
        return (frame is not None, frame)

    def release(self):
        self.released = True


def test_decode_frame_releases_capture_on_failure(monkeypatch):
    cap = FakeCapture(lambda _: None)
    monkeypatch.setattr(cv2, "VideoCapture", lambda _: cap)
    with pytest.raises(DecodeError):
        decode_frame_at(Path("/nonexistent/video.mp4"), 1000)
    assert cap.released is True


def test_decode_frame_returns_frame_and_releases(tmp_path):
    frame = np.full((1620, 2880, 3), 7, dtype=np.uint8)
    cap = FakeCapture(lambda _: frame)
    out = decode_frame_at(tmp_path / "video.mp4", 1000, capture_factory=lambda _: cap)
    assert out is frame and cap.released is True and cap.pos == 1000.0


def test_lighting_stratum_ir_vs_color():
    gray = np.full((50, 50, 3), 120, dtype=np.uint8)
    assert lighting_stratum(gray) == "ir"
    color = gray.copy()
    color[..., 2] = 200
    assert lighting_stratum(color) == "color"


def test_dhash_near_duplicate_distance():
    rng = np.random.default_rng(0)
    base = rng.integers(0, 255, (120, 160), dtype=np.uint8)
    assert hamming(dhash(base), dhash(base)) == 0
    noisy = np.clip(base.astype(int) + rng.integers(-1, 2, base.shape), 0, 255).astype(np.uint8)
    assert hamming(dhash(base), dhash(noisy)) <= 2
    assert hamming(dhash(base), dhash(rng.integers(0, 255, base.shape, dtype=np.uint8))) > 2


# ── extraction ────────────────────────────────────────────────────

def _frame_with_marker(pos_msec: float, salt: str = "") -> np.ndarray:
    """소스·시각마다 다른 랜덤 프레임 (같은 offset 이 여러 소스에 있어도 exact 중복이 안 나게 salt 포함)."""
    frame = np.zeros((1620, 2880, 3), dtype=np.uint8)
    rng = np.random.default_rng(int(hashlib.sha256(f"{salt}|{int(pos_msec)}".encode()).hexdigest()[:8], 16))
    frame[...] = rng.integers(0, 255, frame.shape, dtype=np.uint8)
    return frame


def test_extract_writes_anonymous_zip_and_private_lineage(world, pilot, tmp_path):
    inventory, roles, profile = world
    requests = pilot[:9]
    result = extract_review_items(requests, tmp_path / "mirror", profile, tmp_path / "out", seed=SEED,
                                  capture_factory=lambda _: FakeCapture(_frame_with_marker))
    queue, lineage, report = result["queue"], result["lineage"], result["report"]
    assert queue["status"] == "REVIEW_QUEUE_READY" and len(queue["items"]) == 9
    names = [ReviewItem.from_json(i).image_name for i in queue["items"]]
    assert names == [f"V27P{n:04d}.jpg" for n in range(1, 10)]
    public_text = json.dumps(queue)
    assert "recordings/" not in public_text and "cam0" not in public_text and "timestamp" not in public_text
    by_seq = {row["anonymous_sequence"]: row for row in lineage["items"]}
    assert set(by_seq) == set(i["anonymous_sequence"] for i in queue["items"])
    row = by_seq["V27P0001"]
    req = next(r for r in requests if r.request_id == row["request_id"])
    rect = profile.cameras[req.anonymous_camera_digest][req.roi_name]
    assert tuple(row["full_xy"]) == crop_bounds(rect, profile.padding_px, 2880, 1620)
    item = next(i for i in queue["items"] if i["anonymous_sequence"] == "V27P0001")
    x1, y1, x2, y2 = row["full_xy"]
    assert (item["width"], item["height"]) == (x2 - x1, y2 - y1)
    assert row["lighting_stratum"] in ("ir", "color") and report["lighting_counts"]["color"] == 9
    zip_path = tmp_path / "out" / "review-queue.zip"
    assert oct(zip_path.stat().st_mode & 0o777) == "0o600"
    with zipfile.ZipFile(zip_path) as zf:
        assert sorted(zf.namelist()) == sorted(names + ["review-queue.public.json"])
        jpeg = zf.read("V27P0001.jpg")
    assert hashlib.sha256(jpeg).hexdigest() == item["image_sha256"]
    decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (item["height"], item["width"])
    assert (tmp_path / "out" / "lineage.private.json").exists()


def test_extract_drops_exact_duplicates_and_reports_short(world, pilot, tmp_path):
    inventory, roles, profile = world
    gradient = np.tile(np.linspace(0, 255, 2880, dtype=np.uint8), (1620, 1))
    same = np.stack([gradient] * 3, axis=2)  # 시간 불변, ROI 위치별로만 다른 프레임
    result = extract_review_items(pilot[:6], tmp_path / "mirror", profile, tmp_path / "out", seed=SEED,
                                  capture_factory=lambda _: FakeCapture(lambda _: same))
    # 6 요청 = 2 timestamp × 3 ROI. 같은 ROI 의 crop 은 픽셀이 같아 exact SHA 중복 → 3 개만 남음
    assert len(result["queue"]["items"]) == 3
    assert result["report"]["dropped_exact_duplicate"] == 3
    assert result["queue"]["status"] == "REVIEW_QUEUE_SHORT"


def test_extract_sequence_prefix_for_warmup(world, pilot, tmp_path):
    inventory, roles, profile = world
    result = extract_review_items(pilot[:3], tmp_path / "mirror", profile, tmp_path / "out", seed=SEED, sequence_prefix="W",
                                  capture_factory=lambda _: FakeCapture(_frame_with_marker))
    assert [i["anonymous_sequence"] for i in result["queue"]["items"]] == ["V27W0001", "V27W0002", "V27W0003"]


def test_select_double_review_is_sha_rank():
    items = [{"anonymous_sequence": f"V27P{n:04d}", "image_sha256": hashlib.sha256(str(n).encode()).hexdigest()} for n in range(1, 101)]
    chosen = select_double_review(items, count=60)
    assert len(chosen) == 60 and len(set(chosen)) == 60
    expected = sorted(items, key=lambda i: hashlib.sha256(i["image_sha256"].encode()).hexdigest())[:60]
    assert chosen == [i["anonymous_sequence"] for i in expected]
