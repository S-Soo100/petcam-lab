"""Tests for the Python Evidence S1 throughput benchmark harness.

메트릭 코어(timing/percentile/aggregate)와 fail-closed 안전 preflight, append-safe
JSONL 결과를 Mac mini/RF-DETR/R2 없이 **주입(injection)** 으로 검증한다. clock·host·
lock·schedule·adapter 는 전부 주입되므로 이 테스트는 순수하다(=production 접근 0, VLM 0).
"""

from __future__ import annotations

import json

import pytest

import scripts.benchmark_python_evidence_s1 as bench


# --------------------------------------------------------------------------
# BenchRecord fixture
# --------------------------------------------------------------------------

def _rec(**over):
    base = dict(
        clip_id="c1", camera_short="5b3ea7aa", condition="A6", device="mps",
        cache_mode="cold_independent", repeat=1, is_warmup=False,
        e2e_s=10.0, download_s=3.0, decode_s=2.0, detector_s=4.0, roi_flow_s=0.0,
        bytes_downloaded=1000, downloads=1, peak_rss_bytes=100 * 1024 ** 2,
        temp_peak_bytes=5 * 1024 ** 2, roi_status="ok", risk_control_only=False,
        frames_out=6, error_code=None,
    )
    base.update(over)
    return bench.BenchRecord(**base)


# --------------------------------------------------------------------------
# metric core — timing / percentiles / throughput
# --------------------------------------------------------------------------

def test_percentile_reused_from_prepare():
    assert bench.percentile([1.0, 2.0, 3.0, 4.0], 95) == pytest.approx(3.85)


def test_throughput_capacity_formula():
    # capacity clips/hour = 3600 / p95_seconds
    assert bench.throughput_capacity(22.5) == pytest.approx(160.0)
    assert bench.throughput_capacity(18.0) == pytest.approx(200.0)


def test_throughput_capacity_rejects_nonpositive():
    with pytest.raises(bench.BenchContractError):
        bench.throughput_capacity(0.0)
    with pytest.raises(bench.BenchContractError):
        bench.throughput_capacity(-1.0)


def test_projected_four_camera_formula():
    assert bench.projected_four_camera_p95(60.0, 3) == pytest.approx(80.0)
    assert bench.projected_four_camera_p95(30.0, 4) == pytest.approx(30.0)


def test_aggregate_excludes_warmup():
    recs = [
        _rec(repeat=0, is_warmup=True, e2e_s=99.0),  # warmup — must be excluded
        _rec(repeat=1, e2e_s=10.0),
        _rec(repeat=2, e2e_s=20.0),
        _rec(repeat=3, e2e_s=30.0),
    ]
    agg = bench.aggregate(recs)
    cell = agg[("A6", "mps", "cold_independent")]
    assert cell["count"] == 3  # warmup 제외
    assert cell["e2e_p50"] == pytest.approx(20.0)


def test_aggregate_percentiles_and_capacity():
    recs = [_rec(repeat=i, e2e_s=v) for i, v in [(1, 10.0), (2, 20.0), (3, 30.0)]]
    cell = bench.aggregate(recs)[("A6", "mps", "cold_independent")]
    assert cell["e2e_p95"] == pytest.approx(29.0)  # linear interp of [10,20,30] @95
    assert cell["capacity_per_hour"] == pytest.approx(3600 / 29.0)


def test_aggregate_groups_by_condition_device_cache():
    recs = [
        _rec(condition="A6", device="mps", cache_mode="cold_independent", repeat=1),
        _rec(condition="CROI", device="mps", cache_mode="warm_same_run", repeat=1, roi_status="no_bbox"),
        _rec(condition="CROI", device="cpu", cache_mode="cold_independent", repeat=1),
    ]
    agg = bench.aggregate(recs)
    assert set(agg.keys()) == {
        ("A6", "mps", "cold_independent"),
        ("CROI", "mps", "warm_same_run"),
        ("CROI", "cpu", "cold_independent"),
    }


def test_aggregate_rejects_nonfinite_or_negative_e2e():
    with pytest.raises(bench.BenchContractError):
        bench.aggregate([_rec(e2e_s=float("nan"))])
    with pytest.raises(bench.BenchContractError):
        bench.aggregate([_rec(e2e_s=float("inf"))])
    with pytest.raises(bench.BenchContractError):
        bench.aggregate([_rec(e2e_s=-5.0)])


def test_aggregate_rejects_empty_measured():
    with pytest.raises(bench.BenchContractError):
        bench.aggregate([])
    with pytest.raises(bench.BenchContractError):
        bench.aggregate([_rec(repeat=0, is_warmup=True)])  # only warmup → no measured


# --------------------------------------------------------------------------
# fail-closed safety preflight
# --------------------------------------------------------------------------

def _good_inputs(**over):
    base = dict(
        hostname="baeg-endeuui-Macmini.local", expected_host="baeg-endeuui-Macmini.local",
        repo_head="a" * 40, pinned_sha="a" * 40, repo_dirty=False,
        activity_lock_busy=False, vlm_lock_busy=False, minutes_until_next_job=40.0,
    )
    base.update(over)
    return bench.PreflightInputs(**base)


def test_preflight_passes_when_all_safe():
    bench.run_preflight(_good_inputs())  # no raise


def test_preflight_wrong_host_aborts():
    with pytest.raises(bench.SafetyAbort) as e:
        bench.run_preflight(_good_inputs(hostname="BaekBook-Pro-14-M5.local"))
    assert e.value.code == "wrong_host"


def test_preflight_head_mismatch_aborts():
    with pytest.raises(bench.SafetyAbort) as e:
        bench.run_preflight(_good_inputs(repo_head="b" * 40))
    assert e.value.code == "head_mismatch"


def test_preflight_dirty_repo_aborts():
    with pytest.raises(bench.SafetyAbort) as e:
        bench.run_preflight(_good_inputs(repo_dirty=True))
    assert e.value.code == "repo_dirty"


