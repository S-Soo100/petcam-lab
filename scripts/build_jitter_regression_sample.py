"""jitter 의심 회귀 세트(정지 게코 bbox 흔들림 서명) — 최근 N일 현재-O 클립 중 서명(최장 연속 < 2초 & moving 구간 ≥ 30) 해당을 JSON 으로 남기고,
owner 승인 뒤 `--register` 로 `motion_clip_eval_samples` 에 표본 `jitter-2026-09` 로 등록한다(라벨링 웹 🔎 의심 서명 칩).

용도: ① 팀원 검수 우선순위(정지 오탐이면 X + 오검출) ② 2.6.1 전환 전후 같은 영상으로 회귀 비교. `eval-2026-09`(O/X 재보정용) 과 분리.
사용: uv run python scripts/build_jitter_regression_sample.py --contract gme-motion-v1 <detector64> [--days 14] [--register]
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(Path("/Users/baek/petcam-lab/.env"))
SAMPLE_ID = "jitter-2026-09"
OUT = ROOT / "experiments" / "highlight-eval-sample" / f"{SAMPLE_ID}.json"
ENGINE = "gme-shadow-v1"
LONGEST_LT, BURSTS_GTE = 2.0, 30


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", nargs=2, metavar=("ALGO", "DETECTOR"), required=True)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--register", action="store_true", help="owner 승인 뒤 1회. 이미 있는 (sample, clip) 은 무시")
    a = ap.parse_args()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    now = datetime.now(timezone.utc)
    rows = sb.rpc("fn_highlight_featured", {"p_camera_ids": None, "p_from": (now - timedelta(days=a.days)).isoformat(), "p_to": now.isoformat(),
                                            "p_engine_schema_version": ENGINE, "p_algorithm_version": a.contract[0], "p_detector_identity": a.contract[1]}).execute().data
    ids = [r["clip_id"] for r in rows]
    feat = {}
    for i in range(0, len(ids), 200):
        for x in sb.table("gme_runs").select("clip_id,state_intervals,candidate_moving_sec_any_gecko,created_at").in_("clip_id", ids[i:i + 200]).eq("detector_identity", a.contract[1]).eq("status", "ok").order("created_at", desc=True).execute().data:
            if x["clip_id"] in feat:
                continue
            mv = [iv["end_sec"] - iv["start_sec"] for iv in (x["state_intervals"] or []) if iv["state"] == "moving"]
            feat[x["clip_id"]] = {"longest": max(mv) if mv else 0.0, "bursts": len(mv), "activity": float(x["candidate_moving_sec_any_gecko"] or 0)}
    items = []
    for r in rows:
        f = feat.get(r["clip_id"])
        if f and f["longest"] < LONGEST_LT and f["bursts"] >= BURSTS_GTE:
            items.append({"clip_id": r["clip_id"], "stratum": f"{r['camera_id'][:8]}:jitter", "camera_name": r["camera_name"], "started_at": r["started_at"],
                          "tier": r["tier"], "highlight_source": r["highlight_source"], **f})
    items.sort(key=lambda it: it["started_at"])
    payload = {"sample_id": SAMPLE_ID, "built_at": now.isoformat(timespec="minutes"), "days": a.days,
               "signature": {"longest_moving_sec_lt": LONGEST_LT, "moving_burst_count_gte": BURSTS_GTE},
               "contract": {"engine_schema_version": ENGINE, "algorithm_version": a.contract[0], "detector_identity": a.contract[1]},
               "items": items}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"signature clips: {len(items)} / current-O {len(rows)} → wrote {OUT.relative_to(ROOT)}")
    for it in items:
        print(f"  {it['clip_id'][:8]} {it['camera_name']} {it['started_at'][:16]} tier={it['tier']} src={it['highlight_source']} act={it['activity']:.1f}s longest={it['longest']:.1f}s bursts={it['bursts']}")
    if a.register:
        n = sb.rpc("fn_register_eval_sample", {"p_sample_id": SAMPLE_ID, "p_items": [{"clip_id": it["clip_id"], "stratum": it["stratum"]} for it in items],
                                               "p_actor": os.environ["DEV_USER_ID"], "p_is_owner": True}).execute().data
        print(f"registered new rows: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
