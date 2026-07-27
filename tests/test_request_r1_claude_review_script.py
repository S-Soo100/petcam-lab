from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_SOURCE = REPO_ROOT / "scripts/request-r1-runtime-review-from-claude.sh"
REQUEST_SOURCE = (
    REPO_ROOT
    / "docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-foundation-claude-review.md"
)
NEXT_SESSION = REPO_ROOT / "specs/next-session.md"
RBA_SYSTEM_DESIGN = (
    REPO_ROOT
    / "docs/superpowers/specs/2026-07-27-rba-research-system-v1-design.md"
)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _make_review_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "docs/handoff-prompts").mkdir(parents=True)
    shutil.copy2(SCRIPT_SOURCE, repo / "scripts/request-r1-runtime-review-from-claude.sh")
    shutil.copy2(
        REQUEST_SOURCE,
        repo
        / "docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-foundation-claude-review.md",
    )

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "test fixture"], cwd=repo, check=True)

    args_file = tmp_path / "claude-args.txt"
    stub = tmp_path / "claude-stub"
    _write_executable(
        stub,
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$@" > "$CLAUDE_ARGS_FILE"
printf '# Claude R1 review\\n\\nR1_DESIGN_REVIEW_APPROVE\\n'
""",
    )
    return repo, args_file


def test_review_script_writes_report_and_uses_read_only_claude(tmp_path: Path) -> None:
    repo, args_file = _make_review_repo(tmp_path)
    env = {
        **os.environ,
        "CLAUDE_BIN": str(tmp_path / "claude-stub"),
        "CLAUDE_ARGS_FILE": str(args_file),
    }

    completed = subprocess.run(
        ["bash", "scripts/request-r1-runtime-review-from-claude.sh"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report = (
        repo
        / "docs/handoff-prompts/"
        "2026-07-28-r1-mac-mini-runtime-foundation-claude-review-report.md"
    )
    assert report.read_text(encoding="utf-8").endswith("R1_DESIGN_REVIEW_APPROVE\n")

    args = args_file.read_text(encoding="utf-8").splitlines()
    assert "--model" in args
    assert "opus" in args
    assert "--effort" in args
    assert "high" in args
    assert "--tools" in args
    assert "Read,Glob,Grep" in args
    assert "Write" not in args
    assert "Edit" not in args
    assert "Bash" not in args


def test_review_script_rejects_modified_request_document(tmp_path: Path) -> None:
    repo, args_file = _make_review_repo(tmp_path)
    request = (
        repo
        / "docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-foundation-claude-review.md"
    )
    request.write_text(request.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    env = {
        **os.environ,
        "CLAUDE_BIN": str(tmp_path / "claude-stub"),
        "CLAUDE_ARGS_FILE": str(args_file),
    }

    completed = subprocess.run(
        ["bash", "scripts/request-r1-runtime-review-from-claude.sh"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "review_request_not_committed" in completed.stderr
    assert not args_file.exists()


def test_r1_review_sources_record_verified_operating_contract() -> None:
    next_session = NEXT_SESSION.read_text(encoding="utf-8")
    rba_design = RBA_SYSTEM_DESIGN.read_text(encoding="utf-8")

    assert "AI_OPERATING_CONTRACT_V1_VERIFIED" in next_session
    assert "AI_OPERATING_CONTRACT_V1_VERIFIED" in rba_design
    assert "AI_OPERATING_CONTRACT_IMPLEMENTED_AWAITING_FINAL_REVIEW" not in next_session
    assert "IMPLEMENTED_AWAITING_FINAL_REVIEW" not in rba_design
