"""GME duration epsilon migration을 일회용 PostgreSQL에서 실증해."""

from __future__ import annotations

import argparse
from pathlib import Path
import socket
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BASE_MIGRATION = ROOT / "migrations" / "2026-08-03_gecko_motion_engine_shadow.sql"
EPSILON_MIGRATION = ROOT / "migrations" / "2026-09-04_gme_run_duration_epsilon.sql"
FLAGS = ("-X", "-v", "ON_ERROR_STOP=1", "-qAt")


class ProbeError(RuntimeError):
    pass


def run(argv: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def require_ok(result: subprocess.CompletedProcess[str], label: str) -> str:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:1500]
        raise ProbeError(f"{label}:{detail}")
    return (result.stdout or "").strip()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", type=Path, required=True)
    args = parser.parse_args()
    psql = args.pg_bin / "psql"
    initdb = args.pg_bin / "initdb"
    pg_ctl = args.pg_bin / "pg_ctl"
    createdb = args.pg_bin / "createdb"
    for binary in (psql, initdb, pg_ctl, createdb):
        if not binary.is_file():
            raise ProbeError(f"missing:{binary.name}")

    port = free_port()
    database = "gme_duration_epsilon_probe"
    with tempfile.TemporaryDirectory(prefix="gme-duration-epsilon-pg-") as tmp:
        data_dir = Path(tmp) / "data"
        require_ok(
            run([str(initdb), "-D", str(data_dir), "--auth=trust", "--no-locale"]),
            "initdb",
        )
        started = False

        def sql(db: str, statement: str) -> subprocess.CompletedProcess[str]:
            return run(
                [str(psql), "-h", "127.0.0.1", "-p", str(port), "-d", db, *FLAGS],
                input_text=statement,
            )

        try:
            started_result = subprocess.run(
                [
                    str(pg_ctl),
                    "-D",
                    str(data_dir),
                    "-o",
                    f"-h 127.0.0.1 -p {port}",
                    "-w",
                    "start",
                ],
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=120,
                check=False,
            )
            require_ok(started_result, "pg_start")
            started = True
            require_ok(
                sql(
                    "postgres",
                    "create role anon nologin; create role authenticated nologin; "
                    "create role service_role nologin bypassrls;",
                ),
                "roles",
            )
            require_ok(
                run([str(createdb), "-h", "127.0.0.1", "-p", str(port), database]),
                "createdb",
            )
            require_ok(
                sql(
                    database,
                    "create extension if not exists pgcrypto; "
                    "create table public.motion_clips(id uuid primary key);",
                ),
                "schema",
            )
            require_ok(sql(database, BASE_MIGRATION.read_text()), "base_migration")

            before = sql(
                database,
                "insert into public.motion_clips(id) values "
                "('00000000-0000-4000-8000-000000000001'); "
                "insert into public.gme_jobs("
                "id,clip_id,source,priority,engine_schema_version,algorithm_version,detector_identity"
                ") values ("
                "'10000000-0000-4000-8000-000000000001',"
                "'00000000-0000-4000-8000-000000000001','historical',10,"
                "'gme-shadow-v1','gme-motion-v1',repeat('a',64)); "
                + _insert_run_sql("9.9999999999999996", "noise-before"),
            )
            if before.returncode == 0 or "check constraint" not in before.stderr:
                raise ProbeError("base constraint did not reproduce float-noise rejection")

            require_ok(sql(database, EPSILON_MIGRATION.read_text()), "epsilon_migration")
            require_ok(
                sql(database, _insert_run_sql("9.9999999999999996", "noise-after")),
                "epsilon_acceptance",
            )

            real_inversion = sql(
                database,
                _insert_run_sql("9.9989", "real-inversion"),
            )
            if real_inversion.returncode == 0 or "gme_runs_moving_duration_epsilon_check" not in real_inversion.stderr:
                raise ProbeError("epsilon constraint accepted a real duration inversion")

            definition = require_ok(
                sql(
                    database,
                    "select pg_get_constraintdef(oid) from pg_constraint "
                    "where conrelid='public.gme_runs'::regclass "
                    "and conname='gme_runs_moving_duration_epsilon_check';",
                ),
                "constraint_definition",
            )
            if "0.001" not in definition:
                raise ProbeError(f"unexpected constraint definition:{definition}")
            print("GME_RUN_DURATION_EPSILON_RUNTIME_OK")
            return 0
        finally:
            if started:
                subprocess.run(
                    [str(pg_ctl), "-D", str(data_dir), "-m", "fast", "-w", "stop"],
                    text=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=120,
                    check=False,
                )


def _insert_run_sql(moving: str, producer_run_id: str) -> str:
    artifact_sha = "b" * 64 if producer_run_id == "noise-after" else "c" * 64
    return f"""
    insert into public.gme_runs(
      clip_id,job_id,engine_schema_version,algorithm_version,detector_identity,
      producer_host,producer_run_id,status,duration_sec,decoded_frame_count,
      analyzed_frame_count,source_fps,candidate_moving_sec_any_gecko,
      moving_gecko_seconds,visible_sec,unknown_sec,camera_motion_sec,
      max_simultaneous_geckos,permanent_artifact_key,
      permanent_artifact_sha256,permanent_artifact_bytes
    ) values (
      '00000000-0000-4000-8000-000000000001',
      '10000000-0000-4000-8000-000000000001',
      'gme-shadow-v1','gme-motion-v1',repeat('a',64),
      'probe','{producer_run_id}','ok',10,100,100,10,10,{moving},10,0,0,1,
      'terra-derived/gme/v1/permanent/probe/{producer_run_id}.json',
      '{artifact_sha}',1
    );
    """


if __name__ == "__main__":
    raise SystemExit(main())
