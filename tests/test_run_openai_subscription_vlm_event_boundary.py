import hashlib
import json
from pathlib import Path

import pytest

from scripts.local_vlm_event_boundary import PROMPT, BoundaryPrediction
from scripts.vlm_event_boundary_dense import DENSE_PROMPT
from scripts.recompute_openai_subscription_vlm_event_boundary import recompute
from scripts.run_openai_subscription_vlm_event_boundary import (
    ALLOWED_MODELS,
    DENSE_CONTRACT,
    build_codex_command,
    classify_codex_failure,
    load_frozen_inputs,
    operational_verdict,
    score_model_records,
    trace_is_tool_free,
)


def _write_frozen_fixture(tmp_path: Path) -> tuple[Path, Path]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    payloads = {"p1": b"first-jpeg", "p2": b"second-jpeg"}
    rows = []
    for pair, payload in payloads.items():
        path = inputs / f"{pair}-AB.jpg"
        path.write_bytes(payload)
        rows.append({
            "pair": pair,
            "human": "different_event" if pair == "p1" else "same_event",
            "images": [hashlib.sha256(payload).hexdigest()],
        })
    manifest = tmp_path / "frozen-manifest.json"
    manifest.write_text(json.dumps({
        "pair_count": 2,
        "clip_count": 3,
        "representation": "combined_4x2",
        "prompt_version": "local-vlm-event-boundary-v1",
        "inputs": rows,
    }))
    return manifest, inputs


def test_load_frozen_inputs_checks_identity_and_hash(tmp_path: Path) -> None:
    manifest, inputs = _write_frozen_fixture(tmp_path)

    loaded = load_frozen_inputs(manifest, inputs, expected_count=2)

    assert [row.pair for row in loaded] == ["p1", "p2"]
    assert loaded[0].human == "different_event"
    assert loaded[1].image_path.name == "p2-AB.jpg"


def test_load_frozen_inputs_rejects_image_hash_drift(tmp_path: Path) -> None:
    manifest, inputs = _write_frozen_fixture(tmp_path)
    (inputs / "p1-AB.jpg").write_bytes(b"changed")

    with pytest.raises(ValueError, match="input_hash_drift"):
        load_frozen_inputs(manifest, inputs, expected_count=2)


def test_build_codex_command_is_ephemeral_read_only_and_model_pinned(tmp_path: Path) -> None:
    image = tmp_path / "p1-AB.jpg"
    schema = tmp_path / "schema.json"
    output = tmp_path / "response.json"
    command = build_codex_command(
        codex_path=Path("/opt/homebrew/bin/codex"),
        model="gpt-5.4-mini",
        image_paths=(image,),
        schema_path=schema,
        output_path=output,
        working_dir=tmp_path,
        prompt=PROMPT,
    )

    assert tuple(ALLOWED_MODELS) == (
        "gpt-5.4-mini",
        "gpt-5.6-luna",
        "gpt-5.6-terra",
    )
    assert command[command.index("--model") + 1] == "gpt-5.4-mini"
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--image") + 1] == str(image)
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert 'model_reasoning_effort="low"' in command
    assert "same_event=57" not in " ".join(command)


def test_build_codex_command_rejects_unregistered_model(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="model_not_allowed"):
        build_codex_command(
            codex_path=Path("codex"),
            model="unknown",
            image_paths=(tmp_path / "image.jpg",),
            schema_path=tmp_path / "schema.json",
            output_path=tmp_path / "output.json",
            working_dir=tmp_path,
            prompt=PROMPT,
        )


def test_dense_manifest_loads_two_images_and_codex_receives_both(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    hashes = []
    for suffix, payload in (("A", b"dense-a"), ("B", b"dense-b")):
        path = inputs / f"p1-{suffix}.jpg"
        path.write_bytes(payload)
        hashes.append(hashlib.sha256(payload).hexdigest())
    manifest = tmp_path / "frozen-manifest.json"
    manifest.write_text(json.dumps({
        "pair_count": 1,
        "clip_count": 2,
        "representation": DENSE_CONTRACT.representation,
        "prompt_version": DENSE_CONTRACT.prompt_version,
        "inputs": [{"pair": "p1", "human": "same_event", "images": hashes}],
    }))

    loaded = load_frozen_inputs(
        manifest,
        inputs,
        expected_count=1,
        contract=DENSE_CONTRACT,
    )
    command = build_codex_command(
        codex_path=Path("codex"),
        model="gpt-5.4-mini",
        image_paths=loaded[0].image_paths,
        schema_path=tmp_path / "schema.json",
        output_path=tmp_path / "output.json",
        working_dir=tmp_path,
        prompt=DENSE_CONTRACT.prompt,
    )

    image_index = command.index("--image")
    assert command[image_index + 1:image_index + 3] == [
        str(inputs / "p1-A.jpg"),
        str(inputs / "p1-B.jpg"),
    ]
    assert command[-1] == DENSE_CONTRACT.prompt


def test_trace_integrity_allows_only_reasoning_and_agent_message_items() -> None:
    safe = "\n".join([
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "reasoning"}}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message"}}),
        json.dumps({"type": "turn.completed"}),
    ])
    unsafe = safe + "\n" + json.dumps({
        "type": "item.started",
        "item": {"type": "command_execution"},
    })

    assert trace_is_tool_free(safe) is True
    assert trace_is_tool_free(unsafe) is False
    assert trace_is_tool_free("not-json") is False


