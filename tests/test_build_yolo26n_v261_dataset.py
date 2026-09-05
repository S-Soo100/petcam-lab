from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from scripts.build_yolo26n_v261_dataset import (
    _object_digest,
    build_group_split,
    materialize_dataset,
)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _human_gt() -> dict[str, object]:
    records = []
    for index, (clip, state, night, stamp) in enumerate(
        (
            ("clip-a", "gecko_present", "night-a", 0.0),
            ("clip-b", "gecko_absent", "night-a", 1.0),
            ("clip-c", "gecko_present", "night-b", 2.0),
            ("clip-d", "gecko_absent", "night-b", 3.0),
            ("clip-e", "uncertain", "night-b", 4.0),
        ),
        start=1,
    ):
        image = f"image-{index}".encode()
        records.append(
            {
                "blind_name": f"V{index:07d}.jpg",
                "clip_ref": clip,
                "camera_ref": "cam-a" if night == "night-a" else "cam-b",
                "camera_night": night,
                "timestamp_sec": stamp,
                "image_sha256": _sha_bytes(image),
                "source_video_sha256": f"{index:x}" * 64,
                "width": 100,
                "height": 50,
                "zip_part": 1,
                "dhash64": f"{index:016x}",
                "state": state,
                "boxes_yolo": [[0, 0.5, 0.5, 0.2, 0.4]]
                if state == "gecko_present"
                else [],
            }
        )
    return {
        "schema": "yolo26n-v261-final-human-gt-v1",
        "status": "V261_HUMAN_GT_READY",
        "records": records,
    }


def _sources() -> dict[str, object]:
    return {
        "schema": "yolo26n-v261-development-sources-v1",
        "records": [
            {
                "clip_ref": "clip-a",
                "camera_ref": "cam-a",
                "camera_night": "night-a",
                "started_at": "2026-09-01T00:00:00+09:00",
                "duration_sec": 60,
            },
            {
                "clip_ref": "clip-b",
                "camera_ref": "cam-a",
                "camera_night": "night-a",
                "started_at": "2026-09-01T00:01:30+09:00",
                "duration_sec": 60,
            },
            {
                "clip_ref": "clip-c",
                "camera_ref": "cam-b",
                "camera_night": "night-b",
                "started_at": "2026-09-02T00:00:00+09:00",
                "duration_sec": 60,
            },
            {
                "clip_ref": "clip-d",
                "camera_ref": "cam-b",
                "camera_night": "night-b",
                "started_at": "2026-09-02T00:05:00+09:00",
                "duration_sec": 60,
            },
            {
                "clip_ref": "clip-e",
                "camera_ref": "cam-b",
                "camera_night": "night-b",
                "started_at": "2026-09-02T00:10:00+09:00",
                "duration_sec": 60,
            },
        ],
    }


