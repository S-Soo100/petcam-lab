from __future__ import annotations

import copy

import pytest

from scripts.normalize_yolo26n_v25_cvat_export import normalize_export


def _queue() -> dict[str, object]:
    records = []
    for index in range(1, 202):
        records.append(
            {
                "sequence": f"V25{index:04d}",
                "filename": f"V25{index:04d}.jpg",
                "image_sha256": f"{index:064x}",
                "width": 960,
                "height": 720,
                "annotation_policy": "blind-human-bbox",
            }
        )
    return {
        "schema": "yolo26n-v25-blind-queue-manifest-v1",
        "status": "V25_BLIND_QUEUE_READY",
        "queue_count": 201,
        "prediction_visible": False,
        "empty_frame_allowed": True,
        "records": records,
    }


def _shape(frame: int, *, shape_id: int) -> dict[str, object]:
    return {
        "id": shape_id,
        "type": "rectangle",
        "frame": frame,
        "label_id": 11,
        "group": 0,
        "source": "manual",
        "occluded": False,
        "outside": False,
        "z_order": 0,
        "rotation": 0.0,
        "points": [10.0, 20.0, 110.0, 220.0],
        "attributes": [],
        "elements": [],
        "score": 1.0,
    }


def _annotations() -> dict[str, object]:
    shapes = [_shape(frame, shape_id=frame + 1) for frame in range(198)]
    shapes.extend(_shape(frame, shape_id=199 + offset) for offset, frame in enumerate(range(18)))
    shapes.extend(_shape(0, shape_id=217 + offset) for offset in range(3))
    return {
        "version": 0,
        "tags": [],
        "tracks": [],
        "shapes": shapes,
    }


def test_normalize_exact_job164_contract() -> None:
    result = normalize_export(
        task_id=167,
        job_id=164,
        job_state="completed",
        raw_annotations=_annotations(),
        queue_manifest=_queue(),
    )

    assert result["schema"] == "yolo26n-v25-human-snapshot-v1"
    assert result["status"] == "V25_HUMAN_EXPORT_ACCEPTED"
    assert result["frame_count"] == 201
    assert result["positive_frame_count"] == 198
    assert result["negative_frame_count"] == 3
    assert result["box_count"] == 219
    assert len(result["images"]) == 201
    assert result["images"][-1]["boxes"] == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("task_id", 168), ("job_id", 165), ("job_state", "annotation")],
)
def test_normalize_rejects_wrong_job_contract(field: str, value: object) -> None:
    kwargs = {
        "task_id": 167,
        "job_id": 164,
        "job_state": "completed",
        "raw_annotations": _annotations(),
        "queue_manifest": _queue(),
    }
    kwargs[field] = value
    with pytest.raises(ValueError):
        normalize_export(**kwargs)


@pytest.mark.parametrize("field", ["rotation", "group", "z_order", "frame", "label_id"])
def test_normalize_rejects_bool_as_int(field: str) -> None:
    annotations = _annotations()
    annotations["shapes"][0][field] = False
    with pytest.raises(ValueError):
        normalize_export(167, 164, "completed", annotations, _queue())


def test_normalize_rejects_noncanonical_score_type() -> None:
    annotations = _annotations()
    annotations["shapes"][0]["score"] = True
    with pytest.raises(ValueError):
        normalize_export(167, 164, "completed", annotations, _queue())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("label_id", 10),
        ("source", "auto"),
        ("type", "polygon"),
        ("outside", True),
        ("rotation", 1.0),
        ("points", [10.0, 10.0, 10.0, 20.0]),
    ],
)
def test_normalize_rejects_invalid_shapes(field: str, value: object) -> None:
    annotations = _annotations()
    annotations["shapes"][0][field] = value
    with pytest.raises(ValueError):
        normalize_export(167, 164, "completed", annotations, _queue())


def test_normalize_rejects_tracks_tags_and_queue_drift() -> None:
    annotations = _annotations()
    annotations["tracks"] = [{}]
    with pytest.raises(ValueError):
        normalize_export(167, 164, "completed", annotations, _queue())

    annotations = _annotations()
    queue = copy.deepcopy(_queue())
    queue["records"].pop()
    with pytest.raises(ValueError):
        normalize_export(167, 164, "completed", annotations, queue)


def test_normalize_rejects_wrong_aggregate() -> None:
    annotations = _annotations()
    annotations["shapes"].pop()
    with pytest.raises(ValueError):
        normalize_export(167, 164, "completed", annotations, _queue())
