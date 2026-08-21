"""GT-free OpenAI Responses API window runner와 비용 원장이야."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
from threading import RLock
from typing import Annotated, Literal, Mapping

from pydantic import BaseModel, Field


MODEL = "gpt-5.6-terra"
SERVICE_TIER = "default"
PRICING_SNAPSHOT = "openai-api-gpt-5.6-terra-default-2026-08-22"
PRICING_SOURCE_URL = "https://platform.openai.com/pricing"
MODEL_SOURCE_URL = "https://developers.openai.com/api/docs/models/gpt-5.6-terra"
INPUT_USD_PER_MILLION = 2.50
OUTPUT_USD_PER_MILLION = 15.00
CONSERVATIVE_INPUT_USD_PER_MILLION = 5.50
CONSERVATIVE_OUTPUT_USD_PER_MILLION = 24.75
PROMPT_VERSION = "rba-openai-window-v1"
MAX_OUTPUT_TOKENS = 1200
INPUT_TOKEN_MARGIN = 2000
MAX_INPUT_TOKENS = 12_000
MAX_REQUEST_COST_USD = (
    MAX_INPUT_TOKENS * CONSERVATIVE_INPUT_USD_PER_MILLION
    + MAX_OUTPUT_TOKENS * CONSERVATIVE_OUTPUT_USD_PER_MILLION
) / 1_000_000
PROMPT = """Analyze these chronological frames from one gecko camera clip window.
Report only visible facts. Do not infer an action that is not visibly supported.
Use video-relative timestamps supplied with the frames. Multiple actions may occur.
Count the maximum number of geckos visibly present at the same time as 0, 1, 2, 3, 4+, or uncertain.
If visibility is insufficient, preserve uncertainty. Return the requested structured output only."""


class InputIntegrityError(ValueError):
    """예정된 frame과 실제 API 입력이 다를 때 호출을 막아."""


class BudgetExceeded(RuntimeError):
    """이 run에 허용한 작은 예산을 모두 썼어."""


StrictFiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class SegmentPrediction(BaseModel):
    action: str
    start_sec: Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]
    end_sec: Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]
    evidence_timestamps: list[StrictFiniteFloat]


class VlmWindowPrediction(BaseModel):
    primary_action: str
    observed_actions: list[str]
    segments: list[SegmentPrediction]
    max_visible_gecko_count: Literal["0", "1", "2", "3", "4+", "uncertain"]
    count_evidence_timestamps: list[StrictFiniteFloat]
    visibility: str
    occlusion: str
    quality_flags: list[str]
    uncertainty: str
    user_summary: str


class BudgetGuard:
    def __init__(self, *, max_run_usd: float, request_ceiling_usd: float) -> None:
        if (
            isinstance(max_run_usd, bool)
            or isinstance(request_ceiling_usd, bool)
            or not math.isfinite(max_run_usd)
            or max_run_usd <= 0
            or not math.isfinite(request_ceiling_usd)
            or request_ceiling_usd <= 0
            or request_ceiling_usd > max_run_usd
        ):
            raise ValueError("budget_contract")
        self.max_run_usd = max_run_usd
        self.request_ceiling_usd = request_ceiling_usd
        self.spent_usd = 0.0
        self.halted = False
        self._reserved_usd: float | None = None
        self._lock = RLock()

    def require_request_budget(self) -> None:
        with self._lock:
            if (
                self.halted
                or self.max_run_usd - self.spent_usd < self.request_ceiling_usd
            ):
                raise BudgetExceeded("run_budget_exhausted")

    def reserve_request(self, worst_case_usd: float) -> None:
        with self._lock:
            if self._reserved_usd is not None:
                raise BudgetExceeded("request_already_reserved")
            self.require_request_budget()
            if (
                not math.isfinite(worst_case_usd)
                or worst_case_usd <= 0
                or worst_case_usd > self.request_ceiling_usd
            ):
                self.halted = True
                raise BudgetExceeded("request_ceiling_insufficient")
            self._reserved_usd = self.request_ceiling_usd

    def halt_unknown_usage(self) -> None:
        with self._lock:
            self._reserved_usd = None
            self.halted = True

    def record_usage(self, *, input_tokens: int, output_tokens: int) -> float:
        with self._lock:
            if self._reserved_usd is None:
                raise ValueError("usage_without_reservation")
            if (
                isinstance(input_tokens, bool)
                or isinstance(output_tokens, bool)
                or input_tokens < 0
                or output_tokens < 0
            ):
                raise ValueError("usage_tokens")
            cost = (
                input_tokens * INPUT_USD_PER_MILLION
                + output_tokens * OUTPUT_USD_PER_MILLION
            ) / 1_000_000
            if not math.isfinite(cost):
                raise ValueError("usage_tokens")
            conservative_cost = (
                input_tokens * CONSERVATIVE_INPUT_USD_PER_MILLION
                + output_tokens * CONSERVATIVE_OUTPUT_USD_PER_MILLION
            ) / 1_000_000
            self.spent_usd += cost
            if (
                conservative_cost > self._reserved_usd
                or self.spent_usd > self.max_run_usd
            ):
                self.halted = True
            self._reserved_usd = None
            return cost


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def build_window_content(
    manifest: Mapping[str, object], window: Mapping[str, object]
) -> list[dict[str, object]]:
    raw_frames = manifest.get("frames")
    raw_refs = window.get("frame_refs")
    if not isinstance(raw_frames, list) or not isinstance(raw_refs, list) or not raw_refs:
        raise InputIntegrityError("window_contract")
    frames: dict[str, Mapping[str, object]] = {}
    for raw in raw_frames:
        if not isinstance(raw, Mapping):
            raise InputIntegrityError("frame_contract")
        frame_ref = raw.get("frame_ref")
        if not isinstance(frame_ref, str) or frame_ref in frames:
            raise InputIntegrityError("frame_identity")
        frames[frame_ref] = raw

    timeline: list[str] = []
    images: list[dict[str, object]] = []
    for raw_ref in raw_refs:
        if not isinstance(raw_ref, str) or raw_ref not in frames:
            raise InputIntegrityError("window_frame_ref")
        row = frames[raw_ref]
        path_value = row.get("path")
        expected_sha = row.get("sha256")
        timestamp = row.get("timestamp_sec")
        if (
            not isinstance(path_value, str)
            or not isinstance(expected_sha, str)
            or isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
        ):
            raise InputIntegrityError("frame_contract")
        path = Path(path_value)
        if not path.is_file() or path.is_symlink() or _sha256(path) != expected_sha:
            raise InputIntegrityError("frame_hash_drift")
        encoded = base64.b64encode(path.read_bytes()).decode()
        timeline.append(f"{raw_ref}={float(timestamp):.3f}s")
        images.append(
            {
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{encoded}",
                "detail": "original",
            }
        )
    text = f"{PROMPT}\nFrame order and timestamps: {', '.join(timeline)}"
    return [{"type": "input_text", "text": text}, *images]


def _usage_tokens(usage: object) -> tuple[int, int]:
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if (
        isinstance(input_tokens, bool)
        or isinstance(output_tokens, bool)
        or not isinstance(input_tokens, int)
        or not isinstance(output_tokens, int)
        or input_tokens < 0
        or output_tokens < 0
    ):
        raise InputIntegrityError("usage_contract")
    return input_tokens, output_tokens


def _strict_number(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise InputIntegrityError("prediction_window_contract")
    return float(value)


def _validate_prediction_window(
    prediction: VlmWindowPrediction,
    *,
    window_start: float,
    window_end: float,
    clip_duration: float,
) -> None:
    if not (0 <= window_start < window_end <= clip_duration):
        raise InputIntegrityError("window_time_contract")
    for segment in prediction.segments:
        start = _strict_number(segment.start_sec)
        end = _strict_number(segment.end_sec)
        if not (window_start <= start < end <= window_end):
            raise InputIntegrityError("prediction_window_contract")
        for raw in segment.evidence_timestamps:
            timestamp = _strict_number(raw)
            if not window_start <= timestamp <= window_end:
                raise InputIntegrityError("prediction_window_contract")
    for raw in prediction.count_evidence_timestamps:
        timestamp = _strict_number(raw)
        if not window_start <= timestamp <= window_end:
            raise InputIntegrityError("prediction_window_contract")


def _append_private_jsonl(path: Path, value: object) -> None:
    if path.is_symlink():
        raise InputIntegrityError("ledger_symlink")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(
        path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600
    )
    with os.fdopen(descriptor, "ab") as handle:
        handle.write(_canonical_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def run_frame_manifest(
    *,
    client: object,
    clip_ref: str,
    manifest_path: Path,
    ledger_path: Path,
    budget_guard: BudgetGuard,
) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text())
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "rba-openai-frame-manifest-v1"
        or manifest.get("planned_frame_count") != manifest.get("actual_frame_count")
        or manifest.get("base_coverage_preserved") is not True
        or not isinstance(manifest.get("windows"), list)
    ):
        raise InputIntegrityError("manifest_contract")
    windows = manifest["windows"]
    clip_duration = _strict_number(manifest.get("duration_sec"))
    if clip_duration <= 0:
        raise InputIntegrityError("manifest_contract")
    total_cost = 0.0
    complete_window_count = 0
    api_request_count = 0
    failed_window_count = 0
    for window_index, window in enumerate(windows):
        if not isinstance(window, Mapping):
            raise InputIntegrityError("window_contract")
        window_id = window.get("window_id")
        if not isinstance(window_id, str):
            raise InputIntegrityError("window_contract")
        window_start = _strict_number(window.get("start_sec"))
        window_end = _strict_number(window.get("end_sec"))
        if not 0 <= window_start < window_end <= clip_duration:
            raise InputIntegrityError("window_time_contract")
        try:
            budget_guard.reserve_request(MAX_REQUEST_COST_USD)
            content = build_window_content(manifest, window)
            request_input = [{"role": "user", "content": content}]
            count_response = client.responses.input_tokens.count(  # type: ignore[attr-defined]
                model=MODEL,
                reasoning={"effort": "low"},
                input=request_input,
                truncation="disabled",
            )
            counted_tokens = getattr(count_response, "input_tokens", None)
            if (
                isinstance(counted_tokens, bool)
                or not isinstance(counted_tokens, int)
                or counted_tokens < 0
                or counted_tokens + INPUT_TOKEN_MARGIN > MAX_INPUT_TOKENS
            ):
                budget_guard.halt_unknown_usage()
                raise InputIntegrityError("input_token_count_contract")
            worst_case_cost = (
                (counted_tokens + INPUT_TOKEN_MARGIN)
                * CONSERVATIVE_INPUT_USD_PER_MILLION
                + MAX_OUTPUT_TOKENS * CONSERVATIVE_OUTPUT_USD_PER_MILLION
            ) / 1_000_000
            if worst_case_cost > budget_guard.request_ceiling_usd:
                budget_guard.halt_unknown_usage()
                raise BudgetExceeded("request_ceiling_insufficient")
            api_request_count += 1
            response = client.responses.parse(  # type: ignore[attr-defined]
                model=MODEL,
                reasoning={"effort": "low"},
                max_output_tokens=MAX_OUTPUT_TOKENS,
                service_tier=SERVICE_TIER,
                truncation="disabled",
                input=request_input,
                text_format=VlmWindowPrediction,
            )
            input_tokens, output_tokens = _usage_tokens(
                getattr(response, "usage", None)
            )
            cost = budget_guard.record_usage(
                input_tokens=input_tokens, output_tokens=output_tokens
            )
            total_cost += cost
            if budget_guard.halted:
                raise BudgetExceeded("request_cost_overrun")
            if getattr(response, "service_tier", None) != SERVICE_TIER:
                budget_guard.halted = True
                raise InputIntegrityError("response_service_tier_contract")
            response_model = getattr(response, "model", None)
            if response_model != MODEL:
                budget_guard.halted = True
                raise InputIntegrityError("response_model_contract")
            prediction = getattr(response, "output_parsed", None)
            response_id = getattr(response, "id", None)
            if not isinstance(prediction, VlmWindowPrediction) or not isinstance(
                response_id, str
            ):
                raise InputIntegrityError("response_contract")
            _validate_prediction_window(
                prediction,
                window_start=window_start,
                window_end=window_end,
                clip_duration=clip_duration,
            )
            _append_private_jsonl(
                ledger_path,
                {
                    "schema_version": "rba-openai-window-ledger-v1",
                    "clip_ref": clip_ref,
                    "window_id": window_id,
                    "status": "complete",
                    "media_sha256": manifest.get("media_sha256"),
                    "model": MODEL,
                    "service_tier": SERVICE_TIER,
                    "pricing_snapshot": PRICING_SNAPSHOT,
                    "pricing_source_url": PRICING_SOURCE_URL,
                    "model_source_url": MODEL_SOURCE_URL,
                    "response_model": response_model,
                    "reasoning_effort": "low",
                    "image_detail": "original",
                    "prompt_version": PROMPT_VERSION,
                    "response_id": response_id,
                    "usage": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    },
                    "estimated_cost_usd": round(cost, 8),
                    "window_start_sec": window_start,
                    "window_end_sec": window_end,
                    "clip_duration_sec": clip_duration,
                    "prediction": prediction.model_dump(mode="json"),
                },
            )
            complete_window_count += 1
        except Exception as exc:
            if budget_guard._reserved_usd is not None:
                budget_guard.halt_unknown_usage()
            if isinstance(exc, BudgetExceeded):
                failure_code = "run_budget_exhausted"
            elif isinstance(exc, InputIntegrityError):
                failure_code = "input_integrity_failed"
            else:
                failure_code = "provider_request_failed"
            _append_private_jsonl(
                ledger_path,
                {
                    "schema_version": "rba-openai-window-ledger-v1",
                    "clip_ref": clip_ref,
                    "window_id": window_id,
                    "status": "failed",
                    "media_sha256": manifest.get("media_sha256"),
                    "model": MODEL,
                    "prompt_version": PROMPT_VERSION,
                    "failure_code": failure_code,
                },
            )
            failed_window_count += 1
            for remaining in windows[window_index + 1 :]:
                remaining_id = (
                    remaining.get("window_id")
                    if isinstance(remaining, Mapping)
                    else None
                )
                if not isinstance(remaining_id, str):
                    raise InputIntegrityError("window_contract") from exc
                _append_private_jsonl(
                    ledger_path,
                    {
                        "schema_version": "rba-openai-window-ledger-v1",
                        "clip_ref": clip_ref,
                        "window_id": remaining_id,
                        "status": "failed",
                        "media_sha256": manifest.get("media_sha256"),
                        "model": MODEL,
                        "prompt_version": PROMPT_VERSION,
                        "failure_code": "not_attempted_after_failure",
                    },
                )
                failed_window_count += 1
            break
    return {
        "schema_version": "rba-openai-clip-run-v1",
        "clip_ref": clip_ref,
        "status": "complete" if failed_window_count == 0 else "incomplete",
        "window_count": len(windows),
        "complete_window_count": complete_window_count,
        "failed_window_count": failed_window_count,
        "api_request_count": api_request_count,
        "estimated_cost_usd": round(total_cost, 8),
    }
