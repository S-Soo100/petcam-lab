import json
import socket
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from scripts.verify_research_run_manifest import (
    ManifestError,
    main,
    parse_run_manifest,
    validate_run_manifest,
)


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def base_manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "task_id": "research-contract-test",
        "objective": "validate manifest",
        "source": {
            "execution_repo": "/tmp/repo",
            "branch": "codex/test",
            "commit_sha": "0" * 40,
            "start_manifest_commit_sha": None,
            "final_commit_sha": None,
            "design_path": "/tmp/repo/design.md",
            "plan_path": "/tmp/repo/plan.md",
            "require_clean": True,
        },
        "runtime": {
            "implementation_host": "dev-mac.local",
            "runtime_kind": "none",
            "runtime_host": None,
            "runtime_label": None,
        },
        "model": {
            "profile": "standard_execution",
            "surface": "desktop",
            "requested_model": "gpt-5.6-terra",
            "requested_reasoning": "high",
            "actual_model": None,
            "actual_reasoning": None,
            "fallback_reason": None,
        },
        "authorization": {
            "approved_by": "owner",
            "approved_at": "2026-07-27T00:00:00+09:00",
            "max_permission": "P2",
            "allowed_actions": ["docs_write", "preview_deploy"],
            "p3_targets": [],
            "p4_actions": [],
        },
        "data": {
            "dataset_version": "none",
            "splits": [],
            "privacy_class": "internal",
            "media_contract": "none",
        },
        "budget": {
            "max_provider_calls": 0,
            "max_cost_krw": 0,
            "max_wall_minutes": 60,
            "deadline": None,
        },
        "safety": {
            "requires_host_guard": False,
            "requires_lock": False,
            "requires_rollback": False,
            "requires_residue_zero": False,
            "temp_media_must_be_zero": True,
        },
        "stop_conditions": ["head_mismatch", "secret_exposure"],
        "deliverables": ["REPORT.md"],
    }


def object_at(value: dict[str, object], *path: str) -> dict[str, object]:
    current: object = value
    for name in path:
        assert isinstance(current, dict)
        current = current[name]
    assert isinstance(current, dict)
    return current


def set_at(value: dict[str, object], path: Sequence[str], replacement: object) -> None:
    parent = object_at(value, *path[:-1])
    parent[path[-1]] = replacement


def assert_manifest_error(
    tmp_path: Path,
    value: object,
    expected_code: str,
) -> None:
    with pytest.raises(ManifestError) as raised:
        parse_run_manifest(write_json(tmp_path / "run.json", value))
    assert raised.value.code == expected_code
    assert str(raised.value) == expected_code


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def committed_repo(
    tmp_path: Path,
    repo_name: str = "repo",
) -> tuple[Path, Path, Path, str]:
    repo = tmp_path / repo_name
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "codex@example.invalid")
    git(repo, "config", "user.name", "Codex Test")
    docs = repo / "docs"
    docs.mkdir()
    design = docs / "design.md"
    plan = docs / "plan.md"
    design.write_text("design\n", encoding="utf-8")
    plan.write_text("plan\n", encoding="utf-8")
    git(repo, "add", "docs/design.md", "docs/plan.md")
    git(repo, "commit", "-m", "test artifacts")
    git(repo, "branch", "-m", "codex/test")
    return repo, design, plan, git(repo, "rev-parse", "HEAD")


def manifest_for_repo(
    repo: Path,
    design: Path,
    plan: Path,
    sha: str,
) -> dict[str, object]:
    value = base_manifest()
    object_at(value, "source").update(
        {
            "execution_repo": str(repo),
            "branch": "codex/test",
            "commit_sha": sha,
            "design_path": str(design),
            "plan_path": str(plan),
        }
    )
    return value


def start_manifest_repo(
    tmp_path: Path,
    *,
    mutate: object | None = None,
    implementation_host: str = "implementation.local",
    repo_name: str = "repo",
) -> tuple[Path, Path, dict[str, object], str, str]:
    repo, design, plan, base_sha = committed_repo(tmp_path, repo_name)
    value = manifest_for_repo(repo, design, plan, base_sha)
    object_at(value, "source").update(
        {
            "start_manifest_commit_sha": None,
            "final_commit_sha": None,
        }
    )
    object_at(value, "runtime")["implementation_host"] = implementation_host
    if mutate is not None:
        assert callable(mutate)
        mutate(value)

    manifest = repo / "docs" / "research" / "RUN-MANIFEST.json"
    manifest.parent.mkdir()
    write_json(manifest, value)
    git(repo, "add", "docs/research/RUN-MANIFEST.json")
    git(repo, "commit", "-m", "start manifest")
    start_manifest_sha = git(repo, "rev-parse", "HEAD")
    return repo, manifest, value, base_sha, start_manifest_sha


def final_manifest_repo(
    tmp_path: Path,
    *,
    mutate_final: object | None = None,
    runtime_kind: str = "none",
    implementation_host: str = "implementation.local",
) -> tuple[Path, Path, dict[str, object], str, str, str, str]:
    def configure_start(value: dict[str, object]) -> None:
        if runtime_kind != "none":
            object_at(value, "runtime").update(
                {
                    "runtime_kind": runtime_kind,
                    "runtime_host": "runtime.local",
                    "runtime_label": "com.petcam.worker",
                }
            )

    repo, manifest, value, base_sha, start_manifest_sha = start_manifest_repo(
        tmp_path,
        mutate=configure_start,
        implementation_host=implementation_host,
    )
    (repo / "implementation.txt").write_text("implemented\n", encoding="utf-8")
    git(repo, "add", "implementation.txt")
    git(repo, "commit", "-m", "implementation")
    implementation_sha = git(repo, "rev-parse", "HEAD")

    object_at(value, "source").update(
        {
            "start_manifest_commit_sha": start_manifest_sha,
            "final_commit_sha": implementation_sha,
        }
    )
    object_at(value, "model").update(
        {
            "actual_model": "unverified",
            "actual_reasoning": "unverified",
            "fallback_reason": None,
        }
    )
    if mutate_final is not None:
        assert callable(mutate_final)
        mutate_final(value)
    write_json(manifest, value)
    git(repo, "add", "docs/research/RUN-MANIFEST.json")
    git(repo, "commit", "-m", "final record")
    record_sha = git(repo, "rev-parse", "HEAD")
    return (
        repo,
        manifest,
        value,
        base_sha,
        start_manifest_sha,
        implementation_sha,
        record_sha,
    )


def test_parse_accepts_p2_start_manifest(tmp_path: Path) -> None:
    parsed = parse_run_manifest(write_json(tmp_path / "run.json", base_manifest()))

    assert parsed.task_id == "research-contract-test"
    assert parsed.execution_repo == Path("/tmp/repo")
    assert parsed.max_permission == "P2"
    assert parsed.requested_model == "gpt-5.6-terra"


@pytest.mark.parametrize(
    "secret_key",
    ["password", "api_key", "webhook", "cookie", "signed_url", "secret"],
)
def test_parse_rejects_secret_fields_recursively(
    tmp_path: Path,
    secret_key: str,
) -> None:
    value = base_manifest()
    object_at(value, "data")["splits"] = [{"nested": {secret_key: "redacted"}}]

    assert_manifest_error(tmp_path, value, "secret_field_forbidden")


@pytest.mark.parametrize(
    ("path", "extra"),
    [
        ((), "extra"),
        (("source",), "extra"),
        (("runtime",), "extra"),
        (("model",), "extra"),
        (("authorization",), "extra"),
        (("data",), "extra"),
        (("budget",), "extra"),
        (("safety",), "extra"),
    ],
)
def test_parse_rejects_fields_outside_exact_allowlists(
    tmp_path: Path,
    path: tuple[str, ...],
    extra: str,
) -> None:
    value = base_manifest()
    object_at(value, *path)[extra] = "unexpected"

    assert_manifest_error(tmp_path, value, "unexpected_field")