def test_preflight_activity_lock_busy_aborts():
    with pytest.raises(bench.SafetyAbort) as e:
        bench.run_preflight(_good_inputs(activity_lock_busy=True))
    assert e.value.code == "activity_lock_busy"


def test_preflight_vlm_lock_busy_aborts():
    with pytest.raises(bench.SafetyAbort) as e:
        bench.run_preflight(_good_inputs(vlm_lock_busy=True))
    assert e.value.code == "vlm_lock_busy"


def test_preflight_insufficient_window_aborts():
    with pytest.raises(bench.SafetyAbort) as e:
        bench.run_preflight(_good_inputs(minutes_until_next_job=20.0))
    assert e.value.code == "insufficient_window"


def test_preflight_exactly_25min_ok():
    bench.run_preflight(_good_inputs(minutes_until_next_job=25.0))  # >= boundary, no raise


# --------------------------------------------------------------------------
# 20-minute hard deadline
# --------------------------------------------------------------------------

class _FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_deadline_not_exceeded_before_budget():
    clk = _FakeClock(1000.0)
    d = bench.Deadline(budget_s=1200.0, clock=clk)
    clk.t = 1000.0 + 1199.0
    assert not d.exceeded()
    d.check()  # no raise
    assert d.remaining() == pytest.approx(1.0)


def test_deadline_exceeded_after_budget():
    clk = _FakeClock(1000.0)
    d = bench.Deadline(budget_s=1200.0, clock=clk)
    clk.t = 1000.0 + 1201.0
    assert d.exceeded()
    with pytest.raises(bench.DeadlineExceeded):
        d.check()


def test_default_runtime_budget_is_20_minutes():
    assert bench.RUNTIME_BUDGET_S == 20 * 60


# --------------------------------------------------------------------------
# temp cleanup on success / exception / interrupt
# --------------------------------------------------------------------------

def test_scoped_tempdir_cleans_on_success():
    seen = {}
    with bench.scoped_tempdir() as d:
        (d / "vid.mp4").write_bytes(b"x" * 10)
        seen["d"] = d
        assert d.exists()
    assert not seen["d"].exists()


def test_scoped_tempdir_cleans_on_exception():
    seen = {}
    with pytest.raises(RuntimeError):
        with bench.scoped_tempdir() as d:
            seen["d"] = d
            (d / "frame.jpg").write_bytes(b"y" * 10)
            raise RuntimeError("boom")
    assert not seen["d"].exists()


def test_scoped_tempdir_cleans_on_interrupt():
    seen = {}
    with pytest.raises(KeyboardInterrupt):
        with bench.scoped_tempdir() as d:
            seen["d"] = d
            (d / "frame.jpg").write_bytes(b"z" * 10)
            raise KeyboardInterrupt()
    assert not seen["d"].exists()


def test_dir_size_bytes_counts_media():
    with bench.scoped_tempdir() as d:
        (d / "a.mp4").write_bytes(b"x" * 100)
        (d / "b.jpg").write_bytes(b"y" * 50)
        assert bench.dir_size_bytes(d) == 150


# --------------------------------------------------------------------------
# forbidden write / VLM adapter injection
# --------------------------------------------------------------------------

def test_adapter_config_rejects_vlm_injection():
    with pytest.raises(bench.SafetyAbort) as e:
        bench.validate_adapter_config({"downloader": object(), "vlm": object()})
    assert e.value.code == "forbidden_adapter"


def test_adapter_config_rejects_db_write_injection():
    with pytest.raises(bench.SafetyAbort):
        bench.validate_adapter_config({"downloader": object(), "db_write": object()})


def test_adapter_config_rejects_selector_injection():
    with pytest.raises(bench.SafetyAbort):
        bench.validate_adapter_config({"selector": object()})


def test_adapter_config_allows_known_adapters():
    bench.validate_adapter_config({
        "downloader": object(), "detector_factory": object(),
        "sample_frames": object(), "extract_six": object(),
        "motion_metrics": object(), "clock": object(),
    })  # no raise


# --------------------------------------------------------------------------
# append-safe JSONL results (resume without rerunning completed keys)
# --------------------------------------------------------------------------

def test_append_and_reload_completed_keys(tmp_path):
    p = tmp_path / "raw_results.jsonl"
    r1 = _rec(clip_id="c1", condition="A6", device="mps", cache_mode="cold_independent", repeat=1)
    r2 = _rec(clip_id="c1", condition="B12", device="mps", cache_mode="cold_independent", repeat=1)
    bench.append_record(p, r1)
    bench.append_record(p, r2)
    keys = bench.load_completed_keys(p)
    assert keys == {r1.key, r2.key}


def test_resume_skips_completed(tmp_path):
    p = tmp_path / "raw_results.jsonl"
    done = _rec(clip_id="c9", condition="CROI", device="mps", cache_mode="warm_same_run", repeat=2)
    bench.append_record(p, done)
    completed = bench.load_completed_keys(p)
    assert done.key in completed
    todo = _rec(clip_id="c9", condition="CROI", device="mps", cache_mode="warm_same_run", repeat=3)
    assert todo.key not in completed


def test_reload_tolerates_corrupt_trailing_line(tmp_path):
    p = tmp_path / "raw_results.jsonl"
    good = _rec(clip_id="cA", repeat=1)
    bench.append_record(p, good)
    with p.open("a", encoding="utf-8") as fh:
        fh.write('{"clip_id": "cB", "condi')  # truncated crash line
    keys = bench.load_completed_keys(p)  # must not raise
    assert good.key in keys


def test_record_key_shape():
    r = _rec(clip_id="cK", condition="DALL", device="cpu", cache_mode="cold_independent", repeat=2)
    assert r.key == ("cK", "DALL", "cpu", "cold_independent", 2)


# ==========================================================================
# Task 3 — 조건 어댑터 (A6 / B12 / CROI / DALL) + device 분리
#   실제 nightly/gate 어댑터는 주입. 여기서는 fake 주입으로 wiring·계약을 검증.
# ==========================================================================

from pathlib import Path  # noqa: E402


