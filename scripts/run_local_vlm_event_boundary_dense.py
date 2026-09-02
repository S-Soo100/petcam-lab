"""Mac mini local VLM 두 모델을 경계 밀집 6+6 입력으로 다시 측정해."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import time
from typing import Iterable

import cv2
import numpy as np

from scripts.local_vlm_event_boundary import RESULT_SCHEMA, parse_prediction
from scripts.run_local_vlm_event_boundary import (
    ResourceMonitor,
    _load_model,
    _model_inventory,
    _ollama_json,
    _unload_model,
)
from scripts.run_openai_subscription_vlm_event_boundary import (
    DENSE_CONTRACT,
    load_frozen_inputs,
    score_model_records,
)
from scripts.vlm_event_boundary_dense import DENSE_PROMPT


LOCAL_MODELS = ("minicpm-v4.6:latest", "qwen3-vl:2b")
NUM_CTX = 8192
NUM_PREDICT = 96


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _write_new(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o600)


def _new_private_dir(path: Path) -> None:
    if path.exists():
        raise ValueError("output_exists")
    path.mkdir(mode=0o700)
    path.chmod(0o700)


def build_dense_ollama_payload(model: str, images: Iterable[bytes]) -> dict[str, object]:
    payloads = tuple(images)
    if model not in LOCAL_MODELS or len(payloads) != 2:
        raise ValueError("payload_contract")
    return {
        "model": model,
        "messages": [{
            "role": "user",
            "content": DENSE_PROMPT,
            "images": [base64.b64encode(value).decode("ascii") for value in payloads],
        }],
        "stream": False,
        "think": False,
        "format": RESULT_SCHEMA,
        "keep_alive": "15m",
        "options": {
            "temperature": 0,
            "seed": 20260803,
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
        },
    }


def smoke_response_has_both_images(raw: str) -> bool:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    first = str(payload.get("a", "")).lower()
    second = str(payload.get("b", "")).lower()
    return all(word in first for word in ("red", "square")) and all(
        word in second for word in ("blue", "triangle")
    )


def context_budget_valid(*, prompt_eval_count: int, num_ctx: int, num_predict: int) -> bool:
    return (
        prompt_eval_count > 0
        and num_ctx > 0
        and num_predict > 0
        and prompt_eval_count + num_predict <= num_ctx
    )


def _smoke_images() -> tuple[bytes, bytes]:
    first = np.full((512, 768, 3), 255, dtype=np.uint8)
    second = np.full((512, 768, 3), 255, dtype=np.uint8)
    cv2.rectangle(first, (220, 90), (548, 418), (0, 0, 255), -1)
    triangle = np.array([[384, 70], [160, 430], [608, 430]], np.int32)
    cv2.fillPoly(second, [triangle], (255, 0, 0))
    encoded: list[bytes] = []
    for frame in (first, second):
        ok, payload = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise ValueError("smoke_jpeg")
        encoded.append(payload.tobytes())
    return tuple(encoded)  # type: ignore[return-value]


def _smoke_model(model: str) -> bool:
    payload = build_dense_ollama_payload(model, _smoke_images())
    payload["format"] = "json"
    payload["messages"][0]["content"] = (
        "Look at both attached images. Return JSON with keys a and b. "
        "a must name the color and shape in image A; b must name the color and shape in image B."
    )
    try:
        _load_model(model)
        response = _ollama_json("/api/chat", payload, timeout=120)
        message = response.get("message")
        raw = str(message.get("content", "")) if isinstance(message, dict) else ""
        return smoke_response_has_both_images(raw)
    except Exception:
        return False
    finally:
        try:
            _unload_model(model)
        except Exception:
            pass


def run(args: argparse.Namespace) -> dict[str, object]:
    if socket.gethostname() != args.expected_host:
        raise ValueError("host_mismatch")
    manifest_path = args.source_root / "frozen-manifest.json"
    input_dir = args.source_root / "inputs"
    if _sha256(manifest_path.read_bytes()) != args.expected_manifest_sha256:
        raise ValueError("source_manifest_drift")
    frozen_inputs = load_frozen_inputs(
        manifest_path,
        input_dir,
        contract=DENSE_CONTRACT,
    )
    inventory = _model_inventory()
    if any(model not in inventory for model in LOCAL_MODELS):
        raise ValueError("model_missing")

    smoke = {model: _smoke_model(model) for model in LOCAL_MODELS}
    _new_private_dir(args.output_dir)
    prompt_sha = _sha256(DENSE_PROMPT.encode())
    _write_new(args.output_dir / "frozen-run.json", _canonical_bytes({
        "schema_version": "local-vlm-event-boundary-dense-v2",
        "source_manifest_sha256": args.expected_manifest_sha256,
        "prompt_sha256": prompt_sha,
        "models": {
            model: inventory[model]
            for model in LOCAL_MODELS
        },
        "two_image_smoke": smoke,
        "temperature": 0,
        "seed": 20260803,
        "num_ctx": NUM_CTX,
        "num_predict": NUM_PREDICT,
        "retry": 0,
        "ledger_contains_human_gt_during_model_run": False,
    }))

    human = {row.pair: row.human for row in frozen_inputs}
    summaries: dict[str, object] = {}
    with ResourceMonitor(args.output_dir / "resources.json") as monitor:
        for model in LOCAL_MODELS:
            model_dir = args.output_dir / model.replace(":", "_")
            model_dir.mkdir(mode=0o700)
            model_dir.chmod(0o700)
            ledger_path = model_dir / "results.jsonl"
            descriptor = os.open(ledger_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            records: list[dict[str, object]] = []
            model_started = time.monotonic()
            load_error: str | None = None
            if not smoke[model]:
                load_error = "input_representation_smoke_failed"
            else:
                try:
                    _load_model(model)
                except Exception as exc:
                    load_error = f"load_{type(exc).__name__}"
            try:
                with os.fdopen(descriptor, "wb") as ledger:
                    for row in frozen_inputs:
                        started = time.monotonic()
                        prediction = None
                        error = load_error
                        raw = ""
                        response_meta: dict[str, int] = {}
                        if error is None and monitor.abort.is_set():
                            error = "resource_abort"
                        if error is None:
                            try:
                                response = _ollama_json(
                                    "/api/chat",
                                    build_dense_ollama_payload(
                                        model,
                                        (path.read_bytes() for path in row.image_paths),
                                    ),
                                    timeout=args.timeout_sec,
                                )
                                message = response.get("message")
                                raw = str(message.get("content", "")) if isinstance(message, dict) else ""
                                if len(raw.encode()) > 4096:
                                    raise ValueError("raw_response_too_large")
                                response_meta = {
                                    "prompt_eval_count": int(response.get("prompt_eval_count", 0)),
                                    "eval_count": int(response.get("eval_count", 0)),
                                }
                                if not context_budget_valid(
                                    prompt_eval_count=response_meta["prompt_eval_count"],
                                    num_ctx=NUM_CTX,
                                    num_predict=NUM_PREDICT,
                                ):
                                    error = "context_budget"
                                else:
                                    prediction = parse_prediction(raw)
                            except Exception as exc:
                                error = type(exc).__name__
                        record = {
                            "model": model,
                            "model_digest": str(inventory[model]["digest"]),
                            "pair": row.pair,
                            "input_sha256": list(row.input_sha256),
                            "prompt_sha256": prompt_sha,
                            "elapsed_sec": time.monotonic() - started,
                            "prediction": asdict(prediction) if prediction else None,
                            "error": error,
                            "raw": raw[:4096],
                            "response_meta": response_meta,
                        }
                        records.append(record)
                        ledger.write(_canonical_bytes(record))
                        ledger.flush()
                        os.fsync(ledger.fileno())
            finally:
                if load_error is None:
                    try:
                        _unload_model(model)
                    except Exception:
                        pass
            ledger_path.chmod(0o600)
            aggregate = score_model_records(
                human,
                records,
                expected_count=len(frozen_inputs),
            )
            aggregate["wall_sec"] = time.monotonic() - model_started
            aggregate["ledger_sha256"] = _sha256(ledger_path.read_bytes())
            aggregate["error_counts"] = {
                error: sum(record["error"] == error for record in records)
                for error in sorted({
                    str(record["error"])
                    for record in records
                    if record["error"] is not None
                })
            }
            if not smoke[model]:
                aggregate["operational_verdict"] = "INCONCLUSIVE_INPUT_REPRESENTATION"
            elif any(record["error"] == "context_budget" for record in records):
                aggregate["operational_verdict"] = "INCONCLUSIVE_CONTEXT_BUDGET"
            else:
                aggregate["operational_verdict"] = aggregate["score"]["verdict"]
            summaries[model] = aggregate

    summary = {
        "schema_version": "local-vlm-event-boundary-dense-summary-v2",
        "source_manifest_sha256": args.expected_manifest_sha256,
        "prompt_sha256": prompt_sha,
        "models": summaries,
    }
    summary["summary_sha256"] = _sha256(_canonical_bytes(summary))
    _write_new(args.output_dir / "summary.json", _canonical_bytes(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout-sec", type=int, default=180)
    return parser.parse_args()


def main() -> int:
    summary = run(parse_args())
    print(json.dumps({
        "status": "MEASURED_RUN_COMPLETE",
        "summary_sha256": summary["summary_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
