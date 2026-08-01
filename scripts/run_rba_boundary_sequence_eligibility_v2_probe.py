"""사건 이어짐 v2 migration을 일회용 PostgreSQL cluster에서 실증해."""

from __future__ import annotations

import argparse
from pathlib import Path
import socket
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BASE_MIGRATION = ROOT / "migrations" / "2026-07-31_rba_boundary_review_dashboard.sql"
V2_MIGRATION = ROOT / "migrations" / "2026-08-01_rba_boundary_sequence_eligibility_v2.sql"
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
    database = "rba_sequence_eligibility_probe"
    with tempfile.TemporaryDirectory(prefix="rba-sequence-pg-") as tmp:
        data_dir = Path(tmp) / "data"
        require_ok(run([str(initdb), "-D", str(data_dir), "--auth=trust", "--no-locale"]), "initdb")
        started = False

        def sql(db: str, statement: str) -> subprocess.CompletedProcess[str]:
            return run([
                str(psql), "-h", "127.0.0.1", "-p", str(port), "-d", db, *FLAGS,
            ], input_text=statement)

        try:
            # postgres daemon이 probe의 capture pipe를 상속하면 pg_ctl이 끝나도
            # communicate()가 EOF를 못 받아 대기하므로 서버 stdout은 분리해.
            started_result = subprocess.run(
                [
                    str(pg_ctl), "-D", str(data_dir), "-o", f"-h 127.0.0.1 -p {port}",
                    "-w", "start",
                ],
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=120,
                check=False,
            )
            require_ok(started_result, "pg_start")
            started = True
            require_ok(sql("postgres", "create role anon nologin; create role authenticated nologin; create role service_role nologin;"), "roles")
            require_ok(run([
                str(createdb), "-h", "127.0.0.1", "-p", str(port), database,
            ]), "createdb")
            schema = """
            create extension if not exists pgcrypto;
            create table public.cameras(id uuid primary key, name text);
            create table public.motion_clips(
              id uuid primary key, camera_id uuid, started_at timestamptz not null,
              duration_sec double precision not null, r2_key text
            );
            create table public.motion_clip_system_exclusions(clip_id uuid, state text);
            create table public.motion_blind_review_cohorts(
              id uuid primary key, status text, created_at timestamptz default now()
            );
            create table public.motion_clip_consensus(
              id uuid primary key default gen_random_uuid(), clip_id uuid, cohort_kind text,
              cohort_id uuid, status text, final_decision text, final_gt jsonb
            );
            create table public.motion_clip_labeling_sessions(
              id uuid primary key default gen_random_uuid(), clip_id uuid, reviewed_by uuid,
              initial_gt jsonb, current_gt jsonb, updated_at timestamptz default now()
            );
            """
            require_ok(sql(database, schema), "schema")
            require_ok(sql(database, BASE_MIGRATION.read_text(encoding="utf-8")), "base_migration")
            require_ok(sql(database, V2_MIGRATION.read_text(encoding="utf-8")), "v2_migration")

            owner = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            peer = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
            camera = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
            setup = f"""
            insert into public.cameras values ('{camera}','1번');
            insert into public.motion_clips(id,camera_id,started_at,duration_sec,r2_key)
            select ('00000000-0000-4000-8000-' || lpad(i::text,12,'0'))::uuid,
                   '{camera}', now() + i * interval '40 seconds', 30, 'clip-' || i || '.mp4'
            from generate_series(1,240) i;
            select public.fn_seed_rba_boundary_review(
              'rba-event-grouping-shadow-v2', repeat('a',64), '{owner}', '{owner}', '{peer}',
              (select jsonb_agg(jsonb_build_object(
                'split', case when i <= 60 then 'development' else 'holdout' end,
                'ordinal', case when i <= 60 then i else i-60 end,
                'left_clip_id', ('00000000-0000-4000-8000-' || lpad(i::text,12,'0'))::uuid,
                'right_clip_id', ('00000000-0000-4000-8000-' || lpad((i+1)::text,12,'0'))::uuid,
                'gap_sec', 10, 'gap_bin', 'le30',
                'pair_digest', encode(digest(('old-' || i)::text,'sha256'),'hex')
              ) order by i) from generate_series(1,120) i)
            );
            """
            require_ok(sql(database, setup), "old_seed")
            invalidated = require_ok(sql(database, f"""
              select public.fn_invalidate_rba_boundary_review_v1(
                '{owner}','rba-event-grouping-shadow-v2','게코 부재 자격 검사 누락'
              )->>'status';
            """), "old_invalidate")
            if invalidated != "invalid_eligibility":
                raise ProbeError(f"old invalidation mismatch:{invalidated}")

            seed_v2 = f"""
            select public.fn_seed_rba_boundary_sequence_review_v2(
              'rba-event-sequence-review-v2', repeat('b',64), '{owner}', '{owner}', '{peer}',
              (select jsonb_agg(jsonb_build_object(
                'split', 'development', 'ordinal', i,
                'left_clip_id', ('00000000-0000-4000-8000-' || lpad(i::text,12,'0'))::uuid,
                'right_clip_id', ('00000000-0000-4000-8000-' || lpad((i+1)::text,12,'0'))::uuid,
                'gap_sec', 10, 'gap_bin', 'le30',
                'pair_digest', encode(digest(('new-' || i)::text,'sha256'),'hex')
              ) order by i) from generate_series(1,120) i)
            )->>'status';
            """
            if require_ok(sql(database, seed_v2), "v2_seed") != "eligibility_open":
                raise ProbeError("v2 seed status mismatch")

            workspace = require_ok(sql(database, f"""
              select public.fn_get_rba_boundary_workspace('{owner}')->>'mode';
              select public.fn_get_rba_boundary_workspace('{owner}')->>'total';
              select public.fn_get_rba_boundary_workspace('{peer}')->>'mode';
              select public.fn_get_rba_boundary_workspace('{peer}')->>'next_pair';
            """), "workspace").splitlines()
            if workspace != ["eligibility", "120", "waiting"]:
                raise ProbeError(f"workspace mismatch:{workspace}")

            eligibility = f"""
            do $$
            declare pair_id uuid;
            begin
              for pair_id in
                select p.id from public.rba_boundary_review_pairs p
                join public.rba_boundary_review_cohorts c on c.id=p.cohort_id
                where c.experiment_id='rba-event-sequence-review-v2'
                order by p.ordinal
              loop
                perform public.fn_submit_rba_boundary_eligibility(
                  '{owner}', pair_id,
                  case when (select ordinal from public.rba_boundary_review_pairs where id=pair_id)=120
                    then 'left_gecko_absent' else 'eligible' end
                );
              end loop;
            end $$;
            select c.status from public.rba_boundary_review_cohorts c
              where c.experiment_id='rba-event-sequence-review-v2';
            select count(*) from public.rba_boundary_review_assignments a
              join public.rba_boundary_review_pairs p on p.id=a.pair_id
              join public.rba_boundary_review_cohorts c on c.id=p.cohort_id
              where c.experiment_id='rba-event-sequence-review-v2';
            select count(*) from public.rba_boundary_review_assignments a
              join public.rba_boundary_review_pairs p on p.id=a.pair_id
              join public.rba_boundary_review_cohorts c on c.id=p.cohort_id
              where c.experiment_id='rba-event-sequence-review-v2' and p.ordinal=119;
            """
            phase = require_ok(sql(database, eligibility), "eligibility_phase").splitlines()
            if phase != ["development_open", "236", "0"]:
                raise ProbeError(f"phase mismatch:{phase}")

            immutable = sql(database, "update public.rba_boundary_eligibility_reviews set decision='eligible';")
            if immutable.returncode == 0 or "append-only" not in immutable.stderr:
                raise ProbeError("eligibility append-only failed")
            denied = sql(database, f"set role authenticated; select public.fn_get_rba_boundary_workspace('{owner}');")
            if denied.returncode == 0:
                raise ProbeError("authenticated execute allowed")

            print("RBA_SEQUENCE_ELIGIBILITY_RUNTIME_OK")
            print("RBA_SEQUENCE_ELIGIBILITY_PRIVILEGE_OK")
            require_ok(run([
                str(dropdb), "-h", "127.0.0.1", "-p", str(port), database,
            ]), "dropdb")
            residue = require_ok(sql("postgres", f"select count(*) from pg_database where datname='{database}';"), "residue")
            print(f"PROBE_RESIDUE={residue}")
            if residue != "0":
                raise ProbeError("cleanup failed")
        finally:
            if started:
                run([str(pg_ctl), "-D", str(data_dir), "-m", "fast", "-w", "stop"])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, ProbeError) as exc:
        print(f"RBA_SEQUENCE_ELIGIBILITY_PROBE_FAILED type={type(exc).__name__} detail={exc}", file=sys.stderr)
        raise SystemExit(2) from exc
