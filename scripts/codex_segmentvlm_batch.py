"""CodexFrameAnalyzer batch runner for SegmentVLM artifacts.

ClaudeFrameAnalyzer 와 같은 blind protocol 로 Codex CLI 를 호출한다.
GT/baseline/source filename 은 숨기고, contact sheet 이미지는 `codex exec --image`
로 첨부한다.

사용 예:
    uv run python scripts/codex_segmentvlm_batch.py --limit 3
    uv run python scripts/codex_segmentvlm_batch.py --all
    uv run python scripts/codex_segmentvlm_batch.py --all --force --model gpt-5.5
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_ROOT = REPO_ROOT / "experiments" / "segment-vlm"
ALLOWED_ACTIONS = [
    "moving",
    "drinking",
    "eating_paste",
    "eating_prey",
    "defecating",
    "shedding",
    "hiding",
    "basking",
    "unknown",
]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sample_dirs() -> list[Path]:
    return sorted(p.parent for p in SAMPLE_ROOT.glob("sample-*/segmentvlm_sample.json"))


def build_blind_input(sample_path: Path) -> dict[str, Any]:
    sample = _load_json(sample_path)
    events: list[dict[str, Any]] = []
    for event in sample.get("events", []):
        events.append(
            {
                "event_id": event.get("event_id"),
                "start_sec": event.get("start_sec"),
                "end_sec": event.get("end_sec"),
                "duration_sec": event.get("duration_sec"),
                "peak_changed_ratio": event.get("peak_changed_ratio"),
                "mean_changed_ratio": event.get("mean_changed_ratio"),
                "motion_centroid": event.get("motion_centroid"),
                "contact_sheet": event.get("contact_sheet"),
                "key_frames": event.get("key_frames", []),
            }
        )

    return {
        "clip_id": sample.get("clip_id"),
        "video": sample.get("video", {}),
        "segmentation": sample.get("segmentation", {}),
        "events": events,
        "allowed_actions": ALLOWED_ACTIONS,
        "blind_protocol": {
            "hidden_from_analyzer": [
                "gt_action",
                "baseline_action",
                "baseline_error",
                "source_video",
                "notes",
            ],
            "instruction": "Use only the provided event metadata, contact sheets, and key frames.",
        },
    }


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    first = stripped.find("{")
    last = stripped.rfind("}")
    if first >= 0 and last > first:
        return json.loads(stripped[first : last + 1])

    action = None
    for candidate in ALLOWED_ACTIONS:
        if re.search(rf"\b{re.escape(candidate)}\b", stripped, re.IGNORECASE):
            action = candidate
            break
    if action is None:
        action = "unknown"
    confidence_match = re.search(r"confidence\s*[:=]?\s*([01](?:\.\d+)?)", stripped, re.IGNORECASE)
    confidence = float(confidence_match.group(1)) if confidence_match else 0.5
    review = bool(re.search(r"human review|needs review|ambiguous|uncertain|blurry|obscured", stripped, re.IGNORECASE))
    return {
        "analyzer": "CodexFrameAnalyzer",
        "clip_id": "",
        "predicted_action": action,
        "confidence": confidence,
        "needs_human_review": review,
        "event_findings": [],
        "evidence": [line.strip(" -") for line in stripped.splitlines() if line.strip()][:8],
        "uncertainty_notes": stripped[:1000],
    }


def _image_paths(blind: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for event in blind.get("events", []):
        contact = event.get("contact_sheet")
        if contact and Path(contact).exists():
            paths.append(str(contact))
        for frame_path in event.get("key_frames", [])[:2]:
            if Path(frame_path).exists():
                paths.append(str(frame_path))
    return paths[:8]


def _prompt(blind: dict[str, Any]) -> str:
    blind_for_prompt = {
        "clip_id": blind.get("clip_id"),
        "video": blind.get("video"),
        "segmentation": blind.get("segmentation"),
        "events": [
            {
                "event_id": event.get("event_id"),
                "start_sec": event.get("start_sec"),
                "end_sec": event.get("end_sec"),
                "duration_sec": event.get("duration_sec"),
                "peak_changed_ratio": event.get("peak_changed_ratio"),
                "mean_changed_ratio": event.get("mean_changed_ratio"),
                "motion_centroid": event.get("motion_centroid"),
            }
            for event in blind.get("events", [])
        ],
        "allowed_actions": ALLOWED_ACTIONS,
    }
    return f"""
