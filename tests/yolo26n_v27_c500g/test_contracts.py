from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from backend.rap_c500g_manifest import read_manifest
from backend.rap_c500g_repository import manifest_to_row
from scripts.yolo26n_v27_c500g.contracts import (
    Box,
    CalibrationProvenance,
    DatasetRecord,
    FrameRequest,
    HumanBox,
    PredictionRow,
    ProtectedLedger,
    ProtectedRole,
    ReviewStatus,
    ReviewItem,
    Role,
    RoiProfile,
    RoiRect,
    SourceRecord,
    TeacherFreeze,
    strict_object,
)
from tests.yolo26n_v27_c500g.factories import (
    ZERO_WRITES,
    contract,
    dataset_with_cross_role_night,
    human_gt,
    inputs_with_mutated_replay,
    inputs_with_uncertain_sibling,
    inventory_7days,
    lineage,
    pilot_gt,
    prediction_rows,
    protected_ledgers,
    queue,
    request,
    roles,
    roi_profile,
    valid_source,
    valid_v26_freeze,
)


def test_current_role_contract_has_only_four_assignable_values():
    assert {role.value for role in Role} == {
        "v26_holdout",
        "v26_holdout_date_guard",
        "v27_train",
        "v27_val",
    }


def test_calibration_provenance_is_not_a_current_dataset_role():
    assert {value.value for value in CalibrationProvenance} == {
        "v27_train",
        "pre_study_calibration",
    }
    profile = RoiProfile.from_json(roi_profile())
    assert profile.calibration_provenance is CalibrationProvenance.V27_TRAIN
    assert not hasattr(profile, "calibration_source_role")


def test_future_holdout_is_external_protected_role_not_current_role():
    ledger = ProtectedLedger.from_json(protected_ledgers()[0])
    assert ledger.role is ProtectedRole.V27_FUTURE_HOLDOUT
    assert ledger.source_sha256 == ("b" * 64,)
    with pytest.raises(ValueError):
        Role("v27_future_holdout")


def test_direct_protected_ledger_freezes_source_digest_sequence():
    payload = protected_ledgers()[0]
    digests = payload["source_sha256"]
    ledger = ProtectedLedger(**payload)  # type: ignore[arg-type]
    digests.append("c" * 64)  # type: ignore[union-attr]
    assert ledger.source_sha256 == ("b" * 64,)


def test_fake_bundle_mirrors_complete_existing_manifest_shape(fake_bundle):
    manifest = read_manifest(fake_bundle.manifest)
    row = manifest_to_row(manifest)
    assert [item["name"] for item in manifest["artifacts"]] == [
        "video.mp4",
        "thumbnail.jpg",
        "ffmpeg.sanitized.log",
    ]
    assert row["video_sha256"] == (
        "46f2d6cb96762e9f704f549ab0d8a1b7"
        "62c83ed1d0814f7c5743aa6a126b4870"
    )


def test_review_status_contract_has_only_human_outcomes():
    assert {status.value for status in ReviewStatus} == {
        "present",
        "absent",
        "uncertain",
        "media_error",
    }


def test_source_record_rejects_unknown_role():
    with pytest.raises(ValueError, match="role"):
        SourceRecord.from_json({**valid_source(), "role": "test"})


def test_source_record_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown keys"):
        SourceRecord.from_json({**valid_source(), "prediction": "must-not-pass"})


def test_source_record_is_deeply_immutable_at_its_public_boundary():
    record = SourceRecord.from_json(valid_source())
    with pytest.raises(FrozenInstanceError):
        record.role = Role.V27_VAL  # type: ignore[misc]


