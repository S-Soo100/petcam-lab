"""Local-only disposable PostgreSQL probe for the GME negative-audit migration."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.gme_negative_audit_sampling import (  # noqa: E402
    CHECKPOINT_SHA256,
    DETECTOR_IDENTITY,
    _canonical_json,
    build_private_manifest,
    select_calibration_batch,
)
from scripts.run_motion_double_blind_concurrency_probe import (  # noqa: E402
    _BLIND_ROLES,
    LOCAL_HOSTS,
    ProbeBlocked,
    ProbeFailed,
    _existing_blind_roles,
    _find_pg_tool,
    _run,
    roles_to_cleanup,
)

BLOCKED_VERDICT = "GME_NEGATIVE_AUDIT_BLOCKED_DB_RUNTIME"
MANIFEST_PLACEHOLDER = "__GME_NEGATIVE_AUDIT_MANIFEST__"
REQUIRED_MARKERS = (
    "GME_NEGATIVE_AUDIT_SCHEMA_OK",
    "GME_NEGATIVE_AUDIT_BLIND_OK",
    "GME_NEGATIVE_AUDIT_APPEND_ONLY_OK",
)
_DB_PREFIX = "blind_probe_gme_negative_"
_APPLY_ORDER = (
    ("prerequisites", "tests/sql/gme_negative_audit_prerequisites.sql"),
    ("migration", "migrations/2026-08-23_gme_negative_audit_calibration.sql"),
)
_PROBE_SQL = "tests/sql/gme_negative_audit_probe.sql"
_FIXTURE_BEGIN = "-- GME_NEGATIVE_FIXTURE_BEGIN"
_FIXTURE_END = "-- GME_NEGATIVE_FIXTURE_END"
_PSQL_FLAGS = ("-X", "-v", "ON_ERROR_STOP=1", "-A", "-t", "-q")
_PRESERVED_EXCEPTIONS = (KeyboardInterrupt, SystemExit, subprocess.TimeoutExpired)


class HardenedLocalPostgresBackend:
    """Local psql backend that never reads a user-controlled .psqlrc."""

    def __init__(self, psql: str, dsn: str) -> None:
        self._psql = psql
        self.dsn = dsn

    def psql_run(
        self, sql: str, *, timeout: float = 60.0
    ) -> subprocess.CompletedProcess:
        return _run(self.psql_argv(), timeout=timeout, input_text=sql)

    def psql_argv(self) -> list[str]:
        return [self._psql, self.dsn, *_PSQL_FLAGS]


def negative_audit_temp_database_name(token: str) -> str:
    return f"{_DB_PREFIX}{token}"


def validate_negative_audit_temp_database_name(name: str) -> None:
    """Only a freshly generated 64-bit hex suffix can be a create/drop target."""
    if re.fullmatch(r"blind_probe_gme_negative_[a-f0-9]{16}", name) is None:
        raise ProbeBlocked(f"unsafe_temp_database_name: {name!r}")


def validate_probe_database_url(url: str) -> None:
    """Accept only the exact DSN shape constructed by this runner.

    libpq accepts connection overrides in query parameters and Unix socket hosts, so merely
    checking ``parsed.hostname`` is not sufficient for a destructive disposable-DB runner.
    """
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as error:
        raise ProbeBlocked("unsafe_database_url") from error
    name = parsed.path.removeprefix("/")
    expected_authorities = {f"127.0.0.1:{port}", f"localhost:{port}"}
    if (
        parsed.scheme != "postgresql"
        or parsed.hostname not in LOCAL_HOSTS
        or port is None
        or parsed.netloc not in expected_authorities
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.params
        or parsed.path != f"/{name}"
    ):
        raise ProbeBlocked("unsafe_database_url")
    try:
        validate_negative_audit_temp_database_name(name)
    except ProbeBlocked as error:
        raise ProbeBlocked("unsafe_database_url") from error


def missing_marker(stdout: str) -> str | None:
    lines = stdout.splitlines()
    for line in lines:
        for marker in REQUIRED_MARKERS:
            if marker in line and line != marker:
                return f"invalid_marker_line:{marker}"
    for marker in REQUIRED_MARKERS:
        count = lines.count(marker)
        if count == 0:
            return marker
        if count != 1:
            return f"duplicate_marker:{marker}"
    return None


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def build_probe_manifest() -> dict[str, object]:
    """Build the six-item fixture through the Task 1 canonical producer."""
    control_gt = {"label": "게코-control", "visibility": "visible"}
    control_gt_digest = hashlib.sha256(_canonical_json(control_gt)).hexdigest()
    started = datetime(2026, 8, 20, tzinfo=timezone.utc)
    durations = (0.0000001, 15.25, 30.0, 45.125, 60.0, 75.5)
    negatives: list[dict[str, object]] = []
    controls: list[dict[str, object]] = []
    for index in range(6):
        suffix = f"{index + 1:012d}"
        row: dict[str, object] = {
            "clip_id": f"10000000-0000-4000-8000-{suffix}",
            "stratum": "random_negative" if index < 4 else "positive_control",
            "started_at": started.isoformat().replace("+00:00", "Z"),
            "duration_sec": durations[index],
            "camera_night_key": f"게코-night-{index % 2}",
            "episode_key": f"episode-{index}",
            "gme_run_id": f"20000000-0000-4000-8000-{suffix}",
            "detector_identity": DETECTOR_IDENTITY,
            "media_sha256": _digest(f"probe-media-{index}"),
            "media_dhash": f"{index + 1:016x}",
            "gme_detected": index >= 4,
            "human_gt_digest": control_gt_digest if index >= 4 else None,
        }
        (negatives if index < 4 else controls).append(row)

    selection = select_calibration_batch(
        negatives,
        controls,
        protected_sha256=set(),
        protected_dhash64=set(),
        seed="gme-negative-audit-runtime-probe-v1",
        batch_kind="preview_canary",
        negative_count=4,
        control_count=2,
    )
    return build_private_manifest(
        selection,
        test_sheet_sha256=_digest("probe-test-sheet"),
        cutoff="2026-08-01T00:00:00Z",
        checkpoint_sha256=CHECKPOINT_SHA256,
        protected_manifest_sha256=[_digest("protected-게코-manifest")],
    )


def render_probe_sql(template: str, manifest: dict[str, object]) -> str:
    if template.count(MANIFEST_PLACEHOLDER) != 1:
        raise ProbeFailed("probe_template_requires_exactly_one_manifest_placeholder")
    encoded = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    # SQL string literal escaping is deterministic; generated manifest contains no executable SQL.
    literal = "'" + encoded.replace("'", "''") + "'"
    return template.replace(MANIFEST_PLACEHOLDER, literal)


def extract_fixture_sql(rendered_sql: str) -> str:
    """Extract the exact source-row fixture used by both runtime and lock probes."""
    if rendered_sql.count(_FIXTURE_BEGIN) != 1 or rendered_sql.count(_FIXTURE_END) != 1:
        raise ProbeFailed("probe_fixture_markers_missing_or_duplicated")
    before, remainder = rendered_sql.split(_FIXTURE_BEGIN, 1)
    fixture, after = remainder.split(_FIXTURE_END, 1)
    if not before or not after:
        raise ProbeFailed("probe_fixture_markers_invalid")
    return fixture.strip()


def _manifest_sql_literal(manifest: dict[str, object]) -> str:
    return render_probe_sql(MANIFEST_PLACEHOLDER, manifest)


def _safe_error(error: BaseException) -> str:
    """Bound error detail while removing DSNs/password-like values from cleanup reports."""
    detail = " ".join(str(error).split())
    detail = re.sub(r"postgres(?:ql)?://\S+", "postgresql://[redacted]", detail)
    detail = re.sub(r"(?i)(password=)[^\s;]+", r"\1[redacted]", detail)
    return f"{type(error).__name__}:{detail[:300]}"


def _safe_process_error(process: subprocess.CompletedProcess) -> str:
    detail = process.stderr.strip() or process.stdout.strip() or f"returncode={process.returncode}"
    return _safe_error(RuntimeError(detail)).removeprefix("RuntimeError:")


def _raise_after_cleanup(
    primary_error: BaseException | None, cleanup_errors: list[str]
) -> None:
    if primary_error is None:
        if cleanup_errors:
            raise ProbeFailed("cleanup_failed:" + ";".join(cleanup_errors))
        return
    if isinstance(primary_error, _PRESERVED_EXCEPTIONS):
        if cleanup_errors:
            primary_error.add_note("cleanup_failed:" + ";".join(cleanup_errors))
        raise primary_error.with_traceback(primary_error.__traceback__)
    if cleanup_errors:
        raise ProbeFailed(
            f"primary_failed:{_safe_error(primary_error)};cleanup_failed:"
            + ";".join(cleanup_errors)
        ) from primary_error
    raise primary_error.with_traceback(primary_error.__traceback__)


def _validate_local_connection_parts(host: str, port: int) -> None:
    if host not in LOCAL_HOSTS:
        raise ProbeBlocked(f"non_local_database_forbidden: host={host!r}")
    if not 1 <= port <= 65535:
        raise ProbeBlocked(f"invalid_postgres_port: {port}")


def _database_exists(psql: str, host: str, port: int, name: str) -> bool:
    validate_negative_audit_temp_database_name(name)
    _validate_local_connection_parts(host, port)
    dsn = f"postgresql://{host}:{port}/postgres"
    proc = _run(
        [psql, dsn, *_PSQL_FLAGS],
        timeout=30,
        input_text=f"SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname='{name}');",
    )
    if proc.returncode != 0:
        raise ProbeFailed(f"database_residue_query_failed: {proc.stderr.strip()[:300]}")
    value = proc.stdout.strip().lower()
    if value not in {"t", "f"}:
        raise ProbeFailed(f"database_residue_unparseable: {value!r}")
    return value == "t"


def _drop_probe_roles(
    psql: str, host: str, port: int, roles: list[str]
) -> subprocess.CompletedProcess | None:
    _validate_local_connection_parts(host, port)
    safe = [role for role in roles if role in _BLIND_ROLES]
    if not safe:
        return None
    dsn = f"postgresql://{host}:{port}/postgres"
    sql = "".join(f"DROP ROLE IF EXISTS {role};" for role in safe)
    return _run([psql, dsn, *_PSQL_FLAGS], timeout=30, input_text=sql)


def _apply_sql(backend: HardenedLocalPostgresBackend, label: str, path: Path) -> None:
    proc = backend.psql_run(path.read_text(), timeout=120.0)
    if proc.returncode != 0:
        raise ProbeFailed(f"{label}_apply_failed: {proc.stderr.strip()[:900]}")


def _run_source_lock_probe(
    backend: HardenedLocalPostgresBackend,
    rendered_probe: str,
    manifest: dict[str, object],
) -> None:
    """Prove the import's SHARE locks cancel a concurrent source-table mutation."""
    fixture = extract_fixture_sql(rendered_probe)
    holder_sql = f"""
BEGIN;
CREATE TEMP TABLE probe_manifest (payload jsonb NOT NULL);
INSERT INTO probe_manifest(payload) VALUES ({_manifest_sql_literal(manifest)}::jsonb);
{fixture}
SELECT * FROM public.fn_create_gme_negative_audit_batch(
  '00000000-0000-4000-8000-000000000001',
  (SELECT payload FROM probe_manifest)
);
SELECT pg_sleep(3);
ROLLBACK;
"""
    holder = subprocess.Popen(
        backend.psql_argv(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    primary_error: BaseException | None = None
    holder_cleanup_errors: list[str] = []
    try:
        assert holder.stdin is not None
        holder.stdin.write(holder_sql)
        holder.stdin.flush()
        holder.stdin.close()
        holder.stdin = None

        deadline = time.monotonic() + 8.0
        lock_seen = False
        while time.monotonic() < deadline:
            lock = backend.psql_run(
                "SELECT count(DISTINCT relation.relname)=4 FROM pg_locks held"
                " JOIN pg_class relation ON relation.oid=held.relation"
                " JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace"
                " WHERE namespace.nspname='public' AND relation.relname IN ("
                " 'motion_clips','motion_clip_consensus','gme_jobs','gme_runs')"
                " AND held.mode='ShareLock' AND held.granted"
                ";",
                timeout=10.0,
            )
            if lock.returncode != 0:
                raise ProbeFailed(f"lock_observation_failed: {lock.stderr.strip()[:300]}")
            if lock.stdout.strip().lower() == "t":
                lock_seen = True
                break
            if holder.poll() is not None:
                break
            time.sleep(0.1)
        if not lock_seen:
            out, err = holder.communicate(timeout=5)
            raise ProbeFailed(f"source_share_lock_not_observed: {(err or out).strip()[:500]}")

        mutation = backend.psql_run(
            "\\set VERBOSITY verbose\n"
            "SET statement_timeout='750ms';"
            "UPDATE public.motion_clips SET duration_sec=duration_sec;",
            timeout=5.0,
        )
        if mutation.returncode == 0 or "57014" not in mutation.stderr:
            raise ProbeFailed(
                "source_mutation_did_not_wait_and_cancel: "
                + (mutation.stderr.strip() or mutation.stdout.strip())[:500]
            )
        out, err = holder.communicate(timeout=8)
        if holder.returncode != 0:
            raise ProbeFailed(f"source_lock_holder_failed: {(err or out).strip()[:500]}")
    except BaseException as error:
        primary_error = error
    finally:
        if holder.poll() is None:
            try:
                holder.kill()
            except BaseException as error:
                holder_cleanup_errors.append(f"holder_kill_failed:{_safe_error(error)}")
            try:
                holder.communicate(timeout=5)
            except BaseException as error:
                holder_cleanup_errors.append(
                    f"holder_communicate_failed:{_safe_error(error)}"
                )
    _raise_after_cleanup(primary_error, holder_cleanup_errors)


def _run_probe_steps(
    backend: HardenedLocalPostgresBackend,
    apply_paths: list[tuple[str, Path]],
    probe_path: Path,
) -> None:
    for label, path in apply_paths:
        _apply_sql(backend, label, path)

    manifest = build_probe_manifest()
    rendered = render_probe_sql(probe_path.read_text(), manifest)
    _run_source_lock_probe(backend, rendered, manifest)

    runtime = backend.psql_run(rendered, timeout=180.0)
    if runtime.returncode != 0:
        detail = (runtime.stderr.strip() or runtime.stdout.strip())[:1200]
        raise ProbeFailed(f"runtime_probe_failed: {detail}")
    absent = missing_marker(runtime.stdout)
    if absent is not None:
        raise ProbeFailed(f"marker_absent:{absent}: {runtime.stdout.strip()[:800]}")

    residue = backend.psql_run(
        "SELECT (SELECT count(*) FROM public.gme_negative_audit_batches)"
        " + (SELECT count(*) FROM public.gme_negative_audit_batch_events)"
        " + (SELECT count(*) FROM public.gme_negative_audit_items)"
        " + (SELECT count(*) FROM public.gme_negative_audit_submissions)"
        " + (SELECT count(*) FROM public.gme_negative_audit_corrections)"
        " + (SELECT count(*) FROM public.gme_negative_audit_adjudications)"
        " + (SELECT count(*) FROM public.gme_negative_audit_dataset_decisions);"
    )
    if residue.returncode != 0 or (residue.stdout.strip() or "0") != "0":
        raise ProbeFailed(
            "transaction_residue_nonzero: "
            + (residue.stderr.strip() or residue.stdout.strip())[:300]
        )


def run_local_negative_audit_probe(
    apply_paths: list[tuple[str, Path]],
    probe_path: Path,
    *,
    pg_bin: str | None = None,
    host: str = "127.0.0.1",
    port: int = 5432,
) -> int:
    """Create one random local DB, run the probe, and prove that DB was dropped."""
    _validate_local_connection_parts(host, port)
    psql = _find_pg_tool("psql", pg_bin)
    createdb = _find_pg_tool("createdb", pg_bin)
    dropdb = _find_pg_tool("dropdb", pg_bin)

    name = negative_audit_temp_database_name(secrets.token_hex(8))
    validate_negative_audit_temp_database_name(name)
    dsn = f"postgresql://{host}:{port}/{name}"
    validate_probe_database_url(dsn)
    if _database_exists(psql, host, port, name):
        raise ProbeBlocked(f"temp_database_already_exists: {name}")

    creation_attempted = False
    roles_to_drop: list[str] = []
    primary_error: BaseException | None = None
    cleanup_control_error: BaseException | None = None
    try:
        # createdb may create the DB before timeout/KeyboardInterrupt reaches Python. From this
        # point onward existence is uncertain until the maintenance connection proves otherwise.
        creation_attempted = True
        create = _run([createdb, "-h", host, "-p", str(port), name], timeout=30)
        if create.returncode != 0:
            raise ProbeBlocked(f"createdb_failed: {create.stderr.strip()[:300]}")
        backend = HardenedLocalPostgresBackend(psql, dsn)
        pre_existing = _existing_blind_roles(backend)
        roles_to_drop = roles_to_cleanup(_BLIND_ROLES, pre_existing)
        _run_probe_steps(backend, apply_paths, probe_path)
    except BaseException as error:
        primary_error = error
    finally:
        cleanup_errors: list[str] = []
        if creation_attempted:
            database_present: bool | None = None
            try:
                database_present = _database_exists(psql, host, port, name)
            except BaseException as error:
                if isinstance(error, _PRESERVED_EXCEPTIONS):
                    cleanup_control_error = cleanup_control_error or error
                cleanup_errors.append(
                    f"database_presence_check_failed:{_safe_error(error)}"
                )

            # If the presence check itself failed, --if-exists on the exact validated random
            # name is the fail-closed cleanup. The pre-attempt collision guard proved it was not
            # a pre-existing database.
            drop_attempted = database_present is not False
            try:
                validate_negative_audit_temp_database_name(name)
                if drop_attempted:
                    drop = _run(
                        [
                            dropdb,
                            "-h",
                            host,
                            "-p",
                            str(port),
                            "--if-exists",
                            "--force",
                            name,
                        ],
                        timeout=30,
                    )
                    if drop.returncode != 0:
                        cleanup_errors.append(
                            f"dropdb_failed:{_safe_process_error(drop)}"
                        )
            except BaseException as error:
                if isinstance(error, _PRESERVED_EXCEPTIONS):
                    cleanup_control_error = cleanup_control_error or error
                cleanup_errors.append(f"dropdb_failed:{_safe_error(error)}")

            if drop_attempted:
                try:
                    if _database_exists(psql, host, port, name):
                        cleanup_errors.append("database_residue_nonzero")
                except BaseException as error:
                    if isinstance(error, _PRESERVED_EXCEPTIONS):
                        cleanup_control_error = cleanup_control_error or error
                    cleanup_errors.append(
                        f"database_residue_check_failed:{_safe_error(error)}"
                    )

            try:
                role_drop = _drop_probe_roles(psql, host, port, roles_to_drop)
                if role_drop is not None and role_drop.returncode != 0:
                    cleanup_errors.append(
                        f"role_cleanup_failed:{_safe_process_error(role_drop)}"
                    )
            except BaseException as error:
                if isinstance(error, _PRESERVED_EXCEPTIONS):
                    cleanup_control_error = cleanup_control_error or error
                cleanup_errors.append(f"role_cleanup_failed:{_safe_error(error)}")
    if cleanup_control_error is not None and not isinstance(
        primary_error, _PRESERVED_EXCEPTIONS
    ):
        detail = list(cleanup_errors)
        if primary_error is not None:
            detail.insert(0, f"primary_failed:{_safe_error(primary_error)}")
        if detail:
            cleanup_control_error.add_note(";".join(detail))
        raise cleanup_control_error.with_traceback(cleanup_control_error.__traceback__)
    _raise_after_cleanup(primary_error, cleanup_errors)

    for marker in REQUIRED_MARKERS:
        print(marker)
    print("PROBE_RESIDUE=0")
    return 0


def _resolve_paths() -> tuple[list[tuple[str, Path]], Path]:
    return (
        [(label, _REPO_ROOT / relative) for label, relative in _APPLY_ORDER],
        _REPO_ROOT / _PROBE_SQL,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GME negative-audit disposable DB probe")
    parser.add_argument("--backend", choices=("local-postgres",), default="local-postgres")
    parser.add_argument("--pg-bin", default=None, help="psql/createdb/dropdb directory")
    parser.add_argument("--pg-host", default="127.0.0.1", help="127.0.0.1/localhost only")
    parser.add_argument("--pg-port", default=5432, type=int)
    args = parser.parse_args(argv)

    apply_paths, probe_path = _resolve_paths()
    for _label, path in apply_paths:
        if not path.is_file():
            print(f"{BLOCKED_VERDICT}: missing_file:{path}", file=sys.stderr)
            return 2
    if not probe_path.is_file():
        print(f"{BLOCKED_VERDICT}: missing_file:{probe_path}", file=sys.stderr)
        return 2
    try:
        return run_local_negative_audit_probe(
            apply_paths,
            probe_path,
            pg_bin=args.pg_bin,
            host=args.pg_host,
            port=args.pg_port,
        )
    except ProbeBlocked as error:
        print(f"{BLOCKED_VERDICT}: {error}", file=sys.stderr)
        return 2
    except ProbeFailed as error:
        print(f"GME_NEGATIVE_AUDIT_PROBE_FAILED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
