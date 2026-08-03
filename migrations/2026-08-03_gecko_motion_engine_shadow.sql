-- Gecko Motion Engine production shadow base schema.
-- Forward-only: durable queue + append-only candidate ledger. 이 base migration은 live trigger를 만들지 않는다.
-- 원본 motion_clips/R2, GT, activity-v1, VLM, 앱 데이터는 변경하지 않는다.

create table public.gme_jobs (
  id uuid primary key default gen_random_uuid(),
  clip_id uuid not null references public.motion_clips(id) on delete restrict,
  source text not null check (source in ('smoke','live','historical')),
  priority integer not null check (priority >= 0),
  engine_schema_version text not null,
  algorithm_version text not null,
  detector_identity text not null check (detector_identity ~ '^[0-9a-f]{64}$'),
  status text not null default 'queued'
    check (status in ('queued','processing','succeeded','failed_retryable','failed_terminal')),
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 5 check (max_attempts between 1 and 20),
  next_attempt_at timestamptz,
  claimed_at timestamptz,
  claimed_by text,
  lease_expires_at timestamptz,
  failure_code text check (failure_code is null or failure_code in (
    'r2_download_failed','source_media_missing','r2_access_denied','decode_no_frames',
    'invalid_metadata','detector_failed','gme_compute_failed','artifact_upload_failed',
    'db_transient','internal_error'
  )),
  result_run_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (clip_id, engine_schema_version, algorithm_version, detector_identity)
);

create index idx_gme_jobs_claim
  on public.gme_jobs (status, priority desc, created_at asc, id asc);
create index idx_gme_jobs_lease
  on public.gme_jobs (status, lease_expires_at);

create table public.gme_runs (
  id uuid primary key default gen_random_uuid(),
  clip_id uuid not null references public.motion_clips(id) on delete restrict,
  job_id uuid not null references public.gme_jobs(id) on delete restrict,
  engine_schema_version text not null,
  algorithm_version text not null,
  detector_identity text not null check (detector_identity ~ '^[0-9a-f]{64}$'),
  detector_provenance jsonb not null default '{}'::jsonb
    check (jsonb_typeof(detector_provenance) = 'object'),
  tracker_provenance jsonb not null default '{}'::jsonb
    check (jsonb_typeof(tracker_provenance) = 'object'),
  engine_provenance jsonb not null default '{}'::jsonb
    check (jsonb_typeof(engine_provenance) = 'object'),
  producer_host text not null,
  producer_run_id text not null,
  producer_code_ref text,
  status text not null check (status in ('ok','no_decodable_frames','invalid_metadata','decode_error')),
  duration_sec numeric not null check (duration_sec >= 0),
  decoded_frame_count integer not null check (decoded_frame_count >= 0),
  analyzed_frame_count integer not null check (analyzed_frame_count >= 0),
  source_fps numeric check (source_fps is null or source_fps > 0),
  candidate_moving_sec_any_gecko numeric not null check (candidate_moving_sec_any_gecko >= 0),
  moving_gecko_seconds numeric not null check (moving_gecko_seconds >= 0),
  visible_sec numeric not null check (visible_sec >= 0),
  unknown_sec numeric not null check (unknown_sec >= 0),
  camera_motion_sec numeric not null check (camera_motion_sec >= 0),
  check (candidate_moving_sec_any_gecko <= visible_sec),
  check (moving_gecko_seconds >= candidate_moving_sec_any_gecko),
  check (visible_sec + unknown_sec + camera_motion_sec <= duration_sec + 0.001),
  max_simultaneous_geckos integer not null check (max_simultaneous_geckos >= 0),
  state_intervals jsonb not null default '[]'::jsonb
    check (jsonb_typeof(state_intervals) = 'array' and jsonb_array_length(state_intervals) <= 10000),
  tracking_quality jsonb not null default '{}'::jsonb
    check (jsonb_typeof(tracking_quality) = 'object'),
  permanent_artifact_key text not null
    check (permanent_artifact_key like 'terra-derived/gme/v1/permanent/%'),
  permanent_artifact_sha256 text not null
    check (permanent_artifact_sha256 ~ '^[0-9a-f]{64}$'),
  permanent_artifact_bytes integer not null check (permanent_artifact_bytes > 0),
  debug_artifact_key text
    check (debug_artifact_key is null or debug_artifact_key like 'terra-derived/gme/v1/debug-14d/%'),
  debug_artifact_sha256 text
    check (debug_artifact_sha256 is null or debug_artifact_sha256 ~ '^[0-9a-f]{64}$'),
  debug_artifact_bytes integer
    check (debug_artifact_bytes is null or debug_artifact_bytes > 0),
  created_at timestamptz not null default now(),
  unique (clip_id, engine_schema_version, algorithm_version, detector_identity, permanent_artifact_sha256)
);

