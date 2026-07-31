"""검증 완료 exact-120 private manifest를 사건 경계 검수 채널에 원자적으로 준비해."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any


SHA256 = re.compile(r"^[0-9a-f]{64}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)


class SeedError(RuntimeError):
    pass


def load_env_file(path: Path) -> None:
    if not path.is_file():
        raise SeedError("env_file_missing")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SeedError("env_file_invalid")
        key, value = line.split("=", 1)
        if key and key not in os.environ:
            os.environ[key] = value


def build_seed_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") != "rba-event-boundary-manifest-v2":
        raise SeedError("manifest_schema_invalid")
    experiment_id = manifest.get("experiment_id")
    digest = manifest.get("manifest_sha256")
    if not isinstance(experiment_id, str) or not experiment_id.strip() or not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise SeedError("manifest_identity_invalid")
    preflight = manifest.get("media_preflight")
    if not isinstance(preflight, dict) or preflight.get("verified_count") != 240:
        raise SeedError("media_preflight_not_240")
    splits = manifest.get("splits")
    if not isinstance(splits, dict):
        raise SeedError("manifest_splits_invalid")

    pairs: list[dict[str, Any]] = []
    clip_ids: list[str] = []
    pair_digests: set[str] = set()
    for split in ("development", "holdout"):
        rows = splits.get(split)
        if not isinstance(rows, list) or len(rows) != 60:
            raise SeedError("manifest_split_not_60")
        for ordinal, raw in enumerate(rows, 1):
            if not isinstance(raw, dict):
                raise SeedError("manifest_pair_invalid")
            left = raw.get("left_clip_id")
            right = raw.get("right_clip_id")
            pair_digest = raw.get("pair_id")
            gap_sec = raw.get("gap_sec")
            gap_bin = raw.get("gap_bin")
            if (
                not isinstance(left, str) or not UUID.fullmatch(left)
                or not isinstance(right, str) or not UUID.fullmatch(right) or left == right
                or not isinstance(pair_digest, str) or not SHA256.fullmatch(pair_digest)
                or pair_digest in pair_digests
                or isinstance(gap_sec, bool) or not isinstance(gap_sec, (int, float)) or gap_sec < 0
                or gap_bin not in {"le30", "30to60", "60to300"}
            ):
                raise SeedError("manifest_pair_invalid")
            pair_digests.add(pair_digest)
            clip_ids.extend((left, right))
            pairs.append({
                "split": split,
                "ordinal": ordinal,
                "left_clip_id": left,
                "right_clip_id": right,
                "gap_sec": float(gap_sec),
                "gap_bin": gap_bin,
                "pair_digest": pair_digest,
            })
    if len(set(clip_ids)) != 240:
        raise SeedError("manifest_clip_reuse")
    payload_digest = hashlib.sha256(
        json.dumps(pairs, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "experiment_id": experiment_id,
        "manifest_digest": digest,
        "pairs": pairs,
        "payload_digest": payload_digest,
    }


def resolve_reviewers(client: Any, owner_email: str, peer_email: str) -> tuple[str, str]:
    response = (
        client.table("labeler_applications")
        .select("user_id,email,status")
        .in_("email", [owner_email, peer_email])
        .execute()
    )
    rows = response.data or []
    by_email: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_email.setdefault(str(row.get("email", "")).lower(), []).append(row)
    resolved: list[str] = []
    for email in (owner_email, peer_email):
        matches = by_email.get(email.lower(), [])
        if len(matches) != 1 or not UUID.fullmatch(str(matches[0].get("user_id", ""))):
            raise SeedError("reviewer_identity_not_exact")
        resolved.append(str(matches[0]["user_id"]))
    owner_id, peer_id = resolved
    if owner_id == peer_id:
        raise SeedError("reviewers_must_differ")
    peer_rows = (
        client.table("labelers").select("user_id").eq("user_id", peer_id).limit(1).execute().data or []
    )
    if len(peer_rows) != 1:
        raise SeedError("peer_not_active_labeler")
    configured_owner = os.environ.get("DEV_USER_ID")
    if configured_owner and configured_owner != owner_id:
        raise SeedError("owner_identity_mismatch")
    return owner_id, peer_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--peer-email", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    path = args.artifact / "boundary-pairs.json" if args.artifact.is_dir() else args.artifact
    if not path.is_file():
        raise SeedError("manifest_missing")
    payload = build_seed_payload(json.loads(path.read_text(encoding="utf-8")))

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SeedError("supabase_env_missing")
    from supabase import create_client

    client = create_client(url, key)
    owner_id, peer_id = resolve_reviewers(client, args.owner_email, args.peer_email)
    print(f"SEED_PREFLIGHT_OK pairs={len(payload['pairs'])} clips=240 payload_digest={payload['payload_digest']}")
    if not args.apply:
        print("SEED_DRY_RUN_ONLY writes=0")
        return 0
    result = client.rpc("fn_seed_rba_boundary_review", {
        "p_experiment_id": payload["experiment_id"],
        "p_manifest_digest": payload["manifest_digest"],
        "p_created_by": owner_id,
        "p_owner_id": owner_id,
        "p_peer_id": peer_id,
        "p_pairs": payload["pairs"],
    }).execute().data
    if not isinstance(result, dict) or result.get("pair_count") != 120 or result.get("assignment_count") != 240:
        raise SeedError("seed_result_invalid")
    print(f"SEED_APPLIED_OK pairs=120 assignments=240 status={result.get('status')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, SeedError) as exc:
        print(f"RBA_BOUNDARY_SEED_FAILED type={type(exc).__name__} code={exc}", file=sys.stderr)
        raise SystemExit(2) from exc
