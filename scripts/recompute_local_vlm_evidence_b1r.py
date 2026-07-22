"""Gate B1R 독립 재계산 — pool artifact 를 stdlib 만으로 다시 계산해 probe aggregate 와 대조.

**probe(build_availability/build_episode_candidates_v2)를 import 하지 않는다.** pool JSON 의 candidate
목록에서 final count, clip/episode overlap, canonical pool SHA 를 독립 구현으로 재계산하고, aggregate 의
선언값과 정확히 일치하는지 확인한다. mismatch 면 exit 1 (→ B1R_REJECT_INTEGRITY).

독립성 계약: canonical 형식(정렬 규칙·직렬화)을 이 파일에 별도 하드코딩한다. selector 모듈과 같은 결과가
나와야만 무결성이 증명된다(같은 코드 재사용이면 검증이 아니다).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

# frozen study strata 순서 (독립 하드코딩 — selector 모듈 import 금지).
STRATA = ("absent", "big_move", "rest_micro", "lick_water_food", "wheel_object", "hardcase")


def _canonical_candidate(c: dict) -> dict:
    """candidate_to_dict 와 동일 필드·순서(정렬은 json sort_keys 가 담당)."""
    return {
        "clip_id": c["clip_id"],
        "stratum": c["stratum"],
        "priority_score": c["priority_score"],
        "reason_codes": list(c["reason_codes"]),
        "episode_key": c["episode_key"],
        "source_run_id": c["source_run_id"],
        "source_assessment_id": c["source_assessment_id"],
        "selection_identity_sha256": c["selection_identity_sha256"],
    }


def canonical_pool_sha256(pool: list[dict], selector_version: str) -> str:
    """candidates_canonical_json 과 동치인 독립 재구현. 입력 순서 무관."""
    ordered = sorted(
        pool,
        key=lambda c: (STRATA.index(c["stratum"]), -float(c["priority_score"]), c["clip_id"]),
    )
    payload = {
        "selector_version": selector_version,
        "candidates": [_canonical_candidate(c) for c in ordered],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def recompute(aggregate: dict, pool: dict) -> dict:
    """pool candidate 로 count/overlap/SHA 재계산 후 aggregate/pool 선언값과 대조."""
    reasons: list[str] = []
    cands = pool["pool"]
    selector_version = pool.get("selector_version")

    final = Counter(c["stratum"] for c in cands)
    recomputed_final = {s: final.get(s, 0) for s in STRATA}
    declared_final = aggregate.get("final_allocated_counts")
    if declared_final is not None and {k: declared_final.get(k, 0) for k in STRATA} != recomputed_final:
        reasons.append("final_allocated_counts mismatch")

    clip_overlap = len(cands) - len({c["clip_id"] for c in cands})
    episode_overlap = len(cands) - len({c["episode_key"] for c in cands})
    if clip_overlap != aggregate.get("clip_overlap", 0):
        reasons.append("clip_overlap declared mismatch")
    if episode_overlap != aggregate.get("episode_overlap", 0):
        reasons.append("episode_overlap declared mismatch")
    if clip_overlap != 0 or episode_overlap != 0:
        reasons.append("nonzero clip/episode overlap")

    recomputed_sha = canonical_pool_sha256(cands, selector_version)
    if recomputed_sha != pool.get("pool_sha256"):
        reasons.append("pool_sha256 mismatch (pool)")
    if aggregate.get("pool_sha256") is not None and recomputed_sha != aggregate.get("pool_sha256"):
        reasons.append("pool_sha256 mismatch (aggregate)")

    return {
        "match": not reasons,
        "reasons": reasons,
        "recomputed_pool_sha256": recomputed_sha,
        "recomputed_final_allocated_counts": recomputed_final,
        "clip_overlap": clip_overlap,
        "episode_overlap": episode_overlap,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="B1R pool 독립 재계산 (probe 미의존)")
    p.add_argument("--aggregate", required=True, help="probe tracked aggregate JSON")
    p.add_argument("--pool", required=True, help="probe git-ignored pool JSON")
    args = p.parse_args(argv)

    aggregate = json.loads(Path(args.aggregate).read_text(encoding="utf-8"))
    pool = json.loads(Path(args.pool).read_text(encoding="utf-8"))
    res = recompute(aggregate, pool)
    if res["match"]:
        print(f"MATCH pool_sha256={res['recomputed_pool_sha256']} "
              f"final={res['recomputed_final_allocated_counts']}")
        return 0
    print("MISMATCH: " + "; ".join(res["reasons"]), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
