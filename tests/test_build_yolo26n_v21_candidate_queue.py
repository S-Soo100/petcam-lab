from scripts.build_yolo26n_v21_candidate_queue import (
    CandidatePolicy,
    classify_candidate,
    select_candidate_sources,
)


def _row(
    source_ref: str,
    camera_night: str,
    *,
    yolo_max_conf: float = 0.0,
    yolo_detection_count: int = 0,
    gme_visible_ratio: float = 0.0,
    gme_unknown_ratio: float = 0.0,
    gme_max_geckos: int = 0,
) -> dict[str, object]:
    return {
        "source_ref": source_ref,
        "camera_night": camera_night,
        "yolo_max_conf": yolo_max_conf,
        "yolo_detection_count": yolo_detection_count,
        "gme_visible_ratio": gme_visible_ratio,
        "gme_unknown_ratio": gme_unknown_ratio,
        "gme_max_geckos": gme_max_geckos,
    }


def test_classification_prioritizes_multi_gecko_before_other_signals() -> None:
    candidate = _row(
        "source-1",
        "night-1",
        yolo_max_conf=0.9,
        yolo_detection_count=2,
        gme_unknown_ratio=0.9,
        gme_max_geckos=2,
    )

    assert classify_candidate(candidate) == "multi_gecko"


def test_two_yolo_boxes_without_gme_presence_is_a_false_positive_candidate() -> None:
    candidate = _row(
        "source-1",
        "night-1",
        yolo_max_conf=0.8,
        yolo_detection_count=2,
        gme_visible_ratio=0.0,
        gme_max_geckos=0,
    )

    assert classify_candidate(candidate) == "hard_negative"


def test_classification_surfaces_detector_disagreements_without_making_labels() -> None:
    likely_false_positive = _row(
        "source-1",
        "night-1",
        yolo_max_conf=0.8,
        yolo_detection_count=1,
        gme_visible_ratio=0.05,
        gme_unknown_ratio=0.1,
        gme_max_geckos=0,
    )
    likely_hard_positive = _row(
        "source-2",
        "night-2",
        yolo_max_conf=0.02,
        yolo_detection_count=0,
        gme_visible_ratio=0.4,
        gme_unknown_ratio=0.5,
        gme_max_geckos=1,
    )

    assert classify_candidate(likely_false_positive) == "hard_negative"
    assert classify_candidate(likely_hard_positive) == "hard_positive"


def test_selection_is_deterministic_excludes_existing_and_caps_each_night() -> None:
    rows = [
        _row("multi-a", "night-a", gme_max_geckos=2),
        _row("multi-b", "night-a", gme_max_geckos=2),
        _row("multi-c", "night-b", gme_max_geckos=2),
        _row(
            "negative-a",
            "night-c",
            yolo_max_conf=0.8,
            yolo_detection_count=1,
        ),
        _row(
            "positive-a",
            "night-d",
            gme_visible_ratio=0.5,
            gme_unknown_ratio=0.4,
            gme_max_geckos=1,
        ),
        _row("coverage-a", "night-e", gme_unknown_ratio=0.8),
        _row("already-used", "night-f", gme_max_geckos=2),
    ]
    policy = CandidatePolicy(
        bucket_quotas={
            "multi_gecko": 2,
            "hard_negative": 1,
            "hard_positive": 1,
            "coverage": 1,
        },
        max_sources_per_camera_night=1,
        seed="owner-v2.1",
    )

    first = select_candidate_sources(
        rows,
        policy=policy,
        excluded_source_refs={"already-used"},
    )
    second = select_candidate_sources(
        list(reversed(rows)),
        policy=policy,
        excluded_source_refs={"already-used"},
    )

    assert first == second
    assert {item["source_ref"] for item in first} == {
        "multi-b",
        "multi-c",
        "negative-a",
        "positive-a",
        "coverage-a",
    }
    assert all(item["review_required"] is True for item in first)
    assert all("label" not in item for item in first)


def test_selection_never_reuses_a_source_across_buckets() -> None:
    rows = [
        _row(
            "ambiguous",
            "night-a",
            yolo_max_conf=0.9,
            yolo_detection_count=2,
            gme_max_geckos=2,
        ),
        _row("coverage", "night-b"),
    ]
    policy = CandidatePolicy(
        bucket_quotas={
            "multi_gecko": 1,
            "hard_negative": 1,
            "hard_positive": 0,
            "coverage": 1,
        },
        max_sources_per_camera_night=2,
        seed="owner-v2.1",
    )

    selected = select_candidate_sources(rows, policy=policy)

    refs = [item["source_ref"] for item in selected]
    assert refs == ["ambiguous", "coverage"]
    assert len(refs) == len(set(refs))


def test_selection_backfills_an_empty_bucket_without_breaking_night_cap() -> None:
    rows = [
        _row("coverage-a", "night-a"),
        _row("coverage-b", "night-b"),
        _row("coverage-c", "night-c"),
    ]
    policy = CandidatePolicy(
        bucket_quotas={
            "multi_gecko": 1,
            "hard_negative": 0,
            "hard_positive": 0,
            "coverage": 2,
        },
        max_sources_per_camera_night=1,
        seed="owner-v2.1",
    )

    selected = select_candidate_sources(rows, policy=policy)

    assert len(selected) == 3
    assert {item["source_ref"] for item in selected} == {
        "coverage-a",
        "coverage-b",
        "coverage-c",
    }
