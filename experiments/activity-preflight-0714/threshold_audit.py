"""사후 threshold audit — 기존 preflight 30 clip 을 threshold 0.05~0.25 curve 로 재추론.

반증 검증: 0.25 에서 no_gecko(exclude_absent)였던 clip 이 낮은 threshold 에서 게코 검출을 회복하는가.
사람 GT(review_manifest)는 그대로 쓰되 detector threshold 만 바꿔 decision 을 재계산한다.
model 1회 로드 + det.threshold 만 바꿔 재추론(predict(threshold=self.threshold)). R2 재다운로드 없음(로컬 clip).
"""
import csv
import json
from pathlib import Path

from gecko_vision_gate.activity_policy import ActivityPolicy, decide
from gecko_vision_gate.detector import GeckoDetector
from gecko_vision_gate.frame_sampling import sample_frames
from gecko_vision_gate.motion_evidence import compute_motion_metrics
from gecko_vision_gate.prelabel import prelabel_from_frames

EXP = Path("/Users/baek/petcam-lab/experiments/activity-preflight-0714")
CLIPS = Path("/Users/baek/petcam-lab/storage/activity-preflight-0714/clips")
CKPT = "/Users/baek/myPythonProjects/gecko-vision-gate/runs/gecko_v2/checkpoint_best_ema.pth"
THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.25]

human: dict[str, str] = {}
with (EXP / "review_manifest.csv").open(encoding="utf-8") as f:
    for row in csv.DictReader(f):
        j = (row.get("human_judgment(absent/static/active/unclear)") or "").strip().lower()
        if j:
            human[row["clip_id"]] = j

policy = ActivityPolicy(version="audit", gate_threshold=0.0)  # decide 는 motion 기반, gate_threshold 미사용
det = GeckoDetector(model_size="nano", threshold=min(THRESHOLDS), checkpoint=CKPT)

per_clip: dict[str, dict] = {}
for mp4 in sorted(CLIPS.glob("*.mp4")):
    cid = mp4.stem
    frames = sample_frames(mp4, 12)
    per_clip[cid] = {}
    for t in THRESHOLDS:
        det.threshold = t
        r = prelabel_from_frames(frames, threshold=t, checkpoint=CKPT, detector=det)
        m = compute_motion_metrics(frames, r)
        a = decide(r, m, policy)
        per_clip[cid][f"{t:.2f}"] = {
            "decision": a.decision, "reason": a.reason_code,
            "gecko_visible": r.gecko_visible, "conf": r.visibility_confidence,
        }

print("thr | FE_absent FE_static | prec_absent prec_static | active_recall | det_absent det_static")
rows_out = []
for t in THRESHOLDS:
    k = f"{t:.2f}"
    fe_absent = [c for c in per_clip if human.get(c) == "active" and per_clip[c][k]["decision"] == "exclude_absent"]
    fe_static = [c for c in per_clip if human.get(c) == "active" and per_clip[c][k]["decision"] == "exclude_static"]
    det_absent = [c for c in per_clip if per_clip[c][k]["decision"] == "exclude_absent"]
    det_static = [c for c in per_clip if per_clip[c][k]["decision"] == "exclude_static"]
    h_active = [c for c in per_clip if human.get(c) == "active"]
    pa = (sum(human.get(c) == "absent" for c in det_absent) / len(det_absent)) if det_absent else None
    ps = (sum(human.get(c) == "static" for c in det_static) / len(det_static)) if det_static else None
    rc = (sum(per_clip[c][k]["decision"] == "active" for c in h_active) / len(h_active)) if h_active else None
    fpa = "n/a" if pa is None else f"{pa*100:.0f}%"
    fps = "n/a" if ps is None else f"{ps*100:.0f}%"
    frc = "n/a" if rc is None else f"{rc*100:.0f}%"
    print(f"{k}| {len(fe_absent):9d} {len(fe_static):9d} | {fpa:>11} {fps:>11} | {frc:>13} | {len(det_absent):10d} {len(det_static):d}")
    rows_out.append({"threshold": t, "fe_absent": len(fe_absent), "fe_static": len(fe_static),
                     "prec_absent": pa, "prec_static": ps, "active_recall": rc,
                     "n_det_absent": len(det_absent), "n_det_static": len(det_static)})

# 0.25→0.10 회복 상세: 0.25 에서 exclude_absent 였던 clip 의 threshold별 gecko conf
recovered = []
for c in per_clip:
    if per_clip[c]["0.25"]["decision"] == "exclude_absent":
        recovered.append({"clip_id": c, "human": human.get(c),
                          "conf_by_thr": {k: per_clip[c][k]["conf"] for k in per_clip[c]},
                          "decision_by_thr": {k: per_clip[c][k]["decision"] for k in per_clip[c]}})

(EXP / "threshold_audit.json").write_text(
    json.dumps({"thresholds": THRESHOLDS, "curve": rows_out, "recovered_from_025_absent": recovered,
                "per_clip": per_clip, "human": human}, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\n0.25 exclude_absent 였던 {len(recovered)}개의 threshold별 conf → threshold_audit.json")
