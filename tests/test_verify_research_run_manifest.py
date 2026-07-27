import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from scripts.verify_research_run_manifest import ManifestError, parse_run_manifest


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
    ("actual_model", "actual_reasoning"),
    [
        ("gpt-5.6-terra", None),
        (None, "high"),
    ],
)
def test_parse_rejects_partial_actual_model_provenance(
    tmp_path: Path,
    actual_model: str | None,
    actual_reasoning: str | None,
) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "actual_model": actual_model,
            "actual_reasoning": actual_reasoning,
        }
    )

    assert_manifest_error(tmp_path, value, "actual_provenance_incomplete")


@pytest.mark.parametrize("fallback_reason", [None, "", " \t "])
def test_parse_requires_reason_when_actual_differs_from_requested(
    tmp_path: Path,
    fallback_reason: str | None,
) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "actual_model": "gpt-5.6-sol",
            "actual_reasoning": "ultra",
            "fallback_reason": fallback_reason,
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


@pytest.mark.parametrize("fallback_reason", [None, "", " \t "])
def test_parse_accepts_blank_reason_when_actual_matches_requested(
    tmp_path: Path,
    fallback_reason: str | None,
) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "actual_model": "gpt-5.6-terra",
            "actual_reasoning": "high",
            "fallback_reason": fallback_reason,
        }
    )

    parsed = parse_run_manifest(write_json(tmp_path / "run.json", value))

    assert parsed.fallback_reason is None


def test_parse_accepts_unverified_actual_with_reason(tmp_path: Path) -> None:
    value = base_manifest()
    object_at(value, "model").update(
        {
            "actual_model": "unverified",
            "actual_reasoning": "unverified",
            "fallback_reason": "runtime does not expose model identity",
        }
    )

    parsed = parse_run_manifest(write_json(tmp_path / "run.json", value))

    assert parsed.actual_model == "unverified"
    assert parsed.actual_reasoning == "unverified"
