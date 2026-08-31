-- 기존 v2.5 legacy claim RPC를 바꾸지 않고, 새 worker가 자기 detector identity job만 claim하게 한다.
-- 이 migration은 live trigger/model/web을 전환하지 않는 pre-smoke 안전장치다.

do $$
begin
  if to_regclass('public.gme_jobs') is null then
    raise exception 'GME identity claim preflight failed: base queue missing';
  end if;
end $$;

create function public.fn_claim_gme_jobs_for_detector(
  p_limit integer,
  p_worker_host text,
  p_now timestamptz,
  p_include_historical boolean default true,
  p_detector_identity text default null
) returns setof public.gme_jobs
language plpgsql security invoker set search_path='' as $$
begin
  if p_limit is null or p_limit < 1 or p_limit > 200 then
    raise exception 'p_limit out of range' using errcode='22023';
  end if;
  if p_worker_host is null or btrim(p_worker_host) = '' then
    raise exception 'worker host required' using errcode='22023';
  end if;
  if p_detector_identity is null or p_detector_identity !~ '^[0-9a-f]{64}$' then
    raise exception 'detector identity must be a lowercase SHA-256' using errcode='22023';
  end if;

  -- 다른 detector의 lease/attempt 상태까지 정규화하지 않는다.
  update public.gme_jobs
    set status='failed_terminal', failure_code='internal_error', completed_at=p_now,
        claimed_at=null, claimed_by=null, lease_expires_at=null, updated_at=p_now
    where detector_identity = p_detector_identity
      and (
        (status='processing' and lease_expires_at is not null and lease_expires_at < p_now)
        or status='failed_retryable'
      )
      and attempt_count >= max_attempts;

  update public.gme_jobs
    set status='failed_retryable', next_attempt_at=p_now, claimed_at=null, claimed_by=null,
        lease_expires_at=null, updated_at=p_now
    where detector_identity = p_detector_identity
      and status='processing'
      and lease_expires_at is not null
      and lease_expires_at < p_now
      and attempt_count < max_attempts;

  return query
  update public.gme_jobs j
    set status='processing', claimed_by=p_worker_host, claimed_at=p_now,
        lease_expires_at=p_now + interval '30 minutes', attempt_count=j.attempt_count+1, updated_at=p_now
    where j.detector_identity = p_detector_identity
      and j.id in (
        select c.id from public.gme_jobs c
        where c.detector_identity = p_detector_identity
          and c.status in ('queued','failed_retryable')
          and c.attempt_count < c.max_attempts
          and (c.next_attempt_at is null or c.next_attempt_at <= p_now)
          and (p_include_historical or c.source <> 'historical')
        order by priority desc, created_at asc, id asc
        for update skip locked
        limit p_limit
      )
    returning j.*;
end $$;

revoke all on function public.fn_claim_gme_jobs_for_detector(integer,text,timestamptz,boolean,text) from public, anon, authenticated;
grant execute on function public.fn_claim_gme_jobs_for_detector(integer,text,timestamptz,boolean,text) to service_role;
