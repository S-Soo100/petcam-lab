"""local VLM evidence scorer + 독립 재계산 단위 테스트.

계약(TEST-SHEET §9·§10·§11 / plan Task 6):
confusion·macro/weighted F1·present recall·object top-k·abstain rate·30-clip consistency·
Wilson/bootstrap CI·완전성(missing/dup/unexpected)·verdict 우선순위. 독립 재계산 script 는
scorer 를 import 하지 않고 같은 canonical 값을 낸다 (불일치 → REJECT_INTEGRITY).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.recompute_local_vlm_evidence import recompute
from scripts.score_local_vlm_evidence import (
    MIN_OBJECT_POSITIVE,
    bootstrap_metric_ci,
    canonical_sha256,
    canonical_summary,
    compute_verdict,
    macro_f1,
    present_recall,
    resource_gate,
    score,
    weighted_f1,
    wilson_interval,
)


def _valid_runtime() -> dict:
    """모든 자원 필드가 채워지고 임계값을 통과하는 runtime artifact."""
    return {
        "peak_rss_bytes": 4 * 1024**3,
        "swap_delta_bytes": 0,
        "temp_residual_count": 0,
        "worker_exit_delta": 0,
        "deadline_delay_sec": 0,
        "sustained_clips_per_hour": 100.0,
        "projected_four_camera_p95": 10.0,
    }


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
    s = score(results, gt, manifest, runtime=_valid_runtime())
    # 기대 keys = base 4 + repeat h1 2 = 6, 전부 존재
    assert s["completeness"]["expected_keys"] == 6
    assert s["completeness"]["got_keys"] == 6
    assert s["completeness"]["missing"] == 0
    assert s["completeness"]["unexpected"] == 0
    assert s["completeness"]["duplicates"] == 0
    assert s["completeness"]["successes"] == 6


def test_score_quality_numbers() -> None:
    results, gt, manifest = _dataset()
    s = score(results, gt, manifest, runtime=_valid_runtime())
    assert s["quality"]["present_recall"]["point"] == pytest.approx(2 / 3)
    assert s["quality"]["abstain_rate"] == pytest.approx(0.0)
    # object top-k recall: h2 만 실제 object → 1.0
    assert s["quality"]["object_topk_recall"]["point"] == pytest.approx(1.0)


def test_score_repeat_consistency() -> None:
    results, gt, manifest = _dataset()
    s = score(results, gt, manifest, runtime=_valid_runtime())
    assert s["repeat"]["repeated_clips"] == 1
    assert s["repeat"]["consistency"] == pytest.approx(1.0)


def test_repeat_inconsistency_detected() -> None:
    results, gt, manifest = _dataset()
    # h1 run2 를 다른 presence 로 바꿔 불일치 유발
    for r in results:
        if r["measured_key"] == "h1#run2":
            r["observation"] = _obs("uncertain")
    s = score(results, gt, manifest, runtime=_valid_runtime())
    assert s["repeat"]["consistency"] == pytest.approx(0.0)


def test_missing_key_detected() -> None:
    results, gt, manifest = _dataset()
    results = [r for r in results if r["measured_key"] != "h4#run0"]
    s = score(results, gt, manifest, runtime=_valid_runtime())
    assert s["completeness"]["missing"] == 1


def test_duplicate_key_detected() -> None:
    results, gt, manifest = _dataset()
    results.append(dict(results[0]))  # h1#run0 중복
    s = score(results, gt, manifest, runtime=_valid_runtime())
    assert s["completeness"]["duplicates"] == 1


def test_unexpected_key_detected() -> None:
    results, gt, manifest = _dataset()
    results.append(_result("zz", 0, "big_move", "holdout", obs=_obs("present")))
    s = score(results, gt, manifest, runtime=_valid_runtime())
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
    s = score(results, gt, manifest, runtime=_valid_runtime())
    canon_score = canonical_summary(s)
    canon_recompute = recompute(results, gt, manifest)
    assert canon_score == canon_recompute
    assert canonical_sha256(canon_score) == canonical_sha256(canon_recompute)


def test_recompute_catches_mismatch() -> None:
    # 결과를 훼손하면 두 canonical 이 달라야 한다 (integrity 감지)
    results, gt, manifest = _dataset()
    s = score(results, gt, manifest, runtime=_valid_runtime())
    tampered = [r for r in results if r["measured_key"] != "h2#run0"]
    canon_recompute = recompute(tampered, gt, manifest)
    assert canonical_summary(s) != canon_recompute


# --- Task 5: CI 수학 · coverage · resource gate ------------------------------


def _dataset_without_object_positive():
    results, gt, manifest = _dataset()
    for g in gt:
        g["object_candidates"] = ["unknown"]
    return results, gt, manifest


def test_presence_ci_bootstraps_macro_f1_not_exact_accuracy() -> None:
    # 충분한 표본(20)에서 macro-F1 분포와 per-example accuracy 분포는 확연히 갈린다.
    pairs = (
        [("present", "present")] * 8
        + [("absent", "absent")] * 6
        + [("present", "absent")] * 3
        + [("uncertain", "absent")] * 3
    )
    point = macro_f1(pairs)  # ~0.503
    exact_fn = lambda xs: sum(g == p for g, p in xs) / len(xs)  # noqa: E731  ~0.70
    assert point != pytest.approx(exact_fn(pairs))  # point 부터 다른 지표
    ci = bootstrap_metric_ci(pairs, macro_f1, seed=7, n_boot=500)
    assert ci[0] <= point <= ci[1]
    # 실제 지표(macro F1)를 bootstrap → per-example accuracy CI 와 다르다
    exact_ci = bootstrap_metric_ci(pairs, exact_fn, seed=7, n_boot=500)
    assert ci != exact_ci


def test_visibility_and_motion_have_ci() -> None:
    results, gt, manifest = _dataset()
    s = score(results, gt, manifest, runtime=_valid_runtime())
    assert "ci" in s["quality"]["visibility_weighted_f1"]
    assert "ci" in s["quality"]["motion_macro_f1"]
    for m in ("presence_macro_f1", "visibility_weighted_f1", "motion_macro_f1"):
        lo, hi = s["quality"][m]["ci"]
        assert lo <= s["quality"][m]["point"] <= hi


def test_min_object_positive_is_ten() -> None:
    assert MIN_OBJECT_POSITIVE == 10


def test_zero_object_positive_cannot_pass_quality() -> None:
    results, gt, manifest = _dataset_without_object_positive()
    s = score(results, gt, manifest, runtime=_valid_runtime())
    assert s["coverage"]["object_positive"] == 0
    assert s["gates"]["quality"] is False
    assert s["verdict"] == "REJECT_QUALITY"


def test_object_below_min_cannot_pass_quality() -> None:
    # object-positive 가 1건뿐(<10)이면 완벽 recall 이어도 품질 통과 불가
    results, gt, manifest = _dataset()  # h2 하나만 object-positive
    s = score(results, gt, manifest, runtime=_valid_runtime())
    assert s["coverage"]["object_positive"] == 1
    assert s["gates"]["quality"] is False


def test_runtime_is_mandatory() -> None:
    results, gt, manifest = _dataset()
    with pytest.raises(ValueError, match="RESOURCE_EVIDENCE_MISSING"):
        score(results, gt, manifest, runtime=None)


def test_runtime_missing_field_rejects_resource() -> None:
    results, gt, manifest = _dataset()
    rt = _valid_runtime()
    del rt["peak_rss_bytes"]
    with pytest.raises(ValueError, match="RESOURCE_EVIDENCE_MISSING"):
        score(results, gt, manifest, runtime=rt)


def test_resource_gate_fails_on_bad_metric() -> None:
    results, gt, manifest = _dataset()
    rt = _valid_runtime()
    rt["worker_exit_delta"] = 1  # 인접 worker 종료 drift
    s = score(results, gt, manifest, runtime=rt)
    assert s["gates"]["resource"] is False
    assert s["verdict"] == "REJECT_RESOURCE"


def test_resource_gate_capacity_shortfall_fails() -> None:
    rt = _valid_runtime()
    rt["sustained_clips_per_hour"] = 5.0  # < 2 * projected(10) = 20
    assert resource_gate(rt) is False


def test_by_strata_keys_match_manifest_and_roi_modes_present() -> None:
    results, gt, manifest = _dataset()
    s = score(results, gt, manifest, runtime=_valid_runtime())
    assert set(s["by_strata"]) == set(manifest["strata"])
    assert "union_roi" in s["by_roi_mode"]
    # 각 그룹은 표본 수·점수 필드를 갖는다
    for grp in s["by_strata"].values():
        assert "n" in grp and "presence_macro_f1" in grp


def test_runtime_echoed_in_summary() -> None:
    results, gt, manifest = _dataset()
    rt = _valid_runtime()
    s = score(results, gt, manifest, runtime=rt)
    assert s["runtime"] == rt


# --- Task 7: cross-boundary dry end-to-end (media-free fixture) ---------------

_FX = Path(__file__).resolve().parent / "fixtures" / "local_vlm_evidence_hardened"


def _load_fixture():
    manifest = json.loads((_FX / "manifest.json").read_text())
    gt = json.loads((_FX / "gt.json").read_text())
    runtime = json.loads((_FX / "runtime.json").read_text())
    results = [
        json.loads(line)
        for line in (_FX / "results.jsonl").read_text().splitlines()
        if line.strip()
    ]
    return results, gt, manifest, runtime


def test_hardened_fixture_scores_and_recomputes_identically() -> None:
    results, gt, manifest, runtime = _load_fixture()
    full = score(results, gt, manifest, runtime=runtime, recompute_match=True)
    independent = recompute(results, gt, manifest, runtime)
    # scorer canonical == 독립 재계산 (공유 helper 없이 같은 숫자)
    assert canonical_summary(full) == independent
    assert canonical_sha256(canonical_summary(full)) == canonical_sha256(independent)
    # 자원 gate 는 유효 runtime 으로 통과
    assert full["gates"]["resource"] is True
    # coverage: 6 strata · 양 ROI mode · object-positive 12
    assert set(full["by_strata"]) == set(manifest["strata"])
    assert set(full["by_roi_mode"]) == {"union_roi", "full_frame_no_detection"}
    assert full["coverage"]["object_positive"] == 12
    # 합성 fixture 는 expected key 를 정확히 채운다 (integrity 깨끗)
    assert full["completeness"]["missing"] == 0
    assert full["completeness"]["unexpected"] == 0
    assert full["completeness"]["duplicates"] == 0


def test_hardened_fixture_has_no_production_leakage() -> None:
    # fixture 에 실제 URL/secret/signed URL 이 없어야 한다 (합성 데이터 계약)
    blob = " ".join(
        (_FX / name).read_text()
        for name in ("manifest.json", "gt.json", "results.jsonl", "runtime.json")
    ).lower()
    for banned in ("http://", "https://", "r2.cloudflarestorage", "x-amz-", "signature=", "secret"):
        assert banned not in blob