def test_quota_failure_is_not_scored_as_model_quality() -> None:
    assert classify_codex_failure(1, "", "usage limit reached") == "quota_or_rate_limit"
    assert classify_codex_failure(1, "429 rate limit", "") == "quota_or_rate_limit"
    assert classify_codex_failure(2, "", "other failure") == "codex_exit_2"


def test_clear_safety_failure_is_not_mislabeled_as_nondeterministic_borderline() -> None:
    assert operational_verdict(
        {"verdict": "REJECT_SAFETY", "overmerge": 2, "same_correct": 29},
        [],
    ) == "REJECT_SAFETY"
    assert operational_verdict(
        {"verdict": "REJECT_SAFETY", "overmerge": 1, "same_correct": 40},
        [],
    ) == "INCONCLUSIVE_NONDETERMINISTIC_BORDERLINE"
    assert operational_verdict(
        {"verdict": "REJECT_RELIABILITY", "overmerge": 0, "same_correct": 0},
        ["quota_or_rate_limit"],
    ) == "INCONCLUSIVE_QUOTA"


def test_score_model_records_reuses_safety_first_contract() -> None:
    human = {"p1": "different_event", "p2": "same_event"}
    records = [
        {"pair": "p1", "prediction": {
            "decision": "same_event",
            "confidence": 0.8,
            "reason_code": "continuous_posture",
        }, "elapsed_sec": 1.0},
        {"pair": "p2", "prediction": {
            "decision": "same_event",
            "confidence": 0.9,
            "reason_code": "continuous_motion",
        }, "elapsed_sec": 2.0},
    ]

    result = score_model_records(human, records, expected_count=2)

    assert result["score"]["overmerge"] == 1
    assert result["score"]["verdict"] == "REJECT_SAFETY"
    assert result["latency_sec"] == {"p50": 1.0, "p95": 2.0, "max": 2.0}
    assert BoundaryPrediction(**records[0]["prediction"]).decision == "same_event"


def test_independent_recompute_reads_frozen_source_and_ledgers(tmp_path: Path) -> None:
    manifest, _ = _write_frozen_fixture(tmp_path)
    source = json.loads(manifest.read_text())
    source_by_pair = {row["pair"]: row for row in source["inputs"]}
    prompt_sha = hashlib.sha256(PROMPT.encode()).hexdigest()
    run_root = tmp_path / "run"
    run_root.mkdir()
    models = ("gpt-5.4-mini", "gpt-5.6-luna", "gpt-5.6-terra")
    for model in models:
        model_dir = run_root / model
        model_dir.mkdir()
        records = [
            {
                "model": model,
                "pair": "p1",
                "input_sha256": source_by_pair["p1"]["images"][0],
                "prompt_sha256": prompt_sha,
                "elapsed_sec": 1.0,
                "prediction": {
                    "decision": "different_event",
                    "confidence": 0.9,
                    "reason_code": "clear_stop",
                },
            },
            {
                "model": model,
                "pair": "p2",
                "input_sha256": source_by_pair["p2"]["images"][0],
                "prompt_sha256": prompt_sha,
                "elapsed_sec": 2.0,
                "prediction": {
                    "decision": "same_event",
                    "confidence": 0.9,
                    "reason_code": "continuous_motion",
                },
            },
        ]
        (model_dir / "results.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in records)
        )

    summary = recompute(manifest, run_root, expected_count=2, models=models)

    assert summary["record_count"] == 6
    assert summary["models"]["gpt-5.4-mini"]["score"]["overmerge"] == 0
    assert summary["models"]["gpt-5.4-mini"]["score"]["verdict"] == "DEVELOPMENT_CANDIDATE"


def test_independent_recompute_supports_dense_two_image_contract(tmp_path: Path) -> None:
    image_hashes = [hashlib.sha256(value).hexdigest() for value in (b"a", b"b")]
    manifest = tmp_path / "frozen-manifest.json"
    manifest.write_text(json.dumps({
        "pair_count": 1,
        "clip_count": 2,
        "representation": DENSE_CONTRACT.representation,
        "prompt_version": DENSE_CONTRACT.prompt_version,
        "inputs": [{
            "pair": "p1",
            "human": "different_event",
            "images": image_hashes,
        }],
    }))
    run_root = tmp_path / "run"
    model = "gpt-5.4-mini"
    model_dir = run_root / model
    model_dir.mkdir(parents=True)
    record = {
        "model": model,
        "pair": "p1",
        "input_sha256": image_hashes,
        "prompt_sha256": hashlib.sha256(DENSE_PROMPT.encode()).hexdigest(),
        "elapsed_sec": 1.0,
        "prediction": {
            "decision": "different_event",
            "confidence": 0.9,
            "reason_code": "clear_stop",
        },
    }
    (model_dir / "results.jsonl").write_text(json.dumps(record) + "\n")

    summary = recompute(
        manifest,
        run_root,
        expected_count=1,
        models=(model,),
        input_contract="boundary_dense_6x2",
    )

    assert summary["record_count"] == 1
    assert summary["models"][model]["score"]["overmerge"] == 0
