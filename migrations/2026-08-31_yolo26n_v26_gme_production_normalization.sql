-- YOLO26n v2.6을 신규 production GME job의 detector identity로 전환한다.
-- v2.6 smoke 10건과 현재 v2.5 live 함수가 정확히 확인될 때만 한 transaction 안에서 진행한다.

do $$
declare
  smoke_complete integer;
  gme_trigger_count integer;
  current_function text;
begin
  if to_regclass('public.gme_jobs') is null or to_regclass('public.gme_runs') is null then
    raise exception 'v2.6 GME preflight failed: base schema missing';
  end if;

  select count(*) into smoke_complete
  from public.gme_jobs j
  join public.gme_runs r on j.result_run_id = r.id
  where j.source = 'smoke'
    and j.status = 'succeeded'
    and r.status = 'ok'
    and j.detector_identity = '89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7'
    and r.detector_identity = j.detector_identity
    and r.permanent_artifact_key is not null
    and r.permanent_artifact_sha256 ~ '^[0-9a-f]{64}$'
    and r.permanent_artifact_bytes > 0
    and r.debug_artifact_key is not null
    and r.debug_artifact_sha256 ~ '^[0-9a-f]{64}$'
    and r.debug_artifact_bytes > 0;
  if smoke_complete < 10 then
    raise exception 'v2.6 GME preflight failed: matching smoke complete below 10';
  end if;

  select count(*) into gme_trigger_count
  from pg_trigger
  where tgrelid = 'public.motion_clips'::regclass
    and tgname = 'trg_enqueue_gme_live_job'
    and not tgisinternal;
  if gme_trigger_count <> 1 then
    raise exception 'v2.6 GME preflight failed: unexpected live trigger state';
  end if;

  select pg_get_functiondef('public.fn_enqueue_gme_live_job()'::regprocedure)
    into current_function;
  if position(
    'd4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6'
    in current_function
  ) = 0 then
    raise exception 'v2.6 GME preflight failed: current v2.5 detector identity drift';
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
    '89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7'
  ) on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing;
  return new;
end $$;

revoke all on function public.fn_enqueue_gme_live_job() from public, anon, authenticated;
grant execute on function public.fn_enqueue_gme_live_job() to service_role;

create table public.yolo_demo_rate_limits (
  key_hash text primary key check (key_hash ~ '^[0-9a-f]{64}$'),
  window_started_at timestamptz not null,
  attempts integer not null check (attempts >= 1),
  updated_at timestamptz not null default now()
);

alter table public.yolo_demo_rate_limits enable row level security;
revoke all on table public.yolo_demo_rate_limits from public, anon, authenticated;
grant select, insert, update, delete on table public.yolo_demo_rate_limits to service_role;

create function public.fn_consume_yolo_demo_rate_limit(
  p_key_hash text,
  p_now timestamptz,
  p_limit integer,
  p_window_sec integer
) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare
  current_window timestamptz;
  current_attempts integer;
  retry_after_sec integer;
begin
  if p_key_hash is null or p_key_hash !~ '^[0-9a-f]{64}$'
     or p_now is null
     or p_limit is null or p_limit < 1 or p_limit > 1000
     or p_window_sec is null or p_window_sec < 1 or p_window_sec > 86400 then
    raise exception 'invalid yolo demo rate-limit contract';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(p_key_hash, 0));

  delete from public.yolo_demo_rate_limits
  where key_hash in (
    select key_hash
    from public.yolo_demo_rate_limits
    where window_started_at < p_now - interval '24 hours'
    order by window_started_at, key_hash
    limit 100
  );

  select window_started_at, attempts
    into current_window, current_attempts
  from public.yolo_demo_rate_limits
  where key_hash = p_key_hash
  for update;

  if not found then
    insert into public.yolo_demo_rate_limits (key_hash, window_started_at, attempts, updated_at)
    values (p_key_hash, p_now, 1, p_now);
    return jsonb_build_object('allowed', true, 'retry_after_sec', 0);
  end if;

  if p_now >= current_window + make_interval(secs => p_window_sec) then
    update public.yolo_demo_rate_limits
    set window_started_at = p_now, attempts = 1, updated_at = p_now
    where key_hash = p_key_hash;
    return jsonb_build_object('allowed', true, 'retry_after_sec', 0);
  end if;

  if current_attempts >= p_limit then
    retry_after_sec := greatest(
      1,
      ceil(extract(epoch from (current_window + make_interval(secs => p_window_sec) - p_now)))::integer
    );
    return jsonb_build_object('allowed', false, 'retry_after_sec', retry_after_sec);
  end if;

  update public.yolo_demo_rate_limits
  set attempts = attempts + 1, updated_at = p_now
  where key_hash = p_key_hash;
  return jsonb_build_object('allowed', true, 'retry_after_sec', 0);
end $$;

revoke all on function public.fn_consume_yolo_demo_rate_limit(text,timestamptz,integer,integer) from public, anon, authenticated;
grant execute on function public.fn_consume_yolo_demo_rate_limit(text,timestamptz,integer,integer) to service_role;

-- ROLLBACK CONTRACT (별도 승인된 단일 transaction에서 live 함수 본문만 v2.5로 복원):
-- create or replace function public.fn_enqueue_gme_live_job() returns trigger
-- language plpgsql security invoker set search_path='' as $$
-- begin
--   if new.clip_purpose <> 'production' then return new; end if;
--   insert into public.gme_jobs (
--     clip_id, source, priority, engine_schema_version, algorithm_version, detector_identity
--   ) values (
--     new.id, 'live', 100, 'gme-shadow-v1', 'gme-motion-v0',
--     'd4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6'
--   ) on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing;
--   return new;
-- end $$;
-- v2.5/v2.6 gme_jobs, gme_runs, artifact와 rate-limit 감사 row는 삭제하지 않는다.
