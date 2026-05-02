"""jsonl 159건 vs DB vlm 199건 — 어느 71건이 DB에 없는지 식별.

목적: /results 페이지가 86.2% 안 나오는 진짜 원인이
      'GT 라벨링 부족'이 아니라 'DB import 갭'임을 명시.
"""
import os
import json
from pathlib import Path
from supabase import create_client
from dotenv import load_dotenv

load_dotenv("/Users/baek/petcam-lab/web/.env.local")
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def fetch_all(source: str) -> list[dict]:
    out, off = [], 0
    while True:
        rows = (
            sb.table("behavior_logs")
            .select("clip_id, action, created_at")
            .eq("source", source)
            .order("created_at")
            .range(off, off + 999)
            .execute()
            .data
        )
        if not rows:
            break
        out.extend(rows)
        if len(rows) < 1000:
            break
        off += 1000
    return out


def main() -> None:
    # jsonl SOT
    jp = Path("/tmp/v3.5-zeroshot.jsonl")
    if not jp.exists():
        jp = Path(__file__).parent / "v3.5-zeroshot.jsonl"
    v35: dict[str, str] = {}
    for line in jp.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            if r.get("ok"):
                v35[r["clip_id"]] = r["action"]
        except json.JSONDecodeError:
            pass

    # DB last-wins
    vlm = fetch_all("vlm")
    v_map: dict[str, str] = {}
    for r in vlm:
        v_map[r["clip_id"]] = r["action"]

    # 갭 계산
    in_jsonl_not_db = set(v35) - set(v_map)
    in_db_not_jsonl = set(v_map) - set(v35)
    in_both = set(v35) & set(v_map)

    print(f"jsonl: {len(v35)}건")
    print(f"DB vlm last-wins: {len(v_map)}건")
    print(f"교집합: {len(in_both)}건")
    print(f"jsonl 있지만 DB vlm 없음: {len(in_jsonl_not_db)}건  (← DB import 필요)")
    print(f"DB vlm 있지만 jsonl 없음: {len(in_db_not_jsonl)}건  (← 다른 라운드 잉여)")
    print()

    print("== jsonl 있지만 DB 없는 71건 (action 분포) ==")
    from collections import Counter
    miss_actions = Counter(v35[c] for c in in_jsonl_not_db)
    for a, n in miss_actions.most_common():
        print(f"  {a:14s}  {n}건")
    print()

    print("== sample 5건 (clip_id, jsonl action) ==")
    for cid in sorted(in_jsonl_not_db)[:5]:
        print(f"  {cid}  →  {v35[cid]}")


if __name__ == "__main__":
    main()
