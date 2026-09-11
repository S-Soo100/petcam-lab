"""재층화 규칙 negative-expansion-v1 — 사람이 absent 로 판정한 슬롯(±인접 슬롯)에서 새 timestamp 를 뽑아 음성 예제를 늘린다."""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict

import pytest

from scripts.yolo26n_v27_c500g.contracts import Role
from scripts.yolo26n_v27_c500g.sampling import (
    MIN_SAME_SOURCE_GAP_MS,
    NEGATIVE_EXPANSION_MIN_GAP_MS,
    SelectionShortage,
    select_negative_expansion,
    select_pilot_requests,
)
from tests.yolo26n_v27_c500g.factories import SHA_A, ZERO_WRITES
from tests.yolo26n_v27_c500g.test_sampling import HOLDOUT_NIGHT, SEED, _build, _profile


def _lineage_and_gt(pilot, *, absent_every: int = 7):
    rows, items = [], []
    for n, r in enumerate(pilot, start=1):
        seq = f"V27P{n:04d}"
        rows.append({"anonymous_sequence": seq, "request_id": r.request_id, "source_ref": r.source_ref, "source_sha256": r.source_sha256,
                     "anonymous_camera_digest": r.anonymous_camera_digest, "camera_night": r.camera_night, "enclosure_digest": r.enclosure_digest,
                     "roi_name": r.roi_name, "timestamp_ms": r.timestamp_ms, "time_band": r.time_band, "location_stratum": r.location_stratum,
                     "roi_profile_sha256": r.roi_profile_sha256, "full_xy": [0, 0, 900, 1400], "image_sha256": hashlib.sha256(seq.encode()).hexdigest(),
                     "lighting_stratum": "ir"})
        absent = n % absent_every == 0
        items.append({"anonymous_sequence": seq, "status": "absent" if absent else "present", "boxes": [] if absent else [{"x1": 1.0, "y1": 1.0, "x2": 50.0, "y2": 80.0}],
                      "revision": 2, "attributes": {}, "cvat_frame": n - 1, "source_group_digest": "g", "full_frame_eligible": True})
    lineage = {"schema": "yolo26n-v27-c500g-private-lineage-v1", "status": "LINEAGE_READY", "test_sheet_sha256": SHA_A, "roi_profile_sha256": SHA_A, "items": rows, **ZERO_WRITES}
    gt = {"schema": "yolo26n-v27-c500g-human-gt-v1", "status": "HUMAN_GT_READY", "test_sheet_sha256": SHA_A, "queue_sha256": SHA_A, "items": items, "summary": {}, **ZERO_WRITES}
    return lineage, gt


@pytest.fixture(scope="module")
def world():
    inventory, roles = _build()
    profile = _profile(roles)
    pilot = select_pilot_requests(inventory, roles, profile, target=600, seed=SEED)
    lineage, gt = _lineage_and_gt(pilot)
    used = {(r.source_ref, r.timestamp_ms) for r in pilot}
    return inventory, roles, profile, pilot, lineage, gt, used


def _slot_key(ref: str) -> tuple[str, str, str]:
    parts = ref.split("/")
    return parts[1], parts[2], parts[3]  # cam, night, slot


def test_negative_expansion_returns_600_from_absent_slots_and_neighbours(world):
    inventory, roles, profile, pilot, lineage, gt, used = world
    rows = select_negative_expansion(gt, lineage, inventory, roles, profile, target=600, seed=SEED, used_timestamps=used)
    assert len(rows) == 600
    assert set(Counter((r.source_ref, r.timestamp_ms) for r in rows).values()) == {3}  # 3 ROI per timestamp
    assert {r.role for r in rows} == {Role.V27_TRAIN} and not any(HOLDOUT_NIGHT in r.source_ref for r in rows)
    assert used.isdisjoint((r.source_ref, r.timestamp_ms) for r in rows)
    absent_slots = {_slot_key(l["source_ref"]) for l, i in zip(lineage["items"], gt["items"], strict=True) if i["status"] == "absent"}
    slot_index = {}
    for rec in inventory["records"]:
        cam, night, slot = _slot_key(rec["source_ref"])
        slot_index.setdefault((cam, night), []).append(slot)
    for key in slot_index:
        slot_index[key].sort()
    for r in rows:
        cam, night, slot = _slot_key(r.source_ref)
        ordered = slot_index[(cam, night)]
        pos = ordered.index(slot)
        neighbours = {(cam, night, ordered[k]) for k in (pos - 1, pos, pos + 1) if 0 <= k < len(ordered)}
        assert neighbours & absent_slots, r.source_ref


def test_negative_expansion_respects_spacing_and_per_slot_cap(world):
    inventory, roles, profile, pilot, lineage, gt, used = world
    rows = select_negative_expansion(gt, lineage, inventory, roles, profile, target=600, seed=SEED, used_timestamps=used)
    new_by_slot = defaultdict(set)
    for r in rows:
        new_by_slot[r.source_ref].add(r.timestamp_ms)
    old_by_slot = defaultdict(set)
    for ref, ts in used:
        old_by_slot[ref].add(ts)
    for ref, stamps in new_by_slot.items():
        assert len(stamps) <= 2
        ordered = sorted(stamps)
        assert all(b - a >= NEGATIVE_EXPANSION_MIN_GAP_MS for a, b in zip(ordered, ordered[1:], strict=False))
        assert all(abs(t - o) >= MIN_SAME_SOURCE_GAP_MS for t in stamps for o in old_by_slot.get(ref, ()))


def test_negative_expansion_is_deterministic_and_reports_shortage(world):
    inventory, roles, profile, pilot, lineage, gt, used = world
    a = select_negative_expansion(gt, lineage, inventory, roles, profile, target=600, seed=SEED, used_timestamps=used)
    b = select_negative_expansion(gt, lineage, inventory, roles, profile, target=600, seed=SEED, used_timestamps=used)
    assert [r.to_json() for r in a] == [r.to_json() for r in b]
    tiny_lineage, tiny_gt = _lineage_and_gt(pilot, absent_every=300)  # absent 2건뿐 → 후보 부족
    with pytest.raises(SelectionShortage, match="negative"):
        select_negative_expansion(tiny_gt, tiny_lineage, inventory, roles, profile, target=600, seed=SEED, used_timestamps=used)
