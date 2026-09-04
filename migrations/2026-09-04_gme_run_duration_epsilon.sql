-- GME v1 duration invariant epsilon alignment.
--
-- moving_gecko_seconds와 candidate_moving_sec_any_gecko는 같은 시간을 서로 다른
-- 누적 순서로 계산한다. 엔진 계약은 0.001초 오차를 허용하지만 기존 DB CHECK는
-- 정확 비교라서 1e-16 수준의 부동소수점 노이즈도 거부했다. 이 migration은 해당
-- CHECK 하나만 엔진 계약과 맞추며, 0.001초를 넘는 실제 역전은 계속 차단한다.

do $$
declare
  v_constraint_name text;
  v_constraint_count integer;
begin
  select count(*), min(con.conname)
    into v_constraint_count, v_constraint_name
  from pg_constraint con
  where con.conrelid = 'public.gme_runs'::regclass
    and con.contype = 'c'
    and pg_get_expr(con.conbin, con.conrelid) ilike '%moving_gecko_seconds%'
    and pg_get_expr(con.conbin, con.conrelid) ilike '%candidate_moving_sec_any_gecko%';

  if v_constraint_count <> 1 then
    raise exception 'expected exactly one GME moving-duration cross-field constraint, found %',
      v_constraint_count using errcode = '55000';
  end if;

  execute format(
    'alter table public.gme_runs drop constraint %I',
    v_constraint_name
  );
end $$;

alter table public.gme_runs
  add constraint gme_runs_moving_duration_epsilon_check
  check (
    moving_gecko_seconds >= candidate_moving_sec_any_gecko - 0.001
  ) not valid;

alter table public.gme_runs
  validate constraint gme_runs_moving_duration_epsilon_check;

comment on constraint gme_runs_moving_duration_epsilon_check on public.gme_runs is
  'GME engine duration invariant with 0.001s float-accumulation tolerance.';

-- Rollback (worker를 먼저 정지하고 모든 기존 row가 exact 비교를 만족할 때만):
--   ALTER TABLE public.gme_runs DROP CONSTRAINT gme_runs_moving_duration_epsilon_check;
--   ALTER TABLE public.gme_runs ADD CONSTRAINT gme_runs_moving_duration_exact_check
--     CHECK (moving_gecko_seconds >= candidate_moving_sec_any_gecko);
