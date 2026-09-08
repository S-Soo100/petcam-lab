-- 활성 GME 계약 커버리지 (2.6.1 전환 준비 Task 7, owner 결정 2026-09-08).
-- "활성 계약(engine/algorithm/detector)으로 성공한 run 이 있는 영상" 비율을 최근 7일·전체로 센다.
-- 계약 전환 직후 최근 7일이 0% 로 떨어지는 게 정상이며, 백필이 찰수록 오른다 — 전환 타이밍 판단용(런북 §6).
-- 2026-09-08 실측: 8/27 이후 100%, 전체 47%(12,530/26,761). 읽기 전용, owner 현황과 같은 빈도로만 호출.
BEGIN;

CREATE FUNCTION public.fn_gme_contract_coverage(
  p_engine_schema_version text, p_algorithm_version text, p_detector_identity text
) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  WITH c AS (
    SELECT c.id, c.started_at,
           EXISTS (
             SELECT 1 FROM public.gme_jobs j
              WHERE j.clip_id = c.id AND j.status = 'succeeded'
                AND j.engine_schema_version = p_engine_schema_version
                AND j.algorithm_version = p_algorithm_version
                AND j.detector_identity = p_detector_identity
           ) AS has_run
      FROM public.motion_clips c
     WHERE c.r2_key IS NOT NULL
  )
  SELECT jsonb_build_object(
    'last7d_total',    count(*) FILTER (WHERE started_at >= now() - interval '7 days'),
    'last7d_with_run', count(*) FILTER (WHERE started_at >= now() - interval '7 days' AND has_run),
    'all_total',       count(*),
    'all_with_run',    count(*) FILTER (WHERE has_run)
  ) FROM c;
$$;

REVOKE ALL ON FUNCTION public.fn_gme_contract_coverage(text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_gme_contract_coverage(text, text, text) TO service_role;

COMMIT;
