"""RAP manager incident의 secret-free Slack webhook adapter."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.request import Request, urlopen


class SlackWebhookNotifier:
    def __init__(
        self,
        webhook_url: str | None,
        *,
        opener: Callable[..., Any] = urlopen,
        timeout: float = 5.0,
    ) -> None:
        self._webhook_url = webhook_url.strip() if webhook_url else None
        self._opener = opener
        self._timeout = timeout

    def __call__(self, kind: str, payload: Mapping[str, Any]) -> None:
        if not self._webhook_url:
            return
        camera = str(payload.get("camera_key", "unknown"))
        code = str(payload.get("code", payload.get("state", "unknown")))
        slot = str(payload.get("slot", "unknown"))
        title = "조치 필요" if kind == "camera_terminal" else "자동 복구"
        text = f"[RAP C500G {title}] camera={camera} code={code} slot={slot}"
        body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
        request = Request(
            self._webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self._opener(request, timeout=self._timeout) as response:
            response.read()
