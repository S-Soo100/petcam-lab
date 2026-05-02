"""/results 페이지 73.4% / 94건 진단.

비교 대상:
  - DB behavior_logs (source=human, vlm) last-wins per clip
  - /tmp/v3.5-zeroshot.jsonl 159건 평가셋 (analyze-v35-full.py 기준)
"""
import os
import json
from collections import Counter
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


def merge(a: str) -> str:
    if a in ("drinking", "eating_paste"):
        return "feeding"
    return a


def main() -> None:
    human = fetch_all("human")
    vlm = fetch_all("vlm")
    print(f"human rows total: {len(human)}")
    print(f"vlm rows total:   {len(vlm)}")

    # last-wins per clip (results/page.tsx 로직 동일 — 시간 오름차순 + Map.set로 마지막값 보존)
    h_map: dict[str, str] = {}
    for r in human:
        h_map[r["clip_id"]] = r["action"]
    v_map: dict[str, str] = {}
    for r in vlm:
        v_map[r["clip_id"]] = r["action"]
    print(f"human last-wins clips: {len(h_map)}")
    print(f"vlm   last-wins clips: {len(v_map)}")

    pairs = [(cid, h_map[cid], v_map[cid]) for cid in v_map if cid in h_map]
    print(f"pair (h ∩ v): {len(pairs)}")
    print()

    raw_match = sum(1 for _, g, v in pairs if g == v)
    merged_match = sum(1 for _, g, v in pairs if merge(g) == merge(v))
    n = len(pairs)
    print(f"DB pair 기준:")
    print(f"  raw           : {raw_match}/{n} = {raw_match/n*100:.1f}%")
    print(f"  feeding-merged: {merged_match}/{n} = {merged_match/n*100:.1f}%")
    print(f"  Δ (merged−raw): +{merged_match - raw_match}건")
    print()

    # 159건 평가셋 (jsonl) 기준 — 비교
    jp = Path("/tmp/v3.5-zeroshot.jsonl")
    if not jp.exists():
        jp = Path(__file__).parent / "v3.5-zeroshot.jsonl"
    if jp.exists():
        v35 = {}
        for line in jp.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                if r.get("ok"):
                    v35[r["clip_id"]] = r["action"]
            except json.JSONDecodeError:
                pass
        print(f"v3.5-zeroshot.jsonl: {len(v35)} 건")
        # human ∩ jsonl
        eval_pairs = [(cid, h_map[cid], v35[cid]) for cid in v35 if cid in h_map]
        print(f"평가셋 pair (h ∩ jsonl): {len(eval_pairs)}")
        if eval_pairs:
            r_m = sum(1 for _, g, v in eval_pairs if g == v)
            f_m = sum(1 for _, g, v in eval_pairs if merge(g) == merge(v))
            print(f"  raw           : {r_m}/{len(eval_pairs)} = {r_m/len(eval_pairs)*100:.1f}%")
            print(f"  feeding-merged: {f_m}/{len(eval_pairs)} = {f_m/len(eval_pairs)*100:.1f}%")

        # DB vlm vs jsonl 차이
        in_db_not_jsonl = set(v_map) - set(v35)
        in_jsonl_not_db = set(v35) - set(v_map)
        print()
        print(f"DB vlm 있지만 jsonl 없음: {len(in_db_not_jsonl)}건")
        print(f"jsonl 있지만 DB vlm 없음: {len(in_jsonl_not_db)}건")
    else:
        print("v3.5-zeroshot.jsonl 못 찾음")
    print()

    # confusion pair top
    wrong = [(g, v) for _, g, v in pairs if g != v]
    print(f"== DB 기준 raw mismatch top-10 ({len(wrong)}건) ==")
    for (g, v), n in Counter(wrong).most_common(10):
        merged_note = " (feeding 통합 시 정답)" if g in ("drinking", "eating_paste") and v in ("drinking", "eating_paste") else ""
        print(f"  {g:14s} → {v:14s}  {n}건{merged_note}")


if __name__ == "__main__":
    main()
