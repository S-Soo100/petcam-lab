"""wheel-episode-dedup-shadow 순수 결정론 모듈 단위 테스트.

네트워크·R2·DB 의존 없음. fake numpy frame + synthetic 시그니처만 사용.
(donts/python #13: 네트워크/카메라 의존 테스트는 유닛에서 제외)
"""
import numpy as np

from scripts.wheel_shadow import cohort as co
from scripts.wheel_shadow import grouping as grp
from scripts.wheel_shadow import signatures as sig
from scripts.wheel_shadow.representatives import select_representatives
from scripts.wheel_shadow.representatives import select_representatives as sr
from scripts.wheel_shadow.signatures import ClipSignature


# ----------------------------------------------------------------------------
# Task 1 — signatures
# ----------------------------------------------------------------------------
def _solid(h, w, bgr):
    f = np.zeros((h, w, 3), dtype=np.uint8)
    f[:, :] = bgr
    return f


def test_signature_crop_roi_normalized():
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    frame[10:60, 40:140] = 255  # y 10..60, x 40..140
    roi = sig.RoiBox(x=0.2, y=0.1, w=0.5, h=0.5)  # x40..140, y10..60
    crop = sig.crop_roi(frame, roi)
    assert crop.shape == (50, 100, 3)
    assert crop.mean() == 255.0


def test_signature_ir_vs_day_mode():
    gray = [_solid(20, 20, (128, 128, 128)) for _ in range(3)]  # 무채색
    color = [_solid(20, 20, (10, 200, 30)) for _ in range(3)]   # 채도 높음
    assert sig.ir_mode(gray) == "ir"
    assert sig.ir_mode(color) == "day"


def test_signature_motion_series_and_summary():
    a = _solid(10, 10, (0, 0, 0))
    b = _solid(10, 10, (255, 255, 255))
    series = sig.roi_motion_series([a, b, a])  # 큰 변화 2회
    assert len(series) == 2
    assert series[0] > 0.9
    mean, peak, per = sig.motion_summary(series)
    assert peak >= mean > 0.0


def test_signature_dhash_identical_and_hamming():
    grad = np.tile(np.arange(9, dtype=np.uint8) * 28, (8, 1))
    h1 = sig.dhash(grad)
    h2 = sig.dhash(grad.copy())
    assert h1 == h2
    assert sig.hamming(h1, h2) == 0
    assert sig.hamming(0b1010, 0b0011) == 2


# ----------------------------------------------------------------------------
# Task 2 — grouping
# ----------------------------------------------------------------------------
def _sig(cid, ts, mode="ir", mean=0.20, peak=0.30, ph=0, quality="ok", score=1.0, novelty=False):
    return ClipSignature(cid, ts, 30.0, mode, mean, peak, 0.7, ph, quality, score, novelty, 10)


def test_grouping_time_gap_splits_episodes():
    sigs = [
        _sig("a", "2026-07-19T03:00:00+00:00", ph=0b1111),
        _sig("b", "2026-07-19T03:01:00+00:00", ph=0b1111),
        _sig("c", "2026-07-19T03:21:00+00:00", ph=0b1111),
        _sig("d", "2026-07-19T03:22:00+00:00", ph=0b1111),
    ]
    params = grp.GroupingParams(wheel_motion_floor=0.1, hamming_threshold=4, motion_tolerance=0.1)
    groups, ungrouped = grp.group_clips(sigs, params, select_representatives)
    assert len(groups) == 2
    assert set(groups[0].member_clip_ids) == {"a", "b"}
    assert set(groups[1].member_clip_ids) == {"c", "d"}


def test_grouping_dissimilar_stays_ungrouped_no_overlap():
    sigs = [
        _sig("a", "2026-07-19T03:00:00+00:00", ph=0b0000),
        _sig("b", "2026-07-19T03:01:00+00:00", ph=0b1111_1111),   # hamming 8 > thr → 안 묶임
        _sig("c", "2026-07-19T03:02:00+00:00", ph=0b0000),
    ]
    params = grp.GroupingParams(wheel_motion_floor=0.1, hamming_threshold=3, motion_tolerance=0.1)
    groups, ungrouped = grp.group_clips(sigs, params, select_representatives)
    members = [cid for g in groups for cid in g.member_clip_ids]
    assert len(members) == len(set(members))     # overlap 0
    assert set(groups[0].member_clip_ids) == {"a", "c"}
    assert "b" in ungrouped


