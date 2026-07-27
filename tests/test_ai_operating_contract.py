from pathlib import Path


CONTRACT = Path("docs/research/AI-OPERATING-CONTRACT.md")


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
