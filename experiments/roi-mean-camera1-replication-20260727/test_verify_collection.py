"""Fail-closed unit tests for the camera_1 roi_mean collection verifier.

실험 디렉토리 이름에 하이픈이 있어 일반 import가 안 되므로
importlib.util.spec_from_file_location 로 모듈을 로드한다.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parent / "verify_collection.py"
_spec = importlib.util.spec_from_file_location("verify_collection", _MODULE_PATH)
verify_collection = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_collection)


# --- fixtures -------------------------------------------------------------

def _valid_freeze() -> dict:
    return {
        "schema_version": "roi-camera1-freeze-v1",
        "frozen_at_utc": "2026-07-27T00:00:00+00:00",
        "future_cutoff_utc": "2026-07-27T00:00:00+00:00",
        "target_camera_group": "camera_1",
        "target_camera_count": 1,
        "prior_target_owner_eligible_count": 71,
        "prior_owner_eligible_count": 172,
    }


def _valid_status() -> dict:
    return {
        "schema_version": "roi-camera1-collection-v1",
        "snapshot_at_utc": "2026-07-27T00:00:01+00:00",
        "future_cutoff_utc": "2026-07-27T00:00:00+00:00",
        "target_camera_group": "camera_1",
        "prior_target_owner_eligible_count": 71,
        "future": {
            "owner_completed_clips": 0,
            "evidence_ready_clips": 0,
            "provenance_mismatch_clips": 0,
            "excluded_class_clips": 0,
            "camera_nights": 0,
            "moving": {"clips": 0, "episodes": 0, "camera_nights": 0},
            "static_only": {"clips": 0, "episodes": 0, "camera_nights": 0},
        },
        "coverage": {
            "evidence_ready_fraction": None,
            "provenance_contract_count": 0,
            "frozen_provenance_contract_count": 1,
            "future_provenance_contract_match": True,
        },
        "minimum_met": False,
        "verdict": "ROI_CAMERA1_REPLICATION_COLLECTING",
    }


def _minimum_met_status() -> dict:
    """모든 최소표본을 채운 상태 (여섯 predicate 전부 True)."""
    status = _valid_status()
    status["future"] = {
        "owner_completed_clips": 60,
        "evidence_ready_clips": 60,
        "provenance_mismatch_clips": 0,
        "excluded_class_clips": 0,
        "camera_nights": 3,
        "moving": {"clips": 30, "episodes": 20, "camera_nights": 2},
        "static_only": {"clips": 30, "episodes": 20, "camera_nights": 2},
    }
    status["coverage"] = {
        "evidence_ready_fraction": 1.0,
        "provenance_contract_count": 1,
        "frozen_provenance_contract_count": 1,
        "future_provenance_contract_match": True,
    }
    return status


_FINGERPRINT_ROWS = [
    ("clip_prelabels", "8618", "b096800ebc3914497497f6d0beed1116"),
    ("clip_python_evidence_runs", "4665", "6244b1d2364b8b4bf5ad820447091663"),
    ("motion_clip_labeling_session_revisions", "0", "d41d8cd98f00b204e9800998ecf8427e"),
    ("motion_clip_labeling_sessions", "174", "2e61ae2dbb15f252532c34400aa2a34e"),
    ("motion_clip_labeling_triage", "337", "ccfb59f9cd098b328a018cd7c8b9a0a5"),
    ("motion_clips", "18080", "1541166794ccb81551757634800e43cb"),
]


def _write_fingerprint(path: Path, rows, snapshot: str) -> None:
    lines = ["snapshot_at_utc,table_name,row_count,ordered_fingerprint_md5"]
    for table, count, md5 in rows:
        lines.append(f"{snapshot},{table},{count},{md5}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_valid_root(root: Path) -> None:
    (root / "freeze-manifest.json").write_text(json.dumps(_valid_freeze()), encoding="utf-8")
    (root / "collection-status.json").write_text(json.dumps(_valid_status()), encoding="utf-8")
    _write_fingerprint(root / "fingerprints-start.csv", _FINGERPRINT_ROWS, "2026-07-27T00:00:00Z")
    _write_fingerprint(root / "fingerprints-end.csv", _FINGERPRINT_ROWS, "2026-07-27T00:02:00Z")


# --- tests ----------------------------------------------------------------

def test_valid_collecting_artifacts_pass(tmp_path: Path) -> None:
    _write_valid_root(tmp_path)
    verify_collection.verify(tmp_path)  # 예외 없이 통과해야 한다


def test_rejects_cutoff_mismatch() -> None:
    status = _valid_status()
    status["future_cutoff_utc"] = "2026-07-27T09:00:00+00:00"
    with pytest.raises(ValueError, match="cutoff_mismatch"):
        verify_collection.validate_collection(_valid_freeze(), status)


def test_rejects_camera_identity_drift() -> None:
    status = _valid_status()
    status["prior_target_owner_eligible_count"] = 70
    with pytest.raises(ValueError, match="camera_identity_drift"):
        verify_collection.validate_collection(_valid_freeze(), status)


def test_rejects_minimum_met_marked_collecting() -> None:
    status = _minimum_met_status()
    status["minimum_met"] = True
    status["verdict"] = "ROI_CAMERA1_REPLICATION_COLLECTING"
    with pytest.raises(ValueError, match="verdict_mismatch"):
        verify_collection.validate_collection(_valid_freeze(), status)


def test_rejects_feature_value_before_sample_lock() -> None:
    status = _valid_status()
    status["future"]["moving"]["roi_mean_median"] = 0.42
    with pytest.raises(ValueError, match="prelock_result_leak"):
        verify_collection.validate_collection(_valid_freeze(), status)


def test_rejects_frozen_provenance_contract_drift() -> None:
    # frozen contract 는 이전 172 cohort 기준 정확히 1개여야 한다.
    status = _valid_status()
    status["coverage"]["frozen_provenance_contract_count"] = 2
    with pytest.raises(ValueError, match="provenance_contract_drift"):
        verify_collection.validate_collection(_valid_freeze(), status)


def test_rejects_inconsistent_provenance_match_flag() -> None:
    # future_provenance_contract_match 는 provenance_mismatch_clips==0 과 일치해야 한다.
    status = _valid_status()
    status["future"]["provenance_mismatch_clips"] = 3
    status["coverage"]["future_provenance_contract_match"] = True
    with pytest.raises(ValueError, match="provenance_contract_drift"):
        verify_collection.validate_collection(_valid_freeze(), status)


def test_rejects_future_ready_provenance_exceeds_frozen() -> None:
    # future ready provenance tuple 은 frozen 집합의 부분집합이어야 한다.
    status = _minimum_met_status()
    status["coverage"]["provenance_contract_count"] = 2
    status["coverage"]["frozen_provenance_contract_count"] = 1
    with pytest.raises(ValueError, match="provenance_contract_drift"):
        verify_collection.validate_collection(_valid_freeze(), status)


def test_rejects_source_mutation(tmp_path: Path) -> None:
    _write_fingerprint(tmp_path / "start.csv", _FINGERPRINT_ROWS, "2026-07-27T00:00:00Z")
    mutated = list(_FINGERPRINT_ROWS)
    mutated[5] = ("motion_clips", "18081", "1541166794ccb81551757634800e43cb")
    _write_fingerprint(tmp_path / "end.csv", mutated, "2026-07-27T00:02:00Z")
    with pytest.raises(ValueError, match="source_mutation"):
        verify_collection.validate_fingerprints(tmp_path / "start.csv", tmp_path / "end.csv")


def test_requires_exact_six_fingerprint_tables(tmp_path: Path) -> None:
    five = [row for row in _FINGERPRINT_ROWS if row[0] != "clip_prelabels"]
    _write_fingerprint(tmp_path / "start.csv", five, "2026-07-27T00:00:00Z")
    _write_fingerprint(tmp_path / "end.csv", five, "2026-07-27T00:02:00Z")
    with pytest.raises(ValueError, match="fingerprint_scope"):
        verify_collection.validate_fingerprints(tmp_path / "start.csv", tmp_path / "end.csv")


def test_accepts_select_only_sql(tmp_path: Path) -> None:
    sql = tmp_path / "q.sql"
    sql.write_text(
        "-- comment\nWITH x AS (SELECT 1 AS a)\nSELECT a FROM x;\n", encoding="utf-8"
    )
    verify_collection.validate_select_only(sql)  # 예외 없이 통과


def test_rejects_write_sql(tmp_path: Path) -> None:
    sql = tmp_path / "q.sql"
    sql.write_text(
        "SELECT 1;\n" + "DELETE" + " FROM public.motion_clips;\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="sql_not_select_only"):
        verify_collection.validate_select_only(sql)


def test_rejects_non_select_leading_statement(tmp_path: Path) -> None:
    sql = tmp_path / "q.sql"
    sql.write_text(
        "TRUNCATE" + " public.clip_prelabels;\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="sql_not_select_only"):
        verify_collection.validate_select_only(sql)


def test_rejects_raw_uuid_email_url_r2_key_and_note_key(tmp_path: Path) -> None:
    cases = {
        "uuid": {"x": "123e4567-e89b-12d3-a456-426614174000"},
        "email": {"x": "someone@example.com"},
        "url": {"x": "https://example.com/thing"},
        "r2_key": {"r2_key": "clips/whatever"},
        "note": {"note": "라벨러 메모"},
    }
    for name, payload in cases.items():
        case_dir = tmp_path / name
        case_dir.mkdir()
        (case_dir / "collection-status.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="sensitive_artifact"):
            verify_collection.scan_sensitive_text(case_dir)
