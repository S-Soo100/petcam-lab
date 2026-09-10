from __future__ import annotations

import json
from urllib.error import HTTPError, URLError

from backend.rap_c500g_manager_notify import SlackDeliveryResult, SlackWebhookNotifier


class Response:
    status = 204
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

    result = SlackWebhookNotifier(None, opener=opener)("camera_terminal", {"camera_key": "cam02"})
    assert called is False
    assert result == SlackDeliveryResult(False, "disabled", 0)


def test_slack_delivery_returns_2xx_receipt_without_url_or_body() -> None:
    result = SlackWebhookNotifier(
        "https://hooks.slack.test/private",
        opener=lambda *_args, **_kwargs: Response(),
        clock=lambda: 1.0,
    )("camera_terminal", {"camera_key": "cam01"})

    assert result == SlackDeliveryResult(True, "2xx", 0)
    assert "private" not in repr(result)


def test_slack_delivery_classifies_http_and_transport_failures() -> None:
    def http_error(*_args, **_kwargs):
        raise HTTPError("https://hidden", 429, "limited", {}, None)

    def transport_error(*_args, **_kwargs):
        raise URLError("offline")

    assert SlackWebhookNotifier("https://hidden", opener=http_error)("x", {}).status_class == "4xx"
    assert SlackWebhookNotifier("https://hidden", opener=transport_error)("x", {}).status_class == "transport_error"


def test_slot_raw_summary_is_one_safe_message_for_three_cameras() -> None:
    sent: list[bytes] = []
    def opener(request, timeout: float):
        del timeout
        sent.append(request.data)
        return Response()
    notifier = SlackWebhookNotifier("https://hooks.slack.test/token", opener=opener)
    notifier("slot_raw_summary", {"slot": "20:00", "cameras": {
        "cam01": "uploaded", "cam02": "uploaded", "cam03": "failed"
    }})
    text = json.loads(sent[0])["text"]
    assert all(text.count(camera) == 1 for camera in ("cam01", "cam02", "cam03"))


def test_night_acceptance_includes_health_state() -> None:
    sent: list[bytes] = []

    def opener(request, timeout: float):
        del timeout
        sent.append(request.data)
        return Response()

    notifier = SlackWebhookNotifier("https://hooks.slack.test/token", opener=opener)
    notifier(
        "night_acceptance",
        {
            "night_date": "2026-09-03",
            "state": "degraded",
            "verified_slots": 72,
            "expected_slots": 72,
        },
    )

    text = json.loads(sent[0])["text"]
    assert "state=degraded" in text
