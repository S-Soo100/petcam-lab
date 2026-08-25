import csv
import json
import sys
import types
from collections import Counter

import pytest

import scripts.run_yolo26n_v22_candidate_mining as candidate_mining

from scripts.run_yolo26n_v22_candidate_mining import (
    ACTIVE_EXCLUSION_STATES,
    build_candidate_manifest,
    build_parser,
    choose_probe_indices,
    choose_review_probe_indices,
    eligible_clips,
    load_inventory_existing_source_refs,
    materialize_review_rows,
    _select_inventory_sources,
    reserve_review_image,
    review_frame_is_duplicate,
    validate_cli_contract,
    validate_existing_review_csv,
)


APPROVED_OUTPUT = (
    "/Users/baek-end/private-rba/yolo26n-v22-candidates/"
    "attempt-20260811-owner-v3"
)


def _task4_inventory_argv() -> list[str]:
    return [
        "inventory",
        "--output",
        APPROVED_OUTPUT,
        "--reporter-repo",
        "/tmp/reporter",
        "--seed",
        "owner-v2.2",
        "--cutoff",
        "2026-07-15T00:00:00Z",
        "--existing-selection",
        "/tmp/v21-selection.json",
        "--existing-review-csv",
        "/tmp/v21-review.csv",
        "--probe-hard-positive-sources",
        "560",
        "--probe-hard-negative-sources",
        "530",
        "--inventory-max-sources",
        "1090",
        "--probe-max-sources-per-night",
        "28",
    ]


def _task4_analyze_argv() -> list[str]:
    return [
        "analyze",
        "--output",
        APPROVED_OUTPUT,
        "--existing-images",
        "/tmp/v21-images",
        "--model",
        "/tmp/v21-best.pt",
        "--seed",
        "owner-v2.2",
        "--imgsz",
        "960",
        "--inference-conf",
        "0.05",
        "--probe-frames-per-source",
        "24",
        "--review-frames-per-source",
        "2",
        "--hard-positive-frames",
        "220",
        "--hard-negative-frames",
        "100",
        "--max-frames-per-night",
        "12",
    ]


def test_task4_approved_inventory_and_analyze_cli_contracts_parse() -> None:
    parser = build_parser()

    inventory_args = parser.parse_args(_task4_inventory_argv())
    analyze_args = parser.parse_args(_task4_analyze_argv())

    validate_cli_contract(inventory_args)
    validate_cli_contract(analyze_args)
    assert inventory_args.existing_selection.name == "v21-selection.json"
    assert inventory_args.inventory_max_sources == 1090
    assert inventory_args.probe_max_sources_per_night == 28
    assert analyze_args.probe_frames_per_source == 24


