#!/usr/bin/env python3
"""Evidence-first RBA cascade experiment.

This experiment measures whether cheap video evidence can safely auto-label
simple clips before expensive VLM analysis. Ground truth is used only for
scoring and threshold calibration, never as an input feature.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np


REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "storage" / "dataset-203"
DEFAULT_EXPERIMENT_DIR = REPO_ROOT / "experiments" / "rba-evidence-first-cascade"
VIDEO_EXTS = {".mp4", ".mov"}
V40_AVG_INPUT_TOKENS = 3_650_000 / 185
HIGH_TOKEN_DIRECT_AVG = 120_000.0


@dataclass(frozen=True, slots=True)
class ClipRow:
    filename: str
    clip_id: str
    gt: str
    quality_tag: str = ""
    source: str = ""


@dataclass(frozen=True, slots=True)
class VideoEvidence:
    sample_id: str
    clip_id: str
    duration_sec: float
    width: int
    height: int
    fps: float
    frame_count: int
    brightness_mean: float
    brightness_std: float
    saturation_mean: float
    motion_mean: float
    motion_peak: float
    motion_std: float
    active_motion_ratio: float
    center_motion_ratio: float
    late_motion_ratio: float


@dataclass(frozen=True, slots=True)
class CascadeDecision:
    route: str
    predicted_action: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class ScoredDecision:
    sample_id: str
    gt: str
    baseline_action: str
    decision: CascadeDecision


@dataclass(frozen=True, slots=True)
class MovingRule:
    name: str
    motion_mean_min: float
    motion_peak_min: float
    active_motion_ratio_min: float
    brightness_std_min: float = 0.0
    saturation_max: float = 255.0


DEFAULT_RULE = MovingRule(
    name="conservative-v0",
    motion_mean_min=0.030,
    motion_peak_min=0.100,
    active_motion_ratio_min=0.750,
    brightness_std_min=10.0,
)
NO_AUTO_RULE = MovingRule(
    name="no-auto",
    motion_mean_min=2.0,
    motion_peak_min=2.0,
    active_motion_ratio_min=2.0,
)


def route_with_conservative_rules(evidence: VideoEvidence) -> CascadeDecision:
    return route_with_rule(evidence, DEFAULT_RULE)


def route_with_rule(evidence: VideoEvidence, rule: MovingRule) -> CascadeDecision:
    if rule.name == "no-auto":
        return CascadeDecision(route="fallback_vlm", predicted_action=None, reason="no_safe_auto_rule")
    strong_simple_motion = (
        evidence.motion_mean >= rule.motion_mean_min
        and evidence.motion_peak >= rule.motion_peak_min
        and evidence.active_motion_ratio >= rule.active_motion_ratio_min
        and evidence.brightness_std >= rule.brightness_std_min
        and evidence.saturation_mean <= rule.saturation_max
    )
    if strong_simple_motion:
        return CascadeDecision(
            route="auto_label",
            predicted_action="moving",
            reason=(
                f"strong_simple_motion:{rule.name}:"
                f"mean={evidence.motion_mean:.4f},"
                f"peak={evidence.motion_peak:.4f},"
                f"active={evidence.active_motion_ratio:.2f}"
            ),
        )
    return CascadeDecision(route="fallback_vlm", predicted_action=None, reason=f"ambiguous:{rule.name}")


def score_cascade(
    rows: Sequence[ScoredDecision],
    *,
    baseline_avg_tokens: float,
    fallback_avg_tokens: float,
) -> dict[str, Any]:
    if baseline_avg_tokens <= 0:
        raise ValueError("baseline_avg_tokens must be positive")
    if fallback_avg_tokens < 0:
        raise ValueError("fallback_avg_tokens cannot be negative")
    if not rows:
        return {
            "n": 0,
            "non_vlm_rate": 0.0,
            "fallback_rate": 0.0,
            "accuracy": 0.0,
            "baseline_accuracy": 0.0,
            "accuracy_drop_pp": 0.0,
            "false_auto_label_rate": 0.0,
            "token_reduction": 0.0,
        }

    auto_rows = [r for r in rows if r.decision.route == "auto_label"]
    fallback_rows = [r for r in rows if r.decision.route != "auto_label"]
    false_auto = [
        r
        for r in auto_rows
        if r.decision.predicted_action is None or r.decision.predicted_action != r.gt
    ]

    correct = 0
    baseline_correct = 0
    for row in rows:
        baseline_action = row.baseline_action
        chosen = row.decision.predicted_action if row.decision.route == "auto_label" else baseline_action
        if chosen == row.gt:
            correct += 1
        if baseline_action == row.gt:
            baseline_correct += 1

    fallback_rate = len(fallback_rows) / len(rows)
    expected_tokens = fallback_rate * fallback_avg_tokens
    baseline_accuracy = baseline_correct / len(rows)
    accuracy = correct / len(rows)
    return {
        "n": len(rows),
        "non_vlm_rate": len(auto_rows) / len(rows),
        "fallback_rate": fallback_rate,
        "accuracy": accuracy,
        "baseline_accuracy": baseline_accuracy,
        "accuracy_drop_pp": (baseline_accuracy - accuracy) * 100,
        "false_auto_label_rate": len(false_auto) / len(auto_rows) if auto_rows else 0.0,
        "false_auto_label_count": len(false_auto),
        "auto_label_count": len(auto_rows),
        "token_reduction": 1.0 - expected_tokens / baseline_avg_tokens,
        "expected_avg_input_tokens": expected_tokens,
    }


def load_manifest(path: Path) -> list[ClipRow]:
    rows: list[ClipRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if Path(row["filename"]).suffix.lower() not in VIDEO_EXTS:
                continue
            rows.append(
                ClipRow(
                    filename=row["filename"],
                    clip_id=row["clip_id"],
                    gt=row["gt"],
                    quality_tag=row.get("quality_tag", ""),
                    source=row.get("source", ""),
                )
            )
    return rows


def select_rows(rows: Sequence[ClipRow], sample_size: int, seed: int) -> list[ClipRow]:
    if sample_size <= 0 or sample_size >= len(rows):
        return sorted(rows, key=lambda r: (r.gt, r.clip_id))

    groups: dict[str, list[ClipRow]] = {}
    for row in rows:
        groups.setdefault(row.gt, []).append(row)

    selected: list[ClipRow] = []
    total = len(rows)
    for gt, group in sorted(groups.items()):
        quota = max(1, round(sample_size * len(group) / total))
        group_sorted = sorted(group, key=lambda r: r.clip_id)
        rng_seed = int(hashlib.sha1(f"{seed}:{gt}".encode()).hexdigest()[:8], 16)
        rng = np.random.default_rng(rng_seed)
        indices = sorted(rng.choice(len(group_sorted), size=min(quota, len(group_sorted)), replace=False))
        selected.extend(group_sorted[i] for i in indices)

    if len(selected) > sample_size:
        selected = sorted(selected, key=lambda r: hashlib.sha1(f"{seed}:{r.clip_id}".encode()).hexdigest())[
            :sample_size
        ]
    while len(selected) < sample_size:
        chosen = {r.clip_id for r in selected}
        remaining = [r for r in rows if r.clip_id not in chosen]
        if not remaining:
            break
        next_row = sorted(
            remaining,
            key=lambda r: hashlib.sha1(f"{seed}:fill:{r.clip_id}".encode()).hexdigest(),
        )[0]
        selected.append(next_row)
    return sorted(selected, key=lambda r: (r.gt, r.clip_id))


def sample_id_for(row: ClipRow, index: int) -> str:
    digest = hashlib.sha1(row.clip_id.encode("utf-8")).hexdigest()[:8]
    return f"sample-{index:03d}-{digest}"


def extract_video_evidence(video_path: Path, *, sample_id: str, clip_id: str, frame_samples: int = 16) -> VideoEvidence:
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise RuntimeError(f"cannot open video: {video_path}")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = frame_count / fps if fps > 0 and frame_count > 0 else 60.0

        if frame_count <= 0:
            indices = list(range(frame_samples))
        else:
            indices = np.linspace(0, max(frame_count - 1, 0), num=frame_samples, dtype=int).tolist()

        grays: list[np.ndarray] = []
        brightness: list[float] = []
        saturation: list[float] = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            grays.append(gray)
            brightness.append(float(np.mean(gray)))
            saturation.append(float(np.mean(hsv[:, :, 1])))

        if not grays:
            raise RuntimeError(f"no readable frames: {video_path}")

        motion_values: list[float] = []
        center_values: list[float] = []
        for prev, curr in zip(grays, grays[1:]):
            diff = cv2.absdiff(prev, curr)
            motion_mask = diff > 18
            motion = float(np.mean(motion_mask))
            motion_values.append(motion)

            h, w = motion_mask.shape
            y1, y2 = h // 4, h - h // 4
            x1, x2 = w // 4, w - w // 4
            center = float(np.mean(motion_mask[y1:y2, x1:x2]))
            center_values.append(center / motion if motion > 0 else 0.0)

        if motion_values:
            late_start = max(0, (len(motion_values) * 2) // 3)
            late_mean = float(np.mean(motion_values[late_start:]))
            motion_mean = float(np.mean(motion_values))
            late_ratio = late_mean / motion_mean if motion_mean > 0 else 0.0
        else:
            motion_mean = 0.0
            late_ratio = 0.0

        return VideoEvidence(
            sample_id=sample_id,
            clip_id=clip_id,
            duration_sec=duration,
            width=width,
            height=height,
            fps=fps,
            frame_count=frame_count,
            brightness_mean=float(np.mean(brightness)),
            brightness_std=float(np.std(brightness)),
            saturation_mean=float(np.mean(saturation)),
            motion_mean=motion_mean,
            motion_peak=float(max(motion_values) if motion_values else 0.0),
            motion_std=float(np.std(motion_values) if motion_values else 0.0),
            active_motion_ratio=float(np.mean([m > 0.015 for m in motion_values])) if motion_values else 0.0,
            center_motion_ratio=float(np.mean(center_values)) if center_values else 0.0,
            late_motion_ratio=late_ratio,
        )
    finally:
        cap.release()


def calibrate_moving_rule(
    evidences: Sequence[VideoEvidence],
    labels: dict[str, str],
    *,
    max_false_auto_rate: float = 0.05,
) -> MovingRule:
    candidates: list[MovingRule] = []
    for motion_mean in (0.006, 0.010, 0.014, 0.018, 0.022, 0.026, 0.030):
        for motion_peak in (0.030, 0.050, 0.070, 0.090, 0.120):
            for active in (0.20, 0.35, 0.50, 0.65, 0.80):
                candidates.append(
                    MovingRule(
                        name=f"calibrated-m{motion_mean:.3f}-p{motion_peak:.3f}-a{active:.2f}",
                        motion_mean_min=motion_mean,
                        motion_peak_min=motion_peak,
                        active_motion_ratio_min=active,
                        brightness_std_min=0.0,
                    )
                )

    best = NO_AUTO_RULE
    best_rate = -1.0
    best_false = 1.0
    for rule in candidates:
        decisions = [route_with_rule(e, rule) for e in evidences]
        auto = [(e, d) for e, d in zip(evidences, decisions) if d.route == "auto_label"]
        if not auto:
            continue
        false = sum(1 for e, d in auto if d.predicted_action != labels[e.sample_id])
        false_rate = false / len(auto)
        auto_rate = len(auto) / len(evidences)
        if false_rate <= max_false_auto_rate and (auto_rate > best_rate or (auto_rate == best_rate and false_rate < best_false)):
            best = rule
            best_rate = auto_rate
            best_false = false_rate
    return best


def split_for_calibration(evidences: Sequence[VideoEvidence], *, seed: int) -> tuple[list[VideoEvidence], list[VideoEvidence]]:
    ordered = sorted(evidences, key=lambda e: hashlib.sha1(f"{seed}:{e.sample_id}".encode()).hexdigest())
    cut = max(1, int(len(ordered) * 0.7))
    return ordered[:cut], ordered[cut:]


def build_scored_decisions(
    evidences: Sequence[VideoEvidence],
    rows_by_sample: dict[str, ClipRow],
    *,
    rule: MovingRule,
) -> list[ScoredDecision]:
    scored: list[ScoredDecision] = []
    for evidence in evidences:
        row = rows_by_sample[evidence.sample_id]
        decision = route_with_rule(evidence, rule)
        scored.append(
            ScoredDecision(
                sample_id=evidence.sample_id,
                gt=row.gt,
                baseline_action=row.gt,
                decision=decision,
            )
        )
    return scored


def write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_features(path: Path) -> list[VideoEvidence]:
    out: list[VideoEvidence] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(VideoEvidence(**json.loads(line)))
    return out


def write_report(path: Path, results: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    chosen = results["chosen"]
    pre = results["preprocessor_only"]
    lines = [
        "# RBA Evidence-First Cascade Report",
        "",
        "## Decision",
        "",
        f"Decision: `{results['decision']}`",
        "",
        "This is a separate strategy from SegmentVLM and contact-sheet token reduction. "
        "It tests whether non-VLM video evidence can safely reduce VLM calls before semantic judgment.",
        "",
        "## Chosen Rule",
        "",
        f"- rule: `{chosen['rule']['name']}`",
        f"- split: `{chosen['split']}`",
        f"- N: {chosen['summary']['n']}",
        f"- non-VLM rate: {_pct(chosen['summary']['non_vlm_rate'])}",
        f"- fallback rate: {_pct(chosen['summary']['fallback_rate'])}",
        f"- false auto-label rate: {_pct(chosen['summary']['false_auto_label_rate'])}",
        f"- accuracy drop: {chosen['summary']['accuracy_drop_pp']:.2f}pp",
        f"- token reduction vs 120k direct: {_pct(chosen['summary_high_token']['token_reduction'])}",
        f"- token reduction vs v40 frames: {_pct(chosen['summary_v40']['token_reduction'])}",
        "",
        "## Preprocessor-First Baseline",
        "",
        "This measures the part of the strategy that is already safe: Python/OpenCV handles video "
        "decoding and frame selection, then VLM sees adaptive frames instead of a high-token direct video input.",
        "",
        f"- token reduction vs 120k direct: {_pct(pre['summary_high_token']['token_reduction'])}",
        f"- expected avg input tokens: {pre['summary_high_token']['expected_avg_input_tokens']:.0f}",
        f"- accuracy drop vs fallback baseline: {pre['summary_high_token']['accuracy_drop_pp']:.2f}pp",
        "",
        "## All Runs",
        "",
        "| split | rule | N | non-VLM | false auto | accuracy drop | vs 120k reduction | vs v40 reduction |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run in results["runs"]:
        s = run["summary"]
        lines.append(
            f"| {run['split']} | `{run['rule']['name']}` | {s['n']} | "
            f"{_pct(s['non_vlm_rate'])} | {_pct(s['false_auto_label_rate'])} | "
            f"{s['accuracy_drop_pp']:.2f}pp | {_pct(run['summary_high_token']['token_reduction'])} | "
            f"{_pct(run['summary_v40']['token_reduction'])} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            results["interpretation"],
            "",
            "## Class Distribution",
            "",
            "```json",
            json.dumps(results["class_distribution"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    experiment_dir = Path(args.experiment_dir)
    manifest_rows = load_manifest(Path(args.manifest))
    selected = select_rows(manifest_rows, args.sample_size, args.seed)
    rows_by_sample: dict[str, ClipRow] = {}
    feature_path = experiment_dir / "features.jsonl"

    if args.summarize_only:
        evidences = load_features(feature_path)
    else:
        evidences = []
        for index, row in enumerate(selected, start=1):
            sample_id = sample_id_for(row, index)
            rows_by_sample[sample_id] = row
            video_path = DATASET_DIR / row.filename
            evidence = extract_video_evidence(
                video_path,
                sample_id=sample_id,
                clip_id=row.clip_id,
                frame_samples=args.frame_samples,
            )
            evidences.append(evidence)
        write_jsonl(feature_path, [asdict(e) for e in evidences])

    if not rows_by_sample:
        for index, row in enumerate(selected, start=1):
            rows_by_sample[sample_id_for(row, index)] = row

    labels = {sid: row.gt for sid, row in rows_by_sample.items()}
    train, test = split_for_calibration(evidences, seed=args.seed)
    calibrated_rule = calibrate_moving_rule(train, labels, max_false_auto_rate=args.max_false_auto_rate)
    rules_by_name = {DEFAULT_RULE.name: DEFAULT_RULE, calibrated_rule.name: calibrated_rule}
    rules = list(rules_by_name.values())

    runs: list[dict[str, Any]] = []
    decisions_for_file: list[dict[str, Any]] = []
    all_fallback = [
        ScoredDecision(
            sample_id=e.sample_id,
            gt=rows_by_sample[e.sample_id].gt,
            baseline_action=rows_by_sample[e.sample_id].gt,
            decision=CascadeDecision("fallback_vlm", None, "preprocessor_only"),
        )
        for e in evidences
    ]
    preprocessor_only = {
        "summary_v40": score_cascade(
            all_fallback,
            baseline_avg_tokens=V40_AVG_INPUT_TOKENS,
            fallback_avg_tokens=V40_AVG_INPUT_TOKENS,
        ),
        "summary_high_token": score_cascade(
            all_fallback,
            baseline_avg_tokens=HIGH_TOKEN_DIRECT_AVG,
            fallback_avg_tokens=V40_AVG_INPUT_TOKENS,
        ),
    }
    for split_name, split_rows in (("train", train), ("holdout", test), ("all", evidences)):
        for rule in rules:
            scored = build_scored_decisions(split_rows, rows_by_sample, rule=rule)
            summary_v40 = score_cascade(
                scored,
                baseline_avg_tokens=V40_AVG_INPUT_TOKENS,
                fallback_avg_tokens=V40_AVG_INPUT_TOKENS,
            )
            summary_high = score_cascade(
                scored,
                baseline_avg_tokens=HIGH_TOKEN_DIRECT_AVG,
                fallback_avg_tokens=V40_AVG_INPUT_TOKENS,
            )
            run = {
                "split": split_name,
                "rule": asdict(rule),
                "summary": summary_v40,
                "summary_v40": summary_v40,
                "summary_high_token": summary_high,
            }
            runs.append(run)
            for row in scored:
                decisions_for_file.append(
                    {
                        "split": split_name,
                        "rule": rule.name,
                        "sample_id": row.sample_id,
                        "gt": row.gt,
                        "decision": asdict(row.decision),
                    }
                )

    chosen = _choose_run(runs)
    decision, interpretation = _decision_text(chosen)
    results = {
        "strategy": "Evidence-First Cascade",
        "decision": decision,
        "chosen": chosen,
        "preprocessor_only": preprocessor_only,
        "runs": runs,
        "class_distribution": dict(Counter(row.gt for row in rows_by_sample.values())),
        "interpretation": interpretation,
    }

    experiment_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(experiment_dir / "decisions.jsonl", decisions_for_file)
    (experiment_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_report(experiment_dir / "REPORT.md", results)
    return results


def _choose_run(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    holdout = [r for r in runs if r["split"] == "holdout"]
    candidates = holdout or list(runs)
    return sorted(
        candidates,
        key=lambda r: (
            r["summary"]["accuracy_drop_pp"] > 2.0,
            r["summary"]["false_auto_label_rate"] > 0.05,
            -r["summary"]["non_vlm_rate"],
            r["summary"]["false_auto_label_rate"],
        ),
    )[0]


def _decision_text(chosen: dict[str, Any]) -> tuple[str, str]:
    s = chosen["summary"]
    high = chosen["summary_high_token"]
    achieved = (
        s["non_vlm_rate"] >= 0.20
        and s["false_auto_label_rate"] <= 0.05
        and s["accuracy_drop_pp"] <= 2.0
        and high["token_reduction"] >= 0.80
    )
    if achieved:
        return (
            "adopt_for_high_token_baseline",
            "The calibrated non-VLM moving router meets the high-token baseline target: "
            "at least 20% non-VLM handling, false auto-label rate at or below 5%, "
            "accuracy drop within 2pp, and at least 80% token reduction versus 120k/clip direct calls. "
            "It does not replace VLM judgment for high-value behaviors; it safely removes obvious moving clips first.",
        )
    high_reduction = 1.0 - V40_AVG_INPUT_TOKENS / HIGH_TOKEN_DIRECT_AVG
    if high_reduction >= 0.80:
        return (
            "adopt_preprocessor_first_hold_auto_label",
            "The broader goal is partially achieved by moving video decoding, frame selection, "
            "and evidence extraction outside the VLM: the v40 adaptive-frame fallback costs "
            f"{V40_AVG_INPUT_TOKENS:.0f} input tokens/clip versus a 120k direct-video baseline "
            f"({high_reduction * 100:.1f}% reduction) while preserving the v40 accuracy baseline. "
            "However, OpenCV-only auto-labeling is not safe enough yet. Keep auto-label routing on hold "
            "until detector evidence adds gecko presence and object/ROI cues.",
        )
    return (
        "hold_needs_better_evidence",
        "The current OpenCV-only evidence is not yet enough to meet the full target. "
        "Keep the strategy as a separate research track, but add detector evidence "
        "(gecko presence, hand/tool/prey/bowl ROIs) before production adoption.",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DATASET_DIR / "manifest.csv"))
    parser.add_argument("--experiment-dir", default=str(DEFAULT_EXPERIMENT_DIR))
    parser.add_argument("--sample-size", type=int, default=0, help="0 means full manifest")
    parser.add_argument("--seed", type=int, default=203)
    parser.add_argument("--frame-samples", type=int, default=16)
    parser.add_argument("--max-false-auto-rate", type=float, default=0.05)
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--force", action="store_true", help="accepted for symmetry; feature extraction always rewrites")
    return parser.parse_args()


def main() -> None:
    results = run_experiment(parse_args())
    chosen = results["chosen"]
    print(
        json.dumps(
            {
                "decision": results["decision"],
                "split": chosen["split"],
                "rule": chosen["rule"]["name"],
                "non_vlm_rate": chosen["summary"]["non_vlm_rate"],
                "false_auto_label_rate": chosen["summary"]["false_auto_label_rate"],
                "accuracy_drop_pp": chosen["summary"]["accuracy_drop_pp"],
                "token_reduction_high_token": chosen["summary_high_token"]["token_reduction"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
