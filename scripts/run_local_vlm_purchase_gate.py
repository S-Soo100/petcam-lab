"""MacBook에서 local VLM 모델 사다리를 private one-shot으로 실행해."""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import threading
import time
from typing import Callable, Iterable, Mapping
from urllib import error as urlerror
from urllib import request

import cv2
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path[:0] = [str(_ROOT)]

from scripts.local_vlm_event_boundary import (
    A_FRAME_FRACTIONS,
    B_FRAME_FRACTIONS,
    PROMPT as BOUNDARY_PROMPT,
    RESULT_SCHEMA as BOUNDARY_SCHEMA,
    BoundaryPrediction,
    parse_prediction,
    score_predictions,
)
from scripts.local_vlm_purchase_gate import (
    MODELS,
    SyntheticPrediction,
    boundary_synthetic_cases,
    clip_synthetic_cases,
    parse_synthetic_prediction,
    purchase_verdict,
)
from scripts.run_local_vlm_event_boundary import (
    _combined_sheet,
    _encode_jpeg,
    _fit_long_edge,
    build_contact_sheet,
    extract_frames,
    parse_swap_used_bytes,
)


OLLAMA_BASE = "http://127.0.0.1:11434"
EXPECTED_OLLAMA_VERSION = "0.32.5"
EXPECTED_PAIRS = 74
EXPECTED_MEDIA = 78
NUM_CTX = 8192
NUM_PREDICT = 96
TIMEOUT_SEC = 180
EXPECTED_MODEL_INVENTORY = {
    "gemma3:4b-it-q8_0": ("2376388dec1627f34e046065f670ff8af8f766f8aa0968363cc997c2565f48e0", 4_979_946_122),
    "gemma4:12b-it-qat": ("38044be4f923e5a55264ed7df4eaac2676651a905f735197c504045140c02bd3", 7_151_003_754),
    "qwen3-vl:8b-instruct-q4_K_M": ("0533d74300e4f9bc367d675d4e64ffd073d50ff16a2b4096cc2e8a1cf8c96319", 6_140_415_975),
    "qwen3-vl:30b-a3b-instruct-q4_K_M": ("c871fc73fabc5516500b70a298ea25fd44a6a23d5cffc46c63b50302543e3915", 19_595_410_126),
}

SYNTHETIC_SCHEMA = {
    "type": "object",
    "properties": {
        "background": {"type": "string", "enum": ["dark", "lit"]},
        "position_change": {"type": "string", "enum": ["yes", "no", "uncertain"]},
    },
    "required": ["background", "position_change"],
    "additionalProperties": False,
}
CLIP_PROMPT = """Images 1 through 12 are chronological frames from one camera clip.
Ignore moving shadows and global infrared brightness changes. Judge whether the light-colored oval animal itself changes physical position.
Return JSON only: background is dark only when the scene is nearly black, otherwise lit; position_change is yes, no, or uncertain."""
BOUNDARY_PROMPT_V2 = """Images 1-4 are chronological frames from video A. Images 5-8 are chronological frames from the immediately following video B.
Judge only visible continuity of the light-colored animal. same_event means its physical movement/posture continues across A to B. different_event means a clear stop, reset, jump, or new scene. Return only the requested JSON.""" + "\n" + BOUNDARY_PROMPT


class PurchaseGateError(RuntimeError):
    pass


def resource_violation(rows: list[Mapping[str, object]]) -> str | None:
    if not rows:
        return None
    first_pid = rows[0].get("daemon_pid")
    if any(row.get("daemon_pid") != first_pid for row in rows):
        return "daemon_pid_drift"
    if len(rows) >= 2 and all(
        isinstance(row.get("free_percent"), int) and int(row["free_percent"]) <= 3
        for row in rows[-2:]
    ):
        return "low_free_memory"
    baseline = rows[0].get("swap_used_bytes")
    swaps = [row.get("swap_used_bytes") for row in rows]
    if isinstance(baseline, (int, float)) and all(isinstance(value, (int, float)) for value in swaps) and max(swaps) - baseline > 2 * 1024**3:
        return "swap_growth"
    return None


