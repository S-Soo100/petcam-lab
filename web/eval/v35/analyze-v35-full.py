"""v3.5 zero-shot 159건 분석.

출력:
1) v3.4 vs v3.5 5-카테고리 (held-correct / recovered / broken / still-wrong / missing)
2) Raw 정확도 vs feeding 통합 정확도
3) 클래스별 정확도 (raw + feeding 통합)
4) 잔존 오답 패턴 Top-N
5) 신규 52건 정확도

feeding 통합 매핑 (Round 2 결정 — UX 레이어에서만):
  drinking     ≡ feeding
  eating_paste ≡ feeding
  나머지 그대로
"""
import os
import json
from collections import Counter, defaultdict
from pathlib import Path
from supabase import create_client
from dotenv import load_dotenv

load_dotenv("/Users/baek/petcam-lab/web/.env.local")
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

V35_PATH = Path("/tmp/v3.5-zeroshot.jsonl")
V34_PATH = Path("/tmp/v3.4-zeroshot.jsonl")


def load_jsonl(p: Path) -> dict:
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


def all_rows(table, sel, **filters):
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


# Round 2 메모리 정공법: drinking + eating_paste → feeding
FEEDING_MERGE = {"drinking": "feeding", "eating_paste": "feeding"}
HIDING_MERGE = {"hiding": "moving"}  # v3.5 hiding 폐기 (memory feedback_vlm_class_design)


def merge_label(label: str, *maps) -> str:
    out = label
    for m in maps:
        out = m.get(out, out)
    return out


