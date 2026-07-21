"""Cross-repo 작업 전달 전에 파일·Git·runtime 소유권을 검증해."""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


ALLOWED_KEYS = frozenset(
    {
        "handoff_version",
        "task_id",
        "execution_repo",
        "plan_path",
        "design_path",
        "commit_sha",
        "implementation_host",
        "runtime_kind",
        "runtime_host",
        "runtime_label",
    }
)
REQUIRED_KEYS = frozenset(
    {
        "handoff_version",
        "task_id",
        "execution_repo",
        "plan_path",
        "design_path",
        "commit_sha",
        "implementation_host",
        "runtime_kind",
    }
)
RUNTIME_KINDS = frozenset(
    {"none", "oneshot", "launchagent", "server", "scheduled-job", "mobile-build"}
)
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class HandoffError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class HandoffManifest:
    task_id: str
    execution_repo: Path
    plan_path: Path
    design_path: Path
    commit_sha: str
    implementation_host: str
    runtime_kind: str
    runtime_host: str | None
    runtime_label: str | None


@dataclass(frozen=True, slots=True)
class HandoffSummary:
    task_id: str
    repo_name: str
    commit_short: str
    runtime: str


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _read_front_matter(path: Path) -> dict[str, str]:
    if not path.exists():
        raise HandoffError("manifest_missing")
    if not path.is_file() or path.is_symlink():
        raise HandoffError("manifest_invalid")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise HandoffError("manifest_invalid") from exc
    if not lines or lines[0] != "---":
        raise HandoffError("manifest_invalid")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise HandoffError("manifest_invalid") from exc
    values: dict[str, str] = {}
    for raw_line in lines[1:end]:
        if not raw_line.strip() or ":" not in raw_line:
            raise HandoffError("manifest_invalid")
        key, value = (part.strip() for part in raw_line.split(":", 1))
        if not key:
            raise HandoffError("manifest_invalid")
        if not value and key not in ALLOWED_KEYS:
            raise HandoffError("manifest_invalid")
        if key in values:
            raise HandoffError("manifest_invalid")
        if key not in ALLOWED_KEYS:
            raise HandoffError("unexpected_field")
        values[key] = value
    return values


def _absolute_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise HandoffError("manifest_invalid")
    return path


def _safe_name(value: str) -> str:
    if not SAFE_NAME.fullmatch(value):
        raise HandoffError("manifest_invalid")
    return value


def parse_manifest(path: Path) -> HandoffManifest:
    values = _read_front_matter(path)
    if missing := {key for key in REQUIRED_KEYS if not values.get(key)}:
        del missing  # 값 자체를 오류 문자열에 노출하지 않기 위한 명시적 폐기야.
        raise HandoffError("required_field_missing")
    if values["handoff_version"] != "1":
        raise HandoffError("unsupported_version")
    if not SHA40.fullmatch(values["commit_sha"]):
        raise HandoffError("invalid_commit_sha")
    runtime_kind = values["runtime_kind"]
    if runtime_kind not in RUNTIME_KINDS:
        raise HandoffError("invalid_runtime_kind")
    runtime_host = values.get("runtime_host") or None
    runtime_label = values.get("runtime_label") or None
    if runtime_kind == "none":
        if "runtime_host" in values or "runtime_label" in values:
            raise HandoffError("runtime_field_forbidden")
    else:
        if runtime_host is None:
            raise HandoffError("runtime_host_missing")
        if runtime_label is None:
            raise HandoffError("runtime_label_missing")
        runtime_host = _safe_name(runtime_host)
        runtime_label = _safe_name(runtime_label)
    return HandoffManifest(
        task_id=_safe_name(values["task_id"]),
        execution_repo=_absolute_path(values["execution_repo"]),
        plan_path=_absolute_path(values["plan_path"]),
        design_path=_absolute_path(values["design_path"]),
        commit_sha=values["commit_sha"],
        implementation_host=_safe_name(values["implementation_host"]),
        runtime_kind=runtime_kind,
        runtime_host=runtime_host,
        runtime_label=runtime_label,
    )