def _parent_manifest(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    parent = tmp_path / "parent"
    (parent / "images" / "train").mkdir(parents=True)
    (parent / "labels" / "train").mkdir(parents=True)
    image = b"parent-image"
    label = b"0 0.5 0.5 0.2 0.2\n"
    image_path = parent / "images" / "train" / "old.jpg"
    label_path = parent / "labels" / "train" / "old.txt"
    image_path.write_bytes(image)
    label_path.write_bytes(label)
    manifest = {
        "schema": "yolo26n-owner-dataset-v26",
        "status": "V26_DATASET_READY",
        "records": [
            {
                "split": "train",
                "image_path": "images/train/old.jpg",
                "label_path": "labels/train/old.txt",
                "image_sha256": _sha_bytes(image),
                "label_sha256": _sha_bytes(label),
                "positive": True,
                "box_count": 1,
            },
            {"split": "val", "image_sha256": "e" * 64},
            {"split": "regression-val", "image_sha256": "f" * 64},
            {"split": "regression-test", "image_sha256": "a" * 64},
        ],
    }
    (parent / "manifest.private.json").write_text(json.dumps(manifest))
    return parent, manifest


def test_build_group_split_keeps_adjacent_clips_together_and_excludes_uncertain() -> (
    None
):
    plan = build_group_split(
        final_gt=_human_gt(),
        development_sources=_sources(),
        parent_manifest={
            "schema": "yolo26n-owner-dataset-v26",
            "status": "V26_DATASET_READY",
            "records": [],
        },
    )

    assert plan["status"] == "V261_GROUP_SPLIT_READY"
    by_clip = {row["clip_ref"]: row["split"] for row in plan["records"]}
    assert by_clip["clip-a"] == by_clip["clip-b"]
    assert "clip-e" not in by_clip
    assert plan["excluded_counts"] == {"uncertain": 1, "media_error": 0}
    assert {row["split"] for row in plan["records"]} == {"train", "val"}


def test_build_group_split_rejects_protected_or_future_overlap() -> None:
    final_gt = _human_gt()
    common = {
        "final_gt": final_gt,
        "development_sources": _sources(),
        "parent_manifest": {
            "schema": "yolo26n-owner-dataset-v26",
            "status": "V26_DATASET_READY",
            "records": [],
        },
    }
    with pytest.raises(ValueError, match="protected image overlap"):
        build_group_split(
            **common, protected_image_sha256={final_gt["records"][0]["image_sha256"]}
        )
    with pytest.raises(ValueError, match="future holdout overlap"):
        build_group_split(**common, future_clip_refs={"clip-a"})


def test_build_group_split_uses_parent_train_only() -> None:
    parent = {
        "schema": "yolo26n-owner-dataset-v26",
        "status": "V26_DATASET_READY",
        "records": [
            {"split": "train", "image_sha256": "1" * 64},
            {"split": "val", "image_sha256": "2" * 64},
            {"split": "regression-val", "image_sha256": "3" * 64},
            {"split": "regression-test", "image_sha256": "4" * 64},
        ],
    }
    plan = build_group_split(
        final_gt=_human_gt(), development_sources=_sources(), parent_manifest=parent
    )
    assert plan["parent_replay_count"] == 1
    assert plan["parent_excluded_split_counts"] == {
        "val": 1,
        "regression-val": 1,
        "regression-test": 1,
    }


def test_build_group_split_groups_near_duplicates_before_assignment() -> None:
    final_gt = _human_gt()
    parent = {
        "schema": "yolo26n-owner-dataset-v26",
        "status": "V26_DATASET_READY",
        "records": [],
    }
    first = build_group_split(
        final_gt=final_gt, development_sources=_sources(), parent_manifest=parent
    )
    train = next(row for row in first["records"] if row["split"] == "train")
    val = next(row for row in first["records"] if row["split"] == "val")
    # Force the two selected rows close in absolute time within one camera-night.
    sources = _sources()
    source_by_clip = {row["clip_ref"]: row for row in sources["records"]}
    source_by_clip[val["clip_ref"]]["camera_night"] = source_by_clip[train["clip_ref"]][
        "camera_night"
    ]
    source_by_clip[val["clip_ref"]]["started_at"] = source_by_clip[train["clip_ref"]][
        "started_at"
    ]
    for row in final_gt["records"]:
        if row["clip_ref"] in {train["clip_ref"], val["clip_ref"]}:
            row["camera_night"] = source_by_clip[train["clip_ref"]]["camera_night"]
            row["dhash64"] = "0000000000000000"

    plan = build_group_split(
        final_gt=final_gt, development_sources=sources, parent_manifest=parent
    )
    selected = [
        row
        for row in plan["records"]
        if row["clip_ref"] in {train["clip_ref"], val["clip_ref"]}
    ]
    assert len({row["split"] for row in selected}) == 1
    assert len({row["split_group_id"] for row in selected}) == 1


def test_build_group_split_rejects_parent_train_exact_overlap() -> None:
    final_gt = _human_gt()
    parent = {
        "schema": "yolo26n-owner-dataset-v26",
        "status": "V26_DATASET_READY",
        "records": [
            {"split": "train", "image_sha256": final_gt["records"][0]["image_sha256"]}
        ],
    }
    with pytest.raises(ValueError, match="v2.6 train image overlap"):
        build_group_split(
            final_gt=final_gt, development_sources=_sources(), parent_manifest=parent
        )


def test_build_group_split_requires_dhash_and_scopes_protected_near_duplicate() -> None:
    final_gt = _human_gt()
    parent = {
        "schema": "yolo26n-owner-dataset-v26",
        "status": "V26_DATASET_READY",
        "records": [],
    }
    missing = json.loads(json.dumps(final_gt))
    del missing["records"][0]["dhash64"]
    with pytest.raises(ValueError, match="dHash is required"):
        build_group_split(
            final_gt=missing,
            development_sources=_sources(),
            parent_manifest=parent,
        )
    with pytest.raises(ValueError, match="protected near-duplicate"):
        build_group_split(
            final_gt=final_gt,
            development_sources=_sources(),
            parent_manifest=parent,
            protected_dhash_by_source={"clip-a": {"0000000000000000"}},
        )
    result = build_group_split(
        final_gt=final_gt,
        development_sources=_sources(),
        parent_manifest=parent,
        protected_dhash_by_source={"different-source": {"0000000000000000"}},
    )
    assert result["status"] == "V261_GROUP_SPLIT_READY"


def test_build_group_split_preserves_positive_negative_night_coverage_when_possible(
    tmp_path: Path,
) -> None:
    del tmp_path
    records = []
    sources = []
    for index in range(4):
        clip = f"clip-{index}"
        state = "gecko_present" if index % 2 == 0 else "gecko_absent"
        records.append(
            {
                "blind_name": f"V{index + 1:07d}.jpg",
                "clip_ref": clip,
                "camera_ref": "cam-a",
                "camera_night": "night-a",
                "timestamp_sec": 0.0,
                "image_sha256": hashlib.sha256(clip.encode()).hexdigest(),
                "dhash64": f"{index * 256:016x}",
                "state": state,
                "boxes_yolo": [[0, 0.5, 0.5, 0.2, 0.2]]
                if state == "gecko_present"
                else [],
            }
        )
        sources.append(
            {
                "clip_ref": clip,
                "camera_ref": "cam-a",
                "camera_night": "night-a",
                "started_at": f"2026-09-01T0{index}:00:00+09:00",
                "duration_sec": 60,
            }
        )
    plan = build_group_split(
        final_gt={
            "schema": "yolo26n-v261-final-human-gt-v1",
            "status": "V261_HUMAN_GT_READY",
            "records": records,
        },
        development_sources={
            "schema": "yolo26n-v261-development-sources-v1",
            "records": sources,
        },
        parent_manifest={
            "schema": "yolo26n-owner-dataset-v26",
            "status": "V26_DATASET_READY",
            "records": [],
        },
    )
    assert plan["split_state_counts"] == {
        "train:gecko_absent": 1,
        "train:gecko_present": 1,
        "val:gecko_absent": 1,
        "val:gecko_present": 1,
    }


def test_materialize_dataset_copies_parent_train_and_writes_empty_negative(
    tmp_path: Path,
) -> None:
    final_gt = _human_gt()
    final_gt["records"] = final_gt["records"][:4]
    sources = _sources()
    sources["records"] = sources["records"][:4]
    parent_root, parent_manifest = _parent_manifest(tmp_path)
    split = build_group_split(
        final_gt=final_gt, development_sources=sources, parent_manifest=parent_manifest
    )
    queue_root = tmp_path / "queue"
    queue_root.mkdir()
    with ZipFile(queue_root / "cvat-upload-part-01.zip", "w", ZIP_DEFLATED) as archive:
        for index in range(1, 5):
            archive.writestr(f"V{index:07d}.jpg", f"image-{index}".encode())

    output = tmp_path / "dataset"
    manifest = materialize_dataset(
        final_gt=final_gt,
        split_plan=split,
        expected_split_sha256=_object_digest(split),
        development_sources=sources,
        parent_manifest=parent_manifest,
        protected_image_sha256=set(),
        protected_dhash_by_source={},
        future_clip_refs=set(),
        input_lineage={},
        parent_dataset_root=parent_root,
        queue_root=queue_root,
        output_root=output,
        source_commit="b" * 40,
        lineage={"final_human_gt_sha256": "c" * 64, "parent_manifest_sha256": "d" * 64},
    )

    assert manifest["status"] == "V261_DATASET_READY"
    assert manifest["parent_train_count"] == 1
    assert manifest["new_image_count"] == 4
    assert manifest["lineage"]["final_human_gt_sha256"] == "c" * 64
    negative = next(
        row for row in manifest["records"] if row.get("state") == "gecko_absent"
    )
    assert (output / negative["label_path"]).read_text() == ""
    assert (output / "data.yaml").is_file()


def test_materialize_dataset_refuses_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    output.mkdir()
    with pytest.raises(FileExistsError):
        materialize_dataset(
            final_gt=_human_gt(),
            split_plan={
                "schema": "yolo26n-v261-group-split-plan-v1",
                "status": "V261_GROUP_SPLIT_READY",
                "records": [],
            },
            expected_split_sha256="0" * 64,
            development_sources=_sources(),
            parent_manifest={
                "schema": "yolo26n-owner-dataset-v26",
                "status": "V26_DATASET_READY",
                "records": [],
            },
            protected_image_sha256=set(),
            protected_dhash_by_source={},
            future_clip_refs=set(),
            input_lineage={},
            parent_dataset_root=tmp_path,
            queue_root=tmp_path,
            output_root=output,
            source_commit="b" * 40,
            lineage={},
        )


def test_materialize_rejects_truncated_or_modified_approved_split(
    tmp_path: Path,
) -> None:
    final_gt = _human_gt()
    final_gt["records"] = final_gt["records"][:4]
    sources = _sources()
    sources["records"] = sources["records"][:4]
    parent_root, parent_manifest = _parent_manifest(tmp_path)
    split = build_group_split(
        final_gt=final_gt, development_sources=sources, parent_manifest=parent_manifest
    )
    approved_sha = _object_digest(split)
    split["records"] = split["records"][:-1]

    with pytest.raises(ValueError, match="approved split"):
        materialize_dataset(
            final_gt=final_gt,
            split_plan=split,
            expected_split_sha256=approved_sha,
            development_sources=sources,
            parent_manifest=parent_manifest,
            protected_image_sha256=set(),
            protected_dhash_by_source={},
            future_clip_refs=set(),
            input_lineage={},
            parent_dataset_root=parent_root,
            queue_root=tmp_path / "queue",
            output_root=tmp_path / "dataset",
            source_commit="b" * 40,
            lineage={},
        )


def test_materialize_rejects_source_lineage_drift_after_split_approval(
    tmp_path: Path,
) -> None:
    final_gt = _human_gt()
    final_gt["records"] = final_gt["records"][:4]
    sources = _sources()
    sources["records"] = sources["records"][:4]
    parent_root, parent_manifest = _parent_manifest(tmp_path)
    approved_lineage = {"parent_manifest_sha256": "a" * 64}
    split = build_group_split(
        final_gt=final_gt,
        development_sources=sources,
        parent_manifest=parent_manifest,
        input_lineage=approved_lineage,
    )

    with pytest.raises(ValueError, match="source contract"):
        materialize_dataset(
            final_gt=final_gt,
            split_plan=split,
            expected_split_sha256=_object_digest(split),
            development_sources=sources,
            parent_manifest=parent_manifest,
            protected_image_sha256=set(),
            protected_dhash_by_source={},
            future_clip_refs=set(),
            input_lineage={"parent_manifest_sha256": "b" * 64},
            parent_dataset_root=parent_root,
            queue_root=tmp_path / "queue",
            output_root=tmp_path / "dataset",
            source_commit="b" * 40,
            lineage={},
        )


def test_label_rejects_center_size_box_that_crosses_image_boundary() -> None:
    from scripts.build_yolo26n_v261_dataset import _label_bytes

    with pytest.raises(ValueError, match="normalized YOLO box"):
        _label_bytes([[0, 0.95, 0.5, 0.2, 0.2]])
