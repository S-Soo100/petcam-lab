"""사건 경계·대시보드 migration을 disposable PostgreSQL DB에서 실증해."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = (
    ROOT / "migrations" / "2026-07-31_rba_boundary_review_dashboard.sql",
    ROOT / "migrations" / "2026-08-02_rba_boundary_adjudication_blind_gate.sql",
)
DB_NAME = re.compile(r"^rba_boundary_probe_[0-9a-f]{12}$")
ROLES = ("anon", "authenticated", "service_role")
FLAGS = ("-X", "-v", "ON_ERROR_STOP=1", "-qAt")


class ProbeError(RuntimeError):
    pass


def run(argv: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, input=input_text, text=True, capture_output=True, timeout=90, check=False)


def require_ok(result: subprocess.CompletedProcess[str], label: str) -> str:
    if result.returncode != 0:
        raise ProbeError(f"{label}: {(result.stderr or result.stdout).strip()[:800]}")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", type=Path, required=True)
    args = parser.parse_args()
    psql, createdb, dropdb = (args.pg_bin / name for name in ("psql", "createdb", "dropdb"))
    for binary in (psql, createdb, dropdb):
        if not binary.is_file():
            raise ProbeError(f"missing:{binary.name}")

    database = f"rba_boundary_probe_{secrets.token_hex(6)}"
    if not DB_NAME.fullmatch(database):
        raise ProbeError("unsafe database name")

    def sql(db: str, statement: str) -> subprocess.CompletedProcess[str]:
        return run([str(psql), "-h", "127.0.0.1", "-p", "5432", "-d", db, *FLAGS], input_text=statement)

    existing_text = require_ok(sql("postgres", "select rolname from pg_roles where rolname in ('anon','authenticated','service_role') order by 1;"), "roles")
    existing = set(existing_text.splitlines()) if existing_text else set()
    created_roles = [role for role in ROLES if role not in existing]
    try:
        if created_roles:
            require_ok(sql("postgres", "\n".join(f"create role {role} nologin;" for role in created_roles)), "role setup")
        require_ok(run([str(createdb), "-h", "127.0.0.1", "-p", "5432", database]), "createdb")
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
        for migration in MIGRATIONS:
            require_ok(sql(database, migration.read_text(encoding="utf-8")), f"migration:{migration.name}")
        seed = """
        insert into public.cameras values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','1번');
        insert into public.motion_clips values
          ('11111111-1111-4111-8111-111111111111','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',now()-interval '2 min',30,'a.mp4'),
          ('22222222-2222-4222-8222-222222222222','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',now()-interval '1 min',30,'b.mp4');
        insert into public.motion_clip_labeling_sessions(clip_id,reviewed_by,initial_gt)
        values ('11111111-1111-4111-8111-111111111111','bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','{"primary_action":"moving"}');
        select public.fn_seed_rba_boundary_review(
          'probe', repeat('a',64),
          'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
          (
            select jsonb_agg(jsonb_build_object(
              'split', case when i <= 60 then 'development' else 'holdout' end,
              'ordinal', case when i <= 60 then i else i-60 end,
              'left_clip_id', '11111111-1111-4111-8111-111111111111',
              'right_clip_id', '22222222-2222-4222-8222-222222222222',
              'gap_sec', 30, 'gap_bin', 'le30',
              'pair_digest', encode(digest(i::text,'sha256'),'hex')
            ) order by i) from generate_series(1,120) i
          )
        );
        """
        require_ok(sql(database, seed), "seed")
        pre_gate = require_ok(sql(database, """
          select public.fn_get_rba_boundary_access('cccccccc-cccc-4ccc-8ccc-cccccccccccc')->>'enabled';
          select public.fn_get_rba_boundary_workspace('cccccccc-cccc-4ccc-8ccc-cccccccccccc')->>'total';
          select public.fn_submit_rba_boundary_decision('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',(select id from public.rba_boundary_review_pairs where split='development' and ordinal=1),'uncertain')->>'submitted';
          select public.fn_submit_rba_boundary_decision('cccccccc-cccc-4ccc-8ccc-cccccccccccc',(select id from public.rba_boundary_review_pairs where split='development' and ordinal=1),'uncertain')->>'submitted';
          select public.fn_list_rba_boundary_conflicts('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')->>'ready';
          select public.fn_list_rba_boundary_conflicts('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')->>'total';
          select jsonb_array_length(public.fn_list_rba_boundary_conflicts('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')->'items');
        """), "pre gate").splitlines()
        if pre_gate != ["true", "60", "true", "true", "false", "0", "0"]:
            raise ProbeError(f"pre gate mismatch:{pre_gate}")

        blocked = sql(database, """
          select public.fn_resolve_rba_boundary_conflict(
            'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            (select id from public.rba_boundary_review_pairs where split='development' and ordinal=1),
            'same_event','이어지는 움직임'
          );
        """)
        if blocked.returncode == 0 or "adjudication_not_ready" not in blocked.stderr:
            raise ProbeError("pre-completion resolution was not blocked")

        # 마지막 peer 제출만 남겨 둔다. 그 제출이 미커밋인 동안 다른 세션의 resolve는 PT409여야 한다.
        require_ok(sql(database, """
          select public.fn_submit_rba_boundary_decision(
            a.reviewer_id, a.pair_id, 'same_event'
          )
          from public.rba_boundary_review_assignments a
          join public.rba_boundary_review_pairs p on p.id=a.pair_id
          where p.split='development' and p.ordinal between 2 and 60
            and not (a.reviewer_role='peer' and p.ordinal=60);
        """), "fill except last")
        last_submit_sql = """
          begin;
          select public.fn_submit_rba_boundary_decision(
            'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
            (select id from public.rba_boundary_review_pairs where split='development' and ordinal=60),
            'same_event'
          );
          select pg_advisory_xact_lock(314159, 271828);
          select pg_sleep(2);
          commit;
        """
        last_process = subprocess.Popen(
            [str(psql), "-h", "127.0.0.1", "-p", "5432", "-d", database, *FLAGS],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        assert last_process.stdin is not None
        last_process.stdin.write(last_submit_sql)
        last_process.stdin.close()
        lock_seen = False
        lock_deadline = time.monotonic() + 5
        while time.monotonic() < lock_deadline:
            held = require_ok(sql(database, """
              select count(*) from pg_locks
              where locktype='advisory' and classid=314159 and objid=271828 and granted;
            """), "last-submit handshake")
            if held == "1":
                lock_seen = True
                break
            time.sleep(0.05)
        if not lock_seen:
            last_process.kill()
            raise ProbeError("last submit did not reach the uncommitted handshake")
        race_blocked = sql(database, """
          select public.fn_resolve_rba_boundary_conflict(
            'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
            (select id from public.rba_boundary_review_pairs where split='development' and ordinal=1),
            'same_event','이어지는 움직임'
          );
        """)
        if race_blocked.returncode == 0 or "adjudication_not_ready" not in race_blocked.stderr:
            last_process.kill()
            raise ProbeError("uncommitted-last-submit race was not blocked")
        last_stdout = last_process.stdout.read() if last_process.stdout else ""
        last_stderr = last_process.stderr.read() if last_process.stderr else ""
        last_code = last_process.wait(timeout=10)
        if last_code != 0:
            raise ProbeError(f"last submit failed:{(last_stderr or last_stdout)[:500]}")

        post_gate = require_ok(sql(database, """
          select public.fn_list_rba_boundary_conflicts('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')->>'ready';
          select public.fn_list_rba_boundary_conflicts('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')->>'total';
          select public.fn_resolve_rba_boundary_conflict('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',(select id from public.rba_boundary_review_pairs where split='development' and ordinal=1),'same_event','이어지는 움직임')->>'resolved';
          select public.fn_get_labeling_data_dashboard('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')->>'gt_labeled_video_count';
        """), "post gate").splitlines()
        if post_gate != ["true", "1", "true", "1"]:
            raise ProbeError(f"post gate mismatch:{post_gate}")

        append_only = sql(database, "update public.rba_boundary_review_submissions set decision='same_event';")
        if append_only.returncode == 0 or "append-only" not in append_only.stderr:
            raise ProbeError("append-only guard failed")
        denied = sql(database, "set role authenticated; select public.fn_get_rba_boundary_workspace('cccccccc-cccc-4ccc-8ccc-cccccccccccc');")
        if denied.returncode == 0:
            raise ProbeError("authenticated execute allowed")
        print("RBA_BOUNDARY_RUNTIME_OK")
        print("RBA_BOUNDARY_BLIND_GATE_OK")
        print("RBA_BOUNDARY_LAST_SUBMIT_RACE_OK")
        print("RBA_BOUNDARY_APPEND_ONLY_OK")
        print("RBA_BOUNDARY_PRIVILEGE_OK")
    finally:
        if DB_NAME.fullmatch(database):
            run([str(dropdb), "-h", "127.0.0.1", "-p", "5432", "--if-exists", database])
        if created_roles:
            require_ok(
                sql("postgres", "\n".join(f"drop role if exists {role};" for role in reversed(created_roles))),
                "role cleanup",
            )
        residue = require_ok(sql("postgres", f"select count(*) from pg_database where datname='{database}';"), "residue")
        role_residue = require_ok(sql(
            "postgres",
            "select count(*) from pg_roles where rolname in ("
            + ",".join(f"'{role}'" for role in created_roles)
            + ");" if created_roles else "select 0;",
        ), "role residue")
        print(f"PROBE_RESIDUE={residue}")
        print(f"ROLE_RESIDUE={role_residue}")
        if residue != "0" or role_residue != "0":
            raise ProbeError("cleanup failed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, ProbeError) as exc:
        print(f"RBA_BOUNDARY_PROBE_FAILED type={type(exc).__name__} detail={exc}", file=sys.stderr)
        raise SystemExit(2) from exc
