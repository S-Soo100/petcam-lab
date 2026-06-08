"""eval-0608 등록 정합성 가드 (read-only) — 203 통합 평가셋 검증.

2026-06-08 159 동결 해제 → 203 단일 운영. 이 스크립트는 등록/로더가 일관된지 확인:
  load_eval_set()=203, load_eval_set_0608()=44, 0608 ⊆ 203, 159 부분집합 = 203−44.

실행: PYTHONPATH=. uv run python scripts/verify_eval0608.py
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.eval_vlm_worker_regression import load_eval_set, load_eval_set_0608  # noqa: E402

load_dotenv(REPO / ".env")
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

print("=" * 58)
print("eval-0608 등록 검증 (203 통합 운영)")
print("=" * 58)

cc = sb.table("camera_clips").select("id", count="exact").execute().count
bl = sb.table("behavior_logs").select("id", count="exact").eq("source", "human").execute().count
print(f"camera_clips 총           = {cc}   (203 기대)")
print(f"behavior_logs human 총    = {bl}   (203 기대)")

allset = load_eval_set()
new = load_eval_set_0608()
a_ids = {t.clip_id for t in allset}
n_ids = {t.clip_id for t in new}
legacy159 = len(a_ids - n_ids)

print()
print(f"load_eval_set()       = {len(allset):3d}  {'✅ 203 통합' if len(allset) == 203 else '❌ 203 아님'}")
print(f"load_eval_set_0608()  = {len(new):3d}  {'✅ 44' if len(new) == 44 else '❌ 44 아님'}")
print(f"0608 ⊆ 전체            = {'✅' if n_ids <= a_ids else '❌ 누락!'}  (44가 203 안에 포함)")
print(f"159 부분집합 = 203−44  = {legacy159:3d}  {'✅ 복원 가능(v3.5 비교용)' if legacy159 == 159 else '❌'}")

print()
print("eval-0608(44) GT 분포:")
dist = Counter(t.gt_action for t in new)
# 2961 GT 정정(hand_feeding→eating_paste, blind 평가가 발견) 반영: paste 9→10, hand_feeding 14→13
expect = {"drinking": 9, "eating_paste": 10, "eating_prey": 11, "hand_feeding": 13, "moving": 1}
for k in sorted(dist):
    mark = "✅" if dist[k] == expect.get(k) else "❌"
    print(f"  {k:14s} {dist[k]:2d}  {mark} (기대 {expect.get(k)})")
print(f"  species 샘플: {new[0].species_id} (crested-gecko 기대)")

ok = (
    len(allset) == 203
    and len(new) == 44
    and n_ids <= a_ids
    and legacy159 == 159
    and dict(dist) == expect
)
print()
print("=" * 58)
print("종합:", "✅ 전부 통과" if ok else "❌ 실패 — 위 항목 확인")
