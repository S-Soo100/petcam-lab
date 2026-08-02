"""Runner 구현과 독립적으로 local VLM 사건 경계 결과를 재계산해."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.local_vlm_event_boundary import parse_prediction, score_predictions


class RecomputeError(RuntimeError):
    """frozen manifest와 measured 결과가 일치하지 않아."""


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _load_json(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise RecomputeError("manifest_invalid")
    return raw


def recompute(manifest_path: Path, results_path: Path) -> dict[str, object]:
    manifest = _load_json(manifest_path)
    raw_models = manifest.get("models")
    raw_inputs = manifest.get("inputs")
    pair_count = manifest.get("pair_count")
    prompt_sha256 = manifest.get("prompt_sha256")
    if (
        not isinstance(raw_models, dict)
        or not isinstance(raw_inputs, list)
        or not isinstance(pair_count, int)
        or not isinstance(prompt_sha256, str)
        or len(prompt_sha256) != 64
    ):
        raise RecomputeError("manifest_invalid")

    inputs: dict[str, dict[str, object]] = {}
    for row in raw_inputs:
        if not isinstance(row, dict):
            raise RecomputeError("manifest_invalid")
        pair = str(row.get("pair", ""))
        if not pair or pair in inputs:
            raise RecomputeError("manifest_duplicate")
        inputs[pair] = row
    if len(inputs) != pair_count:
        raise RecomputeError("manifest_count")

    records: dict[tuple[str, str], dict[str, object]] = {}
    for line in results_path.read_text().splitlines():
        row = json.loads(line)
        if not isinstance(row, dict):
            raise RecomputeError("record_invalid")
        model = str(row.get("model", ""))
        pair = str(row.get("pair", ""))
        key = (model, pair)
        if model not in raw_models or pair not in inputs:
            raise RecomputeError("unexpected_identity")
        if key in records:
            raise RecomputeError("duplicate_record")
        model_spec = raw_models[model]
        if not isinstance(model_spec, dict) or row.get("model_digest") != model_spec.get("digest"):
            raise RecomputeError("model_digest_drift")
        if row.get("input_sha256") != inputs[pair].get("images"):
            raise RecomputeError("input_digest_drift")
        if row.get("human") != inputs[pair].get("human"):
            raise RecomputeError("human_drift")
        if row.get("prompt_sha256") != prompt_sha256:
            raise RecomputeError("prompt_digest_drift")
        records[key] = row

    expected_keys = {(model, pair) for model in raw_models for pair in inputs}
    if set(records) != expected_keys:
        raise RecomputeError("missing_record")

    summaries: dict[str, object] = {}
    human = {pair: str(row["human"]) for pair, row in inputs.items()}
    for model in sorted(raw_models):
        predictions = {}
        latencies: list[float] = []
        for pair in inputs:
            row = records[(model, pair)]
            prediction = row.get("prediction")
            predictions[pair] = (
                None
                if prediction is None
                else parse_prediction(json.dumps(prediction, separators=(",", ":"), allow_nan=False))
            )
            elapsed = row.get("elapsed_sec")
            if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or elapsed < 0:
                raise RecomputeError("latency_invalid")
            latencies.append(float(elapsed))
        score = score_predictions(human, predictions, expected_count=pair_count)  # type: ignore[arg-type]
        ordered = sorted(latencies)
        percentile = lambda value: ordered[round((len(ordered) - 1) * value)]
        summaries[model] = {
            "score": asdict(score),
            "latency_sec": {
                "p50": percentile(0.5),
                "p95": percentile(0.95),
                "max": ordered[-1],
            },
        }
    summary = {
        "schema_version": "local-vlm-event-boundary-recompute-v1",
        "record_count": len(records),
        "models": summaries,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "results_sha256": hashlib.sha256(results_path.read_bytes()).hexdigest(),
    }
    summary["summary_sha256"] = hashlib.sha256(_canonical_bytes(summary)).hexdigest()
    return summary


def render_public_summary(summary: dict[str, object]) -> str:
    lines = [
        "# Local VLM 사건 경계 독립 재계산",
        "",
        f"- measured record: {summary['record_count']}",
        "",
    ]
    models = summary.get("models", {})
    if not isinstance(models, dict):
        raise RecomputeError("summary_invalid")
    for model, raw in sorted(models.items()):
        if not isinstance(raw, dict) or not isinstance(raw.get("score"), dict):
            raise RecomputeError("summary_invalid")
        score: dict[str, Any] = raw["score"]
        latency: dict[str, Any] = raw["latency_sec"]
        lines.extend([
            f"## {model}",
            "",
            f"- verdict: `{score['verdict']}`",
            f"- over-merge: {score['overmerge']}",
            f"- over-split: {score['oversplit']}",
            f"- same recall: {score['same_recall']:.2%}",
            f"- p95 latency: {latency['p95']:.3f}s",
            "",
        ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--public-report", type=Path)
    args = parser.parse_args()
    summary = recompute(args.manifest, args.results)
    if args.public_report:
        if args.public_report.exists():
            raise RecomputeError("public_report_exists")
        args.public_report.write_text(render_public_summary(summary))
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