def terminal_status_for_exception(exc: Exception, phase: str) -> str:
    if isinstance(exc, urlerror.HTTPError):
        return "SYNTHETIC_GATE_FAIL" if phase == "synthetic" else "QUALITY_FAIL"
    if isinstance(exc, (TimeoutError, urlerror.URLError, ConnectionError)) or "resource" in str(exc):
        return "RESOURCE_FAIL"
    return "SYNTHETIC_GATE_FAIL" if phase == "synthetic" else "QUALITY_FAIL"


class ResourceMonitor:
    def __init__(self, output: Path):
        self.output = output
        self.rows: list[dict[str, object]] = []
        self.stop = threading.Event()
        self.abort_reason: str | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    @staticmethod
    def _command(args: list[str]) -> str:
        completed = subprocess.run(args, text=True, capture_output=True, timeout=5)
        if completed.returncode != 0:
            raise PurchaseGateError("resource_command")
        return completed.stdout.strip()

    def _snapshot(self) -> dict[str, object]:
        pressure = self._command(["/usr/bin/memory_pressure", "-Q"])
        free_values = [int(token) for token in pressure.replace("%", "").split() if token.isdigit() and 0 <= int(token) <= 100]
        if not free_values:
            raise PurchaseGateError("memory_pressure_parse")
        swap = parse_swap_used_bytes(self._command(["/usr/sbin/sysctl", "-n", "vm.swapusage"]))
        pid_text = self._command(["/usr/sbin/lsof", "-nP", "-iTCP:11434", "-sTCP:LISTEN", "-t"])
        pids = {int(value) for value in pid_text.splitlines() if value.isdigit()}
        if len(pids) != 1:
            raise PurchaseGateError("daemon_pid")
        return {"monotonic_sec": time.monotonic(), "free_percent": free_values[-1], "swap_used_bytes": swap, "daemon_pid": next(iter(pids))}

    def _run(self) -> None:
        try:
            while not self.stop.is_set():
                self.rows.append(self._snapshot())
                self.abort_reason = resource_violation(self.rows)
                if self.abort_reason:
                    return
                self.stop.wait(2)
        except Exception as exc:
            self.rows.append({"monitor_error": type(exc).__name__})
            self.abort_reason = "monitor_error"

    def check(self) -> None:
        if self.abort_reason:
            raise PurchaseGateError(f"resource_abort:{self.abort_reason}")

    def __enter__(self) -> "ResourceMonitor":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        self.thread.join(timeout=5)
        _write_new(self.output, _canonical(self.rows))


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _private_file(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise PurchaseGateError("private_file")
    return path.read_bytes()


def _write_new(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _new_dir(path: Path) -> None:
    if not path.parent.is_dir() or stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
        raise PurchaseGateError("output_parent_mode")
    path.mkdir(mode=0o700)


def _payload(model: str, images: Iterable[bytes], prompt: str, schema: object) -> dict[str, object]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(value).decode() for value in images]}],
        "stream": False,
        "think": False,
        "format": schema,
        "keep_alive": "15m",
        "options": {"temperature": 0, "seed": 20260802, "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT},
    }


def build_clip_payload(model: str, images: Iterable[bytes]) -> dict[str, object]:
    return _payload(model, images, CLIP_PROMPT, SYNTHETIC_SCHEMA)


def build_boundary_payload(model: str, images: Iterable[bytes]) -> dict[str, object]:
    return _payload(model, images, BOUNDARY_PROMPT_V2, BOUNDARY_SCHEMA)


def _ollama(endpoint: str, payload: object, *, timeout: int = TIMEOUT_SEC) -> dict[str, object]:
    req = request.Request(f"{OLLAMA_BASE}{endpoint}", data=_canonical(payload), headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=timeout) as response:
        parsed = json.loads(response.read())
    if not isinstance(parsed, dict):
        raise PurchaseGateError("ollama_response")
    return parsed


def _inventory() -> dict[str, dict[str, object]]:
    with request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=10) as response:
        payload = json.loads(response.read())
    rows = payload.get("models")
    if not isinstance(rows, list):
        raise PurchaseGateError("ollama_inventory")
    return {str(row["name"]): {"digest": str(row["digest"]), "size": int(row["size"])} for row in rows}


