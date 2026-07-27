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
# 이전 Owner GT 172 cohort 의 canonical provenance contract 는 benchmark 기준 정확히 1개.
# future evidence 는 이 frozen contract 에 정확히 일치할 때만 ready 로 인정한다.
FROZEN_PROVENANCE_CONTRACT_COUNT = 1
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

# write/DDL 키워드. production DB 는 SELECT-only 라 이 중 하나라도 나오면 거부한다.
_WRITE_SQL = re.compile(
    r"\b(insert|update|delete|merge|alter|create|drop|truncate|grant|revoke|call)\b",
    re.IGNORECASE,
)


# --- SQL SELECT-only 계약 --------------------------------------------------

def _strip_sql_comments(sql: str) -> str:
    without_blocks = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", without_blocks)


def validate_select_only(sql_path: Path) -> None:
    """각 statement 가 SELECT/WITH 로 시작하고 write/DDL 키워드가 없는지 검사한다."""
    sql = _strip_sql_comments(sql_path.read_text(encoding="utf-8"))
    for index, statement in enumerate(sql.split(";"), start=1):
        statement = statement.strip()
        if not statement:
            continue
        if not re.match(r"^(select|with)\b", statement, flags=re.IGNORECASE):
            raise ValueError(
                f"sql_not_select_only statement {index} does not start with SELECT/WITH"
            )
        match = _WRITE_SQL.search(statement)
        if match:
            raise ValueError(
                f"sql_not_select_only statement {index} contains {match.group(1).upper()}"
            )


def _extract_cte_body(sql: str, name: str) -> str:
    """`name AS ( ... )` CTE 본문을 balanced-paren 으로 추출한다."""
    marker = re.search(rf"\b{re.escape(name)}\s+AS\s*\(", sql, flags=re.IGNORECASE)
    if marker is None:
        raise ValueError(f"frozen_cohort_unbounded missing_cte={name}")
    depth = 1
    start = marker.end()
    index = start
    while index < len(sql) and depth > 0:
        char = sql[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        index += 1
    if depth != 0:
        raise ValueError(f"frozen_cohort_unbounded unbalanced_cte={name}")
    return sql[start : index - 1]


def assert_historical_cohort_frozen(sql: str) -> None:
    """collection-status.sql 의 historical_cohort 가 cutoff 상한으로 동결됐는지 검사한다.

    historical_cohort 에 명시적 상한(`started_at <= :'future_cutoff_utc'`)이 없으면, 같은
    frozen cutoff 로 미래에 재실행할 때 post-cutoff Owner 완료 GT 가 172 cohort 에 섞여
    prior_owner_eligible_count·target camera ranking/count·frozen provenance 가 drift 한다.
    즉 frozen 172 contract 가 실제로 frozen 이 아니게 된다. future cohort 는 반대로 하한
    (`started_at > :'future_cutoff_utc'`)을 유지해야 미래 표본만 집계한다.

    주석 안에 상한을 적어두고 실제 코드에선 빼는 우회를 막기 위해 주석을 먼저 제거한 뒤 검사한다.
    """
    sql = _strip_sql_comments(sql)
    historical = _extract_cte_body(sql, "historical_cohort")
    if not re.search(r"started_at\s*<=\s*:'future_cutoff_utc'", historical):
        raise ValueError("frozen_cohort_unbounded historical_cohort_missing_upper_cutoff")
    future = _extract_cte_body(sql, "future_owner_completed")
    if not re.search(r"started_at\s*>\s*:'future_cutoff_utc'", future):
        raise ValueError("frozen_cohort_unbounded future_missing_lower_cutoff")


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
    coverage = status["coverage"]
    owner_completed = _require_count(future["owner_completed_clips"], "owner_completed_clips")
    evidence_ready = _require_count(future["evidence_ready_clips"], "evidence_ready_clips")
    mismatch = _require_count(future["provenance_mismatch_clips"], "provenance_mismatch_clips")
    _require_count(future["excluded_class_clips"], "excluded_class_clips")
    _require_count(future["camera_nights"], "future.camera_nights")
    for label in ("moving", "static_only"):
        _require_count(future[label]["clips"], f"{label}.clips")
        _require_count(future[label]["episodes"], f"{label}.episodes")
        _require_count(future[label]["camera_nights"], f"{label}.camera_nights")
    ready_provenance = _require_count(
        coverage["provenance_contract_count"], "provenance_contract_count"
    )
    frozen_provenance = _require_count(
        coverage["frozen_provenance_contract_count"], "frozen_provenance_contract_count"
    )

    if evidence_ready > owner_completed:
        raise ValueError(
            f"coverage_bound evidence_ready={evidence_ready} owner_completed={owner_completed}"
        )

    # frozen provenance contract 는 이전 172 cohort 기준 정확히 1개여야 하고,
    # future ready provenance 는 그 frozen 집합의 부분집합이어야 하며, match flag 는
    # provenance_mismatch_clips==0 과 정확히 일치해야 한다.
    if frozen_provenance != FROZEN_PROVENANCE_CONTRACT_COUNT:
        raise ValueError(f"provenance_contract_drift frozen={frozen_provenance}")
    if ready_provenance > frozen_provenance:
        raise ValueError(
            f"provenance_contract_drift ready={ready_provenance} frozen={frozen_provenance}"
        )
    match_flag = coverage["future_provenance_contract_match"]
    if not isinstance(match_flag, bool) or match_flag != (mismatch == 0):
        raise ValueError(
            f"provenance_contract_drift match={match_flag!r} mismatch={mismatch}"
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
    for sql_path in sorted(root.glob("*.sql")):
        validate_select_only(sql_path)
    collection_sql = root / "collection-status.sql"
    if collection_sql.exists():
        assert_historical_cohort_frozen(collection_sql.read_text(encoding="utf-8"))
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