@pytest.mark.parametrize(
    ("path", "field"),
    [
        ((), "task_id"),
        (("source",), "branch"),
        (("runtime",), "runtime_kind"),
        (("model",), "profile"),
        (("authorization",), "approved_by"),
        (("data",), "dataset_version"),
        (("budget",), "deadline"),
        (("safety",), "requires_lock"),
    ],
)
def test_parse_rejects_missing_required_fields(
    tmp_path: Path,
    path: tuple[str, ...],
    field: str,
) -> None:
    value = base_manifest()
    del object_at(value, *path)[field]

    assert_manifest_error(tmp_path, value, "missing_field")


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("task_id",), 7),
        (("objective",), False),
        (("source", "execution_repo"), None),
        (("source", "require_clean"), 1),
        (("runtime", "implementation_host"), []),
        (("model", "requested_model"), 3),
        (("model", "fallback_reason"), False),
        (("authorization", "approved_at"), None),
        (("data", "media_contract"), 1),
        (("safety", "requires_lock"), 0),
    ],
)
def test_parse_rejects_invalid_scalar_types(
    tmp_path: Path,
    path: tuple[str, ...],
    replacement: object,
) -> None:
    value = base_manifest()
    set_at(value, path, replacement)

    assert_manifest_error(tmp_path, value, "invalid_scalar_type")


def test_parse_rejects_non_object_sections(tmp_path: Path) -> None:
    value = base_manifest()
    value["authorization"] = []

    assert_manifest_error(tmp_path, value, "invalid_object")


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("schema_version",), 2),
        (("runtime", "runtime_kind"), "daemon"),
        (("model", "profile"), "unknown"),
        (("model", "surface"), "browser"),
        (("model", "requested_reasoning"), "max"),
        (("model", "actual_reasoning"), "max"),
        (("authorization", "max_permission"), "P5"),
        (("data", "privacy_class"), "private"),
    ],
)
def test_parse_rejects_invalid_enums(
    tmp_path: Path,
    path: tuple[str, ...],
    replacement: object,
) -> None:
    value = base_manifest()
    set_at(value, path, replacement)

    expected = (
        "invalid_permission_level"
        if path == ("authorization", "max_permission")
        else "invalid_enum"
    )
    assert_manifest_error(tmp_path, value, expected)


@pytest.mark.parametrize(
    "commit_sha",
    ["0" * 39, "0" * 41, "G" * 40, "A" * 40],
)
def test_parse_requires_lowercase_sha40(tmp_path: Path, commit_sha: str) -> None:
    value = base_manifest()
    object_at(value, "source")["commit_sha"] = commit_sha

    assert_manifest_error(tmp_path, value, "invalid_commit_sha")


@pytest.mark.parametrize("field", ["execution_repo", "design_path", "plan_path"])
def test_parse_requires_absolute_source_paths(tmp_path: Path, field: str) -> None:
    value = base_manifest()
    object_at(value, "source")[field] = "relative/path"

    assert_manifest_error(tmp_path, value, "path_not_absolute")


@pytest.mark.parametrize(
    ("field", "replacement", "expected_code"),
    [
        ("max_provider_calls", -1, "negative_budget"),
        ("max_cost_krw", -0.1, "negative_budget"),
        ("max_wall_minutes", -1, "negative_budget"),
        ("max_provider_calls", 1.5, "invalid_scalar_type"),
        ("max_cost_krw", True, "invalid_scalar_type"),
        ("max_wall_minutes", False, "invalid_scalar_type"),
    ],
)
def test_parse_requires_nonnegative_typed_budget(
    tmp_path: Path,
    field: str,
    replacement: object,
    expected_code: str,
) -> None:
    value = base_manifest()
    object_at(value, "budget")[field] = replacement

    assert_manifest_error(tmp_path, value, expected_code)


@pytest.mark.parametrize("field", ["stop_conditions", "deliverables"])
def test_parse_requires_nonempty_terminal_arrays(tmp_path: Path, field: str) -> None:
    value = base_manifest()
    value[field] = []

    assert_manifest_error(tmp_path, value, "nonempty_array_required")


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("authorization", "allowed_actions"), "docs_write"),
        (("authorization", "p3_targets"), {}),
        (("authorization", "p4_actions"), {}),
        (("data", "splits"), "holdout"),
        (("stop_conditions",), "head_mismatch"),
        (("deliverables",), "REPORT.md"),
    ],
)
def test_parse_rejects_non_array_values(
    tmp_path: Path,
    path: tuple[str, ...],
    replacement: object,
) -> None:
    value = base_manifest()
    set_at(value, path, replacement)

    assert_manifest_error(tmp_path, value, "invalid_array")


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("authorization", "allowed_actions"), [""]),
        (("authorization", "allowed_actions"), [1]),
        (("data", "splits"), [""]),
        (("data", "splits"), [None]),
        (("stop_conditions",), [""]),
        (("deliverables",), [3]),
    ],
)
def test_parse_rejects_invalid_string_array_items(
    tmp_path: Path,
    path: tuple[str, ...],
    replacement: object,
) -> None:
    value = base_manifest()
    set_at(value, path, replacement)

    assert_manifest_error(tmp_path, value, "invalid_array_item")


def test_parse_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(ManifestError) as raised:
        parse_run_manifest(path)
    assert str(raised.value) == "invalid_json"
    assert raised.value.__cause__ is None


