"""하이라이트 봉인 평가 표본 — 층화 무작위 추출 (2.6.1 전환 준비 Task 3).

읽기 전용으로 production 후보를 뽑아 JSON 으로 남긴다. `--register` 만 write(owner 승인 뒤 한 번).

층화: 카메라 × 규칙 initial(O/X). 층당 --per-stratum(기본 30), 후보가 적으면 있는 만큼(억지로 안 채움).
후보 조건: 최근 --days 일, 미디어 있음, 운영 적격, 활성 계약 run 있음(=목록 RPC 가 rule 판정을 냄), 사람 확정 없음.
seed 고정으로 재현 가능. 표본은 검출기 채택 판정용이 아니라 규칙 재보정 기준선(계획서 참고).

사용:
  uv run python scripts/build_highlight_eval_sample.py --sample-id eval-2026-09 --days 14 --seed 20260909
  uv run python scripts/build_highlight_eval_sample.py --sample-id eval-2026-09 --days 14 --seed 20260909 --register   # owner 승인 뒤
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

ROOT = Path(__file__).resolve().parents[1]
# worktree 엔 .env 가 없을 수 있어 main 체크아웃의 .env 를 폴백으로 읽는다(둘 다 없으면 KeyError 로 명확히 실패).
load_dotenv(ROOT / ".env")
load_dotenv(Path("/Users/baek/petcam-lab/.env"))
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
DEV = os.environ["DEV_USER_ID"]
ENGINE = "gme-shadow-v1"
PAGE = 101


def active_contract() -> tuple[str, str]:
    """env 가 있으면 env(운영 계약), 없으면 최신 succeeded job 의 계약(로컬 편의)."""
    env_a, env_d = os.environ.get("GME_ACTIVE_ALGORITHM_VERSION"), os.environ.get("GME_ACTIVE_DETECTOR_IDENTITY")
    if env_a and env_d:
        return env_a, env_d
    j = sb.table("gme_jobs").select("algorithm_version,detector_identity").eq("status", "succeeded").order("created_at", desc=True).limit(1).execute().data[0]
    return j["algorithm_version"], j["detector_identity"]


def list_page(state: str, cam: str, cursor: tuple[str, str] | None, algo: str, det: str) -> list[dict]:
    return sb.rpc("fn_list_labeling_v4_clips", {
        "p_viewer_id": DEV, "p_is_owner": True, "p_scope": "all", "p_camera_ids": [cam],
        "p_label_state": "unlabeled", "p_highlight_state": state, "p_behavior_flag": None,
        "p_engine_schema_version": ENGINE, "p_algorithm_version": algo, "p_detector_identity": det,
        "p_cursor_started_at": cursor[0] if cursor else None, "p_cursor_id": cursor[1] if cursor else None, "p_limit": PAGE,
    }).execute().data


def candidates(days: int, algo: str, det: str) -> dict[tuple[str, str], list[dict]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cams = sb.table("cameras").select("id,name").execute().data
    out: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for cam in cams:
        for state, tag in (("yes", "O"), ("no", "X")):
            cursor = None
            while True:
                rows = list_page(state, cam["id"], cursor, algo, det)
                # 목록은 started_at DESC 라 since 보다 오래된 행이 나오면 이후 페이지는 전부 오래됨.
                keep = [r for r in rows if r["started_at"] >= since and r["highlight_source"] == "rule" and r["highlight_status"] == "decided"]
                out[(cam["id"], tag)].extend({**r, "camera_name": cam["name"]} for r in keep)
                if len(rows) < PAGE or rows[-1]["started_at"] < since:
                    break
                cursor = (rows[-1]["started_at"], rows[-1]["clip_id"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample-id", required=True)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--seed", type=int, default=20260909)
    ap.add_argument("--per-stratum", type=int, default=30)
    ap.add_argument("--register", action="store_true", help="owner 승인 뒤에만 — production write")
    ap.add_argument("--register-json", action="store_true", help="재추출 없이 커밋된 JSON 의 items 를 그대로 등록(승인 뒤). 후보 집합이 그 사이 바뀌어도 표본이 흔들리지 않게")
    a = ap.parse_args()
    if a.register_json:
        path = ROOT / "experiments" / "highlight-eval-sample" / f"{a.sample_id}.json"
        items = json.loads(path.read_text())["items"]
        n = sb.rpc("fn_register_eval_sample", {
            "p_sample_id": a.sample_id,
            "p_items": [{"clip_id": p["clip_id"], "stratum": p["stratum"]} for p in items],
            "p_actor": DEV, "p_is_owner": True,
        }).execute().data
        prog = sb.rpc("fn_eval_sample_progress", {"p_sample_id": a.sample_id}).execute().data
        print(f"registered (new rows): {n} of {len(items)} from {path.name}; progress: {prog}")
        return 0
    rnd = random.Random(a.seed)
    algo, det = active_contract()
    print(f"contract: {algo} {det[:12]}…  days={a.days} seed={a.seed} per_stratum={a.per_stratum}")

    picked: list[dict] = []
    summary: list[dict] = []
    for (cam_id, tag), rows in sorted(candidates(a.days, algo, det).items(), key=lambda kv: (kv[1][0]["camera_name"] if kv[1] else kv[0][0], kv[0][1])):
        chosen = rnd.sample(rows, min(len(rows), a.per_stratum))
        name = rows[0]["camera_name"] if rows else cam_id[:8]
        summary.append({"camera": name, "camera_id": cam_id, "initial": tag, "candidates": len(rows), "picked": len(chosen)})
        print(f"{name:16s} {tag}  후보 {len(rows):5d} → 표본 {len(chosen):3d}")
        picked += [{
            "clip_id": r["clip_id"], "stratum": f"{cam_id[:8]}:{tag}", "camera_id": cam_id, "camera_name": name,
            "started_at": r["started_at"], "initial": tag, "reason": r["highlight_reason"],
        } for r in chosen]

    out = ROOT / "experiments" / "highlight-eval-sample" / f"{a.sample_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "sample_id": a.sample_id, "seed": a.seed, "days": a.days, "per_stratum": a.per_stratum,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "contract": {"engine_schema_version": ENGINE, "algorithm_version": algo, "detector_identity": det},
        "strata": summary, "items": picked,
    }, ensure_ascii=False, indent=1))
    print("wrote", out.relative_to(ROOT), "n =", len(picked))

    if a.register:
        n = sb.rpc("fn_register_eval_sample", {
            "p_sample_id": a.sample_id,
            "p_items": [{"clip_id": p["clip_id"], "stratum": p["stratum"]} for p in picked],
            "p_actor": DEV, "p_is_owner": True,
        }).execute().data
        print("registered (new rows):", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
