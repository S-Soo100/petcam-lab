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
                usage=SimpleNamespace(input_tokens=1000, output_tokens=100),
            )

    client = SimpleNamespace(responses=FakeResponses())
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
    assert len(calls) == 1
    call = calls[0]
    assert call["model"] == "gpt-5.6-terra"
    assert call["reasoning"] == {"effort": "low"}
    assert call["max_output_tokens"] == 1200
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
    assert rows[0]["estimated_cost_usd"] == pytest.approx(0.004)
    assert ledger.stat().st_mode & 0o777 == 0o600


def test_budget_guard_blocks_before_next_request() -> None:
    guard = BudgetGuard(max_run_usd=0.008, request_ceiling_usd=0.005)
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
    guard.record_usage(input_tokens=0, output_tokens=7000)

    summary = run_frame_manifest(
        client=SimpleNamespace(responses=FakeResponses()),
        clip_ref="smoke-abc",
        manifest_path=manifest_path,
        ledger_path=tmp_path / "results.jsonl",
        budget_guard=guard,
    )

    assert parse_calls == 0
    assert summary["status"] == "incomplete"
    assert summary["api_request_count"] == 0


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
        client=SimpleNamespace(responses=FailingResponses()),
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
    assert all(row["status"] == "failed" for row in rows)
    assert "provider detail" not in ledger.read_text()
