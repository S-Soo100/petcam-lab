-- B그룹에 배정된 두 카메라만 50초 이상 기준을 적용한다.
--
-- 기존 slot/consensus/submission/삭제 감사 row는 보존하고 읽기 경로만 forward 교체한다.
-- 다른 카메라는 terminal exclusion 기준 외에 길이로 추가 제외하지 않는다.

BEGIN;

CREATE OR REPLACE FUNCTION public.fn_motion_blind_clip_is_labelable(
  p_clip_id uuid
) RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.motion_clips m
    WHERE m.id = p_clip_id
      AND (
        m.camera_id NOT IN (
          'f6599924-d133-4562-a48c-a06ff59db29d'::uuid, -- P4 Cam 2(dev)
          '90119209-4cdf-46f0-a151-c16d2445a1f1'::uuid  -- P4 Cam 3
        )
        OR m.duration_sec >= 50
      )
      AND NOT EXISTS (
        SELECT 1
        FROM public.motion_clip_system_exclusions sx
        WHERE sx.clip_id = m.id
          AND sx.state IN ('quarantined','media_deleted')
      )
  );
$$;

REVOKE ALL ON FUNCTION public.fn_motion_blind_clip_is_labelable(uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_motion_blind_clip_is_labelable(uuid)
  TO service_role;


CREATE OR REPLACE FUNCTION public.fn_list_motion_blind_queue(
  p_reviewer_id uuid,
  p_activity_day date,
  p_cohort_kind text DEFAULT 'live',
  p_cohort_id uuid DEFAULT NULL,
  p_cursor_started_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 31
) RETURNS TABLE (
  clip_id uuid, camera_id uuid, camera_name text, started_at timestamptz,
  duration_sec double precision, media_ready boolean, activity_day_kst date,
  lease_expires_at timestamptz
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
  IF (p_cursor_started_at IS NULL) <> (p_cursor_id IS NULL) THEN
    RAISE EXCEPTION 'cursor requires both started_at and id' USING ERRCODE = '22023';
  END IF;

  RETURN QUERY
  SELECT
    m.id AS clip_id,
    m.camera_id AS camera_id,
    cam.name AS camera_name,
    m.started_at AS started_at,
    m.duration_sec AS duration_sec,
    (m.r2_key IS NOT NULL) AS media_ready,
    s.activity_day_kst AS activity_day_kst,
    s.lease_expires_at AS lease_expires_at
  FROM public.motion_clip_review_slots s
  JOIN public.motion_clips m ON m.id = s.clip_id
  LEFT JOIN public.cameras cam ON cam.id = m.camera_id
  WHERE s.reviewer_id = p_reviewer_id
    AND s.cohort_kind = p_cohort_kind
    AND (s.cohort_id IS NOT DISTINCT FROM p_cohort_id)
    AND (p_cohort_kind = 'canary' OR s.activity_day_kst = p_activity_day)
    AND s.submitted_at IS NULL
    AND public.fn_motion_blind_clip_is_labelable(s.clip_id)
    AND (p_cursor_started_at IS NULL
         OR m.started_at < p_cursor_started_at
         OR (m.started_at = p_cursor_started_at AND m.id < p_cursor_id))
  ORDER BY m.started_at DESC, m.id DESC
  LIMIT LEAST(GREATEST(p_limit, 1), 100);
END;
$$;

REVOKE ALL ON FUNCTION public.fn_list_motion_blind_queue(
  uuid, date, text, uuid, timestamptz, uuid, integer
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_blind_queue(
  uuid, date, text, uuid, timestamptz, uuid, integer
) TO service_role;


CREATE OR REPLACE FUNCTION public.fn_get_motion_blind_workspace(
  p_reviewer_id uuid
) RETURNS TABLE (
  group_id uuid, group_name text,
  priority_activity_day date, oldest_unlocked_activity_day date,
  available_days date[],
  clip_total integer, own_submitted integer, partner_submitted integer,
  agreed_count integer, conflict_count integer, awaiting_count integer,
  late_added_count integer, members jsonb
)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_group_id uuid;
  v_group_name text;
  v_current_day date;
  v_prev_closed date;
  v_floor date;
  v_oldest date;
  v_priority date;
BEGIN
  SELECT g.id, g.name INTO v_group_id, v_group_name
  FROM public.motion_labeling_review_group_members mem
  JOIN public.motion_labeling_review_groups g ON g.id = mem.group_id AND g.active
  WHERE mem.user_id = p_reviewer_id AND mem.ended_at IS NULL
  FOR UPDATE OF mem;
  IF NOT FOUND THEN
    RETURN QUERY SELECT NULL::uuid, NULL::text, NULL::date, NULL::date,
      ARRAY[]::date[], 0, 0, 0, 0, 0, 0, 0, '[]'::jsonb;
    RETURN;
  END IF;

  v_current_day := (clock_timestamp() AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date;
  v_prev_closed := v_current_day - 1;
  v_floor := v_prev_closed - 29;

  SELECT rp.oldest_unlocked_activity_day INTO v_oldest
  FROM public.motion_labeling_reviewer_progress rp
  WHERE rp.group_id = v_group_id AND rp.reviewer_id = p_reviewer_id
  FOR UPDATE;
  IF NOT FOUND THEN
    v_oldest := v_prev_closed;
    INSERT INTO public.motion_labeling_reviewer_progress
      (group_id, reviewer_id, oldest_unlocked_activity_day)
    VALUES (v_group_id, p_reviewer_id, v_oldest)
    ON CONFLICT ON CONSTRAINT motion_labeling_reviewer_progress_pkey DO NOTHING;
  END IF;

  WHILE v_oldest > v_floor
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_review_slots s
      WHERE s.reviewer_id = p_reviewer_id
        AND s.cohort_kind = 'live'
        AND s.activity_day_kst = v_oldest
        AND s.submitted_at IS NULL
        AND public.fn_motion_blind_clip_is_labelable(s.clip_id)
    )
  LOOP
    v_oldest := v_oldest - 1;
  END LOOP;
  UPDATE public.motion_labeling_reviewer_progress rp
    SET oldest_unlocked_activity_day = v_oldest, updated_at = clock_timestamp()
    WHERE rp.group_id = v_group_id AND rp.reviewer_id = p_reviewer_id
      AND rp.oldest_unlocked_activity_day > v_oldest;

  SELECT max(s.activity_day_kst) INTO v_priority
  FROM public.motion_clip_review_slots s
  WHERE s.reviewer_id = p_reviewer_id
    AND s.cohort_kind = 'live'
    AND s.submitted_at IS NULL
    AND s.activity_day_kst BETWEEN v_oldest AND v_prev_closed
    AND public.fn_motion_blind_clip_is_labelable(s.clip_id);

  RETURN QUERY
  WITH days AS (
    SELECT DISTINCT s.activity_day_kst AS d
    FROM public.motion_clip_review_slots s
    WHERE s.reviewer_id = p_reviewer_id
      AND s.cohort_kind = 'live'
      AND s.submitted_at IS NULL
      AND s.activity_day_kst BETWEEN v_oldest AND v_prev_closed
      AND public.fn_motion_blind_clip_is_labelable(s.clip_id)
  ),
  member_counts AS (
    SELECT mem.user_id,
           COALESCE(la.display_name, 'labeler') AS display_name,
           (
             SELECT count(*)
             FROM public.motion_clip_review_slots ms
             WHERE ms.group_id = v_group_id
               AND ms.reviewer_id = mem.user_id
               AND ms.cohort_kind = 'live'
               AND ms.activity_day_kst = v_priority
               AND ms.submitted_at IS NOT NULL
               AND public.fn_motion_blind_clip_is_labelable(ms.clip_id)
           ) AS submitted_count
    FROM public.motion_labeling_review_group_members mem
    LEFT JOIN public.labeler_applications la ON la.user_id = mem.user_id
    WHERE mem.group_id = v_group_id AND mem.ended_at IS NULL
  )
  SELECT
    v_group_id,
    v_group_name,
    v_priority,
    v_oldest,
    COALESCE((SELECT array_agg(d ORDER BY d DESC) FROM days), ARRAY[]::date[]),
    (
      SELECT count(DISTINCT c.clip_id)::integer
      FROM public.motion_clip_consensus c
      WHERE c.group_id = v_group_id
        AND c.cohort_kind = 'live'
        AND EXISTS (
          SELECT 1
          FROM public.motion_clip_review_slots s2
          WHERE s2.clip_id = c.clip_id
            AND s2.reviewer_id = p_reviewer_id
            AND s2.cohort_kind = 'live'
            AND s2.activity_day_kst = v_priority
        )
        AND public.fn_motion_blind_clip_is_labelable(c.clip_id)
    ),
    (
      SELECT count(*)::integer
      FROM public.motion_clip_review_slots s3
      WHERE s3.reviewer_id = p_reviewer_id
        AND s3.cohort_kind = 'live'
        AND s3.activity_day_kst = v_priority
        AND s3.submitted_at IS NOT NULL
        AND public.fn_motion_blind_clip_is_labelable(s3.clip_id)
    ),
    (
      SELECT count(*)::integer
      FROM public.motion_clip_review_slots s4
      WHERE s4.group_id = v_group_id
        AND s4.reviewer_id <> p_reviewer_id
        AND s4.cohort_kind = 'live'
        AND s4.activity_day_kst = v_priority
        AND s4.submitted_at IS NOT NULL
        AND public.fn_motion_blind_clip_is_labelable(s4.clip_id)
    ),
    (
      SELECT count(*)::integer
      FROM public.motion_clip_consensus c2
      WHERE c2.group_id = v_group_id
        AND c2.cohort_kind = 'live'
        AND c2.status = 'agreed'
        AND public.fn_motion_blind_clip_is_labelable(c2.clip_id)
    ),
    (
      SELECT count(*)::integer
      FROM public.motion_clip_consensus c3
      WHERE c3.group_id = v_group_id
        AND c3.cohort_kind = 'live'
        AND c3.status = 'conflict'
        AND public.fn_motion_blind_clip_is_labelable(c3.clip_id)
    ),
    (
      SELECT count(*)::integer
      FROM public.motion_clip_consensus c4
      WHERE c4.group_id = v_group_id
        AND c4.cohort_kind = 'live'
        AND c4.status = 'awaiting'
        AND public.fn_motion_blind_clip_is_labelable(c4.clip_id)
    ),
    (
      SELECT count(*)::integer
      FROM public.motion_clip_review_slots s5
      WHERE s5.reviewer_id = p_reviewer_id
        AND s5.cohort_kind = 'live'
        AND s5.submitted_at IS NULL
        AND s5.activity_day_kst > COALESCE(v_priority, v_floor)
        AND s5.activity_day_kst <= v_prev_closed
        AND public.fn_motion_blind_clip_is_labelable(s5.clip_id)
    ),
    COALESCE(
      (
        SELECT jsonb_agg(jsonb_build_object(
          'display_name', mc.display_name,
          'submitted_count', mc.submitted_count
        ))
        FROM member_counts mc
      ),
      '[]'::jsonb
    );
END;
$$;

REVOKE ALL ON FUNCTION public.fn_get_motion_blind_workspace(uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_motion_blind_workspace(uuid)
  TO service_role;

COMMIT;
