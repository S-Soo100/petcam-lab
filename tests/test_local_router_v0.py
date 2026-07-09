import json
from dataclasses import asdict

from scripts.local_router_v0 import (
    ALLOWED_ROUTES,
    P0_CLASSES,
    analyze_separability,
    decision_subtype,
    run,
    route_l0,
    route_l0_v1,
    route_with_ollama,
    select_smoke_evidences,
    summarize,
)
from scripts.rba_evidence_first_cascade import ClipRow, VideoEvidence
from scripts.local_router_v0 import prompt_for_local_llm


def _evidence_json_from_prompt(prompt: str) -> dict[str, object]:
    marker = "Evidence JSON:\n"
    assert marker in prompt
    evidence_json = prompt.split(marker, 1)[1]
    return json.loads(evidence_json)


def _evidence(**overrides: object) -> VideoEvidence:
    values = {
        "sample_id": "sample-001",
        "clip_id": "clip-001",
        "duration_sec": 60.0,
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "frame_count": 1800,
        "brightness_mean": 60.0,
        "brightness_std": 12.0,
        "saturation_mean": 18.0,
        "motion_mean": 0.008,
        "motion_peak": 0.014,
        "motion_std": 0.004,
        "active_motion_ratio": 0.08,
        "center_motion_ratio": 0.4,
        "late_motion_ratio": 0.5,
    }
    values.update(overrides)
    return VideoEvidence(**values)


def _summary(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "n": 100,
        "routes": {"cloud_now": 40, "cloud_later": 58, "activity_only": 2},
        "cloud_now_rate": 0.40,
        "p0_activity_only_rate": 0.0,
    }
    values.update(overrides)
    return values


def _separability(*, very_low_p0_rate: float = 0.0) -> dict[str, object]:
    return {
        "motion_mean": {
            "very_low": {
                "n": 10,
                "p0_count": 0,
                "p0_rate": very_low_p0_rate,
            }
        }
    }


def test_decision_subtype_rejects_when_l0_p0_activity_only_exceeds_two_percent() -> None:
    subtype = decision_subtype(
        l0_summary=_summary(p0_activity_only_rate=0.021),
        l1_summary=None,
        separability=_separability(),
    )

    assert subtype == "reject-unsafe"


def test_decision_subtype_rejects_when_l1_p0_activity_only_exceeds_two_percent() -> None:
    subtype = decision_subtype(
        l0_summary=_summary(p0_activity_only_rate=0.0),
        l1_summary=_summary(p0_activity_only_rate=0.021, cloud_now_rate=0.20),
        separability=_separability(),
    )

    assert subtype == "reject-unsafe"


def test_decision_subtype_marks_model_limited_when_l1_cloud_now_rate_is_at_least_ninety_percent() -> None:
    subtype = decision_subtype(
        l0_summary=_summary(cloud_now_rate=0.74, p0_activity_only_rate=0.0),
        l1_summary=_summary(cloud_now_rate=0.933, p0_activity_only_rate=0.0),
        separability=_separability(),
    )

    assert subtype == "hold-model-limited"


def test_decision_subtype_marks_input_limited_for_risky_static_activity_only() -> None:
    subtype = decision_subtype(
        l0_summary=_summary(routes={"activity_only": 1, "cloud_later": 99}, p0_activity_only_rate=0.0),
        l1_summary=None,
        separability=_separability(very_low_p0_rate=0.051),
    )

    assert subtype == "hold-input-limited"


def test_l0_routes_very_static_clip_to_activity_only() -> None:
    decision = route_l0(_evidence())

    assert decision.route == "activity_only"
    assert decision.priority < 0.3


def test_l0_routes_strong_motion_to_cloud_now() -> None:
    decision = route_l0(
        _evidence(
            motion_mean=0.04,
            motion_peak=0.15,
            active_motion_ratio=0.82,
        )
    )

    assert decision.route == "cloud_now"
    assert decision.risk == "high"


def test_l0_v1_prefers_cloud_later_for_moderate_motion() -> None:
    decision = route_l0_v1(
        _evidence(
            motion_mean=0.015,
            motion_peak=0.050,
            active_motion_ratio=0.35,
            brightness_mean=55.0,
            brightness_std=10.0,
        )
    )

    assert decision.route == "cloud_later"
    assert 0.35 <= decision.priority <= 0.70


def test_l0_v1_keeps_high_bursty_motion_cloud_now() -> None:
    decision = route_l0_v1(
        _evidence(
            motion_mean=0.030,
            motion_peak=0.150,
            motion_std=0.050,
            active_motion_ratio=0.75,
        )
    )

    assert decision.route == "cloud_now"
    assert decision.risk == "high"


