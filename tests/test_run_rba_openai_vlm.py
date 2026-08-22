from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.run_rba_openai_vlm import (
    BudgetExceeded,
    BudgetGuard,
    InputIntegrityError,
    VlmWindowPrediction,
    build_window_content,
    run_frame_manifest,
)


def _with_input_count(responses: object, tokens: object = 1000) -> object:
    setattr(
        responses,
        "input_tokens",
        SimpleNamespace(
            count=lambda **_: SimpleNamespace(input_tokens=tokens),
        ),
    )
    return responses


def _frame(path: Path, payload: bytes, index: int) -> dict[str, object]:
    path.write_bytes(payload)
    return {
        "frame_ref": f"frame-{index}",
        "frame_index": index,
        "timestamp_sec": float(index),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "path": str(path),
        "source_policies": ["base4fps"],
        "window_ids": ["window-000"],
    }


def _manifest(tmp_path: Path) -> Path:
    frames = [
        _frame(tmp_path / "a.jpg", b"jpeg-a", 0),
        _frame(tmp_path / "b.jpg", b"jpeg-b", 1),
    ]
    manifest = {
        "schema_version": "rba-openai-frame-manifest-v1",
        "media_sha256": "a" * 64,
        "duration_sec": 2.0,
        "planned_frame_count": 2,
        "actual_frame_count": 2,
        "base_coverage_preserved": True,
        "frames": frames,
        "windows": [
            {
                "window_id": "window-000",
                "start_sec": 0.0,
                "end_sec": 2.0,
                "frame_refs": ["frame-0", "frame-1"],
            }
        ],
    }
    path = tmp_path / "frame-manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_build_window_content_rejects_frame_hash_drift(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    Path(manifest["frames"][0]["path"]).write_bytes(b"tampered")

    with pytest.raises(InputIntegrityError, match="frame_hash_drift"):
        build_window_content(manifest, manifest["windows"][0])