def _git(
    repo: Path, args: Sequence[str], runner: Runner
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HandoffError("git_probe_failed") from exc


def _require_git_success(
    repo: Path, args: Sequence[str], runner: Runner
) -> subprocess.CompletedProcess[str]:
    completed = _git(repo, args, runner)
    if completed.returncode != 0:
        raise HandoffError("git_probe_failed")
    return completed


def _validate_repo(path: Path, runner: Runner) -> Path:
    if not path.exists() or not path.is_dir():
        raise HandoffError("repo_missing")
    if path.is_symlink():
        raise HandoffError("repo_not_git_root")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise HandoffError("repo_missing") from exc
    if path != resolved:
        raise HandoffError("repo_not_git_root")
    completed = _require_git_success(
        resolved, ["rev-parse", "--show-toplevel"], runner
    )
    try:
        git_root = Path(completed.stdout.strip()).resolve(strict=True)
    except OSError as exc:
        raise HandoffError("git_probe_failed") from exc
    if git_root != resolved:
        raise HandoffError("repo_not_git_root")
    return resolved


def _artifact_relative(repo: Path, path: Path, missing_code: str) -> Path:
    if not path.exists():
        raise HandoffError(missing_code)
    if not path.is_file():
        raise HandoffError(missing_code)
    try:
        lexical_relative = path.relative_to(repo)
    except ValueError as exc:
        raise HandoffError("artifact_outside_repo") from exc
    if ".." in lexical_relative.parts:
        raise HandoffError("artifact_outside_repo")
    current = repo
    for part in lexical_relative.parts:
        current = current / part
        if current.is_symlink():
            raise HandoffError("artifact_symlink")
    try:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(repo)
    except (OSError, ValueError) as exc:
        raise HandoffError("artifact_outside_repo") from exc
    return relative


def _validate_artifact(
    repo: Path,
    relative: Path,
    commit_sha: str,
    runner: Runner,
) -> None:
    rel = relative.as_posix()
    tracked = _git(repo, ["ls-files", "--error-unmatch", "--", rel], runner)
    if tracked.returncode == 1:
        raise HandoffError("artifact_untracked")
    if tracked.returncode != 0:
        raise HandoffError("git_probe_failed")
    committed_at_head = _require_git_success(
        repo, ["ls-tree", "-r", "--name-only", "HEAD", "--", rel], runner
    )
    if committed_at_head.stdout.strip() != rel:
        raise HandoffError("artifact_untracked")
    committed_at_requested = _require_git_success(
        repo,
        ["ls-tree", "-r", "--name-only", commit_sha, "--", rel],
        runner,
    )
    if committed_at_requested.stdout.strip() != rel:
        raise HandoffError("artifact_not_in_commit")
    status = _require_git_success(
        repo, ["status", "--porcelain", "--", rel], runner
    )
    if status.stdout.strip():
        raise HandoffError("artifact_dirty")


def validate_handoff(
    path: Path, *, runner: Runner = subprocess.run
) -> HandoffSummary:
    manifest = parse_manifest(path)
    repo = _validate_repo(manifest.execution_repo, runner)
    plan_relative = _artifact_relative(repo, manifest.plan_path, "plan_missing")
    design_relative = _artifact_relative(repo, manifest.design_path, "design_missing")
    _validate_artifact(repo, plan_relative, manifest.commit_sha, runner)
    _validate_artifact(repo, design_relative, manifest.commit_sha, runner)
    head = _require_git_success(repo, ["rev-parse", "HEAD"], runner).stdout.strip()
    if head != manifest.commit_sha:
        raise HandoffError("head_mismatch")
    runtime = (
        "none"
        if manifest.runtime_kind == "none"
        else f"{manifest.runtime_kind}@{manifest.runtime_host}"
    )
    return HandoffSummary(
        task_id=manifest.task_id,
        repo_name=repo.name,
        commit_short=manifest.commit_sha[:8],
        runtime=runtime,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an agent handoff manifest")
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = validate_handoff(args.manifest)
    except HandoffError as exc:
        print(f"HANDOFF_FAIL code={exc.code}")
        return 1
    print(
        f"HANDOFF_OK task={summary.task_id} repo={summary.repo_name} "
        f"commit={summary.commit_short} runtime={summary.runtime}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
