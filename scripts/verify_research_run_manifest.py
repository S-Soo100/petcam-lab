"""Parse and fail closed on research run manifest authorization."""

from __future__ import annotations

import argparse
import json
import math
import re
import socket
import subprocess
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
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
        "start_manifest_commit_sha",
        "final_commit_sha",
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
    start_manifest_commit_sha: str | None
    final_commit_sha: str | None
    design_path: Path
    plan_path: Path
    require_clean: bool
    implementation_host: str
    runtime_kind: str
    runtime_host: str | None
    runtime_label: str | None
    profile: str
    surface: str
    requested_model: str
    requested_reasoning: str
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
    base_commit_short: str
    start_manifest_commit_short: str
    implementation_commit_short: str | None
    record_commit_short: str
    permission: str
    model: str
    runtime: str


Runner = Callable[..., subprocess.CompletedProcess[str]]
HostLookup = Callable[[], str]
ApprovalVerifier = Callable[[ResearchRunManifest, str], bool]
RuntimeAttestationVerifier = Callable[[ResearchRunManifest], bool]


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


def _require_canonical_string(value: object) -> str:
    if not isinstance(value, str):
        raise ManifestError("invalid_scalar_type")
    stripped = value.strip()
    if not stripped:
        raise ManifestError("empty_string")
    if any(unicodedata.category(char) == "Cc" for char in stripped):
        raise ManifestError("control_character_forbidden")
    return stripped


def _require_nonblank_approval_string(value: object) -> str:
    return _require_canonical_string(value)


def _require_optional_nonblank_string(value: object) -> str | None:
    if value is None:
        return None
    return _require_canonical_string(value)


def _require_aware_timestamp(value: object, *, invalid_code: str) -> str:
    try:
        stripped = _require_canonical_string(value)
    except ManifestError as error:
        if error.code == "invalid_scalar_type":
            raise
        raise ManifestError(invalid_code) from None
    try:
        timestamp = datetime.fromisoformat(stripped)
    except ValueError:
        raise ManifestError(invalid_code) from None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ManifestError(invalid_code)
    return stripped


def _require_optional_aware_timestamp(value: object, *, invalid_code: str) -> str | None:
    if value is None:
        return None
    return _require_aware_timestamp(value, invalid_code=invalid_code)


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
    unique: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ManifestError("invalid_array")
    if nonempty and not value:
        raise ManifestError("nonempty_array_required")
    result: list[str] = []
    for item in value:
        try:
            result.append(_require_canonical_string(item))
        except ManifestError:
            raise ManifestError("invalid_array_item") from None
    if unique and len(result) != len(set(result)):
        raise ManifestError("duplicate_array_item")
    return tuple(result)


def _require_absolute_path(value: object) -> Path:
    path = Path(_require_canonical_string(value))
    if not path.is_absolute():
        raise ManifestError("path_not_absolute")
    return path


