"""Purchase Gate measured JSONL을 runner import 없이 독립 재계산해."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path[:0] = [str(_ROOT)]

from scripts.local_vlm_event_boundary import parse_prediction, score_predictions
from scripts.local_vlm_purchase_gate import MODELS, parse_synthetic_prediction, purchase_verdict


class RecomputeError(RuntimeError):
    pass


def recompute(manifest_path: Path, results_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict) or not isinstance(manifest.get("models"), dict):
        raise RecomputeError("manifest")
    records = [json.loads(line) for line in results_path.read_text().splitlines()]
    terminals = {}
    for row in records:
        if row.get("stage") == "terminal":
            model = str(row.get("model", ""))
            if model in terminals:
                raise RecomputeError("terminal_duplicate")
            terminals[model] = row
    if set(terminals) != set(manifest["models"]):
        raise RecomputeError("terminal_missing")
    statuses = {model: str(terminals[model].get("status")) for model in manifest["models"]}
    for model in MODELS:
        if statuses[model] == "PASS" or statuses[model] == "QUALITY_FAIL":
            rows = [row for row in records if row.get("stage") == "development" and row.get("model") == model]
            inputs = {str(row["pair"]): row for row in manifest["development"]}
            if len(rows) != 74 or {str(row.get("pair")) for row in rows} != set(inputs):
                raise RecomputeError("development_count")
            if any(
                row.get("input_sha256") != inputs[str(row["pair"])].get("images")
                or row.get("human") != inputs[str(row["pair"])].get("human")
                for row in rows
            ):
                raise RecomputeError("development_input_drift")
            predictions = {str(row["pair"]): parse_prediction(json.dumps(row["prediction"])) for row in rows}
            human = {pair: str(item["human"]) for pair, item in inputs.items()}
            score = score_predictions(human, predictions, expected_count=74)
            expected_status = "PASS" if score.verdict == "DEVELOPMENT_CANDIDATE" else "QUALITY_FAIL"
            if statuses[model] != expected_status:
                raise RecomputeError("status_drift")
        synthetic = [row for row in records if row.get("stage") == "synthetic" and row.get("model") == model]
        if statuses[model] in {"PASS", "QUALITY_FAIL", "SYNTHETIC_GATE_FAIL"} and len(synthetic) != 18:
            raise RecomputeError("synthetic_count")
        if statuses[model] in {"PASS", "QUALITY_FAIL"} and not all(row.get("passed") is True for row in synthetic):
            raise RecomputeError("synthetic_status")
        if statuses[model] == "SYNTHETIC_GATE_FAIL" and synthetic and all(row.get("passed") is True for row in synthetic):
            raise RecomputeError("synthetic_status")
        for row in synthetic:
            if row.get("prediction") is None:
                continue
            if row.get("kind") == "clip":
                parse_synthetic_prediction(json.dumps(row["prediction"]))
            else:
                parse_prediction(json.dumps(row["prediction"]))
    return {"schema_version": "local-vlm-purchase-gate-recompute-v1", "statuses": statuses, "purchase_verdict": purchase_verdict(statuses), "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(), "results_sha256": hashlib.sha256(results_path.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(recompute(args.manifest, args.results), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
