"""봉인 표본의 한 카메라 층을 교체한다 — 2026-09-11 owner: "P4 Cam 2(dev) 16건은 개발 중 빈 사육장, 게코가 찍힌 옛 영상으로 대체".

절차(--apply 없으면 계산·JSON 미리보기만):
  1) 표본 JSON 에서 그 카메라의 기존 항목을 찾는다(전부 미확정이어야 함 — 확정된 건 DB 가 보호하고 여기서도 중단).
  2) 후보 = 그 카메라 · 최근 --days 일 · 미디어 있음·운영 적격·활성 계약 run 있음(목록 RPC 가 rule 판정) · 사람 확정 없음 · **게코 보임**(highlight_reason ≠ '게코 미관측').
  3) O/X 층별 --per-stratum 개 무작위(seed). JSON 의 strata·items 를 그 카메라만 갈아끼우고 amendments 에 기록.
  4) --apply: fn_remove_eval_sample_items(옛 항목) → fn_register_eval_sample(새 항목) → 진행 출력. owner 승인 뒤 1회.

사용: uv run python scripts/replace_eval_sample_stratum.py --sample-id eval-2026-09 --camera-name "P4 Cam 2(dev)" --days 60 --seed 20260911 [--apply]
"""
from __future__ import annotations

import argparse
import json
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(Path("/Users/baek/petcam-lab/.env"))
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
DEV = os.environ["DEV_USER_ID"]
ENGINE = "gme-shadow-v1"
PAGE = 101
NOT_VISIBLE_REASON = "게코 미관측"


def list_unlabeled(state: str, cam_id: str, since: str, algo: str, det: str) -> list[dict]:
    out, cursor = [], None
    while True:
        rows = sb.rpc("fn_list_labeling_v4_clips", {
            "p_viewer_id": DEV, "p_is_owner": True, "p_scope": "all", "p_camera_ids": [cam_id],
            "p_label_state": "unlabeled", "p_highlight_state": state, "p_behavior_flag": None,
            "p_engine_schema_version": ENGINE, "p_algorithm_version": algo, "p_detector_identity": det,
            "p_cursor_started_at": cursor[0] if cursor else None, "p_cursor_id": cursor[1] if cursor else None, "p_limit": PAGE,
        }).execute().data
        out += [r for r in rows if r["started_at"] >= since and r["highlight_source"] == "rule" and r["highlight_status"] == "decided"
                and r["highlight_reason"] != NOT_VISIBLE_REASON]
        if len(rows) < PAGE or rows[-1]["started_at"] < since:
            break
        cursor = (rows[-1]["started_at"], rows[-1]["clip_id"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample-id", required=True)
    ap.add_argument("--camera-name", required=True)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--seed", type=int, default=20260911)
    ap.add_argument("--per-stratum", type=int, default=30)
    ap.add_argument("--apply", action="store_true", help="owner 승인 뒤 1회 — 옛 항목 제거 + 새 항목 등록")
    a = ap.parse_args()
    path = ROOT / "experiments" / "highlight-eval-sample" / f"{a.sample_id}.json"
    doc = json.loads(path.read_text())
    algo, det = doc["contract"]["algorithm_version"], doc["contract"]["detector_identity"]
    cam = next(c for c in sb.table("cameras").select("id,name").execute().data if c["name"] == a.camera_name)
    old_items = [it for it in doc["items"] if it["camera_id"] == cam["id"]]
    print(f"camera {cam['name']} {cam['id'][:8]} · 기존 항목 {len(old_items)}")

    # 기존 항목이 확정됐는지 확인(확정된 건 교체 안 함 — DB 도 보호하지만 여기서 먼저 멈춘다).
    prog_before = sb.rpc("fn_eval_sample_progress", {"p_sample_id": a.sample_id}).execute().data
    labeled_old = []
    for it in old_items:
        cur = sb.rpc("fn_highlight_current", {"p_clip_id": it["clip_id"], "p_engine_schema_version": ENGINE, "p_algorithm_version": algo, "p_detector_identity": det}).execute().data[0]
        if cur["source"] == "human":
            labeled_old.append(it["clip_id"])
    if labeled_old:
        print(f"중단: 기존 항목 중 사람 확정 {len(labeled_old)}건 — 봉인 유지. {labeled_old[:3]}")
        return 1

    since = (datetime.now(timezone.utc) - timedelta(days=a.days)).isoformat()
    rnd = random.Random(a.seed)
    new_items, new_strata = [], []
    for state, tag in (("yes", "O"), ("no", "X")):
        cands = list_unlabeled(state, cam["id"], since, algo, det)
        cands = [c for c in cands if c["clip_id"] not in {it["clip_id"] for it in old_items}]
        chosen = rnd.sample(cands, min(len(cands), a.per_stratum))
        months: dict[str, int] = {}
        for c in cands:
            months[c["started_at"][:7]] = months.get(c["started_at"][:7], 0) + 1
        print(f"{tag}: 후보 월별 {dict(sorted(months.items()))}")
        print(f"{tag}: 게코 보이는 미확정 후보 {len(cands)} → 표본 {len(chosen)}"
              + (f" (범위 {min(c['started_at'] for c in chosen)[:10]} ~ {max(c['started_at'] for c in chosen)[:10]})" if chosen else ""))
        new_strata.append({"camera": cam["name"], "camera_id": cam["id"], "initial": tag, "candidates": len(cands), "picked": len(chosen), "days": a.days, "gecko_visible_only": True})
        new_items += [{"clip_id": r["clip_id"], "stratum": f"{cam['id'][:8]}:{tag}", "camera_id": cam["id"], "camera_name": cam["name"],
                       "started_at": r["started_at"], "initial": tag, "reason": r["highlight_reason"]} for r in chosen]

    doc["strata"] = [s for s in doc["strata"] if s["camera_id"] != cam["id"]] + new_strata
    doc["items"] = [it for it in doc["items"] if it["camera_id"] != cam["id"]] + new_items
    doc.setdefault("amendments", []).append({
        "at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "camera": cam["name"], "camera_id": cam["id"],
        "removed": [it["clip_id"] for it in old_items], "added": len(new_items), "days": a.days, "seed": a.seed,
        "reason": "owner 2026-09-11: 개발 중 빈 사육장(게코 미관측) 영상이라 무의미 → 게코 보이는 옛 영상으로 대체. 제거 항목은 전부 미확정.",
        "applied": a.apply,
    })
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    print(f"JSON: items {len(doc['items'])} (removed {len(old_items)}, added {len(new_items)}) → {path.relative_to(ROOT)}")

    if a.apply:
        removed = sb.rpc("fn_remove_eval_sample_items", {"p_sample_id": a.sample_id, "p_clip_ids": [it["clip_id"] for it in old_items], "p_actor": DEV, "p_is_owner": True}).execute().data if old_items else 0
        added = sb.rpc("fn_register_eval_sample", {"p_sample_id": a.sample_id, "p_items": [{"clip_id": it["clip_id"], "stratum": it["stratum"]} for it in new_items], "p_actor": DEV, "p_is_owner": True}).execute().data
        prog_after = sb.rpc("fn_eval_sample_progress", {"p_sample_id": a.sample_id}).execute().data
        print(f"DB: removed {removed} · registered {added} · progress {prog_before} → {prog_after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
