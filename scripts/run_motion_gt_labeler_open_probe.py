"""motion GT 라벨러 개방 migration(2026-09-09_motion_gt_labeler_open)을 일회용 PostgreSQL 에서 실증한다.
highlight probe 헬퍼 재사용. production 연결 0."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_highlight_rule_v0_probe import (  # noqa: E402
    FLAGS, ProbeError, expect, free_port, parse_kv_lines, require_ok, require_sqlstate, run,
)

MIGRATIONS = [
    ROOT / "migrations" / "2026-07-22_motion_clip_labeling_v3.sql",
    ROOT / "migrations" / "2026-07-22_motion_clip_gt_decision_guard.sql",
    ROOT / "migrations" / "2026-09-09_motion_gt_labeler_open.sql",
]
# v3 migration 이 요구하는 최소 껍데기. 실제 컬럼은 함수가 만지는 것만.
SCHEMA_SQL = """
    create extension if not exists pgcrypto;
    create schema auth; create table auth.users(id uuid primary key);
    create table public.cameras(id uuid primary key, name text);
    create table public.motion_clips(id uuid primary key, camera_id uuid references public.cameras(id),
      started_at timestamptz not null default now(), duration_sec double precision, r2_key text,
      clip_purpose text not null default 'production');
    create table public.labelers(user_id uuid primary key);
    create table public.clip_vlm_jobs(id uuid primary key, clip_id uuid, status text, result jsonb, completed_at timestamptz);
"""
OWNER = "30000000-0000-4000-8000-000000000002"
LABELER = "30000000-0000-4000-8000-000000000001"
CAM = "40000000-0000-4000-8000-000000000001"
CLIP_FRESH = "00000000-0000-4000-8000-000000000001"   # triage 없음
CLIP_SKIP = "00000000-0000-4000-8000-000000000002"    # owner 가 skip
CLIP_NOMEDIA = "00000000-0000-4000-8000-000000000003"
GT = '{"visibility":"visible"}'


def main() -> int:
    os.environ.setdefault("LC_ALL", "C")
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", type=Path, required=True)
    args = parser.parse_args()
    binaries = {n: args.pg_bin / n for n in ("psql", "initdb", "pg_ctl", "createdb")}
    for path in binaries.values():
        if not path.is_file():
            raise ProbeError(f"missing:{path.name}")
    port = free_port()
    db = "motion_gt_open_probe"
    with tempfile.TemporaryDirectory(prefix="motion-gt-open-pg-") as tmp:
        data_dir = Path(tmp) / "data"
        require_ok(run([str(binaries["initdb"]), "-D", str(data_dir), "--auth=trust", "--no-locale"]), "initdb")
        started = False

        def sql(database: str, statement: str) -> subprocess.CompletedProcess[str]:
            return run([str(binaries["psql"]), "-h", "127.0.0.1", "-p", str(port), "-d", database, *FLAGS], input_text=statement)

        def q(statement: str) -> dict[str, str]:
            return parse_kv_lines(require_ok(sql(db, statement), statement[:60]))

        def lock(clip: str, who: str, is_owner: bool) -> subprocess.CompletedProcess[str]:
            return sql(db, f"select 'stage|'||stage from public.fn_lock_motion_clip_gt('{clip}','{who}',{str(is_owner).lower()},'{GT}'::jsonb,null);")

        try:
            require_ok(subprocess.run([str(binaries["pg_ctl"]), "-D", str(data_dir), "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"],
                                      text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120, check=False), "pg_start")
            started = True
            require_ok(sql("postgres", "create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;"), "roles")
            require_ok(run([str(binaries["createdb"]), "-h", "127.0.0.1", "-p", str(port), db]), "createdb")
            require_ok(sql(db, SCHEMA_SQL), "schema")
            for path in MIGRATIONS:
                require_ok(sql(db, path.read_text(encoding="utf-8")), path.name)
            require_ok(sql(db, f"""
                insert into auth.users(id) values ('{OWNER}'),('{LABELER}');
                insert into public.labelers(user_id) values ('{LABELER}');
                insert into public.cameras(id, name) values ('{CAM}', 'probe-cam');
                insert into public.motion_clips(id, camera_id, duration_sec, r2_key) values
                  ('{CLIP_FRESH}', '{CAM}', 60, 'terra-clips/clips/a.mp4'),
                  ('{CLIP_SKIP}', '{CAM}', 60, 'terra-clips/clips/b.mp4'),
                  ('{CLIP_NOMEDIA}', '{CAM}', 60, null);
            """), "seed")

            # 1) 라벨러가 triage 없는 clip 의 GT 를 잠근다 → gt_locked, triage label, 이벤트 labeler_started_labeling
            expect("labeler-lock-fresh", parse_kv_lines(require_ok(lock(CLIP_FRESH, LABELER, False), "labeler-lock")), stage="gt_locked")
            expect("triage-label", q(f"select 'd|'||owner_decision||'|'||decided_by::text from public.motion_clip_labeling_triage where clip_id='{CLIP_FRESH}';"), d=f"label|{LABELER}")
            expect("event", q(f"select 'e|'||event_type from public.motion_clip_labeling_triage_events where clip_id='{CLIP_FRESH}' order by created_at desc limit 1;"), e="labeler_started_labeling")
            # 2) 같은 라벨러 재잠금 → PT423. owner 는 같은 clip 에 자기 세션을 따로 잠글 수 있다(유니크 clip+reviewer)
            require_sqlstate(lock(CLIP_FRESH, LABELER, False), "relock", "PT423")
            expect("owner-lock-same-clip", parse_kv_lines(require_ok(lock(CLIP_FRESH, OWNER, True), "owner-lock")), stage="gt_locked")
            expect("sessions", q(f"select 'n|'||count(*)::text from public.motion_clip_labeling_sessions where clip_id='{CLIP_FRESH}';"), n="2")
            # 3) owner 가 skip 으로 접은 clip 은 라벨러·owner 모두 PT424
            require_ok(sql(db, f"select * from public.fn_decide_motion_clip_labeling('{CLIP_SKIP}','{OWNER}','skip',null,null);"), "skip")
            require_sqlstate(lock(CLIP_SKIP, LABELER, False), "labeler-on-skip", "PT424")
            require_sqlstate(lock(CLIP_SKIP, OWNER, True), "owner-on-skip", "PT424")
            # 4) 원본 없는 clip PT422, 미존재 P0002
            require_sqlstate(lock(CLIP_NOMEDIA, LABELER, False), "no-media", "PT422")
            require_sqlstate(lock("00000000-0000-4000-8000-0000000000ff", LABELER, False), "missing", "P0002")
            # 5) 검수 완료(vlm review) 는 라벨러 세션으로도 된다(prediction 없음 → no_prediction 완료)
            expect("complete", q(f"select 'r|'||coalesce(completion_reason,'null') from public.fn_complete_motion_clip_vlm_review('{CLIP_FRESH}','{LABELER}',null,array[]::text[],null);"), r="no_prediction")
            # 6) CHECK 제약이 하나만 남았고 새 이벤트 값을 허용
            expect("check-count", q("select 'n|'||count(*)::text from pg_constraint where conrelid='public.motion_clip_labeling_triage_events'::regclass and contype='c' and pg_get_constraintdef(oid) like '%event_type%';"), n="1")
            print("MOTION_GT_LABELER_OPEN_PROBE_OK")
        finally:
            if started:
                subprocess.run([str(binaries["pg_ctl"]), "-D", str(data_dir), "-m", "immediate", "stop"], text=True, capture_output=True, timeout=120, check=False)
    print("PROBE_RESIDUE=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
