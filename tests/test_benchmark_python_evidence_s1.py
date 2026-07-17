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
# Task 1 (recovery) — FFmpeg 실행 의존성 preflight
#   A6 실패 확정 원인: SSH 비로그인 PATH 에 /opt/homebrew/bin 이 없어
#   shutil.which("ffmpeg") is None → extract_six subprocess FileNotFoundError.
#   guard 는 detector/R2/temp 어떤 부작용도 내기 전에 fail-closed 로 멈춘다.
# ==========================================================================

import subprocess  # noqa: E402


def test_verify_executable_dependency_missing_returns_ffmpeg_missing():
    """which_fn 이 None 이면 SafetyAbort('ffmpeg_missing')."""
    with pytest.raises(bench.SafetyAbort) as exc:
        bench.verify_executable_dependency(
            "ffmpeg",
            which_fn=lambda _n: None,
            run_fn=lambda _cmd: (_ for _ in ()).throw(AssertionError("run_fn must not run")),
        )
    assert exc.value.code == "ffmpeg_missing"


def test_verify_executable_dependency_missing_does_not_run_or_leak_path():
    """missing 은 run_fn 을 호출하지 않고, 메시지에 전체 PATH·비밀값을 담지 않는다."""
    ran = {"called": False}

    def _run(_cmd):
        ran["called"] = True
        return 0

    with pytest.raises(bench.SafetyAbort) as exc:
        bench.verify_executable_dependency("ffmpeg", which_fn=lambda _n: None, run_fn=_run)
    assert ran["called"] is False
    # 전체 PATH 노출 금지 — os.pathsep 로 이어진 디렉토리 목록이 새 나오면 안 된다.
    assert "/usr/bin:/bin" not in str(exc.value)


def test_verify_executable_dependency_unusable_nonzero_exit():
    """실행 가능 경로지만 run_fn 이 nonzero → SafetyAbort('ffmpeg_unusable')."""
    import sys
    with pytest.raises(bench.SafetyAbort) as exc:
        bench.verify_executable_dependency(
            "ffmpeg",
            which_fn=lambda _n: sys.executable,  # 실존 실행파일 → os.access 통과
            run_fn=lambda _cmd: 1,
        )
    assert exc.value.code == "ffmpeg_unusable"


def test_verify_executable_dependency_unusable_on_timeout():
    """run_fn 이 TimeoutExpired 를 던지면 SafetyAbort('ffmpeg_unusable')."""
    import sys

    def _run(cmd):
        raise subprocess.TimeoutExpired(cmd, 5)

    with pytest.raises(bench.SafetyAbort) as exc:
        bench.verify_executable_dependency(
            "ffmpeg", which_fn=lambda _n: sys.executable, run_fn=_run)
    assert exc.value.code == "ffmpeg_unusable"


def test_verify_executable_dependency_returns_resolved_path():
    """정상: run_fn exit 0 → 해석된 절대경로 반환."""
    import sys
    resolved = bench.verify_executable_dependency(
        "ffmpeg", which_fn=lambda _n: sys.executable, run_fn=lambda _cmd: 0)
    assert resolved == sys.executable


