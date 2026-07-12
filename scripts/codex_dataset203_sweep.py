#!/usr/bin/env python3
"""dataset-203 Codex model sweep.

Codex CLI 에 이미지 프레임을 붙여 호출하고, 모델/입력표현별로 토큰·정확도·속도를
같은 샘플에서 비교한다. 원본 파일명에 GT가 들어있으므로 모델에는 중립 sample id와
추출 이미지 경로만 노출한다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import statistics
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "storage" / "dataset-203"
EXPERIMENT_DIR = REPO_ROOT / "experiments" / "codex-dataset203-model-sweep"
VIDEO_EXTS = {".mp4", ".mov"}

ALLOWED_ACTIONS = [
    "eating_paste",
    "eating_prey",
    "drinking",
    "shedding",
    "moving",
    "unseen",
    "hand_feeding",
]
FEEDING_MERGE = {"drinking": "feeding", "eating_paste": "feeding"}


@dataclass(frozen=True, slots=True)
class ClipRow:
    filename: str
    clip_id: str
    gt: str
    species: str = ""
    source: str = ""
    quality_tag: str = ""


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int = 0
    source: str = "codex-json"


@dataclass(frozen=True, slots=True)
class CallRecord:
    sample_id: str
    clip_id: str
    gt: str
    source_filename: str
    model: str
    representation: str
    image_count: int
    duration_sec: float
    predicted_action: str
    confidence: float
    reasoning: str
    needs_human_review: bool
    usage: TokenUsage | None
    estimated_input_tokens: int | None
    wall_seconds: float
    returncode: int
    error: str | None
    prompt_mode: str = "v40"


@dataclass(frozen=True, slots=True)
class PreparedInput:
    sample_id: str
    representation: str
    image_paths: tuple[Path, ...]
    duration_sec: float


def load_manifest(path: Path) -> list[ClipRow]:
    rows: list[ClipRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(
                ClipRow(
                    filename=row["filename"],
                    clip_id=row["clip_id"],
                    gt=row["gt"],
                    species=row.get("species", ""),
                    source=row.get("source", ""),
                    quality_tag=row.get("quality_tag", ""),
                )
            )
    return rows


def select_stratified(rows: Sequence[ClipRow], target_size: int, seed: int) -> list[ClipRow]:
    """GT 비율을 대략 유지하되 2건 이하 rare class 는 전부 포함한다."""
    if target_size <= 0:
        raise ValueError("target_size must be positive")
    if target_size >= len(rows):
        return sorted(rows, key=lambda r: (r.gt, r.clip_id, r.filename))

    groups: dict[str, list[ClipRow]] = defaultdict(list)
    for row in rows:
        groups[row.gt].append(row)

    if target_size < len(groups):
        rng = random.Random(seed)
        pool = sorted(rows, key=lambda r: (r.gt, r.clip_id, r.filename))
        return sorted(rng.sample(pool, target_size), key=lambda r: (r.gt, r.clip_id, r.filename))

    total = len(rows)
    quotas: dict[str, int] = {}
    fractions: dict[str, float] = {}
    for gt, group in groups.items():
        exact = target_size * len(group) / total
        if len(group) <= 2:
            quota = min(len(group), target_size)
        else:
            quota = max(1, min(len(group), math.floor(exact)))
        quotas[gt] = quota
        fractions[gt] = exact - math.floor(exact)

    while sum(quotas.values()) > target_size:
        candidates = [
            gt
            for gt, group in groups.items()
            if quotas[gt] > 1 and not (len(group) <= 2 and quotas[gt] == len(group))
        ]
        if not candidates:
            candidates = [gt for gt in groups if quotas[gt] > 1]
        if not candidates:
            break
        gt = sorted(candidates, key=lambda k: (fractions[k], -quotas[k], k))[0]
        quotas[gt] -= 1

    while sum(quotas.values()) < target_size:
        candidates = [gt for gt, group in groups.items() if quotas[gt] < len(group)]
        if not candidates:
            break
        gt = sorted(candidates, key=lambda k: (-fractions[k], -len(groups[k]), k))[0]
        quotas[gt] += 1

    selected: list[ClipRow] = []
    for gt in sorted(groups):
        group = sorted(groups[gt], key=lambda r: (r.clip_id, r.filename))
        rng = random.Random(f"{seed}:{gt}")
        rng.shuffle(group)
        selected.extend(group[: quotas[gt]])

    return sorted(selected, key=lambda r: (r.gt, r.clip_id, r.filename))


def sample_id_for(row: ClipRow, index: int) -> str:
    digest = hashlib.sha1(row.clip_id.encode("utf-8")).hexdigest()[:8]
    return f"sample-{index:03d}-{digest}"


def probe_duration(path: Path) -> float:
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            text=True,
        ).strip()
        return float(out) if out and out != "N/A" else 60.0
    except Exception:  # noqa: BLE001 - 실험 스크립트는 건별 실패보다 기본값이 낫다.
        return 60.0


def adaptive_n(dur: float, interval: float = 3.5, lo: int = 6, hi: int = 20) -> int:
    return max(lo, min(hi, round(dur / interval)))


def extract_frames(video_path: Path, out_dir: Path, *, force: bool = False) -> tuple[Path, ...]:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = tuple(sorted(out_dir.glob("frame_*.jpg")))
    if existing and not force:
        return existing

    for old in out_dir.glob("frame_*.jpg"):
        old.unlink()

    dur = probe_duration(video_path)
    n_frames = adaptive_n(dur)
    output: list[Path] = []
    for i in range(n_frames):
        t = (i + 0.5) * dur / n_frames
        fp = out_dir / f"frame_{i:03d}.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{t:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                "scale=1080:1080:force_original_aspect_ratio=decrease",
                "-q:v",
                "3",
                str(fp),
            ],
            capture_output=True,
            check=False,
        )
        if fp.exists():
            output.append(fp)
    return tuple(output)


def make_contact_sheet(video_path: Path, out_path: Path, *, scale: int = 360, force: bool = False) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists() and not force:
        return out_path

    dur = probe_duration(video_path)
    cols, rows = 5, 6
    fps = max(cols * rows / dur, 0.2)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"fps={fps:.4f},scale={scale}:-2,tile={cols}x{rows}",
            "-frames:v",
            "1",
            str(out_path),
        ],
        capture_output=True,
        check=False,
    )
    if not out_path.exists():
        raise RuntimeError(f"failed to create contact sheet: {video_path}")
    return out_path


def sheet_scale_for(representation: str) -> int:
    if representation == "contact-sheet":
        return 360
    match = re.fullmatch(r"contact-sheet-(\d+)", representation)
    if not match:
        raise ValueError(f"unknown contact sheet representation: {representation}")
    return int(match.group(1))


def prepare_input(
    row: ClipRow,
    sample_id: str,
    representation: str,
    *,
    dataset_dir: Path,
    experiment_dir: Path,
    force_assets: bool = False,
) -> PreparedInput:
    video_path = dataset_dir / row.filename
    duration = probe_duration(video_path)
    base = experiment_dir / "assets" / sample_id / representation
    if representation == "frames-adaptive":
        images = extract_frames(video_path, base, force=force_assets)
    elif representation.startswith("contact-sheet"):
        images = (
            make_contact_sheet(
                video_path,
                base / "contact.jpg",
                scale=sheet_scale_for(representation),
                force=force_assets,
            ),
        )
    else:
        raise ValueError(f"unknown representation: {representation}")
    if not images:
        raise RuntimeError(f"no images prepared for {sample_id} {representation}")
    return PreparedInput(sample_id, representation, tuple(images), duration)


def extract_usage_from_text(text: str) -> TokenUsage | None:
    usages: list[TokenUsage] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        usages.extend(_find_usage(obj))
    return usages[-1] if usages else None


def _find_usage(obj: Any) -> list[TokenUsage]:
    found: list[TokenUsage] = []
    if isinstance(obj, dict):
        usage = _usage_from_dict(obj)
        if usage is not None:
            found.append(usage)
        for value in obj.values():
            found.extend(_find_usage(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_usage(item))
    return found


def _usage_from_dict(d: dict[str, Any]) -> TokenUsage | None:
    input_tokens = _first_int(d, "input_tokens", "prompt_tokens", "prompt_token_count")
    output_tokens = _first_int(d, "output_tokens", "completion_tokens", "candidates_token_count")
    total_tokens = _first_int(d, "total_tokens", "total_token_count")
    cached = _first_int(d, "cached_input_tokens", "cached_tokens") or 0
    if input_tokens is None and total_tokens is None:
        return None
    if input_tokens is None:
        input_tokens = max(0, (total_tokens or 0) - (output_tokens or 0))
    if output_tokens is None:
        output_tokens = max(0, (total_tokens or input_tokens) - input_tokens)
    if total_tokens is None:
        total_tokens = input_tokens + output_tokens
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_input_tokens=cached,
    )


def _first_int(d: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = d.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def extract_prediction(text: str) -> tuple[str, float, str, bool]:
    parsed = _extract_json_object(text)
    if parsed:
        action = str(parsed.get("predicted_action") or parsed.get("action") or "ERROR")
        confidence = _to_float(parsed.get("confidence"), default=0.0)
        reasoning = str(parsed.get("reasoning") or parsed.get("evidence") or "")
        review = bool(parsed.get("needs_human_review", False))
        return action, confidence, reasoning, review

    action = "ERROR"
    for candidate in ALLOWED_ACTIONS:
        if re.search(rf"\b{re.escape(candidate)}\b", text, re.IGNORECASE):
            action = candidate
            break
    confidence_match = re.search(r"confidence\s*[:=]\s*([01](?:\.\d+)?)", text, re.IGNORECASE)
    confidence = float(confidence_match.group(1)) if confidence_match else 0.0
    return action, confidence, text[:1000], True


def _extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    first, last = stripped.find("{"), stripped.rfind("}")
    if first >= 0 and last > first:
        candidates.append(stripped[first : last + 1])
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _to_float(value: Any, *, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def token_metric(record: CallRecord) -> int | None:
    if record.usage is not None:
        return record.usage.input_tokens
    return record.estimated_input_tokens


def summarize_records(records: Sequence[CallRecord]) -> dict[str, Any]:
    successful = [r for r in records if r.returncode == 0]
    by_key: dict[str, dict[str, Any]] = {}
    grouped: dict[tuple[str, str, str], list[CallRecord]] = defaultdict(list)
    for record in successful:
        grouped[(record.model, record.prompt_mode, record.representation)].append(record)

    for (model, prompt_mode, representation), rows in sorted(grouped.items()):
        correct = sum(1 for r in rows if r.predicted_action == r.gt)
        merged = sum(
            1
            for r in rows
            if FEEDING_MERGE.get(r.predicted_action, r.predicted_action)
            == FEEDING_MERGE.get(r.gt, r.gt)
        )
        token_values = [t for r in rows if (t := token_metric(r)) is not None]
        by_key[f"{model}|{prompt_mode}|{representation}"] = {
            "model": model,
            "prompt_mode": prompt_mode,
            "representation": representation,
            "n": len(rows),
            "accuracy": correct / len(rows),
            "correct": correct,
            "feeding_merged_accuracy": merged / len(rows),
            "avg_input_tokens": statistics.mean(token_values) if token_values else None,
            "avg_output_tokens": statistics.mean(
                [r.usage.output_tokens for r in rows if r.usage is not None]
            )
            if any(r.usage is not None for r in rows)
            else None,
            "avg_wall_seconds": statistics.mean(r.wall_seconds for r in rows),
            "median_wall_seconds": statistics.median(r.wall_seconds for r in rows),
            "errors": 0,
        }

    paired: dict[str, dict[str, Any]] = {}
    models = sorted({r.model for r in successful})
    for model in models:
        model_rows = [r for r in successful if r.model == model]
        baseline = by_key.get(f"{model}|v40|frames-adaptive")
        if baseline is None:
            for prompt_mode in sorted({r.prompt_mode for r in model_rows}):
                baseline = by_key.get(f"{model}|{prompt_mode}|frames-adaptive")
                if baseline is not None:
                    break
        if not baseline:
            continue
        for candidate_prompt in sorted({r.prompt_mode for r in model_rows}):
            candidate_reprs = sorted(
                {r.representation for r in model_rows if r.prompt_mode == candidate_prompt}
            )
            for candidate_repr in candidate_reprs:
                if candidate_prompt == baseline["prompt_mode"] and candidate_repr == "frames-adaptive":
                    continue
                candidate = by_key.get(f"{model}|{candidate_prompt}|{candidate_repr}")
                if not candidate:
                    continue
                reduction = None
                if baseline["avg_input_tokens"] and candidate["avg_input_tokens"] is not None:
                    reduction = 1 - candidate["avg_input_tokens"] / baseline["avg_input_tokens"]
                paired[
                    f"{model}|{candidate_prompt}|{candidate_repr}_vs_"
                    f"{baseline['prompt_mode']}|frames-adaptive"
                ] = {
                    "model": model,
                    "prompt_mode": candidate_prompt,
                    "candidate": candidate_repr,
                    "baseline_prompt_mode": baseline["prompt_mode"],
                    "baseline": "frames-adaptive",
                    "token_reduction": reduction,
                    "accuracy_drop_pp": (baseline["accuracy"] - candidate["accuracy"]) * 100,
                    "avg_wall_seconds_delta": candidate["avg_wall_seconds"] - baseline["avg_wall_seconds"],
                }

    errors = [r for r in records if r.returncode != 0]
    return {
        "total_records": len(records),
        "successful_records": len(successful),
        "error_records": len(errors),
        "by_model_repr": by_key,
        "paired": paired,
    }


def cascade_summary(
    records: Sequence[CallRecord],
    *,
    model: str,
    threshold: float,
    primary_repr: str = "contact-sheet",
    fallback_repr: str = "frames-adaptive",
    primary_prompt_mode: str = "v40",
    fallback_prompt_mode: str = "v40",
) -> dict[str, Any]:
    primary = {
        r.sample_id: r
        for r in records
        if r.model == model
        and r.prompt_mode == primary_prompt_mode
        and r.representation == primary_repr
        and r.returncode == 0
    }
    fallback = {
        r.sample_id: r
        for r in records
        if r.model == model
        and r.prompt_mode == fallback_prompt_mode
        and r.representation == fallback_repr
        and r.returncode == 0
    }
    sample_ids = sorted(set(primary) & set(fallback))
    if not sample_ids:
        return {
            "model": model,
            "primary_prompt_mode": primary_prompt_mode,
            "fallback_prompt_mode": fallback_prompt_mode,
            "primary_repr": primary_repr,
            "fallback_repr": fallback_repr,
            "threshold": threshold,
            "n": 0,
            "fallback_rate": None,
            "accuracy": None,
            "token_reduction": None,
            "avg_wall_seconds": None,
        }

    correct = 0
    fallbacks = 0
    cascade_tokens = 0
    frame_tokens = 0
    wall = 0.0
    for sample_id in sample_ids:
        p = primary[sample_id]
        f = fallback[sample_id]
        p_tokens = token_metric(p) or 0
        f_tokens = token_metric(f) or 0
        use_fallback = p.confidence < threshold or p.predicted_action not in ALLOWED_ACTIONS
        if use_fallback:
            chosen = f
            fallbacks += 1
            cascade_tokens += p_tokens + f_tokens
            wall += p.wall_seconds + f.wall_seconds
        else:
            chosen = p
            cascade_tokens += p_tokens
            wall += p.wall_seconds
        frame_tokens += f_tokens
        if chosen.predicted_action == chosen.gt:
            correct += 1

    reduction = 1 - cascade_tokens / frame_tokens if frame_tokens else None
    return {
        "model": model,
        "primary_prompt_mode": primary_prompt_mode,
        "fallback_prompt_mode": fallback_prompt_mode,
        "primary_repr": primary_repr,
        "fallback_repr": fallback_repr,
        "threshold": threshold,
        "n": len(sample_ids),
        "fallback_rate": fallbacks / len(sample_ids),
        "accuracy": correct / len(sample_ids),
        "token_reduction": reduction,
        "avg_wall_seconds": wall / len(sample_ids),
    }


def estimate_image_input_tokens(image_paths: Sequence[Path]) -> int | None:
    """Codex usage 이벤트가 없을 때만 쓰는 거친 이미지 토큰 추정치."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return None

    total = 0
    for path in image_paths:
        with Image.open(path) as im:
            w, h = im.size
        total += 85 + 170 * math.ceil(w / 512) * math.ceil(h / 512)
    return total


