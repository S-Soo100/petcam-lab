"""159건 raw vs post-filter final 정확도 비교 + 5-카테고리 분석.

스펙: specs/feature-vlm-feeding-postfilter.md §2.4

입력:
  - v3.5-zeroshot.jsonl (raw 159건, Flash)
  - dish-zeroshot.jsonl  (Flash router 39건, dish + licking)
  - Supabase behavior_logs (human GT)

출력 (콘솔):
  1) raw vs final 전체 정확도 (회귀 가드: final ≥ 85.5% — 정정 2026-05-02, 기존 86.2%는 오기재)
  2) 5-카테고리 (held-correct / recovered / broken / still-wrong)
  3) 클래스별 정확도
  4) post-filter 동작 추적 (39건 raw→final 변화)
"""
import os
import json
from collections import Counter
from pathlib import Path
from supabase import create_client
from dotenv import load_dotenv

from postfilter import apply_dish_postfilter, FEED_CLASSES

load_dotenv("/Users/baek/petcam-lab/web/.env.local")
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

ROOT = Path(__file__).resolve().parent
RAW_PATH = ROOT / "v3.5-zeroshot.jsonl"
DISH_PATH = ROOT / "dish-zeroshot.jsonl"

# v3.5 평가 매핑 (analyze-v35-full.py와 동일 — donts/vlm.md 룰 6, 회귀 가드 일치성)
HIDING_MERGE = {"hiding": "moving"}


def load_jsonl(p: Path) -> dict[str, dict]:
    out = {}
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            if r.get("ok"):
                out[r["clip_id"]] = r
        except json.JSONDecodeError:
            pass
    return out


def all_rows(table: str, sel: str, **filters) -> list[dict]:
    out, off = [], 0
    while True:
        q = sb.table(table).select(sel).order("created_at")
        for k, v in filters.items():
            q = q.eq(k, v)
        rows = q.range(off, off + 999).execute().data
        if not rows:
            break
        out.extend(rows)
        if len(rows) < 1000:
            break
        off += 1000
    return out


def merge_label(label: str, *maps) -> str:
    out = label
    for m in maps:
        out = m.get(out, out)
    return out


