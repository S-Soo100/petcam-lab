"""VLM 오답 진단: behavior_logs 의 GT(human) vs Gemini(vlm) 비교.

feature-hand-feeding-ood-label.md "오답 진단" — 비용 0 (DB만, 크레딧 불필요).
어디서·왜 틀리나 지도 → 영상 추가/모델 변경 가치 판정. 평가셋 변동 시 재진단에 재사용.

confidence 높은 오답 = "자신있게 틀림" = 시각 한계 의심 (영상이 헷갈림).
confidence 낮은 오답 = 모호/프롬프트 신호 부족 의심.

실행: PYTHONPATH=. uv run python scripts/diagnose_vlm_errors.py
"""

from __future__ import annotations

from collections import Counter, defaultdict

from backend.supabase_client import get_supabase_client

FEEDING_MERGE = {"drinking": "feeding", "eating_paste": "feeding"}
HIDING_MERGE = {"hiding": "moving"}


def merge(a: str, *maps: dict[str, str]) -> str:
    for m in maps:
        a = m.get(a, a)
    return a


def main() -> None:
    sb = get_supabase_client()
    rows = (
        sb.table("behavior_logs")
        .select("clip_id,action,source,confidence,reasoning")
        .limit(100000)
        .execute()
        .data
    )

    by_clip: dict[str, dict] = defaultdict(dict)
    for r in rows:
        src = r["source"]
        if src == "human":
            by_clip[r["clip_id"]]["gt"] = r["action"]
        elif src == "vlm":
            by_clip[r["clip_id"]]["vlm"] = r["action"]
            by_clip[r["clip_id"]]["conf"] = r.get("confidence")
            by_clip[r["clip_id"]]["reasoning"] = r.get("reasoning")

    pairs = {c: d for c, d in by_clip.items() if "gt" in d and "vlm" in d}
    n = len(pairs)
    gt_only = sum(1 for d in by_clip.values() if "gt" in d and "vlm" not in d)

    raw_correct = merged_correct = 0
    confusion: Counter = Counter()
    errors = []
    ood_errors = []  # GT=hand_feeding — v3.5 는 클래스 자체가 없어 구조적 오답
    by_gt: dict[str, dict[str, int]] = defaultdict(lambda: {"c": 0, "t": 0})

    for cid, d in pairs.items():
        gt, vlm = d["gt"], d["vlm"]
        gt_m = merge(gt, HIDING_MERGE, FEEDING_MERGE)
        vlm_m = merge(vlm, FEEDING_MERGE)
        by_gt[gt_m]["t"] += 1
        if gt == vlm:
            raw_correct += 1
        if gt_m == vlm_m:
            merged_correct += 1
            by_gt[gt_m]["c"] += 1
        else:
            rec = (cid[:8], gt, vlm, d.get("conf"), (d.get("reasoning") or "")[:95])
            if gt == "hand_feeding":
                ood_errors.append(rec)
            else:
                errors.append(rec)
                confusion[f"{gt_m:9s} → {vlm_m}"] += 1

    print("=" * 64)
    print(f"159건 GT(사람) vs Gemini v3.5(vlm) 진단")
    print("=" * 64)
    print(f"GT+vlm 페어: {n}  (GT만 있고 Gemini 답 없음: {gt_only})")
    print(f"raw 정확도     : {raw_correct}/{n} = {raw_correct / n:.1%}")
    print(f"feeding-merged : {merged_correct}/{n} = {merged_correct / n:.1%}")
    print()
    print("클래스별 정확도 (feeding-merged):")
    for k in sorted(by_gt, key=lambda x: -by_gt[x]["t"]):
        b = by_gt[k]
        print(f"  {k:9s} {b['c']:3d}/{b['t']:3d} = {b['c'] / b['t']:.0%}" if b["t"] else k)
    print()
    print("혼동 패턴 (어떤 행동을 무엇으로 틀리나, OOD 제외):")
    for k, v in confusion.most_common():
        print(f"  {v:2d}x  {k}")
    print()
    print(f"오답 상세 {len(errors)}건 (conf 높은 순 = 자신있게 틀림 = 시각 한계 의심):")
    for cid, gt, vlm, conf, rsn in sorted(errors, key=lambda x: -(x[3] or 0)):
        cs = "None" if conf is None else f"{conf:.2f}"
        print(f"  {cid} {gt:13s}→ {vlm:13s} conf={cs}")
        print(f"           └ {rsn}")
    print()
    print(f"OOD 오답 {len(ood_errors)}건 (GT=hand_feeding — v3.5 는 클래스 없음 → v3.6 가 풀 대상):")
    for cid, gt, vlm, conf, rsn in ood_errors:
        cs = "None" if conf is None else f"{conf:.2f}"
        print(f"  {cid} hand_feeding → {vlm:13s} conf={cs}")
        print(f"           └ {rsn}")


if __name__ == "__main__":
    main()
