from __future__ import annotations

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent))

import verify_artifacts  # noqa: E402


ROOT = Path(__file__).parent


def test_raw_directory_is_gitignored(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("/raw/\n", encoding="utf-8")
    verify_artifacts.assert_raw_ignored(tmp_path)


def test_rejects_missing_raw_ignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="raw_not_ignored"):
        verify_artifacts.assert_raw_ignored(tmp_path)


def test_rejects_sensitive_field_names_in_tracked_json(tmp_path: Path) -> None:
    (tmp_path / "source-summary.json").write_text(
        '{"clip_id":"00000000-0000-0000-0000-000000000000"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sensitive_tracked_content"):
        verify_artifacts.assert_no_sensitive_tracked_content(tmp_path)


def test_inventory_sql_is_select_only() -> None:
    sql = (ROOT / "inventory.sql").read_text(encoding="utf-8")
    verify_artifacts.assert_select_only_sql(sql)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO x VALUES (1)",
        "UPDATE x SET a=1",
        "DELETE FROM x",
        "CREATE TABLE x(a int)",
        "SELECT public.fn_write_something()",
    ],
)
def test_rejects_write_sql(statement: str) -> None:
    with pytest.raises(ValueError, match="non_select_sql"):
        verify_artifacts.assert_select_only_sql(statement)
