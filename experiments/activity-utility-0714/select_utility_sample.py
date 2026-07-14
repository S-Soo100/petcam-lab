"""utility 표본 — detector 판정으로 균형 맞추지 않은 무작위 표본. 카메라 × 주/야(KST IR) strata 분리.

목적: clip 단위 필터가 앱 활동시간을 실제로 얼마나 줄이는지 = strata 별 v1 판정 분포 + raw minutes 대비
exclude(absent+static) 가능 minutes/비율. 판정은 **detector v1 기준 추정**(사람 GT 아님 — 실제 정확도는
safety holdout 로 검증). 무작위 sampling(seed 714)이라 detector 로 균형 맞추지 않은 자연 분포.
"""
import json
import random
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from supabase import create_client

from gecko_vision_gate.activity_policy import ActivityPolicy

from reporter import config, r2
from reporter.gate_runner import assess_clip, load_detector

OUT = Path("/Users/baek/petcam-lab/experiments/activity-utility-0714")
OUT.mkdir(parents=True, exist_ok=True)
KST = timezone(timedelta(hours=9))
N_PER_STRATUM = 25


def tod(started_at_iso: str) -> str:
    h = datetime.fromisoformat(started_at_iso).astimezone(KST).hour
    return "day" if 6 <= h < 18 else "night"


sb = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)


def fetch_all(cam: str) -> list[dict]:
    out, off = [], 0
    while True:
        r = (sb.table("motion_clips").select("id,r2_key,duration_sec,started_at")
             .eq("camera_id", cam).order("started_at").range(off, off + 999).execute().data)
        if not r:
            break
        out += r
        if len(r) < 1000:
            break
        off += 1000
    return out


cams = sorted({r["id"] for r in sb.table("cameras").select("id").execute().data})  # 전체 카메라(3) — motion_clips distinct 는 limit 1000 에 걸려 A만 잡힘
policy = ActivityPolicy(version="activity-v1", gate_threshold=0.10, roi_flow_active=0.5)
det = load_detector(config.GATE_CHECKPOINT_PATH, 0.10)

strata: dict[tuple, list] = {}
for cam in cams:
    for r in fetch_all(cam):
        strata.setdefault((cam, tod(r["started_at"])), []).append(r)

report = []
with tempfile.TemporaryDirectory() as tmp:
    for (cam, t), clips in sorted(strata.items()):
        sample = random.Random(714).sample(clips, min(N_PER_STRATUM, len(clips)))
        counts: Counter = Counter()
        raw_sec = excl_sec = 0.0
        n_ok = 0
        for r in sample:
            dest = Path(tmp) / f"{r['id']}.mp4"
            try:
                r2.download_clip(r["r2_key"], dest)
                ga = assess_clip(str(dest), det, policy, config.GATE_CHECKPOINT_PATH, clip_id=r["id"])
                dec = ga.assessment.decision
                counts[dec] += 1
                raw_sec += r["duration_sec"]
                if dec in ("exclude_absent", "exclude_static"):
                    excl_sec += r["duration_sec"]
                n_ok += 1
            except Exception as e:
                print("ERR", r["id"][:8], type(e).__name__, e)
            finally:
                dest.unlink(missing_ok=True)
        report.append({
            "camera": cam, "tod": t, "stratum_total_clips": len(clips), "sampled": n_ok,
            "decisions": dict(counts), "raw_min": round(raw_sec / 60, 1),
            "excludable_min": round(excl_sec / 60, 1),
            "exclude_pct": round(100 * excl_sec / raw_sec, 1) if raw_sec else 0.0,
        })
        c = report[-1]
        print(f"{cam[:8]} {t:5s} total={c['stratum_total_clips']:5d} n={c['sampled']:2d} "
              f"dec={c['decisions']} raw={c['raw_min']}m excl={c['excludable_min']}m ({c['exclude_pct']}%)")

(OUT / "utility_report.json").write_text(json.dumps({"n_per_stratum": N_PER_STRATUM, "strata": report},
                                                    indent=2, ensure_ascii=False), encoding="utf-8")
tot_raw = sum(r["raw_min"] for r in report)
tot_excl = sum(r["excludable_min"] for r in report)
print(f"\nTOTAL raw={tot_raw:.1f}m excludable={tot_excl:.1f}m ({100*tot_excl/tot_raw:.1f}% of sampled) [detector v1 기준 추정]")
