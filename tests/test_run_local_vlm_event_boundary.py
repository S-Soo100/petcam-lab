import base64
import hashlib
import hmac
import json
from pathlib import Path
import subprocess

import numpy as np
import pytest

from scripts.run_local_vlm_event_boundary import (
    RunnerSafetyError,
    ResourceMonitor,
    build_contact_sheet,
    build_ollama_payload,
    model_lifecycle_payload,
    map_effective_pairs,
    parse_swap_used_bytes,
    require_private_file,
    select_representation,
)


def _token(salt: bytes, namespace: str, raw: str) -> str:
    return hmac.new(
        salt,
        f"{namespace}\0{raw}".encode(),
        hashlib.sha256,
    ).hexdigest()[:16]


def test_require_private_file_checks_mode_and_salt_length(tmp_path: Path) -> None:
    path = tmp_path / "salt.bin"
    path.write_bytes(b"x" * 32)
    path.chmod(0o600)
    assert require_private_file(path, expected_size=32) == b"x" * 32
    path.chmod(0o644)
    with pytest.raises(RunnerSafetyError, match="mode"):
        require_private_file(path, expected_size=32)


def test_map_effective_pairs_joins_db_identity_to_manifest_without_gt_guessing() -> None:
    salt = b"s" * 32
    manifest_pairs = [
        {"pair_digest": "digest-a", "left_clip_id": "left", "right_clip_id": "right"},
        {"pair_digest": "digest-b", "left_clip_id": "x", "right_clip_id": "y"},
    ]
    db_pairs = [
        {"id": "db-a", "pair_digest": "digest-a"},
        {"id": "db-b", "pair_digest": "digest-b"},
    ]
    final = [
        {"pair": _token(salt, "pair", "db-a"), "decision": "same_event"},
    ]
    mapped = map_effective_pairs(manifest_pairs, db_pairs, final, salt)
    assert len(mapped) == 1
    assert mapped[0].left_clip_id == "left"
    assert mapped[0].right_clip_id == "right"
    assert mapped[0].human_decision == "same_event"
    assert mapped[0].private_key == _token(salt, "pair", "db-a")


def test_map_effective_pairs_rejects_unknown_or_duplicate_mapping() -> None:
    salt = b"s" * 32
    manifest = [{"pair_digest": "d", "left_clip_id": "l", "right_clip_id": "r"}]
    db = [{"id": "db", "pair_digest": "d"}]
    with pytest.raises(RunnerSafetyError, match="mapping"):
        map_effective_pairs(manifest, db, [{"pair": "unknown", "decision": "same_event"}], salt)
    duplicate = [
        {"pair": _token(salt, "pair", "db"), "decision": "same_event"},
        {"pair": _token(salt, "pair", "db"), "decision": "different_event"},
    ]
    with pytest.raises(RunnerSafetyError, match="mapping"):
        map_effective_pairs(manifest, db, duplicate, salt)


def test_build_contact_sheet_preserves_all_four_frames() -> None:
    frames = [np.full((40, 60, 3), index * 40, dtype=np.uint8) for index in range(4)]
    sheet = build_contact_sheet(frames, label="A")
    assert sheet.ndim == 3
    assert sheet.shape[0] > 80
    assert sheet.shape[1] == 120
    assert sheet[:24].mean() > 0  # header는 원본 위가 아니라 별도 영역이야.


def test_representation_falls_back_for_either_model_failure() -> None:
    assert select_representation({"a": True, "b": True}) == "two_images"
    assert select_representation({"a": True, "b": False}) == "combined_4x2"
    with pytest.raises(RunnerSafetyError, match="smoke"):
        select_representation({})


def test_ollama_payload_uses_schema_options_images_and_no_retry_contract() -> None:
    images = [b"first", b"second"]
    payload = build_ollama_payload("model:tag", images)
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["keep_alive"] == "15m"
    assert payload["format"]["additionalProperties"] is False
    assert payload["options"] == {
        "temperature": 0,
        "seed": 20260802,
        "num_ctx": 4096,
        "num_predict": 96,
    }
    encoded = payload["messages"][0]["images"]
    assert encoded == [base64.b64encode(value).decode("ascii") for value in images]
    json.dumps(payload, allow_nan=False)


def test_swap_usage_parser_returns_used_bytes() -> None:
    payload = "total = 4096.00M  used = 1024.50M  free = 3071.50M  (encrypted)"
    assert parse_swap_used_bytes(payload) == pytest.approx(1024.5 * 1024 * 1024)
    with pytest.raises(RunnerSafetyError, match="swap"):
        parse_swap_used_bytes("unexpected")


def test_model_lifecycle_payload_separates_load_and_unload() -> None:
    assert model_lifecycle_payload("m", unload=False) == {
        "model": "m",
        "messages": [],
        "stream": False,
        "keep_alive": "15m",
    }
    assert model_lifecycle_payload("m", unload=True)["keep_alive"] == 0


def test_resource_command_failure_is_not_silently_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired("memory_pressure", 5)

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(RunnerSafetyError, match="resource_command"):
        ResourceMonitor._command(["memory_pressure", "-Q"])
