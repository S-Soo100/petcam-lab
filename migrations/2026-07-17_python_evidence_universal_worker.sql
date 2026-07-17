-- Python Evidence Universal Worker — 전 영상 durable queue + append-only raw evidence 원장.
-- Forward-only. 원본 motion_clips/R2 는 불변. 이 마이그레이션은 기존 clip 을 대량 enqueue 하지 않는다
-- (신규는 trigger, 과거는 별도 bounded enqueuer — 설계 §5.1/§10).
--
-- 보안 계약(설계 §5.2/§6):
--   * 모든 함수 SECURITY INVOKER + search_path='' + fully-qualified (search-path 하이재킹 차단)
--   * 두 테이블 RLS enabled + client policy 0 (service_role bypass 로만 접근)
--   * grant 는 service_role only
--   * clip_python_evidence_runs 는 role 무관 UPDATE/DELETE/TRUNCATE 차단(append-only, SQLSTATE 0A000)
--
-- Rollback:
--   drop trigger if exists trg_enqueue_python_evidence_job on public.motion_clips;
--   drop trigger if exists trg_block_python_evidence_run_update on public.clip_python_evidence_runs;
--   drop trigger if exists trg_block_python_evidence_run_delete on public.clip_python_evidence_runs;
--   drop trigger if exists trg_block_python_evidence_run_truncate on public.clip_python_evidence_runs;
--   drop function if exists public.fn_enqueue_python_evidence_job();
--   drop function if exists public.fn_block_python_evidence_run_mutation();
--   drop function if exists public.fn_claim_python_evidence_jobs(integer,text,timestamptz);
--   drop function if exists public.fn_complete_python_evidence_job(uuid,uuid,text);
--   drop function if exists public.fn_fail_python_evidence_job(uuid,text,boolean,text,timestamptz);
--   drop function if exists public.fn_insert_python_evidence_run(jsonb);
--   drop table if exists public.clip_python_evidence_runs;
--   drop table if exists public.python_evidence_jobs;

-- ============================================================================
-- 1) durable queue
-- ============================================================================
create table public.python_evidence_jobs (
  id uuid primary key default gen_random_uuid(),
  clip_id uuid not null references public.motion_clips(id) on delete cascade,
  source text not null check (source in ('live','historical')),
  priority integer not null check (priority >= 0),
  evidence_schema_version text not null,
  algorithm_version text not null,
  status text not null default 'queued'
    check (status in ('queued','processing','succeeded','failed_retryable','failed_terminal')),
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 5 check (max_attempts >= 1),
  next_attempt_at timestamptz,
  claimed_at timestamptz,
  claimed_by text,
  lease_expires_at timestamptz,
  -- allowlist 실패 코드만 저장 (raw exception/URL/secret 저장 금지 — 설계 §5.1). NULL 은 실패 전.
  failure_code text check (failure_code is null or failure_code in (
    'r2_download_failed','decode_no_frames','decode_insufficient_frames','invalid_metadata',
    'detector_failed','temporal_compute_failed','db_transient','db_error','internal_error'
  )),
  result_run_id uuid,  -- FK 는 clip_python_evidence_runs 생성 후 ALTER 로 추가(순환 참조 회피)
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz,
  -- clip 당 활성 (schema,algorithm) 버전 1 job. 버전 올리면 새 job 이 별도로 생긴다.
  unique (clip_id, evidence_schema_version, algorithm_version)
);
-- claim 인덱스: due 한 open job 을 live 우선·안정정렬로 빠르게 집는다.
create index idx_python_evidence_jobs_claim
  on public.python_evidence_jobs (status, priority desc, created_at asc, id asc);
create index idx_python_evidence_jobs_lease
  on public.python_evidence_jobs (status, lease_expires_at);

