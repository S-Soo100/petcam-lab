from __future__ import annotations

import json

from backend.rap_c500g_manager_notify import SlackWebhookNotifier


class Response:
    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b"ok"


def test_slack_notification_is_bounded_and_secret_free() -> None:
    sent: list[tuple[str, bytes, float]] = []

    def opener(request, timeout: float):
        sent.append((request.full_url, request.data, timeout))
        return Response()

    notifier = SlackWebhookNotifier("https://hooks.slack.test/private-token", opener=opener)
    notifier(
        "camera_terminal",
        {
            "camera_key": "cam02",
            "slot": "2026-09-01T20:00:00+09:00",
            "code": "capture_RuntimeError",
            "password": "must-not-leak",
        },
    )

    assert len(sent) == 1
    url, body, timeout = sent[0]
    payload = json.loads(body)
    assert url.endswith("private-token")
    assert timeout == 5.0
    assert "must-not-leak" not in payload["text"]
    assert "cam02" in payload["text"]
    assert "capture_RuntimeError" in payload["text"]


def test_missing_slack_webhook_is_a_safe_noop() -> None:
    called = False

    def opener(request, timeout: float):
        nonlocal called
        called = True
        return Response()

    SlackWebhookNotifier(None, opener=opener)("camera_terminal", {"camera_key": "cam02"})
    assert called is False
