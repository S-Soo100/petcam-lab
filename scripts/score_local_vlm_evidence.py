"""local VLM evidence 품질 scorer (TEST-SHEET §9·§10·§11).

raw 결과 JSONL + 사람 evidence GT + manifest 를 읽어 완전성·품질·반복 일관성을 채점하고
verdict 우선순위를 적용한다. 독립 재계산(`recompute_local_vlm_evidence.py`)이 같은 canonical
값을 내야 하며, 불일치는 `REJECT_INTEGRITY` 다.

deterministic scorer 원칙(무결성 6단계 §4-3a): 재량 없이 사전 등록 게이트를 기계 적용한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.validate_local_vlm_evidence_manifest import build_measured_keys

_CI_SEED = 20260721
_ROUND = 6

# 사전 등록 품질 게이트 (TEST-SHEET §10)
GATE_PRESENCE_MACRO_F1 = 0.85
GATE_PRESENT_RECALL = 0.95
GATE_VISIBILITY_WEIGHTED_F1 = 0.80
GATE_MOTION_MACRO_F1 = 0.75
GATE_OBJECT_TOPK_RECALL = 0.75
GATE_COMPLETION = 0.99
GATE_REPEAT_CONSISTENCY = 0.95

# 독립 재계산과 합의할 canonical 필드 (recompute 와 동일해야 함)
CANONICAL_FIELDS = (
    "expected_keys",
    "got_keys",
    "missing",
    "unexpected",
    "duplicates",
    "successes",
    "parse_failures",
    "gen_errors",
    "input_failures",
    "present_recall",
    "presence_macro_f1",
    "visibility_weighted_f1",
    "motion_macro_f1",
    "object_topk_recall",
    "abstain_rate",
    "repeat_consistency",
)

_CATEGORICAL_FIELDS = (
    "presence_observation",
    "visibility",
    "motion_extent",
)


# --- 지표 primitives ---------------------------------------------------------


def _confusion(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    m: dict[str, dict[str, int]] = {}
    for g, p in pairs:
        m.setdefault(g, {}).setdefault(p, 0)
        m[g][p] += 1
    return m


def _per_class_f1(pairs: list[tuple[str, str]], label: str) -> tuple[float, int]:
    tp = sum(1 for g, p in pairs if g == label and p == label)
    fp = sum(1 for g, p in pairs if g != label and p == label)
    fn = sum(1 for g, p in pairs if g == label and p != label)
    support = sum(1 for g, _ in pairs if g == label)
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return f1, support


def macro_f1(pairs: list[tuple[str, str]], labels: list[str] | None = None) -> float:
    if not pairs:
        return 0.0
    if labels is None:
        labels = sorted({g for g, _ in pairs} | {p for _, p in pairs})
    f1s = [_per_class_f1(pairs, c)[0] for c in labels]
    return sum(f1s) / len(f1s) if f1s else 0.0


def weighted_f1(pairs: list[tuple[str, str]], labels: list[str] | None = None) -> float:
    if not pairs:
        return 0.0
    if labels is None:
        labels = sorted({g for g, _ in pairs} | {p for _, p in pairs})
    total = 0.0
    total_support = 0
    for c in labels:
        f1, support = _per_class_f1(pairs, c)
        total += f1 * support
        total_support += support
    return total / total_support if total_support else 0.0


def present_recall(pairs: list[tuple[str, str]]) -> float:
    denom = sum(1 for g, _ in pairs if g == "present")
    if denom == 0:
        return 0.0
    num = sum(1 for g, p in pairs if g == "present" and p == "present")
    return num / denom


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    phat = successes / n
    denom = 1 + z**2 / n
    center = (phat + z**2 / (2 * n)) / denom
    margin = (z * math.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def _bootstrap_ci(values: list[float], seed: int = _CI_SEED, n_boot: int = 1000) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        return (values[0], values[0])
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(len(values))] for _ in values]
        means.append(statistics.fmean(sample))
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot)]
    return (lo, hi)


# --- 데이터 추출 -------------------------------------------------------------


def _scored_holdout_base(results: list[dict]) -> list[dict]:
    return [
        r
        for r in results
        if r.get("split") == "holdout"
        and r.get("run_index") == 0
        and r.get("status") == "success"
        and r.get("observation")
    ]


def _pairs(scored: list[dict], gt_by: dict, field: str) -> list[tuple[str, str]]:
    out = []
    for r in scored:
        g = gt_by.get(r["durable_key"])
        if g is None:
            continue
        out.append((g[field], r["observation"][field]))
    return out


def _categorical_tuple(obs: dict) -> tuple:
    return (
        obs["presence_observation"],
        obs["visibility"],
        obs["motion_extent"],
        tuple(sorted(obs["body_region_candidates"])),
        tuple(sorted(obs["object_candidates"])),
        bool(obs["abstain"]),
    )


# --- 메인 score --------------------------------------------------------------


def score(
    results: list[dict],
    gt_rows: list[dict],
    manifest: dict,
    *,
    runtime: dict | None = None,
    recompute_match: bool | None = None,
    ci_seed: int = _CI_SEED,
) -> dict:
    gt_by = {g["durable_key"]: g for g in gt_rows}
    expected_keys = {k["measured_key"] for k in build_measured_keys(manifest)}
    got = [r["measured_key"] for r in results]
    got_counter = Counter(got)
    got_set = set(got)

    completeness = {
        "expected_keys": len(expected_keys),
        "got_keys": len(got_set),
        "missing": len(expected_keys - got_set),
        "unexpected": len(got_set - expected_keys),
        "duplicates": sum(c - 1 for c in got_counter.values() if c > 1),
        "successes": sum(1 for r in results if r.get("status") == "success"),
        "parse_failures": sum(1 for r in results if r.get("status") == "parse_failure"),
        "gen_errors": sum(1 for r in results if r.get("status") == "gen_error"),
        "input_failures": sum(1 for r in results if r.get("status") == "input_failure"),
    }

    scored = _scored_holdout_base(results)
    presence_pairs = _pairs(scored, gt_by, "presence_observation")
    visibility_pairs = _pairs(scored, gt_by, "visibility")
    motion_pairs = _pairs(scored, gt_by, "motion_extent")

    pr = present_recall(presence_pairs)
    n_present = sum(1 for g, _ in presence_pairs if g == "present")
    n_present_hit = sum(1 for g, p in presence_pairs if g == "present" and p == "present")

    # object top-k recall
    obj_recalls: list[float] = []
    for r in scored:
        g = gt_by.get(r["durable_key"])
        if g is None:
            continue
        gt_objs = set(g["object_candidates"]) - {"unknown"}
        if not gt_objs:
            continue
        pred_objs = set(r["observation"]["object_candidates"])
        obj_recalls.append(len(gt_objs & pred_objs) / len(gt_objs))
    object_topk = statistics.fmean(obj_recalls) if obj_recalls else None

    abstain_n = sum(1 for r in scored if r["observation"]["abstain"])
    abstain_rate = abstain_n / len(scored) if scored else 0.0
    non_abstain = [r for r in scored if not r["observation"]["abstain"]]
    non_abstain_acc = (
        sum(
            1
            for r in non_abstain
            if gt_by.get(r["durable_key"])
            and gt_by[r["durable_key"]]["presence_observation"]
            == r["observation"]["presence_observation"]
        )
        / len(non_abstain)
        if non_abstain
        else 0.0
    )

    presence_f1 = macro_f1(presence_pairs)
    visibility_wf1 = weighted_f1(visibility_pairs)
    motion_f1 = macro_f1(motion_pairs)

    # 반복 일관성
    repeat_clips = list(manifest.get("repeat_clips") or [])
    consistent = 0
    for dk in repeat_clips:
        runs = {
            r["run_index"]: r
            for r in results
            if r.get("durable_key") == dk and r.get("run_index") in (0, 1, 2)
        }
        if len(runs) != 3 or any(runs[i].get("status") != "success" for i in (0, 1, 2)):
            continue
        tuples = {_categorical_tuple(runs[i]["observation"]) for i in (0, 1, 2)}
        if len(tuples) == 1:
            consistent += 1
    repeat_consistency = consistent / len(repeat_clips) if repeat_clips else 1.0

    # CI
    pr_ci = wilson_interval(n_present_hit, n_present)
    presence_f1_ci = _bootstrap_ci([1.0 if p == g else 0.0 for g, p in presence_pairs], ci_seed)
    obj_ci = _bootstrap_ci(obj_recalls, ci_seed) if obj_recalls else (0.0, 0.0)

    quality = {
        "present_recall": {"point": round(pr, _ROUND), "ci": [round(pr_ci[0], _ROUND), round(pr_ci[1], _ROUND)]},
        "presence_macro_f1": {"point": round(presence_f1, _ROUND), "ci": [round(presence_f1_ci[0], _ROUND), round(presence_f1_ci[1], _ROUND)]},
        "visibility_weighted_f1": {"point": round(visibility_wf1, _ROUND)},
        "motion_macro_f1": {"point": round(motion_f1, _ROUND)},
        "object_topk_recall": {
            "point": round(object_topk, _ROUND) if object_topk is not None else None,
            "ci": [round(obj_ci[0], _ROUND), round(obj_ci[1], _ROUND)] if obj_recalls else None,
        },
        "abstain_rate": round(abstain_rate, _ROUND),
        "non_abstain_accuracy": round(non_abstain_acc, _ROUND),
    }

    confusion = {
        "presence": _confusion(presence_pairs),
        "motion_extent": _confusion(motion_pairs),
    }

    # 게이트
    completion_rate = (
        (completeness["expected_keys"] - completeness["missing"]) / completeness["expected_keys"]
        if completeness["expected_keys"]
        else 0.0
    )
    schema_rate = (
        completeness["successes"] / (completeness["successes"] + completeness["parse_failures"])
        if (completeness["successes"] + completeness["parse_failures"])
        else 1.0
    )
    integrity_ok = (
        completeness["missing"] == 0
        and completeness["unexpected"] == 0
        and completeness["duplicates"] == 0
        and (recompute_match is not False)
    )
    reliability_ok = (
        completion_rate >= GATE_COMPLETION
        and schema_rate >= 1.0
        and repeat_consistency >= GATE_REPEAT_CONSISTENCY
    )
    quality_ok = (
        presence_f1 >= GATE_PRESENCE_MACRO_F1
        and pr >= GATE_PRESENT_RECALL
        and visibility_wf1 >= GATE_VISIBILITY_WEIGHTED_F1
        and motion_f1 >= GATE_MOTION_MACRO_F1
        and (object_topk is None or object_topk >= GATE_OBJECT_TOPK_RECALL)
    )
    gates = {
        "runtime_drift": bool(runtime and runtime.get("drift")),
        "data_insufficient": bool(runtime and runtime.get("data_insufficient")),
        "integrity": integrity_ok,
        "resource": bool(runtime.get("resource_ok", True)) if runtime else True,
        "reliability": reliability_ok,
        "quality": quality_ok,
    }

    return {
        "completeness": completeness,
        "quality": quality,
        "confusion": confusion,
        "repeat": {"repeated_clips": len(repeat_clips), "consistent": consistent, "consistency": round(repeat_consistency, _ROUND)},
        "gates": gates,
        "verdict": compute_verdict(gates),
        "derived": {"completion_rate": round(completion_rate, _ROUND), "schema_rate": round(schema_rate, _ROUND)},
    }


def compute_verdict(gates: dict) -> str:
    """TEST-SHEET §11 우선순위. 정확히 하나만 반환."""
    if gates.get("runtime_drift"):
        return "BLOCKED_RUNTIME_DRIFT"
    if gates.get("data_insufficient"):
        return "BLOCKED_DATA_INSUFFICIENT"
    if not gates.get("integrity", True):
        return "REJECT_INTEGRITY"
    if not gates.get("resource", True):
        return "REJECT_RESOURCE"
    if not gates.get("reliability", True):
        return "REJECT_RELIABILITY"
    if not gates.get("quality", True):
        return "REJECT_QUALITY"
    return "PASS_LOCAL_EVIDENCE_ANALYST"


# --- canonical (독립 재계산 합의) --------------------------------------------


def canonical_summary(full: dict) -> dict:
    q = full["quality"]
    c = full["completeness"]
    otk = q["object_topk_recall"]["point"]
    return {
        "expected_keys": c["expected_keys"],
        "got_keys": c["got_keys"],
        "missing": c["missing"],
        "unexpected": c["unexpected"],
        "duplicates": c["duplicates"],
        "successes": c["successes"],
        "parse_failures": c["parse_failures"],
        "gen_errors": c["gen_errors"],
        "input_failures": c["input_failures"],
        "present_recall": q["present_recall"]["point"],
        "presence_macro_f1": q["presence_macro_f1"]["point"],
        "visibility_weighted_f1": q["visibility_weighted_f1"]["point"],
        "motion_macro_f1": q["motion_macro_f1"]["point"],
        "object_topk_recall": otk,
        "abstain_rate": q["abstain_rate"],
        "repeat_consistency": full["repeat"]["consistency"],
    }


def canonical_sha256(canonical: dict) -> str:
    payload = {k: canonical[k] for k in CANONICAL_FIELDS}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# --- CLI ---------------------------------------------------------------------


def _load_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", required=True, type=Path)
    p.add_argument("--gt", required=True, type=Path)
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)

    results = _load_jsonl(args.results)
    gt = json.loads(args.gt.read_text())
    gt_rows = gt if isinstance(gt, list) else gt.get("rows", [])
    manifest = json.loads(args.manifest.read_text())

    full = score(results, gt_rows, manifest)
    canon = canonical_summary(full)
    full["canonical"] = canon
    full["canonical_sha256"] = canonical_sha256(canon)
    text = json.dumps(full, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(f"VERDICT {full['verdict']} canonical_sha256={full['canonical_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