def test_l0_v1_uses_activity_only_only_for_extreme_static_visible_clip() -> None:
    decision = route_l0_v1(
        _evidence(
            motion_mean=0.001,
            motion_peak=0.004,
            active_motion_ratio=0.01,
            brightness_mean=65.0,
            brightness_std=8.0,
        )
    )

    assert decision.route == "activity_only"


def test_l0_v1_keeps_p0_activity_only_rate_within_two_percent() -> None:
    p0 = next(iter(P0_CLASSES))
    rows = {
        "sample-001": ClipRow(filename="p0-static.mp4", clip_id="clip-001", gt=p0),
        "sample-002": ClipRow(filename="moving.mp4", clip_id="clip-002", gt="moving"),
        "sample-003": ClipRow(filename="calm.mp4", clip_id="clip-003", gt="moving"),
    }
    evidences = [
        _evidence(
            sample_id="sample-001",
            clip_id="clip-001",
            motion_mean=0.004,
            motion_peak=0.011,
            active_motion_ratio=0.06,
            brightness_mean=64.0,
            brightness_std=8.0,
        ),
        _evidence(
            sample_id="sample-002",
            clip_id="clip-002",
            motion_mean=0.018,
            motion_peak=0.060,
            active_motion_ratio=0.32,
        ),
        _evidence(
            sample_id="sample-003",
            clip_id="clip-003",
            motion_mean=0.032,
            motion_peak=0.145,
            active_motion_ratio=0.78,
        ),
    ]

    result = summarize([route_l0_v1(e) for e in evidences], rows)

    assert result["p0_total"] == 1
    assert result["p0_activity_only_rate"] <= 0.02


