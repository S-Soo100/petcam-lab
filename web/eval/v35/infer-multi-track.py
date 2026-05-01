"""오답 26건 × Track 5개 = 130 inference.

Track 가설:
  A: baseline (v3.5 그대로) — 비교군
  B: position-first — 그릇/물 위치 먼저 식별 후 입 위치 매핑
  C: tongue-target — 혀가 닿는 표면 4지선다 (paste/water/other/none)
  D: chain-of-thought — 5단계 관찰 → 추론 분리
  E: conservative — 강한 증거 없으면 moving 디폴트

기준 prompt: web/prompts/system_base.md + species/crested_gecko.md (v3.5).
Track B~E는 baseline 위에 overlay instruction을 prepend.

vlm.md 룰 6 준수: temperature=0.1, top_p=0.95, response_mime_type=json.
JSONL 누적 — 재실행 안전. 각 record에 track 필드 포함.
"""
import os
import json
import time
from pathlib import Path
from supabase import create_client
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv("/Users/baek/petcam-lab/web/.env.local")
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

MODEL_ID = "gemini-2.5-flash"
PROMPTS_ROOT = Path("/Users/baek/petcam-lab/web/prompts")
ROOT = Path(__file__).resolve().parent
ERROR_SET = ROOT / "error-set-154.jsonl"
OUT_PATH = ROOT / "multi-track-zeroshot.jsonl"

BEHAVIOR_CLASSES = [
    "eating_paste", "eating_prey", "drinking", "defecating",
    "shedding", "basking", "moving", "unseen",
]


def build_baseline() -> str:
    base = (PROMPTS_ROOT / "system_base.md").read_text()
    species_file = (PROMPTS_ROOT / "species" / "crested_gecko.md").read_text()
    classes_block = "\n".join(f"- {c}" for c in BEHAVIOR_CLASSES)
    return (base
            .replace("{available_classes_block}", classes_block)
            .replace("{species_name}", "crested_gecko")
            .replace("{species_specific_notes}", species_file))


# Track별 overlay — baseline 앞에 prepend.
TRACK_OVERLAY = {
    "A": "",  # baseline 그대로

    "B": """# TRACK B — Position-first analysis (mandatory pre-step)

Before applying the behavior rules below, you MUST first locate landmarks in the frame.

Step 1 — Locate landmarks (write to reasoning):
  (a) Food dish: small bowl/cup with OPAQUE paste/puree visible? (yes/no/unclear)
  (b) Water source: separate water bowl OR visible water droplets/wet sheen on glass/wall/leaf? (yes/no/unclear)
  (c) Live prey: cricket/roach/mealworm visible? (yes/no/unclear)

Step 2 — Locate the gecko's mouth/tongue relative to those landmarks:
  - Mouth/tongue INSIDE the food dish region with repeated tongue-to-paste contact → eating_paste candidate
  - Mouth/tongue contacting water surface (droplets, meniscus, water bowl) → drinking candidate
  - Mouth/tongue locked on visible prey → eating_prey candidate
  - None of the above → eating/drinking classes are RULED OUT

Proximity to a dish without tongue contact is NEVER evidence of eating. Then apply the rules below.

""",

    "C": """# TRACK C — Tongue-target identification (mandatory)

Before classifying, identify the tongue's contact target during the clip:

Choose ONE target category (write to reasoning):
  (A) OPAQUE paste/puree inside a small dish (cannot see through it, fills the bowl)
  (B) TRANSPARENT water (droplets on glass/wall/leaf, OR meniscus in a water bowl)
  (C) Other surface — own body/eye, air, substrate, dry wall, branch
  (D) NO tongue contact visible in the clip

Mapping:
  (A) with ≥2 repeated licks → eating_paste
  (A) with only 1 single flick → moving (single flick is sensing, not eating)
  (B) with ≥1 clear contact → drinking
  (C) → moving (or shedding if skin removal also visible)
  (D) → moving (or shedding/defecating/basking if those signs are present)

Without identifying a clear (A) or (B) target with the required contact pattern, eating/drinking classes are RULED OUT. Then apply the rules below.

""",

    "D": """# TRACK D — Chain-of-thought (5-step reasoning required)

Reason in this exact order before output. Place the 5 steps in `reasoning` (single line, semicolons between steps):

Step 1 — Frame contents: what's visible? (gecko body parts; dish present?; water source present?; prey present?; substrate/branches)
Step 2 — Gecko motion: still / walking / climbing / twisting / posture-shift / off-screen
Step 3 — Mouth/tongue activity: none / single flick / repeated licks / chewing / biting / pulling
Step 4 — Tongue target: if tongue extends, what surface does it touch? (paste / water / own body / air / substrate / unclear)
Step 5 — Verdict: cite which rule(s) you are applying and why other classes are ruled out.

Be honest about uncertainty in each step. If Step 4 is unclear or "no contact", do NOT classify as eating_paste/eating_prey/drinking.

Then apply the rules below.

""",

    "E": """# TRACK E — Conservative default (moving unless proven otherwise)

DEFAULT TO `moving` UNLESS the visual evidence for another class is strong and explicit.

Strong-evidence requirements (each is a high bar):
  - eating_paste: dish visible AND ≥2 distinct tongue-to-paste contacts visible in the clip. NOT just head-near-dish.
  - eating_prey: live prey visible in same frame as gecko AND focused locking/strike. NOT just movement near where prey might be.
  - drinking: tongue extends to a clearly wet/transparent surface and makes contact. NOT just tongue flicking near a wet area.
  - defecating: tail base lifts AND feces extrusion visible. NOT just tail movement.
  - shedding: pale/dull skin patches visible AND active removal (mouth pulling skin / loose flaps). NOT just dull color.
  - basking: motionless AND visible heat source. NOT just resting.

If ANY of the above conditions is partial, occluded, or open to interpretation → output `moving`.
False positive eating/drinking is more costly than false negative in this dataset.

Then apply the rules below.

""",
}


