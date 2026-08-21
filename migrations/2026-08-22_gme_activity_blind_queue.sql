BEGIN;

CREATE FUNCTION public.fn_current_gme_activity(p_clip_id uuid)
RETURNS TABLE (
  run_id uuid,
  detected boolean,
  activity_sec numeric,
  visible_sec numeric,
  state_intervals jsonb
)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  SELECT
    r.id,
    (r.visible_sec > 0 AND r.max_simultaneous_geckos > 0),
    r.candidate_moving_sec_any_gecko,
    r.visible_sec,
    r.state_intervals
  FROM public.gme_jobs j
  JOIN public.gme_runs r ON r.id = j.result_run_id
  WHERE j.clip_id = p_clip_id
    AND j.status = 'succeeded'
    AND r.status = 'ok'
  ORDER BY j.completed_at DESC NULLS LAST, j.id DESC
  LIMIT 1;
$$;

REVOKE ALL ON FUNCTION public.fn_current_gme_activity(uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_current_gme_activity(uuid) TO service_role;

COMMIT;
