-- Rolling VLM backfill per-night ledger. Durable date-status so empty/blocked nights are
-- not rescanned forever (jobs alone cannot express "attempted, found 0 candidates").
-- Forward-only, idempotent. Does not touch clip_vlm_jobs / GT / behavior_labels / activity.

create table if not exists public.vlm_backfill_ledger (
  id uuid primary key default gen_random_uuid(),
  selector_version text not null,
  source_date date not null,
  scope text not null,                       -- camera_id (per-night chosen camera)
  status text not null default 'pending'
    check (status in ('pending','processing','completed','no_candidates','insufficient_candidates','blocked')),
  target_count int not null default 0,
  created_count int not null default 0,
  processed_count int not null default 0,
  succeeded_count int not null default 0,
  terminal_count int not null default 0,
  last_error_code text,
  attempted_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (selector_version, source_date, scope)
);

alter table public.vlm_backfill_ledger enable row level security;
revoke all on public.vlm_backfill_ledger from anon, authenticated;
grant all on public.vlm_backfill_ledger to service_role;

-- Atomic claim: only the first (concurrent) caller inserts the row and gets true.
create or replace function public.fn_claim_backfill_source_date(
  p_selector text, p_source_date date, p_scope text
) returns boolean
language plpgsql security invoker set search_path=public,pg_temp as $$
begin
  insert into public.vlm_backfill_ledger(selector_version,source_date,scope,status,attempted_at)
  values(p_selector,p_source_date,p_scope,'processing',now())
  on conflict (selector_version,source_date,scope) do nothing;
  return found;
end $$;

-- Idempotent status/counts upsert. completed_at stamped on terminal states.
create or replace function public.fn_upsert_backfill_ledger(
  p_selector text, p_source_date date, p_scope text, p_status text,
  p_target int, p_created int, p_processed int, p_succeeded int, p_terminal int, p_last_error text
) returns void
language plpgsql security invoker set search_path=public,pg_temp as $$
begin
  insert into public.vlm_backfill_ledger(
    selector_version,source_date,scope,status,target_count,created_count,processed_count,
    succeeded_count,terminal_count,last_error_code,attempted_at,
    completed_at)
  values(p_selector,p_source_date,p_scope,p_status,p_target,p_created,p_processed,
    p_succeeded,p_terminal,p_last_error,now(),
    case when p_status in ('completed','no_candidates','insufficient_candidates','blocked') then now() end)
  on conflict (selector_version,source_date,scope) do update set
    status=excluded.status, target_count=excluded.target_count, created_count=excluded.created_count,
    processed_count=excluded.processed_count, succeeded_count=excluded.succeeded_count,
    terminal_count=excluded.terminal_count, last_error_code=excluded.last_error_code,
    updated_at=now(),
    completed_at=case when excluded.status in ('completed','no_candidates','insufficient_candidates','blocked')
                      then now() else public.vlm_backfill_ledger.completed_at end;
end $$;

revoke all on function public.fn_claim_backfill_source_date(text,date,text) from public,anon,authenticated;
revoke all on function public.fn_upsert_backfill_ledger(text,date,text,text,int,int,int,int,int,text) from public,anon,authenticated;
grant execute on function public.fn_claim_backfill_source_date(text,date,text) to service_role;
grant execute on function public.fn_upsert_backfill_ledger(text,date,text,text,int,int,int,int,int,text) to service_role;

-- Rollback:
--   drop function if exists public.fn_upsert_backfill_ledger(text,date,text,text,int,int,int,int,int,text);
--   drop function if exists public.fn_claim_backfill_source_date(text,date,text);
--   drop table if exists public.vlm_backfill_ledger;