def main():
    v35 = load_jsonl(V35_PATH)
    v34 = load_jsonl(V34_PATH)

    human = all_rows("behavior_logs", "clip_id, action, notes, created_at", source="human")
    gt_raw = {r["clip_id"]: r["action"] for r in human}
    gt_notes = {r["clip_id"]: (r.get("notes") or "")[:80] for r in human}

    # 평가 대상: GT가 있는 v3.5 결과
    targets = sorted(set(gt_raw) & set(v35))
    print(f"v3.5 결과 수: {len(v35)} / GT 보유: {len(gt_raw)} / 평가 대상: {len(targets)}\n")

    # Raw 정확도
    correct_raw = sum(1 for c in targets if gt_raw[c] == v35[c]["action"])

    # Hiding은 v3.5에선 moving에 통합됨 (raw GT는 그대로)
    correct_hiding_merged = sum(
        1 for c in targets
        if merge_label(gt_raw[c], HIDING_MERGE) == v35[c]["action"]
    )

    # Feeding 통합 (UX 레이어): drinking ≡ eating_paste, 나머지 그대로
    correct_feeding = sum(
        1 for c in targets
        if merge_label(gt_raw[c], HIDING_MERGE, FEEDING_MERGE)
        == merge_label(v35[c]["action"], FEEDING_MERGE)
    )

    print("== 전체 정확도 (159건) ==")
    print(f"  raw:                {correct_raw}/{len(targets)} = {correct_raw/len(targets)*100:.1f}%")
    print(f"  hiding→moving 매핑:  {correct_hiding_merged}/{len(targets)} = {correct_hiding_merged/len(targets)*100:.1f}%")
    print(f"  + feeding 통합:     {correct_feeding}/{len(targets)} = {correct_feeding/len(targets)*100:.1f}%")
    print()

    # 신규 52건 (inbox/0430)
    new_ids = set(c["clip_id"] for c in human
                  if "inbox/0430" in (c.get("notes") or ""))
    new_targets = [c for c in targets if c in new_ids]
    new_correct_raw = sum(1 for c in new_targets if gt_raw[c] == v35[c]["action"])
    new_correct_feed = sum(
        1 for c in new_targets
        if merge_label(gt_raw[c], HIDING_MERGE, FEEDING_MERGE)
        == merge_label(v35[c]["action"], FEEDING_MERGE)
    )
    print(f"== 신규 52건 (inbox/0430) ==")
    print(f"  raw:           {new_correct_raw}/{len(new_targets)} = {new_correct_raw/len(new_targets)*100 if new_targets else 0:.1f}%")
    print(f"  feeding 통합:  {new_correct_feed}/{len(new_targets)} = {new_correct_feed/len(new_targets)*100 if new_targets else 0:.1f}%")
    print()

    # v3.4 vs v3.5 5-카테고리 (overlap만)
    overlap = sorted(set(targets) & set(v34))
    cat = {"held-correct": [], "recovered": [], "broken": [], "still-wrong": []}
    for cid in overlap:
        g = merge_label(gt_raw[cid], HIDING_MERGE)
        v3 = v34[cid]["action"]
        v5 = v35[cid]["action"]
        ok3, ok5 = (g == v3), (g == v5)
        if ok3 and ok5: cat["held-correct"].append(cid)
        elif (not ok3) and ok5: cat["recovered"].append(cid)
        elif ok3 and (not ok5): cat["broken"].append(cid)
        else: cat["still-wrong"].append(cid)
    missing = [c for c in targets if c not in set(v34)]

    print(f"== v3.4 vs v3.5 5-카테고리 (overlap {len(overlap)}건) ==")
    print(f"  held-correct: {len(cat['held-correct'])}")
    print(f"  recovered:    {len(cat['recovered'])}")
    print(f"  broken:       {len(cat['broken'])}")
    print(f"  still-wrong:  {len(cat['still-wrong'])}")
    print(f"  missing:      {len(missing)}건 (v3.4 미실행. 신규 inbox/0430 + 어제 보충 inbox 포함)")
    missing_correct = sum(1 for c in missing if merge_label(gt_raw[c], HIDING_MERGE) == v35[c]["action"])
    print(f"    그중 정답: {missing_correct}/{len(missing)} = {missing_correct/len(missing)*100 if missing else 0:.1f}%")
    print()

    # 클래스별 정확도 (raw + feeding 통합)
    gt_dist = Counter(merge_label(gt_raw[c], HIDING_MERGE) for c in targets)
    print(f"== 클래스별 정확도 (159건, raw / feeding 통합) ==")
    print(f"{'class':14s} {'n':>4} {'raw':>8} {'feed':>8}  비교")
    for cls, n in gt_dist.most_common():
        c_raw = sum(1 for c in targets
                    if merge_label(gt_raw[c], HIDING_MERGE) == cls
                    and v35[c]["action"] == cls)
        c_feed = sum(1 for c in targets
                     if merge_label(gt_raw[c], HIDING_MERGE, FEEDING_MERGE)
                     == merge_label(cls, FEEDING_MERGE)
                     and merge_label(gt_raw[c], HIDING_MERGE) == cls
                     and merge_label(v35[c]["action"], FEEDING_MERGE)
                     == merge_label(cls, FEEDING_MERGE))
        diff = ""
        if c_feed > c_raw:
            diff = f"  +{c_feed - c_raw}"
        print(f"{cls:14s} {n:4d} {c_raw:5d}/{n} {c_feed:5d}/{n} {diff}")
    print()

    # feeding 통합 카테고리 정확도 (drinking + eating_paste 합쳐서 본 정확도)
    feed_targets = [c for c in targets
                    if gt_raw[c] in ("drinking", "eating_paste")]
    feed_correct = sum(
        1 for c in feed_targets
        if v35[c]["action"] in ("drinking", "eating_paste")
    )
    print(f"== feeding 합쳐 본 정확도 ==")
    print(f"  drinking + eating_paste GT: {len(feed_targets)}건")
    print(f"  feeding 안에 들어온 예측: {feed_correct}/{len(feed_targets)} = {feed_correct/len(feed_targets)*100 if feed_targets else 0:.1f}%")
    feed_misses = [
        (c, gt_raw[c], v35[c]["action"], gt_notes.get(c, "")[:50])
        for c in feed_targets if v35[c]["action"] not in ("drinking", "eating_paste")
    ]
    if feed_misses:
        print(f"  feeding 밖으로 새는 케이스 ({len(feed_misses)}건):")
        for cid, g, p, n in feed_misses[:15]:
            print(f"    {cid[:8]}  GT={g:14s} → v35={p:14s}  ({n})")
    print()

    # 잔존 오답 Top 패턴
    wrong = [
        (gt_raw[c] if gt_raw[c] != "hiding" else "moving", v35[c]["action"])
        for c in targets
        if merge_label(gt_raw[c], HIDING_MERGE) != v35[c]["action"]
    ]
    print(f"== 잔존 오답 패턴 Top-10 ==")
    for (g, p), n in Counter(wrong).most_common(10):
        merged = " (feeding 통합 시 정답)" if (g in FEEDING_MERGE and p in FEEDING_MERGE) else ""
        print(f"  {g:14s} → {p:14s}  {n}건{merged}")


if __name__ == "__main__":
    main()
