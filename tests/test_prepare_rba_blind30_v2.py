"""Formal Blind30 v2 future-pool and R2 media preflight contract."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from scripts.prepare_rba_blind30 import (
    Blind30PreparationError,
    MediaAttestation,
    build_manifest_v2,
    preflight_selected_media,
    select_formal30_v2,
    verify_media_preflight_match,
)
from tests.test_prepare_rba_blind30 import T0, _eligible_pool

V1_T0 = datetime.fromisoformat("2026-07-31T03:44:27.183403+09:00")
V2_T0 = datetime(2026, 8, 5, 0, 0, tzinfo=UTC)
VERIFIED_1 = datetime(2026, 8, 2, 23, 58, tzinfo=UTC)
VERIFIED_2 = datetime(2026, 8, 2, 23, 59, tzinfo=UTC)


class FakeHeadClient:
    def __init__(
        self,
        *,
        overrides: dict[str, dict[str, object] | BaseException] | None = None,
    ) -> None:
        self.overrides = overrides or {}
        self.calls: list[tuple[str, str]] = []

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        self.calls.append((Bucket, Key))
        result = self.overrides.get(Key)
        if isinstance(result, BaseException):
            raise result
        if result is not None:
            return result
        return {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "ContentLength": 1024,
            "ETag": f'"etag-{Key}"',
        }


def _future_pool():
    rows = _eligible_pool()
    shift = datetime(2026, 8, 1, 12, tzinfo=UTC) - min(
        row.started_at for row in rows
    )
    return [replace(row, started_at=row.started_at + shift) for row in rows]


def _keys(rows) -> dict[str, str]:
    return {row.clip_id: f"private/{row.clip_id}.mp4" for row in rows}


def _preflight(rows, client, *, verified_at=VERIFIED_1):
    return preflight_selected_media(
        [row.clip_id for row in rows],
        r2_keys_by_clip=_keys(rows),
        client=client,
        bucket="private-bucket",
        account_id="private-account",
        salt=b"test-only-secret-salt",
        verified_at=verified_at,
    )


def test_v2_uses_future_pool_without_changing_balance_contract() -> None:
    old = _eligible_pool()
    future = _future_pool()

    selected = select_formal30_v2(old + future, t0=V2_T0, not_before=V1_T0)

    assert len(selected) == 30
    assert all(row.started_at >= V1_T0 for row in selected)
    assert len({row.camera_id for row in selected}) >= 2
    assert len({(row.camera_id, row.activity_day_kst) for row in selected}) >= 6


def test_exact_30_head_200_nonzero_with_etag_is_accepted() -> None:
    selected = select_formal30_v2(_future_pool(), t0=V2_T0, not_before=V1_T0)
    client = FakeHeadClient()

    result = _preflight(selected, client)

    assert len(result) == 30
    assert len(client.calls) == 30
    assert all(isinstance(row, MediaAttestation) for row in result.values())
    assert all(row.media_digest_sha256 for row in result.values())


@pytest.mark.parametrize(
    "bad_response",
    (
        {"ResponseMetadata": {"HTTPStatusCode": 404}, "ContentLength": 0, "ETag": ""},
        {"ResponseMetadata": {"HTTPStatusCode": 403}, "ContentLength": 1024, "ETag": '"x"'},
        {"ResponseMetadata": {"HTTPStatusCode": 200}, "ContentLength": 0, "ETag": '"x"'},
        {"ResponseMetadata": {"HTTPStatusCode": 200}, "ContentLength": 1024, "ETag": ""},
        TimeoutError("head timed out"),
    ),
)
def test_any_media_failure_rejects_the_whole_batch_without_partial_result(
    bad_response,
) -> None:
    selected = select_formal30_v2(_future_pool(), t0=V2_T0, not_before=V1_T0)
    keys = _keys(selected)
    failed_key = keys[selected[7].clip_id]
    client = FakeHeadClient(overrides={failed_key: bad_response})

    with pytest.raises(Blind30PreparationError, match="MEDIA_PREFLIGHT_FAILED"):
        _preflight(selected, client)


def test_preflight_requires_exact_30_and_exact_key_projection() -> None:
    selected = select_formal30_v2(_future_pool(), t0=V2_T0, not_before=V1_T0)
    keys = _keys(selected)
    keys.pop(selected[-1].clip_id)

    with pytest.raises(Blind30PreparationError, match="MEDIA_PREFLIGHT_REQUIRES_EXACT_30"):
        preflight_selected_media(
            [row.clip_id for row in selected],
            r2_keys_by_clip=keys,
            client=FakeHeadClient(),
            bucket="bucket",
            account_id="account",
            salt=b"salt",
            verified_at=VERIFIED_1,
        )


def test_second_preflight_must_match_first_digest_and_clip_set() -> None:
    selected = select_formal30_v2(_future_pool(), t0=V2_T0, not_before=V1_T0)
    first = _preflight(selected, FakeHeadClient())
    second = _preflight(
        selected,
        FakeHeadClient(
            overrides={
                _keys(selected)[selected[0].clip_id]: {
                    "ResponseMetadata": {"HTTPStatusCode": 200},
                    "ContentLength": 2048,
                    "ETag": '"changed"',
                }
            }
        ),
        verified_at=VERIFIED_2,
    )

    with pytest.raises(Blind30PreparationError, match="MEDIA_PREFLIGHT_CHANGED"):
        verify_media_preflight_match(
            first,
            second,
            expected_clip_ids=[row.clip_id for row in selected],
        )


def test_v2_manifest_contains_only_salted_media_attestation() -> None:
    selected = select_formal30_v2(_future_pool(), t0=V2_T0, not_before=V1_T0)
    attestation = _preflight(selected, FakeHeadClient())

    manifest = build_manifest_v2(
        selected,
        t0=V2_T0,
        not_before=V1_T0,
        reviewer_fingerprints=("aaaaaaaaaaaa", "bbbbbbbbbbbb"),
        media_attestations=attestation,
    )

    raw = json.dumps(manifest, sort_keys=True)
    assert len(manifest["clips"]) == 30
    assert all("media_preflight" in clip for clip in manifest["clips"])
    for forbidden in (
        "r2_key",
        "private/",
        "private-bucket",
        "private-account",
        '"etag-',
        "credential",
        "signed_url",
    ):
        assert forbidden not in raw
