"""Task 3 — metadata-only role freeze와 v2.6 sealed holdout reservation.

owner 승인(2026-09-10, decision-gate 2차): holdout = v2.6 detector freeze cutoff 이후 첫 3 complete camera-night,
같은 날짜의 나머지 camera-night 는 date guard, 나머지는 v2.7 dev(train/val) — 불완전 camera-night 는 train 전용.
실제 freeze 파일(`yolo26n-v26-detector-freeze-v1`)엔 cutoff 필드가 없어 명시 cutoff 를 받아 근거와 함께 기록한다.
"""
from __future__ import annotations

import builtins
import hashlib
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scripts.yolo26n_v27_c500g.roles import (
    ROLE_FREEZE_SCHEMA,
    HOLDOUT_SHORTAGE,
    READY,
    VAL_SHORTAGE,
    PixelAccessDenied,
    assert_pixel_access_allowed,
    freeze_roles,
)
from tests.yolo26n_v27_c500g.factories import SHA_A, SHA_B, ZERO_WRITES, valid_v26_freeze

KST = ZoneInfo("Asia/Seoul")
CAMERAS = ("cam-digest-01", "cam-digest-02", "cam-digest-03")


def _slot_utc(night: str, index: int) -> str:
    start = datetime.fromisoformat(night).replace(tzinfo=KST) + timedelta(hours=20, minutes=30 * index)
    return start.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _records(nights: dict[str, dict[str, int]]) -> list[dict[str, object]]:
    """nights = {"2026-09-03": {"cam-digest-01": 24, "cam-digest-02": 24, ...}} — 값은 실제 존재하는 슬롯 수."""
    rows = []
    for night, cams in nights.items():
        for cam, n_slots in cams.items():
            for index in range(n_slots):
                rows.append({
                    "source_ref": f"recordings/{cam}/night={night}/slot-{index:02d}",
                    "source_sha256": hashlib.sha256(f"{cam}|{night}|{index}".encode()).hexdigest(),
                    "anonymous_camera_digest": cam,
                    "camera_night": hashlib.sha256(f"camera-night:{cam}/{night}".encode()).hexdigest(),
                    "scheduled_start_utc": _slot_utc(night, index),
                    "duration_sec": 1800.0, "width": 2880, "height": 1620, "fps": 20.0, "codec": "hevc",
                })
    return rows


def _inventory(nights: dict[str, dict[str, int]], *, status: str = "V27_SOURCE_INVENTORY_READY") -> dict[str, object]:
    return {
        "schema": "yolo26n-v27-c500g-source-inventory-v1", "status": status, "test_sheet_sha256": SHA_A,
        "records": _records(nights), **ZERO_WRITES,
    }


def _full(cams=CAMERAS, n=24) -> dict[str, int]:
    return {cam: n for cam in cams}


CUTOFF = "2026-08-31T13:51:52Z"  # v2.6 detector freeze (KST 2026-08-31 22:51:52)


def _freeze() -> dict[str, object]:
    """teacher-freeze factory 의 cutoff 를 이 시험의 cutoff 로 맞춘 매니페스트 (명시 cutoff 와 일치해야 통과)."""
    return {**valid_v26_freeze(), "freeze_cutoff_utc": CUTOFF}


def _seven_nights(start_day: int = 3) -> dict[str, dict[str, int]]:
    return {f"2026-09-{start_day + i:02d}": _full() for i in range(7)}


def _rows(result, role):
    return [r for r in result["rows"] if r["role"] == role]


def _camera_nights(rows):
    return {r["camera_night"] for r in rows}


# ── holdout reservation ─────────────────────────────────────────────

def test_reserves_first_three_post_freeze_complete_camera_nights():
    result = freeze_roles(_inventory(_seven_nights()), _freeze(), seed="v27-role-freeze-v1", freeze_cutoff_utc=CUTOFF)
    holdout = _rows(result, "v26_holdout")
    assert result["status"] == READY
    assert len(_camera_nights(holdout)) == 3
    assert {r["night_date"] for r in holdout} == {"2026-09-03"}
    assert all(r["starts_after_v26_freeze"] is True for r in holdout)
    assert all(r["complete"] is True for r in holdout)


