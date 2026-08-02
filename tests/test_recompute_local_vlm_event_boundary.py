import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.recompute_local_vlm_event_boundary import (
    RecomputeError,
    recompute,
    render_public_summary,
)


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    manifest = {
        "pair_count": 2,
        "prompt_sha256": "f" * 64,
        "models": {
            "m1": {"digest": "a" * 64, "size": 1},
            "m2": {"digest": "b" * 64, "size": 2},
        },
        "inputs": [
            {"pair": "pair-a", "human": "different_event", "images": ["1" * 64]},
            {"pair": "pair-b", "human": "same_event", "images": ["2" * 64]},
        ],
    }
    records = []
    for model, digest in (("m1", "a" * 64), ("m2", "b" * 64)):
        records.extend([
            {
                "model": model,
                "model_digest": digest,
                "pair": "pair-a",
                "human": "different_event",
                "input_sha256": ["1" * 64],
                "elapsed_sec": 1.0,
                "prompt_sha256": "f" * 64,
                "prediction": {
                    "decision": "different_event",
                    "confidence": 0.8,
                    "reason_code": "clear_stop",
                },
                "error": None,
            },
            {
                "model": model,
                "model_digest": digest,
                "pair": "pair-b",
                "human": "same_event",
                "input_sha256": ["2" * 64],
                "elapsed_sec": 2.0,
                "prompt_sha256": "f" * 64,
                "prediction": {
                    "decision": "same_event",
                    "confidence": 0.9,
                    "reason_code": "continuous_motion",
                },
                "error": None,
            },
        ])
    manifest_path = tmp_path / "manifest.json"
    results_path = tmp_path / "results.jsonl"
    manifest_path.write_text(json.dumps(manifest))
    results_path.write_text("".join(json.dumps(row) + "\n" for row in records))
    return manifest_path, results_path


def test_recompute_validates_identity_and_scores_each_model(tmp_path: Path) -> None:
    manifest, results = _write_fixture(tmp_path)
    summary = recompute(manifest, results)
    assert summary["record_count"] == 4
    assert summary["models"]["m1"]["score"]["overmerge"] == 0
    assert summary["models"]["m2"]["score"]["same_correct"] == 1


def test_recompute_rejects_duplicate_or_missing_record(tmp_path: Path) -> None:
    manifest, results = _write_fixture(tmp_path)
    lines = results.read_text().splitlines()
    results.write_text("\n".join(lines[:-1] + [lines[0]]) + "\n")
    with pytest.raises(RecomputeError, match="duplicate|missing"):
        recompute(manifest, results)


def test_recompute_rejects_model_or_input_digest_drift(tmp_path: Path) -> None:
    manifest, results = _write_fixture(tmp_path)
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    rows[0]["model_digest"] = "c" * 64
    results.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(RecomputeError, match="digest"):
        recompute(manifest, results)


def test_recompute_rejects_prompt_digest_drift(tmp_path: Path) -> None:
    manifest, results = _write_fixture(tmp_path)
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    rows[0]["prompt_sha256"] = "0" * 64
    results.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(RecomputeError, match="prompt"):
        recompute(manifest, results)


def test_public_summary_contains_no_uuid_or_private_pair_key(tmp_path: Path) -> None:
    manifest, results = _write_fixture(tmp_path)
    rendered = render_public_summary(recompute(manifest, results))
    assert "pair-a" not in rendered
    assert "123e4567-e89b-12d3-a456-426614174000" not in rendered
    assert "over-merge" in rendered


def test_recompute_supports_direct_script_entrypoint() -> None:
    repo = Path(__file__).resolve().parent.parent
    completed = subprocess.run(
        [sys.executable, "scripts/recompute_local_vlm_event_boundary.py", "--help"],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
