-- Canary가 통과한 뒤 새 production clip만 GME slow-motion v1으로 enqueue한다.
-- 기존 v0 job/run/artifact는 수정하지 않는다.

do $$
declare
  current_function text;
begin
  if to_regprocedure(
    'public.fn_claim_gme_jobs_for_contract(integer,text,timestamptz,boolean,text,text,text)'
  ) is null or to_regprocedure(
    'public.fn_get_gme_observed_moving_time_v2(uuid,text,text,text)'
  ) is null then
    raise exception 'GME v1 cutover failed: exact contract RPC missing';
  end if;

  select pg_get_functiondef('public.fn_enqueue_gme_live_job()'::regprocedure)
    into current_function;
  if position('deccfc8315d3c00edb5bf59db3c573dca568e9d6d7a5da8d7dc93d2082bdb899' in current_function) = 0
     or position('new.clip_purpose <> ''production''' in current_function) = 0
     or position('''gme-shadow-v1'', ''gme-motion-v0''' in current_function) = 0
     or position(
       'on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing'
       in current_function
     ) = 0 then
    raise exception 'GME v1 cutover failed: previous live trigger drift';
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
    new.id, 'live', 100, 'gme-shadow-v1', 'gme-motion-v1',
    'deccfc8315d3c00edb5bf59db3c573dca568e9d6d7a5da8d7dc93d2082bdb899'
  ) on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing;
  return new;
end $$;

revoke all on function public.fn_enqueue_gme_live_job() from public, anon, authenticated;
grant execute on function public.fn_enqueue_gme_live_job() to service_role;
