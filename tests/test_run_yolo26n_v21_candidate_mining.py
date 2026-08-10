from scripts.run_yolo26n_v21_candidate_mining import (
    choose_probe_indices,
    choose_review_probe_indices,
    extract_source_refs,
    review_frame_is_duplicate,
)


def test_choose_probe_indices_spreads_samples_without_endpoints() -> None:
    assert choose_probe_indices(total_frames=120, count=4) == [12, 44, 75, 107]
    assert choose_probe_indices(total_frames=3, count=8) == [0, 1, 2]


def test_hard_negative_review_prefers_high_confidence_probe_frames() -> None:
    probes = [
        {"probe_index": 0, "max_conf": 0.1, "detection_count": 1},
        {"probe_index": 1, "max_conf": 0.8, "detection_count": 1},
        {"probe_index": 2, "max_conf": 0.6, "detection_count": 1},
        {"probe_index": 3, "max_conf": 0.0, "detection_count": 0},
    ]

    assert choose_review_probe_indices(probes, "hard_negative", count=2) == [1, 2]


def test_multi_gecko_review_prefers_more_detections_then_confidence() -> None:
    probes = [
        {"probe_index": 0, "max_conf": 0.9, "detection_count": 1},
        {"probe_index": 1, "max_conf": 0.4, "detection_count": 2},
        {"probe_index": 2, "max_conf": 0.7, "detection_count": 2},
    ]

    assert choose_review_probe_indices(probes, "multi_gecko", count=2) == [2, 1]


def test_hard_positive_review_prefers_low_confidence_and_spreads_ties() -> None:
    probes = [
        {"probe_index": 0, "max_conf": 0.0, "detection_count": 0},
        {"probe_index": 1, "max_conf": 0.6, "detection_count": 1},
        {"probe_index": 2, "max_conf": 0.0, "detection_count": 0},
        {"probe_index": 3, "max_conf": 0.1, "detection_count": 1},
    ]

    assert choose_review_probe_indices(probes, "hard_positive", count=2) == [0, 2]


def test_extract_source_refs_reads_all_selection_sections() -> None:
    payload = {
        "dataset_v2_interval": [{"source_ref": "a"}, {"source_ref": "b"}],
        "dataset_v2_lower_priority": [{"source_ref": "b"}, {"source_ref": "c"}],
        "schema": "private",
    }

    assert extract_source_refs(payload) == {"a", "b", "c"}


def test_review_duplicate_rule_is_strict_for_old_data_and_local_to_source() -> None:
    old_digest = 0b1010
    candidate = 0b1011

    assert review_frame_is_duplicate(candidate, {candidate}, set()) is True
    assert review_frame_is_duplicate(candidate, {old_digest}, set()) is False
    assert review_frame_is_duplicate(candidate, set(), {old_digest}) is True
