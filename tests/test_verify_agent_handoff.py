import subprocess
from pathlib import Path

import pytest

from scripts.verify_agent_handoff import (
    HandoffError,
    main,
    parse_manifest,
    validate_handoff,
)


def write_manifest(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def valid_manifest_text(
    *, overrides: dict[str, str] | None = None, extra_lines: list[str] | None = None
) -> str:
    values = {
        "handoff_version": "1",
        "task_id": "test-task",
        "execution_repo": "/tmp/test-repo",
        "plan_path": "/tmp/test-repo/docs/plan.md",
        "design_path": "/tmp/test-repo/specs/design.md",
        "commit_sha": "0" * 40,
        "implementation_host": "dev-mac.local",
        "runtime_kind": "none",
    }
    values.update(overrides or {})
    lines = ["---", *(f"{key}: {value}" for key, value in values.items())]
    lines.extend(extra_lines or [])
    lines.extend(["---", "# Handoff"])
    return "\n".join(lines) + "\n"


def error_code(path: Path) -> str:
    with pytest.raises(HandoffError) as caught:
        parse_manifest(path)
    return caught.value.code


def test_parse_manifest_accepts_runtime_none() -> None:
    manifest = parse_manifest_text(valid_manifest_text())
    assert manifest.task_id == "test-task"
    assert manifest.runtime_kind == "none"
    assert manifest.runtime_host is None
    assert manifest.runtime_label is None


def parse_manifest_text(text: str):
    """Parser의 파일 경계를 유지하면서 간단한 성공 fixture를 제공해."""
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "handoff.md"
        path.write_text(text, encoding="utf-8")
        return parse_manifest(path)


def test_parse_manifest_accepts_launchagent_runtime() -> None:
    manifest = parse_manifest_text(
        valid_manifest_text(
            overrides={
                "runtime_kind": "launchagent",
                "runtime_host": "mac-mini.local",
                "runtime_label": "com.petcam.worker",
            }
        )
    )
    assert manifest.runtime_host == "mac-mini.local"
    assert manifest.runtime_label == "com.petcam.worker"


def test_parse_manifest_accepts_oneshot_runtime() -> None:
    # local VLM evidence 벤치마크처럼 상주 server/launchagent 가 아닌 1회성 프로세스 runtime.
    manifest = parse_manifest_text(
        valid_manifest_text(
            overrides={
                "runtime_kind": "oneshot",
                "runtime_host": "baeg-endeuui-Macmini.local",
                "runtime_label": "none",
            }
        )
    )
    assert manifest.runtime_kind == "oneshot"
    assert manifest.runtime_host == "baeg-endeuui-Macmini.local"
    assert manifest.runtime_label == "none"


def test_parse_manifest_rejects_missing_file(tmp_path: Path) -> None:
    assert error_code(tmp_path / "missing.md") == "manifest_missing"


def test_parse_manifest_rejects_missing_front_matter(tmp_path: Path) -> None:
    path = write_manifest(tmp_path / "handoff.md", "# no header\n")
    assert error_code(path) == "manifest_invalid"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"handoff_version": "2"}, "unsupported_version"),
        ({"task_id": ""}, "required_field_missing"),
        ({"runtime_kind": "mystery"}, "invalid_runtime_kind"),
        ({"commit_sha": "short"}, "invalid_commit_sha"),
        ({"execution_repo": "relative/repo"}, "manifest_invalid"),
        ({"implementation_host": "bad host"}, "manifest_invalid"),
    ],
)
def test_parse_manifest_rejects_invalid_scalar_contracts(
    tmp_path: Path, overrides: dict[str, str], code: str
) -> None:
    path = write_manifest(
        tmp_path / f"{code}.md", valid_manifest_text(overrides=overrides)
    )
    assert error_code(path) == code


@pytest.mark.parametrize(
    ("extra_line", "code"),
    [
        ("mystery: value", "unexpected_field"),
        ("task_id: duplicate", "manifest_invalid"),
        ("nested:", "manifest_invalid"),
        ("- list", "manifest_invalid"),
    ],
)
def test_parse_manifest_rejects_unknown_duplicate_or_nested_fields(
    tmp_path: Path, extra_line: str, code: str
) -> None:
    path = write_manifest(
        tmp_path / f"{code}.md",
        valid_manifest_text(extra_lines=[extra_line]),
    )
    assert error_code(path) == code


