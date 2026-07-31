"""사건 경계·대시보드 migration을 disposable PostgreSQL DB에서 실증해."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import secrets
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "2026-07-31_rba_boundary_review_dashboard.sql"
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
        require_ok(sql(database, MIGRATION.read_text(encoding="utf-8")), "migration")
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
        behavior = require_ok(sql(database, """
          select public.fn_get_rba_boundary_access('cccccccc-cccc-4ccc-8ccc-cccccccccccc')->>'enabled';
          select public.fn_get_rba_boundary_workspace('cccccccc-cccc-4ccc-8ccc-cccccccccccc')->>'total';
          select public.fn_submit_rba_boundary_decision('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',(select id from public.rba_boundary_review_pairs where split='development' and ordinal=1),'uncertain')->>'submitted';
          select public.fn_submit_rba_boundary_decision('cccccccc-cccc-4ccc-8ccc-cccccccccccc',(select id from public.rba_boundary_review_pairs where split='development' and ordinal=1),'uncertain')->>'submitted';
          select public.fn_list_rba_boundary_conflicts('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')->>'total';
          select public.fn_resolve_rba_boundary_conflict('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',(select id from public.rba_boundary_review_pairs where split='development' and ordinal=1),'same_event','이어지는 움직임')->>'resolved';
          select public.fn_get_labeling_data_dashboard('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')->>'gt_labeled_video_count';
        """), "behavior").splitlines()
        if behavior != ["true", "60", "true", "true", "1", "true", "1"]:
            raise ProbeError(f"behavior mismatch:{behavior}")

        append_only = sql(database, "update public.rba_boundary_review_submissions set decision='same_event';")
        if append_only.returncode == 0 or "append-only" not in append_only.stderr:
            raise ProbeError("append-only guard failed")
        denied = sql(database, "set role authenticated; select public.fn_get_rba_boundary_workspace('cccccccc-cccc-4ccc-8ccc-cccccccccccc');")
        if denied.returncode == 0:
            raise ProbeError("authenticated execute allowed")
        print("RBA_BOUNDARY_RUNTIME_OK")
        print("RBA_BOUNDARY_APPEND_ONLY_OK")
        print("RBA_BOUNDARY_PRIVILEGE_OK")
    finally:
        if DB_NAME.fullmatch(database):
            run([str(dropdb), "-h", "127.0.0.1", "-p", "5432", "--if-exists", database])
        if created_roles:
            sql("postgres", "\n".join(f"drop role if exists {role};" for role in reversed(created_roles)))
        residue = require_ok(sql("postgres", f"select count(*) from pg_database where datname='{database}';"), "residue")
        print(f"PROBE_RESIDUE={residue}")
        if residue != "0":
            raise ProbeError("cleanup failed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, ProbeError) as exc:
        print(f"RBA_BOUNDARY_PROBE_FAILED type={type(exc).__name__} detail={exc}", file=sys.stderr)
        raise SystemExit(2) from exc
