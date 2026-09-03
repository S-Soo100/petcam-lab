-- live 우선 정책도 active GME 계약만 보게 해 과거 계약의 stale job이 새 backfill을 막지 않게 한다.

create function public.fn_gme_operational_stats_for_contract(
  p_now timestamptz,
  p_detector_identity text,
  p_algorithm_version text,
  p_engine_schema_version text
) returns jsonb
language plpgsql security invoker set search_path='' as $$
begin
  if p_detector_identity is null or p_detector_identity !~ '^[0-9a-f]{64}$' then
    raise exception 'detector identity must be a lowercase SHA-256' using errcode='22023';
  end if;
  if p_algorithm_version is null or p_algorithm_version !~ '^gme-motion-v[0-9]+$' then
    raise exception 'invalid GME algorithm version' using errcode='22023';
  end if;
  if p_engine_schema_version <> 'gme-shadow-v1' then
    raise exception 'invalid GME engine schema version' using errcode='22023';
  end if;

  return (
    select jsonb_build_object(
      'queued_live', count(*) filter (
        where source='live' and status in ('queued','failed_retryable')
      ),
      'queued_historical', count(*) filter (
        where source='historical' and status in ('queued','failed_retryable')
      ),
      'processing', count(*) filter (where status='processing'),
      'terminal', count(*) filter (where status='failed_terminal'),
      'oldest_live_age_sec', coalesce(extract(epoch from p_now - (
        min(created_at) filter (
          where source='live' and status in ('queued','failed_retryable')
        )
      )), 0)
    )
    from public.gme_jobs
    where detector_identity = p_detector_identity
      and algorithm_version = p_algorithm_version
      and engine_schema_version = p_engine_schema_version
  );
end $$;

revoke all on function public.fn_gme_operational_stats_for_contract(timestamptz,text,text,text)
  from public, anon, authenticated;
grant execute on function public.fn_gme_operational_stats_for_contract(timestamptz,text,text,text)
  to service_role;