You are CodexFrameAnalyzer for SegmentVLM leopard gecko behavior analysis.

This is a blind evaluation. Use only:
1. the attached contact sheet/key frame images
2. the blind metadata JSON below

Do not read project files, GT labels, baseline predictions, README tables, source video filenames, notes, or experiment summaries.
If visual evidence is weak, set needs_human_review=true.

Allowed actions: {", ".join(ALLOWED_ACTIONS)}

Blind metadata JSON:
{json.dumps(blind_for_prompt, ensure_ascii=False, indent=2)}

Return compact JSON only with keys:
analyzer, clip_id, predicted_action, confidence, needs_human_review, event_findings, evidence, uncertainty_notes.
""".strip()


def run_codex(sample_dir: Path, *, model: str) -> dict[str, Any]:
    sample_path = sample_dir / "segmentvlm_sample.json"
    blind = build_blind_input(sample_path)
    blind_path = sample_dir / "codex-blind-input.json"
    _write_json(blind_path, blind)

    with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False, encoding="utf-8") as tmp:
        out_path = Path(tmp.name)

    cmd = [
        "codex",
        "exec",
        "-s",
        "read-only",
        "-C",
        str(REPO_ROOT),
        "--ephemeral",
        "--ignore-rules",
        "--model",
        model,
        "--output-last-message",
        str(out_path),
    ]
    for path in _image_paths(blind):
        cmd.extend(["--image", path])
    cmd.extend(["--", _prompt(blind)])

    proc = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    stdout_path = sample_dir / "codex-cli-frame-analysis.stdout.txt"
    stderr_path = sample_dir / "codex-cli-frame-analysis.stderr.txt"
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())

    output = out_path.read_text(encoding="utf-8")
    out_path.unlink(missing_ok=True)
    result = _extract_json(output)
    result["clip_id"] = result.get("clip_id") or blind.get("clip_id")
    result["blind_input"] = str(blind_path.resolve())
    result["model_requested"] = model
    _write_json(sample_dir / "codex-cli-frame-analysis.json", result)
    return result


def compare_result(sample_dir: Path) -> dict[str, Any]:
    sample = _load_json(sample_dir / "segmentvlm_sample.json")
    result = _load_json(sample_dir / "codex-cli-frame-analysis.json")
    gt = sample.get("gt_action")
    baseline = sample.get("baseline_action")
    pred = result.get("predicted_action")
    if pred == gt:
        outcome = "recovered" if baseline != gt else "correct"
    elif result.get("needs_human_review"):
        outcome = "still_wrong_but_review"
    else:
        outcome = "still_wrong"
    return {
        "clip_id": sample.get("clip_id"),
        "sample": sample_dir.name,
        "gt_action": gt,
        "baseline_action": baseline,
        "codex_action": pred,
        "confidence": result.get("confidence"),
        "needs_human_review": result.get("needs_human_review"),
        "outcome": outcome,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="run every available sample")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--model", default="gpt-5.5")
    args = parser.parse_args()

    dirs = sample_dirs()
    if not args.all:
        dirs = dirs[: args.limit]

    summaries: list[dict[str, Any]] = []
    for sample_dir in dirs:
        out_path = sample_dir / "codex-cli-frame-analysis.json"
        if out_path.exists() and not args.force:
            print(f"SKIP {sample_dir.name} existing")
        else:
            print(f"RUN {sample_dir.name}")
            result = run_codex(sample_dir, model=args.model)
            print(f"OK {sample_dir.name} -> {result.get('predicted_action')} {result.get('confidence')}")
        summaries.append(compare_result(sample_dir))

    summary_path = SAMPLE_ROOT / "codex-cli-batch-summary.json"
    _write_json(summary_path, {"count": len(summaries), "results": summaries})
    print(f"SUMMARY {summary_path}")
    for row in summaries:
        print(
            f"{row['sample']} gt={row['gt_action']} baseline={row['baseline_action']} "
            f"codex={row['codex_action']} outcome={row['outcome']}"
        )


if __name__ == "__main__":
    main()
