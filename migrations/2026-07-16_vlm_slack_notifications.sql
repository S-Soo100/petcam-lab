-- Durable idempotency for the regular VLM scheduled-window Slack summary (§Item2).
-- One summary per (selector_version, window_start, window_end, producer_host). Atomic claim
-- via INSERT ... ON CONFLICT DO NOTHING so sequential re-runs AND concurrent runs send once.
-- Forward-only, idempotent. Does not touch clip_vlm_jobs / GT / behavior_labels / activity.

create table if not exists public.vlm_slack_notifications (
  id uuid primary key default gen_random_uuid(),
  selector_version text not null,
  window_start timestamptz not null,
  window_end timestamptz not null,
  producer_host text not null,
  run_id text,
  sent_at timestamptz not null default now(),
  unique (selector_version, window_start, window_end, producer_host)
);

alter table public.vlm_slack_notifications enable row level security;
revoke all on public.vlm_slack_notifications from anon, authenticated;
grant all on public.vlm_slack_notifications to service_role;

-- Atomic claim: returns true only for the caller that inserted the row (first / winner).
create or replace function public.fn_claim_vlm_slack_notification(
  p_selector text, p_window_start timestamptz, p_window_end timestamptz, p_host text, p_run_id text
) returns boolean
language plpgsql security invoker set search_path=public,pg_temp as $$
begin
  insert into public.vlm_slack_notifications(selector_version,window_start,window_end,producer_host,run_id)
  values(p_selector,p_window_start,p_window_end,p_host,p_run_id)
  on conflict (selector_version,window_start,window_end,producer_host) do nothing;
  return found;  -- true if inserted (claimed), false if a row already existed
end $$;

-- Release claim so a later run can re-send after a Slack transport failure (retry policy).
create or replace function public.fn_release_vlm_slack_notification(
  p_selector text, p_window_start timestamptz, p_window_end timestamptz, p_host text
) returns void
language plpgsql security invoker set search_path=public,pg_temp as $$
begin
  delete from public.vlm_slack_notifications
  where selector_version=p_selector and window_start=p_window_start
    and window_end=p_window_end and producer_host=p_host;
end $$;

revoke all on function public.fn_claim_vlm_slack_notification(text,timestamptz,timestamptz,text,text) from public,anon,authenticated;
revoke all on function public.fn_release_vlm_slack_notification(text,timestamptz,timestamptz,text) from public,anon,authenticated;
grant execute on function public.fn_claim_vlm_slack_notification(text,timestamptz,timestamptz,text,text) to service_role;
grant execute on function public.fn_release_vlm_slack_notification(text,timestamptz,timestamptz,text) to service_role;

-- Rollback:
--   drop function if exists public.fn_release_vlm_slack_notification(text,timestamptz,timestamptz,text);
--   drop function if exists public.fn_claim_vlm_slack_notification(text,timestamptz,timestamptz,text,text);
--   drop table if exists public.vlm_slack_notifications;
