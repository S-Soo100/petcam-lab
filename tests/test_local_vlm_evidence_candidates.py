"""Gate B1 Task 1 — Local VLM evidence 후보 selector 순수 로직 테스트.

이 테스트는 DB 를 건드리지 않는다. `scripts/local_vlm_evidence_candidates.py` 의
결정론·priority·episode dedup·identity 계약만 검증한다 (설계 §6, plan Gate B1 Task 1).

RED 단계: 아직 모듈이 없으므로 import 실패로 떨어진다.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timezone

import pytest

from scripts.local_vlm_evidence_candidates import (
    STRATA,
    STRATUM_CONFLICT_PRIORITY,
    Candidate,
    Quantiles,
    SourceRow,
    build_episode_candidates,
    candidates_canonical_json,
    candidates_sha256,
    classify_candidate,
    cluster_episodes,
    compute_quantiles,
    nearest_rank,
    series_values,
    source_metrics,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def dt(text: str) -> datetime:
    """ISO8601(Z) -> tz-aware UTC datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def source(**overrides) -> SourceRow:
    base = dict(
        clip_id="clip",
        camera_id="cam",
        captured_at=dt("2026-07-22T10:00:00Z"),
        duration_sec=60.0,
        run_id="run",
        assessment_id="assess",
        prelabel_id="pre",
        activity_decision="active",
        gecko_visible=True,
        visibility_confidence=0.9,
        frames_sampled=6,
        level0_status="ok",
        level1_status="ok",
        global_motion_series=(0.1, 0.2, 0.3),
        roi_motion_series=(0.1, 0.2, 0.3),
        excursion_count=0,
        human_actions=frozenset(),
        current_gt=None,
    )
    base.update(overrides)
    return SourceRow(**base)


def row(clip_id: str, ts: str, **overrides) -> SourceRow:
    return source(clip_id=clip_id, captured_at=dt(ts), **overrides)


def quantiles() -> Quantiles:
    return Quantiles(global_p90_q50=0.5, global_p90_q75=0.8, roi_p90_q50=0.5)


# ---------------------------------------------------------------------------
# case 1 — series_values validation
# ---------------------------------------------------------------------------
def test_series_values_extracts_value_from_point_objects():
    assert series_values([{"t": 0.0, "value": 0.5}, {"t": 1.0, "value": 1.5}]) == (0.5, 1.5)


def test_series_values_accepts_bare_numbers():
    assert series_values([0.5, 1, 2.5]) == (0.5, 1.0, 2.5)


def test_series_values_empty_is_empty_tuple():
    assert series_values([]) == ()


@pytest.mark.parametrize(
    "bad",
    [
        [{"t": 0, "value": -1.0}],        # negative
        [{"t": 0, "value": True}],        # bool (subclass of int)
        [{"t": 0, "value": "x"}],         # string
        [{"t": 0, "value": float("nan")}],  # NaN
        [{"t": 0, "value": float("inf")}],  # inf
        [True],                            # bare bool
    ],
)
def test_series_values_rejects_invalid_points(bad):
    with pytest.raises(ValueError):
        series_values(bad)


# ---------------------------------------------------------------------------
# case 2 — nearest_rank determinism
# ---------------------------------------------------------------------------
def test_nearest_rank_p50_p90():
    values = [1.0, 2.0, 3.0, 4.0]
    assert nearest_rank(values, 0.50) == 2.0   # ceil(0.5*4)=2 -> s[1]
    assert nearest_rank(values, 0.90) == 4.0   # ceil(0.9*4)=4 -> s[3]


def test_nearest_rank_is_order_invariant():
    assert nearest_rank([4.0, 1.0, 3.0, 2.0], 0.90) == nearest_rank([1.0, 2.0, 3.0, 4.0], 0.90)


def test_nearest_rank_empty_is_zero():
    assert nearest_rank([], 0.50) == 0.0


def test_source_metrics_keys_and_values():
    m = source_metrics(source(global_motion_series=(0.1, 0.9), roi_motion_series=(0.2, 0.4), excursion_count=3))
    assert set(m) == {"global_p50", "global_p90", "roi_p50", "roi_p90", "excursion_count"}
    assert m["global_p90"] == 0.9
    assert m["excursion_count"] == 3.0


# ---------------------------------------------------------------------------
# case 3 — 30-minute rolling episode clustering (crosses fixed bucket boundary)
# ---------------------------------------------------------------------------
def test_episode_clustering_crosses_fixed_bucket_boundary():
    rows = [row("a", "2026-07-22T10:29:00Z"), row("b", "2026-07-22T10:31:00Z")]
    episodes = cluster_episodes(rows)
    assert episodes["a"] == episodes["b"]