def test_main_ffmpeg_guard_runs_before_detector_r2_temp(monkeypatch, tmp_path):
    """main(): ffmpeg guard 실패 시 detector loader·R2 resolver·temp factory 는 호출되지 않는다."""
    import backend.supabase_client as sc

    called = {"build_adapters": 0, "tempdir": 0, "supabase": 0}

    monkeypatch.setattr("socket.gethostname", lambda: bench.EXPECTED_HOST)
    monkeypatch.setattr(bench, "_repo_git_state", lambda _d: ("PINNEDSHA", False))
    monkeypatch.setattr(bench, "verify_ffmpeg_available",
                        lambda: (_ for _ in ()).throw(bench.SafetyAbort("ffmpeg_missing", "x")))

    def _spy_build(*a, **k):
        called["build_adapters"] += 1
        raise AssertionError("build_adapters must not run after ffmpeg abort")

    def _spy_tempdir(*a, **k):
        called["tempdir"] += 1
        raise AssertionError("scoped_tempdir must not run after ffmpeg abort")

    def _spy_supabase(*a, **k):
        called["supabase"] += 1
        raise AssertionError("get_supabase_client must not run after ffmpeg abort")

    monkeypatch.setattr(bench, "build_adapters", _spy_build)
    monkeypatch.setattr(bench, "scoped_tempdir", _spy_tempdir)
    monkeypatch.setattr(sc, "get_supabase_client", _spy_supabase)

    rc = bench.main([
        "--manifest", str(tmp_path / "m.json"),
        "--influx", str(tmp_path / "i.json"),
        "--pinned-sha", "PINNEDSHA",
        "--out-dir", str(tmp_path / "out"),
        "--device", "mps",
        "--checkpoint", str(tmp_path / "ckpt.pth"),
        "--window-minutes", "60",
        "--activity-lock-free", "--vlm-lock-free",
    ])
    assert rc != 0
    assert called == {"build_adapters": 0, "tempdir": 0, "supabase": 0}


# ==========================================================================
# Task 2 (recovery) — success-only resume + completeness contract
#   error_code 있는 measured key 는 완료로 치지 않고 재시도 가능해야 하며
#   (A6 FileNotFoundError 99건이 "완료"로 오인돼 재측정 안 되던 문제),
#   warmup 은 measured key 를 채우지 않고, 중복 성공 record 는 계약 오류다.
# ==========================================================================

def _mk_clips(n=32, reduced=16):
    return [
        bench.ClipSpec(
            clip_id=f"clip{i:02d}", camera_short="cam", bbox_stratum="q1",
            duration_sec=60.0, quartile=1, in_reduced=(i < reduced))
        for i in range(n)
    ]


def test_successful_completed_key_skipped_on_resume(tmp_path):
    p = tmp_path / "raw_results.jsonl"
    ok = _rec(clip_id="c1", condition="CROI", device="mps",
              cache_mode="cold_independent", repeat=2, is_warmup=False, error_code=None)
    bench.append_record(p, ok)
    keys = bench.successful_completed_keys(p)
    assert ok.key in keys


def test_error_code_key_not_skipped_and_retried(tmp_path):
    """error_code 가 있는 measured key 는 성공 집합에 없어 재시도 대상이어야 한다."""
    p = tmp_path / "raw_results.jsonl"
    err = _rec(clip_id="c2", condition="A6", device="mps",
               cache_mode="cold_independent", repeat=1, is_warmup=False,
               e2e_s=0.0, error_code="FileNotFoundError")
    bench.append_record(p, err)
    keys = bench.successful_completed_keys(p)
    assert err.key not in keys


def test_error_then_success_same_key_is_completed(tmp_path):
    """같은 key 의 error record 뒤 success record 가 오면 완료로 인정(재시도 성공)."""
    p = tmp_path / "raw_results.jsonl"
    key_args = dict(clip_id="c3", condition="B12", device="mps",
                    cache_mode="warm_same_run", repeat=3, is_warmup=False)
    bench.append_record(p, _rec(**key_args, e2e_s=0.0, error_code="FileNotFoundError"))
    bench.append_record(p, _rec(**key_args, e2e_s=9.0, error_code=None))
    keys = bench.successful_completed_keys(p)
    assert ("c3", "B12", "mps", "warm_same_run", 3) in keys


def test_warmup_record_never_satisfies_measured_key(tmp_path):
    p = tmp_path / "raw_results.jsonl"
    warm = _rec(clip_id="c4", condition="CROI", device="mps",
                cache_mode="cold_independent", repeat=0, is_warmup=True, error_code=None)
    bench.append_record(p, warm)
    keys = bench.successful_completed_keys(p)
    assert warm.key not in keys
    assert keys == set()


def test_nonfinite_e2e_success_not_counted(tmp_path):
    p = tmp_path / "raw_results.jsonl"
    bad = _rec(clip_id="c5", condition="CROI", device="mps",
               cache_mode="cold_independent", repeat=1, is_warmup=False,
               e2e_s=0.0, error_code=None)  # e2e 0 = 무효 timing
    bench.append_record(p, bad)
    assert bench.successful_completed_keys(p) == set()


