"""rba-worker 핸드오버 GT 정정 6건을 behavior_logs(source=human) 에 sync (audit/재현용).

feature-hand-feeding-ood-label.md "GT 정정 6건 sync". behavior_labels 는 비어있어
(옛 PoC 경로 데이터) behavior_logs 의 human row 만 UPDATE. old action 은 notes 에
audit 기록. 2026-06-07 적용 완료 (멱등 — 이미 정정된 row 는 skip).

실행:
    PYTHONPATH=. uv run python scripts/sync_handoff_gt.py           # dry-run (변경 안 함)
    PYTHONPATH=. uv run python scripts/sync_handoff_gt.py --apply    # 실제 UPDATE
"""

from __future__ import annotations

import sys

from backend.supabase_client import get_supabase_client

# short clip_id -> (정정 후 action, 사유). REPORT §2.5.1 audit trail.
CORRECTIONS: dict[str, tuple[str, str]] = {
    "27c5b14f": ("hand_feeding", "사람/도구 frame 등장 OOD"),
    "65b57205": ("moving", "paste 섭취 없음 단순 이동"),
    "9af1ba2e": ("hand_feeding", "사람/도구 frame 등장 OOD"),
    "b8317750": ("hand_feeding", "사람/도구 frame 등장 OOD"),
    "cc0c1d04": ("hand_feeding", "사람/도구 frame 등장 OOD"),
    "ce5fee73": ("hand_feeding", "사람/도구 frame 등장 OOD"),
}


def main() -> int:
    apply = "--apply" in sys.argv
    sb = get_supabase_client()

    rows = sb.table("camera_clips").select("id").limit(100000).execute().data
    short_to_full = {r["id"][:8]: r["id"] for r in rows if r["id"][:8] in CORRECTIONS}

    print(f"mode: {'APPLY (실제 UPDATE)' if apply else 'DRY-RUN (변경 안 함)'}\n")
    would = 0
    for short, (new_action, reason) in CORRECTIONS.items():
        full = short_to_full.get(short)
        if not full:
            print(f"[{short}] NOT FOUND — skip")
            continue
        humans = (
            sb.table("behavior_logs")
            .select("id,action,notes")
            .eq("clip_id", full)
            .eq("source", "human")
            .execute()
            .data
        )
        if not humans:
            print(f"[{short}] human GT row 없음 — skip")
            continue
        for row in humans:
            old = row["action"]
            if old == new_action:
                print(f"[{short}] id={row['id']} 이미 {new_action} — skip")
                continue
            audit = f"[GT정정 rba-worker HITL 2026-06-06: {old}→{new_action} ({reason})]"
            new_notes = ((row.get("notes") or "").strip() + " " + audit).strip()
            print(f"[{short}] id={row['id']}  {old} → {new_action}")
            would += 1
            if apply:
                sb.table("behavior_logs").update(
                    {"action": new_action, "notes": new_notes}
                ).eq("id", row["id"]).execute()

    verb = "UPDATED" if apply else "WOULD UPDATE"
    print(f"\n{verb}: {would} row(s)")
    if not apply and would:
        print("실제 적용하려면: --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
