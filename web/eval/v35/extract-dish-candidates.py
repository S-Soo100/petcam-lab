"""dish-presence post-filter 대상 클립 추출.

스펙: specs/feature-vlm-feeding-postfilter.md §2.1

대상 = (GT가 drinking 또는 eating_paste) ∪ (raw v3.5 출력이 drinking 또는 eating_paste)

이 합집합 클립에 한해서만 dish-presence GT 라벨링이 필요. 다른 클래스 GT/예측 클립은
post-filter 동작 대상이 아니므로 dish 메타 라벨 무의미 (GT 라벨링 비용 절약).

산출:
  web/eval/v35/dish-candidates.jsonl
    - clip_id, gt_action, raw_action, raw_confidence, raw_reasoning, file_path, started_at, notes
"""
import os
import json
from pathlib import Path
from supabase import create_client
from dotenv import load_dotenv

load_dotenv("/Users/baek/petcam-lab/web/.env.local")
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

ROOT = Path(__file__).resolve().parent
RAW_PATH = ROOT / "v3.5-zeroshot.jsonl"
OUT_PATH = ROOT / "dish-candidates.jsonl"

FEED_CLASSES = {"drinking", "eating_paste"}


def load_raw(p: Path) -> dict[str, dict]:
    """v3.5 raw 추론 결과 로드 (clip_id → record)."""
    out: dict[str, dict] = {}
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            if r.get("ok"):
                out[r["clip_id"]] = r
        except json.JSONDecodeError:
            pass
    return out


def all_rows(table: str, sel: str, **filters) -> list[dict]:
    """Supabase 페이지네이션 헬퍼 (analyze-v35-full.py 패턴 재사용)."""
    out, off = [], 0
    while True:
        q = sb.table(table).select(sel).order("created_at")
        for k, v in filters.items():
            q = q.eq(k, v)
        rows = q.range(off, off + 999).execute().data
        if not rows:
            break
        out.extend(rows)
        if len(rows) < 1000:
            break
        off += 1000
    return out


def main() -> None:
    raw = load_raw(RAW_PATH)
    human = all_rows("behavior_logs", "clip_id, action, notes", source="human")
    gt_action = {r["clip_id"]: r["action"] for r in human}
    gt_notes = {r["clip_id"]: (r.get("notes") or "")[:80] for r in human}

    # camera_clips에서 file_path / started_at 가져오기 (159건만)
    eval_ids = sorted(set(gt_action) & set(raw))
    clips = sb.table("camera_clips").select("id, file_path, started_at").in_("id", eval_ids).execute().data
    clip_meta = {c["id"]: c for c in clips}

    # 합집합 추출
    candidates = []
    for cid in eval_ids:
        g = gt_action[cid]
        r = raw[cid]["action"]
        if g not in FEED_CLASSES and r not in FEED_CLASSES:
            continue  # post-filter 대상 아님
        meta = clip_meta.get(cid, {})
        candidates.append({
            "clip_id": cid,
            "gt_action": g,
            "raw_action": r,
            "raw_confidence": raw[cid].get("confidence"),
            "raw_reasoning": raw[cid].get("reasoning", "")[:200],
            "file_path": meta.get("file_path"),
            "started_at": meta.get("started_at"),
            "notes": gt_notes.get(cid, ""),
        })

    # 정렬: GT가 drinking/paste인 케이스 먼저, 그 다음 raw만 drinking/paste
    candidates.sort(key=lambda x: (
        0 if x["gt_action"] in FEED_CLASSES else 1,
        x["gt_action"],
        x["raw_action"],
        x["clip_id"],
    ))

    with open(OUT_PATH, "w") as f:
        for c in candidates:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # 분포 출력
    print(f"=== dish-presence 후보 클립 ===")
    print(f"v3.5 raw 159건 중 합집합: {len(candidates)}건\n")

    gt_only = [c for c in candidates if c["gt_action"] in FEED_CLASSES and c["raw_action"] not in FEED_CLASSES]
    raw_only = [c for c in candidates if c["gt_action"] not in FEED_CLASSES and c["raw_action"] in FEED_CLASSES]
    both = [c for c in candidates if c["gt_action"] in FEED_CLASSES and c["raw_action"] in FEED_CLASSES]
    print(f"  GT∈feed & raw∈feed (양쪽 다): {len(both)}건")
    print(f"  GT∈feed & raw∉feed (false negative): {len(gt_only)}건")
    print(f"  GT∉feed & raw∈feed (false positive): {len(raw_only)}건")
    print()

    print("== (gt_action, raw_action) 매트릭스 ==")
    from collections import Counter
    mat = Counter((c["gt_action"], c["raw_action"]) for c in candidates)
    for (g, r), n in sorted(mat.items()):
        marker = " ✓" if g == r else ""
        print(f"  GT={g:14s}  raw={r:14s}  {n}건{marker}")
    print()

    print(f"산출: {OUT_PATH}")


if __name__ == "__main__":
    main()