def test_parse_rejects_invalid_utf8_without_exposing_cause(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    path.write_bytes(b"\xff")

    with pytest.raises(ManifestError) as raised:
        parse_run_manifest(path)
    assert str(raised.value) == "invalid_json"
    assert raised.value.__cause__ is None


def test_parse_rejects_duplicate_json_keys_recursively(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    path.write_text('{"outer":{"same":1,"same":2}}', encoding="utf-8")

    with pytest.raises(ManifestError) as raised:
        parse_run_manifest(path)
    assert str(raised.value) == "duplicate_json_key"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_parse_rejects_nonfinite_json_constants(
    tmp_path: Path,
    constant: str,
) -> None:
    value = json.dumps(base_manifest()).replace(
        '"max_cost_krw": 0',
        f'"max_cost_krw": {constant}',
    )
    path = tmp_path / "run.json"
    path.write_text(value, encoding="utf-8")

    with pytest.raises(ManifestError) as raised:
        parse_run_manifest(path)
    assert str(raised.value) == "invalid_json"
    assert raised.value.__cause__ is None


def test_parse_rejects_non_object_json_root(tmp_path: Path) -> None:
    assert_manifest_error(tmp_path, [], "invalid_object")


@pytest.mark.parametrize("approved_by", ["", " ", "\t\n"])
def test_parse_rejects_blank_approved_by(
    tmp_path: Path,
    approved_by: str,
) -> None:
    value = base_manifest()
    object_at(value, "authorization")["approved_by"] = approved_by

    assert_manifest_error(tmp_path, value, "empty_string")


@pytest.mark.parametrize(
    "approved_at",
    [
        "",
        "2026-07-27",
        "2026-07-27T00:00:00",
        "not-a-timestamp",
    ],
)
def test_parse_requires_timezone_aware_approved_at(
    tmp_path: Path,
    approved_at: str,
) -> None:
    value = base_manifest()
    object_at(value, "authorization")["approved_at"] = approved_at

    assert_manifest_error(tmp_path, value, "invalid_approved_at")


def test_parse_accepts_approved_at_with_z_timezone(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization")["approved_at"] = "2026-07-27T00:00:00Z"

    parsed = parse_run_manifest(write_json(tmp_path / "run.json", value))

    assert parsed.approved_at == "2026-07-27T00:00:00Z"


def test_parse_rejects_duplicate_allowed_actions(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization")["allowed_actions"] = [
        "docs_write",
        "docs_write",
    ]

    assert_manifest_error(tmp_path, value, "duplicate_allowed_action")


def test_p2_rejects_production_action(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization")["allowed_actions"] = ["production_deploy"]

    assert_manifest_error(tmp_path, value, "permission_scope_mismatch")


def test_parse_rejects_unknown_action(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization")["allowed_actions"] = ["invented_action"]

    assert_manifest_error(tmp_path, value, "permission_scope_mismatch")


def test_p3_requires_exact_target_rollback_and_canary(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization").update(
        {
            "max_permission": "P3",
            "allowed_actions": ["production_deploy"],
            "p3_targets": [],
        }
    )

    assert_manifest_error(tmp_path, value, "p3_authorization_missing")


@pytest.mark.parametrize("field", ["kind", "target", "rollback", "canary"])
def test_p3_rejects_missing_or_empty_authorization_fields(
    tmp_path: Path,
    field: str,
) -> None:
    value = base_manifest()
    target = {
        "kind": "production_deploy",
        "target": "api.tera-ai.uk",
        "rollback": "previous-release",
        "canary": "one-instance",
    }
    target[field] = ""
    object_at(value, "authorization").update(
        {
            "max_permission": "P3",
            "allowed_actions": ["production_deploy"],
            "p3_targets": [target],
        }
    )

    assert_manifest_error(tmp_path, value, "p3_authorization_missing")


def test_p3_rejects_target_fields_outside_exact_allowlist(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization").update(
        {
            "max_permission": "P3",
            "allowed_actions": ["production_deploy"],
            "p3_targets": [
                {
                    "kind": "production_deploy",
                    "target": "api.tera-ai.uk",
                    "rollback": "previous-release",
                    "canary": "one-instance",
                    "extra": "forbidden",
                }
            ],
        }
    )

    assert_manifest_error(tmp_path, value, "unexpected_field")


def test_p3_accepts_matching_structured_authorization(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization").update(
        {
            "max_permission": "P3",
            "allowed_actions": ["production_deploy"],
            "p3_targets": [
                {
                    "kind": "production_deploy",
                    "target": "api.tera-ai.uk",
                    "rollback": "previous-release",
                    "canary": "one-instance",
                }
            ],
        }
    )
    object_at(value, "safety").update(
        {
            "requires_rollback": True,
            "requires_residue_zero": True,
        }
    )

    parsed = parse_run_manifest(write_json(tmp_path / "run.json", value))

    assert parsed.p3_targets[0].kind == "production_deploy"


def test_p3_target_must_match_an_allowed_action(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization").update(
        {
            "max_permission": "P3",
            "allowed_actions": ["production_deploy"],
            "p3_targets": [
                {
                    "kind": "runtime_service_write",
                    "target": "worker",
                    "rollback": "unload",
                    "canary": "disabled-first",
                }
            ],
        }
    )

    assert_manifest_error(tmp_path, value, "p3_authorization_missing")


@pytest.mark.parametrize("field", ["kind", "target", "rollback", "canary"])
def test_p3_rejects_whitespace_only_authorization_fields(
    tmp_path: Path,
    field: str,
) -> None:
    value = base_manifest()
    target = {
        "kind": "production_deploy",
        "target": "api.tera-ai.uk",
        "rollback": "previous-release",
        "canary": "one-instance",
    }
    target[field] = " \t "
    object_at(value, "authorization").update(
        {
            "max_permission": "P3",
            "allowed_actions": ["production_deploy"],
            "p3_targets": [target],
        }
    )

    assert_manifest_error(tmp_path, value, "p3_authorization_missing")


def test_p3_rejects_duplicate_canonical_targets(tmp_path: Path) -> None:
    value = base_manifest()
    target = {
        "kind": "production_deploy",
        "target": "api.tera-ai.uk",
        "rollback": "previous-release",
        "canary": "one-instance",
    }
    spaced_target = {field: f" {item} " for field, item in target.items()}
    object_at(value, "authorization").update(
        {
            "max_permission": "P3",
            "allowed_actions": ["production_deploy"],
            "p3_targets": [target, spaced_target],
        }
    )

    assert_manifest_error(tmp_path, value, "duplicate_p3_target")


def test_p4_requires_separate_approval_reference(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization").update(
        {
            "max_permission": "P4",
            "allowed_actions": ["r2_delete"],
            "p4_actions": [
                {
                    "action": "r2_delete",
                    "target": "bounded-canary",
                    "approval_ref": "",
                }
            ],
        }
    )

    assert_manifest_error(tmp_path, value, "p4_authorization_missing")


@pytest.mark.parametrize("field", ["action", "target", "approval_ref"])
def test_p4_rejects_missing_or_empty_authorization_fields(
    tmp_path: Path,
    field: str,
) -> None:
    value = base_manifest()
    action = {
        "action": "r2_delete",
        "target": "bounded-canary",
        "approval_ref": "owner-approval-42",
    }
    del action[field]
    object_at(value, "authorization").update(
        {
            "max_permission": "P4",
            "allowed_actions": ["r2_delete"],
            "p4_actions": [action],
        }
    )

    assert_manifest_error(tmp_path, value, "p4_authorization_missing")


def test_p4_rejects_action_fields_outside_exact_allowlist(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization").update(
        {
            "max_permission": "P4",
            "allowed_actions": ["r2_delete"],
            "p4_actions": [
                {
                    "action": "r2_delete",
                    "target": "bounded-canary",
                    "approval_ref": "owner-approval-42",
                    "extra": "forbidden",
                }
            ],
        }
    )

    assert_manifest_error(tmp_path, value, "unexpected_field")


def test_p4_accepts_matching_structured_authorization(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization").update(
        {
            "max_permission": "P4",
            "allowed_actions": ["r2_delete"],
            "p4_actions": [
                {
                    "action": "r2_delete",
                    "target": "bounded-canary",
                    "approval_ref": "owner-approval-42",
                }
            ],
        }
    )

    parsed = parse_run_manifest(write_json(tmp_path / "run.json", value))

    assert parsed.p4_actions[0].approval_ref == "owner-approval-42"


def test_p4_action_must_match_an_allowed_action(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization").update(
        {
            "max_permission": "P4",
            "allowed_actions": ["r2_delete"],
            "p4_actions": [
                {
                    "action": "database_delete",
                    "target": "bounded-canary",
                    "approval_ref": "owner-approval-42",
                }
            ],
        }
    )

    assert_manifest_error(tmp_path, value, "p4_authorization_missing")


@pytest.mark.parametrize("field", ["action", "target", "approval_ref"])
def test_p4_rejects_whitespace_only_authorization_fields(
    tmp_path: Path,
    field: str,
) -> None:
    value = base_manifest()
    action = {
        "action": "r2_delete",
        "target": "bounded-canary",
        "approval_ref": "owner-approval-42",
    }
    action[field] = " \t "
    object_at(value, "authorization").update(
        {
            "max_permission": "P4",
            "allowed_actions": ["r2_delete"],
            "p4_actions": [action],
        }
    )

    assert_manifest_error(tmp_path, value, "p4_authorization_missing")


def test_p4_rejects_duplicate_canonical_actions(tmp_path: Path) -> None:
    value = base_manifest()
    action = {
        "action": "r2_delete",
        "target": "bounded-canary",
        "approval_ref": "owner-approval-42",
    }
    spaced_action = {field: f" {item} " for field, item in action.items()}
    object_at(value, "authorization").update(
        {
            "max_permission": "P4",
            "allowed_actions": ["r2_delete"],
            "p4_actions": [action, spaced_action],
        }
    )

    assert_manifest_error(tmp_path, value, "duplicate_p4_action")


@pytest.mark.parametrize(
    ("actual_model", "actual_reasoning", "expected_code"),
    [
        ("gpt-5.6-terra", None, "actual_reasoning_missing"),
        (None, "high", "actual_model_missing"),
    ],
)
def test_parse_rejects_partial_actual_model_provenance(
    tmp_path: Path,
    actual_model: str | None,
    actual_reasoning: str | None,
    expected_code: str,
) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "actual_model": actual_model,
            "actual_reasoning": actual_reasoning,
        }
    )

    assert_manifest_error(tmp_path, value, expected_code)


def test_parse_requires_reason_when_actual_differs_from_requested(
    tmp_path: Path,
) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "actual_model": "gpt-5.6-sol",
            "actual_reasoning": "ultra",
            "fallback_reason": None,
        }
    )

    assert_manifest_error(tmp_path, value, "fallback_reason_required")


def test_parse_rejects_reason_when_actual_matches_requested(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "actual_model": "gpt-5.6-terra",
            "actual_reasoning": "high",
            "fallback_reason": "not a fallback",
        }
    )

    assert_manifest_error(tmp_path, value, "fallback_reason_unexpected")


def test_parse_accepts_null_reason_when_actual_matches_requested(
    tmp_path: Path,
) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "actual_model": "gpt-5.6-terra",
            "actual_reasoning": "high",
            "fallback_reason": None,
        }
    )

    parsed = parse_run_manifest(write_json(tmp_path / "run.json", value))

    assert parsed.fallback_reason is None


def test_parse_strips_requested_model_identifier(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "model")["requested_model"] = "  gpt-5.6-terra \t"

    parsed = parse_run_manifest(write_json(tmp_path / "run.json", value))

    assert parsed.requested_model == "gpt-5.6-terra"


def test_parse_strips_actual_model_identifier_before_comparison(
    tmp_path: Path,
) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "actual_model": " gpt-5.6-terra ",
            "actual_reasoning": "high",
            "fallback_reason": None,
        }
    )

    parsed = parse_run_manifest(write_json(tmp_path / "run.json", value))

    assert parsed.actual_model == "gpt-5.6-terra"


