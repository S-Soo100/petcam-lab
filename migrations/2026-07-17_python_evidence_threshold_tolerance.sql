-- Python Evidence — prelabel threshold 비교 정밀도 fix (forward-only).
-- 원인(Mac mini canary 실측): clip_prelabels.threshold 는 real(float4)라 numeric exact 비교
-- (`pl.threshold is distinct from ...::numeric`)에서 real 0.1(=0.100000001490116) vs numeric 0.1 이
-- 항상 distinct → fn_insert_python_evidence_run 이 22023 'run provenance does not match linked prelabel
-- identity' 을 던져 run 저장 0, jobs 전부 failed_retryable(db_transient) 로 실패했다.
--
-- 이 마이그레이션은 **2026-07-17_python_evidence_universal_worker.sql 을 수정하지 않고**,
-- fn_insert_python_evidence_run 을 CREATE OR REPLACE 한다. 기존 H3/H4 검증(job 잠금·clip/schema/algorithm
-- 일치·prelabel clip 일치·나머지 6 provenance 컬럼 IS DISTINCT FROM·JSON object/array/원소 numeric>=0·point
-- cap 256·멱등)은 전부 보존하고, **threshold 비교만** 다음 계약으로 바꾼다:
--   * payload threshold 가 null/비-number → 차단
--   * abs(pl.threshold::double precision - payload::double precision) <= 1e-6 → 일치
--   * 차이가 1e-6 초과 → 차단
--
-- Rollback: 2026-07-17_python_evidence_universal_worker.sql 의 원본 fn_insert_python_evidence_run 정의로
--           CREATE OR REPLACE 재적용.

create or replace function public.fn_insert_python_evidence_run(p_run jsonb)
returns public.clip_python_evidence_runs
language plpgsql security invoker set search_path='' as $$
declare
  r public.clip_python_evidence_runs%rowtype;
  j public.python_evidence_jobs%rowtype;
  pl public.clip_prelabels%rowtype;
  v_clip uuid := (p_run->>'clip_id')::uuid;
  v_schema text := coalesce(p_run->>'evidence_schema_version','python-evidence-raw-v1');
  v_algo text := coalesce(p_run->>'algorithm_version','croi-temporal-v1');
  v_prelabel uuid := nullif(p_run->>'prelabel_id','')::uuid;
  arr text;
begin
  -- ── H3: job 잠금 + payload 일치 검증 (cross-clip/cross-version run 차단) ──
  select * into j from public.python_evidence_jobs where id=(p_run->>'job_id')::uuid for update;
  if not found then raise exception 'job not found for run' using errcode='22023'; end if;
  if j.clip_id <> v_clip
     or j.evidence_schema_version <> v_schema
     or j.algorithm_version <> v_algo then
    raise exception 'run payload does not match job (clip/schema/algorithm)' using errcode='22023';
  end if;
  -- ── H3: prelabel 연결 검증 — 같은 clip + 정확한 7-column provenance identity ──
  if v_prelabel is not null then
    select * into pl from public.clip_prelabels where id=v_prelabel;
    if not found then raise exception 'prelabel_id not found' using errcode='22023'; end if;
    if pl.clip_id <> v_clip then
      raise exception 'prelabel belongs to a different clip' using errcode='22023';
    end if;
    -- threshold: clip_prelabels.threshold 는 real(float4)라 numeric exact 비교 시 정밀도 오탐 발생.
    -- payload threshold 는 number 여야 하며(null/문자열 차단), pl.threshold 와 1e-6 tolerance 로 비교한다.
    if jsonb_typeof(p_run->'threshold') is distinct from 'number' then
      raise exception 'run provenance does not match linked prelabel identity' using errcode='22023';
    end if;
    if pl.model_name is distinct from p_run->>'model_name'
       or pl.model_version is distinct from p_run->>'model_version'
       or pl.checkpoint_sha256 is distinct from p_run->>'checkpoint_sha256'
       or pl.sampler_version is distinct from p_run->>'sampler_version'
       or pl.schema_version is distinct from p_run->>'schema_version'
       or pl.frames_sampled is distinct from nullif(p_run->>'frames_sampled','')::integer
       or abs(pl.threshold::double precision - (p_run->>'threshold')::double precision) > 1e-6 then
      raise exception 'run provenance does not match linked prelabel identity' using errcode='22023';
    end if;
  end if;
  -- ── H4: JSON 계약 검증 (object/array/원소 t·value numeric>=0) ──
  foreach arr in array array['metadata','motion_summary','spatial_dwell','periodicity_summary'] loop
    if jsonb_typeof(coalesce(p_run->arr,'{}'::jsonb)) <> 'object' then
      raise exception 'field % must be a JSON object', arr using errcode='22023';
    end if;
  end loop;
  foreach arr in array array['global_motion_series','roi_motion_series','motion_excursions'] loop
    if jsonb_typeof(coalesce(p_run->arr,'[]'::jsonb)) <> 'array' then
      raise exception 'field % must be a JSON array', arr using errcode='22023';
    end if;
    if jsonb_array_length(coalesce(p_run->arr,'[]'::jsonb)) > 256 then
      raise exception 'field % exceeds point cap 256', arr using errcode='22023';
    end if;
  end loop;
  foreach arr in array array['global_motion_series','roi_motion_series'] loop
    perform 1 from jsonb_array_elements(coalesce(p_run->arr,'[]'::jsonb)) e
      where not (
        jsonb_typeof(e) = 'object'
        and jsonb_typeof(e->'t') = 'number' and jsonb_typeof(e->'value') = 'number'
        and (e->>'t')::numeric >= 0 and (e->>'value')::numeric >= 0
      );
    if found then
      raise exception 'malformed series element in % (need object t,value numeric>=0)', arr using errcode='22023';
    end if;
  end loop;

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
    select * into r from public.clip_python_evidence_runs
      where clip_id=(p_run->>'clip_id')::uuid
        and evidence_schema_version=coalesce(p_run->>'evidence_schema_version','python-evidence-raw-v1')
        and algorithm_version=coalesce(p_run->>'algorithm_version','croi-temporal-v1')
        and source_prelabel_identity=coalesce(p_run->>'source_prelabel_identity','none');
  end if;
  return r;
end $$;

-- CREATE OR REPLACE 는 기존 ACL 을 보존하나 명시적으로 재확인(service_role only).
revoke all on function public.fn_insert_python_evidence_run(jsonb) from public, anon, authenticated;
grant execute on function public.fn_insert_python_evidence_run(jsonb) to service_role;
