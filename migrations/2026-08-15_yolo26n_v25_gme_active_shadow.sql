-- YOLO26n v2.5를 GME active shadow의 신규 live detector identity로 전환한다.
-- 선행 조건: 동일 identity의 production smoke 10건 성공. 기존 job/run과 원본 media는 불변이다.

do $$
declare
  smoke_complete integer;
  gme_trigger_count integer;
  wrong_worker_claims integer;
  current_function text;
begin
  if to_regclass('public.gme_jobs') is null or to_regclass('public.gme_runs') is null then
    raise exception 'v2.5 GME preflight failed: base schema missing';
  end if;

  select count(*) into smoke_complete
  from public.gme_jobs j
  join public.gme_runs r on j.result_run_id = r.id
  where j.source = 'smoke'
    and j.status = 'succeeded'
    and j.detector_identity = 'd4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6'
    and r.detector_identity = j.detector_identity;
  if smoke_complete < 10 then
    raise exception 'v2.5 GME preflight failed: matching smoke complete below 10';
  end if;

  select count(*) into gme_trigger_count
  from pg_trigger
  where tgrelid = 'public.motion_clips'::regclass
    and tgname = 'trg_enqueue_gme_live_job'
    and not tgisinternal;
  if gme_trigger_count <> 1 then
    raise exception 'v2.5 GME preflight failed: unexpected live trigger state';
  end if;

  select pg_get_functiondef('public.fn_enqueue_gme_live_job()'::regprocedure)
    into current_function;
  if position(
    '7997e853e851ac6592e03d13e7d5098ebfcbcb49b408077d83d7d6359df60a2a'
    in current_function
  ) = 0 then
    raise exception 'v2.5 GME preflight failed: current detector identity drift';
  end if;

  -- 구형 RF-DETR LaunchAgent가 v2.5 historical queue를 먼저 claim한 단일 사고만 복구한다.
  -- run/artifact가 없는 정확히 10건이 아니면 범위를 추측하지 않고 전체 migration을 중단한다.
  select count(*) into wrong_worker_claims
  from public.gme_jobs j
  where j.source = 'historical'
    and j.detector_identity = 'd4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6'
    and j.result_run_id is null
    and j.attempt_count = 1
    and j.status in ('processing','failed_terminal')
    and (j.failure_code is null or j.failure_code = 'gme_compute_failed');
  if wrong_worker_claims <> 10 then
    raise exception 'v2.5 GME preflight failed: wrong-worker incident count drift';
  end if;

  update public.gme_jobs j
  set status = 'queued', attempt_count = 0, failure_code = null,
      next_attempt_at = null, claimed_at = null, claimed_by = null,
      lease_expires_at = null, completed_at = null, updated_at = now()
  where j.source = 'historical'
    and j.detector_identity = 'd4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6'
    and j.result_run_id is null
    and j.attempt_count = 1
    and j.status in ('processing','failed_terminal')
    and (j.failure_code is null or j.failure_code = 'gme_compute_failed');
end $$;

create or replace function public.fn_enqueue_gme_live_job() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if new.clip_purpose <> 'production' then
    return new;
  end if;

  insert into public.gme_jobs (
    clip_id, source, priority, engine_schema_version, algorithm_version, detector_identity
  ) values (
    new.id, 'live', 100, 'gme-shadow-v1', 'gme-motion-v0',
    'd4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6'
  ) on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing;
  return new;
end $$;

revoke all on function public.fn_enqueue_gme_live_job() from public, anon, authenticated;
grant execute on function public.fn_enqueue_gme_live_job() to service_role;

-- ROLLBACK CONTRACT (별도 승인된 단일 transaction에서 함수 본문만 복원):
--   create or replace function public.fn_enqueue_gme_live_job() returns trigger
--   language plpgsql security invoker set search_path='' as $$
--   begin
--     insert into public.gme_jobs (
--       clip_id, source, priority, engine_schema_version, algorithm_version, detector_identity
--     ) values (
--       new.id, 'live', 100, 'gme-shadow-v1', 'gme-motion-v0',
--       '7997e853e851ac6592e03d13e7d5098ebfcbcb49b408077d83d7d6359df60a2a'
--     ) on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing;
--     return new;
--   end $$;
--   GME history remains append-only; v2.5 job/run/artifact는 제거하지 않는다.