def _unload(model: str) -> None:
    _ollama("/api/chat", {"model": model, "messages": [], "stream": False, "keep_alive": 0}, timeout=30)


def _content(response: Mapping[str, object]) -> str:
    message = response.get("message")
    if not isinstance(message, dict):
        raise ValueError("message")
    content = str(message.get("content", ""))
    if not content or len(content.encode()) > 4096:
        raise ValueError("content")
    prompt_count = response.get("prompt_eval_count")
    if isinstance(prompt_count, bool) or not isinstance(prompt_count, int) or prompt_count + NUM_PREDICT > NUM_CTX:
        raise ValueError("context_budget")
    return content


def resolve_exact_pairs(
    a_sheets: Mapping[str, np.ndarray],
    b_sheets: Mapping[str, np.ndarray],
    wanted: Mapping[str, str],
    *,
    combine: Callable[[np.ndarray, np.ndarray], np.ndarray] = _combined_sheet,
    encode: Callable[[np.ndarray], bytes] = _encode_jpeg,
) -> dict[str, tuple[str, str]]:
    by_digest: dict[str, list[tuple[str, str]]] = {}
    wanted_digests = set(wanted.values())
    for a_key, a_sheet in a_sheets.items():
        for b_key, b_sheet in b_sheets.items():
            digest = _sha(encode(combine(a_sheet, b_sheet)))
            if digest in wanted_digests:
                by_digest.setdefault(digest, []).append((a_key, b_key))
    if set(by_digest) != wanted_digests or any(len(rows) != 1 for rows in by_digest.values()):
        raise PurchaseGateError("exact_pair_mapping")
    return {pair: by_digest[digest][0] for pair, digest in wanted.items()}


def load_and_verify_source(root: Path) -> dict[str, object]:
    if not root.is_dir() or stat.S_IMODE(root.stat().st_mode) != 0o700:
        raise PurchaseGateError("private_source_dir")
    manifest_path = root / "frozen-manifest.json"
    manifest = json.loads(_private_file(manifest_path))
    if manifest.get("pair_count") != EXPECTED_PAIRS or manifest.get("clip_count") != EXPECTED_MEDIA or manifest.get("representation") != "combined_4x2":
        raise PurchaseGateError("source_manifest")
    inputs = {p.stem.removesuffix("-AB"): p for p in (root / "inputs").glob("*-AB.jpg")}
    media = {p.stem: p for p in (root / "media").glob("*.mp4")}
    if len(inputs) != EXPECTED_PAIRS or len(media) != EXPECTED_MEDIA:
        raise PurchaseGateError("source_counts")
    for row in manifest["inputs"]:
        path = inputs.get(str(row["pair"]))
        if path is None or _sha(_private_file(path)) != row["images"][0]:
            raise PurchaseGateError("source_input_hash")
    for row in manifest["media"]:
        path = media.get(str(row["clip"]))
        payload = _private_file(path) if path else b""
        if not payload or len(payload) != row["size"] or _sha(payload) != row["sha256"]:
            raise PurchaseGateError("source_media_hash")
    return {"manifest": manifest, "inputs": inputs, "media": media, "manifest_sha256": _sha(_private_file(manifest_path))}


def _individual_frames(path: Path, fractions: tuple[float, ...]) -> tuple[bytes, ...]:
    return tuple(_encode_jpeg(_fit_long_edge(frame, 768)) for frame in extract_frames(path, fractions))