class _Ticker:
    """호출마다 +1s — 결정론적 timing."""
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1.0
        return self.t


class _Det:
    def __init__(self, class_name, confidence, xywh):
        self.class_name = class_name
        self.confidence = confidence
        self.xywh = xywh


class _FakeDetector:
    def __init__(self, dets):
        self._dets = dets
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        return list(self._dets)


# ---- A6 --------------------------------------------------------------------

def test_a6_extracts_six_and_cleans_up():
    captured = {}

    def fake_extract_six(video, out_dir):
        out_dir = Path(out_dir)
        paths = []
        for i in range(6):
            p = out_dir / f"{i}.jpg"
            p.write_bytes(b"x" * 10)
            paths.append(p)
        captured["out_dir"] = out_dir
        captured["calls"] = captured.get("calls", 0) + 1
        return paths

    res = bench.run_A6("clip.mp4", extract_six=fake_extract_six, clock=_Ticker())
    assert res.condition == "A6"
    assert res.frames_out == 6
    assert res.decode_s == pytest.approx(1.0)  # timing captured
    assert res.detector_s == 0.0               # A6 never runs detector / Claude
    assert captured["calls"] == 1
    # cleanup: extract 된 frame 은 실행 후 남지 않는다
    assert not captured["out_dir"].exists()
    assert res.temp_peak_bytes >= 60           # 6 files x 10 bytes measured before cleanup


# ---- B12 -------------------------------------------------------------------

def _fake_sample_frames(video, num_frames=12):
    return [(float(i), object()) for i in range(num_frames)]


def test_b12_samples_12_and_times_decode_and_detector_separately():
    det = _FakeDetector([])  # no gecko
    res = bench.run_B12("clip.mp4", sample_frames=_fake_sample_frames, detector=det, clock=_Ticker())
    assert res.condition == "B12"
    assert res.frames_out == 12               # bounded sampling to num_frames
    assert det.calls == 12                    # detector run per sampled frame
    assert res.decode_s == pytest.approx(1.0)
    assert res.detector_s == pytest.approx(1.0)
    assert res.roi_flow_s == 0.0              # B12 has no ROI flow


# ---- CROI ------------------------------------------------------------------

def test_robust_union_bbox_covers_all_gecko_boxes():
    per_frame = [
        [_Det("gecko", 0.9, [10, 10, 20, 20])],
        [_Det("gecko", 0.8, [40, 30, 10, 10]), _Det("person", 0.9, [0, 0, 5, 5])],
    ]
    bbox = bench.robust_union_bbox(per_frame)
    # union: x0=10,y0=10 .. x1=50,y1=40 -> [10,10,40,30]
    assert bbox == [10, 10, 40, 30]


def test_robust_union_bbox_none_when_no_gecko():
    assert bench.robust_union_bbox([[_Det("person", 0.9, [0, 0, 5, 5])], []]) is None


def test_robust_union_bbox_filters_low_confidence():
    per_frame = [[_Det("gecko", 0.1, [10, 10, 20, 20])]]
    assert bench.robust_union_bbox(per_frame, conf_floor=0.5) is None


def test_croi_runs_dense_flow_inside_bbox():
    captured = {}

    def fake_dense_roi_flow(video, bbox):
        captured["bbox"] = bbox
        captured["calls"] = captured.get("calls", 0) + 1
        return [0.1, 0.2, 0.3]  # raw, meaning-neutral series

    det = _FakeDetector([_Det("gecko", 0.9, [10, 10, 20, 20])])
    res = bench.run_CROI("clip.mp4", sample_frames=_fake_sample_frames, detector=det,
                         dense_roi_flow=fake_dense_roi_flow, clock=_Ticker())
    assert res.condition == "CROI"
    assert res.roi_status == "ok"
    assert captured["calls"] == 1
    assert captured["bbox"] == [10, 10, 20, 20]
    assert res.roi_flow_s == pytest.approx(1.0)
    assert res.roi_series_len == 3
    # 의미 판정 필드가 없어야 한다 (raw only)
    assert not hasattr(res, "behavior")
    assert not hasattr(res, "label")


def test_croi_no_bbox_skips_dense_flow():
    captured = {}

    def fake_dense_roi_flow(video, bbox):
        captured["called"] = True
        return [1.0]

    det = _FakeDetector([])  # no gecko -> no bbox
    res = bench.run_CROI("clip.mp4", sample_frames=_fake_sample_frames, detector=det,
                         dense_roi_flow=fake_dense_roi_flow, clock=_Ticker())
    assert res.roi_status == "no_bbox"
    assert res.roi_flow_s == 0.0
    assert res.roi_series_len == 0
    assert "called" not in captured          # dense flow 는 no_bbox 에서 건너뛴다 (full frame 대체 금지)


# ---- DALL ------------------------------------------------------------------

def test_dall_processes_frames_one_at_a_time_and_marks_risk():
    log = []

    def fake_decode_seq(video):
        for i in range(4):
            log.append(("y", i))
            yield object()

    class _LogDetector:
        def __init__(self):
            self.calls = 0

        def detect(self, frame):
            log.append(("d", self.calls))
            self.calls += 1
            return []

    det = _LogDetector()
    dl = bench.Deadline(budget_s=10 ** 9, clock=_Ticker())
    res = bench.run_DALL("clip.mp4", decode_seq=fake_decode_seq, detector=det,
                         deadline=dl, clock=_Ticker(), in_reduced=True)
    assert res.condition == "DALL"
    assert res.risk_control_only is True
    assert res.frames_out == 4
    assert det.calls == 4
    # 한 프레임씩 (interleaved) — 전체 리스트로 붙잡지 않는다
    assert log == [("y", 0), ("d", 0), ("y", 1), ("d", 1), ("y", 2), ("d", 2), ("y", 3), ("d", 3)]


def test_dall_refuses_non_reduced_clip():
    def fake_decode_seq(video):
        yield object()

    with pytest.raises(bench.BenchContractError):
        bench.run_DALL("clip.mp4", decode_seq=fake_decode_seq, detector=_FakeDetector([]),
                       deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()),
                       clock=_Ticker(), in_reduced=False)


