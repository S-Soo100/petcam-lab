"""local VLM evidence scorer + 독립 재계산 단위 테스트.

계약(TEST-SHEET §9·§10·§11 / plan Task 6):
confusion·macro/weighted F1·present recall·object top-k·abstain rate·30-clip consistency·
Wilson/bootstrap CI·완전성(missing/dup/unexpected)·verdict 우선순위. 독립 재계산 script 는
scorer 를 import 하지 않고 같은 canonical 값을 낸다 (불일치 → REJECT_INTEGRITY).
"""

from __future__ import annotations

import pytest

from scripts.recompute_local_vlm_evidence import recompute
from scripts.score_local_vlm_evidence import (
    canonical_sha256,
    canonical_summary,
    compute_verdict,
    macro_f1,
    present_recall,
    score,
    wilson_interval,
)


# --- 합성 데이터 -------------------------------------------------------------


def _manifest() -> dict:
    clips = []
    for dk, strata, split in [
        ("h1", "big_move", "holdout"),
        ("h2", "lick_water_food", "holdout"),
        ("h3", "absent", "holdout"),
        ("h4", "big_move", "holdout"),
    ]:
        clips.append(
            {
                "durable_key": dk,
                "clip_id": f"id-{dk}",
                "strata": strata,
                "split": split,
                "camera_id": "cam-a",
                "capture_date": "2026-07-01",
                "episode_id": f"ep-{dk}",
            }
        )
    return {
        "experiment": "local-vlm-evidence-analyst",
        "strata": ["big_move", "lick_water_food", "absent"],
        "clips": clips,
        "repeat_clips": ["h1"],  # h1 3회
    }


def _obs(presence, visibility="clear", motion="body_translation", objects=None, abstain=False):
    return {
        "schema_version": "local-evidence-analyst-v1",
        "presence_observation": presence,
        "visibility": visibility,
        "motion_extent": motion,
        "body_region_candidates": ["whole"],
        "object_candidates": objects if objects is not None else ["unknown"],
        "evidence_conflicts": [],
        "abstain": abstain,
        "observation": "obs",
    }


def _result(dk, run, strata, split, status="success", obs=None):
    rec = {
        "measured_key": f"{dk}#run{run}",
        "durable_key": dk,
        "clip_id": f"id-{dk}",
        "run_index": run,
        "strata": strata,
        "split": split,
        "status": status,
        "observation": obs,
        "roi_mode": "union_roi",
    }
    return rec


def _gt(dk, presence, visibility="clear", motion="body_translation", objects=None):
    return {
        "durable_key": dk,
        "presence_observation": presence,
        "visibility": visibility,
        "motion_extent": motion,
        "body_region_candidates": ["whole"],
        "object_candidates": objects if objects is not None else ["unknown"],
        "human_uncertain": False,
        "reason": "r",
    }


def _dataset():
    """GT vs pred:
    h1 present/present, h2 present/present, h3 absent/absent, h4 present/absent(오답).
    present recall = 2/3. h1 반복 3회 동일 → consistent. h2 object recall 1.0.
    """
    gt = [
        _gt("h1", "present"),
        _gt("h2", "present", objects=["water_bowl"]),
        _gt("h3", "absent"),
        _gt("h4", "present"),
    ]
    results = [
        _result("h1", 0, "big_move", "holdout", obs=_obs("present")),
        _result("h2", 0, "lick_water_food", "holdout", obs=_obs("present", objects=["water_bowl", "glass"])),
        _result("h3", 0, "absent", "holdout", obs=_obs("absent", motion="none")),
        _result("h4", 0, "big_move", "holdout", obs=_obs("absent", motion="none")),
        # h1 반복 (동일 categorical → consistent)
        _result("h1", 1, "big_move", "holdout", obs=_obs("present")),
        _result("h1", 2, "big_move", "holdout", obs=_obs("present")),
    ]
    return results, gt, _manifest()


# --- 지표 단위 ---------------------------------------------------------------


def test_present_recall() -> None:
    pairs = [("present", "present"), ("present", "present"), ("absent", "absent"), ("present", "absent")]
    assert present_recall(pairs) == pytest.approx(2 / 3)


def test_macro_f1_perfect() -> None:
    pairs = [("a", "a"), ("b", "b"), ("a", "a")]
    assert macro_f1(pairs, ["a", "b"]) == pytest.approx(1.0)


def test_wilson_interval_bounds() -> None:
    low, high = wilson_interval(2, 3)
    assert 0.0 <= low <= 2 / 3 <= high <= 1.0


