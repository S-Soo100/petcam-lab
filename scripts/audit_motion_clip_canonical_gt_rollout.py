"""Canonical GT source/canonical aggregate와 projection health를 감사해."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from typing import Any

AUDIT_RPC = "fn_audit_motion_clip_canonical_gt"
HEALTH_RPC = "fn_get_motion_clip_gt_projection_health"


def _default_client():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("supabase_environment_missing")
    return create_client(url, key)


def _dict_result(data: Any, code: str) -> dict[str, object]:
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict):
        raise RuntimeError(code)
    return data


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[[], Any] = _default_client,
) -> int:
    parser = argparse.ArgumentParser(description="Audit canonical motion GT rollout")
    parser.add_argument("--expected-source-digest")
    parser.add_argument("--print-source-digest", action="store_true")
    args = parser.parse_args(argv)

    try:
        client = client_factory()
        audit = _dict_result(
            client.rpc(AUDIT_RPC, {}).execute().data,
            "canonical_audit_response_invalid",
        )
        health = _dict_result(
            client.rpc(HEALTH_RPC, {}).execute().data,
            "canonical_health_response_invalid",
        )
        required = {
            "source_counts",
            "canonical_counts",
            "excluded_counts",
            "overlap_count",
            "reconciliation_pending",
            "orphan_head_count",
            "source_mutation_digest",
            "workflow_observation_digest",
            "parity_mismatch_count",
        }
        if not required.issubset(audit):
            raise RuntimeError("canonical_audit_response_invalid")
        digest = audit["source_mutation_digest"]
        if not isinstance(digest, str) or not digest:
            raise RuntimeError("canonical_audit_response_invalid")
    except Exception:
        print("CANONICAL_GT_AUDIT_FAILED", file=sys.stderr)
        return 1

    if args.print_source_digest:
        print(digest)
        return 0

    ok = (
        int(audit["orphan_head_count"]) == 0
        and int(audit["parity_mismatch_count"]) == 0
        and (
            args.expected_source_digest is None
            or digest == args.expected_source_digest
        )
    )
    print(
        json.dumps(
            {"ok": ok, "audit": audit, "health": health},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
