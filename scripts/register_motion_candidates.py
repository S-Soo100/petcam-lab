"""motion_clips 백필 결과(jsonl) → camera_clips 미러 + behavior_logs(vlm 후보) 등록.

nightly-reporter 의 backfill_window.py --out 이 만든 jsonl 을 읽어, moving/error/unseen 이
아닌 clip 을 라벨링 대상(camera_clips)에 "후보"로 편입한다.

왜 미러가 필요한가: behavior_logs.clip_id FK → camera_clips(id), 라벨링 큐도 camera_clips 만
조회(has_motion + r2_key). motion_clips 는 petcam-lab 코드에 없음(완전 분리) → camera_clips 로
미러해야 라벨링/평가에 노출된다. motion_clips.id 를 그대로 재사용(추적성 + FK 충족).

방법론(중요, cherry-pick 방지):
- claude 라벨은 GT 아님 → behavior_logs source='vlm', verified=False 로만 저장.
- 사람 육안 확정은 라벨링 웹에서 behavior_labels 로 (이 스크립트 범위 밖).
- manifest(평가셋 SOT)는 안 건드림 — 육안 확정 후 별도 편입(register_eval_batch 류).

멱등: camera_clips 에 id 존재 시 skip. behavior_logs UNIQUE(clip_id, source) 도 2차 방어.

실행:
  PYTHONPATH=. uv run python scripts/register_motion_candidates.py --jsonl <path>            # dry-run
  PYTHONPATH=. uv run python scripts/register_motion_candidates.py --jsonl <path> --apply     # 실제 INSERT
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

REPO = Path(__file__).resolve().parent.parent
OWNER_USER_ID = "380d97fd-cb83-4490-ac26-cf691b32614f"  # owner (register_eval_batch 동일)
CRESTED_PET_ID = "55518f35-b251-4ed7-962f-b65611d63223"  # owner crested-gecko pet
VLM_MODEL = "claude-sonnet-4-6"  # backfill classify --model sonnet
# 등록 제외: moving(흔함·정보적음) / error(분류실패) / unseen(게코없음, --include-unseen 으로 포함가능)
SKIP_ACTIONS = {"moving", "error", "unseen"}


def main() -> int:
    ap = argparse.ArgumentParser(description="motion 백필 후보 → camera_clips + behavior_logs 등록")
    ap.add_argument("--jsonl", required=True, type=Path, help="backfill_window --out 결과 파일")
    ap.add_argument("--apply", action="store_true", help="실제 INSERT (없으면 dry-run 출력만)")
    ap.add_argument("--include-unseen", action="store_true", help="unseen 도 등록(hard-negative 용)")
    args = ap.parse_args()

    jsonl = args.jsonl.expanduser()
    if not jsonl.is_file():
        sys.exit(f"jsonl 없음: {jsonl}")
    rows = [json.loads(x) for x in jsonl.read_text().splitlines() if x.strip()]
    skip_actions = SKIP_ACTIONS - ({"unseen"} if args.include_unseen else set())
    cand = [r for r in rows if r["action"] not in skip_actions]
    print(f"jsonl {len(rows)}개 → 등록대상 {len(cand)}개, mode={'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"  전체 분포: {dict(Counter(r['action'] for r in rows))}")
    print(f"  등록 분포: {dict(Counter(r['action'] for r in cand))}\n")
    if not cand:
        print("등록대상 0건 — 종료.")
        return 0

    load_dotenv(REPO / ".env")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    ids = [r["clip_id"] for r in cand]
    # 메타 보강: motion_clips 에서 width/height/fps/codec (nullable 이나 있으면 채움)
    meta = {m["id"]: m for m in
            sb.table("motion_clips").select("id,width,height,fps,codec").in_("id", ids).execute().data}
    # 이미 미러된 camera_clips id (멱등)
    existing = {e["id"] for e in
                sb.table("camera_clips").select("id").in_("id", ids).execute().data}
    print(f"이미 등록됨: {len(existing)}개\n")

    done = skipped = failed = 0
    for r in cand:
        cid = r["clip_id"]
        if cid in existing:
            print(f"  [skip] {cid[:8]} {r['action']} (이미 camera_clips 존재)")
            skipped += 1
            continue
        m = meta.get(cid, {})
        clip_row = {
            "id": cid,  # motion_clips.id 재사용 (추적성 + behavior_logs FK 충족)
            "user_id": OWNER_USER_ID,
            "pet_id": CRESTED_PET_ID,
            "camera_id": r.get("camera_id"),
            "source": "camera",  # camera_clips_source_check: camera/upload/youtube 만 허용 (실카메라 클립)
            "started_at": r["started_at"],
            "duration_sec": r["duration_sec"],
            "has_motion": True,
            "width": m.get("width"), "height": m.get("height"),
            "fps": m.get("fps"), "codec": m.get("codec"),
            "file_path": r["r2_key"],  # NOT NULL — 로컬 원본 없어 r2_key 로 대체(식별용)
            "r2_key": r["r2_key"],
        }
        log_row = {
            "clip_id": cid, "frame_idx": 0,
            "action": r["action"], "confidence": r.get("confidence"),
            "source": "vlm", "vlm_model": VLM_MODEL,
            "reasoning": r.get("reasoning", ""),
            "verified": False,
            "notes": "motion-backfill B_sat v4.0 (claude 후보, 육안 미확정)",
        }
        print(f"  {cid[:8]}  {r['action']:12s} conf={r.get('confidence')}  {r['started_at'][:16]}")
        if not args.apply:
            done += 1
            continue
        try:
            sb.table("camera_clips").insert(clip_row).execute()
            sb.table("behavior_logs").insert(log_row).execute()
        except Exception as e:  # noqa: BLE001 — clip 단위 격리, 실패해도 나머지 진행
            print(f"     -> 실패: {str(e)[:160]}", file=sys.stderr)
            failed += 1
            continue
        print("     -> camera_clips + behavior_logs(vlm) ✅")
        done += 1

    print(f"\n{'=' * 52}")
    print(f"처리 {done}, skip {skipped}, 실패 {failed}, mode={'APPLY' if args.apply else 'DRY-RUN'}")
    if not args.apply:
        print("검수 후 실제 실행: --apply 추가")
    else:
        print(f"라벨링 큐에 {done}개 후보 추가됨 → 웹에서 육안 확정 → behavior_labels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