def build_prompt(representation: str, image_count: int, prompt_mode: str) -> str:
    if prompt_mode == "v40":
        prompt = (DATASET_DIR / "prompt_v4.0.md").read_text(encoding="utf-8")
    elif prompt_mode == "compact":
        prompt = compact_prompt()
    else:
        raise ValueError(f"unknown prompt mode: {prompt_mode}")
    if representation == "frames-adaptive":
        input_note = (
            f"Below are {image_count} still frames sampled evenly across a motion clip, "
            "in chronological order. Judge the dominant behavior across the whole sequence."
        )
    else:
        input_note = (
            "The attached image is a 5x6 contact sheet: 30 frames sampled evenly across "
            "a motion clip, left-to-right and top-to-bottom."
        )
    return f"""
{prompt}

# Blind evaluation input
{input_note}

Allowed actions: {", ".join(ALLOWED_ACTIONS)}

Return JSON only:
{{
  "predicted_action": "one of the allowed actions",
  "confidence": 0.0,
  "reasoning": "short visual evidence",
  "needs_human_review": false
    }}
    """.strip()


def compact_prompt() -> str:
    return """
You classify crested gecko petcam clips into exactly one action.

Classes:
- hand_feeding: human hand/tool visibly delivers food, prey, or paste to the gecko.
- eating_prey: visible live prey plus locked attention, stalking, lunge, bite, or chewing after capture.
- eating_paste: visible food dish/paste plus repeated tongue contact with paste.
- drinking: body/head anchored at one external surface with repeated licking; visible water is not required.
- shedding: visible loose/pale old skin plus active biting, pulling, rubbing, or removal.
- moving: default for locomotion, climbing, posture shifts, sensing tongue flicks, grooming, or ambiguous action.
- unseen: gecko absent or only an unidentifiable fragment for the clip.

Priority: hand_feeding > eating_prey > eating_paste > drinking > shedding > moving > unseen.
When ambiguous, choose moving. Do not infer food or prey if it is not visible. Single tongue flicks are not eating or drinking.
Return JSON only with predicted_action, confidence, reasoning, needs_human_review.
""".strip()


