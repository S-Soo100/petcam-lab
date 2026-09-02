from scripts.analyze_yolo26n_owner_media_failures import analyze_failures


def test_analyzer_assigns_failures_without_exposing_sequences():
    ledger = {
        "schema": "yolo26n-owner-media-external-predictions-v1",
        "status": "PREDICTIONS_COMPLETE",
        "records": [
            {"sequence": "O0001", "gt_boxes": [[10, 10, 50, 50]], "predictions": []},
            {
                "sequence": "O0002",
                "gt_boxes": [[10, 10, 50, 50]],
                "predictions": [
                    {"confidence": .9, "xyxy": [10, 10, 50, 50]},
                    {"confidence": .8, "xyxy": [11, 11, 49, 49]},
                ],
            },
            {
                "sequence": "O0003",
                "gt_boxes": [],
                "predictions": [{"confidence": .7, "xyxy": [1, 1, 5, 5]}],
            },
            {
                "sequence": "O0004",
                "gt_boxes": [[10, 10, 50, 50]],
                "predictions": [{"confidence": .7, "xyxy": [40, 40, 70, 70]}],
            },
        ],
    }

    report = analyze_failures(ledger, threshold=.20, iou_threshold=.50)

    assert report["status"] == "OWNER_MEDIA_FAILURE_ANALYSIS_COMPLETE"
    assert report["image_count"] == 4
    assert report["failure_counts"] == {
        "complete_miss": 2,
        "duplicate_box": 1,
        "false_positive_negative": 1,
        "localization_error": 1,
    }
    assert report["priority"] == [
        "complete_miss",
        "false_positive_negative",
        "duplicate_box",
        "localization_error",
    ]
    assert "sequence" not in str(report)
    assert report["db_write_count"] == report["r2_write_count"] == 0


def test_analyzer_rejects_duplicate_sequence_and_invalid_geometry():
    duplicate = {
        "schema": "yolo26n-owner-media-external-predictions-v1",
        "status": "PREDICTIONS_COMPLETE",
        "records": [
            {"sequence": "O0001", "gt_boxes": [], "predictions": []},
            {"sequence": "O0001", "gt_boxes": [], "predictions": []},
        ],
    }
    try:
        analyze_failures(duplicate, threshold=.20, iou_threshold=.50)
    except ValueError as exc:
        assert "sequence" in str(exc)
    else:
        raise AssertionError("duplicate sequence must fail")

    malformed = {
        "schema": "yolo26n-owner-media-external-predictions-v1",
        "status": "PREDICTIONS_COMPLETE",
        "records": [
            {"sequence": "O0001", "gt_boxes": [[5, 5, 1, 1]], "predictions": []},
        ],
    }
    try:
        analyze_failures(malformed, threshold=.20, iou_threshold=.50)
    except ValueError as exc:
        assert "box" in str(exc)
    else:
        raise AssertionError("invalid box must fail")
