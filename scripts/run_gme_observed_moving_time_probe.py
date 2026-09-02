"""GME 관측 움직임 시간 migration을 일회용 PostgreSQL에서 실증해."""

from __future__ import annotations

import argparse
from pathlib import Path
import socket
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BASE_MIGRATION = ROOT / "migrations" / "2026-08-03_gecko_motion_engine_shadow.sql"
METRIC_MIGRATION = ROOT / "migrations" / "2026-09-03_gme_observed_moving_time_v1.sql"
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
    dropdb = args.pg_bin / "dropdb"
    for binary in (psql, initdb, pg_ctl, createdb, dropdb):
        if not binary.is_file():
            raise ProbeError(f"missing:{binary.name}")

    port = free_port()
    database = "gme_observed_moving_time_probe"
    with tempfile.TemporaryDirectory(prefix="gme-observed-moving-time-pg-") as tmp:
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
                    "create table public.motion_clips(id uuid primary key); "
                    "grant select on public.motion_clips to service_role;",
                ),
                "schema",
            )
            require_ok(
                sql(database, BASE_MIGRATION.read_text(encoding="utf-8")),
                "base_migration",
            )
            require_ok(
                sql(database, METRIC_MIGRATION.read_text(encoding="utf-8")),
                "metric_migration",
            )

            identity = "a" * 64
            other_identity = "b" * 64
            setup = f"""
            insert into public.motion_clips(id) values
              ('00000000-0000-4000-8000-000000000001'),
              ('00000000-0000-4000-8000-000000000002'),
              ('00000000-0000-4000-8000-000000000003'),
              ('00000000-0000-4000-8000-000000000004'),
              ('00000000-0000-4000-8000-000000000005');

            insert into public.gme_jobs(
              id,clip_id,source,priority,engine_schema_version,algorithm_version,
              detector_identity,status
            ) values
              ('10000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000001',
               'historical',10,'gme-shadow-v1','gme-motion-v0','{identity}','succeeded'),
              ('10000000-0000-4000-8000-000000000002','00000000-0000-4000-8000-000000000002',
               'historical',10,'gme-shadow-v1','gme-motion-v0','{identity}','succeeded'),
              ('10000000-0000-4000-8000-000000000003','00000000-0000-4000-8000-000000000003',
               'historical',10,'gme-shadow-v1','gme-motion-v0','{identity}','failed_terminal'),
              ('10000000-0000-4000-8000-000000000004','00000000-0000-4000-8000-000000000004',
               'historical',10,'gme-shadow-v1','gme-motion-v0','{identity}','queued'),
              ('10000000-0000-4000-8000-000000000005','00000000-0000-4000-8000-000000000004',
               'historical',10,'gme-shadow-v1','gme-motion-v1','{identity}','queued');

            insert into public.gme_runs(
              id,clip_id,job_id,engine_schema_version,algorithm_version,detector_identity,
              producer_host,producer_run_id,status,duration_sec,decoded_frame_count,
              analyzed_frame_count,source_fps,candidate_moving_sec_any_gecko,
              moving_gecko_seconds,visible_sec,unknown_sec,camera_motion_sec,
              max_simultaneous_geckos,permanent_artifact_key,
              permanent_artifact_sha256,permanent_artifact_bytes
            ) values
              ('20000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000001',
               '10000000-0000-4000-8000-000000000001','gme-shadow-v1','gme-motion-v0','{identity}',
               'probe','probe-measured','ok',30,300,300,10,12.5,12.5,20,5,1,1,
               'terra-derived/gme/v1/permanent/probe/measured.json',repeat('c',64),1),
              ('20000000-0000-4000-8000-000000000002','00000000-0000-4000-8000-000000000002',
               '10000000-0000-4000-8000-000000000002','gme-shadow-v1','gme-motion-v0','{identity}',
               'probe','probe-not-observed','ok',30,300,300,10,0,0,0,30,0,0,
               'terra-derived/gme/v1/permanent/probe/not-observed.json',repeat('d',64),1);

            update public.gme_jobs set result_run_id='20000000-0000-4000-8000-000000000001'
              where id='10000000-0000-4000-8000-000000000001';
            update public.gme_jobs set result_run_id='20000000-0000-4000-8000-000000000002'
              where id='10000000-0000-4000-8000-000000000002';
            """
            require_ok(sql(database, setup), "fixtures")

            states = require_ok(
                sql(
                    database,
                    f"""
                    select measurement_status || ':' || moving_time_sec::text
                      from public.fn_get_gme_observed_moving_time_v1(
                        '00000000-0000-4000-8000-000000000001','{identity}');
                    select measurement_status
                      from public.fn_get_gme_observed_moving_time_v1(
                        '00000000-0000-4000-8000-000000000002','{identity}');
                    select measurement_status
                      from public.fn_get_gme_observed_moving_time_v1(
                        '00000000-0000-4000-8000-000000000003','{identity}');
                    select measurement_status
                      from public.fn_get_gme_observed_moving_time_v1(
                        '00000000-0000-4000-8000-000000000005','{identity}');
                    select measurement_status
                      from public.fn_get_gme_observed_moving_time_v1(
                        '00000000-0000-4000-8000-000000000001','{other_identity}');
                    """,
                ),
                "states",
            ).splitlines()
            if states != ["measured:12.5", "not_observed", "failed", "pending", "pending"]:
                raise ProbeError(f"state mismatch:{states}")

            ambiguous = sql(
                database,
                f"""
                select * from public.fn_get_gme_observed_moving_time_v1(
                  '00000000-0000-4000-8000-000000000004','{identity}');
                """,
            )
            if ambiguous.returncode == 0 or "ambiguous GME detector identity" not in ambiguous.stderr:
                raise ProbeError("duplicate identity did not fail closed")
            print("GME_OBSERVED_MOVING_TIME_RUNTIME_OK")

            denied = sql(
                database,
                f"""
                set role authenticated;
                select * from public.fn_get_gme_observed_moving_time_v1(
                  '00000000-0000-4000-8000-000000000001','{identity}');
                """,
            )
            if denied.returncode == 0 or "permission denied" not in denied.stderr:
                raise ProbeError("authenticated execute allowed")
            service_role_state = require_ok(
                sql(
                    database,
                    f"""
                    set role service_role;
                    select measurement_status
                      from public.fn_get_gme_observed_moving_time_v1(
                        '00000000-0000-4000-8000-000000000001','{identity}');
                    """,
                ),
                "service_role_execute",
            )
            if service_role_state != "measured":
                raise ProbeError(f"service role mismatch:{service_role_state}")
            print("GME_OBSERVED_MOVING_TIME_PRIVILEGE_OK")

            rollback = require_ok(
                sql(
                    database,
                    "drop function public.fn_get_gme_observed_moving_time_v1(uuid, text); "
                    "select to_regprocedure('public.fn_get_gme_observed_moving_time_v1(uuid,text)') "
                    "is null;",
                ),
                "rollback",
            )
            if rollback != "t":
                raise ProbeError(f"rollback residue:{rollback}")
            print("GME_OBSERVED_MOVING_TIME_ROLLBACK_OK")
            require_ok(
                run([str(dropdb), "-h", "127.0.0.1", "-p", str(port), database]),
                "dropdb",
            )
            print("PROBE_RESIDUE=0")
        finally:
            if started:
                run([str(pg_ctl), "-D", str(data_dir), "-m", "fast", "-w", "stop"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