def test_episode_clustering_gap_over_30min_starts_new_episode():
    rows = [
        row("a", "2026-07-22T10:29:00Z"),
        row("b", "2026-07-22T10:31:00Z"),
        row("c", "2026-07-22T11:02:00Z"),  # 31 min after b
    ]
    episodes = cluster_episodes(rows)
    assert episodes["a"] == episodes["b"]
    assert episodes["c"] != episodes["b"]


def test_episode_clustering_separates_cameras():
    rows = [
        row("a", "2026-07-22T10:29:00Z", camera_id="cam1"),
        row("b", "2026-07-22T10:31:00Z", camera_id="cam2"),
    ]
    episodes = cluster_episodes(rows)
    assert episodes["a"] != episodes["b"]


# ---------------------------------------------------------------------------
# case 4 — single stratum assignment (hardcase wins over big_move)
# ---------------------------------------------------------------------------
def test_stratum_priority_is_single_assignment():
    candidate = classify_candidate(
        source(activity_decision="active", level1_status="no_bbox"), quantiles()
    )
    assert candidate is not None
    assert candidate.stratum == "hardcase"


def test_hardcase_beats_big_move_even_with_excursions():
    # matches hardcase (no_bbox + visible) AND big_move (excursion_count>0) -> hardcase only
    candidate = classify_candidate(
        source(level1_status="no_bbox", gecko_visible=True, excursion_count=5), quantiles()
    )
    assert candidate.stratum == "hardcase"


def test_absent_from_activity_decision():
    candidate = classify_candidate(source(activity_decision="exclude_absent", gecko_visible=False), quantiles())
    assert candidate.stratum == "absent"


def test_lick_food_from_human_action():
    candidate = classify_candidate(
        source(activity_decision="active", level1_status="ok", gecko_visible=True,
               human_actions=frozenset({"drinking"}), excursion_count=0,
               global_motion_series=(0.0,), roi_motion_series=(0.0,)),
        quantiles(),
    )
    assert candidate.stratum == "lick_water_food"


def test_rest_micro_localized_motion():
    q = Quantiles(global_p90_q50=0.5, global_p90_q75=0.8, roi_p90_q50=0.3)
    candidate = classify_candidate(
        source(activity_decision="unknown_free", level1_status="ok", gecko_visible=True,
               excursion_count=0, global_motion_series=(0.1,), roi_motion_series=(0.9,)),
        q,
    )
    # global_p90=0.1 <= 0.5, roi_p90=0.9 >= 0.3, visible -> rest_micro
    assert candidate.stratum == "rest_micro"


def test_no_signal_returns_none():
    candidate = classify_candidate(
        source(activity_decision="active", level1_status="ok", gecko_visible=True,
               excursion_count=0, frames_sampled=6,
               global_motion_series=(0.0,), roi_motion_series=(0.0,),
               human_actions=frozenset(), current_gt=None),
        Quantiles(global_p90_q50=0.5, global_p90_q75=0.8, roi_p90_q50=0.5),
    )
    assert candidate is None


# ---------------------------------------------------------------------------
# case 5 — full pipeline order invariance (identical JSON bytes + SHA)
# ---------------------------------------------------------------------------
def _diverse_rows() -> list[SourceRow]:
    rows = []
    # big_move episodes on cam1
    for i in range(4):
        rows.append(row(f"bm{i}", f"2026-07-22T09:{i:02d}:00Z", camera_id="cam1",
                        excursion_count=2 + i, global_motion_series=(0.9, 0.95)))
    # absent episodes on cam2
    for i in range(3):
        rows.append(row(f"ab{i}", f"2026-07-22T12:{i:02d}:00Z", camera_id="cam2",
                        activity_decision="exclude_absent", gecko_visible=False,
                        global_motion_series=(0.0,), roi_motion_series=(0.0,)))
    # hardcase on cam1 later day
    rows.append(row("hc0", "2026-07-23T01:00:00Z", camera_id="cam1",
                    level1_status="no_bbox", gecko_visible=True))
    # lick on cam2
    rows.append(row("lk0", "2026-07-23T02:00:00Z", camera_id="cam2",
                    human_actions=frozenset({"licking"}),
                    global_motion_series=(0.1,), roi_motion_series=(0.1,)))
    return rows


def test_pipeline_is_order_invariant():
    rows = _diverse_rows()
    base = build_episode_candidates(rows)
    base_json = candidates_canonical_json(base)
    base_sha = candidates_sha256(base)

    for seed in (1, 7, 42):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        again = build_episode_candidates(shuffled)
        assert candidates_canonical_json(again) == base_json
        assert candidates_sha256(again) == base_sha


def test_pipeline_dedups_clips_and_episodes():
    rows = _diverse_rows()
    cands = build_episode_candidates(rows)
    clip_ids = [c.clip_id for c in cands]
    episode_keys = [c.episode_key for c in cands]
    assert len(clip_ids) == len(set(clip_ids))       # no clip twice
    assert len(episode_keys) == len(set(episode_keys))  # one clip per episode
    assert all(c.stratum in STRATA for c in cands)


