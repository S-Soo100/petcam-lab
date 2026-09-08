"""highlight rule v0 migration을 일회용 PostgreSQL에서 실증한다. production 연결 0."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    ROOT / "migrations" / "2026-08-03_gecko_motion_engine_shadow.sql",
    ROOT / "migrations" / "2026-09-03_gme_observed_moving_time_v1.sql",
    ROOT / "migrations" / "2026-09-03_gme_slow_motion_v1_contract.sql",
    # 운영 적격 가드(fn_is_motion_clip_production_labeling_eligible) — highlight/v4 RPC 의 선행 계약.
    ROOT / "migrations" / "2026-08-06_motion_clip_purpose_labeling_guard.sql",
    ROOT / "migrations" / "2026-09-08_highlight_rule_v0.sql",
    ROOT / "migrations" / "2026-09-08_highlight_aggregates_fast.sql",  # stats/overview 집계 교체(CREATE OR REPLACE)
    ROOT / "migrations" / "2026-09-09_highlight_reason_gecko_visible.sql",  # 사유 enum + submit 검증 + stats 키(UX ⑥)
    ROOT / "migrations" / "2026-09-10_highlight_quality_stats.sql",
]
# 두 probe 공용 최소 스키마. clip_purpose 컬럼·exclusions 테이블은 08-06 가드가 요구한다.
SCHEMA_SQL = """
    create extension if not exists pgcrypto;
    create schema auth; create table auth.users(id uuid primary key);
    create table public.cameras(id uuid primary key, name text);
    create table public.motion_clips(id uuid primary key, camera_id uuid references public.cameras(id),
      started_at timestamptz not null default now(), duration_sec double precision, r2_key text,
      clip_purpose text not null default 'production');
    create table public.motion_clip_system_exclusions(clip_id uuid primary key, state text not null);
    -- 집계 migration 이 overview 도 함께 교체하므로 참조 테이블만 빈 껍데기로 둔다.
    create table public.labeler_applications(user_id uuid primary key, display_name text not null, status text not null);
    create table public.labelers(user_id uuid primary key);
    grant select on public.motion_clips, public.cameras, public.labelers, public.motion_clip_system_exclusions to service_role;