def test_duplicate_successful_measured_keys_rejected(tmp_path):
    p = tmp_path / "raw_results.jsonl"
    args = dict(clip_id="c6", condition="CROI", device="mps",
                cache_mode="cold_independent", repeat=1, is_warmup=False, error_code=None)
    bench.append_record(p, _rec(**args, e2e_s=10.0))
    bench.append_record(p, _rec(**args, e2e_s=11.0))
    with pytest.raises(bench.BenchContractError):
        bench.successful_completed_keys(p)


def test_successful_completed_tolerates_corrupt_trailing_line(tmp_path):
    p = tmp_path / "raw_results.jsonl"
    ok = _rec(clip_id="c7", repeat=1, is_warmup=False, error_code=None, e2e_s=8.0)
    bench.append_record(p, ok)
    with p.open("a", encoding="utf-8") as fh:
        fh.write('{"clip_id": "c8", "condi')  # truncated crash line
    keys = bench.successful_completed_keys(p)
    assert ok.key in keys


def test_expected_measured_keys_mps_full_workload():
    clips = _mk_clips(32, reduced=16)
    keys = bench.expected_measured_keys(clips, device="mps", repeats=3)
    # A6/B12/CROI = 32 clips each; DALL = reduced 16; × 2 cache modes × 3 repeats.
    per_cache = 32 * 3 + 16  # 112 measured (condition,clip) per cache/repeat
    assert len(keys) == per_cache * 2 * 3  # 672
    dall = {k for k in keys if k[1] == "DALL"}
    assert len({k[0] for k in dall}) == 16
    for cond in ("A6", "B12", "CROI"):
        clip_ids = {k[0] for k in keys if k[1] == cond}
        assert len(clip_ids) == 32
    assert {k[3] for k in keys} == {"cold_independent", "warm_same_run"}
    assert {k[4] for k in keys} == {1, 2, 3}
    assert all(k[2] == "mps" for k in keys)


def test_expected_measured_keys_cpu_reduced_only():
    clips = _mk_clips(32, reduced=16)
    keys = bench.expected_measured_keys(clips, device="cpu", repeats=3)
    # CPU: reduced 16 for all four conditions × 2 cache × 3 repeats.
    assert len(keys) == 16 * 4 * 2 * 3  # 384
    assert {k[0] for k in keys} == {f"clip{i:02d}" for i in range(16)}
    assert {k[1] for k in keys} == {"A6", "B12", "CROI", "DALL"}
    assert all(k[2] == "cpu" for k in keys)


def test_completeness_report_separates_missing_and_unexpected():
    expected = {("a", "A6", "mps", "cold_independent", 1),
                ("b", "A6", "mps", "cold_independent", 1)}
    actual = {("a", "A6", "mps", "cold_independent", 1),
              ("z", "DALL", "mps", "warm_same_run", 2)}
    rep = bench.completeness_report(expected, actual)
    assert rep["missing_count"] == 1
    assert rep["unexpected_count"] == 1
    assert ("b", "A6", "mps", "cold_independent", 1) in rep["missing"]
    assert ("z", "DALL", "mps", "warm_same_run", 2) in rep["unexpected"]
    assert rep["complete"] is False


def test_completeness_report_complete_when_exact_match():
    keys = {("a", "A6", "mps", "cold_independent", 1)}
    rep = bench.completeness_report(keys, set(keys))
    assert rep["complete"] is True
    assert rep["missing_count"] == 0 and rep["unexpected_count"] == 0


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


# ==========================================================================
# H1 lazy-load ordering fix — _model=None 초기 상태에서 detect() 가 올바르게 동작해야 한다
#
#   핵심 버그: DeviceContractDetector.detect() 가
#     1) _check_device()  ← _model=None 이라 device_check_failed
#     2) inner.detect()   ← _ensure_loaded() 가 여기서 _model 설정
#   순서로 실행 → 첫 호출이 device_check_failed 로 끝남.
#
#   수정 후 올바른 순서:
#     1) inner.detect()   ← _ensure_loaded() 완료 → _model 설정됨
#     2) _check_device()  ← _model.model.device 읽기 가능
#
#   RED: 현재 코드는 _model=None lazy fake 에서 device_check_failed 를 올린다.
#   GREEN: detect() 순서 수정 후 통과.
# ==========================================================================