def test_conflict_priority_picks_higher_stratum_representative():
    # two clips in one episode (same camera, 2 min apart): one hardcase, one big_move
    rows = [
        row("h", "2026-07-22T10:00:00Z", camera_id="camX", level1_status="no_bbox", gecko_visible=True),
        row("b", "2026-07-22T10:02:00Z", camera_id="camX", excursion_count=9,
            global_motion_series=(0.99,)),
    ]
    cands = build_episode_candidates(rows)
    assert len(cands) == 1               # one episode -> one representative
    assert cands[0].stratum == "hardcase"
    assert cands[0].clip_id == "h"


def test_priority_score_normalized_over_stratum():
    # low-motion filler pulls the global median down so the three high-motion clips
    # land above q75 -> unambiguous big_move (distinct cameras -> distinct episodes).
    rows = []
    for i in range(5):
        rows.append(row(f"f{i}", "2026-07-22T10:00:00Z", camera_id=f"f{i}",
                        global_motion_series=(0.0,), roi_motion_series=(0.0,)))
    rows.append(row("b0", "2026-07-22T10:00:00Z", camera_id="c0", excursion_count=1,
                    global_motion_series=(0.9,), roi_motion_series=(0.0,)))
    rows.append(row("b1", "2026-07-22T10:00:00Z", camera_id="c1", excursion_count=5,
                    global_motion_series=(0.9,), roi_motion_series=(0.0,)))
    rows.append(row("b2", "2026-07-22T10:00:00Z", camera_id="c2", excursion_count=3,
                    global_motion_series=(0.9,), roi_motion_series=(0.0,)))
    cands = [c for c in build_episode_candidates(rows) if c.stratum == "big_move"]
    scores = sorted((c.priority_score for c in cands), reverse=True)
    assert scores == [1.0, 0.5, 0.0]


# ---------------------------------------------------------------------------
# case 6 — SourceRow rejects model output fields
# ---------------------------------------------------------------------------
def test_source_row_rejects_model_output_fields():
    with pytest.raises(TypeError):
        SourceRow(  # type: ignore[call-arg]
            clip_id="c", camera_id="cam", captured_at=dt("2026-07-22T10:00:00Z"),
            duration_sec=60.0, run_id="r", assessment_id=None, prelabel_id=None,
            activity_decision=None, gecko_visible=None, visibility_confidence=None,
            frames_sampled=None, level0_status="ok", level1_status="ok",
            global_motion_series=(), roi_motion_series=(), excursion_count=0,
            human_actions=frozenset(), current_gt=None,
            prediction="moving",  # model output must not be accepted
        )


def test_source_row_rejects_reasoning_field():
    with pytest.raises(TypeError):
        SourceRow(  # type: ignore[call-arg]
            clip_id="c", camera_id="cam", captured_at=dt("2026-07-22T10:00:00Z"),
            duration_sec=60.0, run_id="r", assessment_id=None, prelabel_id=None,
            activity_decision=None, gecko_visible=None, visibility_confidence=None,
            frames_sampled=None, level0_status="ok", level1_status="ok",
            global_motion_series=(), roi_motion_series=(), excursion_count=0,
            human_actions=frozenset(), current_gt=None,
            reasoning="the gecko is drinking",
        )


# ---------------------------------------------------------------------------
# identity determinism
# ---------------------------------------------------------------------------
def test_selection_identity_is_deterministic():
    a = classify_candidate(source(clip_id="z", level1_status="no_bbox"), quantiles())
    b = classify_candidate(source(clip_id="z", level1_status="no_bbox"), quantiles())
    assert a.selection_identity_sha256 == b.selection_identity_sha256
    assert len(a.selection_identity_sha256) == 64  # sha256 hex


def test_conflict_priority_constant_ordering():
    assert STRATUM_CONFLICT_PRIORITY == (
        "hardcase", "wheel_object", "lick_water_food", "rest_micro", "big_move", "absent",
    )
    assert set(STRATUM_CONFLICT_PRIORITY) == set(STRATA)


def test_compute_quantiles_only_uses_level0_ok():
    rows = [
        source(clip_id="ok1", level0_status="ok", global_motion_series=(0.2,), roi_motion_series=(0.2,)),
        source(clip_id="ok2", level0_status="ok", global_motion_series=(0.8,), roi_motion_series=(0.8,)),
        source(clip_id="bad", level0_status="no_decodable_frames",
               global_motion_series=(99.0,), roi_motion_series=(99.0,)),
    ]
    q = compute_quantiles(rows)
    # the 99.0 outlier from a non-ok row must not leak into thresholds
    assert q.global_p90_q75 <= 0.8
    assert q.roi_p90_q50 <= 0.8
