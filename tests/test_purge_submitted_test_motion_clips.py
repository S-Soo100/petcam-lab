from __future__ import annotations

import pytest

from scripts.purge_submitted_test_motion_clips import (
    EXPECTED_DEPENDENCIES,
    assert_exact_objects_absent,
    assert_exact_objects_present,
    delete_exact_objects,
    exact_object_presence,
    validate_dependency_counts,
    validate_exact_keys,
)


class FakeR2:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.deleted: list[tuple[str, str]] = []
        self.existing = set(existing or set())

    def head_object(self, *, Bucket: str, Key: str) -> None:
        del Bucket
        if Key not in self.existing:
            raise FakeNotFound()

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.deleted.append((Bucket, Key))
        self.existing.discard(Key)


class FakeNotFound(Exception):
    response = {"Error": {"Code": "404"}}


def test_expected_dependency_contract_is_the_owner_approved_exact_four() -> None:
    assert EXPECTED_DEPENDENCIES == {
        "target_clips": 4,
        "review_slots": 8,
        "blind_submissions": 4,
        "consensus": 4,
        "gme_jobs": 4,
        "gme_runs": 4,
        "clip_favorites": 0,
        "behavior_logs": 0,
        "behavior_labels": 0,
        "camera_clips": 0,
    }


def test_dependency_drift_fails_closed() -> None:
    counts = dict(EXPECTED_DEPENDENCIES)
    counts["blind_submissions"] = 5

    with pytest.raises(ValueError, match="dependency drift"):
        validate_dependency_counts(counts)


def test_exact_keys_reject_prefix_wildcard_and_duplicates() -> None:
    with pytest.raises(ValueError, match="exact object key"):
        validate_exact_keys(["test/camera/day/"])
    with pytest.raises(ValueError, match="exact object key"):
        validate_exact_keys(["test/*"])
    with pytest.raises(ValueError, match="duplicate"):
        validate_exact_keys(["test/a.mp4", "test/a.mp4"])


def test_dry_run_never_calls_r2_delete() -> None:
    client = FakeR2()

    deleted = delete_exact_objects(
        client,
        bucket="petcam-clips",
        keys=["test/a.mp4", "test/a.jpg"],
        execute=False,
    )

    assert deleted == 0
    assert client.deleted == []


def test_execute_deletes_each_exact_key_without_bulk_api() -> None:
    client = FakeR2()

    deleted = delete_exact_objects(
        client,
        bucket="petcam-clips",
        keys=["test/a.mp4", "test/a.jpg"],
        execute=True,
    )

    assert deleted == 2
    assert client.deleted == [
        ("petcam-clips", "test/a.mp4"),
        ("petcam-clips", "test/a.jpg"),
    ]


def test_exact_object_presence_counts_without_returning_keys() -> None:
    client = FakeR2(existing={"test/a.mp4"})

    result = exact_object_presence(
        client,
        bucket="petcam-clips",
        keys=["test/a.mp4", "test/a.jpg"],
    )

    assert result == {"present": 1, "absent": 1}


def test_preflight_fails_before_delete_if_any_expected_object_is_missing() -> None:
    client = FakeR2(existing={"test/a.mp4"})

    with pytest.raises(RuntimeError, match="R2 exact-object preflight failed"):
        assert_exact_objects_present(
            client,
            bucket="petcam-clips",
            keys=["test/a.mp4", "test/a.jpg"],
        )

    assert client.deleted == []


def test_postflight_requires_every_exact_object_to_be_absent() -> None:
    client = FakeR2(existing={"test/a.mp4", "test/a.jpg"})
    keys = ["test/a.mp4", "test/a.jpg"]

    assert_exact_objects_present(client, bucket="petcam-clips", keys=keys)
    delete_exact_objects(client, bucket="petcam-clips", keys=keys, execute=True)
    assert_exact_objects_absent(client, bucket="petcam-clips", keys=keys)

    client.existing.add("test/a.mp4")
    with pytest.raises(RuntimeError, match="R2 exact-object postflight failed"):
        assert_exact_objects_absent(client, bucket="petcam-clips", keys=keys)
