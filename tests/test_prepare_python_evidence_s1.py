"""Tests for the Python Evidence S1 throughput-benchmark preparation.

이 스크립트는 production DB 를 read-only 로 읽어 32-clip covered-subset workload 와
influx snapshot 을 **결정론적으로** 사전등록한다. 순수 선택/집계 함수는 Supabase 없이
dict fixture 로 검증한다(=production 접근 0). accuracy GT 는 보지 않는다.

계약(plan Frozen workload):
  - camera allowlist = 5b3ea7aa, f6599924 (S1 covered subset). 90119209 일반화 금지.
  - 5b3ea7aa present 8 + absent 8, f6599924 present 16 (absent 는 가용 0 = 제약 기록).
  - 각 stratum 안에서 duration quartile 균등, deterministic seed 20260717.
  - 축소 manifest = 32 중 stratum·quartile 유지한 deterministic 16.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import scripts.prepare_python_evidence_s1 as prep


UTC = timezone.utc
CAM_A = "5b3ea7aa-1111-4222-8333-444455556666"  # short 5b3ea7aa (allowlisted)
CAM_B = "f6599924-1111-4222-8333-444455556666"  # short f6599924 (allowlisted)
CAM_X = "90119209-1111-4222-8333-444455556666"  # short 90119209 (NOT allowlisted)


# --------------------------------------------------------------------------
# fixture helpers — production row shapes (dict) 를 최소로 재현
# --------------------------------------------------------------------------

def _clip(cid, cam, dur, *, r2_key="clips/x.mp4"):
    return {"id": cid, "camera_id": cam, "started_at": "2026-07-15T12:00:00Z",
            "duration_sec": dur, "r2_key": r2_key}


def _prelabel(pid, cid, *, frames=12, bbox=None):
    return {"id": pid, "clip_id": cid, "frames_sampled": frames, "gecko_bbox": bbox,
            "checkpoint_sha256": "a" * 64, "sampler_version": "even-uniform-v1",
            "schema_version": "gate-evidence-v1", "model_version": "gecko_v2"}


def _assessment(cid, pid, *, policy="activity-v1", decision="active"):
    return {"id": f"a-{cid}", "clip_id": cid, "prelabel_id": pid,
            "policy_version": policy, "decision": decision}


def _triple(cid, cam, dur, *, frames=12, bbox=None, policy="activity-v1", r2_key="clips/x.mp4"):
    """한 clip 의 (motion_clip, prelabel, assessment) 3행을 만든다."""
    pid = f"p-{cid}"
    return (_clip(cid, cam, dur, r2_key=r2_key),
            _prelabel(pid, cid, frames=frames, bbox=bbox),
            _assessment(cid, pid, policy=policy))


def _rows(triples):
    clips = [t[0] for t in triples]
    prelabels = [t[1] for t in triples]
    assessments = [t[2] for t in triples]
    return clips, prelabels, assessments


def _present_bbox():
    return {"x": 1, "y": 2, "w": 30, "h": 40}


def build_full_eligible():
    """32-clip 선택이 성공하도록 넉넉한 eligible pool 을 만든다.

    5b3ea7aa: present 12 (dur 1..12) + absent 10 (dur 1..10)
    f6599924: present 20 (dur 1..20), absent 0 (제약)
    """
    triples = []
    for i in range(1, 13):
        triples.append(_triple(f"A-pres-{i:02d}", CAM_A, float(i), bbox=_present_bbox()))
    for i in range(1, 11):
        triples.append(_triple(f"A-abs-{i:02d}", CAM_A, float(i), bbox=None))
    for i in range(1, 21):
        triples.append(_triple(f"B-pres-{i:02d}", CAM_B, float(i), bbox=_present_bbox()))
    clips, prelabels, assessments = _rows(triples)
    return prep.eligible_from_rows(clips, prelabels, assessments)


# --------------------------------------------------------------------------
# eligibility filter
# --------------------------------------------------------------------------

def test_camera_allowlist_excludes_non_covered_camera():
    triples = [
        _triple("keep-A", CAM_A, 5.0, bbox=_present_bbox()),
        _triple("drop-X", CAM_X, 5.0, bbox=_present_bbox()),  # 90119209 배제
    ]
    clips, prelabels, assessments = _rows(triples)
    eligible = prep.eligible_from_rows(clips, prelabels, assessments)
    ids = {e.clip_id for e in eligible}
    assert ids == {"keep-A"}
    assert all(e.camera_short in prep.CAMERA_ALLOWLIST for e in eligible)


def test_requires_current_activity_v1_assessment():
    triples = [
        _triple("has-v1", CAM_A, 5.0, bbox=_present_bbox(), policy="activity-v1"),
        _triple("wrong-policy", CAM_A, 5.0, bbox=_present_bbox(), policy="activity-v0"),
    ]
    clips, prelabels, assessments = _rows(triples)
    # 세 번째 clip: assessment 자체가 없음
    clips.append(_clip("no-assess", CAM_A, 5.0))
    prelabels.append(_prelabel("p-no-assess", "no-assess", bbox=_present_bbox()))
    eligible = prep.eligible_from_rows(clips, prelabels, assessments)
    assert {e.clip_id for e in eligible} == {"has-v1"}


def test_requires_frames_sampled_at_least_six():
    triples = [
        _triple("ok6", CAM_A, 5.0, frames=6, bbox=_present_bbox()),
        _triple("low5", CAM_A, 5.0, frames=5, bbox=_present_bbox()),
        _triple("zero", CAM_A, 5.0, frames=0, bbox=_present_bbox()),
    ]
    clips, prelabels, assessments = _rows(triples)
    eligible = prep.eligible_from_rows(clips, prelabels, assessments)
    assert {e.clip_id for e in eligible} == {"ok6"}


def test_requires_r2_key_present():
    triples = [
        _triple("has-key", CAM_A, 5.0, bbox=_present_bbox(), r2_key="clips/y.mp4"),
        _triple("no-key", CAM_A, 5.0, bbox=_present_bbox(), r2_key=""),
        _triple("null-key", CAM_A, 5.0, bbox=_present_bbox(), r2_key=None),
    ]
    clips, prelabels, assessments = _rows(triples)
    eligible = prep.eligible_from_rows(clips, prelabels, assessments)
    assert {e.clip_id for e in eligible} == {"has-key"}


def test_bbox_stratum_derived_from_gecko_bbox():
    triples = [
        _triple("pres", CAM_A, 5.0, bbox=_present_bbox()),
        _triple("abs", CAM_A, 5.0, bbox=None),
    ]
    clips, prelabels, assessments = _rows(triples)
    eligible = {e.clip_id: e.bbox_stratum for e in prep.eligible_from_rows(clips, prelabels, assessments)}
    assert eligible == {"pres": "present", "abs": "absent"}


def test_eligible_never_carries_r2_key():
    """artifact leak 방지: EligibleClip 은 r2_key 를 보관하지 않는다."""
    e = build_full_eligible()[0]
    assert not hasattr(e, "r2_key")
    # dataclass 필드에도 없어야 한다
    assert "r2_key" not in getattr(e, "__slots__", ())


# --------------------------------------------------------------------------
# deterministic stratified selection
# --------------------------------------------------------------------------

def test_select_workload_hits_exact_strata_counts():
    wl = prep.select_workload(build_full_eligible())
    assert len(wl.selected) == 32
    counts = {}
    for c in wl.selected:
        counts[(c.camera_short, c.bbox_stratum)] = counts.get((c.camera_short, c.bbox_stratum), 0) + 1
    assert counts == {
        ("5b3ea7aa", "present"): 8,
        ("5b3ea7aa", "absent"): 8,
        ("f6599924", "present"): 16,
    }


def test_selection_spread_evenly_across_quartiles():
    wl = prep.select_workload(build_full_eligible())
    per_q = {}
    for c in wl.selected:
        key = (c.camera_short, c.bbox_stratum, c.quartile)
        per_q[key] = per_q.get(key, 0) + 1
    # 5b3ea7aa present 8 -> 2/quartile ; f6599924 present 16 -> 4/quartile
    assert per_q[("5b3ea7aa", "present", 1)] == 2
    assert per_q[("5b3ea7aa", "present", 4)] == 2
    assert per_q[("f6599924", "present", 1)] == 4
    assert per_q[("f6599924", "present", 4)] == 4
    assert all(q in (1, 2, 3, 4) for (_, _, q) in per_q)


def test_selection_is_deterministic_across_calls_and_input_order():
    eligible = build_full_eligible()
    a = prep.select_workload(eligible)
    shuffled = list(reversed(eligible))
    b = prep.select_workload(shuffled)
    assert [c.clip_id for c in a.selected] == [c.clip_id for c in b.selected]


def test_different_seed_changes_selection_but_not_counts():
    eligible = build_full_eligible()
    a = prep.select_workload(eligible, seed="20260717")
    b = prep.select_workload(eligible, seed="99999999")
    assert len(a.selected) == len(b.selected) == 32
    assert [c.clip_id for c in a.selected] != [c.clip_id for c in b.selected]


def test_insufficient_stratum_fails_closed():
    # 5b3ea7aa present 만 5개 (target 8 미달) -> 나머지 stratum 은 충분히 준다
    triples = []
    for i in range(1, 6):
        triples.append(_triple(f"A-pres-{i}", CAM_A, float(i), bbox=_present_bbox()))
    for i in range(1, 11):
        triples.append(_triple(f"A-abs-{i}", CAM_A, float(i), bbox=None))
    for i in range(1, 21):
        triples.append(_triple(f"B-pres-{i}", CAM_B, float(i), bbox=_present_bbox()))
    clips, prelabels, assessments = _rows(triples)
    eligible = prep.eligible_from_rows(clips, prelabels, assessments)
    with pytest.raises(prep.PrepContractError, match="insufficient"):
        prep.select_workload(eligible)


def test_missing_stratum_fails_closed():
    # 5b3ea7aa absent 0개
    triples = []
    for i in range(1, 13):
        triples.append(_triple(f"A-pres-{i}", CAM_A, float(i), bbox=_present_bbox()))
    for i in range(1, 21):
        triples.append(_triple(f"B-pres-{i}", CAM_B, float(i), bbox=_present_bbox()))
    clips, prelabels, assessments = _rows(triples)
    eligible = prep.eligible_from_rows(clips, prelabels, assessments)
    with pytest.raises(prep.PrepContractError):
        prep.select_workload(eligible)


def test_duplicate_clip_id_rejected():
    eligible = build_full_eligible()
    dup = eligible + [eligible[0]]
    with pytest.raises(prep.PrepContractError, match="duplicate"):
        prep.select_workload(dup)


# --------------------------------------------------------------------------
# reduced 16-clip subset (D / CPU 비교용)
# --------------------------------------------------------------------------

def test_reduced_subset_is_16_and_preserves_strata_quartile():
    wl = prep.select_workload(build_full_eligible())
    reduced_ids = set(wl.reduced_clip_ids)
    assert len(reduced_ids) == 16
    selected_ids = {c.clip_id for c in wl.selected}
    assert reduced_ids <= selected_ids  # subset

    def per_key(ids):
        d = {}
        for c in wl.selected:
            if c.clip_id in ids:
                k = (c.camera_short, c.bbox_stratum, c.quartile)
                d[k] = d.get(k, 0) + 1
        return d

    reduced_per = per_key(reduced_ids)
    # 5b3ea7aa present: 선택 2/quartile -> 축소 1/quartile
    assert reduced_per[("5b3ea7aa", "present", 1)] == 1
    assert reduced_per[("5b3ea7aa", "present", 4)] == 1
    # f6599924 present: 선택 4/quartile -> 축소 2/quartile
    assert reduced_per[("f6599924", "present", 1)] == 2
    # stratum 합
    stratum_totals = {}
    for c in wl.selected:
        if c.clip_id in reduced_ids:
            stratum_totals[(c.camera_short, c.bbox_stratum)] = (
                stratum_totals.get((c.camera_short, c.bbox_stratum), 0) + 1)
    assert stratum_totals == {
        ("5b3ea7aa", "present"): 4,
        ("5b3ea7aa", "absent"): 4,
        ("f6599924", "present"): 8,
    }


def test_reduced_is_deterministic():
    a = prep.select_workload(build_full_eligible())
    b = prep.select_workload(build_full_eligible())
    assert a.reduced_clip_ids == b.reduced_clip_ids


# --------------------------------------------------------------------------
# stable JSON manifest — hashing 대상이므로 canonical/재현 가능해야 한다
# --------------------------------------------------------------------------

def _as_of():
    return datetime(2026, 7, 17, 3, 0, 0, tzinfo=UTC)


def test_manifest_is_stable_and_self_hashing():
    wl = prep.select_workload(build_full_eligible())
    m1 = prep.workload_to_manifest(wl, as_of=_as_of())
    m2 = prep.workload_to_manifest(wl, as_of=_as_of())
    assert json.dumps(m1, sort_keys=True) == json.dumps(m2, sort_keys=True)
    # content hash 는 payload(자기 자신 제외) 로 계산되고 재현 가능
    assert m1["content_sha256"] == m2["content_sha256"]
    assert len(m1["content_sha256"]) == 64


def test_manifest_records_seed_targets_and_absent_constraint():
    wl = prep.select_workload(build_full_eligible())
    m = prep.workload_to_manifest(wl, as_of=_as_of())
    assert m["seed"] == "20260717"
    assert m["camera_allowlist"] == list(prep.CAMERA_ALLOWLIST)
    # f6599924 absent 가용 0 = 제약이 기록되어야 한다
    strata = {(s["camera_short"], s["bbox_stratum"]): s for s in m["strata"]}
    assert strata[("f6599924", "absent")]["available"] == 0
    assert strata[("f6599924", "absent")]["target"] == 0
    assert strata[("5b3ea7aa", "present")]["target"] == 8
    assert len(m["clips"]) == 32


def test_manifest_clips_never_expose_r2_key():
    wl = prep.select_workload(build_full_eligible())
    m = prep.workload_to_manifest(wl, as_of=_as_of())
    blob = json.dumps(m)
    assert "r2_key" not in blob
    assert "clips/" not in blob  # r2 object path leak 방지
    for c in m["clips"]:
        assert set(c.keys()) == {"clip_id", "camera_short", "duration_sec", "bbox_stratum",
                                 "quartile", "in_reduced"}


def test_manifest_input_order_independent():
    eligible = build_full_eligible()
    m1 = prep.workload_to_manifest(prep.select_workload(eligible), as_of=_as_of())
    m2 = prep.workload_to_manifest(prep.select_workload(list(reversed(eligible))), as_of=_as_of())
    assert m1["content_sha256"] == m2["content_sha256"]


# --------------------------------------------------------------------------
# influx snapshot — 유입량 (projected 4-camera p95 계약)
# --------------------------------------------------------------------------

def _clip_at(cam, iso):
    return {"camera_id": cam, "started_at": iso}


def test_influx_projected_four_camera_formula():
    # 2 cameras, 한 시간에 총 10 clip 짜리 버킷을 만들어 p95≈10 이 되게 한다
    rows = []
    base = "2026-07-15T0{h}:{m:02d}:00Z"
    for h in range(0, 5):
        for m in range(0, 5):
            rows.append(_clip_at(CAM_A, base.format(h=h, m=m * 10)))
    snap = prep.compute_influx(rows, as_of=datetime(2026, 7, 16, 0, 0, tzinfo=UTC))
    # observed_camera_count == 1 여기서 -> projection = p95 * 4 / 1
    assert snap["observed_camera_count"] == 1
    expected = snap["observed_total_p95"] * 4 / snap["observed_camera_count"]
    assert snap["projected_4_camera_p95"] == pytest.approx(expected)


def test_influx_rejects_empty():
    with pytest.raises(prep.PrepContractError):
        prep.compute_influx([], as_of=_as_of())


def test_influx_rejects_nonfinite_started_at():
    with pytest.raises(prep.PrepContractError):
        prep.compute_influx([{"camera_id": CAM_A, "started_at": "not-a-date"}], as_of=_as_of())


def test_influx_is_deterministic_and_reports_window():
    rows = [_clip_at(CAM_A, f"2026-07-15T0{h}:00:00Z") for h in range(0, 6)]
    a = prep.compute_influx(rows, as_of=datetime(2026, 7, 16, 0, 0, tzinfo=UTC))
    b = prep.compute_influx(rows, as_of=datetime(2026, 7, 16, 0, 0, tzinfo=UTC))
    assert a == b
    assert a["window_days"] == 7
    assert "projected_note" in a  # 선형 투영 가정 명시


# --------------------------------------------------------------------------
# percentile helper (prepare 가 소유, benchmark 도 재사용)
# --------------------------------------------------------------------------

def test_percentile_linear_interpolation():
    vals = [1.0, 2.0, 3.0, 4.0]
    assert prep.percentile(vals, 50) == pytest.approx(2.5)
    assert prep.percentile(vals, 0) == pytest.approx(1.0)
    assert prep.percentile(vals, 100) == pytest.approx(4.0)


def test_percentile_single_value():
    assert prep.percentile([7.0], 95) == pytest.approx(7.0)


def test_percentile_rejects_empty():
    with pytest.raises(prep.PrepContractError):
        prep.percentile([], 95)
