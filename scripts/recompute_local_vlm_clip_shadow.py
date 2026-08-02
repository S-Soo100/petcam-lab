"""Runner를 import하지 않고 clip shadow 무결성과 aggregate를 다시 계산해."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
import os
from pathlib import Path
import stat
from typing import Mapping


MAX_REQUESTS = 20


class IntegrityError(RuntimeError):
    """독립 재계산에서 provenance나 ledger 모순을 발견했어."""


def _private_file(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise IntegrityError("private_file")
    return path.read_bytes()


def _private_dir(path: Path) -> None:
    if not path.is_dir() or path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise IntegrityError("private_dir")


def _rows(path: Path) -> list[dict[str, object]]:
    try:
        parsed = [json.loads(line) for line in _private_file(path).decode().splitlines()]
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrityError("jsonl") from exc
    if any(not isinstance(row, dict) for row in parsed):
        raise IntegrityError("jsonl_row")
    return parsed


def _write_new(path: Path, content: str | bytes) -> None:
    payload = content.encode() if isinstance(content, str) else content
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def _percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50": None, "p95": None, "max": None}
    ordered = sorted(values)

    def at(fraction: float) -> float:
        return ordered[min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))]

    return {"p50": at(0.5), "p95": at(0.95), "max": ordered[-1]}


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
    model_inventory = gate.get("model_inventory")
    if not isinstance(model_inventory, dict):
        raise IntegrityError("gate_model")
    model_digest = model_inventory.get("digest")
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
            input_path = run_dir / "inputs" / f"{clip}.jpg"
            actual = hashlib.sha256(_private_file(input_path)).hexdigest()
            if row.get("input_sha256") != actual:
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


def _resource_aggregate(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows or rows[0].get("baseline") is not True:
        raise IntegrityError("resource_baseline")
    samples: list[dict[str, object]] = []
    for row in rows:
        if row.get("type") != "resource" or row.get("clip") != "monitor" or not isinstance(row.get("sample"), dict):
            raise IntegrityError("resource_row")
        sample = row["sample"]
        if not all(key in sample for key in ("free_percent", "swap_used_bytes", "serve_pid", "serve_rss_kib")):
            raise IntegrityError("resource_fields")
        samples.append(sample)
    baseline = samples[0]
    pid = baseline["serve_pid"]
    low_streak = 0
    low_free_abort = False
    for row in samples:
        low_streak = low_streak + 1 if int(row["free_percent"]) <= 5 else 0
        low_free_abort = low_free_abort or low_streak >= 2
    return {
        "free_min_percent": min(int(row["free_percent"]) for row in samples),
        "swap_delta_bytes": max(float(row["swap_used_bytes"]) for row in samples) - float(baseline["swap_used_bytes"]),
        "serve_rss_max_kib": max(int(row["serve_rss_kib"]) for row in samples),
        "pid_drift": any(row["serve_pid"] != pid for row in samples),
        "low_free_abort": low_free_abort,
    }


def _review_html(
    run_dir: Path,
    output_dir: Path,
    intents: Mapping[str, Mapping[str, object]],
    results: Mapping[str, Mapping[str, object]],
) -> str:
    cards: list[str] = []
    for clip in sorted(intents):
        result = results.get(clip, {})
        media = os.path.relpath(run_dir / "media" / f"{clip}.mp4", output_dir)
        prediction = json.dumps(result.get("prediction"), ensure_ascii=False, indent=2)
        cards.append(
            f'<article id="{html.escape(clip)}"><h2>{html.escape(clip)}</h2>'
            f'<video controls preload="metadata" src="{html.escape(media)}"></video>'
            f'<pre>{html.escape(prediction)}</pre></article>'
        )
    return (
        "<!doctype html><meta charset=\"utf-8\"><title>Private local VLM review</title>"
        "<style>body{font-family:sans-serif;max-width:960px;margin:auto}video{width:100%}"
        "article{border-bottom:1px solid #ccc;padding:24px 0}pre{white-space:pre-wrap}</style>"
        "<h1>Private local VLM clip shadow review</h1>" + "".join(cards)
    )


def recompute(run_dir: Path, output_dir: Path) -> dict[str, object]:
    _private_dir(run_dir)
    _private_dir(output_dir)
    gate = json.loads(_private_file(run_dir / "gate-a.json"))
    if not isinstance(gate, dict) or gate.get("model") != "gemma3:4b":
        raise IntegrityError("gate")
    ledger = _rows(run_dir / "ledger.jsonl")
    resources = _rows(run_dir / "resources.jsonl")
    intents, results, media_error, media_retry = _validate_ledger(run_dir, gate, ledger)
    resource = _resource_aggregate(resources)
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
        "schema_version": "production-local-vlm-clip-shadow-independent-summary-v1",
        "attempted": attempted,
        "schema_valid": valid,
        "media_error": media_error,
        "media_retry": media_retry,
        "status_counts": dict(sorted(statuses.items())),
        "latency_sec": _percentiles(elapsed),
        "resource": resource,
        "result_without_intent": 0,
        "duplicate_request": 0,
        "verdict": verdict,
        "gate_sha256": hashlib.sha256(_private_file(run_dir / "gate-a.json")).hexdigest(),
        "ledger_sha256": hashlib.sha256(_private_file(run_dir / "ledger.jsonl")).hexdigest(),
    }
    public = (
        "# Production Local VLM Clip Shadow Canary v1\n\n"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = recompute(args.run_dir, args.output_dir)
    print(json.dumps({"status": "RECOMPUTED", "verdict": summary["verdict"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
