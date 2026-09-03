-- GME v1을 v0와 함께 안전하게 운용하기 위한 exact contract RPC.
-- 기존 job/run/trigger는 변경하지 않는다.

create function public.fn_claim_gme_jobs_for_contract(
  p_limit integer,
  p_worker_host text,
  p_now timestamptz,
  p_include_historical boolean,
  p_detector_identity text,
  p_algorithm_version text,
  p_engine_schema_version text
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
  if p_algorithm_version is null or p_algorithm_version !~ '^gme-motion-v[0-9]+$' then
    raise exception 'invalid GME algorithm version' using errcode='22023';
  end if;
  if p_engine_schema_version <> 'gme-shadow-v1' then
    raise exception 'invalid GME engine schema version' using errcode='22023';
  end if;

  update public.gme_jobs
    set status='failed_terminal', failure_code='internal_error', completed_at=p_now,
        claimed_at=null, claimed_by=null, lease_expires_at=null, updated_at=p_now
    where detector_identity = p_detector_identity
      and algorithm_version = p_algorithm_version
      and engine_schema_version = p_engine_schema_version
      and (
        (status='processing' and lease_expires_at is not null and lease_expires_at < p_now)
        or status='failed_retryable'
      )
      and attempt_count >= max_attempts;

  update public.gme_jobs
    set status='failed_retryable', next_attempt_at=p_now, claimed_at=null, claimed_by=null,
        lease_expires_at=null, updated_at=p_now
    where detector_identity = p_detector_identity
      and algorithm_version = p_algorithm_version
      and engine_schema_version = p_engine_schema_version
      and status='processing'
      and lease_expires_at is not null
      and lease_expires_at < p_now
      and attempt_count < max_attempts;

  return query
  update public.gme_jobs j
    set status='processing', claimed_by=p_worker_host, claimed_at=p_now,
        lease_expires_at=p_now + interval '30 minutes', attempt_count=j.attempt_count+1, updated_at=p_now
    where j.detector_identity = p_detector_identity
      and j.algorithm_version = p_algorithm_version
      and j.engine_schema_version = p_engine_schema_version
      and j.id in (
        select c.id from public.gme_jobs c
        where c.detector_identity = p_detector_identity
          and c.algorithm_version = p_algorithm_version
          and c.engine_schema_version = p_engine_schema_version
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

revoke all on function public.fn_claim_gme_jobs_for_contract(integer,text,timestamptz,boolean,text,text,text)
  from public, anon, authenticated;
grant execute on function public.fn_claim_gme_jobs_for_contract(integer,text,timestamptz,boolean,text,text,text)
  to service_role;

create function public.fn_get_gme_observed_moving_time_v2(
  p_clip_id uuid,
  p_engine_schema_version text,
  p_algorithm_version text,
  p_detector_identity text
) returns table (
  run_id uuid,
  detector_identity text,
  measurement_status text,
  moving_time_sec numeric,
  visible_sec numeric,
  unknown_sec numeric,
  camera_motion_sec numeric
)
language plpgsql security invoker set search_path='' as $$
declare
  v_job_count integer;
  v_job_id uuid;
  v_job public.gme_jobs%rowtype;
  v_run public.gme_runs%rowtype;
begin
  if p_clip_id is null
     or p_engine_schema_version <> 'gme-shadow-v1'
     or p_algorithm_version is null
     or p_algorithm_version !~ '^gme-motion-v[0-9]+$'
     or p_detector_identity is null
     or p_detector_identity !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid GME observed-moving-time request' using errcode='22023';
  end if;

  if not exists (select 1 from public.motion_clips c where c.id = p_clip_id) then
    raise exception 'motion clip not found' using errcode='P0002';
  end if;

  select count(*), (array_agg(j.id order by j.created_at asc, j.id asc))[1]
  into v_job_count, v_job_id
  from public.gme_jobs j
  where j.clip_id = p_clip_id
    and j.engine_schema_version = p_engine_schema_version
    and j.algorithm_version = p_algorithm_version
    and j.detector_identity = p_detector_identity;

  if v_job_count = 0 then
    return query select null::uuid, p_detector_identity, 'pending'::text,
      null::numeric, null::numeric, null::numeric, null::numeric;
    return;
  end if;
  if v_job_count > 1 then
    raise exception 'ambiguous exact GME contract for clip' using errcode='PT500';
  end if;

  select j.* into v_job from public.gme_jobs j where j.id = v_job_id;
  if v_job.status in ('queued','processing','failed_retryable') then
    return query select null::uuid, p_detector_identity, 'pending'::text,
      null::numeric, null::numeric, null::numeric, null::numeric;
    return;
  end if;
  if v_job.status = 'failed_terminal' then
    return query select null::uuid, p_detector_identity, 'failed'::text,
      null::numeric, null::numeric, null::numeric, null::numeric;
    return;
  end if;
  if v_job.status <> 'succeeded' or v_job.result_run_id is null then
    return query select v_job.result_run_id, p_detector_identity, 'failed'::text,
      null::numeric, null::numeric, null::numeric, null::numeric;
    return;
  end if;

  select r.* into v_run
  from public.gme_runs r
  where r.id = v_job.result_run_id
    and r.job_id = v_job.id
    and r.clip_id = v_job.clip_id
    and r.engine_schema_version = p_engine_schema_version
    and r.algorithm_version = p_algorithm_version
    and r.detector_identity = p_detector_identity;

  if v_run.id is null or v_run.status <> 'ok' then
    return query select v_job.result_run_id, p_detector_identity, 'failed'::text,
      null::numeric, null::numeric, null::numeric, null::numeric;
    return;
  end if;
  if v_run.visible_sec > 0 then
    return query select v_run.id, p_detector_identity, 'measured'::text,
      v_run.candidate_moving_sec_any_gecko, v_run.visible_sec,
      v_run.unknown_sec, v_run.camera_motion_sec;
    return;
  end if;
  if v_run.visible_sec = 0 then
    return query select v_run.id, p_detector_identity, 'not_observed'::text,
      null::numeric, v_run.visible_sec, v_run.unknown_sec, v_run.camera_motion_sec;
    return;
  end if;
  return query select v_job.result_run_id, p_detector_identity, 'failed'::text,
    null::numeric, null::numeric, null::numeric, null::numeric;
end $$;

revoke all on function public.fn_get_gme_observed_moving_time_v2(uuid,text,text,text)
  from public, anon, authenticated;
grant execute on function public.fn_get_gme_observed_moving_time_v2(uuid,text,text,text)
  to service_role;
