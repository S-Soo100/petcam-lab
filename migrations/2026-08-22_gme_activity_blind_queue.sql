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

-- 기존 시간순 cursor RPC를 GME 탐지/활동량 keyset으로 forward 교체한다.
-- slot 생성 eligibility는 그대로 두고, live 큐의 표시 순서에만 GME 신호를 쓴다.
DROP FUNCTION public.fn_list_motion_blind_queue(
  uuid, date, text, uuid, timestamptz, uuid, integer
);

CREATE FUNCTION public.fn_list_motion_blind_queue(
  p_reviewer_id uuid,
  p_activity_day date,
  p_cohort_kind text DEFAULT 'live',
  p_cohort_id uuid DEFAULT NULL,
  p_cursor_detected boolean DEFAULT NULL,
  p_cursor_activity_sec numeric DEFAULT NULL,
  p_cursor_started_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 31
) RETURNS TABLE (
  clip_id uuid, camera_id uuid, camera_name text, started_at timestamptz,
  duration_sec double precision, media_ready boolean, activity_day_kst date,
  lease_expires_at timestamptz, rank_detected boolean, rank_activity_sec numeric
)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF p_cohort_kind NOT IN ('live','canary') THEN
    RAISE EXCEPTION 'invalid cohort kind' USING ERRCODE = '22023';
  END IF;
  IF (p_cohort_kind = 'canary') <> (p_cohort_id IS NOT NULL) THEN
    RAISE EXCEPTION 'cohort scope mismatch' USING ERRCODE = '22023';
  END IF;
  IF p_cohort_kind = 'live' AND p_activity_day IS NULL THEN
    RAISE EXCEPTION 'live queue requires activity day' USING ERRCODE = '22023';
  END IF;
  IF NOT (
    (p_cursor_detected IS NULL AND p_cursor_activity_sec IS NULL
      AND p_cursor_started_at IS NULL AND p_cursor_id IS NULL)
    OR
    (p_cursor_detected IS NOT NULL AND p_cursor_activity_sec IS NOT NULL
      AND p_cursor_started_at IS NOT NULL AND p_cursor_id IS NOT NULL)
  ) THEN
    RAISE EXCEPTION 'cursor requires detected, activity_sec, started_at, and id'
      USING ERRCODE = '22023';
  END IF;
  IF p_cursor_activity_sec < 0 THEN
    RAISE EXCEPTION 'cursor activity_sec must be non-negative' USING ERRCODE = '22023';
  END IF;

  RETURN QUERY
  SELECT
    ranked.clip_id,
    ranked.camera_id,
    ranked.camera_name,
    ranked.started_at,
    ranked.duration_sec,
    ranked.media_ready,
    ranked.activity_day_kst,
    ranked.lease_expires_at,
    ranked.rank_detected,
    ranked.rank_activity_sec
  FROM (
    SELECT
      m.id AS clip_id,
      m.camera_id AS camera_id,
      cam.name AS camera_name,
      m.started_at AS started_at,
      m.duration_sec AS duration_sec,
      true AS media_ready,
      s.activity_day_kst AS activity_day_kst,
      s.lease_expires_at AS lease_expires_at,
      CASE WHEN p_cohort_kind = 'live'
        THEN COALESCE(gme.detected, false)
        ELSE false
      END AS rank_detected,
      CASE WHEN p_cohort_kind = 'live' AND COALESCE(gme.detected, false)
        THEN COALESCE(gme.activity_sec, 0)
        ELSE 0
      END AS rank_activity_sec
    FROM public.motion_clip_review_slots s
    JOIN public.motion_clips m ON m.id = s.clip_id
    LEFT JOIN public.cameras cam ON cam.id = m.camera_id
    LEFT JOIN LATERAL public.fn_current_gme_activity(m.id) AS gme ON true
    WHERE s.reviewer_id = p_reviewer_id
      AND s.cohort_kind = p_cohort_kind
      AND (s.cohort_id IS NOT DISTINCT FROM p_cohort_id)
      AND (p_cohort_kind = 'canary' OR s.activity_day_kst = p_activity_day)
      AND s.submitted_at IS NULL
      AND public.fn_is_motion_clip_production_labeling_eligible(m.id)
  ) AS ranked
  WHERE p_cursor_detected IS NULL
    OR ranked.rank_detected < p_cursor_detected
    OR (
      ranked.rank_detected = p_cursor_detected
      AND ranked.rank_activity_sec < p_cursor_activity_sec
    )
    OR (
      ranked.rank_detected = p_cursor_detected
      AND ranked.rank_activity_sec = p_cursor_activity_sec
      AND ranked.started_at < p_cursor_started_at
    )
    OR (
      ranked.rank_detected = p_cursor_detected
      AND ranked.rank_activity_sec = p_cursor_activity_sec
      AND ranked.started_at = p_cursor_started_at
      AND ranked.clip_id < p_cursor_id
    )
  ORDER BY rank_detected DESC, rank_activity_sec DESC, started_at DESC, clip_id DESC
  LIMIT LEAST(GREATEST(p_limit, 1), 100);
END;
$$;

REVOKE ALL ON FUNCTION public.fn_list_motion_blind_queue(
  uuid, date, text, uuid, boolean, numeric, timestamptz, uuid, integer
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_blind_queue(
  uuid, date, text, uuid, boolean, numeric, timestamptz, uuid, integer
) TO service_role;

COMMIT;