@pytest.mark.parametrize("missing", ["runtime_host", "runtime_label"])
def test_parse_manifest_requires_launchagent_runtime_fields(
    tmp_path: Path, missing: str
) -> None:
    overrides = {
        "runtime_kind": "launchagent",
        "runtime_host": "mac-mini.local",
        "runtime_label": "com.petcam.worker",
    }
    overrides.pop(missing)
    path = write_manifest(tmp_path / f"{missing}.md", valid_manifest_text(overrides=overrides))
    expected = "runtime_host_missing" if missing == "runtime_host" else "runtime_label_missing"
    assert error_code(path) == expected


def test_parse_manifest_forbids_runtime_fields_for_none(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "handoff.md",
        valid_manifest_text(overrides={"runtime_host": "mac-mini.local"}),
    )
    assert error_code(path) == "runtime_field_forbidden"


def test_parse_manifest_forbids_empty_runtime_fields_for_none(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "handoff.md",
        valid_manifest_text(overrides={"runtime_host": "", "runtime_label": ""}),
    )
    assert error_code(path) == "runtime_field_forbidden"


def test_parse_manifest_rejects_control_characters(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path / "handoff.md",
        valid_manifest_text(overrides={"implementation_host": "mac\x00name"}),
    )
    assert error_code(path) == "manifest_invalid"


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def committed_repo(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    repo = tmp_path / "worker-repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    plan = repo / "docs" / "plan.md"
    design = repo / "specs" / "design.md"
    plan.parent.mkdir()
    design.parent.mkdir()
    plan.write_text("# Plan\n", encoding="utf-8")
    design.write_text("# Design\n", encoding="utf-8")
    git(repo, "add", "docs/plan.md", "specs/design.md")
    git(repo, "commit", "-m", "test fixture")
    return repo, plan, design, git(repo, "rev-parse", "HEAD")


def repo_manifest_text(
    repo: Path,
    plan: Path,
    design: Path,
    sha: str,
    *,
    runtime_kind: str = "none",
    runtime_host: str | None = None,
    runtime_label: str | None = None,
) -> str:
    overrides = {
        "execution_repo": str(repo),
        "plan_path": str(plan),
        "design_path": str(design),
        "commit_sha": sha,
        "runtime_kind": runtime_kind,
    }
    if runtime_host is not None:
        overrides["runtime_host"] = runtime_host
    if runtime_label is not None:
        overrides["runtime_label"] = runtime_label
    return valid_manifest_text(overrides=overrides)


def validate_error(path: Path) -> str:
    with pytest.raises(HandoffError) as caught:
        validate_handoff(path)
    return caught.value.code


def test_validate_handoff_accepts_clean_tracked_artifacts(tmp_path: Path) -> None:
    repo, plan, design, sha = committed_repo(tmp_path)
    manifest = write_manifest(
        tmp_path / "handoff.md",
        repo_manifest_text(
            repo,
            plan,
            design,
            sha,
            runtime_kind="launchagent",
            runtime_host="mac-mini.local",
            runtime_label="com.petcam.worker",
        ),
    )
    summary = validate_handoff(manifest)
    assert summary.commit_short == sha[:8]
    assert summary.repo_name == "worker-repo"
    assert summary.runtime == "launchagent@mac-mini.local"


def test_validate_handoff_accepts_runtime_none(tmp_path: Path) -> None:
    repo, plan, design, sha = committed_repo(tmp_path)
    manifest = write_manifest(
        tmp_path / "handoff.md", repo_manifest_text(repo, plan, design, sha)
    )
    assert validate_handoff(manifest).runtime == "none"


def test_validate_handoff_rejects_missing_repo(tmp_path: Path) -> None:
    repo, plan, design, sha = committed_repo(tmp_path)
    missing = tmp_path / "missing-repo"
    manifest = write_manifest(
        tmp_path / "handoff.md",
        repo_manifest_text(missing, plan, design, sha),
    )
    assert validate_error(manifest) == "repo_missing"


def test_validate_handoff_rejects_non_root_repo_path(tmp_path: Path) -> None:
    repo, plan, design, sha = committed_repo(tmp_path)
    manifest = write_manifest(
        tmp_path / "handoff.md",
        repo_manifest_text(repo / "docs", plan, design, sha),
    )
    assert validate_error(manifest) == "repo_not_git_root"


def test_validate_handoff_rejects_symlink_repo(tmp_path: Path) -> None:
    repo, plan, design, sha = committed_repo(tmp_path)
    linked = tmp_path / "linked-repo"
    linked.symlink_to(repo, target_is_directory=True)
    manifest = write_manifest(
        tmp_path / "handoff.md", repo_manifest_text(linked, plan, design, sha)
    )
    assert validate_error(manifest) == "repo_not_git_root"


@pytest.mark.parametrize(("artifact", "code"), [("plan", "plan_missing"), ("design", "design_missing")])
def test_validate_handoff_rejects_missing_artifact(
    tmp_path: Path, artifact: str, code: str
) -> None:
    repo, plan, design, sha = committed_repo(tmp_path)
    missing = repo / f"missing-{artifact}.md"
    manifest = write_manifest(
        tmp_path / "handoff.md",
        repo_manifest_text(
            repo,
            missing if artifact == "plan" else plan,
            missing if artifact == "design" else design,
            sha,
        ),
    )
    assert validate_error(manifest) == code


def test_validate_handoff_rejects_artifact_outside_repo(tmp_path: Path) -> None:
    repo, _plan, design, sha = committed_repo(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    manifest = write_manifest(
        tmp_path / "handoff.md", repo_manifest_text(repo, outside, design, sha)
    )
    assert validate_error(manifest) == "artifact_outside_repo"


def test_validate_handoff_rejects_symlink_artifact(tmp_path: Path) -> None:
    repo, plan, design, sha = committed_repo(tmp_path)
    linked = repo / "docs" / "linked.md"
    linked.symlink_to(plan)
    manifest = write_manifest(
        tmp_path / "handoff.md", repo_manifest_text(repo, linked, design, sha)
    )
    assert validate_error(manifest) == "artifact_symlink"


@pytest.mark.parametrize("staged", [False, True])
def test_validate_handoff_rejects_untracked_or_staged_only_plan(
    tmp_path: Path, staged: bool
) -> None:
    repo, _plan, design, sha = committed_repo(tmp_path)
    plan = repo / "docs" / "new-plan.md"
    plan.write_text("new", encoding="utf-8")
    if staged:
        git(repo, "add", "docs/new-plan.md")
    manifest = write_manifest(
        tmp_path / "handoff.md", repo_manifest_text(repo, plan, design, sha)
    )
    assert validate_error(manifest) == "artifact_untracked"


def test_validate_handoff_rejects_artifact_absent_from_commit(tmp_path: Path) -> None:
    repo, _plan, design, old_sha = committed_repo(tmp_path)
    plan = repo / "docs" / "new-plan.md"
    plan.write_text("new", encoding="utf-8")
    git(repo, "add", "docs/new-plan.md")
    git(repo, "commit", "-m", "new plan")
    manifest = write_manifest(
        tmp_path / "handoff.md", repo_manifest_text(repo, plan, design, old_sha)
    )
    assert validate_error(manifest) == "artifact_not_in_commit"


def test_validate_handoff_rejects_head_mismatch(tmp_path: Path) -> None:
    repo, plan, design, old_sha = committed_repo(tmp_path)
    note = repo / "note.txt"
    note.write_text("later", encoding="utf-8")
    git(repo, "add", "note.txt")
    git(repo, "commit", "-m", "later commit")
    manifest = write_manifest(
        tmp_path / "handoff.md", repo_manifest_text(repo, plan, design, old_sha)
    )
    assert validate_error(manifest) == "head_mismatch"


def test_validate_handoff_rejects_dirty_artifact(tmp_path: Path) -> None:
    repo, plan, design, sha = committed_repo(tmp_path)
    plan.write_text("changed", encoding="utf-8")
    manifest = write_manifest(
        tmp_path / "handoff.md", repo_manifest_text(repo, plan, design, sha)
    )
    assert validate_error(manifest) == "artifact_dirty"


@pytest.mark.parametrize("broken_command", ["ls-files", "ls-tree"])
def test_validate_handoff_reports_git_probe_failure_instead_of_artifact_state(
    tmp_path: Path, broken_command: str
) -> None:
    repo, plan, design, sha = committed_repo(tmp_path)
    manifest = write_manifest(
        tmp_path / "handoff.md", repo_manifest_text(repo, plan, design, sha)
    )

    def broken_runner(args, **kwargs):
        if broken_command in args:
            return subprocess.CompletedProcess(args, 128, "", "private git error")
        return subprocess.run(args, **kwargs)

    with pytest.raises(HandoffError) as caught:
        validate_handoff(manifest, runner=broken_runner)
    assert caught.value.code == "git_probe_failed"


def test_main_prints_only_allowlisted_missing_manifest_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret_path = tmp_path / "Users" / "private-name" / "missing.md"
    rc = main(["--manifest", str(secret_path)])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == "HANDOFF_FAIL code=manifest_missing\n"
    assert captured.err == ""
    assert "private-name" not in captured.out


def test_main_prints_safe_success_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, plan, design, sha = committed_repo(tmp_path)
    manifest = write_manifest(
        tmp_path / "handoff.md", repo_manifest_text(repo, plan, design, sha)
    )
    assert main(["--manifest", str(manifest)]) == 0
    assert capsys.readouterr().out == (
        f"HANDOFF_OK task=test-task repo=worker-repo "
        f"commit={sha[:8]} runtime=none\n"
    )


def test_main_hides_git_stderr_and_repo_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "private-repo-name"
    repo.mkdir()
    plan = repo / "plan.md"
    design = repo / "design.md"
    plan.write_text("plan", encoding="utf-8")
    design.write_text("design", encoding="utf-8")
    manifest = write_manifest(
        tmp_path / "handoff.md",
        repo_manifest_text(repo, plan, design, "0" * 40),
    )
    assert main(["--manifest", str(manifest)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "HANDOFF_FAIL code=git_probe_failed\n"
    assert "private-repo-name" not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize("option", ["--allow-untracked", "--force", "--skip-git-check"])
def test_main_rejects_bypass_options(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    option: str,
) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--manifest", str(tmp_path / "handoff.md"), option])
    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert "unrecognized arguments" in captured.err


def test_agent_rules_require_handoff_validator() -> None:
    agents = Path("AGENTS.md").read_text(encoding="utf-8")
    claude = Path("CLAUDE.md").read_text(encoding="utf-8")
    required = (
        "scripts/verify_agent_handoff.py",
        "execution_repo",
        "implementation_host",
        "runtime_host",
        "HANDOFF_OK",
    )
    for marker in required:
        assert marker in agents
        assert marker in claude


def test_handoff_template_contains_required_manifest_fields() -> None:
    template = Path("docs/handoff-prompts/_agent-task-handoff-template.md").read_text(
        encoding="utf-8"
    )
    for field in (
        "handoff_version:",
        "task_id:",
        "execution_repo:",
        "plan_path:",
        "design_path:",
        "commit_sha:",
        "implementation_host:",
        "runtime_kind:",
        "runtime_host:",
        "runtime_label:",
    ):
        assert field in template
    assert "--allow-untracked" not in template
    assert "--skip-git-check" not in template


def test_current_sot_does_not_claim_mac_mini_vlm_candidate_verified() -> None:
    sot = Path("specs/next-session.md").read_text(encoding="utf-8")
    assert "야간 VLM 후보 shadow — host attribution 정정" in sot
    assert "정규 candidate LaunchAgent는 MacBook에서 발견" in sot
    assert "Mac mini verified 아님" in sot
    assert "Mac mini의 `com.petcam.vlm-candidate-worker`가" not in sot


def test_vlm_handoff_records_tracked_bootstrap_recovery() -> None:
    handoff = Path(
        "docs/superpowers/plans/2026-07-16-vlm-single-host-operations-hardening.md"
    ).read_text(encoding="utf-8")
    assert "Bootstrap 복구 완료" in handoff
    assert "artifact_untracked" not in handoff
    assert "HANDOFF_OK" in handoff
    assert "execution_repo: /Users/baek/petcam-nightly-reporter" in handoff
    assert "runtime_host: baeg-endeuui-Macmini.local" in handoff
    assert "Mac mini 배포·실행 완료를 뜻하지 않는다" in handoff
