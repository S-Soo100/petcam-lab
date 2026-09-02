import hashlib
import json
from pathlib import Path

from scripts.recompute_local_vlm_event_boundary_dense import recompute
from scripts.vlm_event_boundary_dense import (
    DENSE_PROMPT,
    DENSE_PROMPT_VERSION,
    DENSE_REPRESENTATION,
)


def test_recompute_local_dense_reads_gt_free_ledger(tmp_path: Path) -> None:
    images = [hashlib.sha256(value).hexdigest() for value in (b"a", b"b")]
    manifest = tmp_path / "frozen-manifest.json"
    manifest.write_text(json.dumps({
        "pair_count": 1,
        "representation": DENSE_REPRESENTATION,
        "prompt_version": DENSE_PROMPT_VERSION,
        "inputs": [{
            "pair": "p1",
            "human": "different_event",
            "images": images,
        }],
    }))
    run_root = tmp_path / "run"
    model_dir = run_root / "minicpm-v4.6_latest"
    model_dir.mkdir(parents=True)
    record = {
        "model": "minicpm-v4.6:latest",
        "pair": "p1",
        "input_sha256": images,
        "prompt_sha256": hashlib.sha256(DENSE_PROMPT.encode()).hexdigest(),
        "elapsed_sec": 1.2,
        "prediction": {
            "decision": "different_event",
            "confidence": 0.8,
            "reason_code": "clear_stop",
        },
        "error": None,
        "response_meta": {"prompt_eval_count": 2000, "eval_count": 20},
    }
    (model_dir / "results.jsonl").write_text(json.dumps(record) + "\n")

    summary = recompute(
        manifest,
        run_root,
        expected_count=1,
        models=("minicpm-v4.6:latest",),
    )

    score = summary["models"]["minicpm-v4.6:latest"]["score"]
    assert score["overmerge"] == 0
    assert score["different_correct"] == 1
    assert summary["record_count"] == 1
