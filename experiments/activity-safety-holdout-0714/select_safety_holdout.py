"""독립 safety holdout — activity-v1 튜닝에 **사용하지 않은** 신규 영상으로 두 스위치를 재검증.

기존 preflight 34개(30 + absent_v1 4)를 제외하고, 전체 카메라·시간대를 넓혀 activity-v1(0.10+roi_flow0.5)
detector 로 exclude_static / exclude_absent 후보를 각 ≥10 뽑는다. 사람 blind 검수에서 사람=active 가
1건이라도 그 스위치로 판정되면 그 스위치는 reject(지시문). detector/decision 은 숨긴 blind manifest.
카메라 UUID 는 DB 에서 조회(하드코딩/커밋 금지), manifest/answer 에는 clip_id + 측정값만.
"""
import csv
import json
import shutil
import tempfile
from pathlib import Path

from supabase import create_client

from gecko_vision_gate.activity_policy import ActivityPolicy

from reporter import config, r2
from reporter.gate_runner import assess_clip, load_detector

LAB = Path("/Users/baek/petcam-lab")
PRE = LAB / "experiments/activity-preflight-0714"
OUT = LAB / "experiments/activity-safety-holdout-0714"
CLIPS_DIR = LAB / "storage/activity-safety-holdout-0714/clips"   # gitignore
CLIPS_DIR.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

# activity-v1 튜닝/선정에 이미 쓴 clip (겹침 0 보장)
used = {c["clip_id"] for c in json.loads((PRE / "answer_key.json").read_text())}
used |= {c["clip_id"] for c in json.loads((PRE / "absent_v1_answer.json").read_text())}

TARGET = {"exclude_static": 12, "exclude_absent": 12}
PER_CAM_SCAN = 260

sb = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
cams = sorted({r["id"] for r in sb.table("cameras").select("id").execute().data})  # 전체 카메라(3) — motion_clips distinct 는 limit 1000 에 걸려 A만 잡힘

policy = ActivityPolicy(version="activity-v1", gate_threshold=0.10, roi_flow_active=0.5)
det = load_detector(config.GATE_CHECKPOINT_PATH, 0.10)

buckets: dict[str, list] = {"exclude_static": [], "exclude_absent": [], "active": [], "unknown": []}
scanned = 0
with tempfile.TemporaryDirectory() as tmp:
    for cam in cams:
        # 주/야 다양성 위해 최근 넓게 + motion_score 다양(오름차순 절반 + 내림차순 절반 인터리브)
        rows = (sb.table("motion_clips").select("id,camera_id,r2_key,duration_sec,motion_score,started_at")
                .eq("camera_id", cam).order("started_at", desc=True).limit(400).execute().data)
        rows = [r for r in rows if r["id"] not in used and r.get("motion_score") is not None]
        rows.sort(key=lambda r: r["motion_score"])
        inter = []
        lo, hi = 0, len(rows) - 1
        while lo <= hi:
            inter.append(rows[lo]); lo += 1
            if lo <= hi:
                inter.append(rows[hi]); hi -= 1
        for r in inter[:PER_CAM_SCAN]:
            if len(buckets["exclude_static"]) >= TARGET["exclude_static"] and len(buckets["exclude_absent"]) >= TARGET["exclude_absent"]:
                break
            dest = Path(tmp) / f"{r['id']}.mp4"
            try:
                r2.download_clip(r["r2_key"], dest)
                ga = assess_clip(str(dest), det, policy, config.GATE_CHECKPOINT_PATH, clip_id=r["id"])
                scanned += 1
                dec = ga.assessment.decision
                rec = {"clip_id": r["id"], "camera_id": cam, "detector_decision": dec,
                       "reason_code": ga.assessment.reason_code, "started_at": r["started_at"],
                       "duration_sec": r["duration_sec"], "measurements": ga.assessment.measurements}
                buckets.setdefault(dec, []).append(rec)
                if dec in TARGET and len([b for b in buckets[dec] if b.get("_kept")]) < TARGET[dec]:
                    shutil.copy(dest, CLIPS_DIR / f"{r['id']}.mp4")
                    rec["_kept"] = True
            except Exception as e:
                print("ERR", r["id"][:8], type(e).__name__, e)
            finally:
                dest.unlink(missing_ok=True)

candidates = [b for k in TARGET for b in buckets.get(k, []) if b.get("_kept")]
import random
random.Random(714).shuffle(candidates)
for b in candidates:
    b.pop("_kept", None)
(OUT / "answer_key.json").write_text(json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8")
with (OUT / "review_manifest.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["order", "clip_id", "video_file", "human_judgment(absent/static/active/unclear)", "notes"])
    for i, c in enumerate(candidates, 1):
        w.writerow([i, c["clip_id"], f"clips/{c['clip_id']}.mp4", "", ""])

by_cam = {}
for c in candidates:
    by_cam.setdefault(c["camera_id"], 0)
    by_cam[c["camera_id"]] += 1
overlap = len(set(c["clip_id"] for c in candidates) & used)
print(f"scanned={scanned} cams={len(cams)} bucket=" + str({k: len(v) for k, v in buckets.items()}))
print(f"selected static={sum(1 for c in candidates if c['detector_decision']=='exclude_static')} "
      f"absent={sum(1 for c in candidates if c['detector_decision']=='exclude_absent')} "
      f"per_camera={by_cam} overlap_with_tuning={overlap}")