def test_parse_strips_nonblank_fallback_reason(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "actual_model": "gpt-5.6-sol",
            "actual_reasoning": "ultra",
            "fallback_reason": "  approved fallback \t",
        }
    )

    parsed = parse_run_manifest(write_json(tmp_path / "run.json", value))

    assert parsed.fallback_reason == "approved fallback"


@pytest.mark.parametrize("field", ["requested_model", "actual_model"])
def test_parse_rejects_whitespace_only_model_identifiers(
    tmp_path: Path,
    field: str,
) -> None:
    value = base_manifest()
    object_at(value, "model")[field] = " \t "
    if field == "actual_model":
        object_at(value, "model").update(
            {
                "actual_reasoning": "high",
                "fallback_reason": "approved fallback",
            }
        )

    assert_manifest_error(tmp_path, value, "empty_string")


@pytest.mark.parametrize("fallback_reason", ["", " \t "])
def test_parse_rejects_blank_fallback_reason_when_present(
    tmp_path: Path,
    fallback_reason: str,
) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "actual_model": "gpt-5.6-terra",
            "actual_reasoning": "high",
            "fallback_reason": fallback_reason,
        }
    )

    assert_manifest_error(tmp_path, value, "empty_string")


def test_parse_rejects_null_requested_model_even_with_reasoning(
    tmp_path: Path,
) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "requested_model": None,
            "requested_reasoning": "high",
        }
    )

    assert_manifest_error(tmp_path, value, "requested_model_missing")


def test_parse_rejects_fallback_reason_for_unverified_actual(
    tmp_path: Path,
) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "actual_model": "unverified",
            "actual_reasoning": "unverified",
            "fallback_reason": "runtime does not expose model identity",
        }
    )

    assert_manifest_error(tmp_path, value, "fallback_reason_unexpected")


def test_parse_requires_requested_model_and_reasoning(tmp_path: Path) -> None:
    for field in ("requested_model", "requested_reasoning"):
        value = base_manifest()
        object_at(value, "model")[field] = None

        assert_manifest_error(tmp_path, value, f"{field}_missing")


def test_parse_accepts_unverified_actual_without_fallback_reason(
    tmp_path: Path,
) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "actual_model": "unverified",
            "actual_reasoning": "unverified",
            "fallback_reason": None,
        }
    )

    parsed = parse_run_manifest(write_json(tmp_path / "run.json", value))

    assert parsed.actual_model == "unverified"
    assert parsed.actual_reasoning == "unverified"
    assert parsed.fallback_reason is None


@pytest.mark.parametrize(
    "path",
    [
        ("task_id",),
        ("objective",),
        ("runtime", "implementation_host"),
        ("data", "dataset_version"),
        ("data", "media_contract"),
        ("stop_conditions", "0"),
        ("deliverables", "0"),
    ],
)
def test_parse_rejects_blank_canonical_strings(
    tmp_path: Path,
    path: tuple[str, ...],
) -> None:
    value = base_manifest()
    if path[-1] == "0":
        array = value[path[0]]
        assert isinstance(array, list)
        array[0] = " \t "
    else:
        set_at(value, path, " \t ")

    expected = "invalid_array_item" if path[-1] == "0" else "empty_string"
    assert_manifest_error(tmp_path, value, expected)


@pytest.mark.parametrize(
    "path",
    [
        ("task_id",),
        ("objective",),
        ("runtime", "implementation_host"),
        ("data", "dataset_version"),
        ("data", "media_contract"),
        ("stop_conditions", "0"),
        ("deliverables", "0"),
    ],
)
def test_parse_rejects_control_characters_in_canonical_strings(
    tmp_path: Path,
    path: tuple[str, ...],
) -> None:
    value = base_manifest()
    if path[-1] == "0":
        array = value[path[0]]
        assert isinstance(array, list)
        array[0] = "safe\nforged"
    else:
        set_at(value, path, "safe\nforged")

    expected = (
        "invalid_array_item"
        if path[-1] == "0"
        else "control_character_forbidden"
    )
    assert_manifest_error(tmp_path, value, expected)


@pytest.mark.parametrize(
    "deadline",
    [
        "",
        "2026-07-27",
        "2026-07-27T00:00:00",
        "not-a-timestamp",
    ],
)
def test_parse_requires_null_or_timezone_aware_deadline(
    tmp_path: Path,
    deadline: str,
) -> None:
    value = base_manifest()
    object_at(value, "budget")["deadline"] = deadline

    assert_manifest_error(tmp_path, value, "invalid_deadline")


def test_parse_accepts_timezone_aware_deadline(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "budget")["deadline"] = "2026-07-27T00:00:00+09:00"

    parsed = parse_run_manifest(write_json(tmp_path / "run.json", value))

    assert parsed.deadline == "2026-07-27T00:00:00+09:00"


def test_p3_rejects_conflicting_duplicate_identity(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization").update(
        {
            "max_permission": "P3",
            "allowed_actions": ["production_deploy"],
            "p3_targets": [
                {
                    "kind": "production_deploy",
                    "target": "api.tera-ai.uk",
                    "rollback": "previous-release",
                    "canary": "one-instance",
                },
                {
                    "kind": "production_deploy",
                    "target": "api.tera-ai.uk",
                    "rollback": "different-release",
                    "canary": "different-canary",
                },
            ],
        }
    )

    assert_manifest_error(tmp_path, value, "duplicate_p3_target")


def test_p4_rejects_conflicting_duplicate_identity(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "authorization").update(
        {
            "max_permission": "P4",
            "allowed_actions": ["r2_delete"],
            "p4_actions": [
                {
                    "action": "r2_delete",
                    "target": "bounded-canary",
                    "approval_ref": "owner-approval-42",
                },
                {
                    "action": "r2_delete",
                    "target": "bounded-canary",
                    "approval_ref": "owner-approval-43",
                },
            ],
        }
    )

    assert_manifest_error(tmp_path, value, "duplicate_p4_action")


@pytest.mark.parametrize(
    ("action", "safety", "expected_code"),
    [
        (
            "production_deploy",
            {},
            "rollback_protection_required",
        ),
        (
            "runtime_service_write",
            {
                "requires_rollback": True,
                "requires_residue_zero": True,
                "requires_lock": True,
            },
            "host_guard_required",
        ),
        (
            "runtime_service_write",
            {
                "requires_rollback": True,
                "requires_residue_zero": True,
                "requires_host_guard": True,
            },
            "lock_required",
        ),
        (
            "disposable_db",
            {},
            "residue_zero_required",
        ),
        (
            "rollback_probe",
            {"requires_residue_zero": True},
            "rollback_protection_required",
        ),
    ],
)
def test_parse_enforces_action_safety_relationships(
    tmp_path: Path,
    action: str,
    safety: dict[str, bool],
    expected_code: str,
) -> None:
    value = base_manifest()
    authorization = object_at(value, "authorization")
    if action in {"production_deploy", "runtime_service_write"}:
        authorization.update(
            {
                "max_permission": "P3",
                "allowed_actions": [action],
                "p3_targets": [
                    {
                        "kind": action,
                        "target": "exact-target",
                        "rollback": "rollback-plan",
                        "canary": "canary-plan",
                    }
                ],
            }
        )
    else:
        authorization["allowed_actions"] = [action]
    object_at(value, "safety").update(safety)

    assert_manifest_error(tmp_path, value, expected_code)


def test_validate_start_requires_exact_git_and_artifact_provenance(
    tmp_path: Path,
) -> None:
    (
        _repo,
        manifest,
        _value,
        base_sha,
        start_manifest_sha,
    ) = start_manifest_repo(tmp_path)

    summary = validate_run_manifest(
        manifest,
        phase="start",
        host_lookup=lambda: "implementation.local",
    )

    assert summary.task_id == "research-contract-test"
    assert summary.repo_name == "repo"
    assert summary.base_commit_short == base_sha[:8]
    assert summary.start_manifest_commit_short == start_manifest_sha[:8]
    assert summary.implementation_commit_short is None
    assert summary.record_commit_short == start_manifest_sha[:8]
    assert summary.permission == "P2"
    assert summary.model == "gpt-5.6-terra"
    assert summary.runtime == "none"


def test_validate_rejects_invalid_phase_before_reading_manifest(
    tmp_path: Path,
) -> None:
    with pytest.raises(ManifestError, match="^invalid_phase$"):
        validate_run_manifest(tmp_path / "missing.json", phase="preview")


