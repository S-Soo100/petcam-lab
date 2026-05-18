"""ClaudeFrameAnalyzer batch runner for SegmentVLM artifacts.

SegmentVLM 샘플의 GT/baseline/source filename 을 Claude 에게 숨긴 뒤,
contact sheet + key frame + event metadata 만으로 행동을 판정하게 한다.

사용 예:
    uv run python scripts/claude_segmentvlm_batch.py --limit 3
    uv run python scripts/claude_segmentvlm_batch.py --all
    uv run python scripts/claude_segmentvlm_batch.py --all --force
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
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


def _json_schema() -> str:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "analyzer": {"type": "string"},
            "clip_id": {"type": "string"},
            "predicted_action": {"type": "string", "enum": ALLOWED_ACTIONS},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "needs_human_review": {"type": "boolean"},
            "event_findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "event_id": {"type": "string"},
                        "visible_action": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["event_id", "visible_action", "evidence"],
                },
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
            },
            "uncertainty_notes": {"type": "string"},
        },
        "required": [
            "analyzer",
            "clip_id",
            "predicted_action",
            "confidence",
            "needs_human_review",
            "event_findings",
            "evidence",
            "uncertainty_notes",
        ],
    }
    return json.dumps(schema, ensure_ascii=False)


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{"):
        wrapper = json.loads(stripped)
        if wrapper.get("type") == "result" and "result" in wrapper:
            result = _extract_json(str(wrapper["result"]))
            result.setdefault("analyzer", ",".join(wrapper.get("modelUsage", {}).keys()) or "claude")
            result["_claude_total_cost_usd"] = wrapper.get("total_cost_usd")
            return result
        return wrapper

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    first = stripped.find("{")
    last = stripped.rfind("}")
    if first >= 0 and last > first:
        return json.loads(stripped[first : last + 1])

    action = None
    label_match = re.search(
        r"(?:Prediction|Classification)\s*:\s*`?([a-z_]+)`?",
        stripped,
        re.IGNORECASE,
    )
    if label_match and label_match.group(1) in ALLOWED_ACTIONS:
        action = label_match.group(1)
    if action is None:
        first_line = stripped.splitlines()[0] if stripped.splitlines() else stripped
        for candidate in ALLOWED_ACTIONS:
            if re.search(rf"`{re.escape(candidate)}`|\b{re.escape(candidate)}\b", first_line, re.IGNORECASE):
                action = candidate
                break
    if action is None:
        action = "unknown"

    confidence_match = re.search(r"confidence\s*[:=]?\s*([01](?:\.\d+)?)", stripped, re.IGNORECASE)
    confidence = float(confidence_match.group(1)) if confidence_match else 0.5
    review = bool(re.search(r"human review|review flagged|needs review|ambiguous|uncertain", stripped, re.IGNORECASE))
    evidence = [
        line.strip(" -")
        for line in stripped.splitlines()
        if line.strip() and not line.strip().startswith("**")
    ][:8]
    return {
        "analyzer": "claude",
        "clip_id": "",
        "predicted_action": action,
        "confidence": confidence,
        "needs_human_review": review,
        "event_findings": [],
        "evidence": evidence,
        "uncertainty_notes": stripped[:1000],
    }


def _prompt(blind_path: Path, blind: dict[str, Any]) -> str:
    image_paths: list[str] = []
    for event in blind.get("events", []):
        if event.get("contact_sheet"):
            image_paths.append(str(event["contact_sheet"]))
        image_paths.extend(str(path) for path in event.get("key_frames", [])[:3])

    return f"""
You are ClaudeFrameAnalyzer for SegmentVLM leopard gecko behavior analysis.

Read only this blind input JSON and the image paths listed inside it:
- {blind_path}

Do not read experiment specs, GT labels, baseline predictions, README tables, source video filenames, or any other project files.
This is a blind evaluation. If you use hidden labels or filenames, the experiment becomes invalid.

Visual inputs to inspect:
{chr(10).join(f"- {path}" for path in image_paths)}

Task:
- Inspect the event contact sheets/key frames.
- Classify the clip-level behavior using exactly one allowed action from the blind JSON.
- Prefer visible evidence over assumptions.
- Use needs_human_review=true when evidence is weak, ambiguous, or only partially visible.
- Return JSON only matching the required schema.
""".strip()


def run_claude(sample_dir: Path, *, model: str, max_budget_usd: float) -> dict[str, Any]:
    sample_path = sample_dir / "segmentvlm_sample.json"
    blind = build_blind_input(sample_path)
    blind_path = sample_dir / "claude-blind-input.json"
    _write_json(blind_path, blind)

    cmd = [
        "claude",
        "-p",
        _prompt(blind_path, blind),
        "--model",
        model,
        "--max-budget-usd",
        str(max_budget_usd),
        "--tools",
        "Read",
        "--permission-mode",
        "dontAsk",
        "--no-session-persistence",
        "--output-format",
        "json",
        "--json-schema",
        _json_schema(),
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    (sample_dir / "claude-frame-analysis.stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (sample_dir / "claude-frame-analysis.stderr.txt").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())

    result = _extract_json(proc.stdout)
    result["clip_id"] = result.get("clip_id") or blind.get("clip_id")
    result["blind_input"] = str(blind_path.resolve())
    result["model_requested"] = model
    _write_json(sample_dir / "claude-frame-analysis.json", result)
    (sample_dir / "claude-frame-analysis.raw.txt").write_text(proc.stdout, encoding="utf-8")
    return result


def compare_result(sample_dir: Path) -> dict[str, Any]:
    sample = _load_json(sample_dir / "segmentvlm_sample.json")
    result = _load_json(sample_dir / "claude-frame-analysis.json")
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
        "claude_action": pred,
        "confidence": result.get("confidence"),
        "needs_human_review": result.get("needs_human_review"),
        "claude_total_cost_usd": result.get("_claude_total_cost_usd"),
        "outcome": outcome,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="run every available sample")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--max-budget-usd", type=float, default=0.35)
    args = parser.parse_args()

    dirs = sample_dirs()
    if not args.all:
        dirs = dirs[: args.limit]

    summaries: list[dict[str, Any]] = []
    for sample_dir in dirs:
        out_path = sample_dir / "claude-frame-analysis.json"
        if out_path.exists() and not args.force:
            print(f"SKIP {sample_dir.name} existing")
        else:
            print(f"RUN {sample_dir.name}")
            result = run_claude(sample_dir, model=args.model, max_budget_usd=args.max_budget_usd)
            print(f"OK {sample_dir.name} -> {result.get('predicted_action')} {result.get('confidence')}")
        summaries.append(compare_result(sample_dir))

    summary_path = SAMPLE_ROOT / "claude-batch-summary.json"
    _write_json(summary_path, {"count": len(summaries), "results": summaries})
    print(f"SUMMARY {summary_path}")
    for row in summaries:
        print(
            f"{row['sample']} gt={row['gt_action']} baseline={row['baseline_action']} "
            f"claude={row['claude_action']} outcome={row['outcome']}"
        )


if __name__ == "__main__":
    main()
