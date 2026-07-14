"""사람 blind 판단(review_manifest.csv) vs detector(answer_key.json) 대조 → 지표 출력.

사람이 review_manifest.csv 의 human_judgment 를 다 채운 뒤 실행. TEST-SHEET §4~5 지표 계산.
UUID 는 clip_id(clip UUID)만 다루고 출력에도 앞 8자만 쓴다.

    python3 experiments/activity-preflight-0714/compare_preflight.py
"""
import csv
import json
from collections import Counter
from pathlib import Path

EXP = Path(__file__).resolve().parent
answer = {c["clip_id"]: c for c in json.loads((EXP / "answer_key.json").read_text())}

human: dict[str, str] = {}
with (EXP / "review_manifest.csv").open(encoding="utf-8") as f:
    for row in csv.DictReader(f):
        j = (row.get("human_judgment(absent/static/active/unclear)") or "").strip().lower()
        if j:
            human[row["clip_id"]] = j

judged = [cid for cid in answer if cid in human]
print(f"판단 완료 {len(judged)}/{len(answer)}")
if len(judged) < len(answer):
    print("⚠️ 미판단 clip 있음 — 전부 채운 뒤 다시 실행 권장")

det = {cid: answer[cid]["detector_decision"] for cid in judged}

# 1. false exclusion (최우선): 사람=active 인데 detector=exclude_*
fe_absent = [c for c in judged if human[c] == "active" and det[c] == "exclude_absent"]
fe_static = [c for c in judged if human[c] == "active" and det[c] == "exclude_static"]

# 2~3. precision
det_absent = [c for c in judged if det[c] == "exclude_absent"]
det_static = [c for c in judged if det[c] == "exclude_static"]
prec_absent = (sum(human[c] == "absent" for c in det_absent) / len(det_absent)) if det_absent else None
prec_static = (sum(human[c] == "static" for c in det_static) / len(det_static)) if det_static else None

# 4. active recall (참고)
human_active = [c for c in judged if human[c] == "active"]
active_recall = (sum(det[c] == "active" for c in human_active) / len(human_active)) if human_active else None


def pct(x):
    return "n/a" if x is None else f"{x*100:.0f}%"


print("\n=== 분포 ===")
print("detector:", dict(Counter(det.values())))
print("human   :", dict(Counter(human[c] for c in judged)))

print("\n=== 지표 (TEST-SHEET §4) ===")
print(f"false exclusion → absent: {len(fe_absent)}  static: {len(fe_static)}   (0 이어야 스위치 활성화 가능)")
print(f"exclude_absent precision: {pct(prec_absent)}  (n={len(det_absent)})")
print(f"exclude_static precision: {pct(prec_static)}  (n={len(det_static)})")
print(f"active recall(참고): {pct(active_recall)}  (n={len(human_active)})")

print("\n=== decision (TEST-SHEET §5·§7) ===")
ok_absent = (len(fe_absent) == 0) and (prec_absent is not None and prec_absent >= 0.90)
ok_static = (len(fe_static) == 0) and (prec_static is not None and prec_static >= 0.90)
print(f"exclude_absent 스위치: {'ADOPT(활성화 권장)' if ok_absent else 'HOLD/REJECT(비활성 유지)'}")
print(f"exclude_static 스위치: {'ADOPT(활성화 권장)' if ok_static else 'HOLD/REJECT(비활성 유지)'}")

print("\n=== discordant (사람≠detector, hard case) ===")
for c in judged:
    h, d = human[c], det[c]
    match = (h == "absent" and d == "exclude_absent") or (h == "static" and d == "exclude_static") \
        or (h == "active" and d == "active") or (d == "unknown")
    if not match:
        m = answer[c]["measurements"]
        print(f"  {c[:8]} human={h:7s} det={d:15s} reason={answer[c]['reason_code']:20s} "
              f"vr={m.get('visible_frame_ratio')} disp={m.get('max_bbox_center_disp')} "
              f"iou={m.get('min_bbox_iou')} flow={m.get('roi_flow_mag')} glob={m.get('global_bg_change')}")
