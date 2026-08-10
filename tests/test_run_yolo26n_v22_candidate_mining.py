from scripts.run_yolo26n_v22_candidate_mining import (
    ACTIVE_EXCLUSION_STATES,
    build_candidate_manifest,
    choose_probe_indices,
    choose_review_probe_indices,
    eligible_clips,
    materialize_review_rows,
    reserve_review_image,
    review_frame_is_duplicate,
)


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
    assert manifest["frames"][0] == {
        "frame_index": 42,
        "image_sha256": "i" * 64,
        "camera_id": "camera-a",
        "strata_tags": ["multi_gecko"],
    }