-- ============================================================================
-- 2) append-only 결과 원장
-- ============================================================================
create table public.clip_python_evidence_runs (
  id uuid primary key default gen_random_uuid(),
  clip_id uuid not null references public.motion_clips(id) on delete cascade,
  job_id uuid not null references public.python_evidence_jobs(id) on delete cascade,
  prelabel_id uuid references public.clip_prelabels(id) on delete set null,
  evidence_schema_version text not null default 'python-evidence-raw-v1',
  algorithm_version text not null default 'croi-temporal-v1',
  -- Gate 7-column provenance (재현성/감사)
  model_name text,
  model_version text,
  checkpoint_sha256 text,
  threshold numeric,
  sampler_version text,
  schema_version text,
  frames_sampled integer,
  -- producer (관측용, 비밀값 없음)
  producer_host text not null,
  producer_run_id text not null,
  producer_code_ref text,
  -- adaptive depth 상태
  level0_status text not null
    check (level0_status in ('ok','no_decodable_frames','insufficient_decodable_frames','invalid_metadata')),
  level1_status text not null
    check (level1_status in ('ok','no_bbox','skipped')),
  decoded_frame_count integer check (decoded_frame_count is null or decoded_frame_count >= 0),
  point_stride integer check (point_stride is null or point_stride >= 1),
  -- bounded JSON payload (point cap 256 — 설계 §7)
  metadata jsonb not null default '{}'::jsonb,
  motion_summary jsonb not null default '{}'::jsonb,
  global_motion_series jsonb not null default '[]'::jsonb
    check (jsonb_array_length(global_motion_series) <= 256),
  roi_motion_series jsonb not null default '[]'::jsonb
    check (jsonb_array_length(roi_motion_series) <= 256),
  spatial_dwell jsonb not null default '{}'::jsonb,
  periodicity_summary jsonb not null default '{}'::jsonb,
  motion_excursions jsonb not null default '[]'::jsonb
    check (jsonb_array_length(motion_excursions) <= 256),
  -- prelabel identity 의 canonical JSON SHA-256 (prelabel 없으면 literal 'none'); 항상 non-null
  source_prelabel_identity text not null default 'none',
  created_at timestamptz not null default now(),
  -- 동일 identity 재실행 멱등: 같은 clip+버전+prelabel identity 는 1 run
  unique (clip_id, evidence_schema_version, algorithm_version, source_prelabel_identity)
);
create index idx_clip_python_evidence_runs_clip on public.clip_python_evidence_runs (clip_id);
create index idx_clip_python_evidence_runs_job on public.clip_python_evidence_runs (job_id);

-- 순환 FK: job.result_run_id → run.id (두 테이블 생성 후에 추가)
alter table public.python_evidence_jobs
  add constraint fk_python_evidence_jobs_result_run
  foreign key (result_run_id) references public.clip_python_evidence_runs(id) on delete set null;

-- ============================================================================
-- 3) RLS + grant (service_role only, client policy 0)
-- ============================================================================
alter table public.python_evidence_jobs enable row level security;
alter table public.clip_python_evidence_runs enable row level security;
-- client policy 를 만들지 않는다 → anon/authenticated 는 RLS 로 0행. service_role 은 RLS bypass.
revoke all on public.python_evidence_jobs from public, anon, authenticated;
revoke all on public.clip_python_evidence_runs from public, anon, authenticated;
grant all on public.python_evidence_jobs to service_role;
grant all on public.clip_python_evidence_runs to service_role;

-- ============================================================================
-- 4) append-only blocker (role 무관 UPDATE/DELETE/TRUNCATE 차단)
-- ============================================================================
-- ⚠️ 부수효과(의도): clip_python_evidence_runs 의 FK 는 ON DELETE CASCADE 다. 이 트리거가 있으면
--    run 이 달린 motion_clip/job 을 hard-delete 할 때 CASCADE 삭제가 이 트리거에 막혀 부모 삭제도
--    실패한다. evidence 원장은 영구 보존이 원칙이므로 의도된 동작이다(레포 기존 append-only 관례와 동일 —
--    clip_labeling_session_revisions/triage_events). 부모를 지워야 하면 먼저 아카이브/분리한다.
create function public.fn_block_python_evidence_run_mutation() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  -- SQLSTATE 0A000 = feature_not_supported. service_role 포함 모든 role 의 변경을 거부한다.
  raise exception 'clip_python_evidence_runs is append-only (insert-only)' using errcode='0A000';
end $$;
create trigger trg_block_python_evidence_run_update
  before update on public.clip_python_evidence_runs
  for each row execute function public.fn_block_python_evidence_run_mutation();
create trigger trg_block_python_evidence_run_delete
  before delete on public.clip_python_evidence_runs
  for each row execute function public.fn_block_python_evidence_run_mutation();
