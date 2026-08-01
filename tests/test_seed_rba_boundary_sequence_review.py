from datetime import UTC, date, datetime, timedelta

import pytest

from scripts.prepare_rba_sequence_review import build_sequence_manifest
from scripts.rba_event_grouping_core import AccountedClip
from scripts.seed_rba_boundary_sequence_review import (
    SeedError,
    build_seed_payload,
    preflight_selected_media,
)


def _manifest() -> dict:
    rows = []
    base = datetime(2026, 7, 1, 12, tzinfo=UTC)
    nights = []
    for night_index in range(6):
        camera = f"camera-{night_index % 2}"
        day = date(2026, 7, night_index + 1)
        nights.append((camera, day))
        for clip_index in range(31):
            rows.append(AccountedClip(
                clip_id=f"00000000-0000-4000-8{night_index:03d}-{clip_index:012d}",
                camera_id=camera,
                started_at=base + timedelta(days=night_index, seconds=clip_index * 40),
                activity_day_kst=day,
                duration_sec=30.0,
                kind="activity_candidate",
                reason_code=None,
            ))
    manifest = build_sequence_manifest(
        accounted=rows,
        development_nights=tuple(nights),
        source_snapshot_sha256="a" * 64,
        blocked_set_sha256="b" * 64,
        seed="test-seed",
    )
    manifest["media_preflight"] = {
        "verified_count": manifest["unique_clip_count"],
        "passes": ["c" * 64, "d" * 64],
    }
    return manifest


def test_builds_exact120_overlapping_seed_payload_after_two_preflights() -> None:
    payload = build_seed_payload(_manifest())
    assert len(payload["pairs"]) == 120
    assert payload["pairs"][0]["split"] == "development"
    clip_ids = {
        clip_id
        for row in payload["pairs"]
        for clip_id in (row["left_clip_id"], row["right_clip_id"])
    }
    assert len(clip_ids) == 126
    assert payload["pairs"][0]["right_clip_id"] == payload["pairs"][1]["left_clip_id"]


def test_seed_fails_closed_without_second_media_preflight() -> None:
    manifest = _manifest()
    manifest["media_preflight"]["passes"].pop()
    with pytest.raises(SeedError, match="media_preflight_not_twice"):
        build_seed_payload(manifest)


class HeadClient:
    def head_object(self, *, Bucket: str, Key: str) -> dict:
        assert Bucket == "bucket"
        return {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "ContentLength": len(Key),
            "ETag": f'"{Key}"',
        }


def test_media_preflight_checks_each_unique_clip_without_exposing_keys() -> None:
    ids = ("a", "b", "c")
    result = preflight_selected_media(
        ids,
        r2_keys_by_clip={clip_id: f"private/{clip_id}.mp4" for clip_id in ids},
        client=HeadClient(),
        bucket="bucket",
        salt=b"test-salt",
    )
    assert result["verified_count"] == 3
    assert len(result["attestation_sha256"]) == 64
    assert "private/" not in str(result)