def main() -> None:
    raw = load_jsonl(RAW_PATH)
    dish = load_jsonl(DISH_PATH)

    human = all_rows("behavior_logs", "clip_id, action, notes", source="human")
    gt = {r["clip_id"]: r["action"] for r in human}

    targets = sorted(set(gt) & set(raw))
    print(f"v3.5 raw: {len(raw)} / GT 보유: {len(gt)} / 평가 대상: {len(targets)}")
    print(f"dish router 결과: {len(dish)}/39 (router 호출 대상은 합집합 39건)\n")

    # final 계산 — postfilter.apply_dish_postfilter(raw, dish, licking)
    finals: dict[str, str] = {}
    for cid in targets:
        r = raw[cid]["action"]
        if cid in dish:
            d = dish[cid].get("dish_present")
            l = dish[cid].get("licking_behavior")
            finals[cid] = apply_dish_postfilter(r, d, l)
        else:
            finals[cid] = r  # router 호출 대상 아님 또는 미호출

    # 정확도 (hiding→moving 매핑 적용 — analyze-v35-full.py와 일치)
    correct_raw = sum(1 for c in targets
                      if merge_label(gt[c], HIDING_MERGE) == raw[c]["action"])
    correct_final = sum(1 for c in targets
                        if merge_label(gt[c], HIDING_MERGE) == finals[c])

    n = len(targets)
    floor = 0.855 * n  # 락인 floor (정정 2026-05-02 — 기존 0.862는 잘못된 수치, portable 자기충족 검증에서 발견)
    print("=" * 60)
    print("== 전체 정확도 (159건, hiding→moving 매핑 적용) ==")
    print(f"  raw   : {correct_raw}/{n} = {correct_raw/n*100:.1f}%")
    print(f"  final : {correct_final}/{n} = {correct_final/n*100:.1f}%  "
          f"({'+' if correct_final >= correct_raw else ''}{correct_final - correct_raw}건)")
    print(f"  floor : 85.5% ({floor:.0f}건) — {'✅ 통과' if correct_final >= floor else '❌ 미달, 채택 X'}")
    print("=" * 60)
    print()

    # 5-카테고리 (raw vs final)
    cat: dict[str, list[str]] = {
        "held-correct": [], "recovered": [], "broken": [], "still-wrong": []
    }
    for cid in targets:
        g = merge_label(gt[cid], HIDING_MERGE)
        ok_raw = (raw[cid]["action"] == g)
        ok_final = (finals[cid] == g)
        if ok_raw and ok_final:
            cat["held-correct"].append(cid)
        elif (not ok_raw) and ok_final:
            cat["recovered"].append(cid)
        elif ok_raw and (not ok_final):
            cat["broken"].append(cid)
        else:
            cat["still-wrong"].append(cid)

    print("== 5-카테고리 (raw → final) ==")
    print(f"  held-correct : {len(cat['held-correct'])}")
    print(f"  recovered    : {len(cat['recovered'])}  ← post-filter가 살린 케이스")
    print(f"  broken       : {len(cat['broken'])}    ← post-filter가 망친 케이스 (회귀 가드 점검 대상)")
    print(f"  still-wrong  : {len(cat['still-wrong'])}")
    print(f"  recovered > broken : {'✅' if len(cat['recovered']) > len(cat['broken']) else '❌'}")
    print()

    # broken 상세 (있으면 즉시 분석)
    if cat["broken"]:
        print("== broken 상세 ==")
        for cid in cat["broken"]:
            g = merge_label(gt[cid], HIDING_MERGE)
            r = raw[cid]["action"]
            f = finals[cid]
            d = dish.get(cid, {})
            print(f"  {cid[:8]}  GT={g:13s}  raw={r:13s} → final={f:13s}  "
                  f"(dish={d.get('dish_present')}, lick={d.get('licking_behavior')})")
        print()

    # recovered 상세
    if cat["recovered"]:
        print("== recovered 상세 ==")
        for cid in cat["recovered"]:
            g = merge_label(gt[cid], HIDING_MERGE)
            r = raw[cid]["action"]
            f = finals[cid]
            d = dish.get(cid, {})
            print(f"  {cid[:8]}  GT={g:13s}  raw={r:13s} → final={f:13s}  "
                  f"(dish={d.get('dish_present')}, lick={d.get('licking_behavior')})")
        print()

    # 클래스별 정확도
    gt_dist = Counter(merge_label(gt[c], HIDING_MERGE) for c in targets)
    print(f"== 클래스별 정확도 (159건) ==")
    print(f"{'class':14s} {'n':>4}  {'raw':>9}  {'final':>9}  diff")
    for cls, k in gt_dist.most_common():
        c_raw = sum(1 for c in targets
                    if merge_label(gt[c], HIDING_MERGE) == cls
                    and raw[c]["action"] == cls)
        c_fin = sum(1 for c in targets
                    if merge_label(gt[c], HIDING_MERGE) == cls
                    and finals[c] == cls)
        diff = f"{'+' if c_fin > c_raw else ''}{c_fin - c_raw}" if c_fin != c_raw else ""
        print(f"{cls:14s} {k:4d}  {c_raw:5d}/{k:3d}  {c_fin:5d}/{k:3d}  {diff}")
    print()

    # post-filter 동작 추적 (39건 dish 호출 결과만)
    if dish:
        print("== post-filter 동작 추적 (router 호출 클립) ==")
        changed = [c for c in dish if c in raw and raw[c]["action"] != finals.get(c, raw[c]["action"])]
        kept = [c for c in dish if c in raw and raw[c]["action"] == finals.get(c, raw[c]["action"])]
        print(f"  변경 {len(changed)}건 / 유지 {len(kept)}건\n")
        for cid in changed[:30]:
            g = merge_label(gt[cid], HIDING_MERGE) if cid in gt else "?"
            r = raw[cid]["action"]
            f = finals[cid]
            d = dish[cid]
            ok_before = "✓" if r == g else "✗"
            ok_after = "✓" if f == g else "✗"
            print(f"  {cid[:8]}  GT={g:13s}  raw={r:13s} {ok_before} → final={f:13s} {ok_after}  "
                  f"(dish={d.get('dish_present')}, lick={d.get('licking_behavior')})")


if __name__ == "__main__":
    main()
