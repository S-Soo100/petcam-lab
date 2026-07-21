"""T1 채점: blind_sheet + key 조인 → 그룹별 지표 → TEST-SHEET §5·§7 기계 판정.

채점 시점에만 key 개봉 (하드 계약 ②). 판정 룰은 동결 시트 그대로 — 사후 변경 금지.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
EXP_DIR = _REPO_ROOT / "experiments" / "t1-highlight-selection"

INFORMATIVE = {"informative_care", "informative_other"}
ADOPT_GAP = 0.20      # §5: S−R ≥ +20%p
ADOPT_MIN_COUNT = 8   # §5: AND S informative ≥ 8
HOLD_GAP = 0.10       # §5: +10%p 이상 +20%p 미만
HOLD_COUNT = (5, 7)   # §5: 또는 S informative 5~7
REJECT_MAX_COUNT = 4  # §5: S informative ≤ 4


def score_groups(sheet: dict[str, str], key: list[dict]) -> dict:
    """그룹별 n/judged(unsure 제외)/informative/care/absent + informative_rate."""
    groups: dict[str, dict] = {}
    for item in key:
        g = groups.setdefault(item["group"], {
            "n": 0, "judged": 0, "informative": 0, "care": 0, "absent": 0})
        v = sheet[item["review_id"]]
        g["n"] += 1
        if v == "unsure":
            continue
        g["judged"] += 1
        if v in INFORMATIVE:
            g["informative"] += 1
        if v == "informative_care":
            g["care"] += 1
        if v == "absent":
            g["absent"] += 1
    for g in groups.values():
        g["informative_rate"] = round(g["informative"] / g["judged"], 4) if g["judged"] else 0.0
    return groups


def decide(score: dict, rand: dict) -> str:
    """§5 게이트 기계 적용 — adopt → reject → hold 순 판정."""
    gap = score["informative_rate"] - rand["informative_rate"]
    count = score["informative"]
    if gap >= ADOPT_GAP and count >= ADOPT_MIN_COUNT:
        return "adopt"
    if gap < HOLD_GAP or count <= REJECT_MAX_COUNT:
        return "reject"
    return "hold"


def main() -> int:
    sheet = {}
    with (EXP_DIR / "blind_sheet.csv").open() as f:
        for row in csv.DictReader(r for r in f if not r.startswith("#")):
            sheet[row["review_id"]] = row["verdict"].strip()

    key = json.loads((EXP_DIR / "key" / "assignment_key.json").read_text())["items"]
    groups = score_groups(sheet, key)
    s, r = groups["score"], groups["random"]
    decision = decide(s, r)

    # 보조: S그룹 버킷 커버리지 + verdict 분포 (§4)
    dist = {g: {} for g in groups}
    buckets = set()
    for item in key:
        v = sheet[item["review_id"]]
        dist[item["group"]][v] = dist[item["group"]].get(v, 0) + 1
        if item["group"] == "score":
            buckets.add(tuple(item["bucket"]))

    result = {
        "groups": groups, "verdict_dist": dist,
        "gap_pp": round((s["informative_rate"] - r["informative_rate"]) * 100, 1),
        "score_bucket_coverage": len(buckets),
        "decision": decision,
    }
    (EXP_DIR / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