def test_run_frame_manifest_uses_strict_gt_free_contract(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    calls: list[dict[str, object]] = []
    prediction = VlmWindowPrediction(
        primary_action="resting",
        observed_actions=["resting"],
        segments=[],
        max_visible_gecko_count="1",
        count_evidence_timestamps=[0.0],
        visibility="visible",
        occlusion="none",
        quality_flags=[],
        uncertainty="low",
        user_summary="게코 한 마리가 쉬고 있어.",
    )

    class FakeResponses:
        def parse(self, **kwargs: object) -> object:
            calls.append(kwargs)
            return SimpleNamespace(
                id="resp-smoke-1",
                output_parsed=prediction,
                service_tier="default",
                model="gpt-5.6-terra",
                usage=SimpleNamespace(input_tokens=1000, output_tokens=100),
            )

    client = SimpleNamespace(responses=_with_input_count(FakeResponses()))
    ledger = tmp_path / "results.jsonl"

    summary = run_frame_manifest(
        client=client,
        clip_ref="smoke-abc",
        manifest_path=manifest_path,
        ledger_path=ledger,
        budget_guard=BudgetGuard(max_run_usd=5.0, request_ceiling_usd=0.25),
    )

    assert summary["status"] == "complete"
    assert summary["window_count"] == 1
    assert summary["api_request_count"] == 2
    assert summary["input_token_count_request_count"] == 1
    assert summary["generation_request_count"] == 1
    assert len(calls) == 1
    call = calls[0]
    assert call["model"] == "gpt-5.6-terra"
    assert call["reasoning"] == {"effort": "low"}
    assert call["max_output_tokens"] == 1200
    assert call["service_tier"] == "default"
    assert call["truncation"] == "disabled"
    assert call["text_format"] is VlmWindowPrediction
    serialized = json.dumps(call["input"])
    assert "gt" not in serialized.lower()
    images = call["input"][0]["content"][1:]  # type: ignore[index]
    assert all(image["type"] == "input_image" for image in images)
    assert all(image["detail"] == "original" for image in images)
    assert all(image["image_url"].startswith("data:image/jpeg;base64,") for image in images)
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert len(rows) == 1
    assert "human" not in rows[0] and "gt" not in rows[0]
    assert rows[0]["usage"] == {"input_tokens": 1000, "output_tokens": 100}
    assert rows[0]["billing_status"] == "known"
    assert rows[0]["estimated_cost_usd"] == pytest.approx(0.004)
    assert rows[0]["service_tier"] == "default"
    assert rows[0]["response_model"] == "gpt-5.6-terra"
    assert rows[0]["pricing_snapshot"] == (
        "openai-api-gpt-5.6-terra-default-2026-08-22"
    )
    assert rows[0]["window_start_sec"] == 0.0
    assert rows[0]["window_end_sec"] == 2.0
    assert rows[0]["clip_duration_sec"] == 2.0
    assert ledger.stat().st_mode & 0o777 == 0o600


def test_budget_guard_blocks_before_next_request() -> None:
    guard = BudgetGuard(max_run_usd=0.008, request_ceiling_usd=0.005)
    guard.reserve_request(0.004)
    guard.record_usage(input_tokens=1000, output_tokens=100)

    with pytest.raises(BudgetExceeded, match="run_budget_exhausted"):
        guard.require_request_budget()


def test_run_frame_manifest_reserves_request_ceiling_before_client_call(
    tmp_path: Path,
) -> None:
    manifest_path = _manifest(tmp_path)
    parse_calls = 0

    class FakeResponses:
        def parse(self, **_: object) -> object:
            nonlocal parse_calls
            parse_calls += 1
            raise AssertionError("budget guard must block before provider invocation")

    guard = BudgetGuard(max_run_usd=0.2, request_ceiling_usd=0.1)
    guard.reserve_request(0.0957)
    guard.record_usage(input_tokens=0, output_tokens=7000)

    summary = run_frame_manifest(
        client=SimpleNamespace(responses=_with_input_count(FakeResponses())),
        clip_ref="smoke-abc",
        manifest_path=manifest_path,
        ledger_path=tmp_path / "results.jsonl",
        budget_guard=guard,
    )

    assert parse_calls == 0
    assert summary["status"] == "incomplete"
    assert summary["api_request_count"] == 0
    assert summary["input_token_count_request_count"] == 0
    assert summary["generation_request_count"] == 0
    row = json.loads((tmp_path / "results.jsonl").read_text())
    assert row["billing_status"] == "not_attempted"


def test_billable_invalid_prediction_is_charged_before_next_budget_gate(
    tmp_path: Path,
) -> None:
    manifest_path = _manifest(tmp_path)
    parse_calls = 0

    class BillableInvalidResponses:
        def parse(self, **_: object) -> object:
            nonlocal parse_calls
            parse_calls += 1
            return SimpleNamespace(
                id="resp-invalid",
                output_parsed=None,
                service_tier="default",
                model="gpt-5.6-terra",
                usage=SimpleNamespace(input_tokens=0, output_tokens=7000),
            )

    guard = BudgetGuard(max_run_usd=0.2, request_ceiling_usd=0.1)
    client = SimpleNamespace(
        responses=_with_input_count(BillableInvalidResponses())
    )
    ledger = tmp_path / "results.jsonl"

    first = run_frame_manifest(
        client=client,
        clip_ref="smoke-first",
        manifest_path=manifest_path,
        ledger_path=ledger,
        budget_guard=guard,
    )
    second = run_frame_manifest(
        client=client,
        clip_ref="smoke-second",
        manifest_path=manifest_path,
        ledger_path=ledger,
        budget_guard=guard,
    )

    assert first["status"] == "incomplete"
    assert first["estimated_cost_usd"] == pytest.approx(0.105)
    assert guard.spent_usd == pytest.approx(0.105)
    assert second["status"] == "incomplete"
    assert second["api_request_count"] == 0
    assert parse_calls == 1


@pytest.mark.parametrize(
    ("max_run_usd", "request_ceiling_usd"),
    [
        (0.0, 0.1),
        (-1.0, 0.1),
        (True, 0.1),
        (float("nan"), 0.1),
        (float("inf"), 0.1),
        (1.0, 0.0),
        (1.0, -0.1),
        (1.0, True),
        (1.0, float("nan")),
        (1.0, float("inf")),
        (0.1, 0.2),
    ],
)
def test_budget_guard_rejects_impossible_non_finite_or_non_positive_limits(
    max_run_usd: float, request_ceiling_usd: float
) -> None:
    with pytest.raises(ValueError, match="budget_contract"):
        BudgetGuard(
            max_run_usd=max_run_usd,
            request_ceiling_usd=request_ceiling_usd,
        )


def test_run_frame_manifest_records_failure_and_remaining_windows(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["windows"].append(
        {
            "window_id": "window-001",
            "start_sec": 1.0,
            "end_sec": 2.0,
            "frame_refs": ["frame-1"],
        }
    )
    manifest_path.write_text(json.dumps(manifest))

    class FailingResponses:
        def parse(self, **_: object) -> object:
            raise RuntimeError("provider detail must not enter the private ledger")

    ledger = tmp_path / "results.jsonl"
    summary = run_frame_manifest(
        client=SimpleNamespace(responses=_with_input_count(FailingResponses())),
        clip_ref="smoke-abc",
        manifest_path=manifest_path,
        ledger_path=ledger,
        budget_guard=BudgetGuard(max_run_usd=5.0, request_ceiling_usd=0.25),
    )

    assert summary["status"] == "incomplete"
    assert summary["window_count"] == 2
    assert summary["complete_window_count"] == 0
    assert summary["failed_window_count"] == 2
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [row["window_id"] for row in rows] == ["window-000", "window-001"]
    assert [row["failure_code"] for row in rows] == [
        "provider_request_failed",
        "not_attempted_after_failure",
    ]
    assert [row["billing_status"] for row in rows] == [
        "unknown",
        "not_attempted",
    ]
    assert all(row["status"] == "failed" for row in rows)
    assert "provider detail" not in ledger.read_text()
    assert summary["api_request_count"] == 2
    assert summary["input_token_count_request_count"] == 1
    assert summary["generation_request_count"] == 1


@pytest.mark.parametrize("counted_tokens", [1_000_000, None])
def test_input_count_must_be_known_and_within_conservative_limit_before_generation(
    tmp_path: Path, counted_tokens: object
) -> None:
    manifest_path = _manifest(tmp_path)
    parse_calls = 0

    class Responses:
        def parse(self, **_: object) -> object:
            nonlocal parse_calls
            parse_calls += 1
            raise AssertionError("unsafe input must not reach generation")

    guard = BudgetGuard(max_run_usd=0.2, request_ceiling_usd=0.1)
    summary = run_frame_manifest(
        client=SimpleNamespace(
            responses=_with_input_count(Responses(), counted_tokens)
        ),
        clip_ref="smoke-count",
        manifest_path=manifest_path,
        ledger_path=tmp_path / "results.jsonl",
        budget_guard=guard,
    )

    assert summary["status"] == "incomplete"
    assert summary["api_request_count"] == 1
    assert summary["input_token_count_request_count"] == 1
    assert summary["generation_request_count"] == 0
    assert parse_calls == 0
    assert guard.halted is True
    row = json.loads((tmp_path / "results.jsonl").read_text())
    assert row["billing_status"] == "unknown"


def test_actual_cost_over_reserved_ceiling_halts_before_any_second_client_call(
    tmp_path: Path,
) -> None:
    manifest_path = _manifest(tmp_path)
    count_calls = 0
    parse_calls = 0
    prediction = VlmWindowPrediction(
        primary_action="resting",
        observed_actions=["resting"],
        segments=[],
        max_visible_gecko_count="1",
        count_evidence_timestamps=[0.0],
        visibility="visible",
        occlusion="none",
        quality_flags=[],
        uncertainty="low",
        user_summary="summary",
    )

    class InputTokens:
        def count(self, **_: object) -> object:
            nonlocal count_calls
            count_calls += 1
            return SimpleNamespace(input_tokens=1000)

    class Responses:
        input_tokens = InputTokens()

        def parse(self, **_: object) -> object:
            nonlocal parse_calls
            parse_calls += 1
            return SimpleNamespace(
                id="resp-overrun",
                output_parsed=prediction,
                service_tier="default",
                model="gpt-5.6-terra",
                usage=SimpleNamespace(input_tokens=50_000, output_tokens=0),
            )

    guard = BudgetGuard(max_run_usd=0.2, request_ceiling_usd=0.1)
    client = SimpleNamespace(responses=Responses())
    first = run_frame_manifest(
        client=client,
        clip_ref="smoke-first",
        manifest_path=manifest_path,
        ledger_path=tmp_path / "results.jsonl",
        budget_guard=guard,
    )
    second = run_frame_manifest(
        client=client,
        clip_ref="smoke-second",
        manifest_path=manifest_path,
        ledger_path=tmp_path / "results.jsonl",
        budget_guard=guard,
    )

    assert first["status"] == "incomplete"
    assert first["estimated_cost_usd"] > 0.1
    assert second["api_request_count"] == 0
    assert guard.halted is True
    assert count_calls == 1
    assert parse_calls == 1


def test_missing_response_usage_permanently_halts_before_second_client_call(
    tmp_path: Path,
) -> None:
    manifest_path = _manifest(tmp_path)
    count_calls = 0
    parse_calls = 0

    class InputTokens:
        def count(self, **_: object) -> object:
            nonlocal count_calls
            count_calls += 1
            return SimpleNamespace(input_tokens=1000)

    class Responses:
        input_tokens = InputTokens()

        def parse(self, **_: object) -> object:
            nonlocal parse_calls
            parse_calls += 1
            return SimpleNamespace(
                id="resp-missing-usage",
                output_parsed=None,
                service_tier="default",
                model="gpt-5.6-terra",
                usage=None,
            )

    guard = BudgetGuard(max_run_usd=0.2, request_ceiling_usd=0.1)
    client = SimpleNamespace(responses=Responses())
    for clip_ref in ("smoke-first", "smoke-second"):
        run_frame_manifest(
            client=client,
            clip_ref=clip_ref,
            manifest_path=manifest_path,
            ledger_path=tmp_path / "results.jsonl",
            budget_guard=guard,
        )

    assert guard.halted is True
    assert count_calls == 1
    assert parse_calls == 1


def test_budget_guard_allows_only_one_in_flight_reservation() -> None:
    guard = BudgetGuard(max_run_usd=0.2, request_ceiling_usd=0.1)
    guard.reserve_request(0.0957)

    with pytest.raises(BudgetExceeded, match="request_already_reserved"):
        guard.reserve_request(0.0957)


@pytest.mark.parametrize(
    ("segment_end", "segment_evidence"),
    [(2.1, [0.5]), (1.0, [2.1])],
)
def test_prediction_outside_window_is_charged_then_fails_without_complete_ledger(
    tmp_path: Path, segment_end: float, segment_evidence: list[float]
) -> None:
    manifest_path = _manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["windows"].append(
        {
            "window_id": "window-001",
            "start_sec": 1.0,
            "end_sec": 2.0,
            "frame_refs": ["frame-1"],
        }
    )
    manifest_path.write_text(json.dumps(manifest))
    prediction = VlmWindowPrediction.model_validate(
        {
            "primary_action": "moving",
            "observed_actions": ["moving"],
            "segments": [
                {
                    "action": "moving",
                    "start_sec": 0.0,
                    "end_sec": segment_end,
                    "evidence_timestamps": segment_evidence,
                }
            ],
            "max_visible_gecko_count": "1",
            "count_evidence_timestamps": [0.5],
            "visibility": "visible",
            "occlusion": "none",
            "quality_flags": [],
            "uncertainty": "low",
            "user_summary": "summary",
        }
    )

    class Responses:
        def parse(self, **_: object) -> object:
            return SimpleNamespace(
                id="resp-window-invalid",
                output_parsed=prediction,
                service_tier="default",
                model="gpt-5.6-terra",
                usage=SimpleNamespace(input_tokens=1000, output_tokens=100),
            )

    guard = BudgetGuard(max_run_usd=1.0, request_ceiling_usd=0.1)
    ledger = tmp_path / "results.jsonl"
    summary = run_frame_manifest(
        client=SimpleNamespace(responses=_with_input_count(Responses())),
        clip_ref="smoke-window",
        manifest_path=manifest_path,
        ledger_path=ledger,
        budget_guard=guard,
    )

    assert summary["status"] == "incomplete"
    assert guard.spent_usd == pytest.approx(0.004)
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [row["failure_code"] for row in rows] == [
        "input_integrity_failed",
        "not_attempted_after_failure",
    ]
    assert all("prediction" not in row for row in rows)


def test_count_evidence_outside_window_fails_after_usage_charge(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path)
    prediction = VlmWindowPrediction(
        primary_action="resting",
        observed_actions=["resting"],
        segments=[],
        max_visible_gecko_count="1",
        count_evidence_timestamps=[2.1],
        visibility="visible",
        occlusion="none",
        quality_flags=[],
        uncertainty="low",
        user_summary="summary",
    )

    class Responses:
        def parse(self, **_: object) -> object:
            return SimpleNamespace(
                id="resp-count-window-invalid",
                output_parsed=prediction,
                service_tier="default",
                model="gpt-5.6-terra",
                usage=SimpleNamespace(input_tokens=1000, output_tokens=100),
            )

    guard = BudgetGuard(max_run_usd=1.0, request_ceiling_usd=0.1)
    ledger = tmp_path / "results.jsonl"
    run_frame_manifest(
        client=SimpleNamespace(responses=_with_input_count(Responses())),
        clip_ref="smoke-count-window",
        manifest_path=manifest_path,
        ledger_path=ledger,
        budget_guard=guard,
    )

    row = json.loads(ledger.read_text())
    assert row["failure_code"] == "input_integrity_failed"
    assert "prediction" not in row
    assert row["billing_status"] == "known"
    assert row["response_id"] == "resp-count-window-invalid"
    assert row["response_model"] == "gpt-5.6-terra"
    assert row["service_tier"] == "default"
    assert row["pricing_snapshot"] == (
        "openai-api-gpt-5.6-terra-default-2026-08-22"
    )
    assert row["pricing_source_url"] == "https://platform.openai.com/pricing"
    assert row["model_source_url"] == (
        "https://developers.openai.com/api/docs/models/gpt-5.6-terra"
    )
    assert row["usage"] == {"input_tokens": 1000, "output_tokens": 100}
    assert row["estimated_cost_usd"] == pytest.approx(0.004)
    assert guard.spent_usd > 0


@pytest.mark.parametrize(
    ("field_path", "invalid_value"),
    [
        (("segments", 0, "start_sec"), True),
        (("segments", 0, "end_sec"), float("inf")),
        (("segments", 0, "evidence_timestamps", 0), False),
        (("count_evidence_timestamps", 0), float("nan")),
    ],
)
def test_prediction_timestamps_reject_bool_and_nonfinite_values(
    field_path: tuple[object, ...], invalid_value: object
) -> None:
    raw: dict[str, object] = {
        "primary_action": "moving",
        "observed_actions": ["moving"],
        "segments": [
            {
                "action": "moving",
                "start_sec": 0.0,
                "end_sec": 1.0,
                "evidence_timestamps": [0.5],
            }
        ],
        "max_visible_gecko_count": "1",
        "count_evidence_timestamps": [0.5],
        "visibility": "visible",
        "occlusion": "none",
        "quality_flags": [],
        "uncertainty": "low",
        "user_summary": "summary",
    }
    target: object = raw
    for part in field_path[:-1]:
        target = target[part]  # type: ignore[index]
    target[field_path[-1]] = invalid_value  # type: ignore[index]

    with pytest.raises(ValueError):
        VlmWindowPrediction.model_validate(raw)
