"""local-vlm-evidence-analyst 표본 가용성 진단 — **SELECT only**.

design §6 / TEST-SHEET §5 의 180 unique·6 strata×30·camera≥2/date≥3·30분 episode dedup 을
만들 raw pool 이 존재하는지 읽기 전용으로 측정한다. **DB write·모델 출력·GT 생성 없음.**

⚠️ 6 evidence strata(absent/big_move/rest_micro/lick_water_food/wheel_object/hardcase)는
motion_extent·visibility·object 축이라 행동 GT(behavior_logs.action)에서 곧바로 나오지 않는다.
따라서 이 probe 는 "행동 GT 기반 candidate pool 규모"만 보고하고, 진짜 evidence 사전등록은
owner blind evidence GT worksheet 이후에만 가능하다(design §6.3). 이 스크립트는 GT 를 만들지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 행동 class → evidence strata 대략 매핑 (candidate pool 규모 추정용, 최종 GT 아님)
_ACTION_TO_STRATUM_HINT = {
    "moving": "big_move",
    "unseen": "absent",
    "resting": "rest_micro",
    "basking": "rest_micro",
    "hiding": "rest_micro",
    "tongue_flicking": "rest_micro",
    "drinking": "lick_water_food",
    "eating_paste": "lick_water_food",
    "eating_prey": "lick_water_food",
    "hand_feeding": "lick_water_food",
    "playing": "wheel_object",
    "shedding": "hardcase",
    "defecating": "hardcase",
}
_STRATA = ("absent", "big_move", "rest_micro", "lick_water_food", "wheel_object", "hardcase")
_TARGET_PER_STRATUM = 30
_EPISODE_WINDOW_MIN = 30


def _page(query_builder, page_size: int = 1000):
    """supabase .range 페이지네이션으로 전량 SELECT."""
    rows = []
    start = 0
    while True:
        chunk = query_builder().range(start, start + page_size - 1).execute().data
        rows.extend(chunk)
        if len(chunk) < page_size:
            break
        start += page_size
    return rows


def probe() -> dict:
    from backend.supabase_client import get_supabase_client

    sb = get_supabase_client()

    # 1) 사람 행동 GT (behavior_logs source=human)
    gt_rows = _page(
        lambda: sb.table("behavior_logs").select("clip_id,action").eq("source", "human")
    )
    gt_by_clip: dict[str, str] = {}
    for r in gt_rows:
        cid = r.get("clip_id")
        if cid and cid not in gt_by_clip:
            gt_by_clip[cid] = r.get("action")

    # 2) camera_clips 메타 (behavior_logs.clip_id → camera_clips.id 조인)
    clip_rows = _page(
        lambda: sb.table("camera_clips").select("id,camera_id,started_at,source,r2_key,duration_sec")
    )
    meta = {r["id"]: r for r in clip_rows if r.get("id")}

    # 3) 집계
    action_dist = Counter(gt_by_clip.values())
    stratum_pool: dict[str, list[str]] = defaultdict(list)
    cameras: set = set()
    dates: set = set()
    per_stratum_camera: dict[str, Counter] = defaultdict(Counter)
    # episode dedup: stratum 내에서 (camera, 30분 bucket) 당 1개만 세어 unique episode 추정.
    # (clip 은 action 하나 → stratum 하나이므로 stratum 별 dedup 이 candidate pool 규모에 맞다.)
    stratum_episodes: dict[str, set] = defaultdict(set)
    missing_meta = 0

    for cid, action in gt_by_clip.items():
        stratum = _ACTION_TO_STRATUM_HINT.get(action, "hardcase")
        m = meta.get(cid, {})
        cam = m.get("camera_id")
        started = m.get("started_at")
        stratum_pool[stratum].append(cid)
        if not m:
            missing_meta += 1
        if cam:
            cameras.add(cam)
            per_stratum_camera[stratum][cam] += 1
        if started:
            try:
                dt = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
                dates.add(dt.date().isoformat())
                bucket = (cam, dt.strftime("%Y-%m-%d %H"), dt.minute // _EPISODE_WINDOW_MIN)
                stratum_episodes[stratum].add(bucket)
            except (ValueError, TypeError):
                pass

    strata_report = {}
    buildable = True
    for s in _STRATA:
        pool = len(stratum_pool.get(s, []))
        episodes = len(stratum_episodes.get(s, set()))
        cam_share = per_stratum_camera.get(s, Counter())
        top_cam_ratio = (max(cam_share.values()) / sum(cam_share.values())) if cam_share else 0.0
        ok = episodes >= _TARGET_PER_STRATUM
        if not ok:
            buildable = False
        strata_report[s] = {
            "gt_pool": pool,
            "dedup_episodes": episodes,
            "target": _TARGET_PER_STRATUM,
            "meets_target": ok,
            "top_camera_ratio": round(top_cam_ratio, 3),
        }

    return {
        "total_human_gt_clips": len(gt_by_clip),
        "gt_clips_missing_camera_meta": missing_meta,
        "action_distribution": dict(action_dist),
        "distinct_cameras": len(cameras),
        "distinct_dates": len(dates),
        "strata_candidate_pool": strata_report,
        "camera_diversity_ok": len(cameras) >= 2,
        "date_diversity_ok": len(dates) >= 3,
        "strata_buildable_from_behavior_gt": buildable,
        "note": (
            "behavior GT 기반 pool 규모 추정치. evidence strata(motion_extent·visibility·object)는 "
            "owner blind evidence GT worksheet 이후에만 확정. hardcase 는 저가시성 축이라 행동 GT 로 "
            "직접 채울 수 없음. 이 수치는 candidate 규모일 뿐 사전등록 manifest 가 아니다."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    try:
        report = probe()
    except Exception as exc:  # noqa: BLE001 - 진단 스크립트, 실패도 보고
        report = {"error": f"{type(exc).__name__}: {exc}", "reachable": False}
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
