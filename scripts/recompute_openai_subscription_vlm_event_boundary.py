"""구독 Codex VLM ledger를 measured runner와 독립적으로 재채점해."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Iterable

from scripts.local_vlm_event_boundary import (
    PROMPT,
    PROMPT_VERSION,
    BoundaryPrediction,
    parse_prediction,
    score_predictions,
)
from scripts.vlm_event_boundary_dense import (
    DENSE_PROMPT,
    DENSE_PROMPT_VERSION,
    DENSE_REPRESENTATION,
)


DEFAULT_MODELS = (
    "gpt-5.4-mini",
    "gpt-5.6-luna",
    "gpt-5.6-terra",
)
INPUT_CONTRACTS = {
    "legacy_4x2": ("combined_4x2", PROMPT_VERSION, PROMPT, 1),
    "boundary_dense_6x2": (
        DENSE_REPRESENTATION,
        DENSE_PROMPT_VERSION,
        DENSE_PROMPT,
        2,
    ),
}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _latency(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    at = lambda fraction: ordered[round((len(ordered) - 1) * fraction)]
    return {"p50": at(0.5), "p95": at(0.95), "max": ordered[-1]}


def recompute(
    source_manifest: Path,
    run_root: Path,
    *,
    expected_count: int = 74,
    models: Iterable[str] = DEFAULT_MODELS,
    input_contract: str = "legacy_4x2",
) -> dict[str, object]:
    representation, prompt_version, prompt, image_count = INPUT_CONTRACTS[input_contract]
    source = json.loads(source_manifest.read_text())
    rows = source.get("inputs") if isinstance(source, dict) else None
    if (
        not isinstance(rows, list)
        or source.get("representation") != representation
        or source.get("prompt_version") != prompt_version
        or source.get("pair_count") != expected_count
        or len(rows) != expected_count
    ):
        raise ValueError("source_manifest")
    human: dict[str, str] = {}
    input_sha: dict[str, str | list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("source_row")
        pair = row.get("pair")
        decision = row.get("human")
        images = row.get("images")
        if (
            not isinstance(pair, str)
            or pair in human
            or decision not in {"same_event", "different_event"}
            or not isinstance(images, list)
            or len(images) != image_count
            or any(not isinstance(image, str) for image in images)
        ):
            raise ValueError("source_row")
        human[pair] = decision
        input_sha[pair] = images[0] if image_count == 1 else images

    prompt_sha = _sha256(prompt.encode())
    model_summaries: dict[str, object] = {}
    record_count = 0
    for model in tuple(models):
        ledger_path = run_root / model / "results.jsonl"
        predictions: dict[str, BoundaryPrediction | None] = {}
        latencies: list[float] = []
        for line in ledger_path.read_text().splitlines():
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("ledger_row")
            pair = record.get("pair")
            elapsed = record.get("elapsed_sec")
            if (
                record.get("model") != model
                or not isinstance(pair, str)
                or pair not in human
                or pair in predictions
                or record.get("input_sha256") != input_sha[pair]
                or record.get("prompt_sha256") != prompt_sha
                or isinstance(elapsed, bool)
                or not isinstance(elapsed, (int, float))
                or elapsed < 0
            ):
                raise ValueError("ledger_contract")
            raw_prediction = record.get("prediction")
            predictions[pair] = (
                None
                if raw_prediction is None
                else parse_prediction(json.dumps(raw_prediction, separators=(",", ":")))
            )
            latencies.append(float(elapsed))
        if set(predictions) != set(human):
            raise ValueError("ledger_identity")
        score = score_predictions(human, predictions, expected_count=expected_count)  # type: ignore[arg-type]
        model_summaries[model] = {
            "score": asdict(score),
            "latency_sec": _latency(latencies),
            "ledger_sha256": _sha256(ledger_path.read_bytes()),
        }
        record_count += len(predictions)

    summary = {
        "schema_version": "openai-subscription-vlm-event-boundary-recompute-v2",
        "record_count": record_count,
        "source_manifest_sha256": _sha256(source_manifest.read_bytes()),
        "prompt_sha256": prompt_sha,
        "representation": representation,
        "prompt_version": prompt_version,
        "models": model_summaries,
    }
    summary["summary_sha256"] = _sha256(_canonical_bytes(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--input-contract", choices=tuple(INPUT_CONTRACTS), default="legacy_4x2")
    args = parser.parse_args()
    summary = recompute(
        args.source_manifest,
        args.run_root,
        input_contract=args.input_contract,
    )
    payload = _canonical_bytes(summary)
    if args.output:
        if args.output.exists():
            raise ValueError("output_exists")
        args.output.write_bytes(payload)
        args.output.chmod(0o600)
    print(payload.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