def prepare_development(source: Mapping[str, object]) -> tuple[list[dict[str, object]], dict[str, tuple[bytes, ...]]]:
    manifest = source["manifest"]
    media = source["media"]
    a_sheets = {key: build_contact_sheet(extract_frames(path, A_FRAME_FRACTIONS), label="A") for key, path in media.items()}
    b_sheets = {key: build_contact_sheet(extract_frames(path, B_FRAME_FRACTIONS), label="B") for key, path in media.items()}
    wanted = {str(row["pair"]): str(row["images"][0]) for row in manifest["inputs"]}
    mapping = resolve_exact_pairs(a_sheets, b_sheets, wanted)
    human = {str(row["pair"]): str(row["human"]) for row in manifest["inputs"]}
    inputs: dict[str, tuple[bytes, ...]] = {}
    rows = []
    for pair in sorted(mapping):
        left, right = mapping[pair]
        images = _individual_frames(media[left], A_FRAME_FRACTIONS) + _individual_frames(media[right], B_FRAME_FRACTIONS)
        inputs[pair] = images
        rows.append({"pair": pair, "human": human[pair], "images": [_sha(value) for value in images], "source_combined_sha256": wanted[pair]})
    return rows, inputs


def _jpeg_frames(frames: Iterable[np.ndarray]) -> tuple[bytes, ...]:
    return tuple(_encode_jpeg(_fit_long_edge(frame, 768)) for frame in frames)


def _terminal(handle: object, model: str, status: str, detail: object = None) -> None:
    handle.write(_canonical({"stage": "terminal", "model": model, "status": status, "detail": detail}))
    handle.flush()
    os.fsync(handle.fileno())


