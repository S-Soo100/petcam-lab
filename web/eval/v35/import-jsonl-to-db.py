"""v3.5 jsonl 159건 중 vlm_model='gemini-2.5-flash-zeroshot-v3.5' 명시 INSERT 안 된 건 모두 import.

- 안전: INSERT only (기존 row mutate 없음, last-wins 메커니즘으로 v3.5 결과가 최신으로 잡힘).
- 멱등: 이미 v3.5 명시로 있는 행은 SKIP.
- 롤백: `notes='import-from-jsonl-v3.5'` 표식 → `DELETE WHERE notes='...'`.

배경:
  DB `behavior_logs.vlm_model`에 'gemini-2.5-flash' (버전 미상) 라벨 401건이 있고,
  그 중 jsonl 159건과 겹치는 88건의 last-wins가 v3.5 결과와 다른 경우 발견 (18/88).
  이는 v3.6/v3.7 등 후속 라운드가 같은 클립을 재라벨하면서 v3.5 결과를 덮어쓴 것.
  159건 전체를 v3.5 명시 라벨로 추가 INSERT → last-wins로 v3.5가 잡힘.

확인:
  실행 전 dry-run 모드 = INSERT 후보만 출력.
  실제 INSERT는 --apply 플래그.

연관:
  - /results 페이지 model 필터 (vlm_model='gemini-2.5-flash-zeroshot-v3.5')
  - specs/feature-vlm-feeding-merge-ux.md — UI 매핑은 raw 보존
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from supabase import create_client
from dotenv import load_dotenv

load_dotenv("/Users/baek/petcam-lab/web/.env.local")
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


V35_MODEL = "gemini-2.5-flash-zeroshot-v3.5"


def fetch_existing_v35_clips() -> set[str]:
    """v3.5 명시 라벨이 이미 있는 clip_id."""
    out, off = set(), 0
    while True:
        rows = (
            sb.table("behavior_logs")
            .select("clip_id")
            .eq("source", "vlm")
            .eq("vlm_model", V35_MODEL)
            .range(off, off + 999)
            .execute()
            .data
        )
        if not rows:
            break
        out.update(r["clip_id"] for r in rows)
        if len(rows) < 1000:
            break
        off += 1000
    return out


def main() -> None:
    apply = "--apply" in sys.argv

    jp = Path("/tmp/v3.5-zeroshot.jsonl")
    if not jp.exists():
        jp = Path(__file__).parent / "v3.5-zeroshot.jsonl"

    v35: dict[str, dict] = {}
    for line in jp.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            if r.get("ok"):
                v35[r["clip_id"]] = r
        except json.JSONDecodeError:
            pass

    existing = fetch_existing_v35_clips()
    missing = [cid for cid in v35 if cid not in existing]

    print(f"jsonl: {len(v35)}건")
    print(f"DB vlm v3.5 명시 기존: {len(existing)}건")
    print(f"누락 (INSERT 후보): {len(missing)}건")
    print()

    if not missing:
        print("누락 없음 — 종료.")
        return

    rows = [
        {
            "clip_id": cid,
            "action": v35[cid]["action"],
            "source": "vlm",
            "confidence": v35[cid].get("confidence"),
            "reasoning": v35[cid].get("reasoning"),
            "vlm_model": v35[cid].get("model"),
            "notes": "import-from-jsonl-v3.5",
        }
        for cid in missing
    ]

    if not apply:
        print("DRY RUN — INSERT할 행 sample 3건:")
        for r in rows[:3]:
            print(f"  clip_id    : {r['clip_id']}")
            print(f"  action     : {r['action']}")
            print(f"  confidence : {r['confidence']}")
            print(f"  vlm_model  : {r['vlm_model']}")
            print()
        print("실행: uv run python eval/v35/import-jsonl-to-db.py --apply")
        return

    print(f"{len(rows)}건 INSERT 진행...")
    # batched insert (Supabase 1000 limit)
    BATCH = 100
    inserted = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        sb.table("behavior_logs").insert(chunk).execute()
        inserted += len(chunk)
        print(f"  {inserted}/{len(rows)}")
    print()
    print(f"완료: {inserted}건 INSERT 됨.")
    print()
    print("롤백 시:")
    print("  DELETE FROM behavior_logs WHERE notes = 'import-from-jsonl-v3.5'")


if __name__ == "__main__":
    main()
