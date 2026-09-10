"""CLI (Task 10 부분): `inventory` 와 `freeze-roles` 순수 단계 + private attempt 기록. 실제 R2/DB 는 붙이지 않고 fake 로."""
from __future__ import annotations

import json
import stat
from datetime import date, timedelta

import pytest

from scripts.yolo26n_v27_c500g.cli import run_freeze_roles, run_inventory
from tests.yolo26n_v27_c500g.factories import SHA_B
from tests.yolo26n_v27_c500g.test_inventory import TEST_SHEET_SHA256, populate_week


@pytest.fixture(autouse=True)
def _week_tree(fake_bundle, fake_r2, fake_db):
    populate_week(fake_bundle, fake_r2, fake_db)


def _nights(n=7, start=date(2026, 8, 20)):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


@pytest.fixture
def attempt(tmp_path):
    return tmp_path / "attempts" / "a1"


def test_run_inventory_writes_private_artifact_and_public_summary(fake_bundle, fake_r2, fake_db, attempt):
    out = run_inventory(
        local_root=fake_bundle.root, r2_reader=fake_r2, db_reader=fake_db, attempt=attempt,
        camera_keys=["cam01", "cam02", "cam03"], nights=_nights(), test_sheet_sha256=TEST_SHEET_SHA256,
    )
    private = attempt / "inventory" / "source-inventory.private.json"
    assert private.exists() and stat.S_IMODE(private.stat().st_mode) == 0o600
    assert stat.S_IMODE((attempt / "inventory").stat().st_mode) == 0o700
    doc = json.loads(private.read_text())
    assert doc["status"] == "V27_SOURCE_INVENTORY_READY" and doc["test_sheet_sha256"] == TEST_SHEET_SHA256
    assert out["summary"]["schema"] == "yolo26n-v27-c500g-inventory-summary-v1"
    assert out["summary"]["complete_camera_night_count"] == 21
    assert "records" not in out["summary"] and "cam01" not in json.dumps(out["summary"])
    expected = json.loads((attempt / "inventory" / "expected-slots.private.json").read_text())
    assert expected["schedule_sha256"] == doc["expected_slots_schedule_sha256"]
    with pytest.raises(FileExistsError):
        run_inventory(local_root=fake_bundle.root, r2_reader=fake_r2, db_reader=fake_db, attempt=attempt,
                      camera_keys=["cam01", "cam02", "cam03"], nights=_nights(), test_sheet_sha256=TEST_SHEET_SHA256)


def test_run_freeze_roles_reads_private_inventory_and_writes_role_manifest(fake_bundle, fake_r2, fake_db, attempt, tmp_path):
    run_inventory(local_root=fake_bundle.root, r2_reader=fake_r2, db_reader=fake_db, attempt=attempt,
                  camera_keys=["cam01", "cam02", "cam03"], nights=_nights(), test_sheet_sha256=TEST_SHEET_SHA256)
    freeze_path = tmp_path / "detector-freeze.private.json"
    freeze_path.write_text(json.dumps({"schema": "yolo26n-v26-detector-freeze-v1", "status": "V26_DETECTOR_FROZEN_DEVELOPMENT_ONLY",
                                       "checkpoint_sha256": SHA_B}))
    out = run_freeze_roles(attempt=attempt, freeze_manifest=freeze_path, freeze_cutoff_utc="2026-08-21T13:00:00Z",
                           seed="v27-role-freeze-v1", test_sheet_sha256=TEST_SHEET_SHA256)
    private = attempt / "roles" / "role-freeze.private.json"
    doc = json.loads(private.read_text())
    assert doc["schema"] == "yolo26n-v27-c500g-role-freeze-v1"
    assert doc["freeze_cutoff_source"]["origin"] == "explicit" and len(doc["freeze_cutoff_source"]["freeze_manifest_sha256"]) == 64
    assert doc["camera_night_counts"]["v26_holdout"] == 3 and out["status"] in ("V27_ROLE_FREEZE_READY", "V27_VAL_SHORTAGE")
    assert "rows" not in out["summary"] and set(out["summary"]) >= {"status", "camera_night_counts", "date_blocks", "freeze_cutoff_utc"}
    assert out["summary"]["date_blocks"]["holdout"] == ["2026-08-22"]  # cutoff 08-21T13:00Z(22:00 KST) 이후 첫 완비 밤


def test_run_freeze_roles_refuses_test_sheet_pin_mismatch(fake_bundle, fake_r2, fake_db, attempt, tmp_path):
    run_inventory(local_root=fake_bundle.root, r2_reader=fake_r2, db_reader=fake_db, attempt=attempt,
                  camera_keys=["cam01", "cam02", "cam03"], nights=_nights(), test_sheet_sha256=TEST_SHEET_SHA256)
    freeze_path = tmp_path / "f.json"
    freeze_path.write_text(json.dumps({"schema": "yolo26n-v26-detector-freeze-v1", "checkpoint_sha256": SHA_B}))
    other_sheet = "c" * 64  # inventory 에 핀된 값(TEST_SHEET_SHA256)과 다른 SHA
    assert other_sheet != TEST_SHEET_SHA256
    with pytest.raises(ValueError, match="TEST-SHEET"):
        run_freeze_roles(attempt=attempt, freeze_manifest=freeze_path, freeze_cutoff_utc="2026-08-21T13:00:00Z",
                         seed="s", test_sheet_sha256=other_sheet)


def test_env_file_path_prefers_explicit_override(monkeypatch, tmp_path):
    from scripts.yolo26n_v27_c500g.cli import env_file_path

    monkeypatch.delenv("PETCAM_ENV_FILE", raising=False)
    assert env_file_path().name == ".env"
    monkeypatch.setenv("PETCAM_ENV_FILE", str(tmp_path / "other.env"))
    assert env_file_path() == tmp_path / "other.env"


def test_cli_main_rejects_missing_attempt_argument(cli_runner):
    result = cli_runner("inventory")
    assert result.exit_code != 0
    assert "attempt" in (result.stderr + result.stdout)
