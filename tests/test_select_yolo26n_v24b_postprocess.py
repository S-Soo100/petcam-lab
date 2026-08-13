import math

import pytest

from scripts.select_yolo26n_v24b_postprocess import (
    NMS_GRID,
    THRESHOLD_GRID,
    PostprocessMetric,
    build_postprocess_freeze,
    score_prediction_ledger,
    select_postprocess_candidate,
)


def _ledger(*, nms_iou: float = 0.70) -> dict[str, object]:
    return {
        "schema": "yolo26n-v24b-postprocess-prediction-ledger-v1",
        "status": "V24B_POSTPROCESS_PREDICTIONS_READY",
        "dataset_schema": "yolo26n-owner-dataset-v24",
        "evaluation_tier": "development",
        "split": "val",
        "candidate": "warm-start",
        "source_commit": "1" * 40,
        "runner_sha256": "2" * 64,
        "dataset_manifest_sha256": "3" * 64,
        "checkpoint_sha256": "4" * 64,
        "inference": {
            "confidence": 0.001,
            "imgsz": 960,
            "nms_iou": nms_iou,
            "max_det": 50,
            "device": "mps",
        },
        "image_count": 3,
        "gt_box_count": 2,
        "prediction_count": 5,
        "records": [
            {
                "sequence": "A0001",
                "image_sha256": "a" * 64,
                "width": 100,
                "height": 100,
                "gt_boxes": [[0, 0, 10, 10]],
                "predictions": [
                    {"confidence": 0.90, "xyxy": [0, 0, 10, 10]},
                    {"confidence": 0.80, "xyxy": [1, 1, 9, 9]},
                    {"confidence": 0.70, "xyxy": [40, 40, 50, 50]},
                ],
            },
            {
                "sequence": "A0002",
                "image_sha256": "b" * 64,
                "width": 100,
                "height": 100,
                "gt_boxes": [],
                "predictions": [{"confidence": 0.60, "xyxy": [20, 20, 30, 30]}],
            },
            {
                "sequence": "A0003",
                "image_sha256": "c" * 64,
                "width": 100,
                "height": 100,
                "gt_boxes": [[20, 20, 30, 30]],
                "predictions": [{"confidence": 0.04, "xyxy": [20, 20, 30, 30]}],
            },
        ],
    }


def _metric(
    *,
    nms_iou: float,
    confidence: float,
    tp: int = 7,
    fp: int,
    fn: int = 3,
    duplicate: int,
    precision: float = 0.70,
    recall: float = 0.70,
    positive_image_recall: float = 0.70,
) -> PostprocessMetric:
    return PostprocessMetric(
        nms_iou=nms_iou,
        confidence=confidence,
        tp=tp,
        fp=fp,
        fn=fn,
        duplicate=duplicate,
        precision=precision,
        recall=recall,
        positive_image_recall=positive_image_recall,
    )


def _passing_ledger(*, nms_iou: float) -> dict[str, object]:
    ledger = _ledger(nms_iou=nms_iou)
    ledger["records"] = [
        {
            "sequence": "A0001",
            "image_sha256": "a" * 64,
            "width": 100,
            "height": 100,
            "gt_boxes": [[0, 0, 10, 10]],
            "predictions": [
                {"confidence": 0.90, "xyxy": [0, 0, 10, 10]},
                {"confidence": 0.80, "xyxy": [1, 1, 9, 9]},
            ],
        },
        {
            "sequence": "A0002",
            "image_sha256": "b" * 64,
            "width": 100,
            "height": 100,
            "gt_boxes": [[20, 20, 30, 30]],
            "predictions": [{"confidence": 0.90, "xyxy": [20, 20, 30, 30]}],
        },
        {
            "sequence": "A0003",
            "image_sha256": "c" * 64,
            "width": 100,
            "height": 100,
            "gt_boxes": [],
            "predictions": [],
        },
    ]
    ledger["image_count"] = 3
    ledger["gt_box_count"] = 2
    ledger["prediction_count"] = 3
    return ledger


def test_grids_are_the_exact_approved_values():
    assert THRESHOLD_GRID == tuple(round(step * 0.05, 2) for step in range(1, 17))
    assert NMS_GRID == (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)


def test_score_uses_greedy_one_to_one_matching_and_counts_duplicate_predictions():
    scored = score_prediction_ledger(_ledger(), confidence=0.05)

    assert (scored.tp, scored.fp, scored.fn, scored.duplicate) == (1, 3, 1, 1)
    assert scored.precision == pytest.approx(1 / 4)
    assert scored.recall == pytest.approx(1 / 2)
    assert scored.positive_image_recall == pytest.approx(1 / 2)


def test_score_is_deterministic_when_ledger_record_order_changes():
    ledger = _ledger()
    reversed_ledger = dict(ledger, records=list(reversed(ledger["records"])))

    assert score_prediction_ledger(ledger, confidence=0.05) == score_prediction_ledger(
        reversed_ledger, confidence=0.05
    )


def test_score_rejects_threshold_or_match_iou_outside_the_frozen_grid():
    with pytest.raises(ValueError, match="grid"):
        score_prediction_ledger(_ledger(), confidence=0.01)
    with pytest.raises(ValueError, match="exactly"):
        score_prediction_ledger(_ledger(), confidence=0.05, match_iou=0.45)


def test_selector_uses_exact_tie_break_order():
    metrics = [
        _metric(nms_iou=0.60, confidence=0.25, fp=8, duplicate=2),
        _metric(nms_iou=0.50, confidence=0.30, fp=8, duplicate=2),
    ]

    selected = select_postprocess_candidate(metrics, baseline_duplicate=3)

    assert selected is not None
    assert (selected.confidence, selected.nms_iou) == (0.30, 0.50)


