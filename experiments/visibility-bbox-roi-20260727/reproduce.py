"""Historical VLM mismatch 44건의 current baseline 재현 runner.

DB/R2에는 접근하지 않고 local alias mp4만 읽는다. raw clip/run 결과는 gitignored 경로에
durable 저장하고 tracked summary에는 aggregate만 남긴다.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
from typing import Callable

import cv2


MODEL = "claude-sonnet-5"
PASSES = 3
BATCH_SIZE = 4
CALL_TIMEOUT_SEC = 300
ACTIONS = {
    "eating_paste",
    "eating_prey",
    "drinking",
    "shedding",
    "moving",
    "unseen",
    "hand_feeding",
}
TOKEN_KEYS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)
SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "clip_id": {"type": "string"},
                    "action": {"type": "string", "enum": sorted(ACTIONS)},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reasoning": {"type": "string", "maxLength": 300},
                },
                "required": ["clip_id", "action", "confidence", "reasoning"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def sample_times(duration: float) -> list[float]:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("positive_duration_required")
    return [(index + 0.5) * duration / 6 for index in range(6)]


def classify_runs(labels: list[str]) -> str:
    if len(labels) != PASSES or any(label not in ACTIONS for label in labels):
        raise ValueError("invalid_run_labels")
    if len(set(labels)) != 1:
        return "unstable"
    return "stable_correct" if labels[0] == "moving" else "stable_error"


def decide_phase0(summary: dict) -> str:
    if summary["stable_error_clips"] < 10:
        return "VISIBILITY_ROI_REJECT_NO_CURRENT_REPRODUCIBLE_FAILURE"
    return "VISIBILITY_ROI_HOLD_EPISODE_LINK_REQUIRED"


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _common_frame_root(frame_sets: dict[str, list[Path]]) -> str:
    parents = [str(path.parent) for paths in frame_sets.values() for path in paths]
    return str(Path(parents[0]).parent) if len(frame_sets) == 1 else str(
        Path(os.path.commonpath(parents))
    )


def build_command(
    frame_sets: dict[str, list[Path]],
    prompt_path: Path,
) -> list[str]:
    if not 1 <= len(frame_sets) <= BATCH_SIZE:
        raise ValueError("batch_size_1_to_4_required")
    if any(len(paths) != 6 for paths in frame_sets.values()):
        raise ValueError("six_frames_required")
    listing = "\n".join(
        f"- clip_id={alias}: " + ", ".join(str(path) for path in paths)
        for alias, paths in frame_sets.items()
    )
    user_prompt = (
        "각 clip의 프레임 6장을 모두 Read로 열어 시간순으로 보고 대표 행동 하나를 분류해. "
        "clip_id는 입력 그대로 반환해. JSON schema만 출력해.\n" + listing
    )
    return [
        "claude",
        "-p",
        user_prompt,
        "--safe-mode",
        "--tools",
        "Read",
        "--allowed-tools",
        "Read",
        "--add-dir",
        _common_frame_root(frame_sets),
        "--model",
        MODEL,
        "--effort",
        "low",
        "--no-session-persistence",
        "--system-prompt-file",
        str(prompt_path),
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(SCHEMA, separators=(",", ":")),
    ]


def _failure_code(text: str) -> str:
    lowered = text.lower()
    if "not logged in" in lowered:
        return "not_logged_in"
    if any(
        marker in lowered
        for marker in ("session limit", "usage limit", "rate limit", "quota")
    ):
        return "quota_exceeded"
    return "claude_cli_error"


def parse_envelope(stdout: str, expected_aliases: set[str]) -> dict:
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("invalid_envelope") from exc
    if not isinstance(envelope, dict):
        raise RuntimeError("invalid_envelope")
    if envelope.get("is_error"):
        raise RuntimeError(_failure_code(str(envelope.get("result") or "")))
    usage_map = envelope.get("modelUsage")
    if not isinstance(usage_map, dict) or MODEL not in usage_map:
        raise RuntimeError("model_mismatch")
    structured = envelope.get("structured_output")
    if not isinstance(structured, dict) or not isinstance(
        structured.get("items"), list
    ):
        raise RuntimeError("vlm_schema")
    items: dict[str, dict] = {}
    for item in structured["items"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("clip_id"), str)
            or item.get("action") not in ACTIONS
        ):
            raise RuntimeError("vlm_schema")
        alias = item["clip_id"]
        items[alias] = {
            "action": item["action"],
            "confidence": item.get("confidence"),
            "reasoning": item.get("reasoning"),
        }
    if set(items) != expected_aliases:
        raise RuntimeError("clip_set_mismatch")
    raw_usage = usage_map[MODEL]
    usage = {
        "input_tokens": int(raw_usage.get("inputTokens") or 0),
        "cache_creation_input_tokens": int(
            raw_usage.get("cacheCreationInputTokens") or 0
        ),
        "cache_read_input_tokens": int(
            raw_usage.get("cacheReadInputTokens") or 0
        ),
        "output_tokens": int(raw_usage.get("outputTokens") or 0),
    }
    return {"items": items, "usage": usage}


def _run_cli(
    command: list[str],
    *,
    runner: Callable = subprocess.run,
) -> str:
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            timeout=CALL_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("timeout") from exc
    if completed.returncode != 0:
        raise RuntimeError(
            _failure_code(f"{completed.stdout}\n{completed.stderr}")
        )
    return completed.stdout


def run_batches(
    frame_sets: dict[str, list[Path]],
    prompt_path: Path,
    raw_path: Path,
    *,
    passes: int = PASSES,
    batch_size: int = BATCH_SIZE,
    runner: Callable = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    if not 1 <= batch_size <= BATCH_SIZE:
        raise ValueError("batch_size_1_to_4_required")
    raw = json.loads(raw_path.read_text()) if raw_path.exists() else {"passes": {}}
    aliases = sorted(frame_sets)
    for pass_index in range(1, passes + 1):
        pass_key = str(pass_index)
        pass_result = raw["passes"].setdefault(pass_key, {})
        for offset in range(0, len(aliases), batch_size):
            batch_index = offset // batch_size + 1
            batch_key = f"batch-{batch_index:03d}"
            batch_aliases = aliases[offset : offset + batch_size]
            existing = pass_result.get(batch_key)
            if existing and set(existing.get("items", {})) == set(batch_aliases):
                continue
            batch_frames = {alias: frame_sets[alias] for alias in batch_aliases}
            command = build_command(batch_frames, prompt_path)
            last_error: RuntimeError | None = None
            for attempt in range(2):
                try:
                    parsed = parse_envelope(
                        _run_cli(command, runner=runner),
                        set(batch_aliases),
                    )
                    pass_result[batch_key] = {
                        "aliases": batch_aliases,
                        **parsed,
                    }
                    _atomic_json(raw_path, raw)
                    last_error = None
                    break
                except RuntimeError as exc:
                    last_error = exc
                    if str(exc) in {
                        "quota_exceeded",
                        "not_logged_in",
                        "model_mismatch",
                        "clip_set_mismatch",
                    }:
                        raise
                    if attempt == 0:
                        sleep(2)
            if last_error is not None:
                raise last_error
    return raw


def summarize(raw: dict) -> dict:
    clip_labels: dict[str, list[str]] = defaultdict(list)
    tokens: Counter[str] = Counter()
    provider_calls = 0
    for pass_key in sorted(raw.get("passes", {}), key=int):
        for batch_key in sorted(raw["passes"][pass_key]):
            batch = raw["passes"][pass_key][batch_key]
            provider_calls += 1
            for alias, item in batch.get("items", {}).items():
                clip_labels[alias].append(item["action"])
            for key, value in batch.get("usage", {}).items():
                tokens[key] += int(value)
    outcomes = Counter()
    stable_error_actions = Counter()
    completed_runs = 0
    for labels in clip_labels.values():
        completed_runs += len(labels)
        if len(labels) != PASSES:
            continue
        outcome = classify_runs(labels)
        outcomes[outcome] += 1
        if outcome == "stable_error":
            stable_error_actions[labels[0]] += 1
    completed_clips = sum(outcomes.values())
    summary = {
        "completed_clips": completed_clips,
        "completed_runs": completed_runs,
        "provider_calls": provider_calls,
        "stable_correct_clips": outcomes["stable_correct"],
        "stable_error_clips": outcomes["stable_error"],
        "unstable_clips": outcomes["unstable"],
        "unanimity_rate": (
            (outcomes["stable_correct"] + outcomes["stable_error"])
            / completed_clips
            if completed_clips
            else None
        ),
        "stable_error_action_distribution": dict(
            sorted(stable_error_actions.items())
        ),
        "tokens": {
            key: tokens[key]
            for key in TOKEN_KEYS
            if key in tokens
        },
    }
    summary["verdict"] = decide_phase0(summary)
    return summary


def _probe_duration(video_path: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError("ffprobe_failed")
    try:
        return float(completed.stdout.strip())
    except ValueError as exc:
        raise RuntimeError("ffprobe_invalid_duration") from exc


def _normalize_jpeg(path: Path) -> None:
    image = cv2.imread(str(path))
    if image is None:
        raise RuntimeError("frame_decode_failed")
    height, width = image.shape[:2]
    if max(height, width) > 768:
        scale = 768 / max(height, width)
        image = cv2.resize(
            image,
            (round(width * scale), round(height * scale)),
            interpolation=cv2.INTER_AREA,
        )
    if not cv2.imwrite(
        str(path),
        image,
        [cv2.IMWRITE_JPEG_QUALITY, 85],
    ):
        raise RuntimeError("frame_write_failed")


def extract_six(video_path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, timestamp in enumerate(
        sample_times(_probe_duration(video_path)),
        start=1,
    ):
        path = out_dir / f"f_{index:03d}.jpg"
        if not path.exists():
            completed = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    str(path),
                ],
                capture_output=True,
                timeout=60,
            )
            if completed.returncode != 0 or not path.exists():
                raise RuntimeError("frame_extract_failed")
            _normalize_jpeg(path)
        paths.append(path)
    if len(paths) != 6:
        raise RuntimeError("six_frames_required")
    return paths


def _auth_preflight() -> None:
    completed = subprocess.run(
        ["claude", "auth", "status"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    try:
        status = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("auth_probe_failed") from exc
    if completed.returncode != 0 or status.get("loggedIn") is not True:
        raise RuntimeError("auth_probe_failed")


def run_reproduction(
    video_dir: Path,
    prompt_path: Path,
    raw_path: Path,
    summary_path: Path,
) -> dict:
    _auth_preflight()
    videos = sorted(video_dir.glob("review-*.mp4"))
    if len(videos) != 44:
        raise RuntimeError(f"expected_44_videos_got_{len(videos)}")
    frames_root = raw_path.parent / "frames"
    frame_sets = {
        video.stem: extract_six(video, frames_root / video.stem)
        for video in videos
    }
    raw = run_batches(frame_sets, prompt_path, raw_path)
    raw["protocol"] = {
        "model": MODEL,
        "passes": PASSES,
        "batch_size": BATCH_SIZE,
        "prompt_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
        "input": "six-768q85-v1",
    }
    _atomic_json(raw_path, raw)
    summary = {**raw["protocol"], **summarize(raw)}
    _atomic_json(summary_path, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--video-dir", type=Path, required=True)
    run_parser.add_argument("--prompt", type=Path, required=True)
    run_parser.add_argument("--raw-out", type=Path, required=True)
    run_parser.add_argument("--summary-out", type=Path, required=True)
    score_parser = subparsers.add_parser("score")
    score_parser.add_argument("--raw-out", type=Path, required=True)
    score_parser.add_argument("--summary-out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "run":
        summary = run_reproduction(
            args.video_dir,
            args.prompt,
            args.raw_out,
            args.summary_out,
        )
    else:
        raw = json.loads(args.raw_out.read_text(encoding="utf-8"))
        summary = {**raw.get("protocol", {}), **summarize(raw)}
        _atomic_json(args.summary_out, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
