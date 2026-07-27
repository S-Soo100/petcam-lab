"""Parse and fail closed on research run manifest authorization."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

PERMISSION_ACTIONS = {
    "P0": frozenset(),
    "P1": frozenset(
        {
            "docs_write",
            "local_code_write",
            "feature_branch_commit",
            "feature_branch_push",
        }
    ),
    "P2": frozenset(
        {
            "preview_deploy",
            "disposable_db",
            "rollback_probe",
            "nonproduction_canary",
        }
    ),
    "P3": frozenset(
        {
            "production_migration",
            "production_deploy",
            "runtime_service_write",
        }
    ),
    "P4": frozenset(
        {
            "database_delete",
            "r2_delete",
            "destructive_git",
            "credential_change",
            "cost_limit_increase",
        }
    ),
}
FORBIDDEN_SECRET_KEYS = frozenset(
    {"password", "api_key", "webhook", "cookie", "signed_url", "secret"}
)
PERMISSION_ORDER = ("P0", "P1", "P2", "P3", "P4")
RUNTIME_KINDS = frozenset(
    {"none", "oneshot", "launchagent", "server", "scheduled-job", "mobile-build"}
)
MODEL_PROFILES = frozenset(
    {
        "frontier_planning",
        "critical_engineering",
        "standard_execution",
        "independent_review",
        "local_assistant",
    }
)
MODEL_SURFACES = frozenset({"desktop", "cli", "api", "local"})
REASONING_LEVELS = frozenset({"low", "medium", "high", "xhigh", "ultra", "unverified"})
PRIVACY_CLASSES = frozenset({"public", "internal", "sensitive"})
SHA40 = re.compile(r"[0-9a-f]{40}\Z")

TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "task_id",
        "objective",
        "source",
        "runtime",
        "model",
        "authorization",
        "data",
        "budget",
        "safety",
        "stop_conditions",
        "deliverables",
    }
)
SOURCE_FIELDS = frozenset(
    {
        "execution_repo",
        "branch",
        "commit_sha",
        "design_path",
        "plan_path",
        "require_clean",
    }
)
RUNTIME_FIELDS = frozenset(
    {"implementation_host", "runtime_kind", "runtime_host", "runtime_label"}
)
MODEL_FIELDS = frozenset(
    {
        "profile",
        "surface",
        "requested_model",
        "requested_reasoning",
        "actual_model",
        "actual_reasoning",
        "fallback_reason",
    }
)
AUTHORIZATION_FIELDS = frozenset(
    {
        "approved_by",
        "approved_at",
        "max_permission",
        "allowed_actions",
        "p3_targets",
        "p4_actions",
    }
)
DATA_FIELDS = frozenset(
    {"dataset_version", "splits", "privacy_class", "media_contract"}
)
BUDGET_FIELDS = frozenset(
    {"max_provider_calls", "max_cost_krw", "max_wall_minutes", "deadline"}
)
SAFETY_FIELDS = frozenset(
    {
        "requires_host_guard",
        "requires_lock",
        "requires_rollback",
        "requires_residue_zero",
        "temp_media_must_be_zero",
    }
)
P3_TARGET_FIELDS = frozenset({"kind", "target", "rollback", "canary"})
P4_ACTION_FIELDS = frozenset({"action", "target", "approval_ref"})


class ManifestError(RuntimeError):
    """A manifest rejection containing only a stable machine-readable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class P3Target:
    kind: str
    target: str
    rollback: str
    canary: str


@dataclass(frozen=True, slots=True)
class P4Action:
    action: str
    target: str
    approval_ref: str