def test_main_accepts_approved_task4_inventory_contract_before_reads(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(candidate_mining, "inventory", captured.append)
    monkeypatch.setattr(
        candidate_mining.sys, "argv", ["runner", *_task4_inventory_argv()]
    )

    candidate_mining.main()

    assert captured[0].probe_hard_positive_sources == 560
    assert captured[0].probe_hard_negative_sources == 530
    assert captured[0].existing_review_csv.name == "v21-review.csv"


@pytest.mark.parametrize(
    ("argv", "replacement"),
    [
        (_task4_inventory_argv(), ("--probe-hard-positive-sources", "220")),
        (_task4_inventory_argv(), ("--probe-hard-positive-sources", "559")),
        (_task4_inventory_argv(), ("--probe-hard-negative-sources", "100")),
        (_task4_inventory_argv(), ("--probe-hard-negative-sources", "529")),
        (_task4_inventory_argv(), ("--inventory-max-sources", "320")),
        (_task4_inventory_argv(), ("--inventory-max-sources", "1089")),
        (_task4_inventory_argv(), ("--probe-max-sources-per-night", "8")),
        (_task4_inventory_argv(), ("--probe-max-sources-per-night", "27")),
        (
            _task4_inventory_argv(),
            (
                "--output",
                "/Users/baek-end/private-rba/yolo26n-v22-candidates/"
                "attempt-20260810-owner-v1",
            ),
        ),
        (
            _task4_inventory_argv(),
            (
                "--output",
                "/Users/baek-end/private-rba/yolo26n-v22-candidates/"
                "attempt-20260810-owner-v2",
            ),
        ),
        (_task4_analyze_argv(), ("--output", "/tmp/v22")),
        (
            _task4_analyze_argv(),
            (
                "--output",
                "/Users/baek-end/private-rba/yolo26n-v22-candidates/"
                "other/../attempt-20260811-owner-v3",
            ),
        ),
        (_task4_inventory_argv(), ("--seed", "other-seed")),
        (_task4_inventory_argv(), ("--cutoff", "2026-07-15T00:00:01Z")),
        (_task4_inventory_argv(), ("--cutoff", "2026-07-15T00:00:00")),
        (_task4_analyze_argv(), ("--probe-frames-per-source", "23")),
        (_task4_analyze_argv(), ("--review-frames-per-source", "3")),
        (_task4_analyze_argv(), ("--hard-negative-frames", "99")),
        (_task4_analyze_argv(), ("--max-frames-per-night", "13")),
        (_task4_analyze_argv(), ("--seed", "other-seed")),
        (_task4_analyze_argv(), ("--imgsz", "640")),
        (_task4_analyze_argv(), ("--inference-conf", "0.001")),
    ],
)
def test_task4_cli_contract_rejects_unsafe_values(
    argv: list[str], replacement: tuple[str, str]
) -> None:
    flag, value = replacement
    changed = list(argv)
    changed[changed.index(flag) + 1] = value

    with pytest.raises(ValueError):
        validate_cli_contract(build_parser().parse_args(changed))


def test_cli_contract_allows_equivalent_utc_cutoff_spelling() -> None:
    argv = _task4_inventory_argv()
    argv[argv.index("--cutoff") + 1] = "2026-07-15T00:00:00+00:00"

    validate_cli_contract(build_parser().parse_args(argv))


@pytest.mark.parametrize("argv", [_task4_inventory_argv(), _task4_analyze_argv()])
def test_main_rejects_non_v3_output_before_dispatch(monkeypatch, argv) -> None:
    changed = list(argv)
    changed[changed.index("--output") + 1] = "/tmp/not-approved"
    dispatched = []
    monkeypatch.setattr(candidate_mining, "inventory", dispatched.append)
    monkeypatch.setattr(candidate_mining, "analyze", dispatched.append)
    monkeypatch.setattr(candidate_mining.sys, "argv", ["runner", *changed])

    with pytest.raises(SystemExit):
        candidate_mining.main()

    assert dispatched == []


def test_fresh_output_preflight_rejects_stale_phase_artifacts(tmp_path) -> None:
    inventory_output = tmp_path / "inventory-attempt"
    inventory_output.mkdir()
    (inventory_output / "code").mkdir()

    candidate_mining.validate_fresh_output(inventory_output, phase="inventory")
    (inventory_output / "review-index.csv").write_text("stale", encoding="utf-8")
    with pytest.raises(ValueError, match="fresh output"):
        candidate_mining.validate_fresh_output(inventory_output, phase="inventory")

    analyze_output = tmp_path / "analyze-attempt"
    analyze_output.mkdir()
    (analyze_output / "code").mkdir()
    (analyze_output / "source-clips").mkdir()
    (analyze_output / "inventory-selection.private.json").write_text(
        "{}", encoding="utf-8"
    )
    (analyze_output / "probe-sources.private.json").write_text(
        "{}", encoding="utf-8"
    )

    candidate_mining.validate_fresh_output(analyze_output, phase="analyze")
    (analyze_output / "review-frames").mkdir()
    with pytest.raises(ValueError, match="fresh output"):
        candidate_mining.validate_fresh_output(analyze_output, phase="analyze")


def test_existing_selection_requires_at_least_one_source_ref(tmp_path) -> None:
    populated = tmp_path / "candidate-manifest.private.json"
    populated.write_text(
        '{"frames":[{"source_ref":"  source-a  "}]}', encoding="utf-8"
    )
    empty = tmp_path / "empty.json"
    empty.write_text('{"frames":[]}', encoding="utf-8")

    assert load_inventory_existing_source_refs([populated]) == {"source-a"}
    with pytest.raises(ValueError, match="source_ref"):
        load_inventory_existing_source_refs([empty])
    with pytest.raises(ValueError, match="source_ref"):
        load_inventory_existing_source_refs([populated, empty])


@pytest.mark.parametrize("source_ref", ["", "   "])
def test_existing_selection_rejects_empty_or_whitespace_source_ref(
    tmp_path, source_ref: str
) -> None:
    selection = tmp_path / "candidate-manifest.private.json"
    selection.write_text(
        json.dumps({"frames": [{"source_ref": source_ref}]}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="no source_ref"):
        load_inventory_existing_source_refs([selection])


@pytest.mark.parametrize("source_ref", [None, 7, True, [], ["source-a"], {}])
def test_existing_selection_rejects_non_string_source_ref(
    tmp_path, source_ref: object
) -> None:
    selection = tmp_path / "candidate-manifest.private.json"
    selection.write_text(
        json.dumps({"frames": [{"source_ref": source_ref}]}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="source_ref must be a string"):
        load_inventory_existing_source_refs([selection])


def test_existing_review_csv_validates_blind_artifact_without_source_refs(tmp_path) -> None:
    review_csv = tmp_path / "combined-review.private.csv"
    with review_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["sequence", "camera_night_group"]
        )
        writer.writeheader()
        writer.writerows(
            [
                {"sequence": "V0002", "camera_night_group": "night-b"},
                {"sequence": "V0001", "camera_night_group": "night-a"},
            ]
        )

    validate_existing_review_csv(review_csv)


@pytest.mark.parametrize(
    "contents",
    [
        "sequence,filename\nV0001,V0001.jpg\n",
        "sequence,camera_night_group\n",
        "sequence,camera_night_group\nV0001,night-a\nV0001,night-b\n",
    ],
)
def test_existing_review_csv_rejects_nonblind_or_malformed_artifacts(
    tmp_path, contents: str
) -> None:
    review_csv = tmp_path / "invalid.csv"
    review_csv.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match="review CSV"):
        validate_existing_review_csv(review_csv)


def test_inventory_rejects_the_retired_frame_based_night_cap() -> None:
    argv = [
        value
        for value in _task4_inventory_argv()
        if value not in {"--probe-max-sources-per-night", "28"}
    ]

    with pytest.raises(SystemExit):
        build_parser().parse_args([*argv, "--probe-max-frames-per-night", "24"])


def test_inventory_probe_pool_caps_sources_per_camera_night() -> None:
    args = build_parser().parse_args(_task4_inventory_argv())
    sources = [
        {
            "source_ref": "positive-a",
            "camera_night": "same-night",
            "gme_max_geckos": 1,
        },
        {
            "source_ref": "positive-b",
            "camera_night": "same-night",
            "gme_max_geckos": 1,
        },
        {
            "source_ref": "negative-a",
            "camera_night": "other-night",
            "gme_max_geckos": 0,
        },
    ]

    selected = _select_inventory_sources(sources, args=args)

    assert sum(row["camera_night"] == "same-night" for row in selected) == 2
    assert {row["probe_bucket"] for row in selected} == {
        "hard_positive",
        "hard_negative",
    }


def test_inventory_balances_overlapping_nights_to_exact_bucket_quotas() -> None:
    args = build_parser().parse_args(_task4_inventory_argv())
    sources = [
        {
            "source_ref": f"positive-{index:03d}",
            "camera_night": f"shared-night-{index % 40:03d}",
            "gme_max_geckos": 1,
        }
        for index in range(560)
    ] + [
        {
            "source_ref": f"negative-{index:03d}",
            "camera_night": f"shared-night-{(index % 40 + 20) % 40:03d}",
            "gme_max_geckos": 0,
        }
        for index in range(530)
    ]

    selected = _select_inventory_sources(sources, args=args)
    selected_reversed = _select_inventory_sources(reversed(sources), args=args)

    assert [row["source_ref"] for row in selected] == [
        row["source_ref"] for row in selected_reversed
    ]
    assert len(selected) == 1090
    assert sum(row["probe_bucket"] == "hard_positive" for row in selected) == 560
    assert sum(row["probe_bucket"] == "hard_negative" for row in selected) == 530
    assert max(
        sum(row["camera_night"] == night for row in selected)
        for night in {str(row["camera_night"]) for row in selected}
    ) <= 28

    summary = candidate_mining.build_inventory_selection_summary(
        sources, selected, args=args
    )
    assert summary == {
        "status": "V22_INVENTORY_SELECTION_READY",
        "inventory_pool_counts": {"hard_positive": 560, "hard_negative": 530},
        "inventory_selection_counts": {
            "hard_positive": 560,
            "hard_negative": 530,
        },
        "inventory_selection_shortfalls": {
            "hard_positive": 0,
            "hard_negative": 0,
        },
        "inventory_selected_source_count": 1090,
        "probe_max_sources_per_night": 28,
    }
    assert "positive-000" not in json.dumps(summary)


def test_inventory_reserves_shared_night_capacity_for_dependent_bucket() -> None:
    args = build_parser().parse_args(_task4_inventory_argv())
    sources = [
        {
            "source_ref": f"hp-exclusive-{index:04d}",
            "camera_night": f"z-exclusive-night-{index % 20:02d}",
            "gme_max_geckos": 1,
        }
        for index in range(560)
    ] + [
        {
            "source_ref": f"hp-shared-{index:04d}",
            "camera_night": f"a-shared-night-{index % 19:02d}",
            "gme_max_geckos": 1,
        }
        for index in range(440)
    ] + [
        {
            "source_ref": f"hn-shared-{index:04d}",
            "camera_night": f"a-shared-night-{index % 19:02d}",
            "gme_max_geckos": 0,
        }
        for index in range(532)
    ]

    selected = _select_inventory_sources(sources, args=args)
    selected_reversed = _select_inventory_sources(reversed(sources), args=args)

    assert [row["source_ref"] for row in selected] == [
        row["source_ref"] for row in selected_reversed
    ]
    assert len(selected) == 1090
    assert sum(row["probe_bucket"] == "hard_positive" for row in selected) == 560
    assert sum(row["probe_bucket"] == "hard_negative" for row in selected) == 530
    assert max(Counter(row["camera_night"] for row in selected).values()) <= 28


def test_inventory_reports_exact_bucket_shortage_for_maximal_infeasible_flow() -> None:
    args = build_parser().parse_args(_task4_inventory_argv())
    sources = [
        {
            "source_ref": f"hp-exclusive-{index:04d}",
            "camera_night": f"z-exclusive-night-{index % 20:02d}",
            "gme_max_geckos": 1,
        }
        for index in range(560)
    ] + [
        {
            "source_ref": f"hp-shared-{index:04d}",
            "camera_night": f"a-shared-night-{index % 18:02d}",
            "gme_max_geckos": 1,
        }
        for index in range(440)
    ] + [
        {
            "source_ref": f"hn-constrained-{index:04d}",
            "camera_night": f"a-shared-night-{index % 18:02d}",
            "gme_max_geckos": 0,
        }
        for index in range(530)
    ]

    selected = _select_inventory_sources(sources, args=args)
    selected_reversed = _select_inventory_sources(reversed(sources), args=args)
    summary = candidate_mining.build_inventory_selection_summary(
        sources, selected, args=args
    )

    assert [row["source_ref"] for row in selected] == [
        row["source_ref"] for row in selected_reversed
    ]
    assert len(selected) == 1064
    assert max(Counter(row["camera_night"] for row in selected).values()) <= 28
    assert summary["status"] == "V22_INVENTORY_SELECTION_SHORTAGE"
    assert summary["inventory_selection_counts"] == {
        "hard_positive": 560,
        "hard_negative": 504,
    }
    assert summary["inventory_selection_shortfalls"] == {
        "hard_positive": 0,
        "hard_negative": 26,
    }


def test_inventory_uses_seed_rank_to_choose_between_equal_maximum_flows() -> None:
    args = types.SimpleNamespace(
        probe_hard_positive_sources=1,
        probe_hard_negative_sources=0,
        probe_max_sources_per_night=1,
        inventory_max_sources=1,
        seed="owner-v2.2",
    )
    sources = [
        {
            "source_ref": "preferred-source",
            "camera_night": "z-night",
            "gme_max_geckos": 1,
        },
        {
            "source_ref": "other-source",
            "camera_night": "a-night",
            "gme_max_geckos": 1,
        },
    ]

    selected = _select_inventory_sources(sources, args=args)

    assert [row["source_ref"] for row in selected] == ["preferred-source"]


def test_review_source_pool_keeps_same_bucket_reserves_after_initial_quota() -> None:
    analyzed = [
        {
            "source_ref": f"positive-{index:03d}",
            "camera_night": f"positive-night-{index:03d}",
            "camera_id": "camera-a",
            "gme_max_geckos": 1,
            "yolo_detection_count": 0,
        }
        for index in range(111)
    ] + [
        {
            "source_ref": f"negative-{index:03d}",
            "camera_night": f"negative-night-{index:03d}",
            "camera_id": "camera-a",
            "gme_max_geckos": 0,
            "gme_visible_ratio": 0.0,
            "yolo_detection_count": 1,
            "yolo_max_conf": 0.9,
        }
        for index in range(51)
    ]
    policy = candidate_mining.V22CandidatePolicy(
        frame_quotas={"hard_positive": 220, "hard_negative": 100},
        frames_per_source=2,
        max_frames_per_camera_night=12,
        seed="owner-v2.2",
    )

    selected = candidate_mining.select_review_source_pool(analyzed, policy=policy)

    assert len(selected) == 162
    assert sum(row["candidate_bucket"] == "hard_positive" for row in selected) == 111
    assert sum(row["candidate_bucket"] == "hard_negative" for row in selected) == 51
    assert selected == candidate_mining.select_review_source_pool(
        reversed(analyzed), policy=policy
    )


def test_inventory_shortage_stops_before_any_r2_get(monkeypatch, tmp_path) -> None:
    class FakeQuery:
        def __init__(self, rows):
            self.rows = rows

        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: self

        @property
        def not_(self):
            return self

        def execute(self):
            return types.SimpleNamespace(data=self.rows)

    rows_by_table = {
        "motion_clips": [
            {
                "id": "source-a",
                "camera_id": "camera-a",
                "started_at": "2026-07-16T00:00:00Z",
                "duration_sec": 60,
                "r2_key": "clips/source-a.mp4",
                "clip_purpose": "production",
            }
        ],
        "motion_clip_system_exclusions": [],
        "gme_runs": [
            {
                "clip_id": "source-a",
                "created_at": "2026-07-16T01:00:00Z",
                "duration_sec": 60,
                "visible_sec": 30,
                "unknown_sec": 0,
                "max_simultaneous_geckos": 1,
                "status": "ok",
            }
        ],
    }
    fake_client = types.SimpleNamespace(
        table=lambda name: FakeQuery(rows_by_table[name])
    )
    supabase_module = types.ModuleType("supabase")
    supabase_module.create_client = lambda *_args: fake_client
    downloads = []
    r2_module = types.SimpleNamespace(
        R2SourceMissing=type("R2SourceMissing", (Exception,), {}),
        download_clip=lambda *args: downloads.append(args),
    )
    reporter_module = types.ModuleType("reporter")
    reporter_module.config = types.SimpleNamespace(
        SUPABASE_URL="https://example.invalid", SUPABASE_KEY="fake"
    )
    reporter_module.r2 = r2_module
    monkeypatch.setitem(sys.modules, "supabase", supabase_module)
    monkeypatch.setitem(sys.modules, "reporter", reporter_module)

    existing_selection = tmp_path / "existing.json"
    existing_selection.write_text(
        '{"frames":[{"source_ref":"old-source"}]}', encoding="utf-8"
    )
    existing_review = tmp_path / "existing-review.csv"
    existing_review.write_text(
        "sequence,camera_night_group\nV0001,night-a\n", encoding="utf-8"
    )
    args = build_parser().parse_args(
        [
            *_task4_inventory_argv(),
            "--output",
            str(tmp_path / "attempt"),
            "--reporter-repo",
            str(tmp_path / "reporter"),
            "--existing-selection",
            str(existing_selection),
            "--existing-review-csv",
            str(existing_review),
        ]
    )
    monkeypatch.setattr(
        candidate_mining, "APPROVED_OUTPUT_DIR", (tmp_path / "attempt").resolve()
    )

    with pytest.raises(SystemExit, match="V22_INVENTORY_SELECTION_SHORTAGE"):
        candidate_mining.inventory(args)

    assert downloads == []
    summary = json.loads(
        (tmp_path / "attempt" / "inventory-selection.private.json").read_text()
    )
    assert summary["status"] == "V22_INVENTORY_SELECTION_SHORTAGE"
    assert summary["inventory_selection_counts"] == {
        "hard_positive": 1,
        "hard_negative": 0,
    }


def test_inventory_download_summary_preserves_bucket_missing_counts_without_ids() -> None:
    selected = [
        {"source_ref": "hp-a", "probe_bucket": "hard_positive"},
        {"source_ref": "hp-b", "probe_bucket": "hard_positive"},
        {"source_ref": "hn-a", "probe_bucket": "hard_negative"},
    ]
    downloaded = [selected[0], selected[2]]

    summary = candidate_mining.build_inventory_download_summary(
        selected, downloaded
    )

    assert summary == {
        "downloaded_source_count": 2,
        "missing_source_count": 1,
        "downloaded_bucket_counts": {"hard_positive": 1, "hard_negative": 1},
        "missing_bucket_counts": {"hard_positive": 1, "hard_negative": 0},
    }
    assert "hp-a" not in json.dumps(summary)


def test_eligible_clips_excludes_nonproduction_and_active_system_exclusions() -> None:
    clips = [
        {"id": "a", "clip_purpose": "production", "r2_key": "terra-clips/clips/a.mp4"},
        {"id": "b", "clip_purpose": "test", "r2_key": "test/b.mp4"},
        {"id": "c", "clip_purpose": "production", "r2_key": "terra-clips/clips/c.mp4"},
    ]
    exclusions = {"c": "quarantined"}

    assert [row["id"] for row in eligible_clips(clips, exclusions)] == ["a"]


def test_eligible_clips_fail_closed_for_active_states_but_allows_restored() -> None:
    clips = [
        {"id": state, "clip_purpose": "production", "r2_key": f"clips/{state}.mp4"}
        for state in (*sorted(ACTIVE_EXCLUSION_STATES), "restored")
    ]
    exclusions = {state: state for state in ACTIVE_EXCLUSION_STATES}
    exclusions["restored"] = "restored"

    assert [row["id"] for row in eligible_clips(clips, exclusions)] == ["restored"]


def test_eligible_clips_excludes_test_prefix_even_for_production_purpose() -> None:
    clips = [
        {"id": "test-key", "clip_purpose": "production", "r2_key": "test/a.mp4"},
        {"id": "allowed", "clip_purpose": "production", "r2_key": "clips/a.mp4"},
    ]

    assert [row["id"] for row in eligible_clips(clips, {})] == ["allowed"]


def test_choose_probe_indices_spreads_24_samples_without_endpoints_deterministically() -> None:
    first = choose_probe_indices(total_frames=240, count=24)

    assert first == choose_probe_indices(total_frames=240, count=24)
    assert len(first) == 24
    assert first[0] > 0
    assert first[-1] < 239
    assert first == sorted(first)
    assert first[0] == 24
    assert first[-1] == 215


def test_choose_probe_indices_always_returns_24_unique_indices_for_small_valid_videos() -> None:
    for total_frames in range(24, 30):
        indices = choose_probe_indices(total_frames=total_frames, count=24)

        assert len(indices) == 24
        assert len(set(indices)) == 24
        assert indices == sorted(indices)
        assert all(0 <= index < total_frames for index in indices)


def test_extract_probes_counts_decode_and_imwrite_failures_without_dropping_provenance(
    tmp_path,
) -> None:
    class FakeCapture:
        def __init__(self):
            self.reads = iter(((False, None), (True, "frame-a"), (True, "frame-b")))

        def get(self, _property):
            return 30

        def set(self, _property, _value):
            return True

        def read(self):
            return next(self.reads)

    writes = iter((False, True))
    fake_cv2 = types.SimpleNamespace(
        CAP_PROP_FRAME_COUNT=1,
        CAP_PROP_POS_FRAMES=2,
        IMWRITE_JPEG_QUALITY=3,
        imwrite=lambda *_args: next(writes),
    )

    frames, rows, counts = candidate_mining._extract_probes(
        FakeCapture(),
        cv2=fake_cv2,
        source_ordinal=1,
        probe_dir=tmp_path,
        count=3,
    )

    assert frames == ["frame-b"]
    assert [row["probe_index"] for row in rows] == [2]
    assert counts == {
        "requested": 3,
        "readable": 2,
        "decode_failed": 1,
        "imwrite_failed": 1,
    }


def test_probe_extraction_counts_aggregate_by_bucket_without_identifiers() -> None:
    sources = [
        {
            "source_ref": "secret-source-a",
            "r2_key": "secret/key-a.mp4",
            "probe_bucket": "hard_positive",
            "probe_extraction": {
                "requested": 24,
                "readable": 23,
                "decode_failed": 1,
                "imwrite_failed": 1,
            },
        },
        {
            "source_ref": "secret-source-b",
            "r2_key": "secret/key-b.mp4",
            "probe_bucket": "hard_positive",
            "probe_extraction": {
                "requested": 24,
                "readable": 21,
                "decode_failed": 3,
                "imwrite_failed": 1,
            },
        },
        {
            "source_ref": "secret-source-c",
            "r2_key": "secret/key-c.mp4",
            "probe_bucket": "hard_negative",
            "probe_extraction": {
                "requested": 24,
                "readable": 24,
                "decode_failed": 0,
                "imwrite_failed": 0,
            },
        },
    ]

    counts = candidate_mining.aggregate_probe_extraction_counts(sources)

    assert counts == {
        "hard_positive": {
            "requested": 48,
            "readable": 44,
            "decode_failed": 4,
            "imwrite_failed": 2,
        },
        "hard_negative": {
            "requested": 24,
            "readable": 24,
            "decode_failed": 0,
            "imwrite_failed": 0,
        },
    }
    assert "secret-source" not in json.dumps(counts)
    assert "secret/key" not in json.dumps(counts)


def test_analyze_preserves_extraction_failures_in_private_ledgers_and_safe_aggregates(
    monkeypatch, tmp_path
) -> None:
    output = tmp_path / "attempt"
    output.mkdir()
    (output / "source-clips").mkdir()
    (output / "source-clips" / "S0001.mp4").write_bytes(b"fake-video")
    inventory_payload = {
        "status": "V22_INVENTORY_SELECTION_READY",
        "inventory_pool_counts": {"hard_positive": 1, "hard_negative": 0},
        "inventory_selection_counts": {"hard_positive": 1, "hard_negative": 0},
        "inventory_selection_shortfalls": {"hard_positive": 219, "hard_negative": 100},
        "downloaded_source_count": 1,
        "missing_source_count": 0,
        "downloaded_bucket_counts": {"hard_positive": 1, "hard_negative": 0},
        "missing_bucket_counts": {"hard_positive": 0, "hard_negative": 0},
        "sources": [
            {
                "source_ref": "private-source-a",
                "camera_id": "private-camera-a",
                "camera_night": "private-night-a",
                "probe_bucket": "hard_positive",
                "local_name": "S0001.mp4",
                "gme_max_geckos": 1,
                "gme_visible_ratio": 0.5,
                "gme_unknown_ratio": 0.0,
            }
        ],
    }
    (output / "inventory-selection.private.json").write_text(
        "{}", encoding="utf-8"
    )
    (output / "probe-sources.private.json").write_text(
        json.dumps(inventory_payload), encoding="utf-8"
    )
    existing_images = tmp_path / "existing-images"
    existing_images.mkdir()
    model_path = tmp_path / "best.pt"
    model_path.write_bytes(b"checkpoint")

    class FakeCapture:
        def __init__(self, _path):
            self.reads = iter(((False, None), (True, "frame-a"), (True, "frame-b")))

        def get(self, _property):
            return 3

        def set(self, _property, _value):
            return True

        def read(self):
            return next(self.reads)

        def release(self):
            return None

    writes = iter((False, False))

    def fake_imwrite(path, _frame, _params):
        written = next(writes)
        if written:
            candidate_mining.Path(path).write_bytes(b"probe-image")
        return written

    cv2_module = types.ModuleType("cv2")
    cv2_module.CAP_PROP_FRAME_COUNT = 1
    cv2_module.CAP_PROP_POS_FRAMES = 2
    cv2_module.IMWRITE_JPEG_QUALITY = 3
    cv2_module.VideoCapture = FakeCapture
    cv2_module.imwrite = fake_imwrite
    cv2_module.imread = lambda _path: object()

    class FakeModel:
        def __init__(self, _path):
            pass

        def predict(self, *, source, **_kwargs):
            raise AssertionError(f"YOLO must not receive an empty source: {source}")

    ultralytics_module = types.ModuleType("ultralytics")
    ultralytics_module.YOLO = FakeModel
    monkeypatch.setitem(sys.modules, "cv2", cv2_module)
    monkeypatch.setitem(sys.modules, "ultralytics", ultralytics_module)
    monkeypatch.setattr(candidate_mining, "_dhash", lambda _image, _cv2: 7)
    monkeypatch.setattr(candidate_mining, "APPROVED_OUTPUT_DIR", output.resolve())
    args = build_parser().parse_args(
        [
            *_task4_analyze_argv(),
            "--output",
            str(output),
            "--existing-images",
            str(existing_images),
            "--model",
            str(model_path),
        ]
    )

    candidate_mining.analyze(args)

    analyzed = json.loads(
        (output / "analyzed-sources.private.json").read_text(encoding="utf-8")
    )
    assert analyzed["sources"][0]["probe_extraction"] == {
        "requested": 3,
        "readable": 2,
        "decode_failed": 1,
        "imwrite_failed": 2,
    }
    manifest = json.loads(
        (output / "candidate-manifest.private.json").read_text(encoding="utf-8")
    )
    assert manifest["materialization_counts"]["hard_positive"]["decode_failed"] == 1
    assert manifest["materialization_counts"]["hard_positive"]["imwrite_failed"] == 2
    assert manifest["materialization_counts"]["hard_positive"]["source_exhausted"] == 1
    assert manifest["materialization_counts"]["hard_positive"]["candidate_exhausted"] == 220
    review_csv = (output / "review-index.csv").read_text(encoding="utf-8")
    assert "private-source-a" not in review_csv
    assert "private-camera-a" not in review_csv


def test_review_frame_ranking_prefers_missed_or_low_confidence_positives_and_high_confidence_negatives() -> None:
    probes = [
        {"probe_index": 0, "max_conf": 0.75, "detection_count": 1},
        {"probe_index": 1, "max_conf": 0.0, "detection_count": 0},
        {"probe_index": 2, "max_conf": 0.2, "detection_count": 1},
        {"probe_index": 3, "max_conf": 0.9, "detection_count": 1},
    ]

    assert choose_review_probe_indices(probes, "hard_positive", count=2) == [1, 2]
    assert choose_review_probe_indices(probes, "hard_negative", count=2) == [3, 0]


def test_materialization_rechecks_two_frame_source_and_twelve_frame_camera_night_caps() -> None:
    selected = [
        {
            "source_ref": f"source-{index}",
            "camera_night": "night-a",
            "camera_id": "camera-a",
            "candidate_bucket": "hard_positive",
            "strata_tags": ["yolo_missed_gme_visible"],
            "planned_frame_count": 3,
        }
        for index in range(7)
    ]
    probes_by_source = {
        f"source-{index}": [
            {"probe_index": probe, "max_conf": 0.0, "detection_count": 0}
            for probe in range(4)
        ]
        for index in range(7)
    }

    materialized = materialize_review_rows(selected, probes_by_source)

    assert len(materialized) == 12
    assert all(
        sum(row["source_ref"] == source["source_ref"] for row in materialized) <= 2
        for source in selected
    )
    assert sum(row["camera_night"] == "night-a" for row in materialized) == 12
    assert materialized[0]["camera_id"] == "camera-a"
    assert materialized[0]["strata_tags"] == ["yolo_missed_gme_visible"]


def test_accepted_materialization_backfills_rejected_probes_within_the_same_bucket() -> None:
    selected = [
        {
            "source_ref": source_ref,
            "camera_night": f"night-{source_ref}",
            "camera_id": "camera-a",
            "candidate_bucket": bucket,
            "strata_tags": [bucket],
            "planned_frame_count": 2,
        }
        for source_ref, bucket in (
            ("hp-a", "hard_positive"),
            ("hn-a", "hard_negative"),
            ("hp-b", "hard_positive"),
            ("hn-b", "hard_negative"),
        )
    ]
    probes_by_source = {
        "hp-a": [
            {"probe_index": index, "max_conf": confidence, "detection_count": 1}
            for index, confidence in enumerate((0.0, 0.1, 0.2, 0.3))
        ],
        "hp-b": [
            {"probe_index": index, "max_conf": confidence, "detection_count": 1}
            for index, confidence in enumerate((0.0, 0.1))
        ],
        "hn-a": [
            {"probe_index": index, "max_conf": confidence, "detection_count": 1}
            for index, confidence in enumerate((0.9, 0.8, 0.7))
        ],
        "hn-b": [
            {"probe_index": 0, "max_conf": 0.6, "detection_count": 1}
        ],
    }
    outcomes = {
        ("hp-a", 0): "exact_duplicate",
        ("hp-a", 1): "dhash_duplicate",
        ("hp-a", 2): "accepted",
        ("hp-a", 3): "unreadable",
        ("hp-b", 0): "accepted",
        ("hp-b", 1): "accepted",
        ("hn-a", 0): "unreadable",
        ("hn-a", 1): "accepted",
        ("hn-a", 2): "accepted",
    }

    frames, summary = candidate_mining.materialize_accepted_review_rows(
        selected,
        probes_by_source,
        inspect_probe=lambda source_ref, probe_index: (
            outcomes.get((source_ref, probe_index), "accepted"),
            {"frame_index": probe_index, "image_sha256": f"{source_ref}-{probe_index}"},
        ),
        frame_quotas={"hard_positive": 3, "hard_negative": 2},
        frames_per_source=2,
        max_frames_per_camera_night=12,
        probe_extraction_counts={
            "hard_positive": {
                "requested": 7,
                "readable": 6,
                "decode_failed": 1,
                "imwrite_failed": 1,
            },
            "hard_negative": {
                "requested": 4,
                "readable": 3,
                "decode_failed": 1,
                "imwrite_failed": 0,
            },
        },
    )

    assert [(row["source_ref"], row["probe_index"]) for row in frames] == [
        ("hp-a", 2),
        ("hn-a", 1),
        ("hp-b", 0),
        ("hn-a", 2),
        ("hp-b", 1),
    ]
    assert summary == {
        "hard_positive": {
            "planned": 3,
            "accepted": 3,
            "exact_duplicate": 1,
            "dhash_duplicate": 1,
            "deduplicated": 2,
            "unreadable": 1,
            "candidate_sources": 2,
            "candidate_exhausted": 0,
            "source_exhausted": 1,
            "night_cap_blocked": 0,
            "requested": 7,
            "readable": 6,
            "decode_failed": 1,
            "imwrite_failed": 1,
            "quota_shortfall": 0,
        },
        "hard_negative": {
            "planned": 2,
            "accepted": 2,
            "exact_duplicate": 0,
            "dhash_duplicate": 0,
            "deduplicated": 0,
            "unreadable": 1,
            "candidate_sources": 2,
            "candidate_exhausted": 0,
            "source_exhausted": 0,
            "night_cap_blocked": 0,
            "requested": 4,
            "readable": 3,
            "decode_failed": 1,
            "imwrite_failed": 0,
            "quota_shortfall": 0,
        },
    }


def test_accepted_materialization_never_backfills_across_buckets() -> None:
    selected = [
        {
            "source_ref": "hp-a",
            "camera_night": "night-a",
            "camera_id": "camera-a",
            "candidate_bucket": "hard_positive",
            "strata_tags": [],
        },
        {
            "source_ref": "hn-a",
            "camera_night": "night-b",
            "camera_id": "camera-a",
            "candidate_bucket": "hard_negative",
            "strata_tags": [],
        },
    ]
    probes = {
        "hp-a": [{"probe_index": 0, "max_conf": 0.0, "detection_count": 0}],
        "hn-a": [
            {"probe_index": index, "max_conf": 0.9 - index / 10, "detection_count": 1}
            for index in range(3)
        ],
    }

    frames, summary = candidate_mining.materialize_accepted_review_rows(
        selected,
        probes,
        inspect_probe=lambda source_ref, probe_index: (
            "accepted",
            {"frame_index": probe_index, "image_sha256": f"{source_ref}-{probe_index}"},
        ),
        frame_quotas={"hard_positive": 2, "hard_negative": 2},
        frames_per_source=2,
        max_frames_per_camera_night=12,
    )

    assert sum(row["candidate_bucket"] == "hard_positive" for row in frames) == 1
    assert sum(row["candidate_bucket"] == "hard_negative" for row in frames) == 2
    assert summary["hard_positive"]["quota_shortfall"] == 1
    assert summary["hard_negative"]["quota_shortfall"] == 0


def test_accepted_materialization_identifies_night_cap_as_the_shortage_reason() -> None:
    selected = [
        {
            "source_ref": f"hp-{index}",
            "camera_night": "same-night",
            "camera_id": "camera-a",
            "candidate_bucket": "hard_positive",
            "strata_tags": [],
        }
        for index in range(2)
    ]
    probes = {
        f"hp-{source}": [
            {"probe_index": probe, "max_conf": 0.0, "detection_count": 0}
            for probe in range(2)
        ]
        for source in range(2)
    }

    frames, summary = candidate_mining.materialize_accepted_review_rows(
        selected,
        probes,
        inspect_probe=lambda source_ref, probe_index: (
            "accepted",
            {"frame_index": probe_index, "image_sha256": f"{source_ref}-{probe_index}"},
        ),
        frame_quotas={"hard_positive": 4, "hard_negative": 0},
        frames_per_source=2,
        max_frames_per_camera_night=2,
    )

    assert len(frames) == 2
    assert summary["hard_positive"] == {
        "planned": 4,
        "accepted": 2,
        "exact_duplicate": 0,
        "dhash_duplicate": 0,
        "deduplicated": 0,
        "unreadable": 0,
        "candidate_sources": 2,
        "candidate_exhausted": 2,
        "source_exhausted": 0,
        "night_cap_blocked": 2,
        "requested": 0,
        "readable": 0,
        "decode_failed": 0,
        "imwrite_failed": 0,
        "quota_shortfall": 2,
    }


def test_review_duplicate_rule_excludes_existing_exact_sha_and_source_near_dhash() -> None:
    assert review_frame_is_duplicate(
        image_sha256="a" * 64,
        existing_image_sha256={"a" * 64},
        dhash=0b1011,
        source_dhashes=set(),
    ) is True
    assert review_frame_is_duplicate(
        image_sha256="b" * 64,
        existing_image_sha256={"a" * 64},
        dhash=0b1011,
        source_dhashes={0b1010},
    ) is True
    assert review_frame_is_duplicate(
        image_sha256="b" * 64,
        existing_image_sha256={"a" * 64},
        dhash=0b11110000,
        source_dhashes={0b1010},
    ) is False


def test_reserve_review_image_rejects_new_exact_sha_from_another_source() -> None:
    accepted_image_sha256 = {"a" * 64}

    assert reserve_review_image(
        image_sha256="b" * 64,
        accepted_image_sha256=accepted_image_sha256,
        dhash=0b1011,
        source_dhashes=set(),
    ) is True
    assert reserve_review_image(
        image_sha256="b" * 64,
        accepted_image_sha256=accepted_image_sha256,
        dhash=0b11110000,
        source_dhashes=set(),
    ) is False


def test_candidate_manifest_records_reviewer_blinding_and_zero_remote_writes() -> None:
    inventory_summary = {
        "inventory_pool_counts": {"hard_positive": 5564, "hard_negative": 3755},
        "inventory_selection_counts": {"hard_positive": 220, "hard_negative": 100},
        "inventory_selection_shortfalls": {"hard_positive": 0, "hard_negative": 0},
        "downloaded_source_count": 319,
        "missing_source_count": 1,
        "downloaded_bucket_counts": {"hard_positive": 219, "hard_negative": 100},
        "missing_bucket_counts": {"hard_positive": 1, "hard_negative": 0},
    }
    materialization_summary = {
        "hard_positive": {
            "planned": 220,
            "accepted": 0,
            "exact_duplicate": 2,
            "dhash_duplicate": 3,
            "deduplicated": 5,
            "unreadable": 1,
            "quota_shortfall": 220,
        },
        "hard_negative": {
            "planned": 100,
            "accepted": 0,
            "exact_duplicate": 0,
            "dhash_duplicate": 0,
            "deduplicated": 0,
            "unreadable": 4,
            "quota_shortfall": 100,
        },
    }
    manifest = build_candidate_manifest(
        seed="owner-v2.2",
        model_name="best.pt",
        checkpoint_sha256="c" * 64,
        analyzed_ledger_sha256="l" * 64,
        inventory_summary=inventory_summary,
        materialization_summary=materialization_summary,
        review_frames=[
            {
                "frame_index": 42,
                "image_sha256": "i" * 64,
                "camera_id": "camera-a",
                "strata_tags": ["multi_gecko"],
            }
        ],
    )

    assert manifest["prediction_boxes_exposed_to_reviewer"] is False
    assert manifest["db_write_count"] == 0
    assert manifest["r2_write_count"] == 0
    assert manifest["checkpoint_sha256"] == "c" * 64
    assert manifest["analyzed_ledger_sha256"] == "l" * 64
    assert manifest["status"] == "V22_CANDIDATE_QUEUE_SHORTAGE"
    assert manifest["bucket_counts"] == {"hard_positive": 0, "hard_negative": 0}
    assert manifest["source_cap_violation_count"] == 0
    assert manifest["camera_night_cap_violation_count"] == 0
    assert manifest["inventory_pool_counts"] == {
        "hard_positive": 5564,
        "hard_negative": 3755,
    }
    assert manifest["inventory_selection_counts"] == {
        "hard_positive": 220,
        "hard_negative": 100,
    }
    assert manifest["inventory_downloaded_source_count"] == 319
    assert manifest["inventory_missing_source_count"] == 1
    assert manifest["inventory_downloaded_counts"] == {
        "hard_positive": 219,
        "hard_negative": 100,
    }
    assert manifest["inventory_missing_counts"] == {
        "hard_positive": 1,
        "hard_negative": 0,
    }
    assert manifest["materialization_counts"] == materialization_summary
    assert manifest["frames"][0] == {
        "frame_index": 42,
        "image_sha256": "i" * 64,
        "camera_id": "camera-a",
        "strata_tags": ["multi_gecko"],
    }


def test_candidate_manifest_is_ready_only_for_exact_quotas_without_cap_violations() -> None:
    frames = []
    for bucket, source_count in (("hard_positive", 110), ("hard_negative", 50)):
        for source in range(source_count):
            for probe_index in range(2):
                frames.append(
                    {
                        "source_ref": f"{bucket}-source-{source}",
                        "camera_night": f"{bucket}-night-{source // 6}",
                        "candidate_bucket": bucket,
                        "probe_index": probe_index,
                    }
                )

    manifest = build_candidate_manifest(
        seed="owner-v2.2",
        model_name="best.pt",
        checkpoint_sha256="c" * 64,
        analyzed_ledger_sha256="l" * 64,
        review_frames=frames,
    )

    assert manifest["status"] == "V22_CANDIDATE_QUEUE_READY"
    assert manifest["bucket_counts"] == {"hard_positive": 220, "hard_negative": 100}
    assert manifest["camera_night_count"] == 28
    assert manifest["source_cap_violation_count"] == 0
    assert manifest["camera_night_cap_violation_count"] == 0
