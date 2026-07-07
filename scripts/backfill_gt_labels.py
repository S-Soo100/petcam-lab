"""dataset-203 manifest 의 GT → behavior_labels 백필 (라벨링 웹 '완료' 인식용).

## 왜 필요한가 (2026-07-07)
라벨링 웹 큐(`GET /labels/queue`, backend/routers/labels.py)는 "이미 라벨함" 판정을
**behavior_labels** 테이블(labeled_by=user) 로만 한다. 그런데 dataset-203 의 사람 GT 는
과거 라운드 경로라 **behavior_logs source='human'** 에 저장돼 있고 behavior_labels 엔
극히 일부만 있다. → 이미 GT 완료한 203 클립들이 큐에 "미라벨"로 계속 뜬다.

이 스크립트는 manifest.csv(203 평가셋 SOT)의 `gt` 를 owner 명의 behavior_labels row 로
백필해 큐에서 사라지게 한다. **manifest gt 가 SOT** (GT 정정 반영된 동결본).

## 안전장치
- 멱등: 이미 behavior_labels(clip_id, owner) 있으면 skip (UI 라벨 덮어쓰지 않음).
- FK: clip_id 가 camera_clips 에 없으면 insert 불가 → 별도 리포트(건드리지 않음).
- 정합성: manifest gt vs behavior_logs human action 불일치를 리포트(정정 이력 추적).
- behavior_labels 에만 쓴다. behavior_logs / manifest / camera_clips 는 안 건드림.

## 실행
  PYTHONPATH=. uv run python scripts/backfill_gt_labels.py           # dry-run (리포트만)
  PYTHONPATH=. uv run python scripts/backfill_gt_labels.py --apply   # 실제 upsert
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "storage" / "dataset-203" / "manifest.csv"
OWNER_USER_ID = "380d97fd-cb83-4490-ac26-cf691b32614f"  # owner (register_motion_candidates 동일)

# behavior_labels.action 이 허용하는 enum (backend labels.py ActionType Literal).
VALID_ACTIONS = {
    "eating_paste", "drinking", "moving", "unknown", "eating_prey",
    "defecating", "shedding", "basking", "unseen", "hand_feeding",
}


def load_manifest() -> list[dict]:
    with MANIFEST.open() as f:
        return [{"clip_id": r["clip_id"], "gt": r["gt"], "filename": r["filename"]}
                for r in csv.DictReader(f)]


def fetch_all_ids(sb, table: str, col: str) -> set[str]:
    """페이지네이션 없이 전량 — camera_clips/behavior_labels 규모(수백)라 단순 select 로 충분."""
    return {row[col] for row in sb.table(table).select(col).execute().data}


def main() -> int:
    ap = argparse.ArgumentParser(description="dataset-203 GT → behavior_labels 백필")
    ap.add_argument("--apply", action="store_true", help="실제 upsert (없으면 dry-run)")
    args = ap.parse_args()

    rows = load_manifest()
    print(f"manifest {len(rows)}행  gt분포={dict(Counter(r['gt'] for r in rows))}")

    bad_gt = [r for r in rows if r["gt"] not in VALID_ACTIONS]
    if bad_gt:
        for r in bad_gt:
            print(f"  ✗ enum 밖 gt={r['gt']!r}  {r['clip_id']}", file=sys.stderr)
        sys.exit("enum 밖 gt 존재 — 중단 (manifest 확인 필요)")

    load_dotenv(REPO / ".env")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])

    cam_ids = fetch_all_ids(sb, "camera_clips", "id")
    # 이미 owner 가 behavior_labels 로 라벨한 clip → skip (UI 라벨 우선, 덮어쓰지 않음)
    existing_labels = {
        row["clip_id"]: row["action"]
        for row in sb.table("behavior_labels").select("clip_id,action")
        .eq("labeled_by", OWNER_USER_ID).execute().data
    }
    # behavior_logs human = 과거 GT. manifest gt 와 정합성 대조용(정정 이력 추적).
    human_logs = {
        row["clip_id"]: row["action"]
        for row in sb.table("behavior_logs").select("clip_id,action")
        .eq("source", "human").execute().data
    }
    print(f"camera_clips={len(cam_ids)}  behavior_labels(owner)={len(existing_labels)}  "
          f"behavior_logs(human)={len(human_logs)}\n")

    to_insert, missing_clip, already, mism_human, mism_label = [], [], [], [], []
    for r in rows:
        cid, gt = r["clip_id"], r["gt"]
        # 정합성: manifest gt 가 과거 human 라벨과 다르면 기록(정정 반영 = 정상, 하지만 가시화)
        if cid in human_logs and human_logs[cid] != gt:
            mism_human.append((cid, human_logs[cid], gt))
        if cid in existing_labels:
            already.append(cid)
            if existing_labels[cid] != gt:  # 기존 UI 라벨 != manifest → 덮어쓰지 않되 경고
                mism_label.append((cid, existing_labels[cid], gt))
            continue
        if cid not in cam_ids:
            missing_clip.append((cid, gt, r["filename"]))
            continue
        to_insert.append({"clip_id": cid, "labeled_by": OWNER_USER_ID, "action": gt})

    print(f"── 대조 결과 ──")
    print(f"이미 behavior_labels 있음(skip): {len(already)}")
    print(f"camera_clips 없음(FK 불가, 미처리): {len(missing_clip)}")
    print(f"→ 신규 insert 대상: {len(to_insert)}  분포={dict(Counter(x['action'] for x in to_insert))}\n")

    if mism_human:
        print(f"⚠ manifest gt ≠ behavior_logs human ({len(mism_human)}건, 정정 이력일 수 있음):")
        for cid, h, g in mism_human[:20]:
            print(f"    {cid[:8]}  human={h:14s} → gt={g}")
        if len(mism_human) > 20:
            print(f"    … 외 {len(mism_human) - 20}건")
        print()
    if mism_label:
        print(f"⚠ 기존 behavior_labels 액션 ≠ manifest gt ({len(mism_label)}건, 덮어쓰지 않음):")
        for cid, l, g in mism_label:
            print(f"    {cid[:8]}  label={l:14s} vs gt={g}")
        print()
    if missing_clip:
        print(f"⚠ camera_clips 에 없어 처리 못 함 ({len(missing_clip)}건):")
        for cid, g, fn in missing_clip[:20]:
            print(f"    {cid[:8]}  gt={g:14s}  {fn}")
        if len(missing_clip) > 20:
            print(f"    … 외 {len(missing_clip) - 20}건")
        print()

    if not to_insert:
        print("신규 insert 0건 — 종료.")
        return 0
    if not args.apply:
        print(f"DRY-RUN — 실제 실행하려면 --apply 추가 ({len(to_insert)}건 upsert)")
        return 0

    # upsert: on_conflict(clip_id,labeled_by) ignore — 동시성 대비 2차 방어(pre-filter 로 이미 신규만).
    done = 0
    for i in range(0, len(to_insert), 100):
        chunk = to_insert[i:i + 100]
        sb.table("behavior_labels").upsert(
            chunk, on_conflict="clip_id,labeled_by", ignore_duplicates=True
        ).execute()
        done += len(chunk)
        print(f"  upsert {done}/{len(to_insert)}")
    print(f"\n✅ behavior_labels {done}건 백필 완료 — 라벨링 큐에서 203셋 사라짐(owner).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
