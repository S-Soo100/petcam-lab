"""Canonical motion GT projection을 dry-run 기본으로 실행해."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any
from uuid import UUID, uuid4


PROJECT_RPC = "fn_project_motion_clip_canonical_gt"
RECORD_RPC = "fn_record_motion_clip_gt_projection_run"


@dataclass(frozen=True, slots=True)
class ProjectionOptions:
    apply: bool
    run_id: UUID
    limit: int = 500
    after_source_id: UUID | None = None


def require_uuid_env(name: str) -> str:
    raw = os.environ.get(name, "")
    try:
        return str(UUID(raw))
    except (ValueError, AttributeError) as exc:
        raise RuntimeError(f"missing_or_invalid_{name.lower()}") from exc


def build_rpc_params(options: ProjectionOptions) -> dict[str, object]:
    return {
        "p_owner_id": require_uuid_env("DEV_USER_ID"),
        "p_apply": options.apply,
        "p_limit": options.limit,
        "p_after_source_id": (
            str(options.after_source_id) if options.after_source_id else None
        ),
        "p_projection_run_id": str(options.run_id),
    }


def _default_client():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("supabase_environment_missing")
    return create_client(url, key)


def _normalize_result(data: Any) -> dict[str, object]:
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict):
        raise RuntimeError("projection_response_invalid")
    required = {
        "scanned",
        "inserted",
        "already_present",
        "conflicts",
        "dry_run",
        "next_after_source_id",
    }
    if not required.issubset(data):
        raise RuntimeError("projection_response_invalid")
    for key in ("scanned", "inserted", "already_present", "conflicts"):
        if not isinstance(data[key], int) or data[key] < 0:
            raise RuntimeError("projection_response_invalid")
    if not isinstance(data["dry_run"], bool):
        raise RuntimeError("projection_response_invalid")
    return data


def _record_run(
    client: Any,
    *,
    run_id: UUID,
    status: str,
    started_at: str,
    result: dict[str, object] | None = None,
    error_code: str | None = None,
) -> None:
    client.rpc(
        RECORD_RPC,
        {
            "p_run_id": str(run_id),
            "p_status": status,
            "p_scanned": int(result["scanned"]) if result else 0,
            "p_inserted": int(result["inserted"]) if result else 0,
            "p_error_code": error_code,
            "p_started_at": started_at,
        },
    ).execute()


def _write_report(
    report_dir: Path,
    *,
    options: ProjectionOptions,
    started_at: str,
    result: dict[str, object],
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"projection-{options.run_id}.json"
    payload = {
        "schema_version": 1,
        "run_id": str(options.run_id),
        "started_at": started_at,
        "apply": options.apply,
        "limit": options.limit,
        "result": result,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[[], Any] = _default_client,
) -> int:
    parser = argparse.ArgumentParser(description="Project canonical motion GT")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--run-id", type=UUID, default=None)
    parser.add_argument("--confirm-run-id", type=UUID, default=None)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--after-source-id", type=UUID, default=None)
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("artifacts/canonical-gt/projection-runs"),
    )
    args = parser.parse_args(argv)
    run_id = args.run_id or uuid4()
    if args.limit < 1 or args.limit > 500:
        parser.error("--limit must be between 1 and 500")
    if args.apply and args.confirm_run_id != run_id:
        parser.error("--apply requires matching --run-id and --confirm-run-id")

    options = ProjectionOptions(
        apply=args.apply,
        run_id=run_id,
        limit=args.limit,
        after_source_id=args.after_source_id,
    )
    started_at = datetime.now(timezone.utc).isoformat()
    client: Any | None = None
    try:
        client = client_factory()
        response = client.rpc(PROJECT_RPC, build_rpc_params(options)).execute()
        result = _normalize_result(response.data)
        if bool(result["dry_run"]) == options.apply:
            raise RuntimeError("projection_mode_mismatch")
        if options.apply:
            _record_run(
                client,
                run_id=run_id,
                status="succeeded",
                started_at=started_at,
                result=result,
            )
        report = _write_report(
            args.report_dir,
            options=options,
            started_at=started_at,
            result=result,
        )
    except Exception:
        if options.apply and client is not None:
            try:
                _record_run(
                    client,
                    run_id=run_id,
                    status="failed",
                    started_at=started_at,
                    error_code="projection_rpc_failed",
                )
            except Exception:
                pass
        print("CANONICAL_GT_PROJECTION_FAILED", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": int(result["conflicts"]) == 0,
                "report": str(report),
                "result": result,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if not options.apply and int(result["conflicts"]) > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
