from __future__ import annotations

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


def assert_raw_ignored(root: Path) -> None:
    ignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    if "/raw/" not in ignore:
        raise ValueError("raw_not_ignored")


def assert_no_sensitive_tracked_content(root: Path) -> None:
    for path in root.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in SENSITIVE_TOKENS):
            raise ValueError(f"sensitive_tracked_content {path.name}")