@dataclass(frozen=True, slots=True)
class ResearchRunManifest:
    schema_version: int
    task_id: str
    objective: str
    execution_repo: Path
    branch: str
    commit_sha: str
    design_path: Path
    plan_path: Path
    require_clean: bool
    implementation_host: str
    runtime_kind: str
    runtime_host: str | None
    runtime_label: str | None
    profile: str
    surface: str
    requested_model: str | None
    requested_reasoning: str | None
    actual_model: str | None
    actual_reasoning: str | None
    fallback_reason: str | None
    approved_by: str
    approved_at: str
    max_permission: str
    allowed_actions: tuple[str, ...]
    p3_targets: tuple[P3Target, ...]
    p4_actions: tuple[P4Action, ...]
    dataset_version: str
    splits: tuple[str, ...]
    privacy_class: str
    media_contract: str
    max_provider_calls: int
    max_cost_krw: int | float
    max_wall_minutes: int
    deadline: str | None
    requires_host_guard: bool
    requires_lock: bool
    requires_rollback: bool
    requires_residue_zero: bool
    temp_media_must_be_zero: bool
    stop_conditions: tuple[str, ...]
    deliverables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunSummary:
    task_id: str
    repo_name: str
    commit_short: str
    permission: str
    model: str
    runtime: str


Runner = Callable[..., subprocess.CompletedProcess[str]]


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message  # 입력값이 argparse의 기본 usage/error에 섞여 나가지 않게 해.
        raise ManifestError("invalid_arguments")


def allowed_actions(level: str) -> frozenset[str]:
    if level not in PERMISSION_ORDER:
        raise ManifestError("invalid_permission_level")
    result: set[str] = set()
    for current in PERMISSION_ORDER[: PERMISSION_ORDER.index(level) + 1]:
        result.update(PERMISSION_ACTIONS[current])
    return frozenset(result)


def _reject_secret_keys(value: object) -> None:
    if isinstance(value, dict):
        if any(key in FORBIDDEN_SECRET_KEYS for key in value):
            raise ManifestError("secret_field_forbidden")
        for child in value.values():
            _reject_secret_keys(child)
    elif isinstance(value, list):
        for child in value:
            _reject_secret_keys(child)


def _require_object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError("invalid_object")
    return value


def _require_exact_fields(
    value: object,
    expected: frozenset[str],
) -> dict[str, Any]:
    obj = _require_object(value)
    fields = set(obj)
    if fields - expected:
        raise ManifestError("unexpected_field")
    if expected - fields:
        raise ManifestError("missing_field")
    return obj


def _require_nonempty_string(value: object) -> str:
    if not isinstance(value, str):
        raise ManifestError("invalid_scalar_type")
    if not value:
        raise ManifestError("empty_string")
    return value


def _require_optional_nonempty_string(value: object) -> str | None:
    if value is None:
        return None
    return _require_nonempty_string(value)


def _require_nonblank_approval_string(value: object) -> str:
    if not isinstance(value, str):
        raise ManifestError("invalid_scalar_type")
    stripped = value.strip()
    if not stripped:
        raise ManifestError("empty_string")
    return stripped


def _require_optional_nonblank_string(value: object) -> str | None:
    if value is None:
        return None
    return _require_nonblank_approval_string(value)


def _require_aware_timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise ManifestError("invalid_scalar_type")
    stripped = value.strip()
    try:
        timestamp = datetime.fromisoformat(stripped)
    except ValueError:
        raise ManifestError("invalid_approved_at") from None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ManifestError("invalid_approved_at")
    return stripped


def _require_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ManifestError("invalid_scalar_type")
    return value


def _require_enum(value: object, choices: frozenset[str]) -> str:
    if not isinstance(value, str):
        raise ManifestError("invalid_scalar_type")
    if value not in choices:
        raise ManifestError("invalid_enum")
    return value


def _require_optional_enum(
    value: object,
    choices: frozenset[str],
) -> str | None:
    if value is None:
        return None
    return _require_enum(value, choices)


