"""GT 라벨 export — Supabase → data/gt-159.jsonl.

본 레포 운영자만 실행 (DB 접근 권한 필요). 외부 에이전트는 export된 jsonl을 받아서 사용.

실행:
  cd /Users/baek/petcam-lab/web
  uv run python ../vlm-classifier-portable/data/_export-gt.py

연관:
  - data/eval-159.jsonl — 모델 출력 (GT 비교 대상)
  - data/gt-159.jsonl   — 본 스크립트 출력
"""
from __future__ import annotations

import os
import json
from pathlib import Path
from supabase import create_client
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv("/Users/baek/petcam-lab/web/.env.local")
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def main() -> None:
    eval_path = ROOT / "data" / "eval-159.jsonl"
    out_path = ROOT / "data" / "gt-159.jsonl"

    target_clips: set[str] = set()
    for line in eval_path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("ok"):
            target_clips.add(r["clip_id"])
    print(f"target clips (from eval-159.jsonl): {len(target_clips)}")

    rows: list[dict] = []
    off = 0
    while True:
        chunk = (
            sb.table("behavior_logs")
            .select("clip_id, action, created_at, notes")
            .eq("source", "human")
            .order("created_at")
            .range(off, off + 999)
            .execute()
            .data
        )
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        off += 1000

    # last-wins per clip (DB iteration order = created_at asc)
    last: dict[str, dict] = {}
    for r in rows:
        if r["clip_id"] in target_clips:
            last[r["clip_id"]] = {
                "gt_action": r["action"],
                "notes": r.get("notes"),
                "labeled_at": r["created_at"],
            }

    missing = target_clips - set(last)
    print(f"GT 매칭: {len(last)}/{len(target_clips)}")
    if missing:
        print(f"WARNING: GT 없는 clip_id {len(missing)}건")
        for c in sorted(missing)[:5]:
            print(f"  {c}")

    with out_path.open("w") as f:
        for cid in sorted(target_clips):
            if cid in last:
                f.write(json.dumps({"clip_id": cid, **last[cid]}, ensure_ascii=False) + "\n")

    print(f"export 완료: {out_path}")


if __name__ == "__main__":
    main()
