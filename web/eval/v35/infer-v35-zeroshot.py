"""v3.5 zero-shot 추론 — 105건 평가셋 동일.

변경 사항 (vs v3.4)
-------------------
1. hiding 클래스 폐기 — moving에 통합 (모션 트리거 녹화로 진짜 hiding은 데이터셋에 없음).
2. eating_prey stalking 정의 명시 — "prey 보임 + gecko 시선/자세 고정" 포함.
3. drinking 룰은 v3.4 그대로 (시각 한계라 prompt로 못 풀음).

평가 시 GT 매핑
---------------
human GT가 'hiding'인 4건은 평가 시 'moving'으로 매핑 (raw DB는 보존).
이건 후처리 (analyze 단계)에서 처리, 추론 자체는 영향 없음.

JSONL 누적 — 재실행 안전.
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
OUT_PATH = Path("/tmp/v3.5-zeroshot.jsonl")

# v3.5: hiding 제거. 8개 클래스.
BEHAVIOR_CLASSES = [
    "eating_paste", "eating_prey", "drinking", "defecating",
    "shedding",
    "basking", "moving", "unseen",
]


def build_system_prompt() -> str:
    base = (PROMPTS_ROOT / "system_base.md").read_text()
    species_file = (PROMPTS_ROOT / "species" / "crested_gecko.md").read_text()
    classes_block = "\n".join(f"- {c}" for c in BEHAVIOR_CLASSES)
    return (base
            .replace("{available_classes_block}", classes_block)
            .replace("{species_name}", "crested_gecko")
            .replace("{species_specific_notes}", species_file))


def all_rows(table, sel, **filters):
    out, off = [], 0
    while True:
        q = sb.table(table).select(sel).order("created_at")
        for k, v in filters.items():
            q = q.eq(k, v)
        rows = q.range(off, off + 999).execute().data
        if not rows: break
        out.extend(rows)
        if len(rows) < 1000: break
        off += 1000
    return out


def get_eval_targets() -> list:
    h_rows = all_rows("behavior_logs", "clip_id", source="human")
    h_ids = {r["clip_id"] for r in h_rows}

    clips = sb.table("camera_clips").select("id, file_path, has_motion").eq("has_motion", True).execute().data
    targets = []
    for c in clips:
        if c["id"] not in h_ids: continue
        path = c.get("file_path")
        if not path: continue
        if Path(path).exists():
            targets.append((c["id"], path))
    return sorted(targets, key=lambda x: x[0])


def already_done() -> set:
    if not OUT_PATH.exists():
        return set()
    done = set()
    for line in OUT_PATH.read_text().splitlines():
        try:
            r = json.loads(line)
            if r.get("ok"):
                done.add(r["clip_id"])
        except Exception:
            pass
    return done


def main():
    print("=== v3.5 zero-shot 추론 시작 ===\n")

    sys_prompt = build_system_prompt()
    print(f"system prompt 길이: {len(sys_prompt)} chars")

    # 검증: hiding 폐기 + stalking 정의 + shedding 유지
    has_shedding = "shedding" in sys_prompt
    has_stalking = "stalking" in sys_prompt
    has_hiding_class = "- hiding:" in sys_prompt  # available_classes에서 제거됐는지

    print(f"shedding 키워드 포함: {has_shedding}")
    print(f"stalking 키워드 포함: {has_stalking}")
    print(f"hiding 클래스 정의 잔존: {has_hiding_class}")

    if not has_shedding or not has_stalking:
        raise SystemExit("v3.5 prompt 미반영 (shedding/stalking 누락)")
    if has_hiding_class:
        raise SystemExit("hiding 클래스가 아직 prompt에 남아있음 — 폐기 미반영")

    model = genai.GenerativeModel(
        MODEL_ID,
        system_instruction=sys_prompt,
        generation_config={
            "temperature": 0.1,
            "top_p": 0.95,
            "response_mime_type": "application/json",
        },
    )

    targets = get_eval_targets()
    done = already_done()
    pending = [(cid, p) for cid, p in targets if cid not in done]

    print(f"\n평가 대상: {len(targets)}건 / 완료 {len(done)} / 잔여 {len(pending)}")
    if not pending:
        print("처리할 클립 없음. 종료.")
        return

    sample_size = Path(pending[0][1]).stat().st_size
    print(f"sample target: {sample_size/1024/1024:.1f} MB")

    ok_count, fail_count = 0, 0
    t0 = time.time()

    with open(OUT_PATH, "a") as f:
        for i, (cid, path) in enumerate(pending, 1):
            target_bytes = Path(path).read_bytes()
            messages = [{
                "role": "user",
                "parts": [{"mime_type": "video/mp4", "data": target_bytes}],
            }]

            t_call = time.time()
            try:
                response = model.generate_content(messages)
                parsed = json.loads(response.text)
                elapsed_ms = int((time.time() - t_call) * 1000)
                rec = {
                    "clip_id": cid,
                    "ok": True,
                    "action": parsed.get("action"),
                    "confidence": parsed.get("confidence"),
                    "reasoning": parsed.get("reasoning", ""),
                    "elapsed_ms": elapsed_ms,
                    "model": "gemini-2.5-flash-zeroshot-v3.5",
                }
                ok_count += 1
                print(f"[{i}/{len(pending)}] {cid[:8]} → {parsed.get('action','?'):14s} conf={float(parsed.get('confidence') or 0):.2f} ({elapsed_ms}ms)", flush=True)
            except json.JSONDecodeError as e:
                rec = {"clip_id": cid, "ok": False, "error": f"json: {str(e)[:120]}"}
                fail_count += 1
                print(f"[{i}/{len(pending)}] {cid[:8]} JSON FAIL: {str(e)[:80]}", flush=True)
            except Exception as e:
                rec = {"clip_id": cid, "ok": False, "error": str(e)[:200]}
                fail_count += 1
                print(f"[{i}/{len(pending)}] {cid[:8]} FAIL: {str(e)[:80]}", flush=True)

            f.write(json.dumps(rec) + "\n")
            f.flush()

    elapsed = time.time() - t0
    print(f"\n=== 완료 ===")
    print(f"OK {ok_count} / FAIL {fail_count} ({elapsed:.0f}s)")
    print(f"결과: {OUT_PATH}")


if __name__ == "__main__":
    main()
