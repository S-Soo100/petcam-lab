"""T0 채점: blind_sheet verdict × assignment key 그룹 → care precision + decision.

TEST-SHEET §5 를 기계 적용한다 (재량 금지·1회 실행).
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
EXP_DIR = _REPO_ROOT / "experiments" / "t0-bowl-dwell-probe"

CARE = {"eating", "drinking"}
VALID = {"eating", "drinking", "licking_surface", "near_bowl_no_care",
         "elsewhere", "absent", "unsure"}


def score_groups(sheet: dict, key: list) -> dict:
    """그룹별 care_count / judged(unsure 제외) / care_rate / verdict 분포."""
    out: dict[str, dict] = {}
    for item in key:
        g = item["group"]
        v = sheet.get(item["review_id"], "")
        grp = out.setdefault(g, {"care_count": 0, "judged": 0,
                                 "verdicts": Counter(), "n": 0})
        grp["n"] += 1
        grp["verdicts"][v] += 1
        if v and v != "unsure":
            grp["judged"] += 1
            if v in CARE:
                grp["care_count"] += 1
    for grp in out.values():
        grp["care_rate"] = round(grp["care_count"] / grp["judged"], 4) if grp["judged"] else 0.0
        grp["verdicts"] = dict(grp["verdicts"])
    return out


def decide(top: dict, rand: dict) -> str:
    """TEST-SHEET §5: adopt = top 케어 ≥6 AND top care_rate > random care_rate.
    reject = top 케어 ≤2. hold = 3~5건 (또는 ≥6이나 rate 비교 실패)."""
    if top["care_count"] >= 6 and top["care_rate"] > rand["care_rate"]:
        return "adopt"
    if top["care_count"] <= 2:
        return "reject"
    return "hold"


def main() -> int:
    sheet: dict[str, str] = {}
    with (EXP_DIR / "blind_sheet.csv").open() as f:
        for row in csv.DictReader(r for r in f if not r.startswith("#")):
            v = row["verdict"].strip()
            if v not in VALID:
                raise SystemExit(f"허용 외 verdict: {row['review_id']}={v!r}")
            sheet[row["review_id"]] = v
    key = json.loads((EXP_DIR / "key" / "assignment_key.json").read_text())["items"]

    groups = score_groups(sheet, key)
    decision = decide(groups["top"], groups["random"])
    results = {"groups": groups, "decision": decision,
               "care_classes": sorted(CARE), "n_total": len(key)}
    (EXP_DIR / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
