import hashlib
import json
from pathlib import Path

import pytest

from scripts.recompute_local_vlm_clip_shadow import IntegrityError
from scripts.recompute_local_vlm_clip_shadow_v2 import recompute


def _private(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _jsonl(rows: list[dict[str, object]]) -> bytes:
    return b"".join((json.dumps(row, separators=(",", ":")) + "\n").encode() for row in rows)


def _fixture(tmp_path: Path) -> tuple[Path, Path, list[bytes]]:
    run = tmp_path / "run"
    out = tmp_path / "out"
    run.mkdir(mode=0o700)
    out.mkdir(mode=0o700)
    (run / "inputs").mkdir(mode=0o700)
    (run / "media").mkdir(mode=0o700)
    images = [f"jpeg-{index}".encode() for index in range(12)]
    for index, image in enumerate(images, start=1):
        _private(run / "inputs" / f"clip-{index:02d}.jpg", image)
    _private(run / "media" / "clip.mp4", b"video")
    _private(run / "gate-a.json", json.dumps({
        "schema_version": "production-local-vlm-clip-shadow-gate-a-v2",
        "model": "gemma3:4b", "model_inventory": {"digest": "d", "size": 1},
        "prompt_sha256": "p", "frame_count": 12,
    }).encode())
    _private(run / "ledger.jsonl", _jsonl([
        {"type": "request_intent", "clip": "clip", "model_digest": "d", "prompt_sha256": "p",
         "input_sha256": [hashlib.sha256(image).hexdigest() for image in images]},
        {"type": "result", "clip": "clip", "status": "schema_valid", "elapsed_sec": 3.0,
         "prediction": {"summary_ko": "게코가 움직여."}},
    ]))
    _private(run / "resources.jsonl", _jsonl([
        {"type": "resource", "clip": "monitor", "baseline": True,
         "sample": {"free_percent": 60, "swap_used_bytes": 100, "serve_pid": 1, "serve_rss_kib": 10}},
    ]))
    return run, out, images


def test_v2_recompute_validates_all_twelve_ordered_images(tmp_path: Path) -> None:
    run, out, _ = _fixture(tmp_path)
    summary = recompute(run, out)
    assert summary["schema_version"] == "production-local-vlm-clip-shadow-independent-summary-v2"
    assert summary["attempted"] == 1 and summary["schema_valid"] == 1
    assert "Canary v2" in (out / "public-report.md").read_text()


def test_v2_recompute_rejects_one_image_digest_drift(tmp_path: Path) -> None:
    run, out, _ = _fixture(tmp_path)
    _private(run / "inputs" / "clip-07.jpg", b"changed")
    with pytest.raises(IntegrityError, match="input_digest"):
        recompute(run, out)
