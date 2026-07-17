"""python_evidence_universal_worker 마이그레이션 정적 계약 테스트.

기존 migration 계약 테스트(test_clip_vlm_candidate_migration_contract.py)와 같은 방식:
DB 연결 없이 `.sql` 파일을 텍스트로 읽어 보안·큐·append-only 계약이 문자열로 존재하는지만 검증한다.
production 미적용 원칙(설계 §12) + donts/python#13(DB 의존 테스트 금지) 때문에 정적 계약으로 고정한다.

여기서 검증하는 것:
  - durable queue 테이블/결과 원장 테이블 + clip당 1 job(버전 unique)
  - live 우선 + `for update skip locked` claim 정렬
  - lease 회수 · stale 완료 거부 · terminal retry cap
  - motion_clips AFTER INSERT trigger (전 영상 enqueue) + 기존 clip 대량 enqueue 금지
  - append-only: UPDATE/DELETE/TRUNCATE role 무관 차단(SQLSTATE 0A000)
  - service_role only grant · RLS enabled · client policy 0 · search_path='' · fully-qualified
  - point cap 256 (jsonb_array_length)
"""

from __future__ import annotations

from pathlib import Path

SQL_PATH = Path("migrations/2026-07-17_python_evidence_universal_worker.sql")


def _sql() -> str:
    return SQL_PATH.read_text().lower()


def test_migration_file_exists():
    assert SQL_PATH.exists(), f"migration missing: {SQL_PATH}"


def test_creates_queue_and_run_tables():
    t = _sql()
    assert "create table public.python_evidence_jobs" in t
    assert "create table public.clip_python_evidence_runs" in t
    # 두 테이블 모두 motion_clips 에 FK + cascade
    assert "references public.motion_clips(id) on delete cascade" in t


def test_job_status_and_source_enums_closed():
    t = _sql()
    for status in ("queued", "processing", "succeeded", "failed_retryable", "failed_terminal"):
        assert status in t, f"missing job status: {status}"
    assert "check (source in ('live','historical'))" in t


def test_one_job_per_clip_and_version():
    t = _sql()
    # clip + evidence_schema_version + algorithm_version unique = clip당 활성버전 1 job
    assert "unique (clip_id, evidence_schema_version, algorithm_version)" in t


def test_claim_ordering_live_priority_skip_locked():
    t = _sql()
    assert "order by priority desc, created_at asc, id asc" in t
    assert "for update skip locked" in t


def test_lease_recovery_present():
    t = _sql()
    # lease 만료 processing 을 회수하는 컬럼 + 회수 로직
    assert "lease_expires_at" in t
    assert "status='failed_retryable'" in t or "status = 'failed_retryable'" in t


def test_claim_complete_fail_rpcs_exist():
    t = _sql()
    assert "function public.fn_claim_python_evidence_jobs" in t
    assert "function public.fn_complete_python_evidence_job" in t
    assert "function public.fn_fail_python_evidence_job" in t
    assert "function public.fn_insert_python_evidence_run" in t
    assert "function public.fn_enqueue_python_evidence_job" in t


def test_stale_completion_rejected_and_terminal_cap():
    t = _sql()
    # claimed_by 불일치/비-processing 완료 거부 (lease ownership)
    assert "claimed_by is distinct from p_worker_host" in t
    # 최대 attempt 후 terminal 전환
    assert "max_attempts" in t
    assert "'failed_terminal'" in t


def test_trigger_enqueues_every_motion_clip_live():
    t = _sql()
    assert "after insert on public.motion_clips" in t
    # trigger 는 live/priority 100/버전 리터럴로 원자 enqueue + 중복 no-op
    assert "values (new.id, 'live', 100" in t
    assert "'python-evidence-raw-v1'" in t
    assert "'croi-temporal-v1'" in t
    assert "on conflict (clip_id, evidence_schema_version, algorithm_version) do nothing" in t


def _sql_no_comments() -> str:
    """-- 주석 라인을 제거한 실행부만. rollback 주석 등이 negative 검증을 오염시키지 않게."""
    lines = [ln for ln in SQL_PATH.read_text().lower().splitlines() if not ln.strip().startswith("--")]
    return "\n".join(lines)


def test_migration_does_not_bulk_enqueue_existing_rows():
    t = _sql()
    assert "insert into public.python_evidence_jobs" in t  # trigger 안에는 존재
    # negative: 기존 clip 전량을 훑는 backfill INSERT ... SELECT 금지(설계 §5.1/§10).
    # 실행부에서 motion_clips 참조는 trigger 선언 + FK 두 군데뿐이어야 하고, from public.motion_clips
    # (대량 조회)나 그로부터의 INSERT ... SELECT 가 있으면 안 된다.
    body = _sql_no_comments()
    residual = body.replace("after insert on public.motion_clips", "").replace(
        "references public.motion_clips(id) on delete cascade", ""
    )
    assert "public.motion_clips" not in residual


def test_append_only_blocks_all_mutations_incl_service_role():
    t = _sql()
    # UPDATE/DELETE/TRUNCATE 를 role 무관 차단하는 trigger + SQLSTATE 0A000
    assert "before update on public.clip_python_evidence_runs" in t
    assert "before delete on public.clip_python_evidence_runs" in t
    assert "before truncate on public.clip_python_evidence_runs" in t
    assert "0a000" in t  # SQLSTATE feature_not_supported (append-only)


def test_run_result_is_append_only_idempotent_identity():
    t = _sql()
    # 결과 원장 멱등 identity: clip + 버전 + source_prelabel_identity
    assert "unique (clip_id, evidence_schema_version, algorithm_version, source_prelabel_identity)" in t
    # 동일 identity 재삽입은 no-op (기존 run 반환)
    assert "on conflict" in t and "do nothing" in t


def test_source_prelabel_identity_non_null_default_none():
    t = _sql()
    assert "source_prelabel_identity text not null default 'none'" in t


def test_point_cap_256_on_series():
    t = _sql()
    assert "jsonb_array_length" in t
    assert "<= 256" in t


def test_security_invoker_empty_search_path():
    t = _sql()
    # 모든 함수가 SECURITY INVOKER + search_path='' (fully-qualified 강제)
    assert "security invoker set search_path=''" in t
    # security definer 를 쓰지 않는다
    assert "security definer" not in t


def test_grants_service_role_only_and_rls_enabled():
    t = _sql()
    assert "enable row level security" in t
    assert "revoke all on public.python_evidence_jobs from public, anon, authenticated" in t
    assert "revoke all on public.clip_python_evidence_runs from public, anon, authenticated" in t
    assert "to service_role" in t
    # 함수 실행권도 service_role only
    assert "grant execute on function public.fn_claim_python_evidence_jobs" in t


def test_no_client_rls_policies():
    t = _sql()
    # 클라이언트(anon/authenticated) select policy 를 만들지 않는다 (policy 0, service_role bypass).
    assert "create policy" not in t


def test_failure_code_allowlist_present():
    t = _sql()
    # allowlist 실패 코드 CHECK (raw exception/URL 저장 금지 계약의 DB측 강제)
    assert "failure_code" in t
    assert "r2_download_failed" in t
    assert "decode_no_frames" in t
