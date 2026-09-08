-- 최초 규칙 유지율은 보존하고, 계약별 최신 사람 판정 품질을 별도로 읽어.
BEGIN;
CREATE INDEX idx_highlight_verdict_initial_created
  ON public.motion_clip_highlight_verdicts(created_at, clip_id) WHERE kind = 'initial';
CREATE FUNCTION public.fn_highlight_quality_stats(p_from timestamptz, p_to timestamptz)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE result jsonb;
BEGIN
  IF p_from IS NULL OR p_to IS NULL OR NOT isfinite(p_from) OR NOT isfinite(p_to)
     OR p_from >= p_to OR p_to - p_from > interval '31 days' THEN
    RAISE EXCEPTION 'quality window must be within 31 days' USING ERRCODE = '22023';
  END IF;
  WITH samples AS MATERIALIZED (
    SELECT v.rule_version, c.camera_id, cam.name AS camera_name,
      (c.started_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date AS activity_day,
      r.engine_schema_version, r.algorithm_version, r.detector_identity,
      v.initial, v.initial_status, r.visible_sec, final.verdict, final.change_reason,
      final.kind = 'correction' AS corrected,
      coalesce(e.shadow, '{}'::text[]) AS shadow
    FROM public.motion_clip_highlight_verdicts v
    JOIN public.motion_clips c ON c.id = v.clip_id
    LEFT JOIN public.cameras cam ON cam.id = c.camera_id
    LEFT JOIN public.gme_runs r ON r.id = v.gme_run_id
    JOIN public.highlight_rule_versions rule ON rule.version = v.rule_version
    CROSS JOIN LATERAL (
      SELECT f.verdict, f.change_reason, f.kind
      FROM public.motion_clip_highlight_verdicts f
      WHERE f.clip_id = v.clip_id AND f.created_at < p_to
      ORDER BY f.created_at DESC, f.id DESC LIMIT 1
    ) final
    LEFT JOIN LATERAL public.fn_highlight_rule_eval(r, rule.params) e ON r.id IS NOT NULL
    WHERE v.kind = 'initial' AND v.created_at >= p_from AND v.created_at < p_to
  ), grouped AS (
    SELECT rule_version, camera_id, camera_name, activity_day,
      engine_schema_version, algorithm_version, detector_identity,
      count(*) AS reviewed_count,
      count(*) FILTER (WHERE initial AND verdict) AS o_to_o,
      count(*) FILTER (WHERE initial AND NOT verdict) AS o_to_x,
      count(*) FILTER (WHERE NOT initial AND verdict) AS x_to_o,
      count(*) FILTER (WHERE NOT initial AND NOT verdict) AS x_to_x,
      count(*) FILTER (WHERE initial_status = 'pending') AS pending_initial,
      count(*) FILTER (WHERE initial_status = 'failed') AS failed_initial,
      count(*) FILTER (WHERE corrected) AS correction_count,
      count(*) FILTER (WHERE initial AND NOT verdict AND change_reason IN
        ('false_detection','gecko_not_visible','camera_shake')) AS technical_rejects,
      count(*) FILTER (WHERE initial AND NOT verdict AND change_reason IN
        ('too_short','gecko_visible_not_highlight')) AS preference_rejects,
      count(*) FILTER (WHERE initial AND NOT verdict AND (change_reason IS NULL OR change_reason NOT IN
        ('false_detection','gecko_not_visible','camera_shake','too_short','gecko_visible_not_highlight'))) AS other_rejects,
      count(*) FILTER (WHERE initial = false AND verdict = false AND visible_sec = 0
        AND change_reason = 'gecko_visible_not_highlight') AS missed_visibility
    FROM samples
    GROUP BY rule_version,camera_id,camera_name,activity_day,engine_schema_version,algorithm_version,detector_identity
  ), shadow_grouped AS (
    SELECT rule_version,camera_id,camera_name,activity_day,engine_schema_version,algorithm_version,detector_identity,
      trigger_name,count(*) AS additional_count,count(*) FILTER (WHERE verdict) AS human_o
    FROM samples CROSS JOIN LATERAL (SELECT DISTINCT unnest(shadow) AS trigger_name) t
    WHERE initial = false
    GROUP BY rule_version,camera_id,camera_name,activity_day,engine_schema_version,algorithm_version,detector_identity,trigger_name
  )
  SELECT jsonb_build_object(
    'rows',coalesce((SELECT jsonb_agg(to_jsonb(g) ORDER BY activity_day DESC,camera_id,rule_version,
      engine_schema_version,algorithm_version,detector_identity) FROM grouped g),'[]'::jsonb),
    'shadow_rows',coalesce((SELECT jsonb_agg(to_jsonb(g) ORDER BY activity_day DESC,camera_id,rule_version,
      engine_schema_version,algorithm_version,detector_identity,trigger_name) FROM shadow_grouped g),'[]'::jsonb)
  ) INTO result;
  RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.fn_highlight_quality_stats(timestamptz,timestamptz) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_quality_stats(timestamptz,timestamptz) TO service_role;
COMMENT ON FUNCTION public.fn_highlight_quality_stats(timestamptz,timestamptz) IS
  '검수 시작 기간 × 최초 GME 계약. 종료시각 이전 최신 사람값과 비교하며, 전체 정확도가 아닌 검수 표본 품질이야.';
COMMIT;
