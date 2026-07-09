#!/usr/bin/env python3
"""Detector-independent local router v0 experiment.

The router never sees images, filenames, or GT labels. It only receives cheap
video evidence and emits a cloud VLM priority route.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.rba_evidence_first_cascade import (  # noqa: E402
    DATASET_DIR,
    ClipRow,
    VideoEvidence,
    extract_video_evidence,
    load_features,
    load_manifest,
    sample_id_for,
    select_rows,
    write_jsonl,
)


DEFAULT_EXPERIMENT_DIR = REPO_ROOT / "experiments" / "local-router-v0"
P0_CLASSES = {"drinking", "eating_paste", "eating_prey", "hand_feeding", "shedding"}
ALLOWED_ROUTES = {"cloud_now", "cloud_later", "activity_only", "review_candidate"}


@dataclass(frozen=True, slots=True)
class RouterDecision:
    sample_id: str
    clip_id: str
    route: str
    priority: float
    risk: str
    reason: str
    router: str = "l0-deterministic-v0"
    latency_ms: float = 0.0


def evidence_payload(evidence: VideoEvidence) -> dict[str, Any]:
    """Return router-visible fields only. No GT, filename, image, or detector data."""
    return {
        "sample_id": evidence.sample_id,
        "clip_id": evidence.clip_id,
        "duration_sec": round(evidence.duration_sec, 3),
        "width": evidence.width,
        "height": evidence.height,
        "fps": round(evidence.fps, 3),
        "frame_count": evidence.frame_count,
        "brightness_mean": round(evidence.brightness_mean, 4),
        "brightness_std": round(evidence.brightness_std, 4),
        "saturation_mean": round(evidence.saturation_mean, 4),
        "motion_mean": round(evidence.motion_mean, 6),
        "motion_peak": round(evidence.motion_peak, 6),
        "motion_std": round(evidence.motion_std, 6),
        "active_motion_ratio": round(evidence.active_motion_ratio, 6),
        "center_motion_ratio": round(evidence.center_motion_ratio, 6),
        "late_motion_ratio": round(evidence.late_motion_ratio, 6),
    }


def route_l0(evidence: VideoEvidence) -> RouterDecision:
    start = time.perf_counter()

    poor_visibility = evidence.brightness_mean < 18.0 or evidence.brightness_std < 2.0
    very_static = evidence.motion_peak < 0.018 and evidence.active_motion_ratio < 0.12
    low_activity = evidence.motion_mean < 0.010 and evidence.active_motion_ratio < 0.25
    strong_activity = evidence.motion_mean >= 0.026 or evidence.motion_peak >= 0.120
    bursty_or_late = evidence.motion_std >= 0.035 or evidence.late_motion_ratio >= 1.8

    if poor_visibility:
        route = "review_candidate"
        priority = 0.74
        risk = "medium"
        reason = "poor_visibility_requires_review"
    elif strong_activity or bursty_or_late:
        route = "cloud_now"
        priority = 0.86
        risk = "high"
        reason = "high_or_bursty_motion_could_hide_p0_behavior"
    elif very_static:
        route = "activity_only"
        priority = 0.18
        risk = "low"
        reason = "very_static_low_motion_clip"
    elif low_activity:
        route = "cloud_later"
        priority = 0.42
        risk = "medium"
        reason = "low_activity_but_not_safe_to_drop"
    else:
        route = "cloud_later"
        priority = 0.58
        risk = "medium"
        reason = "moderate_motion_batchable"

    latency_ms = (time.perf_counter() - start) * 1000
    return RouterDecision(
        sample_id=evidence.sample_id,
        clip_id=evidence.clip_id,
        route=route,
        priority=priority,
        risk=risk,
        reason=reason,
        latency_ms=latency_ms,
    )


def route_l0_v1(evidence: VideoEvidence) -> RouterDecision:
    start = time.perf_counter()

    poor_visibility = evidence.brightness_mean < 18.0 or evidence.brightness_std < 2.0
    extreme_static_visible = (
        evidence.motion_mean < 0.003
        and evidence.motion_peak < 0.010
        and evidence.active_motion_ratio < 0.05
        and evidence.brightness_mean >= 35.0
        and evidence.brightness_std >= 4.0
    )
    high_or_bursty = (
        evidence.motion_mean >= 0.030
        or evidence.motion_peak >= 0.140
        or evidence.motion_std >= 0.050
        or evidence.late_motion_ratio >= 2.2
    )
    low_batchable = evidence.motion_mean < 0.014 and evidence.active_motion_ratio < 0.35

    if poor_visibility:
        route = "review_candidate"
        priority = 0.74
        risk = "medium"
        reason = "poor_visibility_requires_review"
    elif extreme_static_visible:
        route = "activity_only"
        priority = 0.16
        risk = "low"
        reason = "extreme_static_visible_clip"
    elif high_or_bursty:
        route = "cloud_now"
        priority = 0.88
        risk = "high"
        reason = "high_or_bursty_motion_could_hide_p0_behavior"
    elif low_batchable:
        route = "cloud_later"
        priority = 0.38
        risk = "medium"
        reason = "low_motion_batchable_not_droppable"
    else:
        route = "cloud_later"
        priority = 0.56
        risk = "medium"
        reason = "moderate_motion_batchable"

    return RouterDecision(
        sample_id=evidence.sample_id,
        clip_id=evidence.clip_id,
        route=route,
        priority=priority,
        risk=risk,
        reason=reason,
        router="l0-deterministic-v1",
        latency_ms=(time.perf_counter() - start) * 1000,
    )


def prompt_for_local_llm(evidence: VideoEvidence, *, prompt_mode: str = "v0") -> str:
    payload = evidence_payload(evidence)
    base = (
        "You are RBA Router v1. Decide cloud VLM priority from evidence JSON only.\n"
        "Do not infer a behavior label. Router input contains no ground-truth label, no filename label, no image, and no detector bbox.\n"
        "Allowed routes: cloud_now, cloud_later, activity_only, review_candidate.\n"
        "Forbidden routes: skip, auto_moving, auto_p0.\n"
        "Prefer cloud_later over cloud_now when evidence is not urgent but still should be analyzed eventually.\n"
        "Use activity_only only for extremely static, visible clips with very low motion.\n"
    )
    examples = ""
    if prompt_mode == "v1":
        examples = (
            "Examples:\n"
            '{"motion_mean":0.001,"motion_peak":0.004,"active_motion_ratio":0.01,"brightness_mean":65} -> '
            '{"route":"activity_only","priority":0.15,"risk":"low","reason":"extreme static visible clip"}\n'
            '{"motion_mean":0.012,"motion_peak":0.040,"active_motion_ratio":0.22,"brightness_mean":55} -> '
            '{"route":"cloud_later","priority":0.40,"risk":"medium","reason":"low activity but not safe to drop"}\n'
            '{"motion_mean":0.035,"motion_peak":0.160,"active_motion_ratio":0.80,"brightness_mean":70} -> '
            '{"route":"cloud_now","priority":0.88,"risk":"high","reason":"high motion may hide P0"}\n'
            '{"brightness_mean":12,"brightness_std":1.0,"motion_peak":0.020} -> '
            '{"route":"review_candidate","priority":0.75,"risk":"medium","reason":"poor visibility"}\n'
        )
    return (
        base
        + examples
        + 'Return strict JSON: {"route": "...", "priority": 0.0, "risk": "low|medium|high", "reason": "..."}.\n'
        f"Evidence JSON:\n{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    )


def route_with_ollama(
    evidence: VideoEvidence,
    *,
    model: str,
    timeout_sec: int,
    prompt_mode: str,
) -> RouterDecision:
    start = time.perf_counter()
    prompt = prompt_for_local_llm(evidence, prompt_mode=prompt_mode)
    proc = subprocess.run(
        ["ollama", "run", model, prompt],
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    if proc.returncode != 0:
        return RouterDecision(
            sample_id=evidence.sample_id,
            clip_id=evidence.clip_id,
            route="review_candidate",
            priority=0.80,
            risk="high",
            reason=f"ollama_error:{proc.stderr.strip()[:180]}",
            router=f"ollama:{model}",
            latency_ms=latency_ms,
        )

    try:
        text = proc.stdout.strip()
        first = text.find("{")
        last = text.rfind("}")
        parsed = json.loads(text[first : last + 1] if first >= 0 and last >= first else text)
        route = str(parsed.get("route", "review_candidate"))
        if route not in ALLOWED_ROUTES:
            route = "review_candidate"
        priority = float(parsed.get("priority", 0.80))
        risk = str(parsed.get("risk", "medium"))
        reason = str(parsed.get("reason", "local_llm_router"))
    except Exception as exc:  # noqa: BLE001 - malformed local output becomes review, not failure.
        route = "review_candidate"
        priority = 0.80
        risk = "high"
        reason = f"parse_error:{type(exc).__name__}"

    return RouterDecision(
        sample_id=evidence.sample_id,
        clip_id=evidence.clip_id,
        route=route,
        priority=max(0.0, min(1.0, priority)),
        risk=risk if risk in {"low", "medium", "high"} else "medium",
        reason=reason[:240],
        router=f"ollama:{model}",
        latency_ms=latency_ms,
    )


def summarize(decisions: Sequence[RouterDecision], rows_by_sample: dict[str, ClipRow]) -> dict[str, Any]:
    route_counts = Counter(d.route for d in decisions)
    class_by_route: dict[str, Counter[str]] = defaultdict(Counter)
    p0_activity_only = 0
    p0_cloud_later_or_lower = 0
    p0_total = 0
    for decision in decisions:
        gt = rows_by_sample[decision.sample_id].gt
        class_by_route[decision.route][gt] += 1
        if gt in P0_CLASSES:
            p0_total += 1
            if decision.route == "activity_only":
                p0_activity_only += 1
            if decision.route in {"activity_only", "cloud_later"}:
                p0_cloud_later_or_lower += 1

    n = len(decisions)
    avg_latency = sum(d.latency_ms for d in decisions) / n if n else 0.0
    cloud_now = route_counts["cloud_now"]
    cloud_vlm_eventual = route_counts["cloud_now"] + route_counts["cloud_later"]
    return {
        "n": n,
        "routes": dict(sorted(route_counts.items())),
        "cloud_now_rate": cloud_now / n if n else 0.0,
        "eventual_cloud_vlm_rate": cloud_vlm_eventual / n if n else 0.0,
        "p0_total": p0_total,
        "p0_activity_only_count": p0_activity_only,
        "p0_activity_only_rate": p0_activity_only / p0_total if p0_total else 0.0,
        "p0_cloud_later_or_lower_count": p0_cloud_later_or_lower,
        "p0_cloud_later_or_lower_rate": p0_cloud_later_or_lower / p0_total if p0_total else 0.0,
        "avg_latency_ms": avg_latency,
        "class_by_route": {route: dict(counts) for route, counts in sorted(class_by_route.items())},
    }


def select_smoke_evidences(
    evidences: Sequence[VideoEvidence],
    rows_by_sample: dict[str, ClipRow],
    *,
    limit: int,
    seed: int,
) -> list[VideoEvidence]:
    if limit <= 0 or limit >= len(evidences):
        return list(evidences)

    by_gt: dict[str, list[VideoEvidence]] = defaultdict(list)
    for evidence in evidences:
        by_gt[rows_by_sample[evidence.sample_id].gt].append(evidence)

    selected: list[VideoEvidence] = []
    for gt in sorted(by_gt):
        group = sorted(
            by_gt[gt],
            key=lambda e: hashlib.sha1(f"{seed}:smoke:{gt}:{e.sample_id}".encode()).hexdigest(),
        )
        selected.append(group[0])

    remaining_limit = max(0, limit - len(selected))
    selected_ids = {e.sample_id for e in selected}
    remaining = [e for e in evidences if e.sample_id not in selected_ids]
    selected.extend(
        sorted(
            remaining,
            key=lambda e: hashlib.sha1(f"{seed}:smoke-fill:{e.sample_id}".encode()).hexdigest(),
        )[:remaining_limit]
    )
    return sorted(selected, key=lambda e: e.sample_id)


def _bucket_for(value: float, *, very_low: float, low: float, high: float) -> str:
    if value < very_low:
        return "very_low"
    if value < low:
        return "low"
    if value >= high:
        return "high"
    return "mid"


def analyze_separability(
    evidences: Sequence[VideoEvidence],
    rows_by_sample: dict[str, ClipRow],
) -> dict[str, Any]:
    specs = {
        "motion_mean": (0.004, 0.010, 0.026),
        "motion_peak": (0.012, 0.030, 0.120),
        "active_motion_ratio": (0.08, 0.25, 0.70),
        "brightness_mean": (18.0, 35.0, 90.0),
    }
    out: dict[str, Any] = {}
    for field, (very_low, low, high) in specs.items():
        buckets: dict[str, dict[str, int]] = {
            "very_low": {"n": 0, "p0_count": 0},
            "low": {"n": 0, "p0_count": 0},
            "mid": {"n": 0, "p0_count": 0},
            "high": {"n": 0, "p0_count": 0},
        }
        for evidence in evidences:
            value = float(getattr(evidence, field))
            bucket = _bucket_for(value, very_low=very_low, low=low, high=high)
            buckets[bucket]["n"] += 1
            if rows_by_sample[evidence.sample_id].gt in P0_CLASSES:
                buckets[bucket]["p0_count"] += 1
        out[field] = {
            name: {
                "n": data["n"],
                "p0_count": data["p0_count"],
                "p0_rate": data["p0_count"] / data["n"] if data["n"] else 0.0,
            }
            for name, data in buckets.items()
        }
    return out


def decision_subtype(
    *,
    l0_summary: dict[str, Any],
    l1_summary: dict[str, Any] | None,
    separability: dict[str, Any],
) -> str:
    l1_p0_activity_only_rate = l1_summary["p0_activity_only_rate"] if l1_summary else 0.0
    if l0_summary["p0_activity_only_rate"] > 0.02 or l1_p0_activity_only_rate > 0.02:
        return "reject-unsafe"

    risky_static = separability["motion_mean"]["very_low"]["p0_rate"] > 0.05
    activity_only_rate = l0_summary["routes"].get("activity_only", 0) / l0_summary["n"] if l0_summary["n"] else 0.0
    if risky_static and activity_only_rate > 0:
        return "hold-input-limited"

    if l1_summary and l1_summary["cloud_now_rate"] >= 0.90:
        return "hold-model-limited"

    if l0_summary["cloud_now_rate"] > 0.55:
        return "hold-policy-too-conservative"

    return "adopt-v1"


def decision_label(summary: dict[str, Any], *, llm_status: str) -> str:
    if summary["p0_activity_only_rate"] >= 0.05:
        return "reject"
    if (
        summary["cloud_now_rate"] <= 0.40
        and summary["p0_activity_only_rate"] <= 0.02
        and summary["avg_latency_ms"] <= 3000
        and llm_status == "completed"
    ):
        return "adopt"
    return "hold"


def write_report(path: Path, results: dict[str, Any]) -> None:
    l0 = results["l0_summary"]
    l1 = results["l1_summary"]
    lines = [
        "# Local Router v0 Report",
        "",
        "## Decision",
        "",
        f"Decision: `{results['decision']}`",
        f"Decision subtype: `{results.get('decision_subtype', 'n/a')}`",
        "",
        "This is the first detector-independent RBA Router scorecard. The router did not see images, "
        "filenames, GT labels, or detector boxes.",
        "",
        "## L0 Deterministic Router",
        "",
        f"- N: {l0['n']}",
        f"- routes: `{json.dumps(l0['routes'], ensure_ascii=False, sort_keys=True)}`",
        f"- cloud_now rate: {_pct(l0['cloud_now_rate'])}",
        f"- eventual cloud VLM rate: {_pct(l0['eventual_cloud_vlm_rate'])}",
        f"- P0 -> activity_only: {l0['p0_activity_only_count']}/{l0['p0_total']} = {_pct(l0['p0_activity_only_rate'])}",
        f"- P0 -> cloud_later or lower: {l0['p0_cloud_later_or_lower_count']}/{l0['p0_total']} = {_pct(l0['p0_cloud_later_or_lower_rate'])}",
        f"- avg router latency: {l0['avg_latency_ms']:.3f} ms/clip",
        "",
        "## L1 Local LLM Smoke",
        "",
        f"- status: `{results['l1_status']}`",
    ]
    if results.get("summary_source"):
        lines.append(f"- summary source: `{results['summary_source']}`")
    lines.append(f"- model: `{results['l1_model'] or 'n/a'}`")
    if l1:
        lines.extend(
            [
                f"- N: {l1['n']}",
                f"- routes: `{json.dumps(l1['routes'], ensure_ascii=False, sort_keys=True)}`",
                f"- cloud_now rate: {_pct(l1['cloud_now_rate'])}",
                f"- P0 -> activity_only: {l1['p0_activity_only_count']}/{l1['p0_total']} = {_pct(l1['p0_activity_only_rate'])}",
                f"- avg router latency: {l1['avg_latency_ms']:.1f} ms/clip",
            ]
        )
    lines.extend(
        [
            "",
            "## L0 Class By Route",
            "",
            "```json",
            json.dumps(l0["class_by_route"], ensure_ascii=False, indent=2, sort_keys=True),
            "```",
        ]
    )
    if l1:
        lines.extend(
            [
                "",
                "## L1 Class By Route",
                "",
                "```json",
                json.dumps(l1["class_by_route"], ensure_ascii=False, indent=2, sort_keys=True),
                "```",
            ]
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            results["interpretation"],
            "",
            "## Artifacts",
            "",
            "- `features.jsonl`",
            "- `l0-decisions.jsonl`",
            "- `separability.json`",
            "- `l1-decisions.jsonl` when L1 runs",
            "- `results.json`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def available_ollama_models() -> list[str]:
    try:
        proc = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10, check=False)
    except Exception:  # noqa: BLE001
        return []
    if proc.returncode != 0:
        return []
    names: list[str] = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names


def run(args: argparse.Namespace) -> dict[str, Any]:
    experiment_dir = Path(args.experiment_dir)
    experiment_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = load_manifest(Path(args.manifest))
    selected = select_rows(manifest_rows, args.sample_size, args.seed)
    rows_by_sample = {sample_id_for(row, index): row for index, row in enumerate(selected, start=1)}

    feature_path = experiment_dir / "features.jsonl"
    if args.summarize_only and feature_path.exists():
        evidences = load_features(feature_path)
    else:
        evidences = []
        for index, row in enumerate(selected, start=1):
            sample_id = sample_id_for(row, index)
            evidences.append(
                extract_video_evidence(
                    DATASET_DIR / row.filename,
                    sample_id=sample_id,
                    clip_id=row.clip_id,
                    frame_samples=args.frame_samples,
                )
            )
        write_jsonl(feature_path, [asdict(e) for e in evidences])

    l0_policy = getattr(args, "l0_policy", "v0")
    l0_router = route_l0_v1 if l0_policy == "v1" else route_l0
    l0_decisions = [l0_router(e) for e in evidences]
    write_jsonl(experiment_dir / "l0-decisions.jsonl", [asdict(d) for d in l0_decisions])
    l0_summary = summarize(l0_decisions, rows_by_sample)
    separability = analyze_separability(evidences, rows_by_sample)
    (experiment_dir / "separability.json").write_text(
        json.dumps(separability, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    l1_status = "not_requested"
    l1_model = args.ollama_model
    l1_summary: dict[str, Any] | None = None
    summary_source: str | None = None
    l1_decisions_path = experiment_dir / "l1-decisions.jsonl"
    if args.summarize_only and l1_decisions_path.exists():
        l1_decisions_data = [
            json.loads(line)
            for line in l1_decisions_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        l1_decisions = [RouterDecision(**row) for row in l1_decisions_data]
        if l1_decisions and not l1_model:
            router_name = l1_decisions[0].router
            l1_model = router_name.split(":", 1)[1] if ":" in router_name else router_name
        l1_summary = summarize(l1_decisions, rows_by_sample)
        l1_status = "completed"
        summary_source = "existing_l1_decisions_jsonl"
    elif args.run_ollama:
        models = available_ollama_models()
        if not models and not args.ollama_model:
            l1_status = "blocked_no_ollama_models"
        else:
            l1_model = args.ollama_model or models[0]
            smoke_evidences = select_smoke_evidences(
                evidences,
                rows_by_sample,
                limit=args.ollama_limit,
                seed=args.seed,
            )
            l1_decisions = [
                route_with_ollama(e, model=l1_model, timeout_sec=args.ollama_timeout_sec, prompt_mode=args.prompt_mode)
                for e in smoke_evidences
            ]
            write_jsonl(experiment_dir / "l1-decisions.jsonl", [asdict(d) for d in l1_decisions])
            l1_summary = summarize(l1_decisions, rows_by_sample)
            l1_status = "completed"

    label = decision_label(l0_summary, llm_status=l1_status)
    subtype = decision_subtype(
        l0_summary=l0_summary,
        l1_summary=l1_summary,
        separability=separability,
    )
    if (
        l1_summary
        and l1_summary["cloud_now_rate"] >= l0_summary["cloud_now_rate"]
        and l1_summary["p0_activity_only_rate"] == 0
    ):
        cloud_later_count = l1_summary["routes"].get("cloud_later", 0)
        cloud_now_count = l1_summary["routes"].get("cloud_now", 0)
        if cloud_later_count > 0:
            interpretation = (
                "L0 is safe but too conservative, and the first local LLM smoke only produced limited immediate-call "
                f"reduction: {l1_model} routed {cloud_now_count}/{l1_summary['n']} smoke samples to cloud_now and "
                f"{cloud_later_count}/{l1_summary['n']} to cloud_later. This keeps P0 safe, but still misses the "
                "cloud_now reduction target and needs a stronger local model/prompt or more operational metadata."
            )
        else:
            interpretation = (
                "L0 is safe but too conservative, and the first local LLM smoke did not improve routing: "
                f"{l1_model} sent every smoke sample to cloud_now. This keeps P0 safe, but provides no cloud VLM "
                "reduction. Next step is either a stronger local model/prompt with calibration examples, or adding "
                "operational metadata before another L1 run."
            )
    elif l0_summary["p0_activity_only_rate"] == 0 and l0_summary["cloud_now_rate"] > 0.40:
        interpretation = (
            "L0 is safe on P0 -> activity_only, but too conservative for the target cloud_now <= 40% gate. "
            "This supports continuing to L1/local LLM or adding operational metadata, rather than adopting L0 as-is."
        )
    elif l0_summary["p0_activity_only_rate"] > 0:
        interpretation = (
            "L0 pushed at least one P0 clip into activity_only, so the deterministic rule is not safe enough without "
            "additional evidence or stricter thresholds."
        )
    else:
        interpretation = "L0 met the core safety gate and is a viable baseline for L1 comparison."

    results = {
        "decision": label,
        "decision_subtype": subtype,
        "sample_size": len(evidences),
        "seed": args.seed,
        "l0_summary": l0_summary,
        "separability": separability,
        "l1_status": l1_status,
        "l1_model": l1_model,
        "l1_summary": l1_summary,
        "summary_source": summary_source,
        "interpretation": interpretation,
    }
    (experiment_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_report(experiment_dir / "REPORT.md", results)
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DATASET_DIR / "manifest.csv"))
    parser.add_argument("--experiment-dir", default=str(DEFAULT_EXPERIMENT_DIR))
    parser.add_argument("--sample-size", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260709)
    parser.add_argument("--frame-samples", type=int, default=16)
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--run-ollama", action="store_true")
    parser.add_argument("--ollama-model", default="")
    parser.add_argument("--ollama-limit", type=int, default=30)
    parser.add_argument("--ollama-timeout-sec", type=int, default=30)
    parser.add_argument("--l0-policy", choices=["v0", "v1"], default="v0")
    parser.add_argument("--prompt-mode", choices=["v0", "v1"], default="v0")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    results = run(args)
    print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
