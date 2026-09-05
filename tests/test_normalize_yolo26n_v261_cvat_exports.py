from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import scripts.normalize_yolo26n_v261_cvat_exports as normalizer
from scripts.normalize_yolo26n_v261_cvat_exports import PartSpec, normalize_exports


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)


def _xml(
    images: str, *, labels: tuple[str, ...] = ("gecko", "uncertain", "media_error")
) -> bytes:
    label_xml = "".join(f"<label><name>{name}</name></label>" for name in labels)
    return (
        "<annotations><meta><task><labels>"
        f"{label_xml}</labels></task></meta>{images}</annotations>"
    ).encode()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, tuple[PartSpec, ...]]:
    queue_root = tmp_path / "queue"
    export_root = tmp_path / "exports"
    output_root = tmp_path / "human-gt"
    queue_root.mkdir()
    export_root.mkdir()

    _write_zip(queue_root / "part-01.zip", {"V0000001.jpg": b"one"})
    _write_zip(queue_root / "part-02.zip", {"V0000002.jpg": b"two"})
    _write_zip(
        export_root / "task-01.zip",
        {
            "annotations.xml": _xml(
                '<image id="0" name="V0000001.jpg" width="100" height="50">'
                '<box label="gecko" xtl="10" ytl="5" xbr="60" ybr="35"/>'
                "</image>"
            )
        },
    )
    _write_zip(
        export_root / "task-02.zip",
        {
            "annotations.xml": _xml(
                '<image id="0" name="V0000002.jpg" width="80" height="40"/>'
            )
        },
    )

    review_index = tmp_path / "review-index.private.json"
    review_index.write_text(
        json.dumps(
            {
                "schema": "yolo26n-v261-blind-review-index-v1",
                "records": [
                    {
                        "blind_name": "V0000001.jpg",
                        "clip_ref": "clip-a",
                        "camera_ref": "cam-a",
                        "camera_night": "night-a",
                        "timestamp_sec": 1.0,
                        "image_sha256": hashlib.sha256(b"one").hexdigest(),
                        "source_video_sha256": "a" * 64,
                        "width": 100,
                        "height": 50,
                        "zip_part": 1,
                    },
                    {
                        "blind_name": "V0000002.jpg",
                        "clip_ref": "clip-b",
                        "camera_ref": "cam-a",
                        "camera_night": "night-a",
                        "timestamp_sec": 2.0,
                        "image_sha256": hashlib.sha256(b"two").hexdigest(),
                        "source_video_sha256": "b" * 64,
                        "width": 80,
                        "height": 40,
                        "zip_part": 2,
                    },
                ],
            }
        )
    )
    parts = (
        PartSpec("task-01.zip", "part-01.zip", 1),
        PartSpec("task-02.zip", "part-02.zip", 1),
    )
    completion = tmp_path / "completion.private.json"
    completion.write_text(
        json.dumps(
            {
                "schema": "yolo26n-v261-blind-queue-completion-v1",
                "status": "BLIND_QUEUE_READY",
                "accepted_frame_count": 2,
                "review_index_sha256": _sha(review_index),
                "zip_sha256": {
                    "part-01.zip": _sha(queue_root / "part-01.zip"),
                    "part-02.zip": _sha(queue_root / "part-02.zip"),
                },
            }
        )
    )
    return review_index, completion, queue_root, export_root, output_root, parts


def test_normalize_exports_writes_present_and_absent_gt(tmp_path: Path) -> None:
    review, completion, queue, exports, output, parts = _fixture(tmp_path)

    result = normalize_exports(
        review_index_path=review,
        queue_completion_path=completion,
        queue_root=queue,
        export_root=exports,
        output_root=output,
        part_specs=parts,
    )

    assert result["status"] == "V261_HUMAN_GT_READY"
    assert result["counts"] == {
        "images": 2,
        "positive_images": 1,
        "empty_images": 1,
        "gecko_boxes": 1,
        "uncertain_images": 0,
        "media_error_images": 0,
    }
    records = result["records"]
    assert records[0]["state"] == "gecko_present"
    assert records[0]["boxes_yolo"] == [[0, 0.35, 0.4, 0.5, 0.6]]
    assert records[1]["state"] == "gecko_absent"
    assert records[1]["boxes_yolo"] == []
    assert (
        json.loads((output / "export-freeze.private.json").read_text())["schema"]
        == "yolo26n-v261-export-freeze-v1"
    )
    assert json.loads((output / "final-human-gt.private.json").read_text()) == result