def test_dall_stops_on_deadline():
    def fake_decode_seq(video):
        for i in range(100):
            yield object()

    class _CountdownDeadline:
        def __init__(self, allow):
            self.allow = allow

        def check(self):
            if self.allow <= 0:
                raise bench.DeadlineExceeded("budget")
            self.allow -= 1

    with pytest.raises(bench.DeadlineExceeded):
        bench.run_DALL("clip.mp4", decode_seq=fake_decode_seq, detector=_FakeDetector([]),
                       deadline=_CountdownDeadline(3), clock=_Ticker(), in_reduced=True)


# ---- device 분리 (MPS fail-closed) -----------------------------------------

class _FakeTorch:
    def __init__(self, mps_available):
        outer = self

        class _MPS:
            @staticmethod
            def is_available():
                return outer._mps

        class _Backends:
            mps = _MPS()

        self._mps = mps_available
        self.backends = _Backends()


def test_resolve_device_mps_available():
    assert bench.resolve_device("mps", torch_module=_FakeTorch(True)) == "mps"


def test_resolve_device_mps_unavailable_fails_closed():
    with pytest.raises(bench.SafetyAbort) as e:
        bench.resolve_device("mps", torch_module=_FakeTorch(False))
    assert e.value.code == "mps_unavailable"


def test_resolve_device_cpu_always_ok():
    assert bench.resolve_device("cpu", torch_module=_FakeTorch(False)) == "cpu"


# ==========================================================================
# Task 4 — 다운로드 재사용 + end-to-end 러너 (cold/warm, retry, rotation, 실패격리, temp0)
# ==========================================================================

def _fake_downloader_factory(behaviors=None):
    """dest 에 dummy mp4 를 쓰고 호출을 센다. behaviors=예외 시퀀스(있으면 raise 후 소비)."""
    state = {"calls": 0, "behaviors": list(behaviors or [])}

    def dl(r2_key, dest):
        state["calls"] += 1
        if state["behaviors"]:
            exc = state["behaviors"].pop(0)
            if exc is not None:
                raise exc
        Path(dest).write_bytes(b"m" * 20)
        return Path(dest)

    dl.state = state
    return dl


def _adapter_ok(condition):
    def fn(path):
        return bench.AdapterResult(condition=condition, decode_s=1.0, detector_s=2.0, roi_flow_s=0.0,
                                   frames_out=6, roi_status="ok", risk_control_only=(condition == "DALL"))
    return fn


def _reduced_clip(cid="c1", reduced=True):
    return bench.ClipSpec(clip_id=cid, camera_short="5b3ea7aa", bbox_stratum="present",
                          duration_sec=10.0, quartile=1, in_reduced=reduced)


# ---- cold / warm download counting ----------------------------------------

def test_cold_independent_downloads_once_per_condition(tmp_path):
    dl = _fake_downloader_factory()
    mgr = bench.DownloadManager(dl, "cold_independent", _Ticker())
    recs = bench.run_pass(
        [_reduced_clip("c1")], ["A6", "B12"], cache_mode="cold_independent", manager=mgr,
        adapters={"A6": _adapter_ok("A6"), "B12": _adapter_ok("B12")},
        resolve_r2_key=lambda cid: "clips/secret.mp4",
        deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()), device="mps",
        temp_root=str(tmp_path), repeat=1, is_warmup=False, rusage_fn=lambda: 1024)
    assert dl.state["calls"] == 2          # 조건마다 독립 다운로드
    assert mgr.total_downloads == 2
    assert sum(r.downloads for r in recs) == 2


def test_warm_same_run_downloads_once_per_clip(tmp_path):
    dl = _fake_downloader_factory()
    mgr = bench.DownloadManager(dl, "warm_same_run", _Ticker())
    recs = bench.run_pass(
        [_reduced_clip("c1")], ["A6", "B12"], cache_mode="warm_same_run", manager=mgr,
        adapters={"A6": _adapter_ok("A6"), "B12": _adapter_ok("B12")},
        resolve_r2_key=lambda cid: "clips/secret.mp4",
        deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()), device="mps",
        temp_root=str(tmp_path), repeat=1, is_warmup=False, rusage_fn=lambda: 1024)
    assert dl.state["calls"] == 1          # clip 당 1회, 조건 간 재사용
    assert mgr.total_downloads == 1
    assert sum(r.downloads for r in recs) == 1


def test_cross_process_cache_never_runs():
    assert bench.CROSS_PROCESS_CACHE_STATUS == "not_run_design_required"
    passes = bench.plan_passes(("cold_independent", "warm_same_run"), warmup=1, repeats=3)
    assert all(p[0] != "cross_process_cache" for p in passes)
    # manager 는 cross_process 모드에서 다운로드 자체를 거부한다
    mgr = bench.DownloadManager(_fake_downloader_factory(), "cross_process_cache", _Ticker())
    with pytest.raises(bench.BenchContractError):
        mgr.get("c1", "clips/k.mp4", ".")


def test_download_result_redacts_r2_key(tmp_path):
    dl = _fake_downloader_factory()
    mgr = bench.DownloadManager(dl, "cold_independent", _Ticker())
    res = mgr.get("c1", "clips/very-secret-key.mp4", str(tmp_path))
    assert not hasattr(res, "r2_key")
    assert "secret" not in str(res.path)   # path 는 clip_id 기반, r2_key 미노출
    assert res.bytes == 20
    assert res.downloads == 1


# ---- download retry (bounded, no infinite) --------------------------------

def test_download_retries_transient_then_succeeds(tmp_path):
    dl = _fake_downloader_factory([bench.TransientDownloadError(), bench.TransientDownloadError(), None])
    mgr = bench.DownloadManager(dl, "cold_independent", _Ticker(), max_retries=3)
    res = mgr.get("c1", "clips/k.mp4", str(tmp_path))
    assert dl.state["calls"] == 3
    assert res.downloads == 1


