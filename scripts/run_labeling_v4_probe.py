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
    ALGO, CLIP, ENGINE, FLAGS, IDENTITY, LABELER, MIGRATIONS, OWNER, SCHEMA_SQL, STRANGER,
    ProbeError, expect, free_port, kv_select, parse_kv_lines, require_ok, require_sqlstate, run, setup_sql,
)

V4_MIGRATION = ROOT / "migrations" / "2026-09-08_labeling_v4_simplification.sql"
V4_LIST_CHUNKED_MIGRATION = ROOT / "migrations" / "2026-09-08_labeling_v4_list_chunked.sql"  # 성능 수정(CREATE OR REPLACE)
V4_AGGREGATES_MIGRATION = ROOT / "migrations" / "2026-09-08_highlight_aggregates_fast.sql"  # overview/stats 집계 교체
V4_BEHAVIOR_FLAGS_MIGRATION = ROOT / "migrations" / "2026-09-09_labeling_v4_behavior_flags.sql"  # 의미있는 행동 체크 + 13-인자 목록
V4_PROGRESS_MIGRATION = ROOT / "migrations" / "2026-09-09_labeling_v4_progress.sql"  # 라벨러 진행 집계(UX ③)
V4_VIEW_CLAIMS_MIGRATION = ROOT / "migrations" / "2026-09-09_labeling_v4_view_claims.sql"  # 보는 중 힌트(UX ⑤)
V4_COVERAGE_MIGRATION = ROOT / "migrations" / "2026-09-09_gme_contract_coverage.sql"  # 활성 계약 커버리지(2.6.1 전환 준비)
V4_EVAL_SAMPLES_MIGRATION = ROOT / "migrations" / "2026-09-09_labeling_v4_eval_samples.sql"  # 봉인 평가 표본 + 14-인자 목록
V4_FEATURED_MIGRATION = ROOT / "migrations" / "2026-09-10_highlight_featured_tier.sql"  # ⭐ 대표 tier(조회 시 계산)
V4_FEATURED_HOUR_CAP_MIGRATION = ROOT / "migrations" / "2026-09-11_highlight_featured_hour_cap.sql"  # v0.1: 10분 묶기·시간당 3·하루 상한 없음
V4_BEHAVIOR_MARKS_MIGRATION = ROOT / "migrations" / "2026-09-11_behavior_marks.sql"  # 표시 4종(kind) + 목록 집계 + 대표 v0.1.1(표시 집계·하루 예산 15)
V4_EVAL_SAMPLE_REMOVE_MIGRATION = ROOT / "migrations" / "2026-09-12_eval_sample_remove.sql"  # 표본 항목 제거(owner, 미확정만)
CAM_A = "40000000-0000-4000-8000-000000000001"  # setup_sql 이 만든 카메라
CAM_B = "40000000-0000-4000-8000-000000000002"
CAM_C = "40000000-0000-4000-8000-000000000003"  # §14 전용 카메라(마지막 섹션이라 다른 섹션 개수에 영향 없음)
FEAT = {k: f"50000000-0000-4000-8000-0000000000{i:02d}" for i, k in enumerate(
    ("a1", "a2", "b_flag", "c", "human_x", "prev_day", "rule_x", "h1", "h2", "h3"), start=1)}
# UTC 시각. 하루 경계 20:00 KST = 11:00Z. a1·a2 는 5분 간격 → 한 사건(합 27). human_x 는 05:00 KST(같은 하루). prev_day 는 19:30 KST → 전날.
# h1·h2·h3 는 a 사건과 같은 21시(KST) 안에 15분 간격 → 10분 묶기에선 별개 사건 4개(a·h1·h2·h3) → 시간당 3 상한에 h3 가 걸린다.
FEAT_AT = {"a1": "2026-09-01T12:00:00Z", "a2": "2026-09-01T12:05:00Z", "b_flag": "2026-09-01T15:00:00Z", "c": "2026-09-01T18:00:00Z",
           "human_x": "2026-09-01T20:00:00Z", "prev_day": "2026-09-01T10:30:00Z", "rule_x": "2026-09-01T21:00:00Z",
           "h1": "2026-09-01T12:20:00Z", "h2": "2026-09-01T12:35:00Z", "h3": "2026-09-01T12:50:00Z"}