class _GeckoLazyModel:
    """GeckoDetector lazy-load 시뮬레이션.

    초기 _model=None; detect() 에서 _ensure_loaded() 상당의 동작으로 _model 설정.
    """

    class _TorchModel:
        def __init__(self, device_str: str):
            self.device = device_str

    class _RFDETR:
        def __init__(self, device_str: str):
            self.model = None  # will be set in __init__

        def _set(self, device_str: str):
            self.model = _GeckoLazyModel._TorchModel(device_str)

    def __init__(self, device_str: str):
        self._model = None       # lazy — not yet loaded
        self._device_str = device_str

    def detect(self, frame):
        # simulate _ensure_loaded() — sets _model on first detect()
        if self._model is None:
            r = _GeckoLazyModel._RFDETR(self._device_str)
            r._set(self._device_str)
            self._model = r
        return []


def test_lazy_load_ordering_bug_is_red_with_matching_device():
    """RED 확인: 현재 코드는 _model=None lazy fake + 일치하는 device 에서도 device_check_failed.

    현재 _check_device() 가 inner.detect() 보다 먼저 실행되어 _model=None → 실패.
    GREEN 후에는 inner.detect() 가 먼저 실행되어 _model 이 설정된 뒤 _check_device() 통과.
    """
    inner = _GeckoLazyModel("cpu")
    wrapper = bench.DeviceContractDetector(inner, requested="cpu")
    # 수정 전(RED): 이 호출은 device_check_failed 를 올린다 → 아래 assert 를 주석 처리해 RED 확인.
    # 수정 후(GREEN): 통과해야 한다.
    result = wrapper.detect(object())  # must not raise after fix
    assert result == []


def test_lazy_load_ordering_mismatch_gives_device_mismatch_not_check_failed():
    """lazy-load 후 device 불일치 → device_mismatch (device_check_failed 가 아니어야 함).

    수정 전(RED): _model=None 상태에서 _check_device() 가 먼저 실행 → device_check_failed.
    수정 후(GREEN): inner.detect() 가 먼저 실행 → _model 설정 → device 읽기 가능 → device_mismatch.
    """
    inner = _GeckoLazyModel("mps")   # loads on mps
    wrapper = bench.DeviceContractDetector(inner, requested="cpu")
    with pytest.raises(bench.SafetyAbort) as exc:
        wrapper.detect(object())
    assert exc.value.code == "device_mismatch", (
        f"Expected device_mismatch (lazy _model set by inner.detect first), "
        f"got {exc.value.code!r} — ordering bug still present"
    )


def test_lazy_load_verified_is_true_after_successful_detect():
    """detect() 성공 후 _verified=True 가 돼야 한다 (다음 호출 중복 검증 방지)."""
    inner = _GeckoLazyModel("cpu")
    wrapper = bench.DeviceContractDetector(inner, requested="cpu")
    wrapper.detect(object())
    assert wrapper._verified is True


def test_lazy_load_result_not_returned_on_device_mismatch():
    """device_mismatch 시 inner.detect() 결과를 caller 에 반환하지 말고 abort 해야 한다."""
    inner = _GeckoLazyModel("mps")
    wrapper = bench.DeviceContractDetector(inner, requested="cpu")
    try:
        wrapper.detect(object())
        assert False, "Should have raised SafetyAbort"
    except bench.SafetyAbort as e:
        assert e.code == "device_mismatch"
    # _verified remains False — mismatch detected, no partial state
    assert wrapper._verified is False


# ==========================================================================
# H1 checkpoint_required / checkpoint_missing — COCO fallback 완전 금지
# ==========================================================================

