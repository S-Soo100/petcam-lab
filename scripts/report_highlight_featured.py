"""⭐ 대표 tier 실측(읽기 전용). 카메라×하루 `O · 사건 · 대표 · ✨사건` 표 + fn_highlight_featured 타이밍.

배포 전 production 성능 게이트(콜드 ≤ 3초)와 주간 편향 확인(대표가 늘 같은 시간대인가)에 쓴다.
사용: uv run python scripts/report_highlight_featured.py --days 7 --contract gme-motion-v1 <detector64> [--top-n 3] [--gap-sec 1800] [--camera <uuid>...]
"""

from __future__ import annotations

import argparse
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(Path("/Users/baek/petcam-lab/.env"))
ENGINE = "gme-shadow-v1"
KST = timezone(timedelta(hours=9))


def day_window(now: datetime, days: int, day_start_hour: int = 20) -> tuple[datetime, datetime]:
    """오늘 하루 키(20시 경계) 기준 최근 `days` 개 하루를 덮는 [from, now). petcam-api featured_window 와 같은 정의."""
    key_today = (now.astimezone(KST) - timedelta(hours=day_start_hour)).date()
    first = key_today - timedelta(days=days - 1)
    start = datetime(first.year, first.month, first.day, day_start_hour, tzinfo=KST)
    return start.astimezone(timezone.utc), now


def main() -> int:
    from supabase import create_client  # 테스트에서 day_window 만 import 할 때 supabase 를 요구하지 않는다

    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--contract", nargs=2, metavar=("ALGO", "DETECTOR"), required=True)
    ap.add_argument("--top-n", type=int, default=3)
    ap.add_argument("--gap-sec", type=int, default=1800)
    ap.add_argument("--camera", action="append", default=None, help="uuid, 반복 가능. 없으면 전체")
    a = ap.parse_args()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    p_from, p_to = day_window(datetime.now(timezone.utc), a.days)
    args = {"p_camera_ids": a.camera, "p_from": p_from.isoformat(), "p_to": p_to.isoformat(),
            "p_engine_schema_version": ENGINE, "p_algorithm_version": a.contract[0], "p_detector_identity": a.contract[1],
            "p_top_n": a.top_n, "p_gap_sec": a.gap_sec, "p_day_start_hour": 20, "p_tz": "Asia/Seoul"}
    t = time.time()
    rows = sb.rpc("fn_highlight_featured", args).execute().data  # O 만 돌아와 1,000행 캡 안쪽(14일 실측 ≤ 400)
    cold = time.time() - t
    t = time.time()
    sb.rpc("fn_highlight_featured", args).execute()
    warm = time.time() - t
    print(f"rpc: cold {cold:.2f}s · warm {warm:.2f}s · rows {len(rows)} · window {p_from.isoformat()} → {p_to.isoformat()}")

    agg: dict[tuple[str, str], dict] = defaultdict(lambda: {"o": 0, "eps": set(), "featured": 0, "flag_eps": set(), "hours": []})
    for r in rows:
        g = agg[(r["camera_name"], r["day_key"])]
        g["o"] += 1
        g["eps"].add(r["episode_no"])
        if r["tier"] == "featured":
            g["featured"] += 1
            g["hours"].append(datetime.fromisoformat(r["started_at"]).astimezone(KST).strftime("%H"))
        if r["behavior_flagged"]:
            g["flag_eps"].add(r["episode_no"])
    print("\ncamera | day(20시 경계) | O | 사건 | ⭐대표 | ✨사건 | 대표 시각(KST)")
    for (cam, day), g in sorted(agg.items()):
        print(f"{cam} | {day} | {g['o']} | {len(g['eps'])} | {g['featured']} | {len(g['flag_eps'])} | {' '.join(g['hours'])}")
    over = [(k, g["featured"]) for k, g in agg.items() if g["featured"] > a.top_n]
    print(f"\n대표 > top_n 인 (카메라,하루): {over or '없음'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
