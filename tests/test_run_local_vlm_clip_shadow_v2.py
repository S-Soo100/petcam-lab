import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.run_local_vlm_clip_shadow import ClipCandidate
from scripts.run_local_vlm_clip_shadow_v2 import (
    END_AT,
    gate_a,
    process_candidate,
    smoke_contract,
)


def _private(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _valid_observation() -> str:
    return json.dumps({
        "gecko_visibility": "visible",
        "activity_state": "active",
        "notable_change": "movement",
        "summary_ko": "게코가 위치를 바꾸는 모습이 보여.",
        "confidence": 0.8,
        "needs_human_review": False,
    }, ensure_ascii=False)


def test_v2_smoke_uses_same_question_with_opposite_static_moving_answers() -> None:
    assert smoke_contract("dark_empty")[1:] == ("background", "dark")
    assert smoke_contract("static_silhouette")[1:] == ("position_change", "no")
    assert smoke_contract("moving_silhouette")[1:] == ("position_change", "yes")


def test_gate_a_requires_three_smokes_and_production_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    env = parent / "runtime.env"
    salt = parent / "salt.bin"
    _private(env, b"X=1\n")
    _private(salt, b"s" * 32)
    responses = iter([
        '{"background":"dark"}',
        '{"position_change":"no"}',
        '{"position_change":"yes"}',
        _valid_observation(),
    ])
    calls: list[dict[str, object]] = []

    def fake_ollama(_endpoint: str, payload: object, **_kwargs: object) -> dict[str, object]:
        calls.append(payload)
        return {"message": {"content": next(responses)}, "prompt_eval_count": 3500}

    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow_v2.socket.gethostname", lambda: "host")
    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow_v2.git_head", lambda: "a" * 40)
    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow_v2.model_inventory", lambda: {"gemma3:4b": {"digest": "d", "size": 1}})
    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow_v2.resource_probe", lambda: {"free_percent": 80, "swap_used_bytes": 0, "serve_pid": 1, "serve_rss_kib": 1})
    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow_v2.ollama_json", fake_ollama)
    unloaded: list[bool] = []
    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow_v2.unload_model", lambda: unloaded.append(True))
    args = SimpleNamespace(
        expected_model="gemma3:4b", end_at=END_AT.isoformat(), expected_host="host",
        expected_head="a" * 40, output_dir=parent / "run", env_file=env, salt_file=salt,
    )
    manifest = gate_a(args)
    assert len(calls) == 4
    assert all(len(call["messages"][0]["images"]) == 12 for call in calls)
    assert manifest["smoke"]["static_silhouette"] == "position_change=no"
    assert manifest["production_prompt_eval_count"] == 3500
    assert manifest["production_context_budget"] == 3820
    assert unloaded == [True]
    assert (parent / "run" / "gate-a.json").stat().st_mode & 0o777 == 0o600


def test_gate_a_rejects_missing_or_truncated_production_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parent = tmp_path / "private"
    parent.mkdir(mode=0o700)
    env = parent / "runtime.env"
    salt = parent / "salt.bin"
    _private(env, b"X=1\n")
    _private(salt, b"s" * 32)
    responses = iter([
        '{"background":"dark"}', '{"position_change":"no"}',
        '{"position_change":"yes"}', _valid_observation(),
    ])
    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow_v2.socket.gethostname", lambda: "host")
    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow_v2.git_head", lambda: "a" * 40)
    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow_v2.model_inventory", lambda: {"gemma3:4b": {"digest": "d", "size": 1}})
    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow_v2.ollama_json", lambda *_a, **_k: {
        "message": {"content": next(responses)}, "prompt_eval_count": 4000,
    })
    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow_v2.unload_model", lambda: None)
    args = SimpleNamespace(
        expected_model="gemma3:4b", end_at=END_AT.isoformat(), expected_host="host",
        expected_head="a" * 40, output_dir=parent / "run", env_file=env, salt_file=salt,
    )
    with pytest.raises(RuntimeError, match="context_budget"):
        gate_a(args)


def test_process_candidate_persists_twelve_ordered_input_hashes_before_one_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "run"
    output.mkdir(mode=0o700)
    (output / "media").mkdir(mode=0o700)
    (output / "inputs").mkdir(mode=0o700)
    media = output / "media" / "clip.mp4"
    _private(media, b"video")
    frames = [np.full((40, 60, 3), index * 10, np.uint8) for index in range(12)]
    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow_v2.extract_frames", lambda _p: frames)
    calls: list[dict[str, object]] = []

    def fake_ollama(_endpoint: str, payload: object, **_kwargs: object) -> dict[str, object]:
        calls.append(payload)
        return {"message": {"content": _valid_observation()}}

    monkeypatch.setattr("scripts.run_local_vlm_clip_shadow_v2.ollama_json", fake_ollama)
    candidate = ClipCandidate("clip", "raw", "cam", "key", "2026-08-02T10:00:00+00:00", 60)
    assert process_candidate(
        candidate, salt=b"s" * 32, output_dir=output, ledger=output / "ledger.jsonl",
        r2=object(), bucket="bucket", model_digest="digest",
    ) == "processed"
    rows = [json.loads(line) for line in (output / "ledger.jsonl").read_text().splitlines()]
    assert [row["type"] for row in rows] == ["request_intent", "result"]
    assert len(rows[0]["input_sha256"]) == 12
    assert len(calls) == 1 and len(calls[0]["messages"][0]["images"]) == 12
