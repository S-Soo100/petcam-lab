"""쳇바퀴 에피소드 10분 경계 교정 replay runner (v1.1-boundary-fix).

커밋된 v1 signature 를 그대로 읽어 교정된 grouping 만 다시 수행한다.
**외부 저장소·데이터베이스·메시징·모델 API·워커·웹 에 접근하지 않는다.**
stdlib + 기존 pure 모듈만 import 한다(외부 client config import 없음 → 정적 grep 으로도 0).

사용:
  PYTHONPATH=. uv run python scripts/run_wheel_boundary_correction.py
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from scripts.wheel_shadow.grouping import (
    Group,
    GroupingParams,
    group_clips,
    group_span_sec,
    validate_group_spans,
)
from scripts.wheel_shadow.representatives import select_representatives
from scripts.wheel_shadow.signatures import ClipSignature

REPO = Path(__file__).resolve().parent.parent
V1_DIR = REPO / "experiments" / "wheel-episode-dedup-shadow"
OUT_DIR = REPO / "experiments" / "wheel-episode-dedup-boundary-fix"
ALGORITHM_VERSION = "wheel-episode-dedup-shadow-v1.1-boundary-fix"
MAX_EPISODE_SPAN_SEC = 600.0
LABELING_URL = "https://label.tera-ai.uk/labeling/motion/{clip_id}"

# design §4 동결 입력 SHA-256 (production replay 기준값)
FROZEN_SHAS = {
    "EVIDENCE-AUDIT.json": "23789fa8ea430c4dc24b015847c360a6afa72565c897c3d4b7b8654702a508e3",
    "frozen-cohort.json": "b67b32f27259d132cda5861f8126f6b48f4bb704528c0458ebbf63a95d17f953",
    "wheel-roi-profile-v1.json": "653e64c25e057339ce9a1844d27c570ce99916d20986023fafdabd84935c7825",
}


class InputShaMismatch(RuntimeError):
    """입력 파일 SHA-256 이 기대값과 다를 때(fail-closed)."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dict_to_sig(d: dict) -> ClipSignature:
    """EVIDENCE-AUDIT.json 의 signature dict 를 명시 필드로 복원(v1 dict_to_sig 동일 계약)."""
    return ClipSignature(
        d["clip_id"], d["started_at"], d["duration_sec"], d["mode"],
        d["roi_motion_mean"], d["roi_motion_peak"], d["roi_periodicity"],
        d["perceptual_hash"], d["evidence_quality"], d["evidence_score"],
        d["novelty"], d["frames_used"],
    )


def _params_from_profile(profile: dict) -> tuple[GroupingParams, int]:
    p = profile["grouping_params"]
    return (
        GroupingParams(
            max_inter_clip_gap_sec=p["max_gap_sec"],
            max_episode_span_sec=MAX_EPISODE_SPAN_SEC,
            wheel_motion_floor=p["wheel_motion_floor"],
            hamming_threshold=p["hamming_threshold"],
            motion_tolerance=p["motion_tolerance"],
        ),
        p["novelty_min_hamming"],
    )


def _reps_selector(nmh: int):
    def _f(members):
        return select_representatives(members, max_reps=3, novelty_min_hamming=nmh)
    return _f


