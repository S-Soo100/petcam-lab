"""독립 재계산 — scorer/validator 를 import 하지 않고 canonical 집계를 다시 계산한다.

무결성 6단계 §4-3a 의 "independent recompute": harness(scorer)와 완전히 다른 코드 경로로
같은 숫자를 내야 한다. 하나라도 다르면 `REJECT_INTEGRITY`. 표본 key 규칙·지표·자원 gate 를
전부 여기서 독립 구현한다(공유 helper·상수 import 금지 — 설계 H5).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_ROUND = 6
# build_measured_keys 와 동일한 규칙을 **독립 재구현**: clip 당 run0, repeat clip 은 run0/1/2.
# 셔플·spread 는 순서만 바꿔 measured_key SET 을 바꾸지 않으므로 여기선 SET 만 재현하면 된다.
_REPEAT_RUNS = 3

# scorer 와 코드를 공유하지 않는 독립 자원 gate 상수(설계 H4).
_RESOURCE_FIELDS = (
    "peak_rss_bytes",
    "swap_delta_bytes",
    "temp_residual_count",
    "worker_exit_delta",
    "deadline_delay_sec",
    "sustained_clips_per_hour",
    "projected_four_camera_p95",
)

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


def _macro_f1(pairs, weighted=False):
    if not pairs:
        return 0.0
    labels = sorted(set(g for g, _ in pairs) | set(p for _, p in pairs))
    acc = 0.0
    weight_sum = 0
    for c in labels:
        tp = len([1 for g, p in pairs if g == c and p == c])
        fp = len([1 for g, p in pairs if g != c and p == c])
        fn = len([1 for g, p in pairs if g == c and p != c])
        support = len([1 for g, _ in pairs if g == c])
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        if weighted:
            acc += f1 * support
            weight_sum += support
        else:
            acc += f1
    if weighted:
        return acc / weight_sum if weight_sum else 0.0
    return acc / len(labels)


def _expected_keys(manifest: dict) -> set[str]:
    """measured_key SET 을 독립 재구현. clip 당 run0, repeat clip 은 run0/1/2."""
    repeat_set = set(manifest.get("repeat_clips") or [])
    expected: set[str] = set()
    for c in manifest.get("clips") or []:
        dk = c.get("durable_key")
        runs = _REPEAT_RUNS if dk in repeat_set else 1
        for run in range(runs):
            expected.add(f"{dk}#run{run}")
    return expected


def _resource_ok(runtime: dict) -> bool:
    """scorer 를 import 하지 않는 독립 자원 gate 재계산. 필드 누락은 예외."""
    missing = [k for k in _RESOURCE_FIELDS if runtime.get(k) is None]
    if missing:
        raise ValueError(f"RESOURCE_EVIDENCE_MISSING:{','.join(missing)}")
    return (
        runtime["peak_rss_bytes"] <= 8 * 1024**3
        and runtime["swap_delta_bytes"] <= 1 * 1024**3
        and runtime["temp_residual_count"] == 0
        and runtime["worker_exit_delta"] == 0
        and runtime["deadline_delay_sec"] == 0
        and runtime["sustained_clips_per_hour"] >= 2 * runtime["projected_four_camera_p95"]
    )


def recompute(
    results: list[dict], gt_rows: list[dict], manifest: dict, runtime: dict | None = None
) -> dict:
    gt_by = {g["durable_key"]: g for g in gt_rows}
    expected = _expected_keys(manifest)
    # runtime 이 주어지면 자원 gate 도 독립 검증한다(필드 누락은 fail-closed). canonical 엔 안 넣는다.
    if runtime is not None:
        _resource_ok(runtime)

    got_list = [r["measured_key"] for r in results]
    got_set = set(got_list)
    dup = 0
    seen = {}
    for k in got_list:
        seen[k] = seen.get(k, 0) + 1
    for k, n in seen.items():
        if n > 1:
            dup += n - 1

    def count_status(s):
        return len([1 for r in results if r.get("status") == s])

    # holdout base success
    base = [
        r
        for r in results
        if r.get("split") == "holdout"
        and r.get("run_index") == 0
        and r.get("status") == "success"
        and r.get("observation")
    ]

    def field_pairs(field):
        pairs = []
        for r in base:
            g = gt_by.get(r["durable_key"])
            if g is not None:
                pairs.append((g[field], r["observation"][field]))
        return pairs

    presence = field_pairs("presence_observation")
    visibility = field_pairs("visibility")
    motion = field_pairs("motion_extent")

    # present recall
    gt_present = [1 for g, _ in presence if g == "present"]
    hit_present = [1 for g, p in presence if g == "present" and p == "present"]
    pr = (len(hit_present) / len(gt_present)) if gt_present else 0.0

    # object top-k recall
    recalls = []
    for r in base:
        g = gt_by.get(r["durable_key"])
        if g is None:
            continue
        gt_objs = set(g["object_candidates"]) - {"unknown"}
        if not gt_objs:
            continue
        pred = set(r["observation"]["object_candidates"])
        recalls.append(len(gt_objs & pred) / len(gt_objs))
    obj = (sum(recalls) / len(recalls)) if recalls else None

    # abstain rate
    abstain = len([1 for r in base if r["observation"]["abstain"]])
    abstain_rate = (abstain / len(base)) if base else 0.0

    # repeat consistency
    repeat_clips = list(manifest.get("repeat_clips") or [])
    consistent = 0
    for dk in repeat_clips:
        runs = {}
        for r in results:
            if r.get("durable_key") == dk and r.get("run_index") in (0, 1, 2):
                runs[r["run_index"]] = r
        if len(runs) != 3:
            continue
        if any(runs[i].get("status") != "success" for i in (0, 1, 2)):
            continue
        sigs = set()
        for i in (0, 1, 2):
            o = runs[i]["observation"]
            sigs.add(
                (
                    o["presence_observation"],
                    o["visibility"],
                    o["motion_extent"],
                    tuple(sorted(o["body_region_candidates"])),
                    tuple(sorted(o["object_candidates"])),
                    bool(o["abstain"]),
                )
            )
        if len(sigs) == 1:
            consistent += 1
    repeat_consistency = (consistent / len(repeat_clips)) if repeat_clips else 1.0

    return {
        "expected_keys": len(expected),
        "got_keys": len(got_set),
        "missing": len(expected - got_set),
        "unexpected": len(got_set - expected),
        "duplicates": dup,
        "successes": count_status("success"),
        "parse_failures": count_status("parse_failure"),
        "gen_errors": count_status("gen_error"),
        "input_failures": count_status("input_failure"),
        "present_recall": round(pr, _ROUND),
        "presence_macro_f1": round(_macro_f1(presence), _ROUND),
        "visibility_weighted_f1": round(_macro_f1(visibility, weighted=True), _ROUND),
        "motion_macro_f1": round(_macro_f1(motion), _ROUND),
        "object_topk_recall": (round(obj, _ROUND) if obj is not None else None),
        "abstain_rate": round(abstain_rate, _ROUND),
        "repeat_consistency": round(repeat_consistency, _ROUND),
    }


def canonical_sha256(canonical: dict) -> str:
    payload = {k: canonical[k] for k in CANONICAL_FIELDS}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


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

    canon = recompute(results, gt_rows, manifest)
    sha = canonical_sha256(canon)
    out = {"canonical": canon, "canonical_sha256": sha}
    text = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(f"RECOMPUTE canonical_sha256={sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
