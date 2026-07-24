"""짧은 영상 장치 오류 격리·보존 실제 DB probe 러너 (Task 1~2).

정적 SQL 텍스트 테스트만으로는 못 잡는 런타임 정확성을 검증한다. 일회용 Homebrew PostgreSQL 15
임시 DB(`blind_probe_short_clip_<hex>`)에:

  (1) base prerequisites → motion v3 → double-blind → role-based reads
      → 짧은 영상 추가 prerequisites → 이 migration 을 순서대로 적용
  (2) non-empty 합성 row 로 감지/격리·복구·삭제 lease·append-only·내구성 Slack claim 계약을
      SQL ASSERT 로 검증한다. probe SQL 은 BEGIN … ROLLBACK 으로 합성 row 를 전량 되돌린다.
  (3) rollback 뒤 잔여 synthetic row 0 을 재확인한다.

안전 계약(run_motion_double_blind_concurrency_probe.py 재사용):
  - 127.0.0.1/localhost Homebrew PostgreSQL 만 허용(운영 DB 접속 금지).
  - 무작위 `blind_probe_short_clip_<hex>` DB 만 createdb → finally 에서 그 DB(+probe 가 만든 전역
    role)만 dropdb/drop role. 기존 DB·기존 role 은 절대 수정/삭제하지 않는다(이름 prefix 재검증).
  - 정리 실패는 fail-closed(nonzero). local 툴 부재는 BLOCKED(READY 주장 금지).

성공 출력(여섯 줄):
  SHORT_CLIP_DETECT_OK
  SHORT_CLIP_RESTORE_OK
  SHORT_CLIP_DELETE_LEASE_OK
  SHORT_CLIP_APPEND_ONLY_OK
  SHORT_CLIP_NOTIFY_OK
  PROBE_RESIDUE=0
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 기존 러너의 local-postgres 안전 계약을 재사용한다(동작 변경 없음).
from scripts.run_motion_double_blind_concurrency_probe import (  # noqa: E402
    _BLIND_ROLES,
    LOCAL_HOSTS,
    LocalPostgresBackend,
    ProbeBlocked,
    ProbeFailed,
    _drop_created_roles,
    _existing_blind_roles,
    _find_pg_tool,
    _run,
    roles_to_cleanup,
    validate_database_url,
)

BLOCKED_VERDICT = "SHORT_CLIP_RETENTION_LAB_BLOCKED_DB_RUNTIME"
REQUIRED_MARKERS = (
    "SHORT_CLIP_DETECT_OK",
    "SHORT_CLIP_RESTORE_OK",
    "SHORT_CLIP_DELETE_LEASE_OK",
    "SHORT_CLIP_APPEND_ONLY_OK",
    "SHORT_CLIP_NOTIFY_OK",
    "SHORT_CLIP_CONSUMER_GUARD_OK",
)

# residue 재확인 대상(probe 가 insert 하는 테이블). rollback 이 정상이면 전부 0.
_RESIDUE_TABLES = (
    "public.motion_clips",
    "public.cameras",
    "public.camera_short_clip_policies",
    "public.motion_clip_system_exclusions",
    "public.motion_clip_system_exclusion_events",
    "public.motion_clip_labeling_triage",
    "public.motion_clip_labeling_triage_events",
    "public.motion_clip_labeling_sessions",
    "public.behavior_logs",
    "public.python_evidence_jobs",
    "public.short_clip_retention_notifications",
    "public.labelers",
    "public.labeler_applications",
    "public.motion_labeling_review_groups",
    "public.motion_labeling_review_group_members",
    "public.motion_labeling_review_group_cameras",
    "public.motion_clip_review_slots",
    "public.motion_blind_review_cohorts",
    "public.motion_clip_consensus",
    "auth.users",
)

# migration 적용 순서. 이 migration 은 role-based reads·추가 prerequisites 뒤, probe 앞에 온다.
_APPLY_ORDER = (
    ("prerequisites", "tests/sql/motion_double_blind_prerequisites.sql"),
    ("motion_v3", "migrations/2026-07-22_motion_clip_labeling_v3.sql"),
    ("double_blind", "migrations/2026-07-23_motion_double_blind_labeling.sql"),
    ("role_reads", "migrations/2026-07-24_role_based_labeling_reads.sql"),
    ("short_clip_prereqs", "tests/sql/short_clip_device_error_retention_prerequisites.sql"),
    ("short_clip", "migrations/2026-07-24_short_clip_device_error_retention.sql"),
)
_PROBE_SQL = "tests/sql/short_clip_device_error_retention_probe.sql"


# ── 순수 로직(단위 테스트 대상) ──────────────────────────────────────
def short_clip_temp_database_name(token: str) -> str:
    """무작위 임시 DB 이름. `blind_probe_short_clip_` prefix 로 drop 대상을 좁힌다."""
    return f"blind_probe_short_clip_{token}"


def validate_short_clip_temp_database_name(name: str) -> None:
    """create/drop 대상이 `blind_probe_short_clip_<hex>` 형태인지 강제한다(운영 DB 오삭제 방지)."""
    if not re.fullmatch(r"blind_probe_short_clip_[a-f0-9]+", name):
        raise ProbeBlocked(f"unsafe_temp_database_name: {name!r}")


def missing_marker(stdout: str) -> str | None:
    """probe stdout 에서 누락된 첫 마커를 반환(전부 있으면 None)."""
    for marker in REQUIRED_MARKERS:
        if marker not in stdout:
            return marker
    return None


# ── 실증 단계 ────────────────────────────────────────────────────────
def _residue_count(backend: LocalPostgresBackend) -> int:
    expr = " + ".join(f"(SELECT count(*) FROM {t})" for t in _RESIDUE_TABLES)
    proc = backend.psql_run(f"SELECT {expr};")
    if proc.returncode != 0:
        raise ProbeFailed(f"residue_query_failed: {proc.stderr.strip()[:300]}")
    return int((proc.stdout or "0").strip() or "0")


def _run_short_clip_steps(
    backend: LocalPostgresBackend,
    apply_paths: list[tuple[str, Path]],
    probe: Path,
) -> int:
    # 1) prerequisites + migration 순서 적용(이 migration 마지막).
    for label, path in apply_paths:
        proc = backend.psql_run(path.read_text())
        if proc.returncode != 0:
            raise ProbeFailed(f"{label}_apply_failed: {proc.stderr.strip()[:600]}")

    # 2) non-empty probe: fixtures + RPC 호출 + ASSERT (내부에서 BEGIN … ROLLBACK).
    runtime = backend.psql_run(probe.read_text(), timeout=120.0)
    if runtime.returncode != 0:
        detail = (runtime.stderr.strip() or runtime.stdout.strip())[:800]
        raise ProbeFailed(f"probe_failed: {detail}")
    absent = missing_marker(runtime.stdout)
    if absent is not None:
        detail = (runtime.stderr.strip() or runtime.stdout.strip())[:800]
        raise ProbeFailed(f"marker_absent:{absent}: {detail}")

    # 3) rollback 뒤 잔여 synthetic row 0.
    residue = _residue_count(backend)

    for marker in REQUIRED_MARKERS:
        print(marker)
    print(f"PROBE_RESIDUE={residue}")
    return 0 if residue == 0 else 1


def run_local_short_clip_probe(
    apply_paths: list[tuple[str, Path]],
    probe: Path,
    *,
    pg_bin: str | None = None,
    host: str = "127.0.0.1",
    port: int = 5432,
) -> int:
    """local backend: 무작위 blind_probe_short_clip_* 임시 DB 만 만들고 finally 에서 그 DB(+probe 가
    만든 전역 role)만 정리. 기존 DB·기존 role 은 절대 건드리지 않는다. 정리 실패는 fail-closed."""
    if host not in LOCAL_HOSTS:
        raise ProbeBlocked(f"non_local_database_forbidden: host={host!r}")
    psql = _find_pg_tool("psql", pg_bin)
    createdb = _find_pg_tool("createdb", pg_bin)
    dropdb = _find_pg_tool("dropdb", pg_bin)

    name = short_clip_temp_database_name(secrets.token_hex(8))
    validate_short_clip_temp_database_name(name)  # 생성 전 검증.
    dsn = f"postgresql://{host}:{port}/{name}"
    validate_database_url(dsn)

    created = False
    roles_to_drop: list[str] = []
    result: int | None = None
    cleanup_errors: list[str] = []
    try:
        cp = _run([createdb, "-h", host, "-p", str(port), name], timeout=30)
        if cp.returncode != 0:
            raise ProbeBlocked(f"createdb_failed: {cp.stderr.strip()[:300]}")
        created = True
        backend = LocalPostgresBackend(psql, dsn)
        # migration 적용 전 사전 존재 role 을 확정 → probe 가 만든 것만 정리.
        pre_existing = _existing_blind_roles(backend)
        roles_to_drop = roles_to_cleanup(_BLIND_ROLES, pre_existing)
        result = _run_short_clip_steps(backend, apply_paths, probe)
    finally:
        if created:
            validate_short_clip_temp_database_name(name)  # drop 전 재검증.
            drop = _run([dropdb, "-h", host, "-p", str(port), "--if-exists", name], timeout=30)
            if drop.returncode != 0:
                cleanup_errors.append(f"dropdb_failed: {drop.stderr.strip()[:200]}")
            role_drop = _drop_created_roles(psql, host, port, roles_to_drop)
            if role_drop is not None and role_drop.returncode != 0:
                cleanup_errors.append(f"role_cleanup_failed: {role_drop.stderr.strip()[:200]}")
    if cleanup_errors:
        raise ProbeFailed("cleanup_failed: " + "; ".join(cleanup_errors))
    return result if result is not None else 1


def _resolve_paths() -> tuple[list[tuple[str, Path]], Path]:
    apply_paths = [(label, _REPO_ROOT / rel) for label, rel in _APPLY_ORDER]
    return apply_paths, _REPO_ROOT / _PROBE_SQL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="짧은 영상 격리·보존 실제 DB probe")
    parser.add_argument("--backend", choices=("local-postgres",), default="local-postgres")
    parser.add_argument("--pg-bin", default=None, help="psql/createdb/dropdb 디렉토리")
    parser.add_argument("--pg-host", default="127.0.0.1", help="127.0.0.1/localhost 만")
    parser.add_argument("--pg-port", default=5432, type=int)
    args = parser.parse_args(argv)

    apply_paths, probe = _resolve_paths()
    for _label, path in apply_paths:
        if not path.is_file():
            print(f"{BLOCKED_VERDICT}: missing_file:{path}", file=sys.stderr)
            return 2
    if not probe.is_file():
        print(f"{BLOCKED_VERDICT}: missing_file:{probe}", file=sys.stderr)
        return 2

    try:
        return run_local_short_clip_probe(
            apply_paths, probe, pg_bin=args.pg_bin, host=args.pg_host, port=args.pg_port
        )
    except ProbeBlocked as exc:
        print(f"{BLOCKED_VERDICT}: {exc}", file=sys.stderr)
        return 2
    except ProbeFailed as exc:
        print(f"SHORT_CLIP_PROBE_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