def _require_optional_sha40(value: object) -> str | None:
    if value is None:
        return None
    sha = _require_canonical_string(value)
    if SHA40.fullmatch(sha) is None:
        raise ManifestError("invalid_commit_sha")
    return sha


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
            if error.code in {
                "invalid_scalar_type",
                "empty_string",
                "control_character_forbidden",
            }:
                raise ManifestError("p3_authorization_missing") from None
            raise
        target = P3Target(**values)
        canonical = (target.kind, target.target)
        if any(
            (current.kind, current.target) == canonical
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
            if error.code in {
                "invalid_scalar_type",
                "empty_string",
                "control_character_forbidden",
            }:
                raise ManifestError("p4_authorization_missing") from None
            raise
        action = P4Action(**values)
        canonical = (action.action, action.target)
        if any(
            (current.action, current.target) == canonical
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


def _validate_safety_relationships(
    *,
    actions: tuple[str, ...],
    requires_host_guard: bool,
    requires_lock: bool,
    requires_rollback: bool,
    requires_residue_zero: bool,
) -> None:
    action_set = set(actions)
    if action_set & PERMISSION_ACTIONS["P3"]:
        if not requires_rollback:
            raise ManifestError("rollback_protection_required")
        if not requires_residue_zero:
            raise ManifestError("residue_zero_required")
    if "runtime_service_write" in action_set:
        if not requires_host_guard:
            raise ManifestError("host_guard_required")
        if not requires_lock:
            raise ManifestError("lock_required")
    if "disposable_db" in action_set and not requires_residue_zero:
        raise ManifestError("residue_zero_required")
    if "rollback_probe" in action_set:
        if not requires_rollback:
            raise ManifestError("rollback_protection_required")
        if not requires_residue_zero:
            raise ManifestError("residue_zero_required")


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
    requested_model: str,
    requested_reasoning: str,
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

    positively_identified_difference = (
        actual_model != "unverified" and actual_model != requested_model
    ) or (
        actual_reasoning != "unverified"
        and actual_reasoning != requested_reasoning
    )
    if positively_identified_difference and fallback_reason is None:
        raise ManifestError("fallback_reason_required")
    if not positively_identified_difference and fallback_reason is not None:
        raise ManifestError("fallback_reason_unexpected")


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
    try:
        return _require_canonical_string(value)
    except ManifestError as error:
        if error.code == "empty_string":
            raise ManifestError(missing_code) from None
        if error.code == "control_character_forbidden":
            raise ManifestError(invalid_code) from None
        raise


def _parse_run_manifest_text(text: str) -> ResearchRunManifest:
    try:
        raw: object = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except json.JSONDecodeError:
        raise ManifestError("invalid_json") from None

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

    commit_sha = _require_canonical_string(source["commit_sha"])
    if SHA40.fullmatch(commit_sha) is None:
        raise ManifestError("invalid_commit_sha")
    start_manifest_commit_sha = _require_optional_sha40(
        source["start_manifest_commit_sha"]
    )
    final_commit_sha = _require_optional_sha40(source["final_commit_sha"])

    max_permission_raw = authorization["max_permission"]
    if not isinstance(max_permission_raw, str):
        raise ManifestError("invalid_scalar_type")
    if max_permission_raw not in PERMISSION_ORDER:
        raise ManifestError("invalid_permission_level")
    max_permission = max_permission_raw

    actions = _require_string_array(authorization["allowed_actions"])
    if any(action not in allowed_actions("P4") for action in actions):
        raise ManifestError("permission_scope_mismatch")
    if len(actions) != len(set(actions)):
        raise ManifestError("duplicate_allowed_action")
    p3_targets = _parse_p3_targets(authorization["p3_targets"])
    p4_actions = _parse_p4_actions(authorization["p4_actions"])
    _validate_authorization(max_permission, actions, p3_targets, p4_actions)

    if model["requested_model"] is None:
        raise ManifestError("requested_model_missing")
    requested_model = _require_canonical_string(model["requested_model"])
    if model["requested_reasoning"] is None:
        raise ManifestError("requested_reasoning_missing")
    requested_reasoning = _require_enum(model["requested_reasoning"], REASONING_LEVELS)
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

    require_clean = _require_bool(source["require_clean"])
    if not require_clean:
        raise ManifestError("clean_provenance_required")

    requires_host_guard = _require_bool(safety["requires_host_guard"])
    requires_lock = _require_bool(safety["requires_lock"])
    requires_rollback = _require_bool(safety["requires_rollback"])
    requires_residue_zero = _require_bool(safety["requires_residue_zero"])
    _validate_safety_relationships(
        actions=actions,
        requires_host_guard=requires_host_guard,
        requires_lock=requires_lock,
        requires_rollback=requires_rollback,
        requires_residue_zero=requires_residue_zero,
    )

    manifest = ResearchRunManifest(
        schema_version=schema_version,
        task_id=_require_canonical_string(root["task_id"]),
        objective=_require_canonical_string(root["objective"]),
        execution_repo=_require_absolute_path(source["execution_repo"]),
        branch=_require_canonical_string(source["branch"]),
        commit_sha=commit_sha,
        start_manifest_commit_sha=start_manifest_commit_sha,
        final_commit_sha=final_commit_sha,
        design_path=_require_absolute_path(source["design_path"]),
        plan_path=_require_absolute_path(source["plan_path"]),
        require_clean=require_clean,
        implementation_host=_require_canonical_string(
            runtime["implementation_host"]
        ),
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
        approved_at=_require_aware_timestamp(
            authorization["approved_at"],
            invalid_code="invalid_approved_at",
        ),
        max_permission=max_permission,
        allowed_actions=actions,
        p3_targets=p3_targets,
        p4_actions=p4_actions,
        dataset_version=_require_canonical_string(data["dataset_version"]),
        splits=_require_string_array(data["splits"], unique=True),
        privacy_class=_require_enum(data["privacy_class"], PRIVACY_CLASSES),
        media_contract=_require_canonical_string(data["media_contract"]),
        max_provider_calls=_require_nonnegative_int(budget["max_provider_calls"]),
        max_cost_krw=_require_nonnegative_number(budget["max_cost_krw"]),
        max_wall_minutes=_require_nonnegative_int(budget["max_wall_minutes"]),
        deadline=_require_optional_aware_timestamp(
            budget["deadline"],
            invalid_code="invalid_deadline",
        ),
        requires_host_guard=requires_host_guard,
        requires_lock=requires_lock,
        requires_rollback=requires_rollback,
        requires_residue_zero=requires_residue_zero,
        temp_media_must_be_zero=_require_bool(safety["temp_media_must_be_zero"]),
        stop_conditions=_require_string_array(
            root["stop_conditions"],
            nonempty=True,
            unique=True,
        ),
        deliverables=_require_string_array(
            root["deliverables"],
            nonempty=True,
            unique=True,
        ),
    )
    return manifest


def parse_run_manifest(path: Path) -> ResearchRunManifest:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ManifestError("invalid_json") from None
    except OSError:
        raise ManifestError("manifest_read_failed") from None
    return _parse_run_manifest_text(text)


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
    except (OSError, subprocess.SubprocessError, UnicodeError):
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


def _validate_repo_identity(
    manifest: ResearchRunManifest,
    runner: Runner,
) -> tuple[Path, str]:
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
    if SHA40.fullmatch(head) is None:
        raise ManifestError("git_probe_failed")

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
    return resolved, head


def _validate_clean_repo(repo: Path, runner: Runner) -> None:
    status = _require_git_success(
        repo,
        [
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ],
        runner,
    ).stdout
    if status.strip():
        raise ManifestError("dirty_tree")


def _artifact_relative(repo: Path, path: Path) -> Path:
    try:
        lexical_relative = path.relative_to(repo)
    except ValueError:
        raise ManifestError("artifact_outside_repo") from None
    if not lexical_relative.parts or ".." in lexical_relative.parts:
        raise ManifestError("artifact_outside_repo")
    return lexical_relative


def _committed_blob_id(
    repo: Path,
    relative: Path,
    commit_sha: str,
    runner: Runner,
) -> str:
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
    return object_id


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
    object_id = _committed_blob_id(repo, relative, commit_sha, runner)

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


def _manifest_path_in_repo(repo: Path, path: Path) -> tuple[Path, Path]:
    absolute = path if path.is_absolute() else Path.cwd() / path
    try:
        relative = _artifact_relative(repo, absolute)
    except ManifestError as error:
        if error.code == "artifact_outside_repo":
            raise ManifestError("manifest_outside_repo") from None
        raise
    return absolute, relative


def _validate_current_manifest_blob(
    repo: Path,
    path: Path,
    head: str,
    runner: Runner,
) -> Path:
    absolute, relative = _manifest_path_in_repo(repo, path)
    try:
        _validate_artifact(repo, absolute, head, runner)
    except ManifestError as error:
        mapping = {
            "artifact_outside_repo": "manifest_outside_repo",
            "artifact_missing": "manifest_untracked",
            "artifact_untracked": "manifest_untracked",
            "artifact_invalid_mode": "manifest_untracked",
            "artifact_modified": "manifest_modified",
        }
        code = mapping.get(error.code)
        if code is not None:
            raise ManifestError(code) from None
        raise
    return relative


def _commit_parent(
    repo: Path,
    commit_sha: str,
    runner: Runner,
    *,
    error_code: str,
) -> str:
    probe = _git(repo, ["rev-parse", f"{commit_sha}^"], runner)
    parent = probe.stdout.strip()
    if probe.returncode != 0 or SHA40.fullmatch(parent) is None:
        raise ManifestError(error_code)
    return parent


def _validate_dedicated_manifest_commit(
    repo: Path,
    commit_sha: str,
    manifest_relative: Path,
    runner: Runner,
    *,
    error_code: str,
) -> None:
    changed = _require_git_success(
        repo,
        [
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            "-z",
            commit_sha,
        ],
        runner,
    ).stdout
    changed_paths = [item for item in changed.split("\0") if item]
    if changed_paths != [manifest_relative.as_posix()]:
        raise ManifestError(error_code)


def _require_ancestor(
    repo: Path,
    ancestor: str,
    descendant: str,
    runner: Runner,
) -> None:
    probe = _git(
        repo,
        ["merge-base", "--is-ancestor", ancestor, descendant],
        runner,
    )
    if probe.returncode != 0:
        raise ManifestError("lifecycle_ancestry_mismatch")


def _load_manifest_from_commit(
    repo: Path,
    relative: Path,
    commit_sha: str,
    runner: Runner,
) -> ResearchRunManifest:
    try:
        _committed_blob_id(repo, relative, commit_sha, runner)
    except ManifestError as error:
        if error.code in {"artifact_untracked", "artifact_invalid_mode"}:
            raise ManifestError("start_manifest_untracked") from None
        raise
    blob = _git(
        repo,
        ["cat-file", "blob", f"{commit_sha}:{relative.as_posix()}"],
        runner,
    )
    if blob.returncode != 0:
        raise ManifestError("start_manifest_untracked")
    try:
        return _parse_run_manifest_text(blob.stdout)
    except ManifestError:
        raise ManifestError("start_manifest_invalid") from None


def _validate_start_fields_are_null(manifest: ResearchRunManifest) -> None:
    if any(
        value is not None
        for value in (
            manifest.start_manifest_commit_sha,
            manifest.final_commit_sha,
            manifest.actual_model,
            manifest.actual_reasoning,
            manifest.fallback_reason,
        )
    ):
        raise ManifestError("start_provenance_not_null")


def _validate_final_manifest_immutability(
    original: ResearchRunManifest,
    final: ResearchRunManifest,
) -> None:
    _validate_start_fields_are_null(original)
    mutable_fields = {
        "start_manifest_commit_sha",
        "final_commit_sha",
        "actual_model",
        "actual_reasoning",
        "fallback_reason",
    }
    for field in fields(ResearchRunManifest):
        if field.name in mutable_fields:
            continue
        if getattr(original, field.name) != getattr(final, field.name):
            raise ManifestError("immutable_field_changed")


def _validate_current_host(
    manifest: ResearchRunManifest,
    host_lookup: HostLookup,
) -> None:
    try:
        current = host_lookup()
    except (OSError, RuntimeError):
        raise ManifestError("host_probe_failed") from None
    try:
        canonical = _require_canonical_string(current)
    except ManifestError:
        raise ManifestError("host_probe_failed") from None
    if canonical != manifest.implementation_host:
        raise ManifestError("implementation_host_mismatch")


def _validate_trusted_approval(
    manifest: ResearchRunManifest,
    phase: str,
    verifier: ApprovalVerifier | None,
) -> None:
    if manifest.max_permission not in {"P3", "P4"}:
        return
    if verifier is None:
        raise ManifestError("approval_verifier_missing")
    try:
        verified = verifier(manifest, phase)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise ManifestError("approval_not_verified") from None
    if verified is not True:
        raise ManifestError("approval_not_verified")


def _validate_runtime_attestation(
    manifest: ResearchRunManifest,
    verifier: RuntimeAttestationVerifier | None,
) -> None:
    if manifest.runtime_kind == "none":
        return
    if verifier is None:
        raise ManifestError("runtime_attestation_verifier_missing")
    try:
        verified = verifier(manifest)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise ManifestError("runtime_attestation_not_verified") from None
    if verified is not True:
        raise ManifestError("runtime_attestation_not_verified")


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
    host_lookup: HostLookup = socket.gethostname,
    approval_verifier: ApprovalVerifier | None = None,
    runtime_attestation_verifier: RuntimeAttestationVerifier | None = None,
) -> RunSummary:
    if phase not in {"start", "final"}:
        raise ManifestError("invalid_phase")
    manifest = parse_run_manifest(path)
    repo, head = _validate_repo_identity(manifest, runner)
    manifest_relative = _validate_current_manifest_blob(repo, path, head, runner)
    _validate_clean_repo(repo, runner)
    _validate_artifact(repo, manifest.design_path, manifest.commit_sha, runner)
    _validate_artifact(repo, manifest.plan_path, manifest.commit_sha, runner)
    _validate_current_host(manifest, host_lookup)
    _validate_trusted_approval(manifest, phase, approval_verifier)

    if phase == "start":
        _validate_start_fields_are_null(manifest)
        parent = _commit_parent(
            repo,
            head,
            runner,
            error_code="start_base_not_parent",
        )
        if parent != manifest.commit_sha:
            raise ManifestError("start_base_not_parent")
        _validate_dedicated_manifest_commit(
            repo,
            head,
            manifest_relative,
            runner,
            error_code="start_manifest_commit_not_dedicated",
        )
        start_manifest_sha = head
        implementation_sha = None
    else:
        if manifest.start_manifest_commit_sha is None:
            raise ManifestError("start_manifest_commit_missing")
        if manifest.final_commit_sha is None:
            raise ManifestError("final_commit_missing")
        if manifest.actual_model is None:
            raise ManifestError("actual_model_missing")
        if manifest.actual_reasoning is None:
            raise ManifestError("actual_reasoning_missing")
        record_parent = _commit_parent(
            repo,
            head,
            runner,
            error_code="final_commit_not_parent",
        )
        if record_parent != manifest.final_commit_sha:
            raise ManifestError("final_commit_not_parent")
        start_parent = _commit_parent(
            repo,
            manifest.start_manifest_commit_sha,
            runner,
            error_code="start_base_not_parent",
        )
        if start_parent != manifest.commit_sha:
            raise ManifestError("start_base_not_parent")
        _validate_dedicated_manifest_commit(
            repo,
            manifest.start_manifest_commit_sha,
            manifest_relative,
            runner,
            error_code="start_manifest_commit_not_dedicated",
        )
        _validate_dedicated_manifest_commit(
            repo,
            head,
            manifest_relative,
            runner,
            error_code="final_record_commit_not_dedicated",
        )
        _require_ancestor(
            repo,
            manifest.start_manifest_commit_sha,
            manifest.final_commit_sha,
            runner,
        )
        original = _load_manifest_from_commit(
            repo,
            manifest_relative,
            manifest.start_manifest_commit_sha,
            runner,
        )
        _validate_final_manifest_immutability(original, manifest)
        _validate_runtime_attestation(manifest, runtime_attestation_verifier)
        start_manifest_sha = manifest.start_manifest_commit_sha
        implementation_sha = manifest.final_commit_sha

    return RunSummary(
        task_id=manifest.task_id,
        repo_name=repo.name,
        base_commit_short=manifest.commit_sha[:8],
        start_manifest_commit_short=start_manifest_sha[:8],
        implementation_commit_short=(
            implementation_sha[:8] if implementation_sha is not None else None
        ),
        record_commit_short=head[:8],
        permission=manifest.max_permission,
        model=manifest.actual_model or manifest.requested_model,
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
        f"base={summary.base_commit_short} "
        f"start_manifest={summary.start_manifest_commit_short} "
        "implementation="
        f"{summary.implementation_commit_short or 'none'} "
        f"record={summary.record_commit_short} "
        f"permission={summary.permission} "
        f"model={_marker_value(summary.model)} "
        f"runtime={_marker_value(summary.runtime)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