def write_output_schema(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "predicted_action": {"type": "string", "enum": ALLOWED_ACTIONS},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"},
            "needs_human_review": {"type": "boolean"},
        },
        "required": ["predicted_action", "confidence", "reasoning", "needs_human_review"],
    }
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def run_codex_call(
    row: ClipRow,
    prepared: PreparedInput,
    *,
    model: str,
    experiment_dir: Path,
    prompt_mode: str = "v40",
    reasoning_effort: str | None = "low",
    force: bool = False,
) -> CallRecord:
    model_slug = slugify(model)
    call_dir = experiment_dir / "calls" / model_slug / slugify(prompt_mode) / prepared.representation
    call_dir.mkdir(parents=True, exist_ok=True)
    record_path = call_dir / f"{prepared.sample_id}.json"
    if record_path.exists() and not force:
        return record_from_dict(json.loads(record_path.read_text(encoding="utf-8")))

    blind_workspace = Path(tempfile.gettempdir()) / "petcam-codex-dataset203-blind-workspace"
    blind_workspace.mkdir(parents=True, exist_ok=True)
    schema_path = write_output_schema(experiment_dir / "output-schema.json")
    last_message_path = call_dir / f"{prepared.sample_id}.last-message.txt"
    stdout_path = call_dir / f"{prepared.sample_id}.stdout.jsonl"
    stderr_path = call_dir / f"{prepared.sample_id}.stderr.txt"
    prompt = build_prompt(prepared.representation, len(prepared.image_paths), prompt_mode)

    cmd = [
        "codex",
        "exec",
    ]
    if reasoning_effort:
        cmd.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    cmd.extend(
        [
        "-s",
        "read-only",
        "--skip-git-repo-check",
        "-C",
        str(blind_workspace),
        "--ephemeral",
        "--ignore-rules",
        "--model",
        model,
        "--output-last-message",
        str(last_message_path),
        "--output-schema",
        str(schema_path),
        "--json",
        ]
    )
    for image_path in prepared.image_paths:
        cmd.extend(["--image", str(image_path)])
    cmd.extend(["--", prompt])

    t0 = time.perf_counter()
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    wall_seconds = time.perf_counter() - t0
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")

    raw_text = last_message_path.read_text(encoding="utf-8") if last_message_path.exists() else ""
    usage = extract_usage_from_text(proc.stdout + "\n" + proc.stderr)
    estimated = estimate_image_input_tokens(prepared.image_paths) if usage is None else None
    error = None if proc.returncode == 0 else (proc.stderr.strip() or proc.stdout.strip())[:2000]
    action, confidence, reasoning, review = extract_prediction(raw_text or proc.stdout or proc.stderr)

    record = CallRecord(
        sample_id=prepared.sample_id,
        clip_id=row.clip_id,
        gt=row.gt,
        source_filename=row.filename,
        model=model,
        representation=prepared.representation,
        image_count=len(prepared.image_paths),
        duration_sec=prepared.duration_sec,
        predicted_action=action,
        confidence=confidence,
        reasoning=reasoning,
        needs_human_review=review,
        usage=usage,
        estimated_input_tokens=estimated,
        wall_seconds=wall_seconds,
        returncode=proc.returncode,
        error=error,
        prompt_mode=prompt_mode,
    )
    record_path.write_text(json.dumps(record_to_dict(record), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def record_to_dict(record: CallRecord) -> dict[str, Any]:
    return asdict(record)


def record_from_dict(payload: dict[str, Any]) -> CallRecord:
    usage = payload.get("usage")
    return CallRecord(
        sample_id=payload["sample_id"],
        clip_id=payload["clip_id"],
        gt=payload["gt"],
        source_filename=payload["source_filename"],
        model=payload["model"],
        representation=payload["representation"],
        image_count=int(payload["image_count"]),
        duration_sec=float(payload["duration_sec"]),
        predicted_action=payload.get("predicted_action", "ERROR"),
        confidence=float(payload.get("confidence", 0.0)),
        reasoning=payload.get("reasoning", ""),
        needs_human_review=bool(payload.get("needs_human_review", False)),
        usage=TokenUsage(**usage) if isinstance(usage, dict) else None,
        estimated_input_tokens=payload.get("estimated_input_tokens"),
        wall_seconds=float(payload.get("wall_seconds", 0.0)),
        returncode=int(payload.get("returncode", 1)),
        error=payload.get("error"),
        prompt_mode=payload.get("prompt_mode", "v40"),
    )


def load_records(experiment_dir: Path) -> list[CallRecord]:
    records = []
    for path in sorted((experiment_dir / "calls").glob("*/*/*.json")):
        records.append(record_from_dict(json.loads(path.read_text(encoding="utf-8"))))
    for path in sorted((experiment_dir / "calls").glob("*/*/*/*.json")):
        records.append(record_from_dict(json.loads(path.read_text(encoding="utf-8"))))
    return records


def write_results(records: Sequence[CallRecord], experiment_dir: Path) -> dict[str, Any]:
    experiment_dir.mkdir(parents=True, exist_ok=True)
    results_path = experiment_dir / "results.jsonl"
    with results_path.open("w", encoding="utf-8") as f:
        for record in sorted(records, key=lambda r: (r.model, r.prompt_mode, r.representation, r.sample_id)):
            f.write(json.dumps(record_to_dict(record), ensure_ascii=False) + "\n")

    summary = summarize_records(records)
    successful = [r for r in records if r.returncode == 0]
    models = sorted({r.model for r in successful})
    cascades = []
    for model in models:
        model_rows = [r for r in successful if r.model == model]
        fallback_prompt = "v40" if any(
            r.prompt_mode == "v40" and r.representation == "frames-adaptive" for r in model_rows
        ) else sorted({r.prompt_mode for r in model_rows})[0]
        if not any(
            r.prompt_mode == fallback_prompt and r.representation == "frames-adaptive" for r in model_rows
        ):
            continue
        primary_groups = sorted(
            {
                (r.prompt_mode, r.representation)
                for r in model_rows
                if r.representation != "frames-adaptive"
            }
        )
        for primary_prompt, primary_repr in primary_groups:
            for threshold in (0.5, 0.6, 0.7, 0.8, 0.9):
                cascades.append(
                    cascade_summary(
                        records,
                        model=model,
                        threshold=threshold,
                        primary_repr=primary_repr,
                        fallback_repr="frames-adaptive",
                        primary_prompt_mode=primary_prompt,
                        fallback_prompt_mode=fallback_prompt,
                    )
                )
    summary["cascade"] = [row for row in cascades if row["n"]]
    (experiment_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_summary_csv(summary, experiment_dir / "summary.csv")
    write_report(summary, records, experiment_dir / "REPORT.md")
    return summary


def write_summary_csv(summary: dict[str, Any], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["kind", "model", "prompt_mode", "representation", "n", "accuracy", "avg_input_tokens", "avg_wall_seconds"]
        )
        for row in summary["by_model_repr"].values():
            writer.writerow(
                [
                    "model_repr",
                    row["model"],
                    row["prompt_mode"],
                    row["representation"],
                    row["n"],
                    row["accuracy"],
                    row["avg_input_tokens"],
                    row["avg_wall_seconds"],
                ]
            )
        writer.writerow([])
        writer.writerow(
            [
                "kind",
                "model",
                "prompt_mode",
                "candidate",
                "baseline_prompt_mode",
                "token_reduction",
                "accuracy_drop_pp",
                "avg_wall_seconds_delta",
            ]
        )
        for row in summary["paired"].values():
            writer.writerow(
                [
                    "paired",
                    row["model"],
                    row["prompt_mode"],
                    row["candidate"],
                    row["baseline_prompt_mode"],
                    row["token_reduction"],
                    row["accuracy_drop_pp"],
                    row["avg_wall_seconds_delta"],
                ]
            )


def write_report(summary: dict[str, Any], records: Sequence[CallRecord], path: Path) -> None:
    usage_missing = sum(1 for r in records if r.returncode == 0 and r.usage is None)
    lines = [
        "# Codex dataset-203 model sweep",
        "",
        "## Summary",
        "",
        f"- total records: {summary['total_records']}",
        f"- successful records: {summary['successful_records']}",
        f"- error records: {summary['error_records']}",
        f"- successful records without Codex usage JSON: {usage_missing}",
        "",
        "## Model x Representation",
        "",
        "| model | prompt | repr | N | accuracy | avg input tok | avg sec | median sec |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["by_model_repr"].values():
        lines.append(
            "| {model} | {prompt_mode} | {representation} | {n} | {acc} | {tok} | {sec} | {med} |".format(
                model=row["model"],
                prompt_mode=row["prompt_mode"],
                representation=row["representation"],
                n=row["n"],
                acc=_pct(row["accuracy"]),
                tok=_num(row["avg_input_tokens"]),
                sec=_num(row["avg_wall_seconds"]),
                med=_num(row["median_wall_seconds"]),
            )
        )

    lines.extend(
        [
            "",
            "## Paired Reduction",
            "",
            "| model | prompt | candidate | baseline prompt | token reduction | accuracy drop | speed delta sec |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in summary["paired"].values():
        lines.append(
            "| {model} | {prompt_mode} | {candidate} | {baseline_prompt_mode} | {red} | {drop}pp | {delta} |".format(
                model=row["model"],
                prompt_mode=row["prompt_mode"],
                candidate=row["candidate"],
                baseline_prompt_mode=row["baseline_prompt_mode"],
                red=_pct(row["token_reduction"]),
                drop=_num(row["accuracy_drop_pp"]),
                delta=_num(row["avg_wall_seconds_delta"]),
            )
        )

    if summary.get("cascade"):
        lines.extend(
            [
                "",
                "## Cascade Simulation",
                "",
                "| model | primary | fallback | threshold | N | fallback rate | accuracy | token reduction | avg sec |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in summary["cascade"]:
            lines.append(
                "| {model} | {primary_prompt}/{primary_repr} | {fallback_prompt}/{fallback_repr} | {threshold} | {n} | {fallback} | {acc} | {red} | {sec} |".format(
                    model=row["model"],
                    primary_prompt=row["primary_prompt_mode"],
                    fallback_prompt=row["fallback_prompt_mode"],
                    primary_repr=row["primary_repr"],
                    fallback_repr=row["fallback_repr"],
                    threshold=row["threshold"],
                    n=row["n"],
                    fallback=_pct(row["fallback_rate"]),
                    acc=_pct(row["accuracy"]),
                    red=_pct(row["token_reduction"]),
                    sec=_num(row["avg_wall_seconds"]),
                )
            )

    lines.extend(["", "## Confusion", ""])
    for model_repr, pairs in confusion_by_group(records).items():
        lines.append(f"### {model_repr}")
        if not pairs:
            lines.append("")
            lines.append("- no errors")
            lines.append("")
            continue
        for pair, count in pairs.most_common(8):
            lines.append(f"- {count}x {pair}")
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def confusion_by_group(records: Sequence[CallRecord]) -> dict[str, Counter[str]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        if record.returncode != 0 or record.predicted_action == record.gt:
            continue
        grouped[f"{record.model}|{record.prompt_mode}|{record.representation}"][
            f"{record.gt} -> {record.predicted_action}"
        ] += 1
    return dict(grouped)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _num(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return f"{value:,}"


def slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")


def write_sample_list(samples: Sequence[tuple[str, ClipRow]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "sample_id": sample_id,
            "clip_id": row.clip_id,
            "gt": row.gt,
            "filename": row.filename,
            "source": row.source,
            "quality_tag": row.quality_tag,
        }
        for sample_id, row in samples
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex model sweep on dataset-203")
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--experiment-dir", type=Path, default=EXPERIMENT_DIR)
    parser.add_argument("--sample-size", type=int, default=1)
    parser.add_argument("--seed", type=int, default=203)
    parser.add_argument("--models", nargs="+", default=["gpt-5.5"])
    parser.add_argument("--prompt-mode", choices=["v40", "compact"], default="v40")
    parser.add_argument("--reasoning-effort", default="low", help="Codex model_reasoning_effort override")
    parser.add_argument(
        "--representations",
        nargs="+",
        choices=[
            "contact-sheet",
            "contact-sheet-180",
            "contact-sheet-120",
            "contact-sheet-96",
            "frames-adaptive",
        ],
        default=["contact-sheet", "frames-adaptive"],
    )
    parser.add_argument("--max-calls", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--force-assets", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--summarize-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    experiment_dir: Path = args.experiment_dir
    experiment_dir.mkdir(parents=True, exist_ok=True)

    if args.summarize_only:
        records = load_records(experiment_dir)
        summary = write_results(records, experiment_dir)
        print_summary(summary, experiment_dir)
        return 0

    rows = load_manifest(args.dataset_dir / "manifest.csv")
    selected = select_stratified(rows, target_size=args.sample_size, seed=args.seed)
    samples = [(sample_id_for(row, i + 1), row) for i, row in enumerate(selected)]
    write_sample_list(samples, experiment_dir / "sample_list.json")

    calls = 0
    for sample_id, row in samples:
        for representation in args.representations:
            prepared = prepare_input(
                row,
                sample_id,
                representation,
                dataset_dir=args.dataset_dir,
                experiment_dir=experiment_dir,
                force_assets=args.force_assets,
            )
            if args.prepare_only:
                print(f"PREP {sample_id} {representation} images={len(prepared.image_paths)}")
                continue
            for model in args.models:
                if args.max_calls is not None and calls >= args.max_calls:
                    print(f"STOP max-calls={args.max_calls}")
                    records = load_records(experiment_dir)
                    summary = write_results(records, experiment_dir)
                    print_summary(summary, experiment_dir)
                    return 0
                print(
                    f"RUN {sample_id} {model} {args.prompt_mode} "
                    f"{representation} images={len(prepared.image_paths)}"
                )
                record = run_codex_call(
                    row,
                    prepared,
                    model=model,
                    experiment_dir=experiment_dir,
                    prompt_mode=args.prompt_mode,
                    reasoning_effort=args.reasoning_effort,
                    force=args.force,
                )
                calls += 1
                status = "OK" if record.returncode == 0 else "ERR"
                tok = token_metric(record)
                print(
                    f"{status} {sample_id} {model} {args.prompt_mode} {representation} "
                    f"gt={row.gt} pred={record.predicted_action} conf={record.confidence:.2f} "
                    f"tok={tok if tok is not None else 'n/a'} sec={record.wall_seconds:.1f}"
                )

    records = load_records(experiment_dir)
    summary = write_results(records, experiment_dir)
    print_summary(summary, experiment_dir)
    return 0


def print_summary(summary: dict[str, Any], experiment_dir: Path) -> None:
    print(f"REPORT {experiment_dir / 'REPORT.md'}")
    for key, row in summary["by_model_repr"].items():
        print(
            f"{key}: N={row['n']} acc={_pct(row['accuracy'])} "
            f"avg_tok={_num(row['avg_input_tokens'])} avg_sec={_num(row['avg_wall_seconds'])}"
        )
    for key, row in summary["paired"].items():
        print(
            f"{key}: token_reduction={_pct(row['token_reduction'])} "
            f"accuracy_drop={_num(row['accuracy_drop_pp'])}pp "
            f"speed_delta={_num(row['avg_wall_seconds_delta'])}s"
        )


if __name__ == "__main__":
    raise SystemExit(main())