def run(args: argparse.Namespace) -> dict[str, object]:
    if socket.gethostname() != args.expected_host:
        raise PurchaseGateError("host_mismatch")
    version = subprocess.run([args.ollama_bin, "--version"], text=True, capture_output=True, timeout=10, check=True).stdout
    if EXPECTED_OLLAMA_VERSION not in version:
        raise PurchaseGateError("ollama_version")
    source = load_and_verify_source(args.source_root)
    development_rows, development_inputs = prepare_development(source)
    inventory = _inventory()
    valid_inventory = {
        model: row for model, row in inventory.items()
        if model in EXPECTED_MODEL_INVENTORY
        and (row.get("digest"), row.get("size")) == EXPECTED_MODEL_INVENTORY[model]
    }
    _new_dir(args.output_dir)
    synthetic_rows = []
    for case in clip_synthetic_cases():
        images = _jpeg_frames(case.frames)
        synthetic_rows.append({"kind": "clip", "case": case.name, "expected": asdict(case.expected), "images": [_sha(v) for v in images]})
    for case in boundary_synthetic_cases():
        images = _jpeg_frames(case.frames)
        synthetic_rows.append({"kind": "boundary", "case": case.name, "expected": case.expected, "images": [_sha(v) for v in images]})
    frozen = {
        "schema_version": "local-vlm-purchase-gate-v1",
        "source_manifest_sha256": source["manifest_sha256"],
        "runtime": EXPECTED_OLLAMA_VERSION,
        "models": {model: ({"available": True, **valid_inventory[model]} if model in valid_inventory else {"available": False}) for model in MODELS},
        "model_order": list(MODELS),
        "synthetic": synthetic_rows,
        "development": development_rows,
        "clip_prompt_sha256": _sha(CLIP_PROMPT.encode()),
        "boundary_prompt_sha256": _sha(BOUNDARY_PROMPT_V2.encode()),
    }
    _write_new(args.output_dir / "frozen-manifest.json", _canonical(frozen))
    results_path = args.output_dir / "results.jsonl"
    handle = os.fdopen(os.open(results_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")
    statuses: dict[str, str] = {}
    try:
        for model in MODELS:
            if model not in valid_inventory:
                statuses[model] = "TAG_UNAVAILABLE"
                _terminal(handle, model, statuses[model])
                continue
            synthetic_ok = True
            phase = "synthetic"
            try:
                resource_name = hashlib.sha256(model.encode()).hexdigest()[:12]
                with ResourceMonitor(args.output_dir / f"resources-{resource_name}.json") as monitor:
                    for repeat in range(2):
                        for case in clip_synthetic_cases():
                            started = time.monotonic()
                            raw = ""
                            prediction = None
                            error = None
                            try:
                                response = _ollama("/api/chat", build_clip_payload(model, _jpeg_frames(case.frames)))
                                monitor.check()
                                raw = _content(response)
                                prediction = parse_synthetic_prediction(raw)
                            except urlerror.HTTPError as exc:
                                error = f"HTTP_{exc.code}"
                            except PurchaseGateError:
                                raise
                            except (TimeoutError, urlerror.URLError, ConnectionError):
                                raise
                            except Exception as exc:
                                error = type(exc).__name__
                            passed = prediction == case.expected
                            synthetic_ok &= passed
                            handle.write(_canonical({"stage": "synthetic", "kind": "clip", "model": model, "case": case.name, "repeat": repeat, "expected": asdict(case.expected), "prediction": asdict(prediction) if prediction else None, "passed": passed, "error": error, "elapsed_sec": time.monotonic()-started, "raw": raw}))
                        for case in boundary_synthetic_cases():
                            started = time.monotonic()
                            raw = ""
                            prediction = None
                            error = None
                            try:
                                response = _ollama("/api/chat", build_boundary_payload(model, _jpeg_frames(case.frames)))
                                monitor.check()
                                raw = _content(response)
                                prediction = parse_prediction(raw)
                            except urlerror.HTTPError as exc:
                                error = f"HTTP_{exc.code}"
                            except PurchaseGateError:
                                raise
                            except (TimeoutError, urlerror.URLError, ConnectionError):
                                raise
                            except Exception as exc:
                                error = type(exc).__name__
                            passed = prediction is not None and prediction.decision == case.expected
                            synthetic_ok &= passed
                            handle.write(_canonical({"stage": "synthetic", "kind": "boundary", "model": model, "case": case.name, "repeat": repeat, "expected": case.expected, "prediction": asdict(prediction) if prediction else None, "passed": passed, "error": error, "elapsed_sec": time.monotonic()-started, "raw": raw}))
                        handle.flush(); os.fsync(handle.fileno())
                    if not synthetic_ok:
                        statuses[model] = "SYNTHETIC_GATE_FAIL"
                        _terminal(handle, model, statuses[model])
                        continue
                    phase = "development"
                    predictions: dict[str, BoundaryPrediction | None] = {}
                    human = {str(row["pair"]): str(row["human"]) for row in development_rows}
                    for row in development_rows:
                        pair = str(row["pair"])
                        started = time.monotonic()
                        raw = ""
                        prediction = None
                        error = None
                        try:
                            response = _ollama("/api/chat", build_boundary_payload(model, development_inputs[pair]))
                            monitor.check()
                            raw = _content(response)
                            prediction = parse_prediction(raw)
                        except urlerror.HTTPError as exc:
                            error = f"HTTP_{exc.code}"
                        except (TimeoutError, urlerror.URLError, ConnectionError):
                            raise
                        except PurchaseGateError:
                            raise
                        except Exception as exc:
                            error = type(exc).__name__
                        predictions[pair] = prediction
                        handle.write(_canonical({"stage": "development", "model": model, "pair": pair, "human": human[pair], "input_sha256": row["images"], "prediction": asdict(prediction) if prediction else None, "error": error, "elapsed_sec": time.monotonic()-started, "raw": raw}))
                        handle.flush(); os.fsync(handle.fileno())
                    score = score_predictions(human, predictions, expected_count=EXPECTED_PAIRS)
                    statuses[model] = "PASS" if score.verdict == "DEVELOPMENT_CANDIDATE" else "QUALITY_FAIL"
                    _terminal(handle, model, statuses[model], asdict(score))
            except Exception as exc:
                statuses[model] = terminal_status_for_exception(exc, phase)
                _terminal(handle, model, statuses[model], type(exc).__name__)
            finally:
                _unload(model)
    finally:
        handle.close()
    post_inventory = _inventory()
    if any(
        model in valid_inventory and post_inventory.get(model) != valid_inventory[model]
        for model in MODELS
    ):
        raise PurchaseGateError("model_digest_drift")
    summary = {"schema_version": "local-vlm-purchase-gate-summary-v1", "statuses": statuses, "purchase_verdict": purchase_verdict(statuses), "manifest_sha256": _sha((args.output_dir / "frozen-manifest.json").read_bytes()), "results_sha256": _sha(results_path.read_bytes())}
    _write_new(args.output_dir / "summary.json", _canonical(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--ollama-bin", default="/opt/homebrew/bin/ollama")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), sort_keys=True))