def test_run_uses_v1_router_when_policy_is_v1(tmp_path, monkeypatch) -> None:
    experiment_dir = tmp_path / "experiment"
    feature_path = experiment_dir / "features.jsonl"
    feature_path.parent.mkdir(parents=True, exist_ok=True)
    feature_path.write_text(
        json.dumps(asdict(_evidence(sample_id="sample-001", clip_id="clip-001")), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    rows = [ClipRow(filename="a.mp4", clip_id="clip-001", gt="moving")]

    calls: list[str] = []

    monkeypatch.setattr("scripts.local_router_v0.load_manifest", lambda *_: rows)
    monkeypatch.setattr("scripts.local_router_v0.select_rows", lambda manifest_rows, *_: manifest_rows)
    monkeypatch.setattr("scripts.local_router_v0.sample_id_for", lambda row, index: f"sample-{index:03d}")
    monkeypatch.setattr(
        "scripts.local_router_v0.extract_video_evidence",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not extract videos")),
    )
    monkeypatch.setattr(
        "scripts.local_router_v0.route_l0",
        lambda evidence: calls.append("v0") or route_l0(evidence),
    )
    monkeypatch.setattr(
        "scripts.local_router_v0.route_l0_v1",
        lambda evidence: calls.append("v1") or route_l0_v1(evidence),
    )

    run(
        type(
            "Args",
            (),
            {
                "manifest": str(tmp_path / "manifest.csv"),
                "experiment_dir": str(experiment_dir),
                "sample_size": 1,
                "seed": 20260709,
                "frame_samples": 16,
                "summarize_only": True,
                "run_ollama": False,
                "ollama_model": "",
                "ollama_limit": 30,
                "ollama_timeout_sec": 30,
                "l0_policy": "v1",
            },
        )()
    )

    assert calls == ["v1"]


def test_l0_v1_routes_stay_within_allowed_set_and_skip_forbidden_routes() -> None:
    decisions = [
        route_l0_v1(
            _evidence(
                sample_id="sample-001",
                clip_id="clip-001",
                motion_mean=0.001,
                motion_peak=0.004,
                active_motion_ratio=0.01,
                brightness_mean=65.0,
                brightness_std=8.0,
            )
        ),
        route_l0_v1(
            _evidence(
                sample_id="sample-002",
                clip_id="clip-002",
                motion_mean=0.016,
                motion_peak=0.060,
                active_motion_ratio=0.30,
            )
        ),
        route_l0_v1(
            _evidence(
                sample_id="sample-003",
                clip_id="clip-003",
                motion_mean=0.032,
                motion_peak=0.150,
                active_motion_ratio=0.80,
            )
        ),
        route_l0_v1(
            _evidence(
                sample_id="sample-004",
                clip_id="clip-004",
                brightness_mean=10.0,
                brightness_std=1.0,
            )
        ),
    ]

    routes = {decision.route for decision in decisions}

    assert routes <= ALLOWED_ROUTES
    assert routes.isdisjoint({"skip", "auto_moving", "auto_p0"})


def test_prompt_v1_contains_cloud_later_examples_and_forbidden_routes() -> None:
    prompt = prompt_for_local_llm(_evidence(), prompt_mode="v1")
    evidence_json = _evidence_json_from_prompt(prompt)

    assert "cloud_later" in prompt
    assert "activity_only" in prompt
    assert "Forbidden routes" in prompt
    assert "skip" in prompt
    assert "gt" not in evidence_json
    assert "label" not in evidence_json
    assert all("moving" != value for value in evidence_json.values())
    assert all("drinking" != value for value in evidence_json.values())


def test_route_with_ollama_passes_prompt_mode_through(monkeypatch) -> None:
    prompt_modes: list[str] = []

    def fake_prompt_for_local_llm(evidence: VideoEvidence, *, prompt_mode: str = "v0") -> str:
        prompt_modes.append(prompt_mode)
        return '{"route":"cloud_later","priority":0.4,"risk":"medium","reason":"ok"}'

    class Proc:
        returncode = 0
        stdout = '{"route":"cloud_later","priority":0.4,"risk":"medium","reason":"ok"}'
        stderr = ""

    monkeypatch.setattr("scripts.local_router_v0.prompt_for_local_llm", fake_prompt_for_local_llm)
    monkeypatch.setattr("scripts.local_router_v0.subprocess.run", lambda *args, **kwargs: Proc())

    decision = route_with_ollama(_evidence(), model="mock", timeout_sec=1, prompt_mode="v1")

    assert prompt_modes == ["v1"]
    assert decision.route == "cloud_later"


def test_summary_counts_p0_activity_only_rate() -> None:
    p0 = next(iter(P0_CLASSES))
    evidences = [
        _evidence(sample_id="sample-001", clip_id="clip-001"),
        _evidence(sample_id="sample-002", clip_id="clip-002", motion_mean=0.05, motion_peak=0.2),
    ]
    decisions = [route_l0(e) for e in evidences]
    rows = {
        "sample-001": ClipRow(filename="neutral-a.mp4", clip_id="clip-001", gt=p0),
        "sample-002": ClipRow(filename="neutral-b.mp4", clip_id="clip-002", gt="moving"),
    }

    result = summarize(decisions, rows)

    assert result["p0_total"] == 1
    assert result["p0_activity_only_count"] == 1
    assert result["p0_activity_only_rate"] == 1.0


def test_select_smoke_evidences_includes_each_class_before_fill() -> None:
    evidences = [
        _evidence(sample_id=f"sample-{i:03d}", clip_id=f"clip-{i:03d}")
        for i in range(6)
    ]
    rows = {
        "sample-000": ClipRow(filename="a.mp4", clip_id="clip-000", gt="moving"),
        "sample-001": ClipRow(filename="b.mp4", clip_id="clip-001", gt="moving"),
        "sample-002": ClipRow(filename="c.mp4", clip_id="clip-002", gt="drinking"),
        "sample-003": ClipRow(filename="d.mp4", clip_id="clip-003", gt="drinking"),
        "sample-004": ClipRow(filename="e.mp4", clip_id="clip-004", gt="shedding"),
        "sample-005": ClipRow(filename="f.mp4", clip_id="clip-005", gt="shedding"),
    }

    selected = select_smoke_evidences(evidences, rows, limit=3, seed=20260709)
    selected_gts = {rows[e.sample_id].gt for e in selected}

    assert selected_gts == {"moving", "drinking", "shedding"}


def test_analyze_separability_reports_p0_rate_per_bucket() -> None:
    evidences = [
        _evidence(
            sample_id="sample-001",
            clip_id="clip-001",
            motion_mean=0.001,
            motion_peak=0.004,
            active_motion_ratio=0.01,
        ),
        _evidence(
            sample_id="sample-002",
            clip_id="clip-002",
            motion_mean=0.002,
            motion_peak=0.006,
            active_motion_ratio=0.02,
        ),
        _evidence(
            sample_id="sample-003",
            clip_id="clip-003",
            motion_mean=0.050,
            motion_peak=0.200,
            active_motion_ratio=0.90,
        ),
    ]
    rows = {
        "sample-001": ClipRow(filename="neutral-a.mp4", clip_id="clip-001", gt="moving"),
        "sample-002": ClipRow(filename="neutral-b.mp4", clip_id="clip-002", gt="drinking"),
        "sample-003": ClipRow(filename="neutral-c.mp4", clip_id="clip-003", gt="moving"),
    }

    result = analyze_separability(evidences, rows)

    assert result["motion_mean"]["very_low"]["n"] == 2
    assert result["motion_mean"]["very_low"]["p0_count"] == 1
    assert result["motion_mean"]["very_low"]["p0_rate"] == 0.5


def test_run_summarize_only_writes_separability_and_results(tmp_path, monkeypatch) -> None:
    p0 = next(iter(P0_CLASSES))
    experiment_dir = tmp_path / "experiment"
    feature_path = experiment_dir / "features.jsonl"
    feature_path.parent.mkdir(parents=True, exist_ok=True)
    feature_path.write_text(
        "\n".join(
            [
                json.dumps(
                    asdict(
                        _evidence(
                            sample_id="sample-001",
                            clip_id="clip-001",
                            motion_mean=0.001,
                            motion_peak=0.004,
                            active_motion_ratio=0.01,
                        )
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                json.dumps(
                    asdict(
                        _evidence(
                            sample_id="sample-002",
                            clip_id="clip-002",
                            motion_mean=0.050,
                            motion_peak=0.200,
                            active_motion_ratio=0.90,
                        )
                    ),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = [
        ClipRow(filename="neutral-a.mp4", clip_id="clip-001", gt=p0),
        ClipRow(filename="neutral-b.mp4", clip_id="clip-002", gt="moving"),
    ]

    monkeypatch.setattr("scripts.local_router_v0.load_manifest", lambda *_: rows)
    monkeypatch.setattr("scripts.local_router_v0.select_rows", lambda manifest_rows, *_: manifest_rows)
    monkeypatch.setattr("scripts.local_router_v0.sample_id_for", lambda row, index: f"sample-{index:03d}")
    monkeypatch.setattr(
        "scripts.local_router_v0.extract_video_evidence",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not extract videos")),
    )

    results = run(
        type(
            "Args",
            (),
            {
                "manifest": str(tmp_path / "manifest.csv"),
                "experiment_dir": str(experiment_dir),
                "sample_size": 2,
                "seed": 20260709,
                "frame_samples": 16,
                "summarize_only": True,
                "run_ollama": False,
                "ollama_model": "",
                "ollama_limit": 30,
                "ollama_timeout_sec": 30,
            },
        )()
    )

    separability_path = experiment_dir / "separability.json"
    results_path = experiment_dir / "results.json"
    assert separability_path.exists()
    assert results_path.exists()
    assert "separability" in results
    assert results["separability"]["motion_mean"]["very_low"]["p0_rate"] == 1.0
    assert '"separability"' in results_path.read_text(encoding="utf-8")


def test_run_summarize_only_reuses_existing_l1_decisions_with_completed_status(tmp_path, monkeypatch) -> None:
    experiment_dir = tmp_path / "experiment"
    feature_path = experiment_dir / "features.jsonl"
    l1_path = experiment_dir / "l1-decisions.jsonl"
    feature_path.parent.mkdir(parents=True, exist_ok=True)
    feature_path.write_text(
        json.dumps(asdict(_evidence(sample_id="sample-001", clip_id="clip-001")), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    l1_path.write_text(
        json.dumps(
            {
                "sample_id": "sample-001",
                "clip_id": "clip-001",
                "route": "cloud_later",
                "priority": 0.4,
                "risk": "medium",
                "reason": "existing",
                "router": "ollama:qwen2.5:14b",
                "latency_ms": 12.3,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    rows = [ClipRow(filename="neutral-a.mp4", clip_id="clip-001", gt="moving")]

    monkeypatch.setattr("scripts.local_router_v0.load_manifest", lambda *_: rows)
    monkeypatch.setattr("scripts.local_router_v0.select_rows", lambda manifest_rows, *_: manifest_rows)
    monkeypatch.setattr("scripts.local_router_v0.sample_id_for", lambda row, index: f"sample-{index:03d}")
    monkeypatch.setattr(
        "scripts.local_router_v0.extract_video_evidence",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not extract videos")),
    )
    monkeypatch.setattr(
        "scripts.local_router_v0.available_ollama_models",
        lambda: (_ for _ in ()).throw(AssertionError("should not probe ollama when summarize-only can reuse existing decisions")),
    )
    monkeypatch.setattr(
        "scripts.local_router_v0.route_with_ollama",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not rerun ollama")),
    )

    results = run(
        type(
            "Args",
            (),
            {
                "manifest": str(tmp_path / "manifest.csv"),
                "experiment_dir": str(experiment_dir),
                "sample_size": 1,
                "seed": 20260709,
                "frame_samples": 16,
                "summarize_only": True,
                "run_ollama": True,
                "ollama_model": "qwen2.5:14b",
                "ollama_limit": 30,
                "ollama_timeout_sec": 90,
                "l0_policy": "v1",
                "prompt_mode": "v1",
            },
        )()
    )

    report = (experiment_dir / "REPORT.md").read_text(encoding="utf-8")

    assert results["l1_status"] == "completed"
    assert results["summary_source"] == "existing_l1_decisions_jsonl"
    assert "summary source" in report.lower()
    assert "existing_l1_decisions_jsonl" in report
