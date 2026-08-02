"""12개 개별 프레임을 쓰는 production local VLM private shadow runner야."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sys
import time
from typing import Any

import cv2
import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path[:0] = [str(_REPO_ROOT)]

from scripts.local_vlm_clip_shadow import RESULT_SCHEMA, parse_observation, stop_reason
from scripts.local_vlm_clip_shadow_v2 import (
    FRAME_FRACTIONS,
    MODEL,
    NUM_CTX,
    NUM_PREDICT,
    PROMPT,
    PROMPT_VERSION,
    build_ollama_payload,
    encode_individual_frames,
)
from scripts.run_local_vlm_clip_shadow import (
    ClipCandidate,
    MediaPermanentError,
    MediaRetryError,
    ResourceMonitor,
    RunnerSafetyError,
    _existing_media,
    _r2_client,
    append_ledger,
    canonical_bytes,
    download_media,
    fetch_candidates,
    git_head,
    ledger_counts,
    load_processed_keys,
    media_retry_count,
    model_inventory,
    ollama_json,
    private_token,
    require_private_dir,
    require_private_file,
    resource_probe,
    select_next_candidate,
    sha256,
    unload_model,
    write_new,
)
from scripts.seed_rba_boundary_review import load_env_file


MAX_REQUESTS = 20
POLL_INTERVAL_SEC = 60
END_AT = datetime.fromisoformat("2026-08-03T07:00:00+09:00")


def extract_frames(path: Path) -> list[np.ndarray]:
    """영상 전체에 고르게 퍼진 12개 시점을 원본 순서대로 읽어."""
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise MediaPermanentError("video_open")
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if count < len(FRAME_FRACTIONS):
            raise MediaPermanentError("video_too_short")
        frames: list[np.ndarray] = []
        for fraction in FRAME_FRACTIONS:
            index = min(count - 1, max(0, round((count - 1) * fraction)))
            if not capture.set(cv2.CAP_PROP_POS_FRAMES, index):
                raise MediaPermanentError("video_seek")
            ok, frame = capture.read()
            if not ok or frame is None:
                raise MediaPermanentError("video_decode")
            frames.append(frame)
        return frames
    finally:
        capture.release()


def make_synthetic_images(scene: str) -> tuple[bytes, ...]:
    frames = [np.zeros((160, 240, 3), dtype=np.uint8) for _ in range(12)]
    if scene == "static_silhouette":
        for frame in frames:
            frame[:] = 235
            cv2.ellipse(frame, (120, 80), (38, 18), 0, 0, 360, (15, 15, 15), -1)
    elif scene == "moving_silhouette":
        for index, frame in enumerate(frames):
            frame[:] = 235
            cv2.ellipse(frame, (40 + index * 14, 80), (28, 14), 0, 0, 360, (15, 15, 15), -1)
    elif scene != "dark_empty":
        raise RunnerSafetyError("synthetic_scene")
    return encode_individual_frames(frames)


def smoke_contract(scene: str) -> tuple[dict[str, object], str, str]:
    cases = {
        "dark_empty": ("background", ["dark", "bright"], "dark"),
        "static_silhouette": ("position_change", ["yes", "no"], "no"),
        "moving_silhouette": ("position_change", ["yes", "no"], "yes"),
    }
    try:
        key, values, expected = cases[scene]
    except KeyError as exc:
        raise RunnerSafetyError("synthetic_scene") from exc
    return ({
        "type": "object",
        "properties": {key: {"type": "string", "enum": values}},
        "required": [key],
        "additionalProperties": False,
    }, key, expected)


def smoke_payload(scene: str, images: tuple[bytes, ...]) -> dict[str, object]:
    schema, key, _ = smoke_contract(scene)
    prompts = {
        "dark_empty": "Inspect the 12 separate images. Is the background dark or bright?",
        "static_silhouette": (
            "The 12 separate images are chronological. Does the dark oval's horizontal position "
            "change from image 1 through image 12?"
        ),
        "moving_silhouette": (
            "The 12 separate images are chronological. Does the dark oval's horizontal position "
            "change from image 1 through image 12?"
        ),
    }
    payload = build_ollama_payload(images)
    payload["format"] = schema
    messages = payload["messages"]
    assert isinstance(messages, list) and isinstance(messages[0], dict)
    messages[0]["content"] = prompts[scene] + f" Return only the {key} schema JSON."
    return payload


def _response_content(response: dict[str, object]) -> str:
    message = response.get("message")
    return str(message.get("content", "")) if isinstance(message, dict) else ""


def gate_a(args: argparse.Namespace) -> dict[str, object]:
    if args.expected_model != MODEL or datetime.fromisoformat(args.end_at) != END_AT:
        raise RunnerSafetyError("model_or_end_mismatch")
    if socket.gethostname() != args.expected_host or git_head() != args.expected_head:
        raise RunnerSafetyError("host_or_head_mismatch")
    require_private_dir(args.output_dir.parent)
    args.output_dir.mkdir(mode=0o700)
    require_private_dir(args.output_dir)
    require_private_file(args.env_file)
    require_private_file(args.salt_file, expected_size=32)
    inventory = model_inventory()
    if MODEL not in inventory:
        raise RunnerSafetyError("model_missing")

    smoke: dict[str, str] = {}
    try:
        for scene in ("dark_empty", "static_silhouette", "moving_silhouette"):
            images = make_synthetic_images(scene)
            response = ollama_json("/api/chat", smoke_payload(scene, images))
            parsed = json.loads(_response_content(response))
            _, key, expected = smoke_contract(scene)
            if not isinstance(parsed, dict) or parsed != {key: expected}:
                raise RunnerSafetyError(f"smoke_{scene}")
            smoke[scene] = f"{key}={expected}"

        production_images = make_synthetic_images("moving_silhouette")
        production_response = ollama_json("/api/chat", build_ollama_payload(production_images))
        parse_observation(_response_content(production_response))
        prompt_eval_count = production_response.get("prompt_eval_count")
        if (
            isinstance(prompt_eval_count, bool)
            or not isinstance(prompt_eval_count, int)
            or prompt_eval_count <= 0
            or prompt_eval_count + NUM_PREDICT > NUM_CTX
        ):
            raise RunnerSafetyError("production_context_budget")
        start_at = datetime.now(timezone.utc)
        manifest = {
            "schema_version": "production-local-vlm-clip-shadow-gate-a-v2",
            "host": args.expected_host,
            "code_head": args.expected_head,
            "model": MODEL,
            "model_inventory": inventory[MODEL],
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": sha256(PROMPT.encode()),
            "schema_sha256": sha256(canonical_bytes(RESULT_SCHEMA)),
            "frame_fractions": list(FRAME_FRACTIONS),
            "frame_count": 12,
            "start_at": start_at.isoformat(),
            "end_at": END_AT.isoformat(),
            "smoke": smoke,
            "production_schema_smoke": "valid",
            "production_prompt_eval_count": prompt_eval_count,
            "production_context_budget": prompt_eval_count + NUM_PREDICT,
            "pre_resource": resource_probe(),
        }
        write_new(args.output_dir / "gate-a.json", canonical_bytes(manifest))
    finally:
        unload_model()
    return manifest


def load_gate_manifest(args: argparse.Namespace) -> dict[str, object]:
    manifest = json.loads(require_private_file(args.output_dir / "gate-a.json"))
    inventory = model_inventory()
    expected = {
        "schema_version": "production-local-vlm-clip-shadow-gate-a-v2",
        "host": args.expected_host,
        "code_head": args.expected_head,
        "model": MODEL,
        "model_inventory": inventory.get(MODEL),
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": sha256(PROMPT.encode()),
        "schema_sha256": sha256(canonical_bytes(RESULT_SCHEMA)),
        "frame_fractions": list(FRAME_FRACTIONS),
        "frame_count": 12,
        "end_at": END_AT.isoformat(),
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise RunnerSafetyError("gate_manifest_drift")
    return manifest


def _input_paths(output_dir: Path, private_key: str) -> tuple[Path, ...]:
    return tuple(output_dir / "inputs" / f"{private_key}-{index:02d}.jpg" for index in range(1, 13))


def _load_or_create_inputs(media_path: Path, paths: tuple[Path, ...]) -> tuple[bytes, ...]:
    existing = [path.exists() for path in paths]
    if all(existing):
        return tuple(require_private_file(path) for path in paths)
    if any(existing):
        for path in paths:
            if path.exists():
                require_private_file(path)
                path.unlink()
    images = encode_individual_frames(extract_frames(media_path))
    for path, image in zip(paths, images, strict=True):
        write_new(path, image)
    return images


def process_candidate(
    candidate: ClipCandidate,
    *,
    salt: bytes,
    output_dir: Path,
    ledger: Path,
    r2: Any,
    bucket: str,
    model_digest: str,
) -> str:
    media_path = output_dir / "media" / f"{candidate.private_key}.mp4"
    input_paths = _input_paths(output_dir, candidate.private_key)
    try:
        if media_path.exists():
            size, media_sha = _existing_media(media_path)
        else:
            for path in input_paths:
                if path.exists():
                    require_private_file(path)
                    path.unlink()
            size, media_sha = download_media(r2, bucket, candidate, media_path)
        images = _load_or_create_inputs(media_path, input_paths)
    except MediaRetryError as exc:
        retries = media_retry_count(ledger, candidate.private_key)
        if retries < 2:
            append_ledger(ledger, {
                "type": "media_retry", "clip": candidate.private_key,
                "camera": private_token(salt, "camera", candidate.camera_id),
                "started_at": candidate.started_at, "attempt": retries + 1,
                "error": type(exc).__name__,
            })
            return "retry"
        append_ledger(ledger, {
            "type": "media_error", "clip": candidate.private_key,
            "camera": private_token(salt, "camera", candidate.camera_id),
            "started_at": candidate.started_at, "error": "transient_exhausted",
        })
        return "processed"
    except (MediaPermanentError, ValueError) as exc:
        append_ledger(ledger, {
            "type": "media_error", "clip": candidate.private_key,
            "camera": private_token(salt, "camera", candidate.camera_id),
            "started_at": candidate.started_at, "error": type(exc).__name__,
        })
        return "processed"

    append_ledger(ledger, {
        "type": "request_intent", "clip": candidate.private_key,
        "camera": private_token(salt, "camera", candidate.camera_id),
        "started_at": candidate.started_at, "duration_sec": candidate.duration_sec,
        "media_size": size, "media_sha256": media_sha,
        "input_sha256": [sha256(image) for image in images],
        "prompt_sha256": sha256(PROMPT.encode()), "model_digest": model_digest,
        "at": datetime.now(timezone.utc).isoformat(),
    })
    started = time.monotonic()
    raw = ""
    status = "invalid"
    prediction: dict[str, object] | None = None
    error_name: str | None = None
    response_meta: dict[str, object] = {}
    try:
        response = ollama_json("/api/chat", build_ollama_payload(images))
        raw = _response_content(response)
        if not raw or len(raw.encode()) > 4096:
            raise ValueError("response_size")
        prediction = asdict(parse_observation(raw))
        status = "schema_valid"
        response_meta = {
            "total_duration_ns": int(response.get("total_duration", 0)),
            "load_duration_ns": int(response.get("load_duration", 0)),
            "prompt_eval_count": int(response.get("prompt_eval_count", 0)),
            "eval_count": int(response.get("eval_count", 0)),
        }
    except TimeoutError as exc:
        status = "timeout"
        error_name = type(exc).__name__
    except Exception as exc:  # retry 0: 실패도 그대로 측정값으로 남겨.
        error_name = type(exc).__name__
    append_ledger(ledger, {
        "type": "result", "clip": candidate.private_key, "status": status,
        "elapsed_sec": time.monotonic() - started, "prediction": prediction,
        "error": error_name, "raw": raw[:4096], "response_meta": response_meta,
    })
    return "processed"


def run_live(args: argparse.Namespace) -> dict[str, object]:
    if args.expected_model != MODEL or datetime.fromisoformat(args.end_at) != END_AT:
        raise RunnerSafetyError("model_or_end_mismatch")
    if socket.gethostname() != args.expected_host or git_head() != args.expected_head:
        raise RunnerSafetyError("host_or_head_mismatch")
    require_private_dir(args.output_dir)
    require_private_file(args.env_file)
    salt = require_private_file(args.salt_file, expected_size=32)
    load_env_file(args.env_file)
    manifest = load_gate_manifest(args)
    start_at = datetime.fromisoformat(str(manifest["start_at"]))

    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RunnerSafetyError("supabase_env")
    client = create_client(url, key)
    r2, bucket = _r2_client()
    for name in ("media", "inputs"):
        path = args.output_dir / name
        if path.exists():
            require_private_dir(path)
        else:
            path.mkdir(mode=0o700)
    ledger = args.output_dir / "ledger.jsonl"
    model_digest = str(manifest["model_inventory"]["digest"])
    verdict = "INCOMPLETE_LIVE_VOLUME"
    try:
        with ResourceMonitor(args.output_dir / "resources.jsonl") as monitor:
            while True:
                attempted, valid = ledger_counts(ledger)
                reason = stop_reason(datetime.now(timezone.utc), END_AT, valid, MAX_REQUESTS, attempted)
                if reason:
                    verdict = reason
                    break
                if monitor.abort.is_set():
                    verdict = "REJECT_RESOURCE"
                    break
                candidates = fetch_candidates(client, start_at=start_at, salt=salt)
                candidate = select_next_candidate(candidates, load_processed_keys(ledger))
                if candidate is None:
                    time.sleep(POLL_INTERVAL_SEC)
                    continue
                outcome = process_candidate(
                    candidate, salt=salt, output_dir=args.output_dir, ledger=ledger,
                    r2=r2, bucket=bucket, model_digest=model_digest,
                )
                if outcome == "retry":
                    time.sleep(POLL_INTERVAL_SEC)
            if monitor.abort.is_set():
                verdict = "REJECT_RESOURCE"
    except RunnerSafetyError:
        verdict = "REJECT_INTEGRITY"
        raise
    finally:
        try:
            unload_model()
        except Exception:
            if verdict not in {"REJECT_INTEGRITY", "REJECT_RESOURCE"}:
                verdict = "REJECT_RESOURCE"
        attempted, valid = ledger_counts(ledger)
        summary = {
            "schema_version": "production-local-vlm-clip-shadow-summary-v2",
            "verdict": verdict, "attempted": attempted, "schema_valid": valid,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "ledger_sha256": sha256(ledger.read_bytes()) if ledger.exists() else None,
        }
        if not (args.output_dir / "summary.json").exists():
            write_new(args.output_dir / "summary.json", canonical_bytes(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("gate-a", "run"):
        command = sub.add_parser(name)
        command.add_argument("--env-file", type=Path, required=True)
        command.add_argument("--salt-file", type=Path, required=True)
        command.add_argument("--output-dir", type=Path, required=True)
        command.add_argument("--expected-host", required=True)
        command.add_argument("--expected-head", required=True)
        command.add_argument("--expected-model", required=True)
        command.add_argument("--end-at", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = gate_a(args) if args.command == "gate-a" else run_live(args)
    print(json.dumps({
        "status": "GATE_A_PASS" if args.command == "gate-a" else result["verdict"],
        "output_dir": str(args.output_dir),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