def test_download_transient_gives_up_after_max_retries(tmp_path):
    dl = _fake_downloader_factory([bench.TransientDownloadError()] * 10)
    mgr = bench.DownloadManager(dl, "cold_independent", _Ticker(), max_retries=3)
    with pytest.raises(bench.TransientDownloadError):
        mgr.get("c1", "clips/k.mp4", str(tmp_path))
    assert dl.state["calls"] == 3          # 무한 재시도 금지


def test_download_permanent_error_propagates_immediately(tmp_path):
    dl = _fake_downloader_factory([PermissionError("nope")])
    mgr = bench.DownloadManager(dl, "cold_independent", _Ticker(), max_retries=3)
    with pytest.raises(PermissionError):
        mgr.get("c1", "clips/k.mp4", str(tmp_path))
    assert dl.state["calls"] == 1          # 영구 에러는 재시도 안 함


# ---- condition order rotation ---------------------------------------------

def test_condition_rotation_is_deterministic_and_covers_all():
    conds = ["A6", "B12", "CROI", "DALL"]
    r0 = bench.rotate_conditions(conds, 0)
    r1 = bench.rotate_conditions(conds, 1)
    assert r0 == ["A6", "B12", "CROI", "DALL"]
    assert r1 == ["B12", "CROI", "DALL", "A6"]
    assert set(r1) == set(conds)
    assert bench.rotate_conditions(conds, 1) == r1  # deterministic


def test_plan_passes_excludes_warmup_from_measured():
    passes = bench.plan_passes(("cold_independent", "warm_same_run"), warmup=1, repeats=3)
    measured = [p for p in passes if not p[2]]
    warmups = [p for p in passes if p[2]]
    assert len(warmups) == 2               # 모드당 1 warmup
    assert len(measured) == 6              # 모드당 3 measured


# ---- should_run filter (device/DALL reduced-only) -------------------------

def test_should_run_dall_only_on_reduced():
    assert bench.should_run(_reduced_clip(reduced=True), "DALL", "mps") is True
    assert bench.should_run(_reduced_clip(reduced=False), "DALL", "mps") is False


def test_should_run_cpu_only_on_reduced():
    assert bench.should_run(_reduced_clip(reduced=False), "A6", "cpu") is False
    assert bench.should_run(_reduced_clip(reduced=True), "A6", "cpu") is True
    assert bench.should_run(_reduced_clip(reduced=False), "A6", "mps") is True  # MPS 전체


# ---- deadline between clip/condition --------------------------------------

def test_run_pass_checks_deadline_between_conditions(tmp_path):
    class _CountdownDeadline:
        def __init__(self, allow):
            self.allow = allow

        def check(self):
            if self.allow <= 0:
                raise bench.DeadlineExceeded("budget")
            self.allow -= 1

    dl = _fake_downloader_factory()
    mgr = bench.DownloadManager(dl, "cold_independent", _Ticker())
    with pytest.raises(bench.DeadlineExceeded):
        bench.run_pass(
            [_reduced_clip("c1"), _reduced_clip("c2")], ["A6", "B12"], cache_mode="cold_independent",
            manager=mgr, adapters={"A6": _adapter_ok("A6"), "B12": _adapter_ok("B12")},
            resolve_r2_key=lambda cid: "clips/k.mp4", deadline=_CountdownDeadline(2), device="mps",
            temp_root=str(tmp_path), repeat=1, is_warmup=False, rusage_fn=lambda: 1024)


# ---- failure isolation vs systemic ----------------------------------------

def test_single_clip_failure_is_isolated(tmp_path):
    def bad_a6(path):
        raise ValueError("bad clip")

    dl = _fake_downloader_factory()
    mgr = bench.DownloadManager(dl, "cold_independent", _Ticker())
    recs = bench.run_pass(
        [_reduced_clip("c1")], ["A6", "B12"], cache_mode="cold_independent", manager=mgr,
        adapters={"A6": bad_a6, "B12": _adapter_ok("B12")},
        resolve_r2_key=lambda cid: "clips/k.mp4",
        deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()), device="mps",
        temp_root=str(tmp_path), repeat=1, is_warmup=False, rusage_fn=lambda: 1024)
    by_cond = {r.condition: r for r in recs}
    assert by_cond["A6"].error_code == "ValueError"   # sanitized, no message leak
    assert by_cond["B12"].error_code is None          # 나머지는 계속 진행


def test_systemic_failure_stops_run(tmp_path):
    def systemic(path):
        raise bench.SystemicFailure("detector dead")

    dl = _fake_downloader_factory()
    mgr = bench.DownloadManager(dl, "cold_independent", _Ticker())
    with pytest.raises(bench.SystemicFailure):
        bench.run_pass(
            [_reduced_clip("c1")], ["A6"], cache_mode="cold_independent", manager=mgr,
            adapters={"A6": systemic}, resolve_r2_key=lambda cid: "clips/k.mp4",
            deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()), device="mps",
            temp_root=str(tmp_path), repeat=1, is_warmup=False, rusage_fn=lambda: 1024)


def test_too_many_consecutive_failures_becomes_systemic(tmp_path):
    def always_bad(path):
        raise ValueError("bad")

    clips = [_reduced_clip(f"c{i}") for i in range(10)]
    dl = _fake_downloader_factory()
    mgr = bench.DownloadManager(dl, "cold_independent", _Ticker())
    with pytest.raises(bench.SystemicFailure):
        bench.run_pass(
            clips, ["A6"], cache_mode="cold_independent", manager=mgr,
            adapters={"A6": always_bad}, resolve_r2_key=lambda cid: "clips/k.mp4",
            deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()), device="mps",
            temp_root=str(tmp_path), repeat=1, is_warmup=False, rusage_fn=lambda: 1024,
            max_consecutive_failures=5)


# ---- temp media zero after pass -------------------------------------------

