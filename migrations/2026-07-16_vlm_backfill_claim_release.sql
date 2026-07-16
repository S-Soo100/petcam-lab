-- Rolling backfill claim release (H1). Lets a worker release a source_date claim it took
-- but could not turn into jobs (pre-create exception), so the date is not permanently stuck.
-- DB-enforced: only releases when NO clip_vlm_jobs exist for that selector+source_date, so a
-- partially-created wave is never released (next cycle resumes it instead). Forward-only, idempotent.
-- Does not modify the applied 2026-07-16_vlm_backfill_ledger migration.

create or replace function public.fn_release_backfill_claim(
  p_selector text, p_source_date date, p_scope text
) returns boolean
language plpgsql security invoker set search_path=public,pg_temp as $$
declare deleted int;
begin
  delete from public.vlm_backfill_ledger l
  where l.selector_version = p_selector
    and l.source_date = p_source_date
    and l.scope = p_scope
    and not exists (
      select 1 from public.clip_vlm_jobs j
      where j.selector_version = p_selector
        and (j.rank_features->>'source_date') = p_source_date::text
    );
  get diagnostics deleted = row_count;
  return deleted > 0;
end $$;

revoke all on function public.fn_release_backfill_claim(text,date,text) from public,anon,authenticated;
grant execute on function public.fn_release_backfill_claim(text,date,text) to service_role;

-- Rollback:
--   drop function if exists public.fn_release_backfill_claim(text,date,text);