def test_build_adapters_checkpoint_required_on_empty_string(tmp_path):
    """checkpoint 빈 문자열 → SafetyAbort('checkpoint_required') (COCO fallback 없음)."""
    import torch

    class _FakeTorchMPS:
        class _Backends:
            class _MPS:
                @staticmethod
                def is_available():
                    return True
            mps = _MPS()
        backends = _Backends()

    with pytest.raises(bench.SafetyAbort) as exc:
        bench.build_adapters(
            "cpu",
            checkpoint="",
            model_size="nano",
            deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()),
        )
    assert exc.value.code == "checkpoint_required"


def test_build_adapters_checkpoint_missing_on_nonexistent_file(tmp_path):
    """존재하지 않는 checkpoint 경로 → SafetyAbort('checkpoint_missing')."""
    with pytest.raises(bench.SafetyAbort) as exc:
        bench.build_adapters(
            "cpu",
            checkpoint=str(tmp_path / "nonexistent.pth"),
            model_size="nano",
            deadline=bench.Deadline(budget_s=10 ** 9, clock=_Ticker()),
        )
    assert exc.value.code == "checkpoint_missing"


# ==========================================================================
# H1 eager device loader — _make_detector() 아키텍처 교체 (handoff 2026-07-17)
#
#   RED: _make_detector 이 _BenchmarkGeckoDetector 서브클래스 + DeviceContractDetector
#        래퍼를 쓰며 device 검증이 첫 detect() 즉 첫 R2 다운로드 이후에야 발생.
#   GREEN: eager load + _model/_names 주입 + 반환 전 즉시 device 검증.
#          _BenchmarkGeckoDetector/_ensure_loaded override/DeviceContractDetector 래퍼 제거.
#
#   주입 가능한 factory:
#     _rfdetr_factory(path, device) → rfdetr_model
#     _gecko_factory(model_size, threshold, checkpoint) → detector
#     _torch_module → resolve_device 에 전달 (cpu 테스트에선 FakeTorch 사용)
# ==========================================================================

class _FakeRFDETRModel:
    """fake RFDETR 인스턴스 — .model.device 보유, .class_names 지원."""

    class _TorchModel:
        def __init__(self, device_str: str):
            self.device = device_str

    def __init__(self, device_str: str, class_names=None):
        self.class_names = class_names or ["gecko", "other"]
        self.model = _FakeRFDETRModel._TorchModel(device_str)
        self.optimize_called = False

    def optimize_for_inference(self):
        self.optimize_called = True


class _FakeGeckoInner:
    """fake GeckoDetector — 생성자 인자 기록, detect() 카운트."""

    def __init__(self, model_size, threshold, checkpoint):
        self.model_size = model_size
        self.threshold = threshold
        self.checkpoint = checkpoint
        self._model = None
        self._names = {}
        self.detect_calls = 0

    def detect(self, frame):
        self.detect_calls += 1
        return []


def _rfdetr_factory(rfdetr_device_str, class_names=None):
    """RFDETR factory — 호출 횟수·인자를 기록한다."""
    state = {"calls": 0, "kwargs": []}

    def factory(path, dev):
        state["calls"] += 1
        state["kwargs"].append({"path": path, "device": dev})
        return _FakeRFDETRModel(rfdetr_device_str, class_names)

    factory.state = state
    return factory


def _gecko_factory():
    """GeckoDetector factory — 호출 횟수·인자를 기록한다."""
    state = {"calls": 0, "args": []}

    def factory(model_size, threshold, checkpoint):
        state["calls"] += 1
        state["args"].append({"model_size": model_size, "threshold": threshold,
                              "checkpoint": checkpoint})
        return _FakeGeckoInner(model_size, threshold, checkpoint)

    factory.state = state
    return factory


def _call_make_det(tmp_path, device="cpu", rfdetr_dev="cpu", threshold=0.10, class_names=None):
    """fake checkpoint + fake factories로 _make_detector 호출 helper."""
    ckpt = tmp_path / "model.pth"
    ckpt.write_bytes(b"fake")
    rf = _rfdetr_factory(rfdetr_dev, class_names)
    gf = _gecko_factory()
    det = bench._make_detector(
        device, str(ckpt), "nano",
        threshold=threshold,
        _rfdetr_factory=rf,
        _gecko_factory=gf,
        _torch_module=_FakeTorch(True),
    )
    return det, rf, gf


