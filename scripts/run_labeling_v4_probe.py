"""labeling web v4 migration을 일회용 PostgreSQL에서 실증한다. highlight v0 probe 헬퍼를 재사용. production 연결 0."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# `python scripts/x.py` 는 sys.path[0]=scripts/ 라 `scripts.` 패키지 import 가 안 된다 → 레포 루트를 앞에 넣는다.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_highlight_rule_v0_probe import (  # noqa: E402
    ALGO, CLIP, ENGINE, FLAGS, IDENTITY, LABELER, MIGRATIONS, OWNER, SCHEMA_SQL,
    ProbeError, expect, free_port, kv_select, parse_kv_lines, require_ok, require_sqlstate, run, setup_sql,
)

V4_MIGRATION = ROOT / "migrations" / "2026-09-08_labeling_v4_simplification.sql"
CAM_A = "40000000-0000-4000-8000-000000000001"  # setup_sql 이 만든 카메라
CAM_B = "40000000-0000-4000-8000-000000000002"


def main() -> int:
    # LC_ALL 이 비어 있으면 macOS 에서 postmaster 가 "became multithreaded during startup" 으로 죽는다(A probe 와 동일).
    os.environ.setdefault("LC_ALL", "C")
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", type=Path, required=True)
    args = parser.parse_args()
    binaries = {n: args.pg_bin / n for n in ("psql", "initdb", "pg_ctl", "createdb")}
    for path in binaries.values():
        if not path.is_file():
            raise ProbeError(f"missing:{path.name}")
    port = free_port()
    db = "labeling_v4_probe"
    with tempfile.TemporaryDirectory(prefix="labeling-v4-pg-") as tmp:
        data_dir = Path(tmp) / "data"
        require_ok(run([str(binaries["initdb"]), "-D", str(data_dir), "--auth=trust", "--no-locale"]), "initdb")
        started = False

        def sql(database: str, statement: str) -> subprocess.CompletedProcess[str]:
            return run([str(binaries["psql"]), "-h", "127.0.0.1", "-p", str(port), "-d", database, *FLAGS], input_text=statement)

        def q(statement: str) -> dict[str, str]:
            return parse_kv_lines(require_ok(sql(db, statement), statement[:60]))

        def list_ids(scope: str, extra: str = "null, null, null") -> list[str]:
            out = require_ok(sql(db, f"select clip_id from public.fn_list_labeling_v4_clips('{LABELER}', false, '{scope}', {extra}, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list")
            return [line.strip() for line in out.splitlines() if line.strip()]

        try:
            require_ok(subprocess.run([str(binaries["pg_ctl"]), "-D", str(data_dir), "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"],
                                      text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120, check=False), "pg_start")
            started = True
            require_ok(sql("postgres", "create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;"), "roles")
            require_ok(run([str(binaries["createdb"]), "-h", "127.0.0.1", "-p", str(port), db]), "createdb")
            require_ok(sql(db, SCHEMA_SQL + """
                create table public.labeler_applications(user_id uuid primary key, display_name text not null, status text not null);
            """), "schema")
            for path in [*MIGRATIONS, V4_MIGRATION]:
                require_ok(sql(db, path.read_text(encoding="utf-8")), path.name)
            require_ok(sql(db, setup_sql()), "setup")
            require_ok(sql(db, f"""
                insert into public.labeler_applications(user_id, display_name, status) values ('{LABELER}', '김라벨', 'approved');
                insert into public.cameras(id, name) values ('{CAM_B}', 'probe-cam-b');
                update public.motion_clips set camera_id = '{CAM_B}', started_at = now() - interval '1 day' where id = '{CLIP['short']}';
            """), "extra")

            # 1) 배정 전 mine = 빈 목록, all = 운영 적격 7개(test 목적·격리 clip 은 제외)
            if list_ids("mine"):
                raise ProbeError("mine-before-assign: expected empty")
            all_ids = list_ids("all")
            if len(all_ids) != 7:
                raise ProbeError(f"all: expected 7 got {len(all_ids)}")
            if {CLIP["test_purpose"], CLIP["quarantined"]} & set(all_ids):
                raise ProbeError("all: non-production clip leaked into the list")
            # 2) 배정 → mine = CAM_A 6개, camera 필터로 CAM_B 만 → all 에서 1개
            expect("assign", q(f"select 'n|'||count(*)::text from public.fn_set_labeler_camera_assignments('{LABELER}', array['{CAM_A}']::uuid[], '{OWNER}');"), n="1")
            if len(list_ids("mine")) != 6:
                raise ProbeError("mine-after-assign: expected 6")
            if list_ids("all", f"array['{CAM_B}']::uuid[], null, null") != [CLIP["short"]]:
                raise ProbeError("camera-filter: expected only short clip")
            # 3) highlight 필터: yes = include/boundary×2, pending = pending clip
            yes = set(list_ids("all", "null, null, 'yes'"))
            if yes != {CLIP["include"], CLIP["boundary_activity"], CLIP["boundary_longest"]}:
                raise ProbeError(f"highlight-yes: {yes}")
            if list_ids("all", "null, null, 'pending'") != [CLIP["pending"]]:
                raise ProbeError("highlight-pending")
            # 4) 확정 → labeled/unlabeled 필터 + reviewer raw 컬럼(표시명 해석은 API 단일 resolver) + 잠금
            require_ok(sql(db, f"select * from public.fn_submit_highlight_verdict('{CLIP['short']}','{LABELER}',false,true,'initial','interesting_low_numbers','{ENGINE}','{ALGO}','{IDENTITY}');"), "verdict")
            # `select a union all select b from t` 는 FROM 이 마지막 select 에만 붙는다 → kv_select 로 한 row 를 펼친다.
            expect("labeled-row", q(kv_select(
                ["'src|'||highlight_source", "'val|'||highlight_value::text", "'who|'||reviewer_id::text", "'name|'||reviewer_display_name"],
                f"public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, 'labeled', null, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50)")),
                src="human", val="true", who=LABELER, name="김라벨")
            if CLIP["short"] in list_ids("all", "null, 'unlabeled', null"):
                raise ProbeError("unlabeled filter still contains labeled clip")
            require_sqlstate(sql(db, f"select * from public.fn_submit_highlight_verdict('{CLIP['short']}','{OWNER}',true,false,'initial',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), "lock", "PT409")
            # 5) cursor: limit 3 → 다음 페이지 첫 항목이 4번째
            first = require_ok(sql(db, f"select clip_id||'|'||started_at from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 3);"), "page1").splitlines()
            last_id, last_ts = first[-1].split("|", 1)
            page2 = require_ok(sql(db, f"select clip_id from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, '{ENGINE}','{ALGO}','{IDENTITY}', '{last_ts}', '{last_id}', 3);"), "page2").splitlines()
            if set(page2) & {line.split('|')[0] for line in first}:
                raise ProbeError("cursor: page overlap")
            require_sqlstate(sql(db, f"select * from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, '{ENGINE}','{ALGO}','{IDENTITY}', '{last_ts}', null, 3);"), "cursor-half", "22023")
            # 6) 현황 + 멤버 + 카메라
            expect("overview", q(f"select 'today|'||(public.fn_get_labeling_v4_overview('{ENGINE}','{ALGO}','{IDENTITY}')->>'labeled_today');"), today="1")
            expect("members", q("select 'n|'||count(*)::text from public.fn_list_labeling_v4_members();"), n="1")
            expect("overview-member", q(f"select 'uid|'||(m->>'user_id') from public.fn_get_labeling_v4_overview('{ENGINE}','{ALGO}','{IDENTITY}') o, jsonb_array_elements(o->'members') m;"), uid=LABELER)
            expect("cameras", q(f"select 'assigned|'||count(*) filter (where assigned)::text from public.fn_list_labeling_v4_cameras('{LABELER}');"), assigned="1")
            # 7) 권한
            expect("privs", q("select 'tables|'||count(*)::text from information_schema.role_table_grants where grantee in ('anon','authenticated','service_role') and table_name = 'labeler_camera_assignments';"), tables="0")
            print("LABELING_V4_PROBE_OK")
        finally:
            if started:
                subprocess.run([str(binaries["pg_ctl"]), "-D", str(data_dir), "-m", "immediate", "stop"], text=True, capture_output=True, timeout=120, check=False)
    print("PROBE_RESIDUE=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