create index idx_gme_runs_clip on public.gme_runs (clip_id, created_at desc);
create index idx_gme_runs_job on public.gme_runs (job_id);

alter table public.gme_jobs
  add constraint fk_gme_jobs_result_run
  foreign key (result_run_id) references public.gme_runs(id) on delete restrict;

alter table public.gme_jobs enable row level security;
alter table public.gme_runs enable row level security;
revoke all on public.gme_jobs from public, anon, authenticated;
revoke all on public.gme_runs from public, anon, authenticated;
grant all on public.gme_jobs to service_role;
grant all on public.gme_runs to service_role;

create function public.fn_block_gme_run_mutation() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  raise exception 'gme_runs is append-only (insert-only)' using errcode='0A000';
end $$;
create trigger trg_block_gme_run_update
  before update on public.gme_runs for each row execute function public.fn_block_gme_run_mutation();
create trigger trg_block_gme_run_delete
  before delete on public.gme_runs for each row execute function public.fn_block_gme_run_mutation();
create trigger trg_block_gme_run_truncate
  before truncate on public.gme_runs for each statement execute function public.fn_block_gme_run_mutation();

create function public.fn_enqueue_gme_jobs(
  p_clip_ids uuid[], p_source text, p_priority integer,
  p_engine_schema_version text, p_algorithm_version text, p_detector_identity text
) returns integer
language plpgsql security invoker set search_path='' as $$
declare inserted_count integer;
begin
  if p_source not in ('smoke','live','historical') then
    raise exception 'invalid source' using errcode='22023';
  end if;
  if p_priority is null or p_priority < 0 or p_priority > 1000 then
    raise exception 'invalid priority' using errcode='22023';
  end if;
  if p_clip_ids is null or cardinality(p_clip_ids) < 1 or cardinality(p_clip_ids) > 1000 then
    raise exception 'clip ids out of range' using errcode='22023';
  end if;
  if p_engine_schema_version is null or btrim(p_engine_schema_version) = ''
     or p_algorithm_version is null or btrim(p_algorithm_version) = ''
     or p_detector_identity !~ '^[0-9a-f]{64}$' then
    raise exception 'invalid GME identity' using errcode='22023';
  end if;
  insert into public.gme_jobs (
    clip_id, source, priority, engine_schema_version, algorithm_version, detector_identity
  )
  select c.id, p_source, p_priority, p_engine_schema_version, p_algorithm_version, p_detector_identity
  from public.motion_clips c
  join (select distinct unnest(p_clip_ids) as id) requested on requested.id=c.id
  on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing;
  get diagnostics inserted_count = row_count;
  return inserted_count;
end $$;

create function public.fn_claim_gme_jobs(
  p_limit integer, p_worker_host text, p_now timestamptz, p_include_historical boolean default true
) returns setof public.gme_jobs
language plpgsql security invoker set search_path='' as $$
begin
  if p_limit is null or p_limit < 1 or p_limit > 200 then
    raise exception 'p_limit out of range' using errcode='22023';
  end if;
  if p_worker_host is null or btrim(p_worker_host) = '' then
    raise exception 'worker host required' using errcode='22023';
  end if;
  -- 죽은 worker가 max_attempts를 우회해 poison clip을 영원히 재claim하지 못하게 먼저 terminal 정규화한다.
  update public.gme_jobs
    set status='failed_terminal', failure_code='internal_error', completed_at=p_now,
        claimed_at=null, claimed_by=null, lease_expires_at=null, updated_at=p_now
    where (
      (status='processing' and lease_expires_at is not null and lease_expires_at < p_now)
      or status='failed_retryable'
    ) and attempt_count >= max_attempts;
  update public.gme_jobs
    set status='failed_retryable', next_attempt_at=p_now, claimed_at=null, claimed_by=null,
        lease_expires_at=null, updated_at=p_now
    where status='processing' and lease_expires_at is not null and lease_expires_at < p_now
      and attempt_count < max_attempts;
  return query
  update public.gme_jobs j
    set status='processing', claimed_by=p_worker_host, claimed_at=p_now,
        lease_expires_at=p_now + interval '30 minutes', attempt_count=j.attempt_count+1, updated_at=p_now
    where j.id in (
      select c.id from public.gme_jobs c
      where c.status in ('queued','failed_retryable')
        and c.attempt_count < c.max_attempts
        and (c.next_attempt_at is null or c.next_attempt_at <= p_now)
        and (p_include_historical or c.source <> 'historical')
      order by priority desc, created_at asc, id asc
      for update skip locked
      limit p_limit
    )
    returning j.*;
