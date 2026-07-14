"""Phase 3 preflight — 카메라의 clip 을 detector 로 스캔해 absent/static/active 후보 각 10개 선정.

detector 판정(answer key)은 숨기고, 사람이 먼저 blind 로 동영상을 보고 판단할 review manifest 를
만든다(지시문 §312). 카메라 UUID 는 env PREFLIGHT_CAMERA_ID 로만 받는다(하드코딩/커밋 금지).
answer_key/manifest 에는 clip_id + 측정값만 넣고 r2_key·camera_id 는 넣지 않는다.

    PREFLIGHT_CAMERA_ID=<uuid> uv run python <this>   # (nightly cwd, gate 설치된 venv)
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
CLIPS_DIR = LAB / "storage/activity-preflight-0714/clips"      # gitignore (동영상)
EXP_DIR = LAB / "experiments/activity-preflight-0714"          # 커밋 (manifest/answer)
CLIPS_DIR.mkdir(parents=True, exist_ok=True)
EXP_DIR.mkdir(parents=True, exist_ok=True)

TARGET = {"exclude_absent": 10, "exclude_static": 10, "active": 10}
MAX_SCAN = 160

sb = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
rows = (sb.table("motion_clips")
        .select("id,r2_key,duration_sec,motion_score,started_at")
        .eq("camera_id", CAM).order("started_at", desc=True).limit(400).execute().data)

# motion_score 3등분 라운드로빈으로 다양성 확보(활동/정지/부재가 특정 시간대에 몰리지 않게)
rows = [r for r in rows if r.get("motion_score") is not None]
rows.sort(key=lambda r: r["motion_score"])
n = len(rows)
thirds = [rows[: n // 3], rows[n // 3: 2 * n // 3], rows[2 * n // 3:]]
pool, i = [], 0
while len(pool) < min(MAX_SCAN, n):
    for seg in thirds:
        if i < len(seg):
            pool.append(seg[i])
    i += 1

policy = ActivityPolicy(version="activity-v0-preflight", gate_threshold=config.GATE_THRESHOLD)
det = load_detector(config.GATE_CHECKPOINT_PATH, config.GATE_THRESHOLD)

buckets: dict[str, list] = {}
scanned = 0
with tempfile.TemporaryDirectory() as tmp:
    for r in pool:
        if all(len(buckets.get(k, [])) >= v for k, v in TARGET.items()):
            break
        dest = Path(tmp) / f"{r['id']}.mp4"
        try:
            r2.download_clip(r["r2_key"], dest)
            ga = assess_clip(str(dest), det, policy, config.GATE_CHECKPOINT_PATH, clip_id=r["id"])
            scanned += 1
            dec = ga.assessment.decision
            rec = {"clip_id": r["id"], "detector_decision": dec,
                   "reason_code": ga.assessment.reason_code,
                   "motion_score": r["motion_score"], "started_at": r["started_at"],
                   "measurements": ga.assessment.measurements}
            buckets.setdefault(dec, []).append(rec)
            # 목표 버킷이고 아직 부족하면 동영상 보존
            if dec in TARGET and len(buckets[dec]) <= TARGET[dec]:
                shutil.copy(dest, CLIPS_DIR / f"{r['id']}.mp4")
        except Exception as e:
            print("ERR", r["id"][:8], type(e).__name__, e)
        finally:
            dest.unlink(missing_ok=True)

candidates = []
for k in TARGET:
    candidates += buckets.get(k, [])[: TARGET[k]]

random.Random(714).shuffle(candidates)  # blind: 순서로 decision 추측 방지
(EXP_DIR / "answer_key.json").write_text(
    json.dumps(candidates, indent=2, ensure_ascii=False), encoding="utf-8")
with (EXP_DIR / "review_manifest.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["order", "clip_id", "video_file", "human_judgment(absent/static/active/unclear)", "notes"])
    for idx, c in enumerate(candidates, 1):
        w.writerow([idx, c["clip_id"], f"clips/{c['clip_id']}.mp4", "", ""])

print(f"scanned={scanned}  bucket_counts=" + str({k: len(v) for k, v in buckets.items()}))
print(f"selected={len(candidates)}  (target absent/static/active = 10/10/10)")
print(f"videos -> {CLIPS_DIR}")
print(f"manifest -> {EXP_DIR/'review_manifest.csv'}")
