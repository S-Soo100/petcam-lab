import json
from pathlib import Path


CONTRACT = Path("docs/research/AI-OPERATING-CONTRACT.md")
SCHEMA = Path("docs/research/RUN-MANIFEST.schema.json")
EXAMPLE = Path("docs/research/RUN-MANIFEST.example.json")


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
