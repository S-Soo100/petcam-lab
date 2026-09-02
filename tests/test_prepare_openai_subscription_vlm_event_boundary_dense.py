import hashlib
import json
from pathlib import Path

import pytest

from scripts.prepare_openai_subscription_vlm_event_boundary_dense import (
    gap_seconds_by_digest,
    load_cached_media,
)
from scripts.run_local_vlm_event_boundary import MappedPair, _token


def test_load_cached_media_joins_clip_tokens_and_verifies_hash(tmp_path: Path) -> None:
    salt = b"s" * 32
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    payloads = {"left": b"left-video", "right": b"right-video"}
    media_rows = []
    for clip_id, payload in payloads.items():
        token = _token(salt, "clip", clip_id)
        path = media_dir / f"{token}.mp4"
        path.write_bytes(payload)
        media_rows.append({
            "clip": token,
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    mapped = (
        MappedPair("pair", "digest", "left", "right", "same_event"),
    )

    result = load_cached_media(
        mapped=mapped,
        salt=salt,
        source_media_dir=media_dir,
        source_media_rows=media_rows,
    )

    assert result == {
        "left": media_dir / f"{_token(salt, 'clip', 'left')}.mp4",
        "right": media_dir / f"{_token(salt, 'clip', 'right')}.mp4",
    }


def test_load_cached_media_rejects_hash_drift(tmp_path: Path) -> None:
    salt = b"s" * 32
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    token = _token(salt, "clip", "left")
    (media_dir / f"{token}.mp4").write_bytes(b"changed")
    mapped = (MappedPair("pair", "digest", "left", "left", "same_event"),)

    with pytest.raises(ValueError, match="source_media_hash"):
        load_cached_media(
            mapped=mapped,
            salt=salt,
            source_media_dir=media_dir,
            source_media_rows=[{
                "clip": token,
                "size": 8,
                "sha256": hashlib.sha256(b"expected").hexdigest(),
            }],
        )


def test_gap_seconds_by_digest_is_exact_and_fail_closed() -> None:
    rows = [
        {"pair_digest": "a", "gap_sec": 38.2},
        {"pair_digest": "b", "gap_sec": 1},
    ]
    assert gap_seconds_by_digest(rows) == {"a": 38.2, "b": 1.0}

    with pytest.raises(ValueError, match="gap_mapping"):
        gap_seconds_by_digest(rows + [{"pair_digest": "a", "gap_sec": 2.0}])
    with pytest.raises(ValueError, match="gap_mapping"):
        gap_seconds_by_digest([{"pair_digest": "a", "gap_sec": -1}])
