"""Fail-closed verifier for the camera_1 raw roi_mean future-replication kickoff.

이 스크립트는 kickoff 산출물(freeze manifest, collection status, 6-table
fingerprint)이 동결 계약과 read-only/mutation 계약을 지켰는지 검사한다. 표준
라이브러리만 사용하고, 위반이 있으면 구체적 코드가 담긴 ValueError를 올린다.

결과 값(roi_mean, AUROC, CI 등)은 sample lock 이후 별도 분석 단계의 몫이며 이
kickoff 산출물에는 존재하면 안 된다. 그래서 결과 key가 보이면 즉시 실패한다.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 시작·종료 fingerprint 는 정확히 이 6개 table 만 비교한다.
EXPECTED_TABLES = {
    "motion_clips",
    "motion_clip_labeling_triage",
    "motion_clip_labeling_sessions",
    "motion_clip_labeling_session_revisions",
    "clip_python_evidence_runs",
    "clip_prelabels",
}

FREEZE_SCHEMA = "roi-camera1-freeze-v1"
STATUS_SCHEMA = "roi-camera1-collection-v1"
PRIOR_TARGET_OWNER_ELIGIBLE = 71
COLLECTING_VERDICT = "ROI_CAMERA1_REPLICATION_COLLECTING"

# sample lock 이전에는 어떤 결과/분포 값도 노출하면 안 된다. key 에 이 조각이
# 들어가면 pre-lock leak 으로 본다 (대소문자 무시).
FORBIDDEN_RESULT_FRAGMENTS = (
    "roi_mean",
    "auc",
    "ci_low",
    "ci_high",
    "median",
    "iqr",
    "threshold",
)

# 생성 artifact(.json/.csv)에서만 검사하는 원문 식별자 key (정확한 이름 일치).
FORBIDDEN_DATA_KEYS = {
    "clip_id",
    "camera_id",
    "user_id",
    "reviewed_by",
    "email",
    "note",
    "signed_url",
    "storage_key",
    "r2_key",
}

_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)


# --- collection status / freeze manifest ---------------------------------

def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("cutoff_not_utc")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("cutoff_not_utc") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("cutoff_not_utc")
    return parsed.astimezone(timezone.utc)


def _require_count(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"count_type {label}={value!r}")
    return value


def _scan_result_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            folded = key.casefold()
            if any(fragment in folded for fragment in FORBIDDEN_RESULT_FRAGMENTS):
                raise ValueError(f"prelock_result_leak {key}")
            _scan_result_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _scan_result_keys(nested)


def _minimum_predicates(future: dict) -> list[bool]:
    moving = future["moving"]
    static_only = future["static_only"]
    return [
        moving["clips"] >= 30,
        static_only["clips"] >= 30,
        moving["episodes"] >= 20,
        static_only["episodes"] >= 20,
        future["camera_nights"] >= 3,
        moving["camera_nights"] >= 2 and static_only["camera_nights"] >= 2,
    ]


def validate_collection(freeze: dict, status: dict) -> None:
    """freeze manifest 와 collection status 가 동결 계약을 지켰는지 검사한다."""
    if freeze.get("schema_version") != FREEZE_SCHEMA:
        raise ValueError(f"schema_version freeze={freeze.get('schema_version')!r}")
    if status.get("schema_version") != STATUS_SCHEMA:
        raise ValueError(f"schema_version status={status.get('schema_version')!r}")

    # cutoff 문자열은 두 파일에서 완전히 동일해야 하고 UTC tz-aware 여야 한다.
    freeze_cutoff = freeze.get("future_cutoff_utc")
    status_cutoff = status.get("future_cutoff_utc")
    if freeze_cutoff != status_cutoff:
        raise ValueError(
            f"cutoff_mismatch freeze={freeze_cutoff!r} status={status_cutoff!r}"
        )
    cutoff = _parse_utc(status_cutoff)

    # freeze manifest 자체의 frozen_at 도 cutoff 와 같은 시점이어야 한다.
    if freeze.get("frozen_at_utc") != freeze_cutoff:
        raise ValueError("cutoff_mismatch frozen_at_utc")

    snapshot = _parse_utc(status.get("snapshot_at_utc"))
    if snapshot <= cutoff:
        raise ValueError("snapshot_not_after_cutoff")

    if freeze.get("target_camera_group") != "camera_1":
        raise ValueError(f"target_camera_group freeze={freeze.get('target_camera_group')!r}")
    if status.get("target_camera_group") != "camera_1":
        raise ValueError(f"target_camera_group status={status.get('target_camera_group')!r}")

    for source in (freeze, status):
        if source.get("prior_target_owner_eligible_count") != PRIOR_TARGET_OWNER_ELIGIBLE:
            raise ValueError(
                "camera_identity_drift prior="
                f"{source.get('prior_target_owner_eligible_count')!r}"
            )
    if freeze.get("target_camera_count") != 1:
        raise ValueError(f"camera_identity_drift target_camera_count={freeze.get('target_camera_count')!r}")

    future = status["future"]
    owner_completed = _require_count(future["owner_completed_clips"], "owner_completed_clips")
    evidence_ready = _require_count(future["evidence_ready_clips"], "evidence_ready_clips")
    _require_count(future["excluded_class_clips"], "excluded_class_clips")
    _require_count(future["camera_nights"], "future.camera_nights")
    for label in ("moving", "static_only"):
        _require_count(future[label]["clips"], f"{label}.clips")
        _require_count(future[label]["episodes"], f"{label}.episodes")
        _require_count(future[label]["camera_nights"], f"{label}.camera_nights")
    _require_count(status["coverage"]["provenance_contract_count"], "provenance_contract_count")

    if evidence_ready > owner_completed:
        raise ValueError(
            f"coverage_bound evidence_ready={evidence_ready} owner_completed={owner_completed}"
        )

    # 결과/분포 key 누출 검사 (sample lock 이전).
    _scan_result_keys(status)

    # minimum_met 는 동결된 6개 predicate 와 정확히 일치해야 한다.
    computed_minimum = all(_minimum_predicates(future))
    stated_minimum = status["minimum_met"]
    if stated_minimum is not computed_minimum:
        raise ValueError(
            f"verdict_mismatch minimum_met={stated_minimum!r} computed={computed_minimum!r}"
        )
    if status["verdict"] == COLLECTING_VERDICT and stated_minimum is not False:
        raise ValueError("verdict_mismatch collecting_requires_minimum_false")


# --- source fingerprints --------------------------------------------------

def _load_fingerprint(path: Path) -> dict[str, tuple[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        expected_columns = {
            "snapshot_at_utc",
            "table_name",
            "row_count",
            "ordered_fingerprint_md5",
        }
        if set(reader.fieldnames or []) != expected_columns:
            raise ValueError(f"fingerprint_scope columns={reader.fieldnames!r}")
        rows: dict[str, tuple[str, str]] = {}
        for row in reader:
            table = row["table_name"]
            if table in rows:
                raise ValueError(f"fingerprint_scope duplicate={table}")
            rows[table] = (row["row_count"], row["ordered_fingerprint_md5"])
        return rows


def validate_fingerprints(start_path: Path, end_path: Path) -> None:
    """시작·종료 6-table fingerprint 가 정확히 6개 table 이고 동일한지 검사한다."""
    start = _load_fingerprint(start_path)
    end = _load_fingerprint(end_path)
    for label, table_set in (("start", set(start)), ("end", set(end))):
        if table_set != EXPECTED_TABLES:
            missing = sorted(EXPECTED_TABLES - table_set)
            extra = sorted(table_set - EXPECTED_TABLES)
            raise ValueError(
                f"fingerprint_scope {label} missing={missing} extra={extra}"
            )
    changed = sorted(table for table in EXPECTED_TABLES if start[table] != end[table])
    if changed:
        raise ValueError("source_mutation " + ",".join(changed))


# --- sensitive text scan --------------------------------------------------

def _forbidden_json_keys(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.casefold() in FORBIDDEN_DATA_KEYS:
                return True
            if _forbidden_json_keys(nested):
                return True
    elif isinstance(value, list):
        return any(_forbidden_json_keys(nested) for nested in value)
    return False


def scan_sensitive_text(root: Path) -> None:
    """생성 artifact(.json/.csv)에서 UUID/email/URL/원문 식별자 key 를 거부한다.

    SQL 계약(.sql)은 DB column 이름을 포함하므로 검사하지 않고, .md 는 UUID/email
    누출만 확인한다. verifier/test 코드(.py)는 검사 대상이 아니다.
    """
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in {".json", ".csv", ".md"}:
            continue
        text = path.read_text(encoding="utf-8")
        if _UUID.search(text) or _EMAIL.search(text):
            raise ValueError(f"sensitive_artifact {path.name}")
        if suffix in {".json", ".csv"} and _URL.search(text):
            raise ValueError(f"sensitive_artifact {path.name}:url")
        if suffix == ".json":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if _forbidden_json_keys(parsed):
                raise ValueError(f"sensitive_artifact {path.name}:forbidden_key")
        if suffix == ".csv":
            header = text.splitlines()[0] if text.splitlines() else ""
            columns = {column.strip().casefold() for column in header.split(",")}
            if columns & FORBIDDEN_DATA_KEYS:
                raise ValueError(f"sensitive_artifact {path.name}:forbidden_column")


# --- orchestration --------------------------------------------------------

def verify(root: Path) -> None:
    freeze = json.loads((root / "freeze-manifest.json").read_text(encoding="utf-8"))
    status = json.loads((root / "collection-status.json").read_text(encoding="utf-8"))
    validate_collection(freeze, status)
    validate_fingerprints(root / "fingerprints-start.csv", root / "fingerprints-end.csv")
    scan_sensitive_text(root)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        verify(args.root)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("COLLECTION_ARTIFACTS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
