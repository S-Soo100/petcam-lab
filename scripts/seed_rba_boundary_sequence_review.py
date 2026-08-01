"""사건 이어짐 v2 private manifest를 검증하고 원자 seed payload를 만들어."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from botocore.exceptions import ClientError

from scripts.prepare_rba_sequence_review import manifest_from_base_artifact
from scripts.seed_rba_boundary_review import load_env_file, resolve_reviewers


SHA256 = re.compile(r"^[0-9a-f]{64}$")
UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)


class SeedError(RuntimeError):
    pass


def preflight_selected_media(
    selected_clip_ids: Sequence[str],
    *,
    r2_keys_by_clip: Mapping[str, str],
    client: object,
    bucket: str,
    salt: bytes,
) -> dict[str, object]:
    ordered = tuple(selected_clip_ids)
    if (
        not ordered
        or len(ordered) != len(set(ordered))
        or set(r2_keys_by_clip) != set(ordered)
        or any(not r2_keys_by_clip[clip_id].strip() for clip_id in ordered)
        or not bucket
        or not salt
    ):
        raise SeedError("media_preflight_input_invalid")
    attestations: list[str] = []
    for clip_id in ordered:
        try:
            response = client.head_object(  # type: ignore[attr-defined]
                Bucket=bucket,
                Key=r2_keys_by_clip[clip_id],
            )
        except ClientError as exc:
            raise SeedError("media_preflight_head_failed") from exc
        metadata = response.get("ResponseMetadata", {})
        status = metadata.get("HTTPStatusCode")
        size = response.get("ContentLength")
        etag = response.get("ETag")
        if (
            status != 200
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or not isinstance(etag, str)
            or not etag.strip()
        ):
            raise SeedError("media_preflight_response_invalid")
        attestations.append(hashlib.sha256(
            salt
            + b"\0"
            + clip_id.encode()
            + b"\0"
            + str(size).encode()
            + b"\0"
            + etag.encode()
        ).hexdigest())
    digest = hashlib.sha256(
        "\n".join(sorted(attestations)).encode()
    ).hexdigest()
    return {"verified_count": len(ordered), "attestation_sha256": digest}


def build_seed_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") != "rba-event-sequence-review-manifest-v2":
        raise SeedError("manifest_schema_invalid")
    experiment_id = manifest.get("experiment_id")
    digest = manifest.get("manifest_sha256")
    if (
        experiment_id != "rba-event-sequence-review-v2"
        or not isinstance(digest, str)
        or not SHA256.fullmatch(digest)
    ):
        raise SeedError("manifest_identity_invalid")
    unique_clip_count = manifest.get("unique_clip_count")
    preflight = manifest.get("media_preflight")
    if not isinstance(unique_clip_count, int) or unique_clip_count <= 0:
        raise SeedError("unique_clip_count_invalid")
    if (
        not isinstance(preflight, dict)
        or preflight.get("verified_count") != unique_clip_count
        or not isinstance(preflight.get("passes"), list)
        or len(preflight["passes"]) != 2
        or any(not isinstance(item, str) or not SHA256.fullmatch(item) for item in preflight["passes"])
    ):
        raise SeedError("media_preflight_not_twice")
    raw_pairs = manifest.get("pairs")
    if not isinstance(raw_pairs, list) or len(raw_pairs) != 120:
        raise SeedError("manifest_exact120_required")

    pairs: list[dict[str, object]] = []
    clip_ids: set[str] = set()
    previous_by_run: dict[int, str] = {}
    for ordinal, raw in enumerate(raw_pairs, 1):
        if not isinstance(raw, dict):
            raise SeedError("manifest_pair_invalid")
        left = raw.get("left_clip_id")
        right = raw.get("right_clip_id")
        run_ordinal = raw.get("run_ordinal")
        gap_sec = raw.get("gap_sec")
        gap_bin = raw.get("gap_bin")
        pair_digest = raw.get("pair_digest")
        if (
            raw.get("split") != "development"
            or raw.get("ordinal") != ordinal
            or not isinstance(run_ordinal, int)
            or run_ordinal < 1
            or not isinstance(left, str)
            or not UUID.fullmatch(left)
            or not isinstance(right, str)
            or not UUID.fullmatch(right)
            or left == right
            or isinstance(gap_sec, bool)
            or not isinstance(gap_sec, (int, float))
            or gap_sec < 0
            or gap_bin not in {"le30", "30to60", "60to300"}
            or not isinstance(pair_digest, str)
            or not SHA256.fullmatch(pair_digest)
        ):
            raise SeedError("manifest_pair_invalid")
        previous_right = previous_by_run.get(run_ordinal)
        if previous_right is not None and previous_right != left:
            raise SeedError("manifest_run_not_contiguous")
        previous_by_run[run_ordinal] = right
        clip_ids.update((left, right))
        pairs.append({
            "split": "development",
            "ordinal": ordinal,
            "left_clip_id": left,
            "right_clip_id": right,
            "gap_sec": float(gap_sec),
            "gap_bin": gap_bin,
            "pair_digest": pair_digest,
        })
    if len(clip_ids) != unique_clip_count or len(previous_by_run) < 6:
        raise SeedError("manifest_run_inventory_invalid")
    payload_digest = hashlib.sha256(
        json.dumps(pairs, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "experiment_id": experiment_id,
        "manifest_digest": digest,
        "pairs": pairs,
        "unique_clip_ids": tuple(sorted(clip_ids)),
        "payload_digest": payload_digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, action="append", default=[])
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--peer-email", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    for env_file in args.env_file:
        load_env_file(env_file)
    base_path = (
        args.base_artifact / "boundary-pairs.json"
        if args.base_artifact.is_dir()
        else args.base_artifact
    )
    if not base_path.is_file():
        raise SeedError("base_artifact_missing")
    base = json.loads(base_path.read_text(encoding="utf-8"))
    manifest = manifest_from_base_artifact(base)
    raw_pairs = manifest["pairs"]
    if not isinstance(raw_pairs, list):
        raise SeedError("manifest_pairs_invalid")
    clip_ids = sorted({
        str(clip_id)
        for row in raw_pairs
        for clip_id in (row["left_clip_id"], row["right_clip_id"])
    })

    supabase_url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    endpoint = os.environ.get("R2_ENDPOINT_URL") or os.environ.get("R2_ENDPOINT")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket = os.environ.get("R2_BUCKET_NAME") or os.environ.get("R2_BUCKET")
    if not all((supabase_url, service_key, endpoint, access_key, secret_key, bucket)):
        raise SeedError("runtime_env_missing")

    from supabase import create_client
    import boto3

    db = create_client(str(supabase_url), str(service_key))
    media_rows = (
        db.table("motion_clips")
        .select("id,r2_key")
        .in_("id", clip_ids)
        .execute()
        .data or []
    )
    keys = {
        str(row.get("id")): str(row.get("r2_key"))
        for row in media_rows
        if row.get("id") and row.get("r2_key")
    }
    if set(keys) != set(clip_ids):
        raise SeedError("selected_media_mapping_incomplete")
    blocked = (
        db.table("motion_clip_system_exclusions")
        .select("clip_id,state")
        .in_("clip_id", clip_ids)
        .in_("state", ["quarantined", "media_deleted"])
        .execute()
        .data or []
    )
    if blocked:
        raise SeedError("selected_media_now_excluded")

    r2 = boto3.client(
        "s3",
        endpoint_url=str(endpoint),
        aws_access_key_id=str(access_key),
        aws_secret_access_key=str(secret_key),
        region_name="auto",
    )
    first = preflight_selected_media(
        clip_ids,
        r2_keys_by_clip=keys,
        client=r2,
        bucket=str(bucket),
        salt=os.urandom(32),
    )
    owner_id, peer_id = resolve_reviewers(
        db,
        args.owner_email,
        args.peer_email,
    )
    # 1차 HEAD 뒤 identity/DB read preflight를 마치고, 실제 seed 직전에
    # 같은 고정 clip 집합을 다시 HEAD 해 시간적으로 분리된 이중 검사를 보장해.
    second = preflight_selected_media(
        clip_ids,
        r2_keys_by_clip=keys,
        client=r2,
        bucket=str(bucket),
        salt=os.urandom(32),
    )
    manifest["media_preflight"] = {
        "verified_count": len(clip_ids),
        "passes": [first["attestation_sha256"], second["attestation_sha256"]],
    }
    payload = build_seed_payload(manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "SEQUENCE_PREFLIGHT_OK "
        f"pairs=120 unique_clips={len(clip_ids)} media_passes=2 "
        f"payload_digest={payload['payload_digest']}"
    )
    if not args.apply:
        print("SEQUENCE_DRY_RUN_ONLY writes=artifact_only")
        return 0

    old_rows = (
        db.table("rba_boundary_review_cohorts")
        .select("status")
        .eq("experiment_id", "rba-event-grouping-shadow-v2")
        .limit(1)
        .execute()
        .data or []
    )
    if len(old_rows) != 1:
        raise SeedError("old_cohort_not_exact")
    old_status = str(old_rows[0].get("status"))
    if old_status == "development_open":
        invalidated = db.rpc("fn_invalidate_rba_boundary_review_v1", {
            "p_owner_id": owner_id,
            "p_experiment_id": "rba-event-grouping-shadow-v2",
            "p_reason": "게코 가시성 자격 검사 누락과 독립 pair 표본으로 연구 목적 불충족",
        }).execute().data
        if not isinstance(invalidated, dict) or invalidated.get("status") != "invalid_eligibility":
            raise SeedError("old_cohort_invalidation_failed")
        print(
            "OLD_COHORT_INVALIDATED_OK "
            f"pairs={invalidated.get('pair_count')} submissions={invalidated.get('submission_count')} "
            f"resolutions={invalidated.get('resolution_count')}"
        )
    elif old_status != "invalid_eligibility":
        raise SeedError("old_cohort_unexpected_status")

    result = db.rpc("fn_seed_rba_boundary_sequence_review_v2", {
        "p_experiment_id": payload["experiment_id"],
        "p_manifest_digest": payload["manifest_digest"],
        "p_created_by": owner_id,
        "p_owner_id": owner_id,
        "p_peer_id": peer_id,
        "p_pairs": payload["pairs"],
    }).execute().data
    if (
        not isinstance(result, dict)
        or result.get("status") != "eligibility_open"
        or result.get("pair_count") != 120
        or result.get("assignment_count") != 0
    ):
        raise SeedError("sequence_seed_result_invalid")
    print("SEQUENCE_SEED_APPLIED_OK pairs=120 eligibility=0 assignments=0 status=eligibility_open")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ClientError, OSError, ValueError, SeedError) as exc:
        print(
            f"RBA_SEQUENCE_SEED_FAILED type={type(exc).__name__} code={exc}",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
