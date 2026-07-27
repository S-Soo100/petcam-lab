import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


CONTRACT = Path("docs/research/AI-OPERATING-CONTRACT.md")
SCHEMA = Path("docs/research/RUN-MANIFEST.schema.json")
EXAMPLE = Path("docs/research/RUN-MANIFEST.example.json")
REPORT = Path("docs/handoff-prompts/2026-07-27-ai-operating-contract-report.md")


def test_agent_entrypoints_link_contract_without_copying_it() -> None:
    for path in (Path("AGENTS.md"), Path("CLAUDE.md")):
        text = path.read_text(encoding="utf-8")
        assert "docs/research/AI-OPERATING-CONTRACT.md" in text
        assert "verify_research_run_manifest.py" in text


def test_agent_entrypoints_use_exact_four_line_contract_blocks() -> None:
    for path in (Path("AGENTS.md"), Path("CLAUDE.md")):
        lines = path.read_text(encoding="utf-8").splitlines()
        start = lines.index("### AI 연구 실행 계약")
        assert lines[start : start + 4] == [
            "### AI 연구 실행 계약",
            "",
            (
                "Standard 이상 연구는 "
                "[`docs/research/AI-OPERATING-CONTRACT.md`]"
                "(docs/research/AI-OPERATING-CONTRACT.md)를 따르고 실행 전"
            ),
            (
                "[`scripts/verify_research_run_manifest.py`]"
                "(scripts/verify_research_run_manifest.py)로 run manifest를 검증해."
            ),
        ]


def test_catalog_registers_ai_operating_contract() -> None:
    catalog = json.loads(Path("docs/research/catalog.json").read_text(encoding="utf-8"))
    item = next(row for row in catalog["research"] if row["id"] == "ai-operating-contract-v1")
    assert item["status"] == "operational"
    assert "docs/research/AI-OPERATING-CONTRACT.md" in item["canonical"]["documents"]


def test_catalog_ai_operating_contract_canonical_is_complete() -> None:
    catalog = json.loads(Path("docs/research/catalog.json").read_text(encoding="utf-8"))
    item = next(row for row in catalog["research"] if row["id"] == "ai-operating-contract-v1")
    canonical = item["canonical"]

    assert canonical["repository"] == "petcam-lab"
    assert canonical["branch"] == "codex/research-catalog-20260727"
    assert re.fullmatch(r"[0-9a-f]{40}", canonical["commit"])
    assert set(canonical["documents"]) == {
        "docs/research/AI-OPERATING-CONTRACT.md",
        "docs/research/RUN-MANIFEST.schema.json",
        "docs/research/RUN-MANIFEST.example.json",
        "scripts/verify_research_run_manifest.py",
    }
    assert all(Path(path).is_file() for path in canonical["documents"])


def test_ai_operating_contract_contains_permission_and_model_contracts() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    for required in (
        "P0",
        "P1",
        "P2",
        "P3",
        "P4",
        "P0~P2",
        "frontier_planning",
        "critical_engineering",
        "standard_execution",
        "independent_review",
        "requested_model",
        "actual_model",
        "RUN-MANIFEST",
    ):
        assert required in text


def test_ai_operating_contract_keeps_destructive_actions_owner_gated() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    assert "P4는 항상 별도 Owner 승인" in text
    assert "비밀번호·API key·webhook·cookie·signed URL을 기록하지 않는다" in text
    assert "만료 여부" in text


def test_run_manifest_schema_is_closed_and_has_required_sections() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
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
    ]


def test_run_manifest_example_contains_no_secret_fields() -> None:
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    forbidden = {"password", "api_key", "webhook", "cookie", "signed_url", "secret"}

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(v) for v in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(v) for v in value), set())
        return set()

    assert not (keys(example) & forbidden)
    assert example["authorization"]["max_permission"] == "P2"


def test_run_manifest_example_has_unstarted_model_provenance() -> None:
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert example["task_id"] == "research-run-example"
    assert example["model"]["actual_model"] is None
    assert example["model"]["actual_reasoning"] is None
    assert example["model"]["fallback_reason"] is None


def test_run_manifest_schema_allows_null_fallback_reason() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fallback_reason = schema["properties"]["model"]["properties"]["fallback_reason"]
    assert fallback_reason["type"] == ["string", "null"]
    assert fallback_reason["minLength"] == 1


