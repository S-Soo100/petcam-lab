import re
from pathlib import Path

_PATTERNS = (
    re.compile(r"(?i)authorization:\s*bearer\s+\S+"),
    re.compile(r"(?i)(?:X-Amz-Signature|signature|signed_url)=[^&\s]+"),
    re.compile(r"(?i)rtsp://[^/\s]+"),
    re.compile(r"(?i)(?:webhook|api[_-]?key|password|secret|token)[=:]\S+"),
    re.compile(r"https://hooks\.[^\s]+"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
)


def redact_text(text: str, *, home: Path) -> str:
    result = text.replace(str(home), "$HOME")
    for pattern in _PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def safe_error_detail(value: str, *, home: Path) -> str:
    try:
        return redact_text(value, home=home)[:512]
    except (UnicodeError, re.error, ValueError):
        return "redaction_failed"