def test_run_pass_leaves_zero_temp_media(tmp_path):
    dl = _fake_downloader_factory()
    mgr = bench.DownloadManager(dl, "cold_independent", _Ticker())
    bench.run_pass(
        [_reduced_clip("c1"), _reduced_clip("c2")], ["A6", "B12"], cache_mode="cold_independent",
        manager=mgr, adapters={"A6": _adapter_ok("A6"), "B12": _adapter_ok("B12")},
        resolve_r2_key=lambda cid: "clips/k.mp4",
        deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()), device="mps",
        temp_root=str(tmp_path), repeat=1, is_warmup=False, rusage_fn=lambda: 1024)
    assert bench.count_media_files(tmp_path) == 0   # 모든 scoped temp 정리됨


def test_run_pass_record_fields(tmp_path):
    dl = _fake_downloader_factory()
    mgr = bench.DownloadManager(dl, "cold_independent", _Ticker())
    recs = bench.run_pass(
        [_reduced_clip("c1")], ["CROI"], cache_mode="cold_independent", manager=mgr,
        adapters={"CROI": _adapter_ok("CROI")}, resolve_r2_key=lambda cid: "clips/k.mp4",
        deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()), device="mps",
        temp_root=str(tmp_path), repeat=2, is_warmup=False, rusage_fn=lambda: 4096)
    r = recs[0]
    assert r.clip_id == "c1" and r.condition == "CROI" and r.device == "mps"
    assert r.cache_mode == "cold_independent" and r.repeat == 2 and r.is_warmup is False
    assert r.e2e_s == pytest.approx(r.download_s + r.decode_s + r.detector_s + r.roi_flow_s)
    assert r.peak_rss_bytes == 4096
    assert r.key == ("c1", "CROI", "mps", "cold_independent", 2)


# ---- run_benchmark orchestrator -------------------------------------------

def test_run_benchmark_iterates_passes_and_keeps_temp_zero(tmp_path):
    dl = _fake_downloader_factory()

    def manager_factory(cm):
        return bench.DownloadManager(dl, cm, _Ticker())

    recs = bench.run_benchmark(
        [_reduced_clip("c1")], conditions=["A6", "B12"],
        cache_modes=["cold_independent", "warm_same_run"],
        adapters={"A6": _adapter_ok("A6"), "B12": _adapter_ok("B12")},
        manager_factory=manager_factory, resolve_r2_key=lambda cid: "clips/k.mp4", device="mps",
        temp_root=str(tmp_path), deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()),
        rusage_fn=lambda: 1024, warmup=1, repeats=2)
    # cold(warmup,r1,r2)+warm(warmup,r1,r2)=6 passes × 2 conds = 12 records
    assert len(recs) == 12
    assert sum(1 for r in recs if r.is_warmup) == 4      # 2 warmup passes × 2 conds
    assert bench.count_media_files(tmp_path) == 0
    agg = bench.aggregate(recs)                          # measured 만 집계
    assert ("A6", "mps", "cold_independent") in agg


def test_run_benchmark_resumes_from_completed(tmp_path):
    log = tmp_path / "raw.jsonl"
    dl = _fake_downloader_factory()

    def mf(cm):
        return bench.DownloadManager(dl, cm, _Ticker())

    kwargs = dict(
        conditions=["A6"], cache_modes=["cold_independent"], adapters={"A6": _adapter_ok("A6")},
        manager_factory=mf, resolve_r2_key=lambda c: "k", device="mps", temp_root=str(tmp_path),
        rusage_fn=lambda: 1, result_log=str(log), warmup=1, repeats=2)
    bench.run_benchmark([_reduced_clip("c1")],
                        deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()), **kwargs)
    calls_after_first = dl.state["calls"]
    completed = bench.load_completed_keys(log)
    bench.run_benchmark([_reduced_clip("c1")],
                        deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()),
                        completed=completed, **kwargs)
    assert dl.state["calls"] == calls_after_first        # 완료 키는 재실행/재다운로드 안 함


# ---- S1 게이트 평가 (verdict·독립 재계산 근거) -----------------------------

def _cell(cap, rss=1000, temp=1000):
    return {"capacity_per_hour": cap, "peak_rss_bytes": rss, "temp_peak_bytes": temp}


def test_evaluate_s1_gates_pass():
    agg = {("CROI", "mps", "cold_independent"): _cell(200.0)}
    g = bench.evaluate_s1_gates(agg, projected_4cam_p95=80.0)
    assert g["required_capacity"] == pytest.approx(160.0)
    assert g["croi_mps_capacity"] == pytest.approx(200.0)
    assert g["throughput_ratio"] == pytest.approx(200.0 / 80.0)
    assert g["throughput_pass"] is True
    assert g["rss_pass"] is True
    assert g["disk_pass"] is True
    assert g["all_pass"] is True


def test_evaluate_s1_gates_throughput_fail():
    agg = {("CROI", "mps", "cold_independent"): _cell(100.0)}
    g = bench.evaluate_s1_gates(agg, projected_4cam_p95=80.0)
    assert g["throughput_pass"] is False
    assert g["all_pass"] is False


def test_evaluate_s1_gates_rss_and_disk_limits():
    agg = {("CROI", "mps", "cold_independent"): _cell(200.0, rss=5 * 1024 ** 3, temp=1000)}
    g = bench.evaluate_s1_gates(agg, projected_4cam_p95=80.0)
    assert g["rss_pass"] is False    # 5 GiB > 4 GiB
    agg2 = {("CROI", "mps", "cold_independent"): _cell(200.0, rss=1000, temp=3 * 1024 ** 3)}
    g2 = bench.evaluate_s1_gates(agg2, projected_4cam_p95=80.0)
    assert g2["disk_pass"] is False  # 3 GiB > 2 GiB


def test_evaluate_s1_gates_missing_croi_cell_fails_closed():
    with pytest.raises(bench.BenchContractError):
        bench.evaluate_s1_gates({("A6", "mps", "cold_independent"): _cell(200.0)}, projected_4cam_p95=80.0)


# ==========================================================================
# H1 — Device contract: CPU 요청이 실제 CPU 실행을 보장해야 한다
#   RED: DeviceContractDetector 존재하지 않음 → AttributeError
# ==========================================================================

