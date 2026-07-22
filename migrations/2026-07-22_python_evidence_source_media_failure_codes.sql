-- Python Evidence — R2 원본 소실/권한 오류 실패코드 추가 (forward-only, B1R2 Task 3).
--
-- 배경: 기존 worker 는 모든 R2 download 예외를 retryable `r2_download_failed` 로 처리했다. 역사
-- backfill 에서 보존창 초과로 삭제된 원본(404/NoSuchKey)은 재시도해도 없으므로 무한 재큐가 되어
-- worker cycle 이 계속 nonzero 로 끝난다(B1R 잔여 canary 28건 = 이 현상). B1R2 는 원본 소실을
-- `source_media_missing` terminal, 인증/권한 오류를 `r2_access_denied` terminal 로 분리한다(design §6).
--
-- forward-only 원칙: 기존 `2026-07-17_python_evidence_universal_worker.sql` 을 **수정하지 않고**,
-- `python_evidence_jobs_failure_code_check` CHECK 를 **같은 이름으로 교체**(drop if exists → add)한다.
-- 기존 9개 코드는 그대로 두고 `source_media_missing`·`r2_access_denied` 2개만 추가한다.
-- RLS/grant/테이블/기존 job row 는 건드리지 않는다(제약만 교체). raw exception/URL/secret 저장 금지 계약 유지.
-- Python 측 allowlist(reporter/python_evidence_store.py ALLOWED_FAILURE_CODES)와 1:1 (양쪽 테스트로 고정).

alter table public.python_evidence_jobs
  drop constraint if exists python_evidence_jobs_failure_code_check;

alter table public.python_evidence_jobs
  add constraint python_evidence_jobs_failure_code_check
  check (failure_code is null or failure_code in (
    'r2_download_failed','source_media_missing','r2_access_denied',
    'decode_no_frames','decode_insufficient_frames','invalid_metadata',
    'detector_failed','temporal_compute_failed','db_transient','db_error','internal_error'
  ));

-- rollback (참고용 — 실행 아님. 기존 9-code allowlist 로 되돌린다):
--   alter table public.python_evidence_jobs
--     drop constraint if exists python_evidence_jobs_failure_code_check;
--   alter table public.python_evidence_jobs
--     add constraint python_evidence_jobs_failure_code_check
--     check (failure_code is null or failure_code in (
--       'r2_download_failed','decode_no_frames','decode_insufficient_frames','invalid_metadata',
--       'detector_failed','temporal_compute_failed','db_transient','db_error','internal_error'));
