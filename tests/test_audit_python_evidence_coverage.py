"""Tests for the Python Evidence Hybrid S0 coverage audit.

이 감사는 production DB를 read-only 로 읽어 Gate evidence 의 재고/현재정책/selector 시점
coverage 를 exact / estimate / not_reconstructable 로 분리 측정한다. 순수 집계 함수는
Supabase 없이 dict fixture 로 검증한다(=production 접근 0).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scripts.audit_python_evidence_coverage as audit


UTC = timezone.utc


# --------------------------------------------------------------------------
# fixture helpers
# --------------------------------------------------------------------------

def _dt(iso: str) -> datetime:
    return audit.parse_dt(iso)


def complete_prelabel(**overrides):
    """core_complete 조건을 모두 만족하는 prelabel dict. overrides 로 결손을 주입."""
    row = {
        "id": overrides.pop("id", "p-complete"),
        "clip_id": overrides.pop("clip_id", "c1"),
        "model_name": "rfdetr",
        "model_version": "gecko_v2",
        "checkpoint_sha256": "a" * 64,
        "threshold": 0.1,
        "sampler_version": "even-uniform-v1",
        "schema_version": "gate-evidence-v1",
        "frames_sampled": 12,
        "gecko_visible": True,
        "visibility_confidence": 0.9,
        "best_frame_ts": 1.5,
        "gecko_bbox": {"x": 1, "y": 2, "w": 3, "h": 4},
        "motion_metrics": {
            "visible_frame_count": 8,
            "visible_frame_ratio": 0.6,
            "max_bbox_center_disp": 0.2,
            "max_bbox_size_change": 0.1,
            "min_bbox_iou": 0.7,
            "roi_flow_mag": 0.3,
            "global_bg_change": 0.05,
            "bbox_edge_clipped": False,
        },
        "created_at": _dt("2026-07-14T05:00:00Z"),
    }
    for k, v in overrides.items():
        row[k] = v
    return row


def _camera(cid="camA", name="Cam A"):
    return {"id": cid, "name": name}


def snapshot_fixture():
    """4 eligible clips, dup identity prelabel, activity-v1 assessment, missing-metric, absent."""
    start = _dt("2026-07-14T00:00:00+09:00")
    as_of = _dt("2026-07-16T12:00:00+09:00")

    clips = [
        {"id": "c1", "camera_id": "camA", "started_at": _dt("2026-07-14T05:00:00Z"), "duration_sec": 30.0},
        {"id": "c2", "camera_id": "camA", "started_at": _dt("2026-07-14T06:00:00Z"), "duration_sec": 30.0},
        {"id": "c3", "camera_id": "camA", "started_at": _dt("2026-07-14T07:00:00Z"), "duration_sec": 30.0},
        {"id": "c4", "camera_id": "camA", "started_at": _dt("2026-07-14T08:00:00Z"), "duration_sec": 30.0},
    ]
    # c1: two rows, SAME identity (dup) -> counts once
    p1a = complete_prelabel(id="p1a", clip_id="c1")
    p1b = complete_prelabel(id="p1b", clip_id="c1")
    # c2: missing a motion metric -> core incomplete (but c2 is not policy_ready)
    p2 = complete_prelabel(id="p2", clip_id="c2")
    del p2["motion_metrics"]["roi_flow_mag"]
    # c3: absent evidence, nullable bbox/best_frame -> still core complete
    p3 = complete_prelabel(
        id="p3", clip_id="c3", gecko_visible=False, gecko_bbox=None, best_frame_ts=None
    )
    prelabels = [p1a, p1b, p2, p3]  # c4 has none

    assessments = [
        {"id": "a1", "clip_id": "c1", "prelabel_id": "p1a", "policy_version": "activity-v1",
         "decision": "active", "created_at": _dt("2026-07-14T05:10:00Z")},
        {"id": "a3", "clip_id": "c3", "prelabel_id": "p3", "policy_version": "activity-v1",
         "decision": "exclude_absent", "created_at": _dt("2026-07-14T07:10:00Z")},
    ]
    return audit.AuditSnapshot(
        start=start, as_of=as_of, cameras=(_camera(),), motion_clips=tuple(clips),
        prelabels=tuple(prelabels), assessments=tuple(assessments),
        settings={"camA": {"enabled": True, "active_policy_version": "activity-v1"}},
    )


def selector_fixture(prelabel_created_after_run=False):
    start = _dt("2026-07-14T00:00:00+09:00")
    as_of = _dt("2026-07-16T12:00:00+09:00")
    run_time = _dt("2026-07-15T13:00:00Z")
    w_start = _dt("2026-07-15T11:00:00Z")
    w_end = _dt("2026-07-15T13:00:00Z")

    win_clip = {"id": "wc1", "camera_id": "camA", "started_at": _dt("2026-07-15T12:00:00Z"), "duration_sec": 30.0}
    prelabel_created = _dt("2026-07-15T14:00:00Z") if prelabel_created_after_run else _dt("2026-07-15T12:30:00Z")
    win_prelabel = complete_prelabel(id="wp1", clip_id="wc1", created_at=prelabel_created)

    runs = [{
        "id": "run1", "camera_id": "camA", "window_start": w_start, "window_end": w_end,
        "selector_version": "budget-router-v1", "created_at": run_time,
    }]
    jobs = [
        {"id": "j1", "selector_run_id": "run1", "clip_id": "wc1", "camera_id": "camA",
         "prelabel_id": "wp1", "activity_assessment_id": None, "created_at": run_time},
        {"id": "j2", "selector_run_id": "run1", "clip_id": "wc1", "camera_id": "camA",
         "prelabel_id": None, "activity_assessment_id": None, "created_at": run_time},
    ]
    return audit.AuditSnapshot(
        start=start, as_of=as_of, cameras=(_camera(),), motion_clips=(win_clip,),
        prelabels=(win_prelabel,), selector_runs=tuple(runs), jobs=tuple(jobs),
        settings={"camA": {"enabled": True, "active_policy_version": "activity-v1"}},
    )


def backfill_only_fixture():
    start = _dt("2026-07-14T00:00:00+09:00")
    as_of = _dt("2026-07-16T12:00:00+09:00")
    run_time = _dt("2026-07-15T13:35:00Z")
    runs = [{
        "id": "bf1", "camera_id": "camA", "window_start": _dt("2026-07-15T11:00:00Z"),
        "window_end": _dt("2026-07-15T13:00:00Z"), "selector_version": "backfill-router-v1",
        "created_at": run_time,
    }]
    return audit.AuditSnapshot(
        start=start, as_of=as_of, cameras=(_camera(),), selector_runs=tuple(runs),
        settings={"camA": {"enabled": True}},
    )


# --------------------------------------------------------------------------
# Task 1 — inventory + completeness
# --------------------------------------------------------------------------

def test_inventory_counts_unique_clips_and_current_policy_ready():
    result = audit.build_inventory_rows(snapshot_fixture(), policy_version="activity-v1")
    assert result.total_eligible == 4
    assert result.any_prelabel_count == 3
    assert result.policy_ready_count == 2


def test_absent_nullable_bbox_is_core_complete():
    row = complete_prelabel(gecko_visible=False, gecko_bbox=None, best_frame_ts=None)
    assert audit.core_evidence_issues(row) == ()


def test_missing_motion_metric_is_not_core_complete():
    row = complete_prelabel()
    del row["motion_metrics"]["roi_flow_mag"]
    assert audit.core_evidence_issues(row) == ("motion_metrics.roi_flow_mag",)


def test_bad_checkpoint_and_zero_frames_flagged():
    row = complete_prelabel(checkpoint_sha256="short", frames_sampled=0)
    issues = audit.core_evidence_issues(row)
    assert "checkpoint_sha256" in issues
    assert "frames_sampled" in issues


def test_kst_date_boundary():
    assert audit.kst_date(_dt("2026-07-13T15:00:00Z")) == audit.date(2026, 7, 14)
    assert audit.kst_date(_dt("2026-07-13T14:59:59Z")) == audit.date(2026, 7, 13)


def test_duplicated_prelabels_count_once_in_identity():
    result = audit.build_inventory_rows(snapshot_fixture(), policy_version="activity-v1")
    ident = {(r["model_version"], r["schema_version"], r["frames_sampled"]): r["unique_clips"]
             for r in result.identity_rows}
    # c1 dup identity + c2 + c3 all share the same identity tuple -> unique clips = 3
    assert ident[("gecko_v2", "gate-evidence-v1", 12)] == 3


# --------------------------------------------------------------------------
# Task 2 — selector-time exact / estimate / not_reconstructable
# --------------------------------------------------------------------------

def test_selected_linkage_uses_job_foreign_keys_as_exact():
    rows = audit.build_selector_rows(selector_fixture())
    assert rows[0].selected_jobs == 2
    assert rows[0].selected_with_prelabel == 1
    assert rows[0].selected_linkage_kind == "exact"


def test_window_time_excludes_prelabel_created_after_run():
    rows = audit.build_selector_rows(selector_fixture(prelabel_created_after_run=True))
    assert rows[0].window_clips_with_prelabel_at_run == 0
    assert rows[0].window_time_kind == "estimate"


def test_window_time_counts_prelabel_created_before_run():
    rows = audit.build_selector_rows(selector_fixture())
    assert rows[0].window_clips_with_prelabel_at_run == 1


def test_exact_eligible_pool_is_never_claimed():
    assert audit.build_selector_rows(selector_fixture())[0].eligible_pool_kind == "not_reconstructable"


def test_classify_selector():
    assert audit.classify_selector("budget-router-v1") == "regular"
    assert audit.classify_selector("historical-backfill-v1") == "backfill"
    assert audit.classify_selector("something-else") == "other"


def test_broken_job_prelabel_fk_is_contract_error():
    snap = selector_fixture()
    broken = dict(snap.jobs[0])
    broken["prelabel_id"] = "does-not-exist"
    snap2 = audit.AuditSnapshot(
        start=snap.start, as_of=snap.as_of, cameras=snap.cameras, motion_clips=snap.motion_clips,
        prelabels=snap.prelabels, selector_runs=snap.selector_runs,
        jobs=(broken, snap.jobs[1]), settings=snap.settings,
    )
    with pytest.raises(audit.AuditContractError):
        audit.build_selector_rows(snap2)


def test_regular_and_backfill_never_aggregated_and_missing_regular_warns():
    rows = audit.build_selector_rows(backfill_only_fixture())
    assert all(r.selector_kind == "backfill" for r in rows)
    assert not any(r.selector_kind == "regular" for r in rows)
    warnings = audit.selector_warnings(rows)
    assert "regular_selector_sample_missing" in warnings


# --------------------------------------------------------------------------
# Task 3 — paginated SELECT-only adapter
# --------------------------------------------------------------------------

class _FakeQuery:
    """order().range().execute() 만 지원. mutation 메서드는 호출 자체를 기록해 금지 검증."""

    def __init__(self, rows, mutations):
        self._rows = rows
        self._mutations = mutations
        self._order = None
        self._range = None

    def order(self, col, desc=False):
        self._order = col
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = sorted(self._rows, key=lambda r: r[self._order])
        s, e = self._range
        return type("Resp", (), {"data": rows[s : e + 1]})()

    # forbidden — record if ever called
    def insert(self, *a, **k):
        self._mutations.append("insert"); return self

    def update(self, *a, **k):
        self._mutations.append("update"); return self

    def delete(self, *a, **k):
        self._mutations.append("delete"); return self

    def upsert(self, *a, **k):
        self._mutations.append("upsert"); return self


def test_select_all_paginates_and_is_read_only():
    rows = [{"id": f"{i:05d}"} for i in range(1001)]
    mutations = []
    reads = {"count": 0}

    def factory():
        reads["count"] += 1
        return _FakeQuery(rows, mutations)

    out = audit.select_all(factory, order_column="id", page_size=1000)
    assert len(out) == 1001
    assert len({r["id"] for r in out}) == 1001
    assert [r["id"] for r in out] == sorted(r["id"] for r in out)
    assert reads["count"] == 2          # two page reads
    assert mutations == []              # zero mutation calls


def test_select_all_rejects_duplicate_page_ids():
    rows = [{"id": "dup"}, {"id": "dup"}]
    with pytest.raises(audit.AuditContractError):
        audit.select_all(lambda: _FakeQuery(rows, []), order_column="id", page_size=1000)


def test_script_source_has_no_mutation_calls():
    src = Path(audit.__file__).read_text(encoding="utf-8")
    for forbidden in (".insert(", ".update(", ".delete(", ".upsert(", ".rpc("):
        assert forbidden not in src, f"forbidden mutation token in script: {forbidden}"


# --------------------------------------------------------------------------
# Task 4 — verdict + atomic render + privacy
# --------------------------------------------------------------------------

def _pass_snapshot():
    start = _dt("2026-07-14T00:00:00+09:00")
    as_of = _dt("2026-07-16T12:00:00+09:00")
    clip = {"id": "c1", "camera_id": "camA", "started_at": _dt("2026-07-14T05:00:00Z"), "duration_sec": 30.0}
    pre = complete_prelabel(id="p1", clip_id="c1")
    assess = {"id": "a1", "clip_id": "c1", "prelabel_id": "p1", "policy_version": "activity-v1",
              "decision": "active", "created_at": _dt("2026-07-14T05:10:00Z")}
    run = {"id": "run1", "camera_id": "camA", "window_start": _dt("2026-07-14T04:00:00Z"),
           "window_end": _dt("2026-07-14T06:00:00Z"), "selector_version": "budget-router-v1",
           "created_at": _dt("2026-07-14T06:00:00Z")}
    job = {"id": "j1", "selector_run_id": "run1", "clip_id": "c1", "camera_id": "camA",
           "prelabel_id": "p1", "activity_assessment_id": None, "created_at": _dt("2026-07-14T06:00:00Z")}
    return audit.AuditSnapshot(
        start=start, as_of=as_of, cameras=(_camera(),), motion_clips=(clip,), prelabels=(pre,),
        assessments=(assess,), selector_runs=(run,), jobs=(job,),
        settings={"camA": {"enabled": True, "active_policy_version": "activity-v1"}},
    )


def _gap_snapshot():
    # contract complete but no regular selector run -> GAP
    snap = _pass_snapshot()
    return audit.AuditSnapshot(
        start=snap.start, as_of=snap.as_of, cameras=snap.cameras, motion_clips=snap.motion_clips,
        prelabels=snap.prelabels, assessments=snap.assessments, selector_runs=(), jobs=(),
        settings=snap.settings,
    )


def _hold_snapshot():
    # policy_ready clip whose referenced prelabel is core-incomplete -> HOLD
    snap = _pass_snapshot()
    bad = complete_prelabel(id="p1", clip_id="c1")
    del bad["motion_metrics"]["roi_flow_mag"]
    return audit.AuditSnapshot(
        start=snap.start, as_of=snap.as_of, cameras=snap.cameras, motion_clips=snap.motion_clips,
        prelabels=(bad,), assessments=snap.assessments, selector_runs=snap.selector_runs,
        jobs=snap.jobs, settings=snap.settings,
    )


def test_verdicts_pass_gap_hold():
    assert audit.evaluate_verdict_for(_pass_snapshot()).label == "S0_PASS"
    assert audit.evaluate_verdict_for(_gap_snapshot()).label == "S0_PASS_WITH_COVERAGE_GAP"
    assert audit.evaluate_verdict_for(_hold_snapshot()).label == "S0_HOLD_DATA_CONTRACT"


def test_render_artifacts_share_snapshot_and_selector_kinds(tmp_path):
    out = tmp_path / "s0"
    audit.render_artifacts(_pass_snapshot(), out)
    summary = json.loads((out / "summary.json").read_text())
    for name in ("camera_date_coverage.csv", "selector_time_coverage.csv", "identity_distribution.csv", "REPORT.md"):
        assert (out / name).exists()
    sid = summary["snapshot_id"]
    assert sid and summary["as_of_utc"]
    sel = (out / "selector_time_coverage.csv").read_text()
    for field in ("selected_linkage_kind", "window_time_kind", "eligible_pool_kind"):
        assert field in sel
    # snapshot_id echoed into REPORT.md too
    assert sid in (out / "REPORT.md").read_text()


def test_render_requires_overwrite_for_existing_dir(tmp_path):
    out = tmp_path / "s0"
    audit.render_artifacts(_pass_snapshot(), out)
    with pytest.raises(audit.AuditContractError):
        audit.render_artifacts(_pass_snapshot(), out)
    audit.render_artifacts(_pass_snapshot(), out, overwrite=True)  # ok


def test_failed_render_leaves_no_partial_dir(tmp_path, monkeypatch):
    out = tmp_path / "s0"

    def boom(*a, **k):
        raise RuntimeError("render blew up")

    monkeypatch.setattr(audit, "_write_selector_csv", boom)
    with pytest.raises(RuntimeError):
        audit.render_artifacts(_pass_snapshot(), out)
    assert not out.exists()
    # unrelated sibling paths untouched
    assert list(tmp_path.iterdir()) == []


def test_privacy_no_secrets_in_artifacts(tmp_path):
    start = _dt("2026-07-14T00:00:00+09:00")
    as_of = _dt("2026-07-16T12:00:00+09:00")
    owner = "11111111-2222-3333-4444-555555555555"
    r2 = "clips/eval/secret-object-key.mp4"
    token = "sb_secret_" + "Z" * 40
    clip = {"id": "cccccccc-dddd-eeee-ffff-000000000000", "camera_id": "camA",
            "started_at": _dt("2026-07-14T05:00:00Z"), "duration_sec": 30.0,
            "owner_id": owner, "r2_key": r2}
    pre = complete_prelabel(id="p1", clip_id="cccccccc-dddd-eeee-ffff-000000000000")
    pre["motion_metrics"]["secret_leak"] = token
    pre["detected_objects"] = [{"type": "gecko", "note": token}]
    assess = {"id": "a1", "clip_id": "cccccccc-dddd-eeee-ffff-000000000000", "prelabel_id": "p1",
              "policy_version": "activity-v1", "decision": "active", "created_at": _dt("2026-07-14T05:10:00Z")}
    snap = audit.AuditSnapshot(
        start=start, as_of=as_of, cameras=(_camera(),), motion_clips=(clip,), prelabels=(pre,),
        assessments=(assess,), settings={"camA": {"enabled": True, "active_policy_version": "activity-v1"}},
    )
    out = tmp_path / "s0"
    audit.render_artifacts(snap, out)
    for f in out.iterdir():
        text = f.read_text()
        assert owner not in text
        assert r2 not in text
        assert token not in text
        # full clip UUID must not appear (short 8-char prefix is allowed)
        assert "cccccccc-dddd-eeee-ffff-000000000000" not in text


def test_cli_requires_as_of():
    with pytest.raises(SystemExit):
        audit.main(["--start", "2026-07-14T00:00:00+09:00"])