"""
# VERBOSITY=verbose 여야 psql stderr 에 SQLSTATE(PT409 등)가 찍힌다(기본은 메시지만).
FLAGS = ("-X", "-v", "ON_ERROR_STOP=1", "-v", "VERBOSITY=verbose", "-qAt")
ENGINE, ALGO, IDENTITY = "gme-shadow-v1", "gme-motion-v1", "a" * 64
CLIP = {k: f"00000000-0000-4000-8000-00000000000{i}" for i, k in enumerate(
    ("include", "boundary_activity", "boundary_longest", "short", "not_observed", "pending", "shadow_only",
     "test_purpose", "quarantined"), start=1)}  # 뒤 둘은 운영 비적격(목록 제외·확정 P0002)
LABELER = "30000000-0000-4000-8000-000000000001"
OWNER = "30000000-0000-4000-8000-000000000002"
STRANGER = "30000000-0000-4000-8000-000000000003"


class ProbeError(RuntimeError):
    pass


def parse_kv_lines(out: str) -> dict[str, str]:
    """psql -qAt 로 찍은 `key|value` 줄들을 dict 로."""
    parsed: dict[str, str] = {}
    for line in out.splitlines():
        if "|" in line:
            key, value = line.split("|", 1)
            parsed[key.strip()] = value.strip()
    return parsed


def expect(label: str, parsed: dict[str, str], **want: str) -> None:
    for key, value in want.items():
        got = parsed.get(key)
        if got != value:
            raise RuntimeError(f"{label}: {key} expected {value!r} got {got!r}")


def run(argv: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, input=input_text, text=True, capture_output=True, timeout=120, check=False)


def require_ok(result: subprocess.CompletedProcess[str], label: str) -> str:
    if result.returncode != 0:
        raise ProbeError(f"{label}:{(result.stderr or result.stdout).strip()[:1500]}")
    return (result.stdout or "").strip()


def require_sqlstate(result: subprocess.CompletedProcess[str], label: str, sqlstate: str) -> None:
    if result.returncode == 0 or sqlstate not in (result.stderr or ""):
        raise ProbeError(f"{label}: expected SQLSTATE {sqlstate}, got rc={result.returncode} {result.stderr[:400]}")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_row(state: str, start: float, end: float) -> str:
    return f'{{"state":"{state}","start_sec":{start},"end_sec":{end},"track_ids":["g0001"]}}'


def kv_select(exprs: list[str], from_clause: str) -> str:
    """한 row 를 `key|value` 여러 줄로 펼친다. (`select a union all select b from t` 는 FROM 이 마지막 select 에만 붙어 깨진다.)"""
    return f"select unnest(array[{', '.join(exprs)}]) from {from_clause};"


def setup_sql() -> str:
    def job(n: int, clip: str, status: str) -> str:
        return (f"('1000000{n}-0000-4000-8000-000000000001','{clip}','historical',10,"
                f"'{ENGINE}','{ALGO}','{IDENTITY}','{status}')")

    def run_(n: int, clip: str, activity: float, visible: float, intervals: str) -> str:
        # sha256 CHECK 가 ^[0-9a-f]{64}$ 라 숫자 n 을 반복한다(chr(96+7)='g' 는 hex 가 아님).
        return (f"('2000000{n}-0000-4000-8000-000000000001','{clip}','1000000{n}-0000-4000-8000-000000000001',"
                f"'{ENGINE}','{ALGO}','{IDENTITY}','probe','probe-{n}','ok',60,600,600,10,{activity},{activity},"
                f"{visible},0,0,1,'terra-derived/gme/v1/permanent/probe/{n}.json',repeat('{n}',64),1,"
                f"'[{intervals}]'::jsonb)")

    intervals = {
        "include": ",".join([run_row("moving", 0, 12.5)]),
        "boundary_activity": ",".join([run_row("moving", 0, 4), run_row("static", 4, 10), run_row("moving", 10, 16)]),  # activity=10.0, longest=6 → 트리거 둘 다
        "boundary_longest": ",".join([run_row("moving", 0, 5.0)]),  # activity=5.0(<10), longest=5.0(>=5) → O
        "short": ",".join([run_row("moving", 0, 4.9)]),  # activity 4.9, longest 4.9 → X
        "not_observed": "",
        "shadow_only": ",".join([run_row("moving", 0, 1.0)] + [run_row("moving", i, i + 0.3) for i in range(2, 12)]),  # activity 4, bursts 11, first 0 → shadow frequent_bursts+early_action, X
    }
    return f"""
    INSERT INTO auth.users(id) VALUES ('{LABELER}'),('{OWNER}'),('{STRANGER}');
    INSERT INTO public.labelers(user_id) VALUES ('{LABELER}');
    INSERT INTO public.cameras(id, name) VALUES ('40000000-0000-4000-8000-000000000001','probe-cam');
    INSERT INTO public.motion_clips(id, camera_id, started_at, duration_sec, r2_key)
      SELECT id::uuid, '40000000-0000-4000-8000-000000000001', now(), 60, 'terra-clips/clips/probe/'||id||'.mp4' FROM unnest(ARRAY[{",".join("'" + v + "'" for v in CLIP.values())}]) AS id;
    UPDATE public.motion_clips SET clip_purpose = 'test' WHERE id = '{CLIP['test_purpose']}';
    INSERT INTO public.motion_clip_system_exclusions(clip_id, state) VALUES ('{CLIP['quarantined']}', 'quarantined');
    INSERT INTO public.gme_jobs(id,clip_id,source,priority,engine_schema_version,algorithm_version,detector_identity,status) VALUES
      {job(1, CLIP['include'], 'succeeded')},
      {job(2, CLIP['boundary_activity'], 'succeeded')},
      {job(3, CLIP['boundary_longest'], 'succeeded')},
      {job(4, CLIP['short'], 'succeeded')},
      {job(5, CLIP['not_observed'], 'succeeded')},
      {job(6, CLIP['pending'], 'queued')},
      {job(7, CLIP['shadow_only'], 'succeeded')};
    INSERT INTO public.gme_runs(id,clip_id,job_id,engine_schema_version,algorithm_version,detector_identity,
      producer_host,producer_run_id,status,duration_sec,decoded_frame_count,analyzed_frame_count,source_fps,
      candidate_moving_sec_any_gecko,moving_gecko_seconds,visible_sec,unknown_sec,camera_motion_sec,
      max_simultaneous_geckos,permanent_artifact_key,permanent_artifact_sha256,permanent_artifact_bytes,state_intervals) VALUES
      {run_(1, CLIP['include'], 12.5, 60, intervals['include'])},
      {run_(2, CLIP['boundary_activity'], 10.0, 60, intervals['boundary_activity'])},
      {run_(3, CLIP['boundary_longest'], 5.0, 60, intervals['boundary_longest'])},
      {run_(4, CLIP['short'], 4.9, 60, intervals['short'])},
      {run_(5, CLIP['not_observed'], 0, 0, intervals['not_observed'])},
      {run_(7, CLIP['shadow_only'], 4.0, 60, intervals['shadow_only'])};
    UPDATE public.gme_jobs j SET result_run_id = r.id FROM public.gme_runs r WHERE r.job_id = j.id;
    """


def main() -> int:
    # LC_ALL 이 비어 있으면 macOS 에서 postmaster 가 "became multithreaded during startup" 으로 죽는다.
    # 클러스터는 어차피 --no-locale 이라 C 로 고정해도 의미가 같다(호출자의 유효한 locale 은 덮어쓰지 않음).
    os.environ.setdefault("LC_ALL", "C")
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-bin", type=Path, required=True)
    args = parser.parse_args()
    binaries = {n: args.pg_bin / n for n in ("psql", "initdb", "pg_ctl", "createdb")}
    for path in binaries.values():
        if not path.is_file():
            raise ProbeError(f"missing:{path.name}")
    port = free_port()
    db = "highlight_rule_v0_probe"
    with tempfile.TemporaryDirectory(prefix="highlight-rule-v0-pg-") as tmp:
        data_dir = Path(tmp) / "data"
        require_ok(run([str(binaries["initdb"]), "-D", str(data_dir), "--auth=trust", "--no-locale"]), "initdb")
        started = False

        def sql(database: str, statement: str) -> subprocess.CompletedProcess[str]:
            return run([str(binaries["psql"]), "-h", "127.0.0.1", "-p", str(port), "-d", database, *FLAGS], input_text=statement)

        def q(statement: str) -> dict[str, str]:
            return parse_kv_lines(require_ok(sql(db, statement), statement[:60]))

        try:
            require_ok(subprocess.run([str(binaries["pg_ctl"]), "-D", str(data_dir), "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"],
                                      text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120, check=False), "pg_start")
            started = True
            require_ok(sql("postgres", "create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;"), "roles")
            require_ok(run([str(binaries["createdb"]), "-h", "127.0.0.1", "-p", str(port), db]), "createdb")
            require_ok(sql(db, SCHEMA_SQL), "schema")
            for path in MIGRATIONS:
                require_ok(sql(db, path.read_text(encoding="utf-8")), path.name)
            require_ok(sql(db, setup_sql()), "setup")

            def initial(clip: str) -> dict[str, str]:
                return q(kv_select(
                    ["'status|'||status", "'initial|'||coalesce(initial::text,'null')", "'fired|'||fired::text", "'shadow|'||shadow::text"],
                    f"public.fn_highlight_initial('{clip}','{ENGINE}','{ALGO}','{IDENTITY}')"))

            # 1) seed + active
            expect("active", q("select 'version|'||version from public.fn_get_active_highlight_rule();"), version="hl-rule-v0")
            # 2) eval 경계
            expect("include", initial(CLIP["include"]), status="decided", initial="true", fired="{long_activity,sustained_move}")
            expect("boundary_activity", initial(CLIP["boundary_activity"]), initial="true")
            expect("boundary_longest", initial(CLIP["boundary_longest"]), initial="true", fired="{sustained_move}")
            expect("short", initial(CLIP["short"]), initial="false", fired="{}")
            expect("not_observed", initial(CLIP["not_observed"]), status="decided", initial="false")
            expect("pending", initial(CLIP["pending"]), status="pending", initial="null")
            expect("shadow_only", initial(CLIP["shadow_only"]), initial="false", shadow="{frequent_bursts,early_action}")
            # 3) submit: labeler 확정, 잠금, stranger 거부, correction owner-only
            expect("submit", q(f"select 'changed|'||changed::text||'' from public.fn_submit_highlight_verdict('{CLIP['include']}','{LABELER}',false,false,'initial','false_detection','{ENGINE}','{ALGO}','{IDENTITY}');"), changed="true")
            require_sqlstate(sql(db, f"select * from public.fn_submit_highlight_verdict('{CLIP['include']}','{OWNER}',true,true,'initial',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), "lock", "PT409")
            require_sqlstate(sql(db, f"select * from public.fn_submit_highlight_verdict('{CLIP['short']}','{STRANGER}',false,true,'initial',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), "stranger", "PT403")
            require_sqlstate(sql(db, f"select * from public.fn_submit_highlight_verdict('{CLIP['include']}','{LABELER}',false,true,'correction',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), "correction-by-labeler", "PT403")
            expect("owner-correction", q(f"select 'initial|'||initial::text from public.fn_submit_highlight_verdict('{CLIP['include']}','{OWNER}',true,true,'correction',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), initial="true")
            expect("current-human", q(kv_select(
                ["'source|'||source", "'value|'||value::text", "'kind|'||verdict_kind"],
                f"public.fn_highlight_current('{CLIP['include']}','{ENGINE}','{ALGO}','{IDENTITY}')")), source="human", value="true", kind="correction")
            expect("current-rule", q(kv_select(
                ["'source|'||source", "'value|'||value::text"],
                f"public.fn_highlight_current('{CLIP['short']}','{ENGINE}','{ALGO}','{IDENTITY}')")), source="rule", value="false")
            expect("pending-verdict", q(f"select 'changed|'||coalesce(changed::text,'null') from public.fn_submit_highlight_verdict('{CLIP['pending']}','{LABELER}',false,true,'initial',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), changed="null")
            # 3a) 미관측 X 를 X 그대로 두되 '게코 보여·하이라이트 아님' 사유(검출기 누락 신호)를 남긴다 — changed=false, 사유 저장, 모르는 사유는 22023
            expect("visible-not-highlight", q(f"select 'changed|'||changed::text||'' from public.fn_submit_highlight_verdict('{CLIP['not_observed']}','{LABELER}',false,false,'initial','gecko_visible_not_highlight','{ENGINE}','{ALGO}','{IDENTITY}');"), changed="false")
            expect("visible-reason-stored", q(f"select 'r|'||change_reason from public.motion_clip_highlight_verdicts where clip_id='{CLIP['not_observed']}' and kind='initial';"), r="gecko_visible_not_highlight")
            require_sqlstate(sql(db, f"select * from public.fn_submit_highlight_verdict('{CLIP['boundary_activity']}','{LABELER}',false,true,'initial','nope','{ENGINE}','{ALGO}','{IDENTITY}');"), "bad-reason", "22023")
            # 3b) 운영 비적격(test 목적·격리)·미존재는 같은 P0002 — 존재 여부를 새지 않는다.
            require_sqlstate(sql(db, f"select * from public.fn_submit_highlight_verdict('{CLIP['test_purpose']}','{OWNER}',true,true,'initial',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), "test-purpose", "P0002")
            require_sqlstate(sql(db, f"select * from public.fn_submit_highlight_verdict('{CLIP['quarantined']}','{OWNER}',true,true,'initial',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), "quarantined", "P0002")
            require_sqlstate(sql(db, f"select * from public.fn_submit_highlight_verdict('00000000-0000-4000-8000-0000000000ff','{OWNER}',true,true,'initial',null,'{ENGINE}','{ALGO}','{IDENTITY}');"), "missing-clip", "P0002")
            # 4) 규칙 버전 생성 + 활성화 + 잘못된 트리거 거부
            expect("v1", q(f"select 'version|'||version from public.fn_create_highlight_rule_version('hl-rule-v1', '{{\"triggers\":[{{\"name\":\"long_activity\",\"on\":true,\"activity_sec_gte\":12}}]}}'::jsonb, 'probe', '{OWNER}');"), version="hl-rule-v1")
            expect("active-v1", q("select 'version|'||version from public.fn_get_active_highlight_rule();"), version="hl-rule-v1")
            require_sqlstate(sql(db, f"select * from public.fn_create_highlight_rule_version('hl-rule-v2', '{{\"triggers\":[{{\"name\":\"nope\",\"on\":true}}]}}'::jsonb, 'bad', '{OWNER}');"), "unknown-trigger", "22023")
            expect("old-verdict-immutable", q(f"select 'rule|'||rule_version from public.motion_clip_highlight_verdicts where clip_id='{CLIP['include']}' and kind='initial';"), rule="hl-rule-v0")
            # 4b) 필수 숫자 키 누락은 이름별로 거부(AND 단락으로 새던 frequent_bursts.bursts_gte 포함). 문자열 숫자도 거부.
            require_sqlstate(sql(db, f"select * from public.fn_create_highlight_rule_version('hl-rule-v2', '{{\"triggers\":[{{\"name\":\"frequent_bursts\",\"on\":true,\"activity_sec_gte\":3}}]}}'::jsonb, 'bad', '{OWNER}');"), "missing-bursts_gte", "22023")
            require_sqlstate(sql(db, f"select * from public.fn_create_highlight_rule_version('hl-rule-v2', '{{\"triggers\":[{{\"name\":\"long_activity\",\"on\":true,\"activity_sec_gte\":\"10\"}}]}}'::jsonb, 'bad', '{OWNER}');"), "string-number", "22023")
            # 4c) 기존 버전 재활성화(되돌리기) — event append 만, 모르는 버전은 P0002.
            expect("reactivate-v0", q(f"select 'version|'||version from public.fn_activate_highlight_rule_version('hl-rule-v0', '{OWNER}');"), version="hl-rule-v0")
            expect("active-v0-again", q("select 'version|'||version from public.fn_get_active_highlight_rule();"), version="hl-rule-v0")
            require_sqlstate(sql(db, f"select * from public.fn_activate_highlight_rule_version('hl-rule-v9', '{OWNER}');"), "activate-unknown", "P0002")
            expect("activation-events", q("select 'n|'||count(*)::text from public.highlight_rule_activation_events;"), n="3")
            # 5) stats
            expect("stats", q(kv_select(
                ["'n|'||sum(verdict_count)::text", "'d|'||sum(decided_count)::text", "'x|'||sum(o_to_x)::text"],
                "public.fn_highlight_rule_stats(now()-interval '1 hour', now()+interval '1 hour') where rule_version='hl-rule-v0'")), n="3", d="2", x="1")
            expect("stats-reasons", q("select 'fd|'||coalesce((reason_counts->>'false_detection'),'0') from public.fn_highlight_rule_stats(now()-interval '1 hour', now()+interval '1 hour') where rule_version='hl-rule-v0' limit 1;"), fd="1")
            expect("stats-visible-reason", q("select 'gv|'||coalesce(sum((reason_counts->>'gecko_visible_not_highlight')::int),0)::text from public.fn_highlight_rule_stats(now()-interval '1 hour', now()+interval '1 hour') where rule_version='hl-rule-v0';"), gv="1")
            # 6) append-only + 권한
            require_sqlstate(sql(db, "update public.motion_clip_highlight_verdicts set verdict = false;"), "append-only", "0A000")
            require_sqlstate(sql(db, "delete from public.highlight_rule_versions;"), "append-only-rules", "0A000")
            expect("privs", q("select 'tables|'||count(*)::text from information_schema.role_table_grants where grantee in ('anon','authenticated','service_role') and table_name in ('highlight_rule_versions','highlight_rule_activation_events','motion_clip_highlight_verdicts');"), tables="0")
            expect("rls", q("select 'rls|'||count(*)::text from pg_class where relname in ('highlight_rule_versions','highlight_rule_activation_events','motion_clip_highlight_verdicts') and relrowsecurity;"), rls="3")
            require_ok(sql(db, (ROOT / "tests/sql/highlight_quality_probe.sql").read_text()), "quality-probe")
            print("HIGHLIGHT_RULE_V0_PROBE_OK")
        finally:
            if started:
                subprocess.run([str(binaries["pg_ctl"]), "-D", str(data_dir), "-m", "immediate", "stop"], text=True, capture_output=True, timeout=120, check=False)
    print("PROBE_RESIDUE=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