def test_normalize_exports_rejects_queue_export_order_mismatch(tmp_path: Path) -> None:
    review, completion, queue, exports, output, parts = _fixture(tmp_path)
    _write_zip(queue / "part-01.zip", {"WRONG.jpg": b"one"})
    payload = json.loads(completion.read_text())
    payload["zip_sha256"]["part-01.zip"] = _sha(queue / "part-01.zip")
    completion.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="queue/export image order mismatch"):
        normalize_exports(
            review_index_path=review,
            queue_completion_path=completion,
            queue_root=queue,
            export_root=exports,
            output_root=output,
            part_specs=parts,
        )


@pytest.mark.parametrize(
    ("image_xml", "message"),
    [
        (
            (
                '<image id="0" name="V0000001.jpg" width="100" height="50">'
                '<box label="gecko" xtl="60" ytl="5" xbr="10" ybr="35"/></image>'
            ),
            "invalid bbox",
        ),
        (
            (
                '<image id="0" name="V0000001.jpg" width="100" height="50">'
                '<tag label="uncertain"/><tag label="media_error"/></image>'
            ),
            "conflicting tags",
        ),
    ],
)
def test_normalize_exports_rejects_invalid_annotation(
    tmp_path: Path, image_xml: str, message: str
) -> None:
    review, completion, queue, exports, output, parts = _fixture(tmp_path)
    _write_zip(exports / "task-01.zip", {"annotations.xml": _xml(image_xml)})

    with pytest.raises(ValueError, match=message):
        normalize_exports(
            review_index_path=review,
            queue_completion_path=completion,
            queue_root=queue,
            export_root=exports,
            output_root=output,
            part_specs=parts,
        )


def test_normalize_exports_rejects_existing_output(tmp_path: Path) -> None:
    review, completion, queue, exports, output, parts = _fixture(tmp_path)
    output.mkdir()

    with pytest.raises(FileExistsError):
        normalize_exports(
            review_index_path=review,
            queue_completion_path=completion,
            queue_root=queue,
            export_root=exports,
            output_root=output,
            part_specs=parts,
        )


def test_normalize_exports_rejects_output_outside_attempt(tmp_path: Path) -> None:
    review, completion, queue, exports, _, parts = _fixture(tmp_path)
    with pytest.raises(ValueError, match="direct child"):
        normalize_exports(
            review_index_path=review,
            queue_completion_path=completion,
            queue_root=queue,
            export_root=exports,
            output_root=tmp_path / "nested" / "human-gt",
            part_specs=parts,
        )


def test_normalize_exports_requires_exact_ready_counts_and_global_names(
    tmp_path: Path,
) -> None:
    review, completion, queue, exports, output, parts = _fixture(tmp_path)
    with pytest.raises(ValueError, match="exact GT count contract"):
        normalize_exports(
            review_index_path=review,
            queue_completion_path=completion,
            queue_root=queue,
            export_root=exports,
            output_root=output,
            part_specs=parts,
            expected_counts={
                "images": 2,
                "positive_images": 2,
                "empty_images": 0,
                "gecko_boxes": 2,
                "uncertain_images": 0,
                "media_error_images": 0,
            },
        )

    payload = json.loads(review.read_text())
    payload["records"][1]["blind_name"] = "V0000003.jpg"
    review.write_text(json.dumps(payload))
    completion_payload = json.loads(completion.read_text())
    completion_payload["review_index_sha256"] = _sha(review)
    completion.write_text(json.dumps(completion_payload))
    _write_zip(queue / "part-02.zip", {"V0000003.jpg": b"two"})
    completion_payload = json.loads(completion.read_text())
    completion_payload["zip_sha256"]["part-02.zip"] = _sha(queue / "part-02.zip")
    completion.write_text(json.dumps(completion_payload))
    _write_zip(
        exports / "task-02.zip",
        {
            "annotations.xml": _xml(
                '<image id="0" name="V0000003.jpg" width="80" height="40"/>'
            )
        },
    )
    with pytest.raises(ValueError, match="global blind name sequence"):
        normalize_exports(
            review_index_path=review,
            queue_completion_path=completion,
            queue_root=queue,
            export_root=exports,
            output_root=output,
            part_specs=parts,
        )


def test_normalize_exports_detects_input_mutation_before_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review, completion, queue, exports, output, parts = _fixture(tmp_path)
    original = normalizer._parse_export
    mutated = False

    def parse_and_mutate(path: Path):
        nonlocal mutated
        result = original(path)
        if not mutated:
            path.write_bytes(path.read_bytes() + b"drift")
            mutated = True
        return result

    monkeypatch.setattr(normalizer, "_parse_export", parse_and_mutate)
    with pytest.raises(ValueError, match="input changed during normalization"):
        normalize_exports(
            review_index_path=review,
            queue_completion_path=completion,
            queue_root=queue,
            export_root=exports,
            output_root=output,
            part_specs=parts,
        )
    assert not output.exists()