end $$;

create function public.fn_insert_gme_run(p_run jsonb) returns public.gme_runs
language plpgsql security invoker set search_path='' as $$
declare r public.gme_runs%rowtype; j public.gme_jobs%rowtype;
begin
  if jsonb_typeof(coalesce(p_run->'state_intervals','[]'::jsonb)) <> 'array'
     or jsonb_array_length(coalesce(p_run->'state_intervals','[]'::jsonb)) > 10000 then
    raise exception 'state_intervals must be bounded array' using errcode='22023';
  end if;
  if jsonb_typeof(coalesce(p_run->'tracking_quality','{}'::jsonb)) <> 'object'
     or jsonb_typeof(coalesce(p_run->'detector_provenance','{}'::jsonb)) <> 'object'
     or jsonb_typeof(coalesce(p_run->'tracker_provenance','{}'::jsonb)) <> 'object'
     or jsonb_typeof(coalesce(p_run->'engine_provenance','{}'::jsonb)) <> 'object' then
    raise exception 'provenance/quality must be objects' using errcode='22023';
  end if;
  select * into j from public.gme_jobs where id=(p_run->>'job_id')::uuid for update;
  if not found then raise exception 'job not found' using errcode='22023'; end if;
  if j.clip_id <> (p_run->>'clip_id')::uuid
     or j.engine_schema_version <> p_run->>'engine_schema_version'
     or j.algorithm_version <> p_run->>'algorithm_version'
     or j.detector_identity <> p_run->>'detector_identity' then
    raise exception 'run payload does not match job' using errcode='22023';
  end if;
  insert into public.gme_runs (
    clip_id, job_id, engine_schema_version, algorithm_version, detector_identity,
    detector_provenance, tracker_provenance, engine_provenance,
    producer_host, producer_run_id, producer_code_ref, status,
    duration_sec, decoded_frame_count, analyzed_frame_count, source_fps,
    candidate_moving_sec_any_gecko, moving_gecko_seconds, visible_sec, unknown_sec, camera_motion_sec,
    max_simultaneous_geckos, state_intervals, tracking_quality,
    permanent_artifact_key, permanent_artifact_sha256, permanent_artifact_bytes,
    debug_artifact_key, debug_artifact_sha256, debug_artifact_bytes
  ) values (
    (p_run->>'clip_id')::uuid, (p_run->>'job_id')::uuid,
    p_run->>'engine_schema_version', p_run->>'algorithm_version', p_run->>'detector_identity',
    coalesce(p_run->'detector_provenance','{}'::jsonb), coalesce(p_run->'tracker_provenance','{}'::jsonb),
    coalesce(p_run->'engine_provenance','{}'::jsonb), p_run->>'producer_host', p_run->>'producer_run_id',
    p_run->>'producer_code_ref', p_run->>'status', (p_run->>'duration_sec')::numeric,
    (p_run->>'decoded_frame_count')::integer, (p_run->>'analyzed_frame_count')::integer,
    nullif(p_run->>'source_fps','')::numeric, (p_run->>'candidate_moving_sec_any_gecko')::numeric,
    (p_run->>'moving_gecko_seconds')::numeric, (p_run->>'visible_sec')::numeric,
    (p_run->>'unknown_sec')::numeric, (p_run->>'camera_motion_sec')::numeric,
    (p_run->>'max_simultaneous_geckos')::integer, coalesce(p_run->'state_intervals','[]'::jsonb),
    coalesce(p_run->'tracking_quality','{}'::jsonb), p_run->>'permanent_artifact_key',
    p_run->>'permanent_artifact_sha256', (p_run->>'permanent_artifact_bytes')::integer,
    nullif(p_run->>'debug_artifact_key',''), nullif(p_run->>'debug_artifact_sha256',''),
    nullif(p_run->>'debug_artifact_bytes','')::integer
  )
  on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity, permanent_artifact_sha256)
  do nothing returning * into r;
  if not found then
    select * into r from public.gme_runs
      where clip_id=(p_run->>'clip_id')::uuid
        and engine_schema_version=p_run->>'engine_schema_version'
        and algorithm_version=p_run->>'algorithm_version'
        and detector_identity=p_run->>'detector_identity'
        and permanent_artifact_sha256=p_run->>'permanent_artifact_sha256';
  end if;
  return r;
