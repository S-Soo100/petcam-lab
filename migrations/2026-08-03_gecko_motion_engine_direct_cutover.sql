-- GME direct production-shadow cutover. Supabase migration runner의 단일 transaction에서 실행한다.
-- 선행: base schema applied, 실영상 smoke 10/10, legacy processing 0.

do $$
declare legacy_trigger_count integer; gme_trigger_count integer; smoke_complete integer; legacy_processing integer;
begin
  if to_regclass('public.gme_jobs') is null or to_regclass('public.gme_runs') is null then
    raise exception 'cutover preflight failed: GME base schema missing';
  end if;
  select count(*) into smoke_complete
    from public.gme_jobs j join public.gme_runs r on r.id=j.result_run_id
    where j.source='smoke' and j.status='succeeded';
  if smoke_complete < 10 then
    raise exception 'cutover preflight failed: smoke complete below 10';
  end if;
  select count(*) into legacy_processing from public.python_evidence_jobs where status='processing';
  if legacy_processing <> 0 then
    raise exception 'cutover preflight failed: legacy processing jobs remain';
  end if;
  select count(*) into legacy_trigger_count from pg_trigger
    where tgrelid='public.motion_clips'::regclass and tgname='trg_enqueue_python_evidence_job' and not tgisinternal;
  select count(*) into gme_trigger_count from pg_trigger
    where tgrelid='public.motion_clips'::regclass and tgname='trg_enqueue_gme_live_job' and not tgisinternal;
  if legacy_trigger_count <> 1 or gme_trigger_count <> 0 then
    raise exception 'cutover preflight failed: unexpected enqueue trigger state';
  end if;
end $$;

create or replace function public.fn_enqueue_gme_live_job() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  insert into public.gme_jobs (
    clip_id, source, priority, engine_schema_version, algorithm_version, detector_identity
  ) values (
    new.id, 'live', 100, 'gme-shadow-v1', 'gme-motion-v0',
    '7997e853e851ac6592e03d13e7d5098ebfcbcb49b408077d83d7d6359df60a2a'
  ) on conflict (clip_id, engine_schema_version, algorithm_version, detector_identity) do nothing;
  return new;
end $$;

revoke all on function public.fn_enqueue_gme_live_job() from public, anon, authenticated;
grant execute on function public.fn_enqueue_gme_live_job() to service_role;

create trigger trg_enqueue_gme_live_job
  after insert on public.motion_clips
  for each row execute function public.fn_enqueue_gme_live_job();

drop trigger trg_enqueue_python_evidence_job on public.motion_clips;

-- ROLLBACK CONTRACT (가역 운영 복구, 별도 승인된 atomic SQL로만 실행):
--   drop trigger if exists trg_enqueue_gme_live_job on public.motion_clips;
--   create trigger trg_enqueue_python_evidence_job
--     after insert on public.motion_clips
--     for each row execute function public.fn_enqueue_python_evidence_job();
--   GME history remains append-only; gme_jobs/gme_runs와 artifact는 제거하지 않는다.
