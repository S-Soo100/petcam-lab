"""GT 정정 2차 batch (2026-06-09 결정, DB sync 2026-06-12) → behavior_logs(source=human). 임시.

drinking 가설2 검증 중 owner 영상 직접 확인으로 cam-motion drinking 4건 → 실제 moving 판정.
로컬(dataset-203 파일명+manifest)은 _apply_gt_corrections.py 로 0609 적용 완료 — DB만 남아 있었음
(당시 Gemini key 차단으로 대기). _sync_gt_corrections_0609.py 패턴 재사용 (notes audit, 멱등).

실행:
    PYTHONPATH=. uv run python scripts/_sync_gt_corrections_0609_r2.py          # dry-run
    PYTHONPATH=. uv run python scripts/_sync_gt_corrections_0609_r2.py --apply  # 실제 적용
"""
from __future__ import annotations

import sys

from backend.supabase_client import get_supabase_client

# clip8 → (새 action, 사유)
CORRECTIONS: dict[str, tuple[str, str]] = {
    "ff1ecb03": ("moving", "owner 영상 확인: 애매해서 drinking 라벨했던 것 — 실제 moving"),
    "05da625c": ("moving", "owner 영상 확인: 물 없는 곳 핥기(chemoreception 경계) — drinking 아님"),
    "2420abd8": ("moving", "owner 영상 확인: 물 없는 곳 핥기(chemoreception 경계) — drinking 아님"),
    "987c7b5d": ("moving", "owner 영상 확인: 물 없는 곳 핥기(chemoreception 경계) — drinking 아님"),
}


def main() -> int:
    apply = "--apply" in sys.argv
    sb = get_supabase_client()

    rows = sb.table("camera_clips").select("id").limit(100000).execute().data
    short_to_full = {r["id"][:8]: r["id"] for r in rows if r["id"][:8] in CORRECTIONS}

    print(f"mode: {'APPLY' if apply else 'DRY-RUN'}\n--- UPDATE ---")
    upd = 0
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
            audit = f"[GT정정 2026-06-09 2차: {old}→{new_action} ({reason})]"
            new_notes = ((row.get("notes") or "").strip() + " " + audit).strip()
            print(f"[{short}] {old} → {new_action}")
            upd += 1
            if apply:
                sb.table("behavior_logs").update(
                    {"action": new_action, "notes": new_notes}
                ).eq("id", row["id"]).execute()

    verb = "applied" if apply else "would"
    print(f"\n{verb}: UPDATE {upd}")
    if not apply and upd:
        print("실제 적용: --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