end $$;

create function public.fn_complete_gme_job(p_job_id uuid, p_run_id uuid, p_worker_host text)
returns boolean
language plpgsql security invoker set search_path='' as $$
declare j public.gme_jobs%rowtype; r public.gme_runs%rowtype;
begin
  select * into j from public.gme_jobs where id=p_job_id for update;
  if not found then raise exception 'job not found' using errcode='22023'; end if;
  if j.status <> 'processing' or j.claimed_by is distinct from p_worker_host then return false; end if;
  select * into r from public.gme_runs where id=p_run_id;
  if not found or r.job_id <> p_job_id or r.clip_id <> j.clip_id
     or r.engine_schema_version <> j.engine_schema_version
     or r.algorithm_version <> j.algorithm_version
     or r.detector_identity <> j.detector_identity then
    raise exception 'run does not belong to job' using errcode='22023';
  end if;
  update public.gme_jobs set status='succeeded', result_run_id=p_run_id, completed_at=now(),
    lease_expires_at=null, updated_at=now() where id=p_job_id;
  return true;
end $$;

create function public.fn_fail_gme_job(
  p_job_id uuid, p_failure_code text, p_retryable boolean, p_worker_host text, p_now timestamptz
) returns boolean
language plpgsql security invoker set search_path='' as $$
declare j public.gme_jobs%rowtype;
begin
  if p_failure_code not in (
    'r2_download_failed','source_media_missing','r2_access_denied','decode_no_frames',
    'invalid_metadata','detector_failed','gme_compute_failed','artifact_upload_failed',
    'db_transient','internal_error'
  ) then raise exception 'invalid failure code' using errcode='22023'; end if;
  select * into j from public.gme_jobs where id=p_job_id for update;
  if not found then raise exception 'job not found' using errcode='22023'; end if;
  if j.status <> 'processing' or j.claimed_by is distinct from p_worker_host then return false; end if;
  if p_retryable and j.attempt_count < j.max_attempts then
    update public.gme_jobs set status='failed_retryable', failure_code=p_failure_code,
      next_attempt_at=p_now + interval '1 minute' * power(2, j.attempt_count)::integer,
      lease_expires_at=null, updated_at=p_now where id=p_job_id;
  else
    update public.gme_jobs set status='failed_terminal', failure_code=p_failure_code,
      completed_at=p_now, lease_expires_at=null, updated_at=p_now where id=p_job_id;
  end if;
  return true;
end $$;

create function public.fn_gme_operational_stats(p_now timestamptz default now()) returns jsonb
language sql security invoker set search_path='' as $$
  select jsonb_build_object(
    'queued_live', count(*) filter (where source='live' and status in ('queued','failed_retryable')),
    'queued_historical', count(*) filter (where source='historical' and status in ('queued','failed_retryable')),
    'processing', count(*) filter (where status='processing'),
    'terminal', count(*) filter (where status='failed_terminal'),
    'oldest_live_age_sec', coalesce(extract(epoch from p_now -
      (min(created_at) filter (where source='live' and status in ('queued','failed_retryable')))), 0)
  ) from public.gme_jobs;
$$;

revoke all on function public.fn_enqueue_gme_jobs(uuid[],text,integer,text,text,text) from public, anon, authenticated;
revoke all on function public.fn_claim_gme_jobs(integer,text,timestamptz,boolean) from public, anon, authenticated;
revoke all on function public.fn_insert_gme_run(jsonb) from public, anon, authenticated;
revoke all on function public.fn_complete_gme_job(uuid,uuid,text) from public, anon, authenticated;
revoke all on function public.fn_fail_gme_job(uuid,text,boolean,text,timestamptz) from public, anon, authenticated;
revoke all on function public.fn_gme_operational_stats(timestamptz) from public, anon, authenticated;
grant execute on function public.fn_enqueue_gme_jobs(uuid[],text,integer,text,text,text) to service_role;
grant execute on function public.fn_claim_gme_jobs(integer,text,timestamptz,boolean) to service_role;
grant execute on function public.fn_insert_gme_run(jsonb) to service_role;
grant execute on function public.fn_complete_gme_job(uuid,uuid,text) to service_role;
grant execute on function public.fn_fail_gme_job(uuid,text,boolean,text,timestamptz) to service_role;
grant execute on function public.fn_gme_operational_stats(timestamptz) to service_role;