def build_track_prompt(track: str) -> str:
    overlay = TRACK_OVERLAY[track]
    base = build_baseline()
    if overlay:
        return overlay + base
    return base


def load_errors() -> list[dict]:
    out = []
    for line in ERROR_SET.read_text().splitlines():
        if not line.strip():
            continue
        out.append(json.loads(line))
    return out


def already_done() -> set[tuple[str, str]]:
    """완료된 (clip_id, track) 쌍."""
    if not OUT_PATH.exists():
        return set()
    done = set()
    for line in OUT_PATH.read_text().splitlines():
        try:
            r = json.loads(line)
            if r.get("ok"):
                done.add((r["clip_id"], r["track"]))
        except Exception:
            pass
    return done


def main() -> None:
    print(f"=== multi-track inference ({MODEL_ID}) ===\n")

    errors = load_errors()
    done = already_done()
    tracks = list(TRACK_OVERLAY.keys())

    # 작업 큐 — track별로 그룹화 (모델 재생성 비용 절감)
    pending: dict[str, list[dict]] = {t: [] for t in tracks}
    for e in errors:
        for t in tracks:
            if (e["clip_id"], t) not in done:
                pending[t].append(e)

    total_pending = sum(len(v) for v in pending.values())
    print(f"오답 클립: {len(errors)} / Track: {len(tracks)} / 총 호출: {len(errors)*len(tracks)}")
    print(f"완료: {len(done)} / 잔여: {total_pending}")
    if not total_pending:
        print("처리할 작업 없음. 종료.")
        return

    ok_count, fail_count = 0, 0
    t0 = time.time()

    with open(OUT_PATH, "a") as f:
        for track in tracks:
            if not pending[track]:
                continue
            sys_prompt = build_track_prompt(track)
            print(f"\n--- Track {track} ({len(pending[track])}건, sys prompt {len(sys_prompt)} chars) ---")
            model = genai.GenerativeModel(
                MODEL_ID,
                system_instruction=sys_prompt,
                generation_config={
                    "temperature": 0.1,
                    "top_p": 0.95,
                    "response_mime_type": "application/json",
                },
            )

            for i, e in enumerate(pending[track], 1):
                cid = e["clip_id"]
                path = e["file_path"]
                if not path or not Path(path).exists():
                    rec = {"clip_id": cid, "track": track, "ok": False, "error": f"file missing: {path}"}
                    f.write(json.dumps(rec) + "\n")
                    f.flush()
                    fail_count += 1
                    print(f"[{track} {i}/{len(pending[track])}] {cid[:8]} FILE MISSING")
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
                        "track": track,
                        "ok": True,
                        "action": parsed.get("action"),
                        "confidence": float(parsed.get("confidence") or 0),
                        "reasoning": parsed.get("reasoning", "")[:500],
                        "elapsed_ms": elapsed_ms,
                        "model": MODEL_ID,
                        "gt": e["gt"],
                        "raw_v35": e["raw"],
                    }
                    ok_count += 1
                    match = "✓" if rec["action"] == e["gt"] else "✗"
                    print(f"[{track} {i}/{len(pending[track])}] {cid[:8]} GT={e['gt']:13s} → {parsed.get('action','?'):13s} {match} conf={rec['confidence']:.2f} ({elapsed_ms}ms)", flush=True)
                except json.JSONDecodeError as je:
                    rec = {"clip_id": cid, "track": track, "ok": False, "error": f"json: {str(je)[:120]}"}
                    fail_count += 1
                    print(f"[{track} {i}/{len(pending[track])}] {cid[:8]} JSON FAIL: {str(je)[:80]}", flush=True)
                except Exception as ex:
                    rec = {"clip_id": cid, "track": track, "ok": False, "error": str(ex)[:200]}
                    fail_count += 1
                    print(f"[{track} {i}/{len(pending[track])}] {cid[:8]} FAIL: {str(ex)[:80]}", flush=True)

                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()

    elapsed = time.time() - t0
    print(f"\n=== 완료 ===")
    print(f"OK {ok_count} / FAIL {fail_count} ({elapsed:.0f}s)")
    print(f"결과: {OUT_PATH}")


if __name__ == "__main__":
    main()