def test_roles_never_overlap_and_cover_every_record():
    inv = _inventory(_seven_nights())
    result = freeze_roles(inv, _freeze(), seed="v27-role-freeze-v1", freeze_cutoff_utc=CUTOFF)
    by_night: dict[str, set[str]] = {}
    for r in result["rows"]:
        by_night.setdefault(r["camera_night"], set()).add(r["role"])
    assert all(len(roles) == 1 for roles in by_night.values())
    assert len(result["rows"]) == len(inv["records"])
    assert result["schema"] == ROLE_FREEZE_SCHEMA
    assert result["test_sheet_sha256"] == SHA_A
    assert all(result[k] == 0 for k in ZERO_WRITES)


def test_same_date_leftovers_become_date_guard_when_holdout_spans_two_dates():
    nights = {"2026-09-03": {"cam-digest-01": 24, "cam-digest-02": 24, "cam-digest-03": 20}}
    nights.update({f"2026-09-{d:02d}": _full() for d in range(4, 10)})
    result = freeze_roles(_inventory(nights), _freeze(), seed="v27-role-freeze-v1", freeze_cutoff_utc=CUTOFF)
    holdout = _rows(result, "v26_holdout")
    guard = _rows(result, "v26_holdout_date_guard")
    assert {(r["night_date"], r["anonymous_camera_digest"]) for r in holdout} == {
        ("2026-09-03", "cam-digest-01"), ("2026-09-03", "cam-digest-02"), ("2026-09-04", "cam-digest-01"),
    }
    assert {(r["night_date"], r["anonymous_camera_digest"]) for r in guard} == {
        ("2026-09-03", "cam-digest-03"), ("2026-09-04", "cam-digest-02"), ("2026-09-04", "cam-digest-03"),
    }


def test_pre_freeze_nights_are_never_promoted_when_short():
    nights = {"2026-08-28": _full(), "2026-08-29": _full(), "2026-09-03": {"cam-digest-01": 24, "cam-digest-02": 24, "cam-digest-03": 5}}
    nights.update({f"2026-09-{d:02d}": _full() for d in range(4, 7)})
    # 09-03 complete 는 2개, 이후 09-04 가 있으므로 3개 채워짐 → shortage 아님. 09-04~06 을 빼면 shortage.
    short = {"2026-08-28": _full(), "2026-08-29": _full(), "2026-09-03": {"cam-digest-01": 24, "cam-digest-02": 24, "cam-digest-03": 5}}
    result = freeze_roles(_inventory(short), _freeze(), seed="v27-role-freeze-v1", freeze_cutoff_utc=CUTOFF)
    assert result["status"] == HOLDOUT_SHORTAGE
    assert len(_camera_nights(_rows(result, "v26_holdout"))) == 2
    assert all(r["night_date"] != "2026-08-28" and r["night_date"] != "2026-08-29" for r in _rows(result, "v26_holdout"))


def test_incomplete_camera_nights_are_train_only_and_flagged():
    nights = _seven_nights()
    nights["2026-09-06"] = {"cam-digest-01": 24, "cam-digest-02": 21, "cam-digest-03": 24}
    result = freeze_roles(_inventory(nights), _freeze(), seed="v27-role-freeze-v1", freeze_cutoff_utc=CUTOFF)
    incomplete = [r for r in result["rows"] if r["complete"] is False]
    assert incomplete and {r["role"] for r in incomplete} == {"v27_train"}
    assert {r["anonymous_camera_digest"] for r in incomplete} == {"cam-digest-02"}


def test_val_shortage_when_fewer_than_three_dev_date_blocks():
    nights = {"2026-09-03": _full(), "2026-09-04": _full(), "2026-09-05": _full()}
    result = freeze_roles(_inventory(nights), _freeze(), seed="v27-role-freeze-v1", freeze_cutoff_utc=CUTOFF)
    assert result["status"] == VAL_SHORTAGE
    assert len(_camera_nights(_rows(result, "v26_holdout"))) == 3


