-- Budgeted Claude VLM candidate router v1. Forward-only; source clips/R2 stay immutable.
create table public.clip_vlm_selector_runs (
  id uuid primary key default gen_random_uuid(),
  camera_id uuid not null references public.cameras(id) on delete cascade,
  window_start timestamptz not null, window_end timestamptz not null,
  selector_version text not null,
  clips_seen integer not null check (clips_seen >= 0),
  hard_invalid_count integer not null check (hard_invalid_count >= 0),
  already_processed_count integer not null check (already_processed_count >= 0),
  episode_count integer not null check (episode_count >= 0),
  pool_counts jsonb not null default '{}'::jsonb,
  selected_clip_ids jsonb not null default '[]'::jsonb,
  unselected_reason_counts jsonb not null default '{}'::jsonb,
  monthly_budget_usd numeric(12,6) not null,
  month_reserved_usd numeric(12,6) not null,
  month_actual_usd numeric(12,6) not null,
  producer_host text not null, producer_run_id text not null,
  created_at timestamptz not null default now(), completed_at timestamptz,
  unique (camera_id, window_start, selector_version),
  check (window_end > window_start)
);

create table public.clip_vlm_jobs (
  id uuid primary key default gen_random_uuid(),
  selector_run_id uuid not null references public.clip_vlm_selector_runs(id) on delete cascade,
  clip_id uuid not null references public.motion_clips(id) on delete cascade,
  camera_id uuid not null references public.cameras(id) on delete cascade,
  window_start timestamptz not null, window_end timestamptz not null,
  slot text not null check (slot in ('customer_highlight','subtle_behavior','diversity_discovery','exclusion_audit')),
  selector_version text not null, episode_key text not null,
  rank_features jsonb not null, selection_reason text not null,
  activity_assessment_id uuid references public.clip_activity_assessments(id) on delete set null,
  prelabel_id uuid references public.clip_prelabels(id) on delete set null,
  status text not null check (status in ('queued','submitted','succeeded','failed_retryable','failed_terminal','held_budget','held_model_mismatch')),
  attempt_count integer not null default 0 check (attempt_count between 0 and 2),
  queued_at timestamptz not null default now(), submitted_at timestamptz, completed_at timestamptz,
  model_requested text not null, model_actual text,
  prompt_version text not null, prompt_sha256 text not null,
  sampler_version text not null, frames_sampled integer check (frames_sampled between 0 and 6),
  provider_request_id text, result jsonb, error_code text,
  reserved_cost_usd numeric(12,6) not null check (reserved_cost_usd >= 0),
  input_tokens bigint, cache_creation_input_tokens bigint, cache_read_input_tokens bigint,
  output_tokens bigint, cost_usd numeric(12,6), pricing_version text not null,
  producer_host text not null, producer_run_id text not null, created_at timestamptz not null default now(),
  unique (clip_id, selector_version), unique (selector_run_id, slot), check (window_end > window_start)
);
create index idx_clip_vlm_jobs_status_queued on public.clip_vlm_jobs(status, queued_at);
create index idx_clip_vlm_jobs_month_cost on public.clip_vlm_jobs(created_at, status);
create index idx_clip_vlm_jobs_camera_created on public.clip_vlm_jobs(camera_id, created_at desc);

alter table public.clip_vlm_selector_runs enable row level security;
alter table public.clip_vlm_jobs enable row level security;
create policy "owner reads own vlm selector runs" on public.clip_vlm_selector_runs for select to authenticated
 using (exists (select 1 from public.cameras c where c.id=clip_vlm_selector_runs.camera_id and c.owner_id=(select auth.uid())));
create policy "owner reads own vlm jobs" on public.clip_vlm_jobs for select to authenticated
 using (exists (select 1 from public.motion_clips mc where mc.id=clip_vlm_jobs.clip_id and mc.owner_id=(select auth.uid())));
revoke all on public.clip_vlm_selector_runs from anon, authenticated;
revoke all on public.clip_vlm_jobs from anon, authenticated;
grant select on public.clip_vlm_selector_runs, public.clip_vlm_jobs to authenticated;
grant all on public.clip_vlm_selector_runs, public.clip_vlm_jobs to service_role;