def test_selector_prioritizes_duplicate_then_recall_then_fp_before_confidence_and_nms():
    selected = select_postprocess_candidate(
        [
            _metric(nms_iou=0.40, confidence=0.80, fp=0, duplicate=2, recall=0.90),
            _metric(nms_iou=0.40, confidence=0.80, fp=0, duplicate=1, recall=0.70),
            _metric(nms_iou=0.40, confidence=0.80, fp=2, duplicate=1, recall=0.80),
            _metric(nms_iou=0.60, confidence=0.80, fp=1, duplicate=1, recall=0.80),
            _metric(nms_iou=0.40, confidence=0.80, fp=1, duplicate=1, recall=0.80),
        ],
        baseline_duplicate=2,
    )

    assert selected is not None
    assert (selected.duplicate, selected.recall, selected.fp, selected.confidence, selected.nms_iou) == (
        1,
        0.80,
        1,
        0.80,
        0.40,
    )


def test_selector_filters_by_all_floors_and_baseline_duplicate():
    eligible = _metric(nms_iou=0.40, confidence=0.25, fp=6, duplicate=3)
    metrics = [
        _metric(nms_iou=0.45, confidence=0.25, fp=1, duplicate=1, precision=0.59),
        _metric(nms_iou=0.50, confidence=0.25, fp=1, duplicate=1, recall=0.64),
        _metric(nms_iou=0.55, confidence=0.25, fp=1, duplicate=4),
        eligible,
    ]

    assert select_postprocess_candidate(metrics, baseline_duplicate=3) == eligible


def test_build_freeze_records_grid_metrics_and_selected_candidate():
    ledgers = {nms_iou: _passing_ledger(nms_iou=nms_iou) for nms_iou in NMS_GRID}
    ledger_sha256 = {nms_iou: f"{index:x}" * 64 for index, nms_iou in enumerate(NMS_GRID)}

    freeze = build_postprocess_freeze(ledgers, ledger_sha256=ledger_sha256)

    assert freeze["status"] == "V24B_POSTPROCESS_FROZEN_DEVELOPMENT_ONLY"
    assert freeze["threshold_grid"] == list(THRESHOLD_GRID)
    assert freeze["nms_grid"] == list(NMS_GRID)
    assert len(freeze["metrics"]) == len(THRESHOLD_GRID) * len(NMS_GRID)
    assert freeze["selected"] == {
        "confidence": 0.80,
        "nms_iou": 0.40,
        "duplicate": 1,
    }


def test_selector_fails_closed_when_no_candidate_meets_floor():
    ledgers = {nms_iou: _ledger(nms_iou=nms_iou) for nms_iou in NMS_GRID}
    for ledger in ledgers.values():
        ledger["records"] = [
            {
                "sequence": "A0001",
                "image_sha256": "a" * 64,
                "width": 100,
                "height": 100,
                "gt_boxes": [[0, 0, 10, 10]],
                "predictions": [{"confidence": 0.90, "xyxy": [40, 40, 50, 50]}],
            }
        ]
        ledger["image_count"] = 1
        ledger["gt_box_count"] = 1
        ledger["prediction_count"] = 1

    result = build_postprocess_freeze(
        ledgers,
        ledger_sha256={nms_iou: "f" * 64 for nms_iou in NMS_GRID},
    )

    assert result["status"] == "V24B_POSTPROCESS_SHORTAGE"
    assert "selected" not in result


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda ledger: ledger.__setitem__("image_count", True), "count"),
        (
            lambda ledger: ledger["records"][0]["predictions"][0].__setitem__(
                "confidence", math.nan
            ),
            "finite",
        ),
        (
            lambda ledger: ledger["records"][0]["predictions"][0].__setitem__(
                "confidence", math.inf
            ),
            "finite",
        ),
        (lambda ledger: ledger.__setitem__("prediction_count", 99), "count"),
        (
            lambda ledger: ledger["records"].append(dict(ledger["records"][0])),
            "duplicate",
        ),
        (lambda ledger: ledger.__setitem__("checkpoint_sha256", "A" * 64), "SHA"),
    ],
)
def test_score_rejects_unsafe_ledger_values(mutate, match):
    ledger = _ledger()
    mutate(ledger)

    with pytest.raises(ValueError, match=match):
        score_prediction_ledger(ledger, confidence=0.05)


def test_selector_rejects_bool_and_nonfinite_metrics_or_baseline():
    valid = _metric(nms_iou=0.40, confidence=0.25, fp=1, duplicate=1)
    invalid_bool = PostprocessMetric(
        nms_iou=0.40,
        confidence=0.25,
        tp=True,
        fp=1,
        fn=1,
        duplicate=1,
        precision=0.7,
        recall=0.7,
        positive_image_recall=0.7,
    )
    invalid_nan = PostprocessMetric(
        nms_iou=0.40,
        confidence=0.25,
        tp=1,
        fp=1,
        fn=1,
        duplicate=1,
        precision=math.nan,
        recall=0.7,
        positive_image_recall=0.7,
    )

    with pytest.raises(ValueError, match="metric"):
        select_postprocess_candidate([invalid_bool], baseline_duplicate=1)
    with pytest.raises(ValueError, match="metric"):
        select_postprocess_candidate([invalid_nan], baseline_duplicate=1)
    with pytest.raises(ValueError, match="baseline"):
        select_postprocess_candidate([valid], baseline_duplicate=True)