def test_run_manifest_schema_and_example_allow_no_runtime() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    runtime = schema["properties"]["runtime"]["properties"]
    for field in ("runtime_host", "runtime_label"):
        assert runtime[field]["type"] == ["string", "null"]
        assert runtime[field]["minLength"] == 1

    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert example["runtime"]["runtime_kind"] == "none"
    assert example["runtime"]["runtime_host"] is None
    assert example["runtime"]["runtime_label"] is None


def test_run_manifest_schema_closes_privileged_approval_objects() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    authorization = schema["properties"]["authorization"]["properties"]

    p3_target = authorization["p3_targets"]["items"]
    assert p3_target["type"] == "object"
    assert p3_target["additionalProperties"] is False
    assert p3_target["required"] == ["kind", "target", "rollback", "canary"]
    assert set(p3_target["properties"]) == {"kind", "target", "rollback", "canary"}
    assert all(p3_target["properties"][field] for field in p3_target["properties"])
    assert p3_target["properties"]["kind"]["enum"] == [
        "production_migration",
        "production_deploy",
        "runtime_service_write",
    ]

    p4_action = authorization["p4_actions"]["items"]
    assert p4_action["type"] == "object"
    assert p4_action["additionalProperties"] is False
    assert p4_action["required"] == ["action", "target", "approval_ref"]
    assert set(p4_action["properties"]) == {"action", "target", "approval_ref"}
    assert all(p4_action["properties"][field] for field in p4_action["properties"])
    assert p4_action["properties"]["action"]["enum"] == [
        "database_delete",
        "r2_delete",
        "destructive_git",
        "credential_change",
        "cost_limit_increase",
    ]


def test_run_manifest_schema_enumerates_unique_actions_and_arrays() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    properties = schema["properties"]
    authorization = properties["authorization"]["properties"]
    all_actions = {
        action
        for actions in (
            [],
            [
                "docs_write",
                "local_code_write",
                "feature_branch_commit",
                "feature_branch_push",
            ],
            [
                "preview_deploy",
                "disposable_db",
                "rollback_probe",
                "nonproduction_canary",
            ],
            [
                "production_migration",
                "production_deploy",
                "runtime_service_write",
            ],
            [
                "database_delete",
                "r2_delete",
                "destructive_git",
                "credential_change",
                "cost_limit_increase",
            ],
        )
        for action in actions
    }

    assert set(authorization["allowed_actions"]["items"]["enum"]) == all_actions
    for section in (
        authorization["allowed_actions"],
        authorization["p3_targets"],
        authorization["p4_actions"],
        properties["data"]["properties"]["splits"],
        properties["stop_conditions"],
        properties["deliverables"],
    ):
        assert section["uniqueItems"] is True


def test_run_manifest_schema_models_lifecycle_and_deadline() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    source = schema["properties"]["source"]
    assert source["required"] == [
        "execution_repo",
        "branch",
        "commit_sha",
        "start_manifest_commit_sha",
        "final_commit_sha",
        "design_path",
        "plan_path",
        "require_clean",
    ]
    assert source["properties"]["require_clean"] == {"const": True}
    for field in ("start_manifest_commit_sha", "final_commit_sha"):
        assert source["properties"][field]["type"] == ["string", "null"]
        assert source["properties"][field]["pattern"] == "^[0-9a-f]{40}$"

    deadline = schema["properties"]["budget"]["properties"]["deadline"]
    assert deadline["type"] == ["string", "null"]
    assert deadline["format"] == "date-time"


def test_draft_202012_validator_accepts_example_with_format_checking() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    assert list(validator.iter_errors(example)) == []


def test_contract_documents_fail_closed_lifecycle_and_status_vocabulary() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    for required in (
        "start_manifest_commit_sha",
        "final_commit_sha",
        "trusted approval verifier",
        "runtime attestation verifier",
        "PREVIEW_READY",
    ):
        assert required in text
    assert "PREVIEW_VERIFIED" not in text


def test_report_waits_for_controller_independent_review() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert "`IMPLEMENTED_AWAITING_FINAL_REVIEW`" in text
    assert "prior final review findings" in text
    assert "`AI_OPERATING_CONTRACT_V1_VERIFIED`" not in text