create function public.fn_create_clip_vlm_selector_run(p_run jsonb, p_jobs jsonb) returns uuid
language plpgsql security invoker set search_path=public,pg_temp as $$
declare rid uuid; j jsonb;
begin
 if jsonb_typeof(p_jobs) is distinct from 'array' or jsonb_array_length(p_jobs) > 4 then raise exception 'jobs max 4' using errcode='22023'; end if;
 insert into public.clip_vlm_selector_runs(camera_id,window_start,window_end,selector_version,clips_seen,hard_invalid_count,already_processed_count,episode_count,pool_counts,selected_clip_ids,unselected_reason_counts,monthly_budget_usd,month_reserved_usd,month_actual_usd,producer_host,producer_run_id,completed_at)
 values ((p_run->>'camera_id')::uuid,(p_run->>'window_start')::timestamptz,(p_run->>'window_end')::timestamptz,p_run->>'selector_version',(p_run->>'clips_seen')::int,(p_run->>'hard_invalid_count')::int,(p_run->>'already_processed_count')::int,(p_run->>'episode_count')::int,p_run->'pool_counts',p_run->'selected_clip_ids',p_run->'unselected_reason_counts',(p_run->>'monthly_budget_usd')::numeric,(p_run->>'month_reserved_usd')::numeric,(p_run->>'month_actual_usd')::numeric,p_run->>'producer_host',p_run->>'producer_run_id',now())
 on conflict (camera_id,window_start,selector_version) do update set completed_at=now() returning id into rid;
 for j in select value from jsonb_array_elements(p_jobs) loop
  insert into public.clip_vlm_jobs(selector_run_id,clip_id,camera_id,window_start,window_end,slot,selector_version,episode_key,rank_features,selection_reason,activity_assessment_id,prelabel_id,status,model_requested,prompt_version,prompt_sha256,sampler_version,reserved_cost_usd,pricing_version,producer_host,producer_run_id)
  values(rid,(j->>'clip_id')::uuid,(p_run->>'camera_id')::uuid,(p_run->>'window_start')::timestamptz,(p_run->>'window_end')::timestamptz,j->>'slot',p_run->>'selector_version',j->>'episode_key',j->'rank_features',j->>'selection_reason',nullif(j->>'activity_assessment_id','')::uuid,nullif(j->>'prelabel_id','')::uuid,'queued',j->>'model_requested',j->>'prompt_version',j->>'prompt_sha256',j->>'sampler_version',(j->>'reserved_cost_usd')::numeric,j->>'pricing_version',p_run->>'producer_host',p_run->>'producer_run_id') on conflict do nothing;
 end loop; return rid;
end $$;

create function public.fn_reserve_clip_vlm_job(p_job_id uuid,p_month_start timestamptz,p_budget_usd numeric) returns boolean
language plpgsql security invoker set search_path=public,pg_temp as $$
declare j public.clip_vlm_jobs%rowtype; committed numeric;
begin
 perform pg_advisory_xact_lock(hashtextextended('clip_vlm_monthly_budget',0));
 select * into j from public.clip_vlm_jobs where id=p_job_id for update;
 if not found or j.status not in ('queued','failed_retryable') then raise exception 'job not reservable' using errcode='22023'; end if;
 select coalesce(sum(coalesce(cost_usd,0)),0)+coalesce(sum(case when status in ('submitted','failed_retryable') then reserved_cost_usd else 0 end),0) into committed from public.clip_vlm_jobs where created_at>=p_month_start and id<>p_job_id;
 if committed+j.reserved_cost_usd>p_budget_usd then update public.clip_vlm_jobs set status='held_budget',completed_at=now() where id=p_job_id; return false; end if;
 update public.clip_vlm_jobs set status='submitted',attempt_count=attempt_count+1,submitted_at=now() where id=p_job_id; return true;
end $$;
revoke all on function public.fn_create_clip_vlm_selector_run(jsonb,jsonb) from public,anon,authenticated;
revoke all on function public.fn_reserve_clip_vlm_job(uuid,timestamptz,numeric) from public,anon,authenticated;
grant execute on function public.fn_create_clip_vlm_selector_run(jsonb,jsonb) to service_role;
grant execute on function public.fn_reserve_clip_vlm_job(uuid,timestamptz,numeric) to service_role;

-- Rollback: drop function fn_reserve_clip_vlm_job; drop function fn_create_clip_vlm_selector_run;
-- drop table clip_vlm_jobs; drop table clip_vlm_selector_runs.