create trigger trg_block_python_evidence_run_truncate
  before truncate on public.clip_python_evidence_runs
  for each statement execute function public.fn_block_python_evidence_run_mutation();

-- ============================================================================
-- 5) 전 영상 enqueue trigger (신규 motion_clips → live job 1건)
-- ============================================================================
create function public.fn_enqueue_python_evidence_job() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  -- 신규 clip 은 무조건 현재 active 버전의 live job 을 원자 생성. 중복은 no-op.
  -- motion_clips insert 는 service_role 경로라 invoker 로도 job insert 권한이 있다.
  insert into public.python_evidence_jobs (clip_id, source, priority, evidence_schema_version, algorithm_version)
  values (new.id, 'live', 100, 'python-evidence-raw-v1', 'croi-temporal-v1')
  on conflict (clip_id, evidence_schema_version, algorithm_version) do nothing;
  return new;
end $$;
create trigger trg_enqueue_python_evidence_job
  after insert on public.motion_clips
  for each row execute function public.fn_enqueue_python_evidence_job();

-- ============================================================================
-- 6) claim/complete/fail/insert RPC (모두 service_role only)
-- ============================================================================
-- claim: lease 만료 회수 → live 우선 안정정렬 → SKIP LOCKED 로 최대 p_limit 개 processing 전환.
create function public.fn_claim_python_evidence_jobs(p_limit integer, p_worker_host text, p_now timestamptz)
returns setof public.python_evidence_jobs
language plpgsql security invoker set search_path='' as $$
begin
  -- lease 만료 processing 회수: 죽은 worker 가 잡고 있던 job 을 다시 retryable 로.
  update public.python_evidence_jobs
    set status='failed_retryable', next_attempt_at=p_now, lease_expires_at=null, updated_at=p_now
    where status='processing' and lease_expires_at is not null and lease_expires_at < p_now;

  return query
  update public.python_evidence_jobs j
    set status='processing',
        claimed_by=p_worker_host,
        claimed_at=p_now,
        lease_expires_at=p_now + interval '15 minutes',
        attempt_count=j.attempt_count + 1,
        updated_at=p_now
    where j.id in (
      select c.id from public.python_evidence_jobs c
      where c.status in ('queued','failed_retryable')
        and (c.next_attempt_at is null or c.next_attempt_at <= p_now)
      order by priority desc, created_at asc, id asc
      for update skip locked
      limit p_limit
    )
    returning j.*;
end $$;

-- complete: 자기 lease(claimed_by 일치) + processing 상태일 때만 succeeded. stale 완료는 거부(false).
create function public.fn_complete_python_evidence_job(p_job_id uuid, p_run_id uuid, p_worker_host text)
returns boolean
language plpgsql security invoker set search_path='' as $$
declare j public.python_evidence_jobs%rowtype;
begin
  select * into j from public.python_evidence_jobs where id=p_job_id for update;
  if not found then raise exception 'job not found' using errcode='22023'; end if;
  if j.status <> 'processing' or j.claimed_by is distinct from p_worker_host then
    return false;  -- lease ownership 불일치/비-processing = stale 완료 거부
  end if;
  update public.python_evidence_jobs
    set status='succeeded', result_run_id=p_run_id, completed_at=now(),
        lease_expires_at=null, updated_at=now()
    where id=p_job_id;
  return true;
end $$;

-- fail: 자기 lease 일 때만. retryable & attempt<max 면 failed_retryable(지수 backoff), 아니면 terminal.
create function public.fn_fail_python_evidence_job(
  p_job_id uuid, p_failure_code text, p_retryable boolean, p_worker_host text, p_now timestamptz
) returns boolean
language plpgsql security invoker set search_path='' as $$
declare j public.python_evidence_jobs%rowtype;
begin
  select * into j from public.python_evidence_jobs where id=p_job_id for update;
  if not found then raise exception 'job not found' using errcode='22023'; end if;
  if j.status <> 'processing' or j.claimed_by is distinct from p_worker_host then
    return false;  -- stale
  end if;
  if p_retryable and j.attempt_count < j.max_attempts then
    update public.python_evidence_jobs
      set status='failed_retryable', failure_code=p_failure_code,
          next_attempt_at=p_now + (interval '1 minute' * power(2, j.attempt_count)::integer),
          lease_expires_at=null, updated_at=p_now
      where id=p_job_id;
  else
    -- 최대 attempt 초과 또는 비-retryable → allowlist terminal 전환
    update public.python_evidence_jobs
      set status='failed_terminal', failure_code=p_failure_code,
          completed_at=p_now, lease_expires_at=null, updated_at=p_now
      where id=p_job_id;
  end if;
  return true;
