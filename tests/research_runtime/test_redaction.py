from pathlib import Path

import pytest

from backend.research_runtime.redaction import redact_text, safe_error_detail


@pytest.mark.parametrize(
    "secret",
    [
        "Authorization: Bearer fake-token-value",
        "https://example.invalid/x?X-Amz-Signature=abcdef",
        "rtsp://user:pass@example.invalid/live",
        "SLACK_WEBHOOK_URL=https://hooks.slack.invalid/abc",
        "owner@example.com",
        "/Users/baek-end/private/file",
    ],
)
def test_redactor_removes_secret_like_values(secret: str) -> None:
    redacted = redact_text(secret, home=Path("/Users/baek-end"))
    assert secret not in redacted
    assert "fake-token-value" not in redacted
    assert "pass@" not in redacted
    assert "/Users/baek-end" not in redacted


def test_safe_error_detail_is_bounded() -> None:
    result = safe_error_detail("x" * 1000, home=Path("/Users/baek"))
    assert len(result) == 512
