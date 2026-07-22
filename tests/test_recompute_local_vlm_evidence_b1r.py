"""Gate B1R Task 5 — 독립 재계산 검증.

`recompute_local_vlm_evidence_b1r` 는 probe(build_availability/build_episode_candidates_v2)를 import 하지
않고, pool artifact 만 stdlib 로 다시 계산해 aggregate 선언값과 대조한다. 이 테스트는 probe 로 일관된
artifact 를 만든 뒤 독립 재계산이 MATCH 하는지, 변조하면 mismatch(exit 1) 인지 확인한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.recompute_local_vlm_evidence_b1r import canonical_pool_sha256, main, recompute
from scripts.probe_local_vlm_evidence_candidates import aggregate_payload, build_availability, pool_payload
from scripts.local_vlm_evidence_candidates import SourceRow

V2 = "local-vlm-evidence-selector-v2"


def _sr(clip_id, camera_id, **over) -> SourceRow:
    base = dict(
        clip_id=clip_id, camera_id=camera_id,
        captured_at=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
        duration_sec=60.0, run_id=f"run-{clip_id}", assessment_id=None, prelabel_id=None,
        activity_decision="exclude_absent", gecko_visible=False, visibility_confidence=0.5,
        frames_sampled=6, level0_status="ok", level1_status="ok",
        global_motion_series=(0.0,), roi_motion_series=(0.0,), excursion_count=0,
        human_actions=frozenset(), current_gt=None,
    )
    base.update(over)
    return SourceRow(**base)


def _artifacts(rows):
    result = build_availability(rows, selector_version=V2)
    return aggregate_payload(result, "wm"), pool_payload(result)


def _rows():
    return [_sr(f"a{i}", f"cam{i}") for i in range(4)]


def test_recompute_matches_consistent_pool():
    agg, pool = _artifacts(_rows())
    res = recompute(agg, pool)
    assert res["match"] is True
    assert res["reasons"] == []
    assert res["recomputed_pool_sha256"] == pool["pool_sha256"]


def test_recompute_detects_pool_sha_mismatch():
    agg, pool = _artifacts(_rows())
    pool = {**pool, "pool_sha256": "0" * 64}
    res = recompute(agg, pool)
    assert res["match"] is False


def test_recompute_detects_count_mismatch():
    agg, pool = _artifacts(_rows())
    agg = {**agg, "final_allocated_counts": {**agg["final_allocated_counts"], "absent": 999}}
    res = recompute(agg, pool)
    assert res["match"] is False


def test_recompute_detects_clip_overlap():
    agg, pool = _artifacts(_rows())
    pool = {**pool, "pool": pool["pool"] + [pool["pool"][0]]}  # duplicate clip
    res = recompute(agg, pool)
    assert res["match"] is False


def test_canonical_sha_is_independent_of_input_order():
    agg, pool = _artifacts(_rows())
    shuffled = list(reversed(pool["pool"]))
    assert canonical_pool_sha256(shuffled, V2) == canonical_pool_sha256(pool["pool"], V2)


def test_recompute_main_exit_codes(tmp_path):
    agg, pool = _artifacts(_rows())
    ap = tmp_path / "agg.json"
    pp = tmp_path / "pool.json"
    ap.write_text(json.dumps(agg))
    pp.write_text(json.dumps(pool))
    assert main(["--aggregate", str(ap), "--pool", str(pp)]) == 0
    pp.write_text(json.dumps({**pool, "pool_sha256": "0" * 64}))
    assert main(["--aggregate", str(ap), "--pool", str(pp)]) == 1
