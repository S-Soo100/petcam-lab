import csv
import json

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


def _task4_inventory_argv() -> list[str]:
    return [
        "inventory",
        "--output",
        "/tmp/v22",
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
        "220",
        "--probe-hard-negative-sources",
        "100",
        "--probe-max-frames-per-night",
        "24",
    ]


def _task4_analyze_argv() -> list[str]:
    return [
        "analyze",
        "--output",
        "/tmp/v22",
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
    assert analyze_args.probe_frames_per_source == 24


def test_main_accepts_approved_task4_inventory_contract_before_reads(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr(candidate_mining, "inventory", captured.append)
    monkeypatch.setattr(
        candidate_mining.sys, "argv", ["runner", *_task4_inventory_argv()]
    )

    candidate_mining.main()

    assert captured[0].probe_hard_positive_sources == 220
    assert captured[0].existing_review_csv.name == "v21-review.csv"


@pytest.mark.parametrize(
    ("argv", "replacement"),
    [
        (_task4_inventory_argv(), ("--probe-hard-positive-sources", "219")),
        (_task4_inventory_argv(), ("--probe-max-frames-per-night", "23")),
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


def test_inventory_probe_pool_uses_the_24_frame_camera_night_bound() -> None:
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

    assert sum(row["camera_night"] == "same-night" for row in selected) == 1
    assert {row["probe_bucket"] for row in selected} == {
        "hard_positive",
        "hard_negative",
    }


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
    manifest = build_candidate_manifest(
        seed="owner-v2.2",
        model_name="best.pt",
        checkpoint_sha256="c" * 64,
        analyzed_ledger_sha256="l" * 64,
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
