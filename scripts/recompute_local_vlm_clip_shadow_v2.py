"""Runner와 분리해서 v2의 12개 입력·ledger·자원 집계를 다시 계산해."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Mapping

from scripts.recompute_local_vlm_clip_shadow import (
    IntegrityError,
    MAX_REQUESTS,
    _percentiles,
    _private_dir,
    _private_file,
    _resource_aggregate,
    _review_html,
    _rows,
    _write_new,
)


def _validate_ledger(
    run_dir: Path,
    gate: Mapping[str, object],
    rows: list[dict[str, object]],
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]], int, int]:
    intents: dict[str, dict[str, object]] = {}
    results: dict[str, dict[str, object]] = {}
    media_keys: set[str] = set()
    retry_counts: Counter[str] = Counter()
    media_error = 0
    inventory = gate.get("model_inventory")
    if not isinstance(inventory, dict):
        raise IntegrityError("gate_model")
    model_digest = inventory.get("digest")
    prompt_digest = gate.get("prompt_sha256")
    for row in rows:
        kind = row.get("type")
        clip = row.get("clip")
        if not isinstance(kind, str) or not isinstance(clip, str):
            raise IntegrityError("ledger_identity")
        if kind == "request_intent":
            if clip in intents:
                raise IntegrityError("duplicate_request_intent")
            if row.get("model_digest") != model_digest or row.get("prompt_sha256") != prompt_digest:
                raise IntegrityError("digest_drift")
            expected = row.get("input_sha256")
            if not isinstance(expected, list) or len(expected) != 12 or not all(isinstance(item, str) for item in expected):
                raise IntegrityError("input_digest_shape")
            actual = [
                hashlib.sha256(_private_file(run_dir / "inputs" / f"{clip}-{index:02d}.jpg")).hexdigest()
                for index in range(1, 13)
            ]
            if expected != actual:
                raise IntegrityError("input_digest_drift")
            intents[clip] = row
        elif kind == "result":
            if clip not in intents:
                raise IntegrityError("result_without_intent")
            if clip in results:
                raise IntegrityError("duplicate_result")
            results[clip] = row
        elif kind == "media_error":
            if clip in intents or clip in media_keys:
                raise IntegrityError("media_error_after_intent")
            media_keys.add(clip)
            media_error += 1
        elif kind == "media_retry":
            if clip in intents or clip in media_keys:
                raise IntegrityError("media_retry_order")
            retry_counts[clip] += 1
            if retry_counts[clip] > 2:
                raise IntegrityError("media_retry_count")
        else:
            raise IntegrityError("unexpected_ledger_type")
    return intents, results, media_error, sum(retry_counts.values())


def recompute(run_dir: Path, output_dir: Path) -> dict[str, object]:
    _private_dir(run_dir)
    _private_dir(output_dir)
    gate = json.loads(_private_file(run_dir / "gate-a.json"))
    if (
        not isinstance(gate, dict)
        or gate.get("schema_version") != "production-local-vlm-clip-shadow-gate-a-v2"
        or gate.get("model") != "gemma3:4b"
        or gate.get("frame_count") != 12
    ):
        raise IntegrityError("gate")
    intents, results, media_error, media_retry = _validate_ledger(
        run_dir, gate, _rows(run_dir / "ledger.jsonl")
    )
    resource = _resource_aggregate(_rows(run_dir / "resources.jsonl"))
    statuses = Counter(str(row.get("status", "invalid")) for row in results.values())
    elapsed = [
        float(row["elapsed_sec"])
        for row in results.values()
        if isinstance(row.get("elapsed_sec"), (int, float))
    ]
    attempted = len(intents)
    valid = statuses["schema_valid"]
    if resource["pid_drift"] or resource["low_free_abort"] or float(resource["swap_delta_bytes"]) > 1024**3:
        verdict = "REJECT_RESOURCE"
    elif attempted >= MAX_REQUESTS and valid < MAX_REQUESTS:
        verdict = "REJECT_RELIABILITY"
    elif valid >= MAX_REQUESTS:
        verdict = "LIVE_SHADOW_TECHNICAL_PASS"
    else:
        verdict = "INCOMPLETE_LIVE_VOLUME"
    summary: dict[str, object] = {
        "schema_version": "production-local-vlm-clip-shadow-independent-summary-v2",
        "attempted": attempted, "schema_valid": valid,
        "media_error": media_error, "media_retry": media_retry,
        "status_counts": dict(sorted(statuses.items())),
        "latency_sec": _percentiles(elapsed), "resource": resource,
        "result_without_intent": 0, "duplicate_request": 0,
        "verdict": verdict,
        "gate_sha256": hashlib.sha256(_private_file(run_dir / "gate-a.json")).hexdigest(),
        "ledger_sha256": hashlib.sha256(_private_file(run_dir / "ledger.jsonl")).hexdigest(),
    }
    public = (
        "# Production Local VLM Clip Shadow Canary v2\n\n"
        "- input: `12 separate chronological frames per clip`\n"
        f"- verdict: `{verdict}`\n"
        f"- attempted/schema-valid/media-error: `{attempted}/{valid}/{media_error}`\n"
        f"- latency p50/p95/max: `{summary['latency_sec']}`\n"
        f"- free memory min: `{resource['free_min_percent']}%`\n"
        f"- swap delta bytes: `{resource['swap_delta_bytes']}`\n"
        "- production mutation: `0 (runner contract; 별도 운영 감사 필요)`\n"
    )
    _write_new(output_dir / "summary-private.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    _write_new(output_dir / "public-report.md", public)
    _write_new(output_dir / "review-index-private.html", _review_html(run_dir, output_dir, intents, results))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    summary = recompute(args.run_dir, args.output_dir)
    print(json.dumps({"status": "RECOMPUTED", "verdict": summary["verdict"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
