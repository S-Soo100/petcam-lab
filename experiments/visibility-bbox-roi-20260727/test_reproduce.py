from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).with_name("reproduce.py")


def subject():
    assert MODULE_PATH.exists(), "reproduce.py must be implemented"
    spec = importlib.util.spec_from_file_location("visibility_reproduce", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sample_times_are_six_segment_midpoints():
    assert subject().sample_times(60.0) == [5.0, 15.0, 25.0, 35.0, 45.0, 55.0]


@pytest.mark.parametrize("duration", [0.0, -1.0, float("nan"), float("inf")])
def test_sample_times_reject_invalid_duration(duration):
    with pytest.raises(ValueError, match="positive_duration_required"):
        subject().sample_times(duration)


def test_three_identical_non_moving_labels_are_stable_error():
    assert subject().classify_runs(["shedding"] * 3) == "stable_error"


def test_three_moving_labels_are_stable_correct():
    assert subject().classify_runs(["moving"] * 3) == "stable_correct"


def test_mixed_labels_are_unstable():
    assert subject().classify_runs(["moving", "shedding", "moving"]) == "unstable"


def test_run_classifier_rejects_wrong_count_or_unknown_label():
    with pytest.raises(ValueError, match="invalid_run_labels"):
        subject().classify_runs(["moving", "moving"])
    with pytest.raises(ValueError, match="invalid_run_labels"):
        subject().classify_runs(["moving", "moving", "basking"])


def test_phase0_rejects_when_stable_error_clips_below_ten():
    assert subject().decide_phase0({"stable_error_clips": 9}) == (
        "VISIBILITY_ROI_REJECT_NO_CURRENT_REPRODUCIBLE_FAILURE"
    )


def test_phase0_holds_for_episode_link_when_clip_gate_passes():
    assert subject().decide_phase0({"stable_error_clips": 10}) == (
        "VISIBILITY_ROI_HOLD_EPISODE_LINK_REQUIRED"
    )


def test_build_command_requires_one_to_four_clips_with_six_frames(tmp_path):
    mod = subject()
    prompt = tmp_path / "prompt.md"
    prompt.write_text("frozen")
    six = [tmp_path / f"f_{index}.jpg" for index in range(6)]
    with pytest.raises(ValueError, match="batch_size_1_to_4_required"):
        mod.build_command({}, prompt)
    with pytest.raises(ValueError, match="six_frames_required"):
        mod.build_command({"review-001": six[:5]}, prompt)
    with pytest.raises(ValueError, match="batch_size_1_to_4_required"):
        mod.build_command({f"review-{index:03d}": six for index in range(5)}, prompt)


def test_build_command_pins_read_only_exact_model_and_prompt(tmp_path):
    mod = subject()
    prompt = tmp_path / "prompt.md"
    prompt.write_text("frozen")
    frames = tmp_path / "frames"
    frames.mkdir()
    six = []
    for index in range(6):
        path = frames / f"f_{index}.jpg"
        path.write_bytes(b"x")
        six.append(path)
    command = mod.build_command({"review-001": six}, prompt)
    assert command[0:2] == ["claude", "-p"]
    assert command[command.index("--model") + 1] == "claude-sonnet-5"
    assert command[command.index("--system-prompt-file") + 1] == str(prompt)
    assert command[command.index("--tools") + 1] == "Read"
    assert command[command.index("--allowed-tools") + 1] == "Read"
    assert "--safe-mode" in command
    assert "--no-session-persistence" in command


def envelope(*, aliases=("review-001",), model="claude-sonnet-5"):
    items = [
        {
            "clip_id": alias,
            "action": "moving",
            "confidence": 0.9,
            "reasoning": "visible movement",
        }
        for alias in aliases
    ]
    return json.dumps(
        {
            "is_error": False,
            "session_id": "session-sensitive",
            "structured_output": {"items": items},
            "modelUsage": {
                model: {
                    "inputTokens": 10,
                    "cacheCreationInputTokens": 20,
                    "cacheReadInputTokens": 30,
                    "outputTokens": 40,
                    "costUSD": 0,
                }
            },
        }
    )


def test_parse_envelope_accepts_exact_model_and_alias_set():
    parsed = subject().parse_envelope(envelope(), {"review-001"})
    assert parsed["items"]["review-001"]["action"] == "moving"
    assert parsed["usage"]["output_tokens"] == 40
    assert "session-sensitive" not in json.dumps(parsed)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (json.dumps({"is_error": True, "result": "usage limit"}), "quota_exceeded"),
        ("not-json", "invalid_envelope"),
        (
            envelope(model="claude-sonnet-4-6"),
            "model_mismatch",
        ),
        (
            envelope(aliases=("review-002",)),
            "clip_set_mismatch",
        ),
    ],
)
def test_parse_envelope_fails_closed(payload, message):
    with pytest.raises(RuntimeError, match=message):
        subject().parse_envelope(payload, {"review-001"})


def test_summarize_is_aggregate_only_and_counts_tokens_once_per_batch():
    raw = {
        "passes": {
            "1": {
                "batch-001": {
                    "items": {
                        "review-001": {"action": "moving"},
                        "review-002": {"action": "shedding"},
                    },
                    "usage": {"input_tokens": 1, "output_tokens": 2},
                }
            },
            "2": {
                "batch-001": {
                    "items": {
                        "review-001": {"action": "moving"},
                        "review-002": {"action": "shedding"},
                    },
                    "usage": {"input_tokens": 3, "output_tokens": 4},
                }
            },
            "3": {
                "batch-001": {
                    "items": {
                        "review-001": {"action": "moving"},
                        "review-002": {"action": "shedding"},
                    },
                    "usage": {"input_tokens": 5, "output_tokens": 6},
                }
            },
        }
    }
    summary = subject().summarize(raw)
    assert summary["completed_clips"] == 2
    assert summary["completed_runs"] == 6
    assert summary["stable_correct_clips"] == 1
    assert summary["stable_error_clips"] == 1
    assert summary["unstable_clips"] == 0
    assert summary["stable_error_action_distribution"] == {"shedding": 1}
    assert summary["tokens"] == {"input_tokens": 9, "output_tokens": 12}
    assert summary["verdict"] == "VISIBILITY_ROI_REJECT_NO_CURRENT_REPRODUCIBLE_FAILURE"
    serialized = json.dumps(summary)
    assert "review-001" not in serialized
    assert "review-002" not in serialized


def test_run_batches_resume_skips_completed_batch_and_writes_new_batch(tmp_path):
    mod = subject()
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(
        json.dumps(
            {
                "passes": {
                    "1": {
                        "batch-001": {
                            "aliases": ["review-001"],
                            "items": {"review-001": {"action": "moving"}},
                            "usage": {},
                        }
                    }
                }
            }
        )
    )
    frame_sets = {
        "review-001": [tmp_path / f"a-{index}.jpg" for index in range(6)],
        "review-002": [tmp_path / f"b-{index}.jpg" for index in range(6)],
    }
    calls = []

    def fake_runner(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=envelope(aliases=("review-002",)), stderr="")

    raw = mod.run_batches(
        frame_sets,
        tmp_path / "prompt.md",
        raw_path,
        passes=1,
        batch_size=1,
        runner=fake_runner,
    )
    assert len(calls) == 1
    assert set(raw["passes"]["1"]) == {"batch-001", "batch-002"}
    persisted = json.loads(raw_path.read_text())
    assert persisted == raw