def test_validate_rejects_missing_repo(tmp_path: Path) -> None:
    value = base_manifest()
    source = object_at(value, "source")
    source["execution_repo"] = str(tmp_path / "missing-repo")
    source["design_path"] = str(tmp_path / "missing-repo" / "design.md")
    source["plan_path"] = str(tmp_path / "missing-repo" / "plan.md")

    with pytest.raises(ManifestError, match="^repo_missing$"):
        validate_run_manifest(
            write_json(tmp_path / "run.json", value),
            phase="start",
        )


def test_validate_rejects_repo_that_is_not_exact_git_root(
    tmp_path: Path,
) -> None:
    def mutate(value: dict[str, object]) -> None:
        repo = Path(str(object_at(value, "source")["execution_repo"]))
        object_at(value, "source")["execution_repo"] = str(repo / "docs")

    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path, mutate=mutate)

    with pytest.raises(ManifestError, match="^repo_not_git_root$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_rejects_branch_mismatch(tmp_path: Path) -> None:
    def mutate(value: dict[str, object]) -> None:
        object_at(value, "source")["branch"] = "codex/other"

    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path, mutate=mutate)

    with pytest.raises(ManifestError, match="^branch_mismatch$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_rejects_detached_head(tmp_path: Path) -> None:
    (
        repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path)
    git(repo, "checkout", "--detach")

    with pytest.raises(ManifestError, match="^branch_mismatch$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_probes_branch_with_symbolic_ref(tmp_path: Path) -> None:
    (
        repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path)
    calls: list[list[str]] = []

    def recording_runner(
        args: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.run(args, **kwargs)

    validate_run_manifest(
        manifest,
        phase="start",
        runner=recording_runner,
        host_lookup=lambda: "implementation.local",
    )

    assert [
        "git",
        "-C",
        str(repo),
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
    ] in calls
    assert not any("--abbrev-ref" in call for call in calls)


def test_validate_rejects_dirty_tree_when_clean_is_required(
    tmp_path: Path,
) -> None:
    (
        repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path)
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(ManifestError, match="^dirty_tree$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_parse_requires_clean_provenance(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "source")["require_clean"] = False

    assert_manifest_error(tmp_path, value, "clean_provenance_required")


def test_validate_uses_explicit_complete_status_probe(tmp_path: Path) -> None:
    (
        repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path)
    calls: list[list[str]] = []

    def recording_runner(
        args: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.run(args, **kwargs)

    validate_run_manifest(
        manifest,
        phase="start",
        runner=recording_runner,
        host_lookup=lambda: "implementation.local",
    )

    assert [
        "git",
        "-C",
        str(repo),
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignore-submodules=none",
    ] in calls


def test_validate_detects_untracked_files_when_git_config_hides_them(
    tmp_path: Path,
) -> None:
    (
        repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path)
    git(repo, "config", "status.showUntrackedFiles", "no")
    (repo / "hidden-by-config.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(ManifestError, match="^dirty_tree$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_rejects_missing_artifact(tmp_path: Path) -> None:
    def mutate(value: dict[str, object]) -> None:
        repo = Path(str(object_at(value, "source")["execution_repo"]))
        object_at(value, "source")["design_path"] = str(
            repo / "docs" / "missing.md"
        )

    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path, mutate=mutate)

    with pytest.raises(ManifestError, match="^artifact_missing$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_rejects_artifact_outside_repo(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")

    def mutate(value: dict[str, object]) -> None:
        object_at(value, "source")["design_path"] = str(outside)

    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path, mutate=mutate)

    with pytest.raises(ManifestError, match="^artifact_outside_repo$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_rejects_ignored_untracked_artifact(tmp_path: Path) -> None:
    repo, _design, plan, _sha = committed_repo(tmp_path)
    (repo / ".gitignore").write_text("docs/new-design.md\n", encoding="utf-8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "ignore test artifact")
    base_sha = git(repo, "rev-parse", "HEAD")
    design = repo / "docs" / "new-design.md"
    design.write_text("new\n", encoding="utf-8")
    value = manifest_for_repo(repo, design, plan, base_sha)
    object_at(value, "runtime")["implementation_host"] = "implementation.local"
    manifest = repo / "RUN-MANIFEST.json"
    write_json(manifest, value)
    git(repo, "add", "RUN-MANIFEST.json")
    git(repo, "commit", "-m", "start manifest")

    with pytest.raises(ManifestError, match="^artifact_untracked$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_rejects_artifact_modified_after_base(tmp_path: Path) -> None:
    repo, design, plan, base_sha = committed_repo(tmp_path)
    value = manifest_for_repo(repo, design, plan, base_sha)
    object_at(value, "runtime")["implementation_host"] = "implementation.local"
    design.write_text("modified after declared commit\n", encoding="utf-8")
    manifest = repo / "RUN-MANIFEST.json"
    write_json(manifest, value)
    git(repo, "add", "docs/design.md", "RUN-MANIFEST.json")
    git(repo, "commit", "-m", "start manifest with modified design")

    with pytest.raises(ManifestError, match="^artifact_modified$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_rejects_non_regular_artifact_mode(tmp_path: Path) -> None:
    repo, design, plan, _sha = committed_repo(tmp_path)
    design.unlink()
    design.symlink_to(plan.name)
    git(repo, "add", "docs/design.md")
    git(repo, "commit", "-m", "replace design with symlink")
    base_sha = git(repo, "rev-parse", "HEAD")
    value = manifest_for_repo(repo, design, plan, base_sha)
    object_at(value, "runtime")["implementation_host"] = "implementation.local"
    manifest = repo / "RUN-MANIFEST.json"
    write_json(manifest, value)
    git(repo, "add", "RUN-MANIFEST.json")
    git(repo, "commit", "-m", "start manifest")

    with pytest.raises(ManifestError, match="^artifact_invalid_mode$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_rejects_artifact_reached_through_symlink_parent(
    tmp_path: Path,
) -> None:
    repo, design, plan, base_sha = committed_repo(tmp_path)
    value = manifest_for_repo(repo, design, plan, base_sha)
    object_at(value, "runtime")["implementation_host"] = "implementation.local"
    real_docs = repo / "real-docs"
    (repo / "docs").rename(real_docs)
    (repo / "docs").symlink_to(real_docs.name, target_is_directory=True)
    manifest = repo / "RUN-MANIFEST.json"
    write_json(manifest, value)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "start manifest through symlink")

    with pytest.raises(ManifestError, match="^artifact_outside_repo$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_accepts_executable_regular_artifact(tmp_path: Path) -> None:
    repo, design, plan, _sha = committed_repo(tmp_path)
    design.chmod(0o755)
    git(repo, "add", "docs/design.md")
    git(repo, "commit", "-m", "make design executable")
    base_sha = git(repo, "rev-parse", "HEAD")
    value = manifest_for_repo(repo, design, plan, base_sha)
    object_at(value, "runtime")["implementation_host"] = "implementation.local"
    manifest = repo / "RUN-MANIFEST.json"
    write_json(manifest, value)
    git(repo, "add", "RUN-MANIFEST.json")
    git(repo, "commit", "-m", "start manifest")
    start_manifest_sha = git(repo, "rev-parse", "HEAD")

    summary = validate_run_manifest(
        manifest,
        phase="start",
        host_lookup=lambda: "implementation.local",
    )

    assert summary.base_commit_short == base_sha[:8]
    assert summary.start_manifest_commit_short == start_manifest_sha[:8]


@pytest.mark.parametrize(
    ("runtime_host", "runtime_label"),
    [
        ("runtime.local", None),
        (None, "com.petcam.worker"),
        ("runtime.local", "com.petcam.worker"),
    ],
)
def test_parse_rejects_runtime_fields_when_kind_is_none(
    tmp_path: Path,
    runtime_host: str | None,
    runtime_label: str | None,
) -> None:
    value = base_manifest()
    object_at(value, "runtime").update(
        {
            "runtime_host": runtime_host,
            "runtime_label": runtime_label,
        }
    )

    assert_manifest_error(tmp_path, value, "runtime_field_forbidden")


@pytest.mark.parametrize(
    ("runtime_host", "runtime_label", "expected_code"),
    [
        (None, "com.petcam.worker", "runtime_host_missing"),
        ("runtime.local", None, "runtime_label_missing"),
    ],
)
def test_parse_requires_runtime_fields_when_kind_is_not_none(
    tmp_path: Path,
    runtime_host: str | None,
    runtime_label: str | None,
    expected_code: str,
) -> None:
    value = base_manifest()
    object_at(value, "runtime").update(
        {
            "runtime_kind": "launchagent",
            "runtime_host": runtime_host,
            "runtime_label": runtime_label,
        }
    )

    assert_manifest_error(tmp_path, value, expected_code)


@pytest.mark.parametrize(
    ("field", "replacement", "expected_code"),
    [
        ("runtime_host", "", "runtime_host_missing"),
        ("runtime_host", " \t ", "runtime_host_missing"),
        ("runtime_label", "", "runtime_label_missing"),
        ("runtime_label", " \t ", "runtime_label_missing"),
    ],
)
def test_parse_rejects_blank_non_none_runtime_identity(
    tmp_path: Path,
    field: str,
    replacement: str,
    expected_code: str,
) -> None:
    value = base_manifest()
    object_at(value, "runtime").update(
        {
            "runtime_kind": "launchagent",
            "runtime_host": "runtime.local",
            "runtime_label": "com.petcam.worker",
            field: replacement,
        }
    )

    assert_manifest_error(tmp_path, value, expected_code)


@pytest.mark.parametrize(
    ("field", "replacement", "expected_code"),
    [
        ("runtime_host", "runtime.\nlocal", "runtime_host_invalid"),
        ("runtime_label", "com.petcam.\x7fworker", "runtime_label_invalid"),
    ],
)
def test_parse_rejects_control_characters_in_runtime_identity(
    tmp_path: Path,
    field: str,
    replacement: str,
    expected_code: str,
) -> None:
    value = base_manifest()
    object_at(value, "runtime").update(
        {
            "runtime_kind": "launchagent",
            "runtime_host": "runtime.local",
            "runtime_label": "com.petcam.worker",
            field: replacement,
        }
    )

    assert_manifest_error(tmp_path, value, expected_code)


def test_parse_canonicalizes_non_none_runtime_identity(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "runtime").update(
        {
            "runtime_kind": "launchagent",
            "runtime_host": "  runtime.local \t",
            "runtime_label": " com.petcam.worker ",
        }
    )

    parsed = parse_run_manifest(write_json(tmp_path / "run.json", value))

    assert parsed.runtime_host == "runtime.local"
    assert parsed.runtime_label == "com.petcam.worker"


def test_validate_formats_non_none_runtime(tmp_path: Path) -> None:
    def configure_runtime(value: dict[str, object]) -> None:
        object_at(value, "runtime").update(
            {
                "runtime_kind": "launchagent",
                "runtime_host": "runtime.local",
                "runtime_label": "com.petcam.worker",
            }
        )

    _, manifest, _, _, _ = start_manifest_repo(
        tmp_path,
        mutate=configure_runtime,
    )

    summary = validate_run_manifest(
        manifest,
        phase="start",
        host_lookup=lambda: "implementation.local",
    )

    assert summary.runtime == "launchagent@runtime.local"


def test_final_phase_requires_actual_model_and_reasoning(
    tmp_path: Path,
) -> None:
    def remove_actual_provenance(value: dict[str, object]) -> None:
        object_at(value, "model").update(
            {
                "actual_model": None,
                "actual_reasoning": None,
                "fallback_reason": None,
            }
        )

    _, manifest, _, _, _, _, _ = final_manifest_repo(
        tmp_path,
        mutate_final=remove_actual_provenance,
    )

    with pytest.raises(ManifestError, match="^actual_model_missing$"):
        validate_run_manifest(
            manifest,
            phase="final",
            host_lookup=lambda: "implementation.local",
        )


def test_final_phase_accepts_unverified_actual_provenance(
    tmp_path: Path,
) -> None:
    _, manifest, _, _, _, _, _ = final_manifest_repo(
        tmp_path,
    )

    summary = validate_run_manifest(
        manifest,
        phase="final",
        host_lookup=lambda: "implementation.local",
    )

    assert summary.model == "unverified"


def test_validate_start_accepts_dedicated_manifest_commit(
    tmp_path: Path,
) -> None:
    (
        _repo,
        manifest,
        _value,
        base_sha,
        start_manifest_sha,
    ) = start_manifest_repo(tmp_path)

    summary = validate_run_manifest(
        manifest,
        phase="start",
        host_lookup=lambda: "implementation.local",
    )

    assert summary.base_commit_short == base_sha[:8]
    assert summary.start_manifest_commit_short == start_manifest_sha[:8]
    assert summary.implementation_commit_short is None
    assert summary.record_commit_short == start_manifest_sha[:8]


def test_validate_start_rejects_manifest_commit_with_other_changes(
    tmp_path: Path,
) -> None:
    repo, design, plan, base_sha = committed_repo(tmp_path)
    value = manifest_for_repo(repo, design, plan, base_sha)
    object_at(value, "runtime")["implementation_host"] = "implementation.local"
    manifest = repo / "docs" / "research" / "RUN-MANIFEST.json"
    manifest.parent.mkdir()
    write_json(manifest, value)
    (repo / "implementation.txt").write_text("too early\n", encoding="utf-8")
    git(repo, "add", "docs/research/RUN-MANIFEST.json", "implementation.txt")
    git(repo, "commit", "-m", "mixed start manifest")

    with pytest.raises(
        ManifestError,
        match="^start_manifest_commit_not_dedicated$",
    ):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_start_requires_manifest_inside_execution_repo(
    tmp_path: Path,
) -> None:
    (
        _repo,
        _manifest,
        value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path)
    outside = write_json(tmp_path / "outside.json", value)

    with pytest.raises(ManifestError, match="^manifest_outside_repo$"):
        validate_run_manifest(
            outside,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_start_requires_manifest_bytes_from_current_head(
    tmp_path: Path,
) -> None:
    (
        _repo,
        manifest,
        value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path)
    value["objective"] = "modified after commit"
    write_json(manifest, value)

    with pytest.raises(ManifestError, match="^manifest_modified$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_start_requires_base_as_manifest_commit_parent(
    tmp_path: Path,
) -> None:
    repo, design, plan, base_sha = committed_repo(tmp_path)
    (repo / "intermediate.txt").write_text("intermediate\n", encoding="utf-8")
    git(repo, "add", "intermediate.txt")
    git(repo, "commit", "-m", "intermediate")
    value = manifest_for_repo(repo, design, plan, base_sha)
    object_at(value, "source").update(
        {
            "start_manifest_commit_sha": None,
            "final_commit_sha": None,
        }
    )
    object_at(value, "runtime")["implementation_host"] = "implementation.local"
    manifest = repo / "RUN-MANIFEST.json"
    write_json(manifest, value)
    git(repo, "add", "RUN-MANIFEST.json")
    git(repo, "commit", "-m", "start manifest")

    with pytest.raises(ManifestError, match="^start_base_not_parent$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


@pytest.mark.parametrize(
    ("path", "replacement", "expected_code"),
    [
        (("source", "start_manifest_commit_sha"), "1" * 40, "start_provenance_not_null"),
        (("source", "final_commit_sha"), "2" * 40, "start_provenance_not_null"),
        (("model", "actual_model"), "unverified", "start_provenance_not_null"),
        (("model", "actual_reasoning"), "unverified", "start_provenance_not_null"),
        (("model", "fallback_reason"), "unexpected", "fallback_reason_unexpected"),
    ],
)
def test_validate_start_requires_unstarted_lifecycle_fields(
    tmp_path: Path,
    path: tuple[str, ...],
    replacement: str,
    expected_code: str,
) -> None:
    def mutate(value: dict[str, object]) -> None:
        set_at(value, path, replacement)
        if path == ("model", "actual_model"):
            object_at(value, "model")["actual_reasoning"] = "unverified"
        elif path == ("model", "actual_reasoning"):
            object_at(value, "model")["actual_model"] = "unverified"

    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path, mutate=mutate)

    with pytest.raises(ManifestError, match=f"^{expected_code}$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_final_accepts_base_start_implementation_record_chain(
    tmp_path: Path,
) -> None:
    (
        _repo,
        manifest,
        _value,
        base_sha,
        start_manifest_sha,
        implementation_sha,
        record_sha,
    ) = final_manifest_repo(tmp_path)

    summary = validate_run_manifest(
        manifest,
        phase="final",
        host_lookup=lambda: "implementation.local",
    )

    assert summary.base_commit_short == base_sha[:8]
    assert summary.start_manifest_commit_short == start_manifest_sha[:8]
    assert summary.implementation_commit_short == implementation_sha[:8]
    assert summary.record_commit_short == record_sha[:8]


def test_validate_final_requires_implementation_after_start_manifest(
    tmp_path: Path,
) -> None:
    (
        repo,
        manifest,
        value,
        _base_sha,
        start_manifest_sha,
    ) = start_manifest_repo(tmp_path)
    object_at(value, "source").update(
        {
            "start_manifest_commit_sha": start_manifest_sha,
            "final_commit_sha": start_manifest_sha,
        }
    )
    object_at(value, "model").update(
        {
            "actual_model": "unverified",
            "actual_reasoning": "unverified",
            "fallback_reason": None,
        }
    )
    write_json(manifest, value)
    git(repo, "add", "docs/research/RUN-MANIFEST.json")
    git(repo, "commit", "-m", "final record without implementation")

    with pytest.raises(
        ManifestError,
        match="^implementation_commit_not_after_start$",
    ):
        validate_run_manifest(
            manifest,
            phase="final",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_final_rejects_manifest_changed_during_implementation(
    tmp_path: Path,
) -> None:
    (
        repo,
        manifest,
        value,
        _base_sha,
        start_manifest_sha,
    ) = start_manifest_repo(tmp_path)
    transient = json.loads(json.dumps(value))
    transient["objective"] = "transient implementation rewrite"
    write_json(manifest, transient)
    (repo / "implementation.txt").write_text("implemented\n", encoding="utf-8")
    git(repo, "add", "docs/research/RUN-MANIFEST.json", "implementation.txt")
    git(repo, "commit", "-m", "implementation with manifest rewrite")
    implementation_sha = git(repo, "rev-parse", "HEAD")

    object_at(value, "source").update(
        {
            "start_manifest_commit_sha": start_manifest_sha,
            "final_commit_sha": implementation_sha,
        }
    )
    object_at(value, "model").update(
        {
            "actual_model": "unverified",
            "actual_reasoning": "unverified",
            "fallback_reason": None,
        }
    )
    write_json(manifest, value)
    git(repo, "add", "docs/research/RUN-MANIFEST.json")
    git(repo, "commit", "-m", "final record")

    with pytest.raises(
        ManifestError,
        match="^manifest_changed_before_final_record$",
    ):
        validate_run_manifest(
            manifest,
            phase="final",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_final_rejects_record_commit_with_other_changes(
    tmp_path: Path,
) -> None:
    (
        repo,
        manifest,
        value,
        _base_sha,
        _start_manifest_sha,
        _implementation_sha,
        _record_sha,
    ) = final_manifest_repo(tmp_path)
    git(repo, "reset", "--soft", "HEAD^")
    git(repo, "reset")
    write_json(manifest, value)
    (repo / "report.txt").write_text("mixed final record\n", encoding="utf-8")
    git(repo, "add", "docs/research/RUN-MANIFEST.json", "report.txt")
    git(repo, "commit", "-m", "mixed final record")

    with pytest.raises(
        ManifestError,
        match="^final_record_commit_not_dedicated$",
    ):
        validate_run_manifest(
            manifest,
            phase="final",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_final_requires_implementation_as_record_parent(
    tmp_path: Path,
) -> None:
    (
        repo,
        manifest,
        value,
        _base_sha,
        _start_manifest_sha,
        implementation_sha,
        _record_sha,
    ) = final_manifest_repo(tmp_path)
    git(repo, "reset", "--soft", "HEAD^")
    git(repo, "reset")
    (repo / "intermediate-report.txt").write_text("intermediate\n", encoding="utf-8")
    git(repo, "add", "intermediate-report.txt")
    git(repo, "commit", "-m", "intermediate report")
    assert git(repo, "rev-parse", "HEAD") != implementation_sha
    write_json(manifest, value)
    git(repo, "add", "docs/research/RUN-MANIFEST.json")
    git(repo, "commit", "-m", "final record")

    with pytest.raises(ManifestError, match="^final_commit_not_parent$"):
        validate_run_manifest(
            manifest,
            phase="final",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_final_rejects_immutable_manifest_field_change(
    tmp_path: Path,
) -> None:
    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
        _implementation_sha,
        _record_sha,
    ) = final_manifest_repo(
        tmp_path,
        mutate_final=lambda value: value.update(
            {"objective": "silently expanded objective"}
        ),
    )

    with pytest.raises(ManifestError, match="^immutable_field_changed$"):
        validate_run_manifest(
            manifest,
            phase="final",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_compares_current_host_with_implementation_host(
    tmp_path: Path,
) -> None:
    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path)

    with pytest.raises(ManifestError, match="^implementation_host_mismatch$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "different-host.local",
        )


def test_validate_fails_closed_when_current_host_lookup_fails(
    tmp_path: Path,
) -> None:
    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path)

    def fail_lookup() -> str:
        raise OSError("host unavailable")

    with pytest.raises(ManifestError, match="^host_probe_failed$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=fail_lookup,
        )


@pytest.mark.parametrize("permission", ["P3", "P4"])
def test_validate_privileged_manifest_requires_trusted_approval_verifier(
    tmp_path: Path,
    permission: str,
) -> None:
    def mutate(value: dict[str, object]) -> None:
        authorization = object_at(value, "authorization")
        safety = object_at(value, "safety")
        if permission == "P3":
            authorization.update(
                {
                    "max_permission": "P3",
                    "allowed_actions": ["production_deploy"],
                    "p3_targets": [
                        {
                            "kind": "production_deploy",
                            "target": "api.tera-ai.uk",
                            "rollback": "previous-release",
                            "canary": "one-instance",
                        }
                    ],
                }
            )
            safety.update(
                {
                    "requires_rollback": True,
                    "requires_residue_zero": True,
                }
            )
        else:
            authorization.update(
                {
                    "max_permission": "P4",
                    "allowed_actions": ["r2_delete"],
                    "p4_actions": [
                        {
                            "action": "r2_delete",
                            "target": "bounded-canary",
                            "approval_ref": "owner-approval-42",
                        }
                    ],
                }
            )

    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path, mutate=mutate)

    with pytest.raises(ManifestError, match="^approval_verifier_missing$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_privileged_manifest_uses_injected_trusted_approval(
    tmp_path: Path,
) -> None:
    def mutate(value: dict[str, object]) -> None:
        object_at(value, "authorization").update(
            {
                "max_permission": "P3",
                "allowed_actions": ["production_deploy"],
                "p3_targets": [
                    {
                        "kind": "production_deploy",
                        "target": "api.tera-ai.uk",
                        "rollback": "previous-release",
                        "canary": "one-instance",
                    }
                ],
            }
        )
        object_at(value, "safety").update(
            {
                "requires_rollback": True,
                "requires_residue_zero": True,
            }
        )

    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path, mutate=mutate)
    calls: list[tuple[str, str]] = []

    def approve(parsed: object, phase: str) -> bool:
        calls.append((parsed.max_permission, phase))
        return True

    summary = validate_run_manifest(
        manifest,
        phase="start",
        host_lookup=lambda: "implementation.local",
        approval_verifier=approve,
    )

    assert summary.permission == "P3"
    assert calls == [("P3", "start")]


def test_validate_privileged_manifest_rejects_untrusted_approval(
    tmp_path: Path,
) -> None:
    def mutate(value: dict[str, object]) -> None:
        object_at(value, "authorization").update(
            {
                "max_permission": "P3",
                "allowed_actions": ["production_deploy"],
                "p3_targets": [
                    {
                        "kind": "production_deploy",
                        "target": "api.tera-ai.uk",
                        "rollback": "previous-release",
                        "canary": "one-instance",
                    }
                ],
            }
        )
        object_at(value, "safety").update(
            {
                "requires_rollback": True,
                "requires_residue_zero": True,
            }
        )

    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(tmp_path, mutate=mutate)

    with pytest.raises(ManifestError, match="^approval_not_verified$"):
        validate_run_manifest(
            manifest,
            phase="start",
            host_lookup=lambda: "implementation.local",
            approval_verifier=lambda _manifest, _phase: False,
        )


def test_validate_final_non_none_runtime_requires_attestation_verifier(
    tmp_path: Path,
) -> None:
    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
        _implementation_sha,
        _record_sha,
    ) = final_manifest_repo(tmp_path, runtime_kind="launchagent")

    with pytest.raises(
        ManifestError,
        match="^runtime_attestation_verifier_missing$",
    ):
        validate_run_manifest(
            manifest,
            phase="final",
            host_lookup=lambda: "implementation.local",
        )


def test_validate_final_non_none_runtime_uses_injected_attestation(
    tmp_path: Path,
) -> None:
    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
        _implementation_sha,
        _record_sha,
    ) = final_manifest_repo(tmp_path, runtime_kind="launchagent")
    calls: list[tuple[str, str | None, str | None]] = []

    def attest(parsed: object) -> bool:
        calls.append(
            (parsed.runtime_kind, parsed.runtime_host, parsed.runtime_label)
        )
        return True

    summary = validate_run_manifest(
        manifest,
        phase="final",
        host_lookup=lambda: "implementation.local",
        runtime_attestation_verifier=attest,
    )

    assert summary.runtime == "launchagent@runtime.local"
    assert calls == [("launchagent", "runtime.local", "com.petcam.worker")]


def shared_schema_parser_corpus() -> list[tuple[str, dict[str, object], bool]]:
    valid = base_manifest()
    object_at(valid, "source").update(
        {
            "start_manifest_commit_sha": None,
            "final_commit_sha": None,
        }
    )

    def changed(
        name: str,
        path: tuple[str, ...],
        replacement: object,
    ) -> tuple[str, dict[str, object], bool]:
        value = json.loads(json.dumps(valid))
        set_at(value, path, replacement)
        return name, value, False

    return [
        ("valid-start", valid, True),
        changed("clean-false", ("source", "require_clean"), False),
        changed("blank-task", ("task_id",), " \t "),
        changed("naive-deadline", ("budget", "deadline"), "2026-07-27T00:00:00"),
        changed("requested-model-null", ("model", "requested_model"), None),
        changed(
            "runtime-none-with-host",
            ("runtime", "runtime_host"),
            "runtime.local",
        ),
        changed(
            "unknown-action",
            ("authorization", "allowed_actions"),
            ["invented_action"],
        ),
        changed(
            "duplicate-action",
            ("authorization", "allowed_actions"),
            ["docs_write", "docs_write"],
        ),
    ]


@pytest.mark.parametrize(
    ("_name", "value", "is_valid"),
    shared_schema_parser_corpus(),
    ids=[item[0] for item in shared_schema_parser_corpus()],
)
def test_draft_202012_and_parser_corpus_parity(
    tmp_path: Path,
    _name: str,
    value: dict[str, object],
    is_valid: bool,
) -> None:
    schema = json.loads(
        Path("docs/research/RUN-MANIFEST.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    schema_errors = list(validator.iter_errors(value))
    manifest = write_json(tmp_path / f"{_name}.json", value)

    if is_valid:
        assert schema_errors == []
        parse_run_manifest(manifest)
    else:
        assert schema_errors
        with pytest.raises(ManifestError):
            parse_run_manifest(manifest)


def test_validate_uses_injected_subprocess_runner(tmp_path: Path) -> None:
    repo, design, plan, sha = committed_repo(tmp_path)
    value = manifest_for_repo(repo, design, plan, sha)
    calls: list[list[str]] = []

    def failing_runner(
        args: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="")

    with pytest.raises(ManifestError, match="^git_probe_failed$"):
        validate_run_manifest(
            write_json(tmp_path / "run.json", value),
            phase="start",
            runner=failing_runner,
        )

    assert calls == [["git", "-C", str(repo), "rev-parse", "--show-toplevel"]]


def test_cli_schema_only_skips_git_probes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = write_json(tmp_path / "run.json", base_manifest())

    exit_code = main(
        [
            "--manifest",
            str(manifest),
            "--phase",
            "start",
            "--schema-only",
        ]
    )

    assert exit_code == 0
    assert (
        capsys.readouterr().out
        == "RUN_MANIFEST_SCHEMA_OK task=research-contract-test permission=P2\n"
    )


def test_cli_success_prints_stable_marker(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (
        _repo,
        manifest,
        _value,
        base_sha,
        start_manifest_sha,
    ) = start_manifest_repo(
        tmp_path,
        implementation_host=socket.gethostname(),
    )

    exit_code = main(["--manifest", str(manifest), "--phase", "start"])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "RUN_MANIFEST_OK task=research-contract-test repo=repo "
        f"base={base_sha[:8]} start_manifest={start_manifest_sha[:8]} "
        f"implementation=none record={start_manifest_sha[:8]} "
        "permission=P2 model=gpt-5.6-terra runtime=none\n"
    )


def test_cli_schema_marker_percent_encodes_unsafe_task_id(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    value = base_manifest()
    value["task_id"] = "task name %"
    manifest = write_json(tmp_path / "run.json", value)

    exit_code = main(
        [
            "--manifest",
            str(manifest),
            "--phase",
            "start",
            "--schema-only",
        ]
    )

    assert exit_code == 0
    assert (
        capsys.readouterr().out
        == "RUN_MANIFEST_SCHEMA_OK task=task%20name%20%25 permission=P2\n"
    )


def test_cli_success_marker_percent_encodes_all_dynamic_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def mutate(value: dict[str, object]) -> None:
        value["task_id"] = "task name %"
        object_at(value, "model")["requested_model"] = "model name %"
        object_at(value, "runtime").update(
            {
                "runtime_kind": "oneshot",
                "runtime_host": "runtime host",
                "runtime_label": "runtime label",
            }
        )

    (
        _repo,
        manifest,
        _value,
        base_sha,
        start_manifest_sha,
    ) = start_manifest_repo(
        tmp_path,
        mutate=mutate,
        implementation_host=socket.gethostname(),
        repo_name="repo name %",
    )

    exit_code = main(["--manifest", str(manifest), "--phase", "start"])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "RUN_MANIFEST_OK task=task%20name%20%25 "
        "repo=repo%20name%20%25 "
        f"base={base_sha[:8]} start_manifest={start_manifest_sha[:8]} "
        f"implementation=none record={start_manifest_sha[:8]} "
        "permission=P2 "
        "model=model%20name%20%25 "
        "runtime=oneshot@runtime%20host\n"
    )


def test_cli_failure_prints_only_stable_code_and_exits_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = write_json(tmp_path / "run.json", base_manifest())

    exit_code = main(["--manifest", str(manifest), "--phase", "start"])

    assert exit_code == 2
    assert capsys.readouterr().out == "RUN_MANIFEST_FAIL code=repo_missing\n"


def test_cli_fails_closed_for_p3_without_trusted_backend(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def mutate(value: dict[str, object]) -> None:
        object_at(value, "authorization").update(
            {
                "max_permission": "P3",
                "allowed_actions": ["production_deploy"],
                "p3_targets": [
                    {
                        "kind": "production_deploy",
                        "target": "api.tera-ai.uk",
                        "rollback": "previous-release",
                        "canary": "one-instance",
                    }
                ],
            }
        )
        object_at(value, "safety").update(
            {
                "requires_rollback": True,
                "requires_residue_zero": True,
            }
        )

    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
    ) = start_manifest_repo(
        tmp_path,
        mutate=mutate,
        implementation_host=socket.gethostname(),
    )

    exit_code = main(["--manifest", str(manifest), "--phase", "start"])

    assert exit_code == 2
    assert (
        capsys.readouterr().out
        == "RUN_MANIFEST_FAIL code=approval_verifier_missing\n"
    )


def test_cli_final_fails_closed_without_runtime_attestation_backend(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (
        _repo,
        manifest,
        _value,
        _base_sha,
        _start_manifest_sha,
        _implementation_sha,
        _record_sha,
    ) = final_manifest_repo(
        tmp_path,
        runtime_kind="launchagent",
        implementation_host=socket.gethostname(),
    )

    exit_code = main(["--manifest", str(manifest), "--phase", "final"])

    assert exit_code == 2
    assert (
        capsys.readouterr().out
        == "RUN_MANIFEST_FAIL code=runtime_attestation_verifier_missing\n"
    )


def test_cli_invalid_phase_uses_stable_failure_marker(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = write_json(tmp_path / "run.json", base_manifest())

    exit_code = main(["--manifest", str(manifest), "--phase", "preview"])

    assert exit_code == 2
    assert capsys.readouterr().out == "RUN_MANIFEST_FAIL code=invalid_phase\n"


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--manifest"],
        ["--manifest", "private-value", "--phase"],
        ["--unknown", "private\nvalue"],
        ["--man", "private-value", "--phase", "start"],
    ],
)
def test_cli_argument_errors_do_not_echo_inputs_or_usage(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(argv)

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == "RUN_MANIFEST_FAIL code=invalid_arguments\n"
    assert captured.err == ""