def run_row(state: str, start: float, end: float) -> str:  # highlight probe 의 run_row 와 동일(그쪽 import 목록에 없어 로컬 정의)
    return f'{{"state":"{state}","start_sec":{start},"end_sec":{end},"track_ids":["g0001"]}}'


def _feat_job(n: int, clip: str) -> str:
    return f"('51{n:06d}-0000-4000-8000-000000000001','{clip}','historical',10,'{ENGINE}','{ALGO}','{IDENTITY}','succeeded')"


def _feat_run(n: int, clip: str, activity: float, intervals: str) -> str:
    # setup_sql 의 run_ 과 같은 23 컬럼. sha256 은 setup 과 겹치지 않게 '{n%10}e' 반복(n ≤ 10 이라 유일).
    return (f"('52{n:06d}-0000-4000-8000-000000000001','{clip}','51{n:06d}-0000-4000-8000-000000000001',"
            f"'{ENGINE}','{ALGO}','{IDENTITY}','probe','feat-{n}','ok',60,600,600,10,{activity},{activity},60,0,0,1,"
            f"'terra-derived/gme/v1/permanent/feat/{n}.json',repeat('{n % 10}e',32),1,'[{intervals}]'::jsonb)")


def featured_setup_sql() -> str:
    iv = {"a1": run_row("moving", 0, 12), "a2": run_row("moving", 0, 15), "b_flag": run_row("moving", 0, 20), "c": run_row("moving", 0, 11),
          "human_x": run_row("moving", 0, 30), "prev_day": run_row("moving", 0, 13),
          "rule_x": ",".join([run_row("moving", 0, 2), run_row("moving", 3, 6)]),  # activity 5 · longest 3 → 규칙 X
          "h1": run_row("moving", 0, 14), "h2": run_row("moving", 0, 13), "h3": run_row("moving", 0, 11)}
    act = {"a1": 12, "a2": 15, "b_flag": 20, "c": 11, "human_x": 30, "prev_day": 13, "rule_x": 5, "h1": 14, "h2": 13, "h3": 11}
    keys = list(FEAT)
    clips = ",".join(f"('{FEAT[k]}','{CAM_C}','{FEAT_AT[k]}',60,'terra-clips/clips/probe/{FEAT[k]}.mp4')" for k in keys)
    jobs = ",".join(_feat_job(i, FEAT[k]) for i, k in enumerate(keys, start=1))
    runs = ",".join(_feat_run(i, FEAT[k], act[k], iv[k]) for i, k in enumerate(keys, start=1))
    return f"""
    INSERT INTO public.cameras(id, name) VALUES ('{CAM_C}', 'probe-cam-c');
    INSERT INTO public.motion_clips(id, camera_id, started_at, duration_sec, r2_key) VALUES {clips};
    INSERT INTO public.gme_jobs(id,clip_id,source,priority,engine_schema_version,algorithm_version,detector_identity,status) VALUES {jobs};
    INSERT INTO public.gme_runs(id,clip_id,job_id,engine_schema_version,algorithm_version,detector_identity,
      producer_host,producer_run_id,status,duration_sec,decoded_frame_count,analyzed_frame_count,source_fps,
      candidate_moving_sec_any_gecko,moving_gecko_seconds,visible_sec,unknown_sec,camera_motion_sec,
      max_simultaneous_geckos,permanent_artifact_key,permanent_artifact_sha256,permanent_artifact_bytes,state_intervals) VALUES {runs};
    UPDATE public.gme_jobs j SET result_run_id = r.id FROM public.gme_runs r WHERE r.job_id = j.id AND j.result_run_id IS NULL;
    """


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
            require_ok(sql(db, SCHEMA_SQL), "schema")  # labeler_applications 는 공용 SCHEMA_SQL 에 있다(2026-09-08 집계 migration 이후)
            for path in [*[m for m in MIGRATIONS if m != V4_AGGREGATES_MIGRATION], V4_MIGRATION, V4_LIST_CHUNKED_MIGRATION, V4_AGGREGATES_MIGRATION, V4_BEHAVIOR_FLAGS_MIGRATION, V4_PROGRESS_MIGRATION, V4_VIEW_CLAIMS_MIGRATION, V4_COVERAGE_MIGRATION, V4_EVAL_SAMPLES_MIGRATION, V4_FEATURED_MIGRATION, V4_FEATURED_HOUR_CAP_MIGRATION, V4_BEHAVIOR_MARKS_MIGRATION, V4_EVAL_SAMPLE_REMOVE_MIGRATION]:
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
            expect("overview-camera", q(f"select 'sum|'||sum((c->>'unlabeled')::int)::text from public.fn_get_labeling_v4_overview('{ENGINE}','{ALGO}','{IDENTITY}') o, jsonb_array_elements(o->'cameras') c;"), sum=q(f"select 'sum|'||(public.fn_get_labeling_v4_overview('{ENGINE}','{ALGO}','{IDENTITY}')->>'unlabeled_total');")["sum"])
            expect("cameras", q(f"select 'assigned|'||count(*) filter (where assigned)::text from public.fn_list_labeling_v4_cameras('{LABELER}');"), assigned="1")
            # 7) 권한
            expect("privs", q("select 'tables|'||count(*)::text from information_schema.role_table_grants where grantee in ('anon','authenticated','service_role') and table_name = 'labeler_camera_assignments';"), tables="0")
            # 8) 의미있는 행동 체크: 체크(멱등·첫 체크자 유지) → 13-인자 목록 필터/컬럼 → 남의 해제 PT403 → owner 해제 → 비적격 P0002
            expect("flag-on", q(f"select 'f|'||flagged::text||'' from public.fn_set_motion_clip_behavior_flag('{CLIP['include']}','{LABELER}',false,true);"), f="true")
            expect("flag-idempotent", q(f"select 'by|'||flagged_by::text from public.fn_set_motion_clip_behavior_flag('{CLIP['include']}','{OWNER}',true,true);"), by=LABELER)
            expect("flag-get", q(f"select 'name|'||coalesce(flagged_by_display_name,'null') from public.fn_get_motion_clip_behavior_flag('{CLIP['include']}');"), name="김라벨")
            flagged = require_ok(sql(db, f"select clip_id||'|'||behavior_flagged::text||'|'||coalesce(behavior_flagged_by_display_name,'null') from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, 'yes', '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list-flag").splitlines()
            if flagged != [f"{CLIP['include']}|true|김라벨"]:
                raise ProbeError(f"list-flag: {flagged}")
            if len(list_ids("all")) != 7:
                raise ProbeError("wrapper-12-args: expected 7 after flag")
            require_sqlstate(sql(db, f"select * from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, 'no', '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "flag-filter-bad", "22023")
            require_sqlstate(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{CLIP['include']}','{STRANGER}',false,false);"), "unflag-stranger", "PT403")
            expect("unflag-owner", q(f"select 'f|'||flagged::text||'' from public.fn_set_motion_clip_behavior_flag('{CLIP['include']}','{OWNER}',true,false);"), f="false")
            expect("flag-self-on", q(f"select 'f|'||a.flagged::text||'' from public.fn_set_motion_clip_behavior_flag('{CLIP['short']}','{LABELER}',false,true) a;"), f="true")
            expect("unflag-self", q(f"select 'f|'||a.flagged::text||'' from public.fn_set_motion_clip_behavior_flag('{CLIP['short']}','{LABELER}',false,false) a;"), f="false")
            require_sqlstate(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{CLIP['test_purpose']}','{OWNER}',true,true);"), "flag-ineligible", "P0002")
            expect("flag-privs", q("select 'tables|'||count(*)::text from information_schema.role_table_grants where grantee in ('anon','authenticated','service_role') and table_name = 'motion_clip_behavior_flags';"), tables="0")
            expect("flag-rls", q("select 'rls|'||count(*)::text from pg_class where relname = 'motion_clip_behavior_flags' and relrowsecurity;"), rls="1")
            # 9) 진행 집계(UX ③): 라벨러(CAM_A 배정)는 mine=배정 카메라 미라벨 수, all=전체 미라벨 수, 오늘 내가 = 이 probe 에서 잠근 initial 수.
            #    위에서 short clip(CAM_B) 이 LABELER 확정 → labeled_today_me=1. 배정 없는 STRANGER 는 mine NULL.
            prog = q(kv_select(
                ["'me|'||(j->>'labeled_today_me')", "'mine|'||coalesce(j->>'unlabeled_mine','null')", "'all|'||(j->>'unlabeled_all')"],
                f"public.fn_get_labeling_v4_progress('{LABELER}') j"))
            unl_all = len(list_ids("all", "null, 'unlabeled', null"))
            unl_mine = len(list_ids("mine", "null, 'unlabeled', null"))
            expect("progress", prog, me="1", mine=str(unl_mine), all=str(unl_all))
            expect("progress-no-assign", q(f"select 'mine|'||coalesce(j->>'unlabeled_mine','null') from public.fn_get_labeling_v4_progress('{STRANGER}') j;"), mine="null")
            # 10) 보는 중 힌트(UX ⑤): 라벨러가 include 를 열면 claim, owner 기준 fresh 목록에 include 가 있고 본인(라벨러) 기준엔 없다.
            #     미존재 clip claim 은 조용히 무시. TTL 0 은 1초로 클램프.
            require_ok(sql(db, f"select public.fn_claim_motion_clip_view('{CLIP['include']}','{LABELER}');"), "claim")
            require_ok(sql(db, f"select public.fn_claim_motion_clip_view('00000000-0000-4000-8000-0000000000ff','{LABELER}');"), "claim-missing")
            fresh = require_ok(sql(db, f"select clip_id from public.fn_fresh_motion_clip_view_claims(array['{CLIP['include']}','{CLIP['short']}']::uuid[], '{OWNER}', 120);"), "fresh-owner").splitlines()
            if fresh != [CLIP['include']]:
                raise ProbeError(f"fresh-owner: {fresh}")
            if require_ok(sql(db, f"select clip_id from public.fn_fresh_motion_clip_view_claims(array['{CLIP['include']}']::uuid[], '{LABELER}', 120);"), "fresh-self").strip():
                raise ProbeError("fresh-self: own claim must not be returned")
            expect("claims-count", q("select 'n|'||count(*)::text from public.motion_clip_view_claims;"), n="1")
            expect("claims-privs", q("select 'tables|'||count(*)::text from information_schema.role_table_grants where grantee in ('anon','authenticated','service_role') and table_name = 'motion_clip_view_claims';"), tables="0")
            # 12) 활성 계약 커버리지: 미디어 있는 clip 전체 vs 활성 identity 로 succeeded job 이 있는 clip(queued 인 pending 은 제외).
            #     다른 identity 로 물으면 with_run 0. 기대값은 같은 DB 에서 직접 센다(시드 가정 없이).
            media_total = q("select 'n|'||count(*)::text from public.motion_clips where r2_key is not null;")["n"]
            with_run = q(f"select 'n|'||count(distinct j.clip_id)::text from public.gme_jobs j join public.motion_clips c on c.id = j.clip_id and c.r2_key is not null where j.status='succeeded' and j.engine_schema_version='{ENGINE}' and j.algorithm_version='{ALGO}' and j.detector_identity='{IDENTITY}';")["n"]
            cov = q(kv_select(["'all_total|'||(j->>'all_total')", "'all_with_run|'||(j->>'all_with_run')", "'last7d_total|'||(j->>'last7d_total')"],
                              f"public.fn_gme_contract_coverage('{ENGINE}','{ALGO}','{IDENTITY}') j"))
            expect("coverage", cov, all_total=media_total, all_with_run=with_run)
            if int(cov["last7d_total"]) > int(media_total):
                raise ProbeError("coverage: last7d exceeds total")
            expect("coverage-other-identity", q(f"select 'w|'||(public.fn_gme_contract_coverage('{ENGINE}','{ALGO}','{'b' * 64}')->>'all_with_run');"), w="0")
            # 13) 봉인 평가 표본: owner 등록(비적격 test_purpose 는 건너뜀·중복 무시) → 14-인자 목록 p_sample_id 필터 → 13-인자 wrapper 불변
            #     → 진행/보고(short 는 §4 에서 LABELER 확정됨) → 라벨러 등록 PT403 → 잘못된 id 22023
            items = (f"[{{\"clip_id\":\"{CLIP['include']}\",\"stratum\":\"a:O\"}},"
                     f"{{\"clip_id\":\"{CLIP['short']}\",\"stratum\":\"b:X\"}},"
                     f"{{\"clip_id\":\"{CLIP['test_purpose']}\",\"stratum\":\"z\"}}]")
            expect("sample-register", q(f"select 'n|'||public.fn_register_eval_sample('eval-probe', '{items}'::jsonb, '{OWNER}', true)::text;"), n="2")
            expect("sample-register-again", q(f"select 'n|'||public.fn_register_eval_sample('eval-probe', '{items}'::jsonb, '{OWNER}', true)::text;"), n="0")
            require_sqlstate(sql(db, f"select public.fn_register_eval_sample('eval-probe', '[]'::jsonb, '{LABELER}', false);"), "sample-labeler", "PT403")
            require_sqlstate(sql(db, f"select public.fn_register_eval_sample('BAD id', '[]'::jsonb, '{OWNER}', true);"), "sample-bad-id", "22023")
            sample_ids = require_ok(sql(db, f"select clip_id from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, null, 'eval-probe', '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list-sample").splitlines()
            if set(sample_ids) != {CLIP['include'], CLIP['short']}:
                raise ProbeError(f"list-sample: {sample_ids}")
            if len(list_ids("all")) != 7:
                raise ProbeError("wrapper-13-args after samples: expected 7")
            require_sqlstate(sql(db, f"select * from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, null, 'BAD id', '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list-sample-bad", "22023")
            expect("sample-progress", q(kv_select(["'total|'||total::text", "'labeled|'||labeled::text"], "public.fn_eval_sample_progress('eval-probe')")), total="2", labeled="1")
            expect("sample-report", q("select 'labeled|'||sum(labeled)::text||'' from public.fn_eval_sample_report('eval-probe');"), labeled="1")
            expect("sample-report-bx", q("select 'x_to_o|'||x_to_o::text||'' from public.fn_eval_sample_report('eval-probe') where stratum='b:X';"), x_to_o="1")  # short: 규칙 X, LABELER O(§4)
            expect("sample-privs", q("select 'tables|'||count(*)::text from information_schema.role_table_grants where grantee in ('anon','authenticated','service_role') and table_name = 'motion_clip_eval_samples';"), tables="0")
            # 13b) 표본 항목 제거(2026-09-12): 미확정 include 는 제거 1 · 확정된 short(§4) 는 보호 0 · 라벨러 PT403 · 빈 배열 22023 · 진행 total 2→1
            expect("sample-remove-unlabeled", q(f"select 'n|'||public.fn_remove_eval_sample_items('eval-probe', array['{CLIP['include']}']::uuid[], '{OWNER}', true)::text;"), n="1")
            expect("sample-remove-labeled-protected", q(f"select 'n|'||public.fn_remove_eval_sample_items('eval-probe', array['{CLIP['short']}']::uuid[], '{OWNER}', true)::text;"), n="0")
            require_sqlstate(sql(db, f"select public.fn_remove_eval_sample_items('eval-probe', array['{CLIP['short']}']::uuid[], '{LABELER}', false);"), "sample-remove-labeler", "PT403")
            require_sqlstate(sql(db, f"select public.fn_remove_eval_sample_items('eval-probe', array[]::uuid[], '{OWNER}', true);"), "sample-remove-empty", "22023")
            expect("sample-progress-after-remove", q(kv_select(["'total|'||total::text", "'labeled|'||labeled::text"], "public.fn_eval_sample_progress('eval-probe')")), total="1", labeled="1")
            expect("sample-remove-privs", q("select 'ok|'||(not has_function_privilege('authenticated', 'public.fn_remove_eval_sample_items(text,uuid[],uuid,boolean)', 'EXECUTE'))::text;"), ok="true")
            # 14) ⭐ 대표 tier v0.1(조회 시 계산, 10분 묶기·시간당 3·하루 상한 없음): CAM_C 에 2026-09-01 클립 10개. 기대:
            #     전날(prev_day 19:30 KST) 1위 featured · b_flag(✨) 1위 · a1+a2 한 사건(합 27, 5분 간격) 2위 — 대표 a2 featured, a1 candidate ·
            #     h1(14) 3위 · h2(13) 4위 · c(11, 03시) 5위 · h3(11, 21시) 6위 — h3 는 21시(KST) 안 4번째 사건이라 시간당 3 에 걸려 candidate ·
            #     human_x(사람 X)·rule_x(규칙 X) 는 아예 없음. 옛 인자(30분·하루 3)로 부르면 h1~h3 가 a 사건에 흡수돼 featured 4개.
            #     마지막 섹션: CAM_C 클립이 무필터 목록 개수를 바꾸므로 앞 섹션 뒤에 둔다.
            require_ok(sql(db, featured_setup_sql()), "featured-setup")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['b_flag']}','{LABELER}',false,true);"), "featured-flag")
            require_ok(sql(db, f"select * from public.fn_submit_highlight_verdict('{FEAT['human_x']}','{LABELER}',false,false,'initial','false_detection','{ENGINE}','{ALGO}','{IDENTITY}');"), "featured-human-x")
            feat_call = f"public.fn_highlight_featured(array['{CAM_C}']::uuid[], '2026-08-31T00:00:00Z', '2026-09-03T00:00:00Z', '{ENGINE}','{ALGO}','{IDENTITY}', null, 600, 20, 'Asia/Seoul', 3, 15)"
            feat_cols = "clip_id||'|'||tier||'|'||episode_rank||'|'||episode_hour_rank||'|'||is_representative||'|'||episode_clip_count||'|'||episode_activity_sec||'|'||day_key"
            got = require_ok(sql(db, f"select {feat_cols} from {feat_call} order by day_key, episode_rank, started_at;"), "featured").splitlines()
            want = [f"{FEAT['prev_day']}|featured|1|1|true|1|13.0|2026-08-31",
                    f"{FEAT['b_flag']}|featured|1|1|true|1|20.0|2026-09-01",
                    f"{FEAT['a1']}|candidate|2|1|false|2|27.0|2026-09-01",
                    f"{FEAT['a2']}|featured|2|1|true|2|27.0|2026-09-01",
                    f"{FEAT['h1']}|featured|3|2|true|1|14.0|2026-09-01",
                    f"{FEAT['h2']}|featured|4|3|true|1|13.0|2026-09-01",
                    f"{FEAT['c']}|featured|5|1|true|1|11.0|2026-09-01",
                    f"{FEAT['h3']}|candidate|6|4|true|1|11.0|2026-09-01"]
            if got != want:
                raise ProbeError(f"featured: got {got} want {want}")
            # 하루 상한 2 면 h1(3위) 부터 candidate · 시간당 상한 NULL 이면 h3 도 featured · 옛 기본 조합(30분·하루 3·시간당 없음)은 featured 4
            expect("featured-top2", q(f"select 'tier|'||tier from {feat_call.replace('null, 600', '2, 600')} where clip_id = '{FEAT['h1']}';"), tier="candidate")
            expect("featured-no-hour-cap", q(f"select 'tier|'||tier from {feat_call.replace(chr(39) + 'Asia/Seoul' + chr(39) + ', 3', chr(39) + 'Asia/Seoul' + chr(39) + ', null')} where clip_id = '{FEAT['h3']}';"), tier="featured")
            expect("featured-legacy-params", q(f"select 'n|'||count(*)::text from {feat_call.replace('null, 600, 20, ' + chr(39) + 'Asia/Seoul' + chr(39) + ', 3', '3, 1800, 20, ' + chr(39) + 'Asia/Seoul' + chr(39) + ', null')} where tier = 'featured';"), n="4")
            # 사람 O 가산: c 를 사람 O 로 확정하면 a 사건(27) 보다 위(2위) — ✨ 는 여전히 1위
            require_ok(sql(db, f"select * from public.fn_submit_highlight_verdict('{FEAT['c']}','{LABELER}',false,true,'initial',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), "featured-human-o")
            expect("featured-human-o-rank", q(f"select 'rank|'||episode_rank::text from {feat_call} where clip_id = '{FEAT['c']}';"), rank="2")
            expect("featured-source", q(f"select 'src|'||highlight_source||'' from {feat_call} where clip_id = '{FEAT['c']}';"), src="human")
            # 카메라 NULL(전체) 도 같은 8행(다른 섹션 클립은 now() 라 기간 밖) · 기간·top_n·hour_cap·tz 인자 검증 · 권한
            all_cams_call = feat_call.replace(f"array['{CAM_C}']::uuid[]", "null")
            expect("featured-all-cams", q(f"select 'n|'||count(*)::text from {all_cams_call};"), n="8")
            require_sqlstate(sql(db, f"select * from {feat_call.replace(chr(39) + 'Asia/Seoul' + chr(39) + ', 3', chr(39) + 'Asia/Seoul' + chr(39) + ', 11')};"), "featured-hour-cap", "22023")
            require_sqlstate(sql(db, f"select * from {feat_call.replace(chr(39) + '2026-08-31T00:00:00Z' + chr(39), chr(39) + '2026-07-01T00:00:00Z' + chr(39))};"), "featured-range", "22023")
            require_sqlstate(sql(db, f"select * from {feat_call.replace('null, 600', '0, 600')};"), "featured-top-n", "22023")
            require_sqlstate(sql(db, f"select * from {feat_call.replace('Asia/Seoul', 'Mars/Olympus')};"), "featured-tz", "22023")
            expect("featured-privs", q("select 'ok|'||(not has_function_privilege('authenticated', 'public.fn_highlight_featured(uuid[],timestamptz,timestamptz,text,text,text,integer,integer,integer,text,integer,integer)', 'EXECUTE'))::text;"), ok="true")
            # 하루 예산(v0.1.1): p_day_cap=2 → 09-01 은 사건 순위 1·2(b_flag·a2)만, 시간당 상한에 걸린 h3 는 예산을 안 먹음. 전날 prev_day 는 그대로 → featured 3.
            expect("featured-day-cap", q(f"select 'n|'||count(*)::text from {feat_call.replace(', 3, 15)', ', 3, 2)')} where tier = 'featured';"), n="3")
            require_sqlstate(sql(db, f"select * from {feat_call.replace(', 3, 15)', ', 3, 0)')};"), "featured-day-cap-bad", "22023")
            # 15) 행동 표시 4종: get 4행 · set(kind) · 옛 4-인자/단일 get 은 meaningful 만 · 목록 중복 없음·종류 필터 · 잘못된 kind 22023 · 남의 표시 해제 PT403 · 권한
            #     표시 뒤 대표: h1(🎡)·h2(🎡+⚠️) 는 flagged 라 b_flag(✨) 다음(activity 14 > 13) → 2·3위 featured, 추락만 있는 h3 는 승격 안 됨(시간당 4번째 → candidate).
            expect("marks-get-4", q(f"select 'n|'||count(*)::text from public.fn_get_motion_clip_behavior_flags('{FEAT['h1']}');"), n="4")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h1']}','{LABELER}',false,'wheel',true);"), "mark-wheel-h1")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h2']}','{LABELER}',false,'wheel',true);"), "mark-wheel-h2")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h2']}','{LABELER}',false,'fall',true);"), "mark-fall-h2")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h3']}','{LABELER}',false,'fall',true);"), "mark-fall-h3")
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['rule_x']}','{LABELER}',false,'closeup',true);"), "mark-closeup-rule-x")  # X 영상에도 📸 가능
            require_sqlstate(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h1']}','{LABELER}',false,'jump',true);"), "mark-bad-kind", "22023")
            require_sqlstate(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h2']}','{STRANGER}',false,'wheel',false);"), "unflag-stranger", "PT403")
            expect("marks-kinds-h2", q(f"select 'k|'||array_to_string(kinds, ',') from public.fn_get_motion_clip_behavior_kinds(array['{FEAT['h2']}']::uuid[]);"), k="wheel,fall")
            expect("legacy-get-h2", q(f"select 'f|'||flagged::text from public.fn_get_motion_clip_behavior_flag('{FEAT['h2']}');"), f="false")
            expect("legacy-get-b", q(f"select 'f|'||flagged::text from public.fn_get_motion_clip_behavior_flag('{FEAT['b_flag']}');"), f="true")
            expect("legacy-set-4arg", q(f"select 'f|'||flagged::text from public.fn_set_motion_clip_behavior_flag('{FEAT['h3']}','{LABELER}',false,true);"), f="true")  # meaningful 위임
            require_ok(sql(db, f"select * from public.fn_set_motion_clip_behavior_flag('{FEAT['h3']}','{LABELER}',false,'meaningful',false);"), "unmark-meaningful-h3")
            wheel_ids = require_ok(sql(db, f"select clip_id from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, 'wheel', null, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list-wheel").splitlines()
            if sorted(wheel_ids) != sorted([FEAT['h1'], FEAT['h2']]):
                raise ProbeError(f"list-wheel: {wheel_ids}")
            any_ids = require_ok(sql(db, f"select clip_id from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, 'yes', null, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list-any").splitlines()
            if len(any_ids) != len(set(any_ids)) or set(any_ids) != {FEAT['b_flag'], FEAT['h1'], FEAT['h2'], FEAT['h3'], FEAT['rule_x']}:
                raise ProbeError(f"list-any dup/set: {any_ids}")
            require_sqlstate(sql(db, f"select * from public.fn_list_labeling_v4_clips('{LABELER}', false, 'all', null, null, null, 'jump', null, '{ENGINE}','{ALGO}','{IDENTITY}', null, null, 50);"), "list-bad-kind", "22023")
            got5 = require_ok(sql(db, f"select clip_id||'|'||tier||'|'||episode_rank||'|'||coalesce(nullif(array_to_string(behavior_kinds, '+'), ''), '-') from {feat_call} where clip_id in ('{FEAT['h1']}','{FEAT['h2']}','{FEAT['h3']}','{FEAT['a2']}') order by episode_rank;"), "featured-marks").splitlines()
            want5 = [f"{FEAT['h1']}|featured|2|wheel", f"{FEAT['h2']}|featured|3|wheel+fall", f"{FEAT['a2']}|featured|5|-", f"{FEAT['h3']}|candidate|6|fall"]
            if got5 != want5:
                raise ProbeError(f"featured-marks: got {got5} want {want5}")
            expect("featured-rows-no-dup", q(f"select 'n|'||count(*)::text from {feat_call};"), n="8")  # h2 표시 2개여도 1행
            expect("marks-privs", q("select 'ok|'||(not has_function_privilege('authenticated', 'public.fn_set_motion_clip_behavior_flag(uuid,uuid,boolean,text,boolean)', 'EXECUTE'))::text;"), ok="true")
            print("LABELING_V4_PROBE_OK")
        finally:
            if started:
                subprocess.run([str(binaries["pg_ctl"]), "-D", str(data_dir), "-m", "immediate", "stop"], text=True, capture_output=True, timeout=120, check=False)
    print("PROBE_RESIDUE=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