end $$;

-- insert_run: append-only 결과 원장에 1 run. 동일 identity 재실행은 기존 run 을 그대로 반환(멱등).
create function public.fn_insert_python_evidence_run(p_run jsonb)
returns public.clip_python_evidence_runs
language plpgsql security invoker set search_path='' as $$
declare r public.clip_python_evidence_runs%rowtype;
begin
  insert into public.clip_python_evidence_runs (
    clip_id, job_id, prelabel_id, evidence_schema_version, algorithm_version,
    model_name, model_version, checkpoint_sha256, threshold, sampler_version, schema_version, frames_sampled,
    producer_host, producer_run_id, producer_code_ref,
    level0_status, level1_status, decoded_frame_count, point_stride,
    metadata, motion_summary, global_motion_series, roi_motion_series, spatial_dwell,
    periodicity_summary, motion_excursions, source_prelabel_identity
  ) values (
    (p_run->>'clip_id')::uuid,
    (p_run->>'job_id')::uuid,
    nullif(p_run->>'prelabel_id','')::uuid,
    coalesce(p_run->>'evidence_schema_version','python-evidence-raw-v1'),
    coalesce(p_run->>'algorithm_version','croi-temporal-v1'),
    p_run->>'model_name', p_run->>'model_version', p_run->>'checkpoint_sha256',
    nullif(p_run->>'threshold','')::numeric, p_run->>'sampler_version', p_run->>'schema_version',
    nullif(p_run->>'frames_sampled','')::integer,
    p_run->>'producer_host', p_run->>'producer_run_id', p_run->>'producer_code_ref',
    p_run->>'level0_status', p_run->>'level1_status',
    nullif(p_run->>'decoded_frame_count','')::integer, nullif(p_run->>'point_stride','')::integer,
    coalesce(p_run->'metadata','{}'::jsonb), coalesce(p_run->'motion_summary','{}'::jsonb),
    coalesce(p_run->'global_motion_series','[]'::jsonb), coalesce(p_run->'roi_motion_series','[]'::jsonb),
    coalesce(p_run->'spatial_dwell','{}'::jsonb), coalesce(p_run->'periodicity_summary','{}'::jsonb),
    coalesce(p_run->'motion_excursions','[]'::jsonb),
    coalesce(p_run->>'source_prelabel_identity','none')
  )
  on conflict (clip_id, evidence_schema_version, algorithm_version, source_prelabel_identity) do nothing
  returning * into r;

  if not found then
    -- 이미 존재하는 run 을 그대로 반환(멱등, 변경 없음).
    select * into r from public.clip_python_evidence_runs
      where clip_id=(p_run->>'clip_id')::uuid
        and evidence_schema_version=coalesce(p_run->>'evidence_schema_version','python-evidence-raw-v1')
        and algorithm_version=coalesce(p_run->>'algorithm_version','croi-temporal-v1')
        and source_prelabel_identity=coalesce(p_run->>'source_prelabel_identity','none');
  end if;
  return r;
end $$;

revoke all on function public.fn_claim_python_evidence_jobs(integer,text,timestamptz) from public, anon, authenticated;
revoke all on function public.fn_complete_python_evidence_job(uuid,uuid,text) from public, anon, authenticated;
revoke all on function public.fn_fail_python_evidence_job(uuid,text,boolean,text,timestamptz) from public, anon, authenticated;
revoke all on function public.fn_insert_python_evidence_run(jsonb) from public, anon, authenticated;
grant execute on function public.fn_claim_python_evidence_jobs(integer,text,timestamptz) to service_role;
grant execute on function public.fn_complete_python_evidence_job(uuid,uuid,text) to service_role;
grant execute on function public.fn_fail_python_evidence_job(uuid,text,boolean,text,timestamptz) to service_role;
grant execute on function public.fn_insert_python_evidence_run(jsonb) to service_role;
