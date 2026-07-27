from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


WRITE_SQL = re.compile(
    r"\b(insert|update|delete|merge|alter|drop|truncate|create|grant|revoke|call)\b",
    re.IGNORECASE,
)
SENSITIVE_PATTERNS = {
    "uuid": re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
        re.IGNORECASE,
    ),
    "url": re.compile(r"https?://\S+", re.IGNORECASE),
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    "r2_key": re.compile(r"\b(?:terra-clips|motion-clips)/\S+", re.IGNORECASE),
}


def _strip_sql_comments(sql: str) -> str:
    without_blocks = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", without_blocks)


def validate_select_only(sql_path: Path) -> list[str]:
    if not sql_path.exists():
        return ["audit.sql missing"]
    sql = _strip_sql_comments(sql_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for index, statement in enumerate(sql.split(";"), start=1):
        statement = statement.strip()
        if not statement:
            continue
        if not re.match(r"^(select|with)\b", statement, flags=re.IGNORECASE):
            errors.append(f"statement {index} does not start with SELECT/WITH")
        match = WRITE_SQL.search(statement)
        if match:
            errors.append(f"statement {index} contains {match.group(1).upper()}")
    return errors


def validate_no_sensitive_raw(root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {
            ".md",
            ".csv",
            ".json",
            ".py",
            ".sql",
        }:
            continue
        text = path.read_text(encoding="utf-8")
        for label, pattern in SENSITIVE_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{path.name}: {label}")
    return errors


def validate_fingerprints(root: Path) -> list[str]:
    start_path = root / "fingerprints-start.csv"
    end_path = root / "fingerprints-end.csv"
    errors: list[str] = []
    if start_path.exists() != end_path.exists():
        errors.append("start/end fingerprint file pair is incomplete")

    def load(path: Path) -> dict[str, tuple[str, str]]:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = csv.DictReader(handle)
            return {
                row["table_name"]: (
                    row["row_count"],
                    row["ordered_fingerprint_md5"],
                )
                for row in rows
            }

    if start_path.exists() and end_path.exists():
        start = load(start_path)
        end = load(end_path)
        if start != end:
            changed = sorted(set(start) | set(end), key=str.casefold)
            changed = [table for table in changed if start.get(table) != end.get(table)]
            errors.append("changed tables: " + ",".join(changed))

    cohort_path = root / "cohort-fingerprints.csv"
    if cohort_path.exists():
        with cohort_path.open(encoding="utf-8", newline="") as handle:
            rows = {
                row["phase"]: (
                    row["eligible_count"],
                    row["eligible_ordered_sha256"],
                )
                for row in csv.DictReader(handle)
            }
        if set(rows) != {"start", "end"}:
            errors.append("cohort fingerprint requires start and end")
        elif rows["start"] != rows["end"]:
            errors.append("changed owner eligible cohort")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()

    sql_errors = validate_select_only(args.root / "audit.sql")
    if sql_errors:
        print("SQL_NOT_SELECT_ONLY: " + "; ".join(sql_errors), file=sys.stderr)
        return 1

    sensitive_errors = validate_no_sensitive_raw(args.root)
    if sensitive_errors:
        print("SENSITIVE_RAW_DATA: " + "; ".join(sensitive_errors), file=sys.stderr)
        return 1

    fingerprint_errors = validate_fingerprints(args.root)
    if fingerprint_errors:
        print("FINGERPRINT_MUTATION: " + "; ".join(fingerprint_errors), file=sys.stderr)
        return 1

    print("ARTIFACT_CONTRACT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