# --- 통합 score --------------------------------------------------------------


def test_score_completeness() -> None:
    results, gt, manifest = _dataset()
    s = score(results, gt, manifest)
    # 기대 keys = base 4 + repeat h1 2 = 6, 전부 존재
    assert s["completeness"]["expected_keys"] == 6
    assert s["completeness"]["got_keys"] == 6
    assert s["completeness"]["missing"] == 0
    assert s["completeness"]["unexpected"] == 0
    assert s["completeness"]["duplicates"] == 0
    assert s["completeness"]["successes"] == 6


def test_score_quality_numbers() -> None:
    results, gt, manifest = _dataset()
    s = score(results, gt, manifest)
    assert s["quality"]["present_recall"]["point"] == pytest.approx(2 / 3)
    assert s["quality"]["abstain_rate"] == pytest.approx(0.0)
    # object top-k recall: h2 만 실제 object → 1.0
    assert s["quality"]["object_topk_recall"]["point"] == pytest.approx(1.0)


def test_score_repeat_consistency() -> None:
    results, gt, manifest = _dataset()
    s = score(results, gt, manifest)
    assert s["repeat"]["repeated_clips"] == 1
    assert s["repeat"]["consistency"] == pytest.approx(1.0)


def test_repeat_inconsistency_detected() -> None:
    results, gt, manifest = _dataset()
    # h1 run2 를 다른 presence 로 바꿔 불일치 유발
    for r in results:
        if r["measured_key"] == "h1#run2":
            r["observation"] = _obs("uncertain")
    s = score(results, gt, manifest)
    assert s["repeat"]["consistency"] == pytest.approx(0.0)


def test_missing_key_detected() -> None:
    results, gt, manifest = _dataset()
    results = [r for r in results if r["measured_key"] != "h4#run0"]
    s = score(results, gt, manifest)
    assert s["completeness"]["missing"] == 1


def test_duplicate_key_detected() -> None:
    results, gt, manifest = _dataset()
    results.append(dict(results[0]))  # h1#run0 중복
    s = score(results, gt, manifest)
    assert s["completeness"]["duplicates"] == 1


def test_unexpected_key_detected() -> None:
    results, gt, manifest = _dataset()
    results.append(_result("zz", 0, "big_move", "holdout", obs=_obs("present")))
    s = score(results, gt, manifest)
    assert s["completeness"]["unexpected"] == 1


# --- verdict 우선순위 --------------------------------------------------------


def test_verdict_priority_integrity_first() -> None:
    gates = {
        "integrity": False,
        "resource": False,
        "reliability": False,
        "quality": False,
    }
    assert compute_verdict(gates) == "REJECT_INTEGRITY"


def test_verdict_resource_before_reliability() -> None:
    gates = {"integrity": True, "resource": False, "reliability": False, "quality": False}
    assert compute_verdict(gates) == "REJECT_RESOURCE"


def test_verdict_reliability_before_quality() -> None:
    gates = {"integrity": True, "resource": True, "reliability": False, "quality": False}
    assert compute_verdict(gates) == "REJECT_RELIABILITY"


def test_verdict_quality() -> None:
    gates = {"integrity": True, "resource": True, "reliability": True, "quality": False}
    assert compute_verdict(gates) == "REJECT_QUALITY"


def test_verdict_pass() -> None:
    gates = {"integrity": True, "resource": True, "reliability": True, "quality": True}
    assert compute_verdict(gates) == "PASS_LOCAL_EVIDENCE_ANALYST"


def test_verdict_runtime_drift_and_data() -> None:
    assert compute_verdict({"runtime_drift": True}) == "BLOCKED_RUNTIME_DRIFT"
    assert compute_verdict({"data_insufficient": True}) == "BLOCKED_DATA_INSUFFICIENT"


# --- 독립 재계산 일치 --------------------------------------------------------


def test_independent_recompute_agrees() -> None:
    results, gt, manifest = _dataset()
    s = score(results, gt, manifest)
    canon_score = canonical_summary(s)
    canon_recompute = recompute(results, gt, manifest)
    assert canon_score == canon_recompute
    assert canonical_sha256(canon_score) == canonical_sha256(canon_recompute)


def test_recompute_catches_mismatch() -> None:
    # 결과를 훼손하면 두 canonical 이 달라야 한다 (integrity 감지)
    results, gt, manifest = _dataset()
    s = score(results, gt, manifest)
    tampered = [r for r in results if r["measured_key"] != "h2#run0"]
    canon_recompute = recompute(tampered, gt, manifest)
    assert canonical_summary(s) != canon_recompute
