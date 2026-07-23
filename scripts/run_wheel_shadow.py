"""P4 Cam(dev) 쳇바퀴 에피소드 중복 묶음 read-only shadow 오케스트레이터.

SELECT-only(DB) + read-only(R2 head/get). production write · VLM 호출 · 라벨링웹 변경 0.
모든 media 는 tempfile.TemporaryDirectory 안에서만 생성·즉시 삭제(temp media 0).

사용:
  # 전체 실행 (fresh cohort + known wheel regression, artifact 생성)
  PYTHONPATH=. uv run python scripts/run_wheel_shadow.py --limit 0
  # 소규모 smoke
  PYTHONPATH=. uv run python scripts/run_wheel_shadow.py --limit 30
  # 결정론 재생성 (EVIDENCE-AUDIT.json 시그니처 → 재그룹 → groups SHA)
  PYTHONPATH=. uv run python scripts/run_wheel_shadow.py --replay
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from pathlib import Path

import cv2
import numpy as np

from backend.r2_uploader import get_r2_bucket, get_r2_client
from backend.supabase_client import get_supabase_client
from scripts.wheel_shadow import cohort as co
from scripts.wheel_shadow import grouping as grp
from scripts.wheel_shadow import signatures as sig
from scripts.wheel_shadow.io_utils import download_clip, extract_adaptive_frames
from scripts.wheel_shadow.representatives import select_representatives

REPO = Path(__file__).resolve().parent.parent
EXP = REPO / "experiments" / "wheel-episode-dedup-shadow"
PROFILE_PATH = EXP / "wheel-roi-profile-v1.json"
CAMERA_NAME = "P4 Cam (dev)"                       # exact name (UUID 하드코딩 금지)
FRESH_RANGE = ("2026-07-19T00:00:00+00:00", "2026-07-22T00:00:00+00:00")
LABELING_URL = "https://label.tera-ai.uk/labeling/motion/{clip_id}"
EVIDENCE_SCHEMA = "python-evidence-raw-v1"
EVIDENCE_ALGO = "croi-temporal-v1"


# ----------------------------------------------------------------------------
# DB SELECT-only helpers
# ----------------------------------------------------------------------------
def resolve_camera(sb) -> str:
    rows = sb.table("cameras").select("id,name").eq("name", CAMERA_NAME).execute().data
    if len(rows) != 1:
        raise SystemExit(f"HOLD: camera name {CAMERA_NAME!r} not unique ({len(rows)})")
    return rows[0]["id"]


def select_fresh_clips(sb, cam_id: str, limit: int) -> list[dict]:
    q = (
        sb.table("motion_clips")
        .select("id,started_at,duration_sec,r2_key,camera_id")
        .eq("camera_id", cam_id)
        .gte("started_at", FRESH_RANGE[0])
        .lt("started_at", FRESH_RANGE[1])
        .not_.is_("r2_key", "null")
        .order("started_at")
        .order("id")
    )
    rows = q.execute().data
    return rows[:limit] if limit and limit > 0 else rows


def select_known_wheel_gt(sb, cam_id: str) -> list[dict]:
    ids: set[str] = set()
    for col in ("current_gt", "initial_gt"):
        rows = (
            sb.table("motion_clip_labeling_sessions")
            .select(f"clip_id,{col}")
            .filter(f"{col}->>enrichment_object", "eq", "wheel")
            .execute()
            .data
        )
        ids.update(r["clip_id"] for r in rows)
    if not ids:
        return []
    clips = (
        sb.table("motion_clips")
        .select("id,started_at,duration_sec,r2_key,camera_id")
        .in_("id", list(ids))
        .eq("camera_id", cam_id)
        .order("started_at")
        .execute()
        .data
    )
    return [c for c in clips if c.get("r2_key")]


def latest_evidence(sb, clip_ids: list[str]) -> dict[str, dict]:
    """cohort clip 의 canonical Python Evidence run(최신 1건)."""
    out: dict[str, dict] = {}
    for i in range(0, len(clip_ids), 100):
        chunk = clip_ids[i:i + 100]
        rows = (
            sb.table("clip_python_evidence_runs")
            .select("id,clip_id,evidence_schema_version,algorithm_version,level0_status,"
                    "level1_status,decoded_frame_count,producer_host,producer_run_id,created_at")
            .in_("clip_id", chunk)
            .eq("evidence_schema_version", EVIDENCE_SCHEMA)
            .eq("algorithm_version", EVIDENCE_ALGO)
            .order("created_at", desc=True)
            .execute()
            .data
        )
        for r in rows:
            out.setdefault(r["clip_id"], r)  # 최신(desc 정렬)이 먼저 → 첫 것 유지
    return out


def gt_watermark(sb, cam_id: str) -> str | None:
    """관측용: motion_clip_labeling_sessions 최신 updated_at (동시 라벨링 진행 근거)."""
    rows = (
        sb.table("motion_clip_labeling_sessions")
        .select("updated_at")
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return rows[0]["updated_at"] if rows else None


def mutation_fingerprint(sb, clip_ids: list[str]) -> str:
    """cohort clip 의 불변 속성 SHA. 동시 라벨링·신규 clip 유입에 불변, 내 실수 write 만 감지."""
    recs: list[tuple] = []
    for i in range(0, len(clip_ids), 100):
        chunk = clip_ids[i:i + 100]
        rows = (
            sb.table("motion_clips")
            .select("id,r2_key,started_at,duration_sec")
            .in_("id", chunk)
            .execute()
            .data
        )
        for r in rows:
            recs.append((r["id"], r.get("r2_key"), r["started_at"], r.get("duration_sec")))
    recs.sort()
    blob = json.dumps(recs, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


# ----------------------------------------------------------------------------
# 시그니처 계산 (R2 read + ffmpeg + OpenCV)
# ----------------------------------------------------------------------------
def _roi_from_profile(profile: dict) -> sig.RoiBox:
    r = profile["roi_normalized"]
    return sig.RoiBox(x=r["x"], y=r["y"], w=r["w"], h=r["h"])


def _evidence_quality(ev: dict | None, frames_used: int) -> tuple[str, float]:
    if ev is None:
        return ("missing", float(frames_used))
    l0 = ev.get("level0_status")
    l1 = ev.get("level1_status")
    dfc = ev.get("decoded_frame_count") or 0
    score = float(dfc) + float(frames_used) + (2.0 if l1 == "ok" else 0.0)
    if l0 == "ok" and frames_used >= 5:
        return ("ok", score)
    if frames_used >= 3:
        return ("degraded", score)
    return ("missing", score)


def compute_signature(clip: dict, roi: sig.RoiBox, ev: dict | None,
                      frame_paths: list[Path]) -> sig.ClipSignature:
    imgs = [cv2.imread(str(p)) for p in frame_paths]
    imgs = [im for im in imgs if im is not None]
    frames_used = len(imgs)
    if frames_used < 3:
        # 신뢰 불가 → novelty=True → ungrouped
        return sig.ClipSignature(
            clip_id=clip["id"], started_at=clip["started_at"],
            duration_sec=float(clip.get("duration_sec") or 0.0), mode="unknown",
            roi_motion_mean=0.0, roi_motion_peak=0.0, roi_periodicity=0.0,
            perceptual_hash=0, evidence_quality="missing", evidence_score=0.0,
            novelty=True, frames_used=frames_used,
        )
    mode = sig.ir_mode(imgs)
    roi_frames = [sig.crop_roi(im, roi) for im in imgs]
    series = sig.roi_motion_series(roi_frames)
    mean, peak, per = sig.motion_summary(series)
    # perceptual: ROI 평균 프레임(구조 안정) → dHash
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32) for f in roi_frames]
    h0, w0 = grays[0].shape
    stacked = np.stack([g if g.shape == (h0, w0) else cv2.resize(g, (w0, h0)) for g in grays])
    mean_roi = stacked.mean(axis=0).astype(np.uint8)
    phash = sig.dhash(mean_roi)
    quality, score = _evidence_quality(ev, frames_used)
    return sig.ClipSignature(
        clip_id=clip["id"], started_at=clip["started_at"],
        duration_sec=float(clip.get("duration_sec") or 0.0), mode=mode,
        roi_motion_mean=mean, roi_motion_peak=peak, roi_periodicity=per,
        perceptual_hash=phash, evidence_quality=quality, evidence_score=round(score, 3),
        novelty=False, frames_used=frames_used,
    )


def build_signatures(clips: list[dict], roi: sig.RoiBox, ev_map: dict, r2, bucket,
                     label: str) -> list[sig.ClipSignature]:
    sigs: list[sig.ClipSignature] = []
    for idx, clip in enumerate(clips, 1):
        with tempfile.TemporaryDirectory(prefix="wheel_shadow_") as td:
            tdp = Path(td)
            mp4 = tdp / "clip.mp4"
            ok = download_clip(r2, bucket, clip["r2_key"], mp4)
            if not ok:
                sigs.append(sig.ClipSignature(
                    clip["id"], clip["started_at"], float(clip.get("duration_sec") or 0.0),
                    "unknown", 0.0, 0.0, 0.0, 0, "missing", 0.0, True, 0))
            else:
                frames = extract_adaptive_frames(mp4, tdp / "frames")
                sigs.append(compute_signature(clip, roi, ev_map.get(clip["id"]), frames))
            # tempdir 컨텍스트 종료 = media 삭제
        if idx % 50 == 0:
            print(f"  [{label}] {idx}/{len(clips)} 시그니처 완료")
    return sigs


# ----------------------------------------------------------------------------
# grouping + artifact
# ----------------------------------------------------------------------------
def _params_from_profile(profile: dict) -> tuple[grp.GroupingParams, int]:
    p = profile["grouping_params"]
    return (
        grp.GroupingParams(
            max_gap_sec=p["max_gap_sec"],
            wheel_motion_floor=p["wheel_motion_floor"],
            hamming_threshold=p["hamming_threshold"],
            motion_tolerance=p["motion_tolerance"],
        ),
        p["novelty_min_hamming"],
    )


def _select_reps(nmh: int):
    def _f(members):
        return select_representatives(members, max_reps=3, novelty_min_hamming=nmh)
    return _f


def group_and_summarize(sigs, params, nmh):
    groups, ungrouped = grp.group_clips(sigs, params, _select_reps(nmh))
    membership = sum(len(g.member_clip_ids) for g in groups)
    reps = sum(len(g.representative_clip_ids) for g in groups)
    return groups, ungrouped, membership, reps


def groups_sha(groups: list[grp.Group], ungrouped: list[str]) -> str:
    payload = {
        "groups": [
            {
                "group_id": g.group_id, "mode": g.mode,
                "members": sorted(g.member_clip_ids),
                "representatives": list(g.representative_clip_ids),
                "first": g.started_at_first, "last": g.started_at_last,
            }
            for g in groups
        ],
        "ungrouped": sorted(ungrouped),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def sig_to_dict(s: sig.ClipSignature) -> dict:
    return {
        "clip_id": s.clip_id, "started_at": s.started_at, "duration_sec": s.duration_sec,
        "mode": s.mode, "roi_motion_mean": s.roi_motion_mean, "roi_motion_peak": s.roi_motion_peak,
        "roi_periodicity": s.roi_periodicity, "perceptual_hash": s.perceptual_hash,
        "evidence_quality": s.evidence_quality, "evidence_score": s.evidence_score,
        "novelty": s.novelty, "frames_used": s.frames_used,
    }


def dict_to_sig(d: dict) -> sig.ClipSignature:
    return sig.ClipSignature(
        d["clip_id"], d["started_at"], d["duration_sec"], d["mode"],
        d["roi_motion_mean"], d["roi_motion_peak"], d["roi_periodicity"],
        d["perceptual_hash"], d["evidence_quality"], d["evidence_score"],
        d["novelty"], d["frames_used"],
    )


def write_artifacts(profile, cohort, fresh_sigs, fresh_groups, fresh_ungrouped,
                    known_sigs, known_groups, ev_map):
    # shadow-groups.json (결정론 출력)
    fresh_membership = sum(len(g.member_clip_ids) for g in fresh_groups)
    fresh_reps = sum(len(g.representative_clip_ids) for g in fresh_groups)
    known_reps = sum(len(g.representative_clip_ids) for g in known_groups)
    known_membership = sum(len(g.member_clip_ids) for g in known_groups)
    # 검토량 = 그룹 대표 + 미묶음(개별 그대로 검토). 아무것도 안 묶이면 감소 0.
    known_ungrouped = len(known_sigs) - known_membership
    known_review = known_reps + known_ungrouped
    workload_reduction = (
        round(1.0 - known_review / len(known_sigs), 4) if known_sigs else None
    )
    shadow_groups = {
        "camera_name": CAMERA_NAME,
        "profile_id": profile["profile_id"],
        "cohort_sha256": cohort["cohort_sha256"],
        "grouping_params": profile["grouping_params"],
        "groups": [
            {
                "group_id": g.group_id, "mode": g.mode,
                "members": sorted(g.member_clip_ids),
                "representatives": list(g.representative_clip_ids),
                "started_at_first": g.started_at_first, "started_at_last": g.started_at_last,
            }
            for g in fresh_groups
        ],
        "ungrouped": sorted(fresh_ungrouped),
        "summary": {
            "n_groups": len(fresh_groups),
            "n_membership": fresh_membership,
            "n_representatives": fresh_reps,
            "n_ungrouped": len(fresh_ungrouped),
            "n_fresh_total": len(fresh_sigs),
        },
        "known_wheel_regression": {
            "n_gt": len(known_sigs),
            "n_groups": len(known_groups),
            "n_membership": known_membership,
            "n_representatives": known_reps,
            "workload_reduction": workload_reduction,
        },
        "groups_sha256": groups_sha(fresh_groups, fresh_ungrouped),
    }
    (EXP / "shadow-groups.json").write_text(
        json.dumps(shadow_groups, ensure_ascii=False, indent=2), encoding="utf-8")

    # BLIND-REVIEW.csv — score/근거 노출 금지, group 제안만
    rep_set = {cid for g in fresh_groups for cid in g.representative_clip_ids}
    with (EXP / "BLIND-REVIEW.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group_id", "is_representative", "clip_id", "captured_at",
                    "labeling_url", "owner_verdict"])
        for g in fresh_groups:
            for cid in sorted(g.member_clip_ids, key=lambda c: (c not in rep_set, c)):
                started = next((s.started_at for s in fresh_sigs if s.clip_id == cid), "")
                w.writerow([g.group_id, "yes" if cid in rep_set else "no", cid,
                            started, LABELING_URL.format(clip_id=cid), ""])

    # EVIDENCE-AUDIT.json — 알고리즘 점수 + provenance (BLIND 과 분리)
    member_group = {cid: g.group_id for g in fresh_groups for cid in g.member_clip_ids}
    rep_flag = {cid: (cid in rep_set) for g in fresh_groups for cid in g.member_clip_ids}
    audit = {"fresh": [], "known_wheel": []}
    for bucket_name, sigs in (("fresh", fresh_sigs), ("known_wheel", known_sigs)):
        for s in sigs:
            ev = ev_map.get(s.clip_id)
            audit[bucket_name].append({
                "signature": sig_to_dict(s),
                "grouping": {
                    "group_id": member_group.get(s.clip_id),
                    "is_representative": rep_flag.get(s.clip_id, False),
                    "status": "grouped" if s.clip_id in member_group else "ungrouped",
                },
                "evidence_provenance": {
                    "run_id": ev.get("id") if ev else None,
                    "evidence_schema_version": ev.get("evidence_schema_version") if ev else None,
                    "algorithm_version": ev.get("algorithm_version") if ev else None,
                    "level0_status": ev.get("level0_status") if ev else None,
                    "level1_status": ev.get("level1_status") if ev else None,
                    "decoded_frame_count": ev.get("decoded_frame_count") if ev else None,
                    "producer_host": ev.get("producer_host") if ev else None,
                    "producer_run_id": ev.get("producer_run_id") if ev else None,
                },
            })
    (EXP / "EVIDENCE-AUDIT.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return shadow_groups


# ----------------------------------------------------------------------------
# replay (결정론 검증) — 저장 시그니처에서 재그룹
# ----------------------------------------------------------------------------
def replay() -> str:
    profile = json.loads(PROFILE_PATH.read_text())
    params, nmh = _params_from_profile(profile)
    audit = json.loads((EXP / "EVIDENCE-AUDIT.json").read_text())
    fresh_sigs = [dict_to_sig(r["signature"]) for r in audit["fresh"]]
    groups, ungrouped, _, _ = group_and_summarize(fresh_sigs, params, nmh)
    sha = groups_sha(groups, ungrouped)
    print(f"REPLAY groups_sha256={sha} (groups={len(groups)}, ungrouped={len(ungrouped)})")
    return sha


# ----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="fresh clip 상한 (0=전체)")
    ap.add_argument("--replay", action="store_true", help="저장 시그니처 재그룹 → SHA")
    a = ap.parse_args()

    if a.replay:
        replay()
        return 0

    profile = json.loads(PROFILE_PATH.read_text())
    roi = _roi_from_profile(profile)
    params, nmh = _params_from_profile(profile)

    sb = get_supabase_client()
    r2 = get_r2_client()
    bucket = get_r2_bucket()
    cam_id = resolve_camera(sb)

    fresh = select_fresh_clips(sb, cam_id, a.limit)
    known = select_known_wheel_gt(sb, cam_id)
    if len(fresh) < 3:
        raise SystemExit("HOLD: fresh clips < 3")
    print(f"fresh={len(fresh)} known_wheel_gt={len(known)}")

    all_ids = [c["id"] for c in fresh] + [c["id"] for c in known]
    ev_map = latest_evidence(sb, all_ids)
    watermark = gt_watermark(sb, cam_id)

    # 동시 라벨링 안전 계약: cohort 동결 + fingerprint(전)
    cohort = co.build_frozen_cohort(
        camera_name=CAMERA_NAME, camera_id=cam_id,
        started_at_range=list(FRESH_RANGE),
        clips=[{"clip_id": c["id"],
                "run_id": (ev_map.get(c["id"], {}) or {}).get("id"),
                "evidence_schema_version": EVIDENCE_SCHEMA,
                "algorithm_version": EVIDENCE_ALGO} for c in fresh],
        known_wheel_gt_clip_ids=[c["id"] for c in known],
        gt_snapshot_watermark=watermark,
    )
    fp_before = mutation_fingerprint(sb, all_ids)

    # 시그니처 (R2 read + ffmpeg, temp media 즉시 삭제)
    fresh_sigs = build_signatures(fresh, roi, ev_map, r2, bucket, "fresh")
    known_sigs = build_signatures(known, roi, ev_map, r2, bucket, "known")

    # grouping
    fresh_groups, fresh_ungrouped, membership, reps = group_and_summarize(fresh_sigs, params, nmh)
    known_groups, _, _, _ = group_and_summarize(known_sigs, params, nmh)

    # fingerprint(후) — SELECT-only 불변 검증
    fp_after = mutation_fingerprint(sb, all_ids)
    watermark_after = gt_watermark(sb, cam_id)
    mutation_ok = fp_before == fp_after

    # overlap 0 검증
    member_ids = [cid for g in fresh_groups for cid in g.member_clip_ids]
    overlap = len(member_ids) - len(set(member_ids))

    cohort["mutation_fingerprint_before"] = fp_before
    cohort["mutation_fingerprint_after"] = fp_after
    cohort["mutation_unchanged"] = mutation_ok
    cohort["gt_watermark_start"] = watermark
    cohort["gt_watermark_end"] = watermark_after
    (EXP / "frozen-cohort.json").write_text(
        json.dumps(cohort, ensure_ascii=False, indent=2), encoding="utf-8")

    sg = write_artifacts(profile, cohort, fresh_sigs, fresh_groups, fresh_ungrouped,
                         known_sigs, known_groups, ev_map)

    print("=" * 60)
    print(f"fresh groups={len(fresh_groups)} membership={membership} reps={reps} "
          f"ungrouped={len(fresh_ungrouped)}")
    print(f"known wheel: gt={len(known_sigs)} groups={len(known_groups)} "
          f"reps={sg['known_wheel_regression']['n_representatives']} "
          f"workload_reduction={sg['known_wheel_regression']['workload_reduction']}")
    print(f"overlap={overlap} mutation_unchanged={mutation_ok} groups_sha={sg['groups_sha256'][:12]}")
    print(f"gt watermark start={watermark} end={watermark_after} "
          f"(동시 라벨링 진행={'yes' if watermark != watermark_after else 'no'})")
    if not mutation_ok:
        print("!!! SHADOW_REJECTED_SAFETY: mutation fingerprint 변화 감지")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