def _require_string_array(
    value: object,
    *,
    nonempty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ManifestError("invalid_array")
    if nonempty and not value:
        raise ManifestError("nonempty_array_required")
    if any(not isinstance(item, str) or not item for item in value):
        raise ManifestError("invalid_array_item")
    return tuple(value)


def _require_absolute_path(value: object) -> Path:
    path = Path(_require_nonempty_string(value))
    if not path.is_absolute():
        raise ManifestError("path_not_absolute")
    return path


def _require_nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError("invalid_scalar_type")
    if value < 0:
        raise ManifestError("negative_budget")
    return value


def _require_nonnegative_number(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError("invalid_scalar_type")
    if not math.isfinite(value):
        raise ManifestError("invalid_scalar_type")
    if value < 0:
        raise ManifestError("negative_budget")
    return value


def _parse_p3_targets(value: object) -> tuple[P3Target, ...]:
    if not isinstance(value, list):
        raise ManifestError("invalid_array")
    result: list[P3Target] = []
    for item in value:
        if not isinstance(item, dict):
            raise ManifestError("p3_authorization_missing")
        if set(item) - P3_TARGET_FIELDS:
            raise ManifestError("unexpected_field")
        if P3_TARGET_FIELDS - set(item):
            raise ManifestError("p3_authorization_missing")
        try:
            values = {
                field: _require_nonblank_approval_string(item[field])
                for field in P3_TARGET_FIELDS
            }
        except ManifestError as error:
            if error.code in {"invalid_scalar_type", "empty_string"}:
                raise ManifestError("p3_authorization_missing") from None
            raise
        target = P3Target(**values)
        canonical = (target.kind, target.target, target.rollback, target.canary)
        if any(
            (current.kind, current.target, current.rollback, current.canary)
            == canonical
            for current in result
        ):
            raise ManifestError("duplicate_p3_target")
        result.append(target)
    return tuple(result)


def _parse_p4_actions(value: object) -> tuple[P4Action, ...]:
    if not isinstance(value, list):
        raise ManifestError("invalid_array")
    result: list[P4Action] = []
    for item in value:
        if not isinstance(item, dict):
            raise ManifestError("p4_authorization_missing")
        if set(item) - P4_ACTION_FIELDS:
            raise ManifestError("unexpected_field")
        if P4_ACTION_FIELDS - set(item):
            raise ManifestError("p4_authorization_missing")
        try:
            values = {
                field: _require_nonblank_approval_string(item[field])
                for field in P4_ACTION_FIELDS
            }
        except ManifestError as error:
            if error.code in {"invalid_scalar_type", "empty_string"}:
                raise ManifestError("p4_authorization_missing") from None
            raise
        action = P4Action(**values)
        canonical = (action.action, action.target, action.approval_ref)
        if any(
            (current.action, current.target, current.approval_ref) == canonical
            for current in result
        ):
            raise ManifestError("duplicate_p4_action")
        result.append(action)
    return tuple(result)


def _validate_authorization(
    max_permission: str,
    actions: tuple[str, ...],
    p3_targets: tuple[P3Target, ...],
    p4_actions: tuple[P4Action, ...],
) -> None:
    action_set = set(actions)
    if not action_set <= allowed_actions(max_permission):
        raise ManifestError("permission_scope_mismatch")

    required_p3 = action_set & PERMISSION_ACTIONS["P3"]
    authorized_p3 = {item.kind for item in p3_targets}
    if authorized_p3 != required_p3:
        raise ManifestError("p3_authorization_missing")

    required_p4 = action_set & PERMISSION_ACTIONS["P4"]
    authorized_p4 = {item.action for item in p4_actions}
    if authorized_p4 != required_p4:
        raise ManifestError("p4_authorization_missing")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError("duplicate_json_key")
        result[key] = value
    return result


def _reject_nonfinite_constant(_: str) -> None:
    raise ManifestError("invalid_json")


def _validate_model_provenance(
    *,
    requested_model: str | None,
    requested_reasoning: str | None,
    actual_model: str | None,
    actual_reasoning: str | None,
    fallback_reason: str | None,
) -> None:
    if actual_model is None and actual_reasoning is not None:
        raise ManifestError("actual_model_missing")
    if actual_model is not None and actual_reasoning is None:
        raise ManifestError("actual_reasoning_missing")
    if actual_model is None:
        if fallback_reason is not None:
            raise ManifestError("fallback_reason_unexpected")
        return

    actual_matches_requested = (
        actual_model == requested_model and actual_reasoning == requested_reasoning
    )
    if actual_matches_requested and fallback_reason is not None:
        raise ManifestError("fallback_reason_unexpected")
    if not actual_matches_requested and fallback_reason is None:
        raise ManifestError("fallback_reason_required")


def _validate_runtime_contract(
    *,
    runtime_kind: str,
    runtime_host: str | None,
    runtime_label: str | None,
) -> None:
    if runtime_kind == "none":
        if runtime_host is not None or runtime_label is not None:
            raise ManifestError("runtime_field_forbidden")
        return
    if runtime_host is None:
        raise ManifestError("runtime_host_missing")
    if runtime_label is None:
        raise ManifestError("runtime_label_missing")


def _canonical_runtime_identity(
    value: object,
    *,
    missing_code: str,
    invalid_code: str,
) -> str:
    if value is None:
        raise ManifestError(missing_code)
    if not isinstance(value, str):
        raise ManifestError("invalid_scalar_type")
    canonical = value.strip()
    if not canonical:
        raise ManifestError(missing_code)
    if any(unicodedata.category(char) == "Cc" for char in canonical):
        raise ManifestError(invalid_code)
    return canonical


def parse_run_manifest(path: Path) -> ResearchRunManifest:
    try:
        raw: object = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ManifestError("invalid_json") from None
    except OSError:
        raise ManifestError("manifest_read_failed") from None

    _reject_secret_keys(raw)
    root = _require_exact_fields(raw, TOP_LEVEL_FIELDS)
    source = _require_exact_fields(root["source"], SOURCE_FIELDS)
    runtime = _require_exact_fields(root["runtime"], RUNTIME_FIELDS)
    model = _require_exact_fields(root["model"], MODEL_FIELDS)
    authorization = _require_exact_fields(
        root["authorization"],
        AUTHORIZATION_FIELDS,
    )
    data = _require_exact_fields(root["data"], DATA_FIELDS)
    budget = _require_exact_fields(root["budget"], BUDGET_FIELDS)
    safety = _require_exact_fields(root["safety"], SAFETY_FIELDS)

    schema_version = root["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ManifestError("invalid_scalar_type")
    if schema_version != 1:
        raise ManifestError("invalid_enum")

    commit_sha = _require_nonempty_string(source["commit_sha"])
    if SHA40.fullmatch(commit_sha) is None:
        raise ManifestError("invalid_commit_sha")

    max_permission_raw = authorization["max_permission"]
    if not isinstance(max_permission_raw, str):
        raise ManifestError("invalid_scalar_type")
    if max_permission_raw not in PERMISSION_ORDER:
        raise ManifestError("invalid_permission_level")
    max_permission = max_permission_raw

    actions = _require_string_array(authorization["allowed_actions"])
    if len(actions) != len(set(actions)):
        raise ManifestError("duplicate_allowed_action")
    p3_targets = _parse_p3_targets(authorization["p3_targets"])
    p4_actions = _parse_p4_actions(authorization["p4_actions"])
    _validate_authorization(max_permission, actions, p3_targets, p4_actions)

    requested_model = _require_optional_nonblank_string(model["requested_model"])
    requested_reasoning = _require_optional_enum(
        model["requested_reasoning"],
        REASONING_LEVELS,
    )
    actual_model = _require_optional_nonblank_string(model["actual_model"])
    actual_reasoning = _require_optional_enum(
        model["actual_reasoning"],
        REASONING_LEVELS,
    )
    fallback_reason = _require_optional_nonblank_string(model["fallback_reason"])
    _validate_model_provenance(
        requested_model=requested_model,
        requested_reasoning=requested_reasoning,
        actual_model=actual_model,
        actual_reasoning=actual_reasoning,
        fallback_reason=fallback_reason,
    )

    runtime_kind = _require_enum(runtime["runtime_kind"], RUNTIME_KINDS)
    if runtime_kind == "none":
        if (
            runtime["runtime_host"] is not None
            or runtime["runtime_label"] is not None
        ):
            raise ManifestError("runtime_field_forbidden")
        runtime_host = None
        runtime_label = None
    else:
        runtime_host = _canonical_runtime_identity(
            runtime["runtime_host"],
            missing_code="runtime_host_missing",
            invalid_code="runtime_host_invalid",
        )
        runtime_label = _canonical_runtime_identity(
            runtime["runtime_label"],
            missing_code="runtime_label_missing",
            invalid_code="runtime_label_invalid",
        )
    _validate_runtime_contract(
        runtime_kind=runtime_kind,
        runtime_host=runtime_host,
        runtime_label=runtime_label,
    )

    return ResearchRunManifest(
        schema_version=schema_version,
        task_id=_require_nonempty_string(root["task_id"]),
        objective=_require_nonempty_string(root["objective"]),
        execution_repo=_require_absolute_path(source["execution_repo"]),
        branch=_require_nonempty_string(source["branch"]),
        commit_sha=commit_sha,
        design_path=_require_absolute_path(source["design_path"]),
        plan_path=_require_absolute_path(source["plan_path"]),
        require_clean=_require_bool(source["require_clean"]),
        implementation_host=_require_nonempty_string(runtime["implementation_host"]),
        runtime_kind=runtime_kind,
        runtime_host=runtime_host,
        runtime_label=runtime_label,
        profile=_require_enum(model["profile"], MODEL_PROFILES),
        surface=_require_enum(model["surface"], MODEL_SURFACES),
        requested_model=requested_model,
        requested_reasoning=requested_reasoning,
        actual_model=actual_model,
        actual_reasoning=actual_reasoning,
        fallback_reason=fallback_reason,
        approved_by=_require_nonblank_approval_string(authorization["approved_by"]),
        approved_at=_require_aware_timestamp(authorization["approved_at"]),
        max_permission=max_permission,
        allowed_actions=actions,
        p3_targets=p3_targets,
        p4_actions=p4_actions,
        dataset_version=_require_nonempty_string(data["dataset_version"]),
        splits=_require_string_array(data["splits"]),
        privacy_class=_require_enum(data["privacy_class"], PRIVACY_CLASSES),
        media_contract=_require_nonempty_string(data["media_contract"]),
        max_provider_calls=_require_nonnegative_int(budget["max_provider_calls"]),
        max_cost_krw=_require_nonnegative_number(budget["max_cost_krw"]),
        max_wall_minutes=_require_nonnegative_int(budget["max_wall_minutes"]),
        deadline=_require_optional_nonempty_string(budget["deadline"]),
        requires_host_guard=_require_bool(safety["requires_host_guard"]),
        requires_lock=_require_bool(safety["requires_lock"]),
        requires_rollback=_require_bool(safety["requires_rollback"]),
        requires_residue_zero=_require_bool(safety["requires_residue_zero"]),
        temp_media_must_be_zero=_require_bool(safety["temp_media_must_be_zero"]),
        stop_conditions=_require_string_array(
            root["stop_conditions"],
            nonempty=True,
        ),
        deliverables=_require_string_array(root["deliverables"], nonempty=True),
    )


def _git(
    repo: Path,
    args: Sequence[str],
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        raise ManifestError("git_probe_failed") from None


def _require_git_success(
    repo: Path,
    args: Sequence[str],
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    completed = _git(repo, args, runner)
    if completed.returncode != 0:
        raise ManifestError("git_probe_failed")
    return completed


def _validate_repo_and_git_state(
    manifest: ResearchRunManifest,
    runner: Runner,
) -> Path:
    repo = manifest.execution_repo
    if not repo.exists() or not repo.is_dir():
        raise ManifestError("repo_missing")
    if repo.is_symlink():
        raise ManifestError("repo_not_git_root")
    try:
        resolved = repo.resolve(strict=True)
    except OSError:
        raise ManifestError("repo_missing") from None
    if repo != resolved:
        raise ManifestError("repo_not_git_root")

    root_probe = _require_git_success(
        resolved,
        ["rev-parse", "--show-toplevel"],
        runner,
    )
    try:
        git_root = Path(root_probe.stdout.strip()).resolve(strict=True)
    except OSError:
        raise ManifestError("git_probe_failed") from None
    if git_root != resolved:
        raise ManifestError("repo_not_git_root")

    head = _require_git_success(
        resolved,
        ["rev-parse", "HEAD"],
        runner,
    ).stdout.strip()
    if head != manifest.commit_sha:
        raise ManifestError("head_mismatch")

    branch_probe = _git(
        resolved,
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        runner,
    )
    if branch_probe.returncode != 0:
        raise ManifestError("branch_mismatch")
    branch = branch_probe.stdout.strip()
    if branch != manifest.branch:
        raise ManifestError("branch_mismatch")

    if manifest.require_clean:
        status = _require_git_success(
            resolved,
            ["status", "--porcelain"],
            runner,
        ).stdout
        if status.strip():
            raise ManifestError("dirty_tree")
    return resolved


def _artifact_relative(repo: Path, path: Path) -> Path:
    try:
        lexical_relative = path.relative_to(repo)
    except ValueError:
        raise ManifestError("artifact_outside_repo") from None
    if not lexical_relative.parts or ".." in lexical_relative.parts:
        raise ManifestError("artifact_outside_repo")
    return lexical_relative


def _validate_artifact(
    repo: Path,
    path: Path,
    commit_sha: str,
    runner: Runner,
) -> None:
    relative = _artifact_relative(repo, path)
    if not path.exists() and not path.is_symlink():
        raise ManifestError("artifact_missing")
    rel = relative.as_posix()
    committed = _require_git_success(
        repo,
        ["ls-tree", "-z", commit_sha, "--", rel],
        runner,
    )
    entries = [item for item in committed.stdout.split("\0") if item]
    if len(entries) != 1 or "\t" not in entries[0]:
        raise ManifestError("artifact_untracked")
    metadata, committed_path = entries[0].split("\t", 1)
    try:
        mode, object_type, object_id = metadata.split(" ")
    except ValueError:
        raise ManifestError("git_probe_failed") from None
    if committed_path != rel:
        raise ManifestError("artifact_untracked")
    if mode not in {"100644", "100755"} or object_type != "blob":
        raise ManifestError("artifact_invalid_mode")

    current = repo
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ManifestError("artifact_outside_repo")
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise ManifestError("artifact_missing")
    try:
        path.resolve(strict=True).relative_to(repo)
    except (OSError, ValueError):
        raise ManifestError("artifact_outside_repo") from None

    working_object_id = _require_git_success(
        repo,
        ["hash-object", "--no-filters", "--", rel],
        runner,
    ).stdout.strip()
    if working_object_id != object_id:
        raise ManifestError("artifact_modified")


def _format_runtime(manifest: ResearchRunManifest) -> str:
    if manifest.runtime_kind == "none":
        return "none"
    return f"{manifest.runtime_kind}@{manifest.runtime_host}"


def _marker_value(value: str) -> str:
    return quote(
        value,
        safe="-._~@",
        encoding="utf-8",
        errors="surrogatepass",
    )


def validate_run_manifest(
    path: Path,
    *,
    phase: str,
    runner: Runner = subprocess.run,
) -> RunSummary:
    if phase not in {"start", "final"}:
        raise ManifestError("invalid_phase")
    manifest = parse_run_manifest(path)
    repo = _validate_repo_and_git_state(manifest, runner)
    _validate_artifact(repo, manifest.design_path, manifest.commit_sha, runner)
    _validate_artifact(repo, manifest.plan_path, manifest.commit_sha, runner)
    if phase == "final":
        if manifest.actual_model is None:
            raise ManifestError("actual_model_missing")
        if manifest.actual_reasoning is None:
            raise ManifestError("actual_reasoning_missing")
    return RunSummary(
        task_id=manifest.task_id,
        repo_name=repo.name,
        commit_short=manifest.commit_sha[:8],
        permission=manifest.max_permission,
        model=manifest.actual_model or manifest.requested_model or "unverified",
        runtime=_format_runtime(manifest),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _SafeArgumentParser(
        description="Verify a research run manifest",
        allow_abbrev=False,
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--schema-only", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.phase not in {"start", "final"}:
            raise ManifestError("invalid_phase")
        if args.schema_only:
            manifest = parse_run_manifest(args.manifest)
        else:
            summary = validate_run_manifest(args.manifest, phase=args.phase)
    except ManifestError as error:
        print(f"RUN_MANIFEST_FAIL code={error.code}")
        return 2

    if args.schema_only:
        print(
            f"RUN_MANIFEST_SCHEMA_OK task={_marker_value(manifest.task_id)} "
            f"permission={manifest.max_permission}"
        )
        return 0
    print(
        f"RUN_MANIFEST_OK task={_marker_value(summary.task_id)} "
        f"repo={_marker_value(summary.repo_name)} "
        f"commit={summary.commit_short} permission={summary.permission} "
        f"model={_marker_value(summary.model)} "
        f"runtime={_marker_value(summary.runtime)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
