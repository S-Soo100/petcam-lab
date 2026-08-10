from scripts.build_yolo26n_v22_candidate_queue import (
    V22CandidatePolicy,
    classify_v22_candidate,
    select_v22_candidate_sources,
)


def _row(
    source_ref: str,
    camera_night: str,
    camera_id: str,
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
        "camera_id": camera_id,
        "yolo_max_conf": yolo_max_conf,
        "yolo_detection_count": yolo_detection_count,
        "gme_visible_ratio": gme_visible_ratio,
        "gme_unknown_ratio": gme_unknown_ratio,
        "gme_max_geckos": gme_max_geckos,
    }


def test_v22_selection_never_backfills_negative_quota_with_positive_sources() -> None:
    policy = V22CandidatePolicy(
        frame_quotas={"hard_positive": 4, "hard_negative": 2},
        frames_per_source=2,
        max_frames_per_camera_night=4,
        seed="owner-v2.2",
    )
    rows = [
        _row("p1", "n1", "c1", gme_max_geckos=1, yolo_detection_count=0),
        _row("p2", "n2", "c2", gme_max_geckos=1, yolo_detection_count=0),
    ]

    selected = select_v22_candidate_sources(rows, policy=policy)

    assert [row["candidate_bucket"] for row in selected] == [
        "hard_positive",
        "hard_positive",
    ]
    assert sum(row["planned_frame_count"] for row in selected) == 4


def test_v22_selection_excludes_existing_sources_and_is_input_order_independent() -> None:
    policy = V22CandidatePolicy(
        frame_quotas={"hard_positive": 4, "hard_negative": 2},
        frames_per_source=2,
        max_frames_per_camera_night=12,
        seed="owner-v2.2",
    )
    rows = [
        _row("positive-a", "night-a", "camera-a", gme_max_geckos=1),
        _row("positive-b", "night-b", "camera-b", gme_max_geckos=1),
        _row(
            "negative-a",
            "night-c",
            "camera-c",
            yolo_max_conf=0.8,
            yolo_detection_count=1,
        ),
        _row(
            "excluded-negative",
            "night-d",
            "camera-d",
            yolo_max_conf=0.8,
            yolo_detection_count=1,
        ),
    ]

    first = select_v22_candidate_sources(
        rows,
        policy=policy,
        excluded_source_refs={"excluded-negative"},
    )
    second = select_v22_candidate_sources(
        list(reversed(rows)),
        policy=policy,
        excluded_source_refs={"excluded-negative"},
    )

    assert first == second
    assert "excluded-negative" not in {row["source_ref"] for row in first}


def test_v22_selection_caps_source_and_camera_night_frame_counts() -> None:
    policy = V22CandidatePolicy(
        frame_quotas={"hard_positive": 14},
        frames_per_source=2,
        max_frames_per_camera_night=12,
        seed="owner-v2.2",
    )
    rows = [
        _row(f"positive-{index}", "night-a", "camera-a", gme_max_geckos=1)
        for index in range(7)
    ]

    selected = select_v22_candidate_sources(rows, policy=policy)

    assert all(row["planned_frame_count"] <= 2 for row in selected)
    assert sum(
        row["planned_frame_count"] for row in selected if row["camera_night"] == "night-a"
    ) == 12
    assert len(selected) == 6


def test_v22_multi_gecko_is_a_hard_positive_with_a_stratum_tag() -> None:
    candidate = _row("multi", "night-a", "camera-a", gme_max_geckos=2)
    policy = V22CandidatePolicy(
        frame_quotas={"hard_positive": 2},
        frames_per_source=2,
        max_frames_per_camera_night=12,
        seed="owner-v2.2",
    )

    selected = select_v22_candidate_sources([candidate], policy=policy)

    assert classify_v22_candidate(candidate) == "hard_positive"
    assert selected[0]["candidate_bucket"] == "hard_positive"
    assert "multi_gecko" in selected[0]["strata_tags"]


def test_v22_yolo_only_signal_is_a_review_candidate_not_a_human_negative_label() -> None:
    candidate = _row(
        "yolo-only",
        "night-a",
        "camera-a",
        yolo_max_conf=0.8,
        yolo_detection_count=1,
    )
    policy = V22CandidatePolicy(
        frame_quotas={"hard_negative": 2},
        frames_per_source=2,
        max_frames_per_camera_night=12,
        seed="owner-v2.2",
    )

    selected = select_v22_candidate_sources([candidate], policy=policy)

    assert classify_v22_candidate(candidate) == "hard_negative"
    assert selected[0]["candidate_bucket"] == "hard_negative"
    assert selected[0]["review_required"] is True
    assert not {"label", "bbox", "presence"}.intersection(selected[0])