def test_grouping_low_motion_or_missing_evidence_ungrouped():
    sigs = [
        _sig("a", "2026-07-19T03:00:00+00:00", mean=0.02),                 # 저모션
        _sig("b", "2026-07-19T03:01:00+00:00", quality="missing"),        # evidence 없음
        _sig("c", "2026-07-19T03:02:00+00:00", mean=0.02),
    ]
    params = grp.GroupingParams(wheel_motion_floor=0.1, hamming_threshold=4, motion_tolerance=0.1)
    groups, ungrouped = grp.group_clips(sigs, params, select_representatives)
    assert groups == []
    assert set(ungrouped) == {"a", "b", "c"}


def test_grouping_deterministic():
    import random
    base = [_sig(f"c{i}", f"2026-07-19T03:{i:02d}:00+00:00", ph=0b1010) for i in range(6)]
    params = grp.GroupingParams(wheel_motion_floor=0.1, hamming_threshold=4, motion_tolerance=0.1)
    shuffled = base[:]
    random.Random(7).shuffle(shuffled)
    g1, u1 = grp.group_clips(base, params, select_representatives)
    g2, u2 = grp.group_clips(shuffled, params, select_representatives)
    assert [g.member_clip_ids for g in g1] == [g.member_clip_ids for g in g2]
    assert u1 == u2


# --- v1.1 boundary-fix: run 전체 span(전체 길이) 10분 계약 회귀 ---
def test_grouping_chain_cannot_exceed_total_episode_span():
    # 5분 간격 5개 → inter-gap은 모두 ≤600이지만 a→e 전체 span 1200초.
    # 전체 길이 경계가 있으면 {a,b,c}(0~600)와 {d,e}로 분리돼야 한다.
    sigs = [
        _sig("a", "2026-07-19T03:00:00+00:00", ph=0b1111),
        _sig("b", "2026-07-19T03:05:00+00:00", ph=0b1111),
        _sig("c", "2026-07-19T03:10:00+00:00", ph=0b1111),
        _sig("d", "2026-07-19T03:15:00+00:00", ph=0b1111),
        _sig("e", "2026-07-19T03:20:00+00:00", ph=0b1111),
    ]
    params = grp.GroupingParams(
        max_inter_clip_gap_sec=600,
        max_episode_span_sec=600,
        wheel_motion_floor=0.1,
        hamming_threshold=4,
        motion_tolerance=0.1,
    )
    groups, ungrouped = grp.group_clips(sigs, params, select_representatives)
    assert [set(g.member_clip_ids) for g in groups] == [
        {"a", "b", "c"},
        {"d", "e"},
    ]
    assert ungrouped == []
    assert all(grp.group_span_sec(g) <= 600 for g in groups)


def test_grouping_exact_episode_span_stays_one_group():
    # a→c 정확히 600초 = 같은 run 포함 (경계 inclusive).
    sigs = [
        _sig("a", "2026-07-19T03:00:00+00:00", ph=0b1111),
        _sig("b", "2026-07-19T03:05:00+00:00", ph=0b1111),
        _sig("c", "2026-07-19T03:10:00+00:00", ph=0b1111),
    ]
    params = grp.GroupingParams(
        max_inter_clip_gap_sec=600,
        max_episode_span_sec=600,
        wheel_motion_floor=0.1,
        hamming_threshold=4,
        motion_tolerance=0.1,
    )
    groups, ungrouped = grp.group_clips(sigs, params, select_representatives)
    assert [set(g.member_clip_ids) for g in groups] == [{"a", "b", "c"}]
    assert ungrouped == []
    assert grp.group_span_sec(groups[0]) == 600.0


