"""GT 정정 batch (2026-06-09) → behavior_logs(source=human) sync. 임시.

frames blind 평가 + 사용자 영상 확인으로 검출한 GT 오류 정정.
sync_handoff_gt.py 패턴 재사용 (notes audit, 멱등). 7d9b9e8e 는 편집 영상이라 human GT 삭제(평가셋 제외).

실행:
    PYTHONPATH=. uv run python scripts/_sync_gt_corrections_0609.py          # dry-run
    PYTHONPATH=. uv run python scripts/_sync_gt_corrections_0609.py --apply  # 실제 적용
"""
from __future__ import annotations

import sys

from backend.supabase_client import get_supabase_client

# clip8 → (새 action, 사유)
CORRECTIONS: dict[str, tuple[str, str]] = {
    "69c4badd": ("hand_feeding", "스푼으로 paste 급여 OOD (blind 5회 일치+사용자 영상 확인)"),
    "ea36897b": ("hand_feeding", "손가락으로 곤충 급여 OOD (사용자 영상 확인)"),
    "e0e38e0c": ("hand_feeding", "집게로 귀뚜라미 급여 OOD (사용자 영상 확인)"),
    "458e8aa7": ("moving", "prey 섭취 없음 단순 이동 GT오류 (사용자 영상 확인)"),
    "556a7bfe": ("moving", "hiding 클래스 폐기 → moving (사용자 결정)"),
    "8899146c": ("moving", "hiding 클래스 폐기 → moving (사용자 결정)"),
    "e07f9b00": ("moving", "hiding 클래스 폐기 → moving (사용자 결정)"),
}
# clip8 → 사유 (human GT row 삭제 = 평가셋 제외)
DELETIONS: dict[str, str] = {
    "7d9b9e8e": "편집 영상(여러 짧은 장면 짜깁기) 평가 부적합",
}


def main() -> int:
    apply = "--apply" in sys.argv
    sb = get_supabase_client()
    want = set(CORRECTIONS) | set(DELETIONS)

    rows = sb.table("camera_clips").select("id").limit(100000).execute().data
    short_to_full = {r["id"][:8]: r["id"] for r in rows if r["id"][:8] in want}

    print(f"mode: {'APPLY' if apply else 'DRY-RUN'}\n--- UPDATE ---")
    upd = dele = 0
    for short, (new_action, reason) in CORRECTIONS.items():
        full = short_to_full.get(short)
        if not full:
            print(f"[{short}] camera_clips NOT FOUND — skip")
            continue
        humans = (sb.table("behavior_logs").select("id,action,notes")
                  .eq("clip_id", full).eq("source", "human").execute().data)
        if not humans:
            print(f"[{short}] human GT row 없음 — skip")
            continue
        for row in humans:
            old = row["action"]
            if old == new_action:
                print(f"[{short}] 이미 {new_action} — skip")
                continue
            audit = f"[GT정정 2026-06-09: {old}→{new_action} ({reason})]"
            new_notes = ((row.get("notes") or "").strip() + " " + audit).strip()
            print(f"[{short}] {old} → {new_action}")
            upd += 1
            if apply:
                sb.table("behavior_logs").update(
                    {"action": new_action, "notes": new_notes}
                ).eq("id", row["id"]).execute()

    print("--- DELETE (human GT row) ---")
    for short, reason in DELETIONS.items():
        full = short_to_full.get(short)
        if not full:
            print(f"[{short}] camera_clips NOT FOUND — skip")
            continue
        humans = (sb.table("behavior_logs").select("id,action")
                  .eq("clip_id", full).eq("source", "human").execute().data)
        for row in humans:
            print(f"[{short}] DELETE human GT (action={row['action']}) — {reason}")
            dele += 1
            if apply:
                sb.table("behavior_logs").delete().eq("id", row["id"]).execute()

    verb = "applied" if apply else "would"
    print(f"\n{verb}: UPDATE {upd} / DELETE {dele}")
    if not apply and (upd or dele):
        print("실제 적용: --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
