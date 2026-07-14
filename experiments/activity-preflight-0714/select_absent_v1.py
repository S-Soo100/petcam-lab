"""재실험 — activity-v1 정책(threshold 0.10, roi_flow_active 0.5)에서 exclude_absent 후보를 새로 선정.

0714 audit 결과 0.10 에서 det_absent=0 이고 기존 표본 human absent=0 이라 exclude_absent 를 판정할 수
없었다(REPORT §8-1). 실제 absent 표본을 blind 확보해야 스위치를 독립 판정할 수 있다. detector/decision 은
숨긴 blind manifest 를 만든다. 카메라 UUID 는 env PREFLIGHT_CAMERA_ID 로만.
"""
import csv
import json
import os
import random
import shutil
import tempfile
from pathlib import Path

from supabase import create_client

from gecko_vision_gate.activity_policy import ActivityPolicy

from reporter import config, r2
from reporter.gate_runner import assess_clip, load_detector

CAM = os.environ["PREFLIGHT_CAMERA_ID"]
LAB = Path("/Users/baek/petcam-lab")
CLIPS_DIR = LAB / "storage/activity-preflight-0714-v1/clips"   # gitignore
EXP_DIR = LAB / "experiments/activity-preflight-0714"
CLIPS_DIR.mkdir(parents=True, exist_ok=True)

TARGET_ABSENT = 12
MAX_SCAN = 320

sb = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
rows = (sb.table("motion_clips")
        .select("id,r2_key,duration_sec,motion_score,started_at")
        .eq("camera_id", CAM).order("started_at", desc=True).limit(600).execute().data)
rows = [r for r in rows if r.get("motion_score") is not None]
rows.sort(key=lambda r: r["motion_score"])  # 낮은 motion 부터 = absent(게코 부재/정지) 확률↑

# activity-v1: threshold 0.10 + static 민감도↑. absent 판정에는 absent_max_global_motion 도 관여(하드닝 5).
policy = ActivityPolicy(version="activity-v1", gate_threshold=0.10, roi_flow_active=0.5)
det = load_detector(config.GATE_CHECKPOINT_PATH, 0.10)

absent: list[dict] = []
scanned = 0
with tempfile.TemporaryDirectory() as tmp:
    for r in rows[:MAX_SCAN]:
        if len(absent) >= TARGET_ABSENT:
            break
        dest = Path(tmp) / f"{r['id']}.mp4"
        try:
            r2.download_clip(r["r2_key"], dest)
            ga = assess_clip(str(dest), det, policy, config.GATE_CHECKPOINT_PATH, clip_id=r["id"])
            scanned += 1
            if ga.assessment.decision == "exclude_absent":
                shutil.copy(dest, CLIPS_DIR / f"{r['id']}.mp4")
                absent.append({"clip_id": r["id"], "detector_decision": "exclude_absent",
                               "reason_code": ga.assessment.reason_code, "motion_score": r["motion_score"],
                               "started_at": r["started_at"], "measurements": ga.assessment.measurements})
        except Exception as e:
            print("ERR", r["id"][:8], type(e).__name__, e)
        finally:
            dest.unlink(missing_ok=True)

random.Random(714).shuffle(absent)
(EXP_DIR / "absent_v1_answer.json").write_text(json.dumps(absent, indent=2, ensure_ascii=False), encoding="utf-8")
with (EXP_DIR / "absent_v1_manifest.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["order", "clip_id", "video_file", "human_judgment(absent/static/active/unclear)", "notes"])
    for i, c in enumerate(absent, 1):
        w.writerow([i, c["clip_id"], f"clips/{c['clip_id']}.mp4", "", ""])

print(f"scanned={scanned} absent_found={len(absent)} (target {TARGET_ABSENT})")
print(f"videos -> {CLIPS_DIR}")
