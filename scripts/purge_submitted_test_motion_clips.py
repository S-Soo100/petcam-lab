"""제출된 test motion clip 정확히 4개의 R2 객체를 exact-key로만 정리한다.

기본은 dry-run이다. 이 스크립트는 DB row를 삭제하지 않는다. R2 exact-object 삭제와
사후 부재 확인까지 끝낸 뒤 별도 forward migration이 같은 4개 DB target을 다시 계산·검증해
DB 의존성을 지운다. ID/key/GT/credential은 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


EXPECTED_DEPENDENCIES = {
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
EXECUTE_CONFIRMATION = "DELETE-4-SUBMITTED-TEST-CLIPS"


@dataclass(frozen=True)
class PurgePlan:
    clip_ids: tuple[str, ...]
    object_keys: tuple[str, ...]
    counts: Mapping[str, int]


def validate_dependency_counts(counts: Mapping[str, int]) -> None:
    drift = {
        name: {"expected": expected, "actual": counts.get(name)}
        for name, expected in EXPECTED_DEPENDENCIES.items()
        if counts.get(name) != expected
    }
    if drift:
        raise ValueError(f"dependency drift: {json.dumps(drift, sort_keys=True)}")


def validate_exact_keys(keys: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(key) for key in keys)
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate exact object key")
    for key in normalized:
        if not key or key.endswith("/") or "*" in key or "?" in key:
            raise ValueError("exact object key required")
    return normalized


def delete_exact_objects(
    client: Any,
    *,
    bucket: str,
    keys: Sequence[str],
    execute: bool,
) -> int:
    exact_keys = validate_exact_keys(keys)
    if not execute:
        return 0
    for key in exact_keys:
        # bulk/prefix API를 일부러 쓰지 않는다. 감사 가능한 exact key 한 건씩만 삭제한다.
        client.delete_object(Bucket=bucket, Key=key)
    return len(exact_keys)


def _is_not_found(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return False
    error_detail = response.get("Error")
    if not isinstance(error_detail, Mapping):
        return False
    return str(error_detail.get("Code")) in {"404", "NoSuchKey", "NotFound"}


def exact_object_presence(
    client: Any,
    *,
    bucket: str,
    keys: Sequence[str],
) -> dict[str, int]:
    """Exact key만 HEAD하고 사용자 출력에는 키 대신 집계만 돌려준다."""
    exact_keys = validate_exact_keys(keys)
    present = 0
    absent = 0
    for key in exact_keys:
        try:
            client.head_object(Bucket=bucket, Key=key)
        except Exception as error:
            if not _is_not_found(error):
                raise
            absent += 1
        else:
            present += 1
    return {"present": present, "absent": absent}


def assert_exact_objects_present(
    client: Any,
    *,
    bucket: str,
    keys: Sequence[str],
) -> dict[str, int]:
    result = exact_object_presence(client, bucket=bucket, keys=keys)
    if result["absent"] != 0:
        raise RuntimeError(
            f"R2 exact-object preflight failed: {result['absent']} objects absent"
        )
    return result


def assert_exact_objects_absent(
    client: Any,
    *,
    bucket: str,
    keys: Sequence[str],
) -> dict[str, int]:
    result = exact_object_presence(client, bucket=bucket, keys=keys)
    if result["present"] != 0:
        raise RuntimeError(
            f"R2 exact-object postflight failed: {result['present']} objects remain"
        )
    return result


def _select_by_ids(db: Any, table: str, columns: str, column: str, ids: Sequence[str]) -> list[dict[str, Any]]:
    if not ids:
        return []
    return list(db.table(table).select(columns).in_(column, list(ids)).execute().data or [])


def _submitted_test_clips(db: Any) -> list[dict[str, Any]]:
    test_rows = list(
        db.table("motion_clips")
        .select("id,r2_key,thumbnail_key")
        .eq("clip_purpose", "test")
        .execute()
        .data
        or []
    )
    test_ids = [str(row["id"]) for row in test_rows]
    submitted: list[dict[str, Any]] = []
    for offset in range(0, len(test_ids), 100):
        submitted.extend(
            _select_by_ids(
                db,
                "motion_clip_blind_submissions",
                "clip_id",
                "clip_id",
                test_ids[offset : offset + 100],
            )
        )
    target_ids = {str(row["clip_id"]) for row in submitted}
    return [row for row in test_rows if str(row["id"]) in target_ids]


def build_purge_plan(db: Any) -> PurgePlan:
    clips = _submitted_test_clips(db)
    clip_ids = tuple(sorted(str(row["id"]) for row in clips))

    slots = _select_by_ids(db, "motion_clip_review_slots", "clip_id", "clip_id", clip_ids)
    submissions = _select_by_ids(
        db, "motion_clip_blind_submissions", "clip_id", "clip_id", clip_ids
    )
    consensus = _select_by_ids(db, "motion_clip_consensus", "clip_id", "clip_id", clip_ids)
    jobs = _select_by_ids(db, "gme_jobs", "clip_id", "clip_id", clip_ids)
    runs = _select_by_ids(
        db,
        "gme_runs",
        "clip_id,permanent_artifact_key,debug_artifact_key",
        "clip_id",
        clip_ids,
    )
    favorites = _select_by_ids(db, "clip_favorites", "clip_id", "clip_id", clip_ids)
    behavior_logs = _select_by_ids(db, "behavior_logs", "clip_id", "clip_id", clip_ids)
    behavior_labels = _select_by_ids(db, "behavior_labels", "clip_id", "clip_id", clip_ids)
    camera_clips = _select_by_ids(db, "camera_clips", "id", "id", clip_ids)

    counts = {
        "target_clips": len(clip_ids),
        "review_slots": len(slots),
        "blind_submissions": len(submissions),
        "consensus": len(consensus),
        "gme_jobs": len(jobs),
        "gme_runs": len(runs),
        "clip_favorites": len(favorites),
        "behavior_logs": len(behavior_logs),
        "behavior_labels": len(behavior_labels),
        "camera_clips": len(camera_clips),
    }
    validate_dependency_counts(counts)

    keys: list[str] = []
    for row in clips:
        keys.extend(str(row[name]) for name in ("r2_key", "thumbnail_key") if row.get(name))
    for row in runs:
        keys.extend(
            str(row[name])
            for name in ("permanent_artifact_key", "debug_artifact_key")
            if row.get(name)
        )
    return PurgePlan(
        clip_ids=clip_ids,
        object_keys=validate_exact_keys(keys),
        counts=counts,
    )


def _r2_client_from_env() -> tuple[Any, str]:
    import boto3

    endpoint = os.environ.get("R2_ENDPOINT_URL") or os.environ.get("R2_ENDPOINT")
    access = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket = os.environ.get("R2_BUCKET_NAME") or os.environ.get("R2_BUCKET")
    if not all((endpoint, access, secret, bucket)):
        raise RuntimeError("R2 runtime environment missing")
    return (
        boto3.client(
            "s3",
            endpoint_url=str(endpoint),
            aws_access_key_id=str(access),
            aws_secret_access_key=str(secret),
            region_name="auto",
        ),
        str(bucket),
    )


def _database_from_env() -> Any:
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("Supabase runtime environment missing")
    return create_client(url, key)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-r2", action="store_true", help="exact R2 objects를 실제 삭제")
    parser.add_argument("--confirm", default="", help="execute 확인 문자열")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.execute_r2 and args.confirm != EXECUTE_CONFIRMATION:
        raise SystemExit("execute confirmation mismatch")

    db = _database_from_env()
    plan = build_purge_plan(db)
    r2, bucket = _r2_client_from_env()
    preflight = assert_exact_objects_present(
        r2,
        bucket=bucket,
        keys=plan.object_keys,
    )
    deleted = delete_exact_objects(
        r2,
        bucket=bucket,
        keys=plan.object_keys,
        execute=args.execute_r2,
    )
    postflight = (
        assert_exact_objects_absent(r2, bucket=bucket, keys=plan.object_keys)
        if args.execute_r2
        else None
    )
    print(
        json.dumps(
            {
                "mode": "execute-r2" if args.execute_r2 else "dry-run",
                "dependencies": dict(plan.counts),
                "exact_object_count": len(plan.object_keys),
                "preflight": preflight,
                "deleted_object_count": deleted,
                "postflight": postflight,
                "raw_ids_or_keys_printed": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