class _FakeDetectorWithDevice:
    """device 속성을 가진 가짜 GeckoDetector (lazy-load 완료 상태 시뮬레이션)."""
    def __init__(self, actual_device):
        self.device = actual_device

    def detect(self, frame):
        return []


def test_device_contract_detector_exists():
    """DeviceContractDetector 클래스가 bench 모듈에 존재해야 한다."""
    assert hasattr(bench, "DeviceContractDetector"), (
        "DeviceContractDetector not found — H1 not yet implemented"
    )


def test_device_contract_mismatch_raises_safety_abort():
    """요청 device(cpu)와 실제 model device(mps)가 다르면 SafetyAbort(device_mismatch)."""
    inner = _FakeDetectorWithDevice("mps")
    wrapper = bench.DeviceContractDetector(inner, requested="cpu")
    with pytest.raises(bench.SafetyAbort) as exc:
        wrapper.detect(object())
    assert exc.value.code == "device_mismatch"


def test_device_contract_match_passes_through():
    """요청 device와 실제 device가 일치하면 정상 동작."""
    inner = _FakeDetectorWithDevice("cpu")
    wrapper = bench.DeviceContractDetector(inner, requested="cpu")
    result = wrapper.detect(object())
    assert result == []


def test_device_contract_mps_match_passes():
    """MPS 요청 + MPS device → 통과."""
    inner = _FakeDetectorWithDevice("mps")
    wrapper = bench.DeviceContractDetector(inner, requested="mps")
    result = wrapper.detect(object())
    assert result == []


def test_device_contract_verified_only_once():
    """device 불일치 여부는 첫 detect 에서 확인. 두 번째 호출은 정상 통과해야 한다."""
    inner = _FakeDetectorWithDevice("cpu")
    wrapper = bench.DeviceContractDetector(inner, requested="cpu")
    wrapper.detect(object())  # first call — verify
    wrapper.detect(object())  # second call — skip reverify


def test_device_contract_no_device_attr_raises():
    """model 이 device 속성 없으면 device_check_failed 로 fail-closed."""
    class _DetNoDevice:
        def detect(self, frame):
            return []

    wrapper = bench.DeviceContractDetector(_DetNoDevice(), requested="cpu")
    with pytest.raises(bench.SafetyAbort) as exc:
        wrapper.detect(object())
    assert exc.value.code in ("device_mismatch", "device_check_failed")


# ==========================================================================
# H1 production API — GeckoDetector signature + RF-DETR nested device path
#   RED: 현재 _check_device는 inner.device 만 읽고 inner._model.model.device 경로를 모름
# ==========================================================================

class _FakeTorchModel:
    """torch model 역할 — .device 속성 보유."""
    def __init__(self, device_str: str):
        self.device = device_str


class _FakeRFDETRInner:
    """RFDETR 인스턴스 역할 — .model = _FakeTorchModel."""
    def __init__(self, device_str: str):
        self.model = _FakeTorchModel(device_str)


class _FakeGeckoWithRFDETR:
    """GeckoDetector 역할 — ._model = _FakeRFDETRInner (lazy-load 완료 상태)."""
    def __init__(self, device_str: str):
        self._model = _FakeRFDETRInner(device_str)

    def detect(self, frame):
        return []


def test_device_contract_rfdetr_nested_model_device_match():
    """inner._model.model.device 경로가 requested device 와 일치하면 통과해야 한다.

    RED: 현재 _check_device 는 inner.device 만 읽어 _model.model.device 경로를 모름
         → device_check_failed 를 잘못 올린다.
    GREEN: _model.model.device 경로를 먼저 시도 → 일치하면 통과.
    """
    inner = _FakeGeckoWithRFDETR("cpu")
    wrapper = bench.DeviceContractDetector(inner, requested="cpu")
    result = wrapper.detect(object())  # must not raise
    assert result == []


def test_device_contract_rfdetr_nested_model_device_mismatch():
    """inner._model.model.device 가 requested 와 다르면 device_mismatch 여야 한다.

    RED: 현재는 _model.model.device 경로를 못 읽고 inner.device AttributeError 로 빠져
         device_check_failed 를 올린다 — wrong code.
    GREEN: _model.model.device 경로 읽기 성공 → 불일치면 device_mismatch.
    """
    inner = _FakeGeckoWithRFDETR("mps")
    wrapper = bench.DeviceContractDetector(inner, requested="cpu")
    with pytest.raises(bench.SafetyAbort) as exc:
        wrapper.detect(object())
    assert exc.value.code == "device_mismatch", (
        f"Expected device_mismatch but got {exc.value.code!r} — "
        "_check_device likely falling back to inner.device AttributeError path"
    )


def test_device_contract_rfdetr_model_exists_but_no_device_attr():
    """inner._model.model 이 있어도 .device 가 없으면 device_check_failed."""
    class _ModelNoDevice:
        pass  # no .device

    class _RFDETRNoDevice:
        model = _ModelNoDevice()

    class _GeckoNoDeviceInner:
        _model = _RFDETRNoDevice()
        def detect(self, frame):
            return []

    wrapper = bench.DeviceContractDetector(_GeckoNoDeviceInner(), requested="cpu")
    with pytest.raises(bench.SafetyAbort) as exc:
        wrapper.detect(object())
    assert exc.value.code == "device_check_failed"