def _group_payload(groups: list[Group], ungrouped: list[str]) -> dict:
    return {
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


def _result_sha(fresh_groups, fresh_ung, known_groups, known_ung) -> str:
    payload = {
        "fresh": _group_payload(fresh_groups, fresh_ung),
        "known_wheel": _group_payload(known_groups, known_ung),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _overlap(groups: list[Group]) -> int:
    mem = [cid for g in groups for cid in g.member_clip_ids]
    return len(mem) - len(set(mem))


def _span_violations(groups: list[Group], max_span: float) -> int:
    return sum(1 for g in groups if group_span_sec(g) > max_span)


def _workload_reduction(groups: list[Group], n_total: int) -> tuple[int, float | None]:
    reps = sum(len(g.representative_clip_ids) for g in groups)
    membership = sum(len(g.member_clip_ids) for g in groups)
    ungrouped = n_total - membership
    review = reps + ungrouped
    reduction = round(1.0 - review / n_total, 4) if n_total else None
    return reps, reduction


def _write_blind_review(path: Path, groups: list[Group], sigs: list[ClipSignature]) -> None:
    started = {s.clip_id: s.started_at for s in sigs}
    rep_set = {cid for g in groups for cid in g.representative_clip_ids}
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        # 점수·motion·hash·provenance 열 없음 (owner blind).
        w.writerow(["group_id", "is_representative", "clip_id", "captured_at",
                    "labeling_url", "owner_verdict"])
        for g in groups:
            for cid in sorted(g.member_clip_ids, key=lambda c: (c not in rep_set, c)):
                w.writerow([g.group_id, "yes" if cid in rep_set else "no", cid,
                            started.get(cid, ""), LABELING_URL.format(clip_id=cid), ""])


def run(input_dir: Path, output_dir: Path,
        expected_shas: dict[str, str] | None = None) -> dict:
    shas = expected_shas if expected_shas is not None else FROZEN_SHAS

    # 1) 입력 SHA fail-closed (출력 생성 전에 검증)
    input_sha256: dict[str, str] = {}
    for name, exp in shas.items():
        actual = _sha256(input_dir / name)
        input_sha256[name] = actual
        if actual != exp:
            raise InputShaMismatch(f"INPUT_SHA_MISMATCH file={name}")

    # 2) signature 복원
    profile = json.loads((input_dir / "wheel-roi-profile-v1.json").read_text())
    audit = json.loads((input_dir / "EVIDENCE-AUDIT.json").read_text())
    params, nmh = _params_from_profile(profile)
    reps = _reps_selector(nmh)
    fresh_sigs = [_dict_to_sig(r["signature"]) for r in audit["fresh"]]
    known_sigs = [_dict_to_sig(r["signature"]) for r in audit["known_wheel"]]

    # 3) 교정된 grouping (2회 → 결정론) + 그룹 직후 span 불변식 hard fail
    fresh_groups, fresh_ung = group_clips(fresh_sigs, params, reps)
    known_groups, known_ung = group_clips(known_sigs, params, reps)
    validate_group_spans(fresh_groups, params.max_episode_span_sec)
    validate_group_spans(known_groups, params.max_episode_span_sec)

    fresh_groups2, fresh_ung2 = group_clips(fresh_sigs, params, reps)
    known_groups2, known_ung2 = group_clips(known_sigs, params, reps)

    result_sha = _result_sha(fresh_groups, fresh_ung, known_groups, known_ung)
    replay_sha = _result_sha(fresh_groups2, fresh_ung2, known_groups2, known_ung2)

    # 4) 지표
    fresh_membership = sum(len(g.member_clip_ids) for g in fresh_groups)
    fresh_reps = sum(len(g.representative_clip_ids) for g in fresh_groups)
    fresh_span_viol = _span_violations(fresh_groups, params.max_episode_span_sec)
    known_span_viol = _span_violations(known_groups, params.max_episode_span_sec)
    fresh_overlap = _overlap(fresh_groups)
    known_overlap = _overlap(known_groups)
    fresh_max_span = max((group_span_sec(g) for g in fresh_groups), default=0.0)
    known_reps, known_reduction = _workload_reduction(known_groups, len(known_sigs))
    span_violation_total = fresh_span_viol + known_span_viol
    overlap_total = fresh_overlap + known_overlap

    effective_params = {
        "max_inter_clip_gap_sec": params.max_inter_clip_gap_sec,
        "max_episode_span_sec": params.max_episode_span_sec,
        "wheel_motion_floor": params.wheel_motion_floor,
        "hamming_threshold": params.hamming_threshold,
        "motion_tolerance": params.motion_tolerance,
        "novelty_min_hamming": nmh,
    }

    # 5) 기계 게이트 (runner 자체 검증: 1,2,3,4,5 · gate6=pytest 외부 · gate7=구조상 0)
    gate_all_spans = span_violation_total == 0
    gate_overlap = overlap_total == 0
    gate_determinism = result_sha == replay_sha
    gate_input_sha = all(input_sha256.get(n) == FROZEN_SHAS[n] for n in FROZEN_SHAS)
    gate_reduction = known_reduction is not None and known_reduction >= 0.5
    machine_ok = (
        gate_all_spans and gate_overlap and gate_determinism
        and gate_input_sha and gate_reduction
    )
    verdict = (
        "BOUNDARY_CORRECTION_READY_FOR_OWNER_REVIEW"
        if machine_ok else "BOUNDARY_CORRECTION_REJECTED"
    )

    result = {
        "algorithm_version": ALGORITHM_VERSION,
        "input_sha256": input_sha256,
        "effective_params": effective_params,
        "fresh": {
            "n_total": len(fresh_sigs),
            "n_groups": len(fresh_groups),
            "n_membership": fresh_membership,
            "n_representatives": fresh_reps,
            "n_ungrouped": len(fresh_ung),
            "max_group_span_sec": fresh_max_span,
            "span_violation_count": fresh_span_viol,
            "overlap_count": fresh_overlap,
        },
        "known_wheel": {
            "n_total": len(known_sigs),
            "n_groups": len(known_groups),
            "n_representatives": known_reps,
            "workload_reduction": known_reduction,
            "span_violation_count": known_span_viol,
            "overlap_count": known_overlap,
        },
        "span_violation_count": span_violation_total,
        "overlap_count": overlap_total,
        "result_sha256": result_sha,
        "replay_sha256": replay_sha,
        "machine_gates": {
            "gate1_all_group_spans_le_600": gate_all_spans,
            "gate2_overlap_zero": gate_overlap,
            "gate3_deterministic_replay": gate_determinism,
            "gate4_input_sha_matches_frozen": gate_input_sha,
            "gate5_known_reduction_ge_50pct": gate_reduction,
            "gate6_tests_pass": "verified_by_pytest_externally",
            "gate7_no_db_r2_vlm_temp": "by_construction",
        },
        "machine_verdict": verdict,
    }

    # 6) 산출물 기록 (검증 통과 후에만)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_blind_review(output_dir / "BLIND-REVIEW.csv", fresh_groups, fresh_sigs)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="쳇바퀴 10분 경계 교정 replay")
    ap.add_argument("--input-dir", type=Path, default=V1_DIR)
    ap.add_argument("--output-dir", type=Path, default=OUT_DIR)
    a = ap.parse_args()
    try:
        result = run(a.input_dir, a.output_dir)
    except InputShaMismatch as exc:
        print(str(exc))
        return 2
    print(result["machine_verdict"])
    print(f"fresh: groups={result['fresh']['n_groups']} "
          f"membership={result['fresh']['n_membership']} "
          f"reps={result['fresh']['n_representatives']} "
          f"max_span={result['fresh']['max_group_span_sec']:.0f}s "
          f"span_viol={result['span_violation_count']} overlap={result['overlap_count']}")
    print(f"known_wheel: groups={result['known_wheel']['n_groups']} "
          f"reps={result['known_wheel']['n_representatives']} "
          f"reduction={result['known_wheel']['workload_reduction']}")
    print(f"result_sha={result['result_sha256'][:12]} replay_sha={result['replay_sha256'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
