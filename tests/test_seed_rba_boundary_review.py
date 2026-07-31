import hashlib

import pytest

from scripts.seed_rba_boundary_review import SeedError, build_seed_payload


def manifest() -> dict:
    rows = []
    for i in range(120):
        def uid(n: int) -> str:
            return f"{n:08x}-0000-4000-8000-{n:012x}"
        rows.append({
            "left_clip_id": uid(i * 2 + 1),
            "right_clip_id": uid(i * 2 + 2),
            "pair_id": hashlib.sha256(f"pair-{i}".encode()).hexdigest(),
            "gap_sec": 30.0,
            "gap_bin": "le30",
        })
    return {
        "schema_version": "rba-event-boundary-manifest-v2",
        "experiment_id": "probe",
        "manifest_sha256": "a" * 64,
        "media_preflight": {"verified_count": 240},
        "splits": {"development": rows[:60], "holdout": rows[60:]},
    }


def test_builds_exact_private_seed_payload() -> None:
    payload = build_seed_payload(manifest())
    assert len(payload["pairs"]) == 120
    assert payload["pairs"][0]["ordinal"] == 1
    assert payload["pairs"][60]["split"] == "holdout"
    assert len(payload["payload_digest"]) == 64


@pytest.mark.parametrize("mutation", ["preflight", "split", "reuse"])
def test_fails_closed_on_invalid_manifest(mutation: str) -> None:
    data = manifest()
    if mutation == "preflight":
        data["media_preflight"]["verified_count"] = 239
    elif mutation == "split":
        data["splits"]["development"].pop()
    else:
        data["splits"]["development"][1]["left_clip_id"] = data["splits"]["development"][0]["left_clip_id"]
    with pytest.raises(SeedError):
        build_seed_payload(data)
