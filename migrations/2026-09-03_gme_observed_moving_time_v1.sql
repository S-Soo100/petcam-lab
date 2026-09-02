-- GME 관측 움직임 시간 v1 읽기 계약.
-- append-only gme_runs를 정본으로 두고, 호출자가 고정한 detector identity만 해석한다.
-- 이 migration은 기존 job/run/clip을 변경하지 않는다.

create function public.fn_get_gme_observed_moving_time_v1(
  p_clip_id uuid,
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
     or p_detector_identity is null
     or p_detector_identity !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid GME observed-moving-time request' using errcode='22023';
  end if;

  if not exists (select 1 FROM public.motion_clips c WHERE c.id = p_clip_id) then
    raise exception 'motion clip not found' using errcode='P0002';
  end if;

  -- count와 대표 id를 한 statement snapshot에서 고정해 동시 insert가 job 선택을 바꾸지 못하게 한다.
  select
    count(*),
    (array_agg(j.id order by j.created_at asc, j.id asc))[1]
  into v_job_count, v_job_id
  from public.gme_jobs j
  where j.clip_id = p_clip_id
    and j.detector_identity = p_detector_identity;

  -- live trigger/backfill이 아직 job을 만들지 않은 eligible clip도 과거 값으로 대체하지 않고 pending이다.
  IF v_job_count = 0 THEN
    return query select
      null::uuid,
      p_detector_identity,
      'pending'::text,
      NULL::numeric,
      NULL::numeric,
      NULL::numeric,
      NULL::numeric;
    return;
  end if;

  -- 같은 detector identity가 서로 다른 engine/algorithm job에 중복 사용되면 현재값이 모호하므로 실패한다.
  IF v_job_count > 1 THEN
    raise exception 'ambiguous GME detector identity for clip' using ERRCODE='PT500';
  end if;

  select j.* into v_job
  from public.gme_jobs j
  where j.id = v_job_id;

  if v_job.status IN ('queued','processing','failed_retryable') then
    return query select
      null::uuid,
      p_detector_identity,
      'pending'::text,
      null::numeric,
      null::numeric,
      null::numeric,
      null::numeric;
    return;
  end if;

  if v_job.status = 'failed_terminal' then
    return query select
      null::uuid,
      p_detector_identity,
      'failed'::text,
      null::numeric,
      null::numeric,
      null::numeric,
      null::numeric;
    return;
  end if;

  if v_job.status <> 'succeeded' or v_job.result_run_id is null then
    return query select
      v_job.result_run_id,
      p_detector_identity,
      'failed'::text,
      null::numeric,
      null::numeric,
      null::numeric,
      null::numeric;
    return;
  end if;

  select r.* into v_run
  from public.gme_runs r
  where r.id = v_job.result_run_id
    and r.job_id = v_job.id
    and r.clip_id = v_job.clip_id
    and r.detector_identity = v_job.detector_identity
    and r.engine_schema_version = v_job.engine_schema_version
    and r.algorithm_version = v_job.algorithm_version;

  -- succeeded 상태의 exact run이 없거나 정상 분석 run이 아니면 숫자를 만들지 않는다.
  if v_run.id is null or v_run.status <> 'ok' then
    return query select
      v_job.result_run_id,
      p_detector_identity,
      'failed'::text,
      null::numeric,
      null::numeric,
      null::numeric,
      null::numeric;
    return;
  end if;

  if v_run.status = 'ok' and v_run.visible_sec > 0 then
    return query select
      v_run.id,
      p_detector_identity,
      'measured'::text,
      v_run.candidate_moving_sec_any_gecko,
      v_run.visible_sec,
      v_run.unknown_sec,
      v_run.camera_motion_sec;
    return;
  end if;

  if v_run.status = 'ok' and v_run.visible_sec = 0 then
    return query select
      v_run.id,
      p_detector_identity,
      'not_observed'::text,
      null::numeric,
      v_run.visible_sec,
      v_run.unknown_sec,
      v_run.camera_motion_sec;
    return;
  end if;

  -- DB 불변식으로 도달할 수 없어야 하지만, 미지 상태를 숫자 0으로 강등하지 않는다.
  return query select
    v_job.result_run_id,
    p_detector_identity,
    'failed'::text,
    null::numeric,
    null::numeric,
    null::numeric,
    null::numeric;
end $$;

revoke all on function public.fn_get_gme_observed_moving_time_v1(uuid, text)
  from public, anon, authenticated;
grant execute on function public.fn_get_gme_observed_moving_time_v1(uuid, text)
  to service_role;