def test_grouping_over_episode_span_splits_run():
    # a→c 601초 > 600 = 분리. c는 새 run 단독 → ungrouped.
    sigs = [
        _sig("a", "2026-07-19T03:00:00+00:00", ph=0b1111),
        _sig("b", "2026-07-19T03:05:00+00:00", ph=0b1111),
        _sig("c", "2026-07-19T03:10:01+00:00", ph=0b1111),
    ]
    params = grp.GroupingParams(
        max_inter_clip_gap_sec=600,
        max_episode_span_sec=600,
        wheel_motion_floor=0.1,
        hamming_threshold=4,
        motion_tolerance=0.1,
    )
    groups, ungrouped = grp.group_clips(sigs, params, select_representatives)
    assert [set(g.member_clip_ids) for g in groups] == [{"a", "b"}]
    assert ungrouped == ["c"]
    assert all(grp.group_span_sec(g) <= 600 for g in groups)


# ----------------------------------------------------------------------------
# Task 3 — representatives
# ----------------------------------------------------------------------------
def _m(cid, score, peak, ph):
    return ClipSignature(cid, "2026-07-19T03:00:00+00:00", 30.0, "ir", 0.2, peak, 0.7, ph, "ok", score, False, 10)


def test_representative_three_distinct_axes():
    members = [
        _m("best_ev", score=9.0, peak=0.2, ph=0b0000_0000),
        _m("big_mot", score=1.0, peak=0.9, ph=0b0000_0001),
        _m("novel", score=1.0, peak=0.3, ph=0b1111_1111_1111),  # 시각적으로 매우 다름
        _m("dup", score=1.0, peak=0.25, ph=0b0000_0000),
    ]
    reps = sr(members, max_reps=3, novelty_min_hamming=4)
    assert reps[0] == "best_ev"
    assert reps[1] == "big_mot"
    assert reps[2] == "novel"
    assert len(reps) == 3


def test_representative_caps_at_two_when_no_novelty():
    members = [
        _m("best_ev", score=9.0, peak=0.2, ph=0b0000),
        _m("big_mot", score=1.0, peak=0.9, ph=0b0001),
        _m("similar", score=1.0, peak=0.3, ph=0b0000),
    ]
    reps = sr(members, max_reps=3, novelty_min_hamming=6)
    assert len(reps) == 2
    assert set(reps) == {"best_ev", "big_mot"}


# ----------------------------------------------------------------------------
# Task 4 — cohort SHA
# ----------------------------------------------------------------------------
def test_cohort_sha_is_order_independent_for_ids():
    a = co.build_frozen_cohort(
        camera_name="P4 Cam (dev)", camera_id="cam-uuid",
        started_at_range=["2026-07-19T00:00:00+00:00", "2026-07-22T00:00:00+00:00"],
        clips=[{"clip_id": "b", "run_id": "r2"}, {"clip_id": "a", "run_id": "r1"}],
        known_wheel_gt_clip_ids=["z", "y"],
        gt_snapshot_watermark="2026-07-23T00:00:00+00:00",
    )
    b = co.build_frozen_cohort(
        camera_name="P4 Cam (dev)", camera_id="cam-uuid",
        started_at_range=["2026-07-19T00:00:00+00:00", "2026-07-22T00:00:00+00:00"],
        clips=[{"clip_id": "a", "run_id": "r1"}, {"clip_id": "b", "run_id": "r2"}],
        known_wheel_gt_clip_ids=["y", "z"],
        gt_snapshot_watermark="2026-07-23T00:00:00+00:00",
    )
    assert a["cohort_sha256"] == b["cohort_sha256"]
    assert a["clip_ids"] == ["a", "b"]


def test_cohort_sha_changes_with_content():
    a = co.build_frozen_cohort("cam", "id", ["s", "e"], [{"clip_id": "a", "run_id": "r"}], [], "w")
    b = co.build_frozen_cohort("cam", "id", ["s", "e"], [{"clip_id": "a", "run_id": "r2"}], [], "w")
    assert a["cohort_sha256"] != b["cohort_sha256"]