def test_device_contract_production_signature_boundary_probe():
    """boundary probe: GeckoDetector 생성자에 device 인자가 없음을 production venv 에서 확인.

    handoff 명시 probe:
      PYTHONPATH=.../python-evidence-s1:...petcam-nightly-reporter
      /petcam-nightly-reporter/.venv/bin/python -c
      'from gecko_vision_gate.detector import GeckoDetector; import inspect; print(inspect.signature(GeckoDetector))'
    → "device" 가 signature 에 없어야 한다.
    """
    import subprocess
    probe = (
        "from gecko_vision_gate.detector import GeckoDetector; "
        "import inspect; "
        "sig = inspect.signature(GeckoDetector); "
        "assert 'device' not in sig.parameters, "
        "f'GeckoDetector gained device param: {sig}'"
    )
    result = subprocess.run(
        ["/Users/baek/petcam-nightly-reporter/.venv/bin/python", "-c", probe],
        env={
            **__import__("os").environ,
            "PYTHONPATH": (
                "/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1"
                ":/Users/baek/petcam-nightly-reporter"
            ),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Production API signature probe failed:\n{result.stderr}\n{result.stdout}"
    )


# ==========================================================================
# H2 — Temp peak: 원본 MP4를 포함해야 한다
#   RED: 현재 temp_peak_bytes 는 adapter 산출물만 반영
# ==========================================================================

def _fake_downloader_100bytes(r2_key, dest):
    """100-byte 더미 MP4."""
    Path(dest).write_bytes(b"m" * 100)


class _AdapterWith60BytesTemp:
    """60-byte temp 를 보고하는 어댑터 (MP4 자체를 세지 않음)."""
    def __call__(self, path):
        return bench.AdapterResult(
            condition="B12", decode_s=1.0, detector_s=1.0, roi_flow_s=0.0,
            frames_out=12, roi_status="n/a", risk_control_only=False,
            temp_peak_bytes=60,
        )


def test_temp_peak_includes_downloaded_mp4(tmp_path):
    """MP4 100B + adapter 60B → temp_peak_bytes >= 160."""
    mgr = bench.DownloadManager(_fake_downloader_100bytes, "cold_independent", _Ticker())
    recs = bench.run_pass(
        [_reduced_clip("c1")], ["B12"], cache_mode="cold_independent", manager=mgr,
        adapters={"B12": _AdapterWith60BytesTemp()},
        resolve_r2_key=lambda cid: "clips/k.mp4",
        deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()), device="mps",
        temp_root=str(tmp_path), repeat=1, is_warmup=False, rusage_fn=lambda: 1024,
    )
    assert recs[0].temp_peak_bytes >= 160, (
        f"Expected >= 160 (100 MP4 + 60 adapter), got {recs[0].temp_peak_bytes}"
    )


def test_temp_peak_nonzero_on_download_success_adapter_error(tmp_path):
    """다운로드 성공 + 어댑터 실패 시 temp_peak_bytes 는 0이 아니어야 한다."""
    def _bad_adapter(path):
        raise ValueError("adapter boom")

    mgr = bench.DownloadManager(_fake_downloader_100bytes, "cold_independent", _Ticker())
    recs = bench.run_pass(
        [_reduced_clip("c1")], ["B12"], cache_mode="cold_independent", manager=mgr,
        adapters={"B12": _bad_adapter},
        resolve_r2_key=lambda cid: "clips/k.mp4",
        deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()), device="mps",
        temp_root=str(tmp_path), repeat=1, is_warmup=False, rusage_fn=lambda: 1024,
    )
    rec = recs[0]
    assert rec.error_code == "ValueError"
    assert rec.temp_peak_bytes > 0, (
        f"Expected > 0 (100B MP4 was downloaded), got {rec.temp_peak_bytes}"
    )


def test_temp_peak_warm_no_double_count(tmp_path):
    """warm 모드: 같은 MP4를 두 조건이 공유해도 peak는 한 시점의 dest_dir 크기(중복 합산 X)."""
    mgr = bench.DownloadManager(_fake_downloader_100bytes, "warm_same_run", _Ticker())
    recs = bench.run_pass(
        [_reduced_clip("c1")], ["A6", "B12"], cache_mode="warm_same_run", manager=mgr,
        adapters={"A6": _AdapterWith60BytesTemp(), "B12": _AdapterWith60BytesTemp()},
        resolve_r2_key=lambda cid: "clips/k.mp4",
        deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()), device="mps",
        temp_root=str(tmp_path), repeat=1, is_warmup=False, rusage_fn=lambda: 1024,
    )
    # warm: A6/B12 가 같은 MP4 를 공유 → 각 record 의 peak 가 200+은 안 됨 (중복 합산 없음)
    for rec in recs:
        assert rec.temp_peak_bytes < 300, (
            f"Possible double-count: {rec.condition} peak={rec.temp_peak_bytes}"
        )


# ==========================================================================
# H3 — Threshold: production 과 동일한 0.10이어야 한다
#   RED: DEFAULT_GATE_THRESHOLD 존재하지 않음 → AttributeError
# ==========================================================================

def test_default_gate_threshold_is_0_10():
    """DEFAULT_GATE_THRESHOLD 상수가 0.10이어야 한다."""
    assert hasattr(bench, "DEFAULT_GATE_THRESHOLD"), (
        "DEFAULT_GATE_THRESHOLD not found — H3 not yet implemented"
    )
    assert bench.DEFAULT_GATE_THRESHOLD == pytest.approx(0.10)


def test_write_summary_meta_includes_gate_threshold(tmp_path):
    """summary.json meta 에 gate_threshold=0.10 이 포함돼야 한다."""
    recs = [_rec(repeat=1)]
    summary = bench.write_summary(
        recs,
        projected_4cam_p95=80.0,
        out_path=tmp_path / "summary.json",
        meta={"host": "test", "device": "mps", "gate_threshold": bench.DEFAULT_GATE_THRESHOLD},
    )
    assert summary["meta"].get("gate_threshold") == pytest.approx(0.10)


def test_gate_threshold_recorded_in_summary_meta_from_main_flow(tmp_path):
    """write_summary 에 threshold 포함 시 JSON 으로 직렬화 가능해야 한다."""
    recs = [_rec(repeat=1)]
    out = tmp_path / "summary.json"
    bench.write_summary(
        recs,
        projected_4cam_p95=80.0,
        out_path=out,
        meta={"gate_threshold": 0.10, "host": "x", "device": "mps"},
    )
    loaded = json.loads(out.read_text())
    assert loaded["meta"]["gate_threshold"] == pytest.approx(0.10)