def test_direct_source_and_frame_request_use_same_validation_as_from_json():
    source = SourceRecord(**valid_source())  # type: ignore[arg-type]
    frame_request = FrameRequest(**request())  # type: ignore[arg-type]
    assert source.role is Role.V27_TRAIN
    assert frame_request.role is Role.V27_TRAIN

    with pytest.raises(ValueError, match="role"):
        SourceRecord(**valid_source(role="future"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="role"):
        FrameRequest(**request(role="future"))  # type: ignore[arg-type]


def test_roi_profile_parses_nested_rects_into_immutable_contracts():
    profile = RoiProfile.from_json(roi_profile())
    assert profile.cameras["cam-digest-01"]["left"] == RoiRect(
        0.02, 0.05, 0.31, 0.95
    )
    with pytest.raises(TypeError):
        profile.cameras["cam-digest-01"]["left"] = RoiRect(0.0, 0.0, 0.1, 0.1)  # type: ignore[index]
    assert profile.to_json()["service_write_count"] == 0


def test_direct_roi_profile_freezes_nested_caller_mapping():
    payload = roi_profile()
    cameras = payload["cameras"]
    profile = RoiProfile(**payload)  # type: ignore[arg-type]
    cameras["cam-digest-01"]["left"]["x1"] = 0.20  # type: ignore[index]

    assert profile.cameras["cam-digest-01"]["left"].x1 == 0.02
    with pytest.raises(ValueError, match="frame_width"):
        RoiProfile(**{**roi_profile(), "frame_width": 0})  # type: ignore[arg-type]


def test_frame_request_round_trip_keeps_private_source_identity_and_role():
    frame_request = FrameRequest.from_json(request())
    assert frame_request.role is Role.V27_TRAIN
    assert frame_request.to_json() == request()


def test_review_item_rejects_source_identity_keys_from_anonymous_contract():
    payload = {
        "anonymous_sequence": "V27P0001",
        "image_name": "V27P0001.jpg",
        "image_sha256": "a" * 64,
        "width": 900,
        "height": 1400,
        "source_ref": "must-stay-private",
    }
    with pytest.raises(ValueError, match="unknown keys"):
        ReviewItem.from_json(payload)


@pytest.mark.parametrize("sequence", ["cam01", "bundle-1234", "a/b", "V27p0001", "V27P001"])
def test_review_item_rejects_source_derived_or_malformed_sequence(sequence):
    with pytest.raises(ValueError, match="anonymous_sequence"):
        ReviewItem(
            anonymous_sequence=sequence,
            image_name=f"{sequence}.jpg",
            image_sha256="a" * 64,
            width=900,
            height=1400,
        )


@pytest.mark.parametrize("sequence", ["V27P0001", "V27W0001", "V27T12345"])
def test_review_item_accepts_anonymous_queue_sequence_and_matching_jpg(sequence):
    item = ReviewItem(
        anonymous_sequence=sequence,
        image_name=f"{sequence}.jpg",
        image_sha256="a" * 64,
        width=900,
        height=1400,
    )
    assert item.image_name == f"{sequence}.jpg"


def test_review_item_requires_image_name_to_match_sequence():
    with pytest.raises(ValueError, match="image_name"):
        ReviewItem(
            anonymous_sequence="V27P0001",
            image_name="V27P0002.jpg",
            image_sha256="a" * 64,
            width=900,
            height=1400,
        )


def test_human_box_requires_manual_gecko_rectangle():
    parsed = HumanBox.from_json(
        {
            "anonymous_sequence": "V27P0001",
            "label": "gecko",
            "source": "manual",
            "box": {"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0},
        }
    )
    assert parsed.box == Box(1.0, 2.0, 3.0, 4.0)
    with pytest.raises(ValueError, match="manual"):
        HumanBox.from_json(
            {
                "anonymous_sequence": "V27P0001",
                "label": "gecko",
                "source": "prediction",
                "box": {"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0},
            }
        )


def test_direct_human_box_normalizes_box_and_rejects_prediction_source():
    raw_box = {"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0}
    human_box = HumanBox("V27P0001", raw_box)  # type: ignore[arg-type]
    raw_box["x1"] = 99.0
    assert human_box.box == Box(1.0, 2.0, 3.0, 4.0)

    with pytest.raises(ValueError, match="manual"):
        HumanBox("V27P0001", Box(1, 2, 3, 4), source="prediction")


def test_teacher_freeze_round_trip_preserves_six_run_tuple_and_zero_writes():
    freeze = TeacherFreeze.from_json(valid_v26_freeze())
    assert len(freeze.runs) == 6
    assert freeze.to_json() == valid_v26_freeze()


def test_direct_teacher_freeze_freezes_nested_run_sequence():
    payload = valid_v26_freeze()
    runs = payload["runs"]
    freeze = TeacherFreeze(**payload)  # type: ignore[arg-type]
    runs[0]["status"] = "mutated"  # type: ignore[index]

    assert isinstance(freeze.runs, tuple)
    assert freeze.runs[0]["status"] == "completed"
    with pytest.raises(TypeError):
        freeze.runs[0]["status"] = "mutated"  # type: ignore[index]


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"db_write_count": 1}, "db_write_count"),
        ({"test_sheet_sha256": "g" * 64}, "test_sheet_sha256"),
    ],
)
def test_schema_root_dataclass_rejects_direct_invalid_replacement(changes, field):
    freeze = TeacherFreeze.from_json(valid_v26_freeze())
    with pytest.raises(ValueError, match=field):
        replace(freeze, **changes)


