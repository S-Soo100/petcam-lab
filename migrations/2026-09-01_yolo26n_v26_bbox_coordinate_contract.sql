-- YOLO26n v2.6의 bbox 좌표 계약을 center-xywh에서 top-left-xywh로 바로잡은
-- 새 execution identity로 신규 production GME job을 전환한다.
-- 기존 job, run, artifact는 감사 이력으로 그대로 보존한다.

do $$
declare
  current_function text;
  claim_function text;
  gme_trigger_count integer;
begin
  if to_regclass('public.gme_jobs') is null
     or to_regclass('public.gme_runs') is null then
    raise exception 'v2.6 bbox coordinate transition failed: base schema missing';
  end if;

  if to_regprocedure(
    'public.fn_claim_gme_jobs_for_detector(integer,text,timestamptz,boolean,text)'
  ) is null then
    raise exception 'v2.6 bbox coordinate transition failed: identity-isolated claim RPC missing';
  end if;

  select pg_get_functiondef(to_regprocedure(
    'public.fn_claim_gme_jobs_for_detector(integer,text,timestamptz,boolean,text)'
  )) into claim_function;
  if regexp_count(
       claim_function,
       'detector_identity\s*=\s*p_detector_identity',
       1,
       'i'
     ) < 4
     or position('attempt_count >= max_attempts' in claim_function) = 0
     or position('attempt_count < max_attempts' in claim_function) = 0
     or position('for update skip locked' in claim_function) = 0
     or position('p_include_historical or c.source <> ''historical''' in claim_function) = 0
     or position('p_now + interval ''30 minutes''' in claim_function) = 0 then
    raise exception 'v2.6 bbox coordinate transition failed: identity-isolated claim RPC drift';
  end if;

  select count(*) into gme_trigger_count
  from pg_trigger
  where tgrelid = 'public.motion_clips'::regclass
    and tgname = 'trg_enqueue_gme_live_job'
    and tgfoid = 'public.fn_enqueue_gme_live_job()'::regprocedure
    and tgenabled = 'O'
    and not tgisinternal;
  if gme_trigger_count <> 1 then
    raise exception 'v2.6 bbox coordinate transition failed: unexpected live trigger state';
  end if;

  select pg_get_functiondef('public.fn_enqueue_gme_live_job()'::regprocedure)
    into current_function;
  if position(
    '89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7'
    in current_function
  ) = 0
     or regexp_count(
       current_function,
       '89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7'
     ) <> 1
     or position('new.clip_purpose <> ''production''' in current_function) = 0
     or position('new.id, ''live'', 100, ''gme-shadow-v1'', ''gme-motion-v0''' in current_function) = 0
     or position(
       'on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing'
       in current_function
     ) = 0 then
    raise exception 'v2.6 bbox coordinate transition failed: previous live identity drift';
  end if;
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
    'deccfc8315d3c00edb5bf59db3c573dca568e9d6d7a5da8d7dc93d2082bdb899'
  ) on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing;
  return new;
end $$;

revoke all on function public.fn_enqueue_gme_live_job() from public, anon, authenticated;
grant execute on function public.fn_enqueue_gme_live_job() to service_role;

-- ROLLBACK CONTRACT (별도 승인된 단일 transaction에서 live 함수 identity만 복원):
-- 이전 identity는 89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7이다.
-- 어느 identity의 job, run, artifact도 제거하거나 덮어쓰지 않는다.
