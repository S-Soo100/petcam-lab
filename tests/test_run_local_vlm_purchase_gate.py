import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from urllib.error import HTTPError

from scripts.run_local_vlm_purchase_gate import (
    PurchaseGateError,
    build_boundary_payload,
    build_clip_payload,
    resource_violation,
    terminal_status_for_exception,
    load_and_verify_source,
    resolve_exact_pairs,
)


def _jpeg(frame: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok
    return encoded.tobytes()


def test_payloads_keep_all_images_ordered_and_use_frozen_options() -> None:
    images = [f"image-{index}".encode() for index in range(12)]
    clip = build_clip_payload("model:tag", images)
    assert len(clip["messages"][0]["images"]) == 12
    assert clip["options"] == {
        "temperature": 0,
        "seed": 20260802,
        "num_ctx": 8192,
        "num_predict": 96,
    }
    boundary = build_boundary_payload("model:tag", images[:8])
    assert len(boundary["messages"][0]["images"]) == 8
    assert boundary["format"]["additionalProperties"] is False


def test_resolve_exact_pairs_requires_one_hash_match_per_input() -> None:
    a = {"a": np.zeros((20, 20, 3), dtype=np.uint8)}
    b = {"b": np.full((20, 20, 3), 255, dtype=np.uint8)}
    expected = hashlib.sha256(_jpeg(np.vstack((a["a"], b["b"])))).hexdigest()
    assert resolve_exact_pairs(a, b, {"pair": expected}, combine=lambda x, y: np.vstack((x, y)), encode=_jpeg) == {
        "pair": ("a", "b")
    }
    with pytest.raises(PurchaseGateError, match="exact_pair_mapping"):
        resolve_exact_pairs(a, b, {"pair": "0" * 64}, combine=lambda x, y: np.vstack((x, y)), encode=_jpeg)


def test_load_source_rejects_non_private_files(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir(mode=0o700)
    manifest = root / "frozen-manifest.json"
    manifest.write_text(json.dumps({}))
    manifest.chmod(0o644)
    with pytest.raises(PurchaseGateError, match="private"):
        load_and_verify_source(root)


def test_resource_violation_requires_two_low_samples_and_guards_swap_pid() -> None:
    healthy = [
        {"free_percent": 20, "swap_used_bytes": 0, "daemon_pid": 10},
        {"free_percent": 3, "swap_used_bytes": 1024, "daemon_pid": 10},
    ]
    assert resource_violation(healthy) is None
    assert resource_violation([*healthy, {"free_percent": 3, "swap_used_bytes": 2048, "daemon_pid": 10}]) == "low_free_memory"
    assert resource_violation([healthy[0], {"free_percent": 20, "swap_used_bytes": 2 * 1024**3 + 1, "daemon_pid": 10}]) == "swap_growth"
    assert resource_violation([healthy[0], {"free_percent": 20, "swap_used_bytes": 3 * 1024**3, "daemon_pid": 10}, healthy[0]]) == "swap_growth"
    assert resource_violation([healthy[0], {"free_percent": 20, "swap_used_bytes": 0, "daemon_pid": 11}]) == "daemon_pid_drift"


def test_terminal_status_keeps_monitor_abort_separate_from_http_model_failure() -> None:
    assert terminal_status_for_exception(PurchaseGateError("resource_abort:swap_growth"), "synthetic") == "RESOURCE_FAIL"
    http_error = HTTPError("http://localhost", 400, "bad request", {}, None)
    assert terminal_status_for_exception(http_error, "synthetic") == "SYNTHETIC_GATE_FAIL"
    assert terminal_status_for_exception(http_error, "development") == "QUALITY_FAIL"