def test_make_detector_eager_passes_device_to_rfdetr(tmp_path):
    """requested device가 RFDETR factory에 정확히 전달돼야 한다."""
    _, rf, _ = _call_make_det(tmp_path, device="cpu")
    assert rf.state["calls"] == 1
    assert rf.state["kwargs"][0]["device"] == "cpu"


def test_make_detector_no_device_to_gate_constructor(tmp_path):
    """GeckoDetector factory는 device 인자를 받지 않아야 한다."""
    _, _, gf = _call_make_det(tmp_path)
    assert gf.state["calls"] == 1
    args = gf.state["args"][0]
    assert "device" not in args
    assert set(args.keys()) == {"model_size", "threshold", "checkpoint"}


def test_make_detector_threshold_passed(tmp_path):
    """threshold=0.10이 GeckoDetector factory에 정확히 전달돼야 한다."""
    _, _, gf = _call_make_det(tmp_path, threshold=0.10)
    assert gf.state["args"][0]["threshold"] == pytest.approx(0.10)


def test_make_detector_model_and_names_injected(tmp_path):
    """_model과 _names가 반환 전 주입돼야 한다."""
    det, _, _ = _call_make_det(tmp_path, class_names=["gecko", "other"])
    assert det._model is not None
    assert det._names == {0: "gecko", 1: "other"}


def test_make_detector_device_mismatch_aborts_before_return(tmp_path):
    """RFDETR model.device가 requested와 다르면 SafetyAbort(device_mismatch) — 반환 전."""
    ckpt = tmp_path / "m.pth"
    ckpt.write_bytes(b"x")
    rf = _rfdetr_factory("mps")   # CPU 요청이지만 MPS로 로드
    gf = _gecko_factory()
    with pytest.raises(bench.SafetyAbort) as exc:
        bench._make_detector("cpu", str(ckpt), "nano",
                             _rfdetr_factory=rf, _gecko_factory=gf,
                             _torch_module=_FakeTorch(True))
    assert exc.value.code == "device_mismatch"


def test_make_detector_success_model_set_before_return(tmp_path):
    """성공 반환 시 detector._model이 이미 설정돼 있어야 한다 (deferred 아님)."""
    det, rf, _ = _call_make_det(tmp_path)
    assert det._model is not None
    assert rf.state["calls"] == 1   # 반환 전 1회 eager load


def test_make_detector_detect_no_rfdetr_reload(tmp_path):
    """detect() 여러 번 호출해도 RFDETR factory 재호출 없음."""
    det, rf, _ = _call_make_det(tmp_path)
    det.detect(object())
    det.detect(object())
    assert rf.state["calls"] == 1   # 재로드 없음
    assert det.detect_calls == 2    # gate detect() 직접 호출


def test_make_detector_not_wrapped_in_device_contract(tmp_path):
    """반환된 객체가 DeviceContractDetector 래퍼가 아니어야 한다."""
    det, _, _ = _call_make_det(tmp_path)
    assert not isinstance(det, bench.DeviceContractDetector)


def test_make_detector_subclass_removed():
    """_make_detector 소스에 _BenchmarkGeckoDetector와 _ensure_loaded override가 없어야 한다."""
    import inspect
    source = inspect.getsource(bench._make_detector)
    assert "_BenchmarkGeckoDetector" not in source, "서브클래스 제거 필요"
    assert "_ensure_loaded" not in source, "_ensure_loaded override 제거 필요"


def test_build_adapters_does_not_access_supabase_or_r2():
    """build_adapters 소스에 supabase/r2 접근 없음 — detector 검증 완료 후 Supabase/R2 생성."""
    import inspect
    source = inspect.getsource(bench.build_adapters)
    assert "supabase" not in source.lower(), "build_adapters가 supabase를 직접 접근하지 않아야 함"
    assert "get_supabase_client" not in source
    assert "_make_resolve_r2_key" not in source