def test_validation_is_at_least_one_date_block_deterministic_by_seed():
    inv = _inventory(_seven_nights())
    a = freeze_roles(inv, _freeze(), seed="v27-role-freeze-v1", freeze_cutoff_utc=CUTOFF)
    b = freeze_roles(inv, _freeze(), seed="v27-role-freeze-v1", freeze_cutoff_utc=CUTOFF)
    assert a["rows"] == b["rows"]
    val_dates = {r["night_date"] for r in _rows(a, "v27_val")}
    train_dates = {r["night_date"] for r in _rows(a, "v27_train")}
    assert val_dates and val_dates.isdisjoint(train_dates)  # date block 단위 분리
    assert {r["role"] for r in a["rows"] if r["night_date"] in val_dates} == {"v27_val"}


# ── freeze cutoff provenance ────────────────────────────────────────

def test_cutoff_comes_from_manifest_when_present_and_explicit_must_match():
    freeze = valid_v26_freeze()  # freeze_cutoff_utc 포함
    result = freeze_roles(_inventory(_seven_nights()), freeze, seed="s")
    assert result["freeze_cutoff_utc"] == freeze["freeze_cutoff_utc"]
    assert result["freeze_cutoff_source"]["origin"] == "manifest"
    with pytest.raises(ValueError, match="cutoff"):
        freeze_roles(_inventory(_seven_nights()), freeze, seed="s", freeze_cutoff_utc="2026-09-01T00:00:00Z")


def test_detector_freeze_schema_requires_explicit_cutoff_and_records_provenance():
    detector_freeze = {"schema": "yolo26n-v26-detector-freeze-v1", "status": "V26_DETECTOR_FROZEN_DEVELOPMENT_ONLY",
                       "checkpoint_sha256": SHA_B, "source_commit": "4ce6270"}
    with pytest.raises(ValueError, match="cutoff"):
        freeze_roles(_inventory(_seven_nights()), detector_freeze, seed="s")
    result = freeze_roles(_inventory(_seven_nights()), detector_freeze, seed="s", freeze_cutoff_utc=CUTOFF,
                          freeze_manifest_sha256=SHA_A, freeze_manifest_mtime_utc="2026-08-31T13:51:52Z")
    src = result["freeze_cutoff_source"]
    assert src == {"origin": "explicit", "freeze_schema": "yolo26n-v26-detector-freeze-v1", "checkpoint_sha256": SHA_B,
                   "freeze_manifest_sha256": SHA_A, "freeze_manifest_mtime_utc": "2026-08-31T13:51:52Z"}


def test_rejects_non_ready_inventory_and_unknown_freeze_schema():
    with pytest.raises(ValueError, match="inventory"):
        freeze_roles(_inventory(_seven_nights(), status="V27_SOURCE_INVENTORY_MISMATCH"), _freeze(), seed="s", freeze_cutoff_utc=CUTOFF)
    with pytest.raises(ValueError, match="freeze"):
        freeze_roles(_inventory(_seven_nights()), {"schema": "something-else"}, seed="s", freeze_cutoff_utc=CUTOFF)


# ── metadata-only + pixel gate ──────────────────────────────────────

def test_freeze_roles_never_opens_files(monkeypatch):
    def _no_open(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("freeze_roles must not open files")
    monkeypatch.setattr(builtins, "open", _no_open)
    result = freeze_roles(_inventory(_seven_nights()), _freeze(), seed="s", freeze_cutoff_utc=CUTOFF)
    assert result["status"] == READY


def test_pixel_access_gate_allows_only_listed_roles():
    result = freeze_roles(_inventory(_seven_nights()), _freeze(), seed="s", freeze_cutoff_utc=CUTOFF)
    train_ref = _rows(result, "v27_train")[0]["source_ref"]
    holdout_ref = _rows(result, "v26_holdout")[0]["source_ref"]
    assert_pixel_access_allowed(result, train_ref, allowed_roles=("v27_train",))
    with pytest.raises(PixelAccessDenied):
        assert_pixel_access_allowed(result, holdout_ref, allowed_roles=("v27_train", "v27_val"))
    with pytest.raises(PixelAccessDenied):
        assert_pixel_access_allowed(result, "recordings/unknown/slot", allowed_roles=("v27_train",))
