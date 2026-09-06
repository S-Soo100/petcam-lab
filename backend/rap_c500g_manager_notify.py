"""RAP manager incident의 secret-free Slack webhook adapter."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class SlackDeliveryResult:
    delivered: bool
    status_class: str
    elapsed_ms: int


class SlackWebhookNotifier:
    def __init__(
        self,
        webhook_url: str | None,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._webhook_url = webhook_url.strip() if webhook_url else None
        self._opener = opener
        self._timeout = timeout
        self._clock = clock

    def __call__(self, kind: str, payload: Mapping[str, Any]) -> SlackDeliveryResult:
        if not self._webhook_url:
            return SlackDeliveryResult(False, "disabled", 0)
        camera = str(payload.get("camera_key", "unknown"))
        code = str(payload.get("code", payload.get("state", "unknown")))
        slot = str(payload.get("slot", "unknown"))
        if kind == "slot_raw_summary":
            statuses = payload.get("cameras", {})
            safe = " ".join(
                f"{key}={value}" for key, value in sorted(dict(statuses).items())
                if key in {"cam01", "cam02", "cam03"}
            )
            text = f"[RAP C500G 원본 백업] slot={slot} {safe}"
        elif kind == "night_acceptance":
            night_date = str(payload.get("night_date", "unknown"))
            state = str(payload.get("state", "unknown"))
            verified = int(payload.get("verified_slots", 0))
            expected = int(payload.get("expected_slots", 0))
            text = (
                f"[RAP C500G 12시간 검증] night={night_date} "
                f"state={state} verified={verified}/{expected}"
            )
        else:
            title = "조치 필요" if kind in {"camera_terminal", "pipeline_incident"} else "자동 복구"
            text = f"[RAP C500G {title}] camera={camera} code={code} slot={slot}"
        body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = self._clock()
        try:
            with self._opener(request, timeout=self._timeout) as response:
                response.read()
                status = int(getattr(response, "status", 200))
        except HTTPError as error:
            status_class = "4xx" if 400 <= error.code < 500 else "5xx"
            return SlackDeliveryResult(
                False, status_class, max(0, round((self._clock() - started) * 1000))
            )
        except (URLError, TimeoutError, OSError):
            return SlackDeliveryResult(
                False,
                "transport_error",
                max(0, round((self._clock() - started) * 1000)),
            )
        status_class = (
            "2xx" if 200 <= status < 300
            else "4xx" if 400 <= status < 500
            else "5xx" if 500 <= status < 600
            else "transport_error"
        )
        return SlackDeliveryResult(
            200 <= status < 300,
            status_class,
            max(0, round((self._clock() - started) * 1000)),
        )
