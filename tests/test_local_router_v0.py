import json
from dataclasses import asdict

from scripts.local_router_v0 import (
    P0_CLASSES,
    analyze_separability,
    run,
    route_l0,
    route_l0_v1,
    select_smoke_evidences,
    summarize,
)
from scripts.rba_evidence_first_cascade import ClipRow, VideoEvidence


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
