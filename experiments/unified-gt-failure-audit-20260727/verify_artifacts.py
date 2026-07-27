from __future__ import annotations

import re
from pathlib import Path


RAW_DIR_NAME = "raw"
SENSITIVE_TOKENS = (
    '"clip_id"',
    '"r2_key"',
    '"signed_url"',
    '"email"',
    '"user_id"',
    '"reviewed_by"',
    '"note"',
)
FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|merge|create|alter|drop|truncate|grant|revoke|"
    r"comment|copy|call|do|vacuum|analyze|refresh|reindex|cluster)\b",
    re.IGNORECASE,
)


def assert_raw_ignored(root: Path) -> None:
    ignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    if "/raw/" not in ignore:
        raise ValueError("raw_not_ignored")


def assert_no_sensitive_tracked_content(root: Path) -> None:
    for path in root.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in SENSITIVE_TOKENS):
            raise ValueError(f"sensitive_tracked_content {path.name}")


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", sql)


def assert_select_only_sql(sql: str) -> None:
    clean = _strip_sql_comments(sql)
    if FORBIDDEN_SQL.search(clean):
        raise ValueError("non_select_sql forbidden_keyword")
    for statement in clean.split(";"):
        statement = statement.strip()
        if statement and not re.match(r"^(with|select)\b", statement, re.IGNORECASE):
            raise ValueError("non_select_sql statement_type")
    if re.search(r"\bselect\s+\w+(?:\.\w+)+\s*\(", clean, re.IGNORECASE):
        raise ValueError("non_select_sql function_call")