def test_prediction_row_and_dataset_record_keep_boxes_as_immutable_tuples():
    prediction = PredictionRow.from_json(prediction_rows()[0])
    dataset = DatasetRecord.from_json(
        {
            "sequence": "V27P0001",
            "image_path": "images/V27P0001.jpg",
            "image_sha256": "a" * 64,
            "width": 900,
            "height": 1400,
            "boxes": [{"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0}],
            "camera_night": "night-2026-08-20-a",
            "role": "v27_train",
            "provenance": "c500g-prospective",
        }
    )
    assert prediction.box == Box(10.0, 20.0, 110.0, 120.0)
    assert dataset.boxes == (Box(1.0, 2.0, 3.0, 4.0),)


def test_direct_prediction_and_dataset_use_same_validation_and_freeze_boxes():
    prediction = PredictionRow(**prediction_rows()[0])  # type: ignore[arg-type]
    boxes = [{"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0}]
    dataset = DatasetRecord(
        sequence="V27P0001",
        image_path="images/V27P0001.jpg",
        image_sha256="a" * 64,
        width=900,
        height=1400,
        boxes=boxes,  # type: ignore[arg-type]
        camera_night="night-2026-08-20-a",
        role="v27_train",  # type: ignore[arg-type]
        provenance="c500g-prospective",
    )
    boxes[0]["x1"] = 99.0
    boxes.append({"x1": 5.0, "y1": 6.0, "x2": 7.0, "y2": 8.0})

    assert prediction.role is Role.V27_TRAIN
    assert prediction.box == Box(10.0, 20.0, 110.0, 120.0)
    assert dataset.role is Role.V27_TRAIN
    assert dataset.boxes == (Box(1.0, 2.0, 3.0, 4.0),)

    with pytest.raises(ValueError, match="confidence"):
        PredictionRow(**{**prediction_rows()[0], "confidence": 1.1})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="image_path"):
        DatasetRecord(
            sequence="V27P0001",
            image_path="../escape.jpg",
            image_sha256="a" * 64,
            width=900,
            height=1400,
            boxes=(),
            camera_night="night-2026-08-20-a",
            role=Role.V27_TRAIN,
            provenance="c500g-prospective",
        )


@pytest.mark.parametrize(
    "coordinates",
    [
        (1.0, 1.0, 1.0, 2.0),
        (1.0, 1.0, 2.0, 1.0),
        (float("nan"), 1.0, 2.0, 2.0),
    ],
)
def test_box_rejects_nonpositive_or_nonfinite_geometry(coordinates):
    with pytest.raises(ValueError, match="box"):
        Box(*coordinates)


def test_schema_root_requires_all_four_zero_write_literals():
    valid = {
        "schema": "root-v1",
        "status": "READY",
        "test_sheet_sha256": "a" * 64,
        **ZERO_WRITES,
    }
    assert strict_object(
        valid,
        required={"schema", "status", "test_sheet_sha256"},
        optional=set(),
    )["git_write_count"] == 0

    for field in ZERO_WRITES:
        missing = dict(valid)
        missing.pop(field)
        with pytest.raises(ValueError, match=field):
            strict_object(
                missing,
                required={"schema", "status", "test_sheet_sha256"},
                optional=set(),
            )


@pytest.mark.parametrize("bad_value", [1, -1, False, 0.0, "0", None])
def test_schema_root_rejects_nonzero_or_nonliteral_write_counts(bad_value):
    payload = {
        "schema": "root-v1",
        "status": "READY",
        "test_sheet_sha256": "a" * 64,
        **ZERO_WRITES,
        "db_write_count": bad_value,
    }
    with pytest.raises(ValueError, match="db_write_count"):
        strict_object(
            payload,
            required={"schema", "status", "test_sheet_sha256"},
            optional=set(),
        )


@pytest.mark.parametrize("bad_sha", ["a" * 63, "a" * 65, "g" * 64, "A" * 64, 64])
def test_test_sheet_pin_requires_exact_lowercase_whole_file_sha256(bad_sha):
    payload = {
        "schema": "root-v1",
        "status": "READY",
        "test_sheet_sha256": bad_sha,
        **ZERO_WRITES,
    }
    with pytest.raises(ValueError, match="test_sheet_sha256"):
        strict_object(
            payload,
            required={"schema", "status", "test_sheet_sha256"},
            optional=set(),
        )


def test_all_factory_builders_expose_strict_synthetic_contract_shapes(tmp_path):
    source = SourceRecord.from_json(valid_source())
    inventory = strict_object(
        inventory_7days(),
        {"schema", "status", "test_sheet_sha256", "records"},
    )
    freeze = TeacherFreeze.from_json(valid_v26_freeze())
    role_manifest = strict_object(
        roles(), {"schema", "status", "test_sheet_sha256", "rows"}
    )
    profile = RoiProfile.from_json(roi_profile())
    frame_request = FrameRequest.from_json(request())
    pilot = strict_object(
        pilot_gt(),
        {
            "schema",
            "status",
            "test_sheet_sha256",
            "roi_profile_sha256",
            "fraction_full_frame_short_side_ge_16px",
            "edge_issue_image_fraction",
            "items",
        },
    )
    cvat_contract = strict_object(
        contract(),
        {
            "schema",
            "status",
            "test_sheet_sha256",
            "queue_sha256",
            "status_labels",
            "rectangle_label",
        },
    )
    review_queue = strict_object(
        queue(), {"schema", "status", "test_sheet_sha256", "items"}
    )
    private_lineage = strict_object(
        lineage(), {"schema", "status", "test_sheet_sha256", "items"}
    )
    gt = strict_object(
        human_gt(), {"schema", "status", "test_sheet_sha256", "items"}
    )
    protected = ProtectedLedger.from_json(protected_ledgers()[0])
    predictions = tuple(PredictionRow.from_json(row) for row in prediction_rows())
    uncertain = strict_object(
        inputs_with_uncertain_sibling(),
        {"schema", "status", "test_sheet_sha256", "items"},
    )
    leaking = strict_object(
        dataset_with_cross_role_night(),
        {"schema", "status", "test_sheet_sha256", "records"},
    )
    mutated = inputs_with_mutated_replay(tmp_path)

    assert source.source_ref.startswith("private/")
    assert len(inventory["records"]) == 21
    assert len(freeze.runs) == 6
    assert len(role_manifest["rows"]) == 21
    assert len(profile.cameras) == 3
    assert frame_request.timestamp_ms == 60_000
    assert pilot["fraction_full_frame_short_side_ge_16px"] == 0.95
    assert cvat_contract["rectangle_label"] == "gecko"
    assert ReviewItem.from_json(review_queue["items"][0]).anonymous_sequence == "V27P0001"  # type: ignore[index]
    assert private_lineage["items"][0]["source_ref"].startswith("private/")  # type: ignore[index]
    assert gt["items"][0]["status"] == "present"  # type: ignore[index]
    assert protected.role is ProtectedRole.V27_FUTURE_HOLDOUT
    assert len(predictions) == 1
    assert uncertain["items"][2]["status"] == "uncertain"  # type: ignore[index]
    assert {row["role"] for row in leaking["records"]} == {"v27_train", "v27_val"}  # type: ignore[union-attr]
    assert mutated["actual_image_bytes"] == b"mutated replay bytes"
    assert mutated["expected_image_sha256"] != "0" * 64


def test_all_shared_fixtures_are_synthetic_and_offer_expected_interfaces(
    tmp_path, fake_bundle, fake_r2, fake_db, cli_runner, fake_c500g_tree
):
    listed = fake_r2.list_objects_v2(Bucket="synthetic")
    key = listed["Contents"][0]["Key"]
    headed = fake_r2.head_object(Bucket="synthetic", Key=key)
    selected = fake_db.select("bundle_id,video_sha256").execute()
    cli_result = cli_runner("--definitely-invalid")

    assert fake_bundle.root.is_relative_to(tmp_path)
    assert fake_bundle.video.read_bytes() == b"synthetic-c500g-video"
    assert len(listed["Contents"]) == 3
    assert headed["ContentLength"] > 0
    assert len(selected.data) == 1
    assert fake_r2.write_calls == []
    assert fake_db.write_calls == []
    assert callable(cli_runner)
    assert cli_result.exit_code != 0
    assert isinstance(cli_result.stdout, str)
    assert isinstance(cli_result.stderr, str)
    assert fake_c500g_tree.source == fake_bundle.root
    assert fake_c500g_tree.attempt.is_dir()
    assert fake_c500g_tree.root.is_relative_to(tmp_path)
