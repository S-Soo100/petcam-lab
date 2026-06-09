"""GT 정정 batch 적용 (로컬: dataset-203 파일명 + manifest.csv). 임시.

DB(behavior_logs)는 별도 스크립트. 7d9b9e8e 는 편집 영상이라 삭제(203→202).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

DS = Path("/Users/baek/petcam-lab/storage/dataset-203")
APPLY = "--apply" in sys.argv

# clip8 → 새 GT (None = 삭제)
CORR: dict[str, str | None] = {
    "69c4badd": "hand_feeding",   # 스푼 급여 (파일명 이미 수정됨)
    "ea36897b": "hand_feeding",   # 손가락 곤충 급여 (파일명 이미 수정됨)
    "458e8aa7": "moving",         # 실제 moving (GT 오류)
    "e0e38e0c": "hand_feeding",   # 집게로 귀뚜라미 급여 (GT 오류)
    "556a7bfe": "moving",         # hiding 폐기 → moving
    "8899146c": "moving",
    "e07f9b00": "moving",
    "7d9b9e8e": None,             # 편집 영상 → 삭제
    # 2차 (2026-06-09) drinking GT 재검토 — owner 영상 직접 확인. cam-motion 4건 실제 moving.
    "ff1ecb03": "moving",         # owner: "애매해서 drinking 라벨했던 것" — moving 맞음
    "05da625c": "moving",         # 물통 앞 아래·중앙·위 핥지만 drinking 아닐 가능성 (owner 판단)
    "2420abd8": "moving",         # 동일
    "987c7b5d": "moving",         # 동일
}

rows = list(csv.DictReader(open(DS / "manifest.csv")))
fields = rows[0].keys()
out_rows = []
actions = []

for r in rows:
    c8 = r["clip_id"][:8]
    if c8 not in CORR:
        out_rows.append(r)
        continue
    new_gt = CORR[c8]
    # 실제 파일 찾기 (사용자가 일부 이미 rename 했으므로 glob)
    matches = [m for m in DS.glob(f"*{c8}*") if m.suffix.lower() in (".mp4", ".mov")]
    cur = matches[0] if matches else None

    if new_gt is None:  # 삭제
        actions.append(f"DELETE  {cur.name if cur else '(파일없음)'}  + manifest 행 제거")
        if APPLY and cur:
            cur.unlink()
        continue  # manifest 에서도 제외

    ext = (cur.suffix.lower().lstrip(".") if cur else r["filename"].rsplit(".", 1)[-1])
    new_fn = f"{new_gt}__{r['pred_v361']}__{c8}.{ext}"
    new_match = "Y" if new_gt == r["pred_v361"] else ("na" if r["pred_v361"] == "na" else "N")
    actions.append(f"GT {r['gt']:12s}→{new_gt:12s}  {cur.name if cur else '?':45s}→ {new_fn}  match={new_match}")
    if APPLY:
        if cur and cur.name != new_fn:
            cur.rename(DS / new_fn)
        r["gt"], r["filename"], r["match"] = new_gt, new_fn, new_match
    out_rows.append(r)

print(f"{'APPLY' if APPLY else 'DRY-RUN'} — {len(actions)}건 처리, manifest {len(rows)}→{len(out_rows)}행")
for a in actions:
    print("  " + a)

if APPLY:
    with (DS / "manifest.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n✅ manifest.csv 재작성 ({len(out_rows)}행)")
else:
    print("\n검수 후: --apply")
