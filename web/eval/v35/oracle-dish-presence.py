"""dish-presence GT oracle — Gemini Pro로 39건에 dish + licking 두 시그널 판정.

스펙: specs/feature-vlm-feeding-postfilter.md §2.1

입력: web/eval/v35/dish-candidates.jsonl (39건)
출력: web/eval/v35/dish-presence-oracle.jsonl

oracle = 사람 spot check의 1차 통과. Pro reasoning이 명확/모호 두 부류로 나누고,
모호 케이스만 사람이 확인 → GT 확정 (별도 단계).

JSONL 누적 — 재실행 안전.
"""
import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv("/Users/baek/petcam-lab/web/.env.local")
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

ROOT = Path(__file__).resolve().parent
CAND_PATH = ROOT / "dish-candidates.jsonl"
OUT_PATH = ROOT / "dish-presence-oracle.jsonl"

MODEL_ID = "gemini-2.5-pro"  # GT oracle: Pro의 reasoning 활용

SYSTEM_PROMPT = """You are an oracle for a crested gecko behavior dataset.
You judge ONLY two binary signals from a short video clip and return JSON.

Signals (independent, both required):

1. dish_present — Is FOOD (pasty supplement / fruit puree / prey items) visibly
   present IN OR ON a dish/bowl during this clip?

   This is the CORE question — we are not asking whether a bowl exists, but whether
   FOOD is being offered to the gecko at the time of this clip.

   - true: food/supplement is visible inside or on a dish at any point in the clip.
     The food may be partially eaten but still recognizable as food.
   - false: the dish is empty, OR no dish is in frame, OR only the water reservoir/
     walls/plants/decor are visible. An empty bowl alone is NOT enough — without
     visible food, this signal is false.

   Note: in this dataset the enclosure may always contain an empty dish even when
   the gecko is not being fed. Treat such clips as dish_present = false.

2. licking_behavior — Does the gecko visibly perform a licking/lapping action
   (mouth/tongue contact with a surface, repeated tongue flicks aimed at a target)?
   - true: tongue clearly extends to touch a surface (food, water spout, wall, hand, etc.)
   - false: gecko walks/stays still without licking, or no gecko visible

Be conservative — when a signal is ambiguous (partially visible, brief, occluded),
choose the value you find more likely AND describe the uncertainty in `reasoning`.

Output JSON only:
{
  "dish_present": true|false,
  "licking_behavior": true|false,
  "confidence": 0.0~1.0,
  "reasoning": "short Korean or English, 1-2 sentences"
}
"""


def load_candidates(p: Path) -> list[dict]:
    out = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        out.append(json.loads(line))
    return out


def already_done(p: Path) -> set[str]:
    if not p.exists():
        return set()
    done = set()
    for line in p.read_text().splitlines():
        try:
            r = json.loads(line)
            if r.get("ok"):
                done.add(r["clip_id"])
        except Exception:
            pass
    return done


def main() -> None:
    print(f"=== dish-presence oracle (Gemini Pro) ===\n")

    candidates = load_candidates(CAND_PATH)
    done = already_done(OUT_PATH)
    pending = [c for c in candidates if c["clip_id"] not in done]
    print(f"전체: {len(candidates)} / 완료: {len(done)} / 잔여: {len(pending)}")

    if not pending:
        print("처리할 클립 없음. 종료.")
        return

    model = genai.GenerativeModel(
        MODEL_ID,
        system_instruction=SYSTEM_PROMPT,
        generation_config={
            "temperature": 0.1,
            "top_p": 0.95,
            "response_mime_type": "application/json",
        },
    )

    ok_count, fail_count = 0, 0
    t0 = time.time()

    with open(OUT_PATH, "a") as f:
        for i, cand in enumerate(pending, 1):
            cid = cand["clip_id"]
            path = cand["file_path"]
            if not path or not Path(path).exists():
                rec = {"clip_id": cid, "ok": False, "error": f"file missing: {path}"}
                f.write(json.dumps(rec) + "\n")
                f.flush()
                fail_count += 1
                print(f"[{i}/{len(pending)}] {cid[:8]} FILE MISSING")
                continue

            video_bytes = Path(path).read_bytes()
            messages = [{
                "role": "user",
                "parts": [{"mime_type": "video/mp4", "data": video_bytes}],
            }]

            t_call = time.time()
            try:
                response = model.generate_content(messages)
                parsed = json.loads(response.text)
                elapsed_ms = int((time.time() - t_call) * 1000)
                rec = {
                    "clip_id": cid,
                    "ok": True,
                    "dish_present": bool(parsed.get("dish_present")),
                    "licking_behavior": bool(parsed.get("licking_behavior")),
                    "confidence": float(parsed.get("confidence") or 0),
                    "reasoning": parsed.get("reasoning", "")[:300],
                    "elapsed_ms": elapsed_ms,
                    "model": MODEL_ID,
                    "gt_action": cand["gt_action"],
                    "raw_action": cand["raw_action"],
                }
                ok_count += 1
                d = "Y" if rec["dish_present"] else "n"
                l = "Y" if rec["licking_behavior"] else "n"
                print(f"[{i}/{len(pending)}] {cid[:8]} GT={cand['gt_action']:13s} raw={cand['raw_action']:13s} → dish={d} lick={l} conf={rec['confidence']:.2f} ({elapsed_ms}ms)", flush=True)
            except json.JSONDecodeError as e:
                rec = {"clip_id": cid, "ok": False, "error": f"json: {str(e)[:120]}"}
                fail_count += 1
                print(f"[{i}/{len(pending)}] {cid[:8]} JSON FAIL: {str(e)[:80]}", flush=True)
            except Exception as e:
                rec = {"clip_id": cid, "ok": False, "error": str(e)[:200]}
                fail_count += 1
                print(f"[{i}/{len(pending)}] {cid[:8]} FAIL: {str(e)[:80]}", flush=True)

            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()

    elapsed = time.time() - t0
    print(f"\n=== 완료 ===")
    print(f"OK {ok_count} / FAIL {fail_count} ({elapsed:.0f}s)")
    print(f"결과: {OUT_PATH}")


if __name__ == "__main__":
    main()
