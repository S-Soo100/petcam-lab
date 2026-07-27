-- 이중 블라인드 workspace progress 초기화 런타임 수정 — forward-only.
--
-- RETURNS TABLE의 output 이름 `group_id`/`reviewer_id`가 PL/pgSQL 변수로도 해석되어
-- column-list `ON CONFLICT`가 production에서 42702로 실패했다. 컬럼 추론 대신
-- 실제 PK constraint 이름을 사용하고 나머지 workspace 계약은 그대로 보존한다.

BEGIN;

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
      SELECT 1 FROM public.motion_clip_review_slots s
      WHERE s.reviewer_id = p_reviewer_id AND s.cohort_kind = 'live'
        AND s.activity_day_kst = v_oldest AND s.submitted_at IS NULL)
  LOOP
    v_oldest := v_oldest - 1;
  END LOOP;
  UPDATE public.motion_labeling_reviewer_progress rp
    SET oldest_unlocked_activity_day = v_oldest, updated_at = clock_timestamp()
    WHERE rp.group_id = v_group_id AND rp.reviewer_id = p_reviewer_id
      AND rp.oldest_unlocked_activity_day > v_oldest;

  SELECT max(s.activity_day_kst) INTO v_priority
  FROM public.motion_clip_review_slots s
  WHERE s.reviewer_id = p_reviewer_id AND s.cohort_kind = 'live'
    AND s.submitted_at IS NULL
    AND s.activity_day_kst BETWEEN v_oldest AND v_prev_closed;

  RETURN QUERY
  WITH days AS (
    SELECT DISTINCT s.activity_day_kst AS d
    FROM public.motion_clip_review_slots s
    WHERE s.reviewer_id = p_reviewer_id AND s.cohort_kind = 'live'
      AND s.submitted_at IS NULL
      AND s.activity_day_kst BETWEEN v_oldest AND v_prev_closed
  ),
  member_counts AS (
    SELECT mem.user_id,
           COALESCE(la.display_name, 'labeler') AS display_name,
           (SELECT count(*) FROM public.motion_clip_review_slots ms
             WHERE ms.group_id = v_group_id AND ms.reviewer_id = mem.user_id
               AND ms.cohort_kind = 'live' AND ms.activity_day_kst = v_priority
               AND ms.submitted_at IS NOT NULL) AS submitted_count
    FROM public.motion_labeling_review_group_members mem
    LEFT JOIN public.labeler_applications la ON la.user_id = mem.user_id
    WHERE mem.group_id = v_group_id AND mem.ended_at IS NULL
  )
  SELECT
    v_group_id, v_group_name, v_priority, v_oldest,
    COALESCE((SELECT array_agg(d ORDER BY d DESC) FROM days), ARRAY[]::date[]),
    (SELECT count(DISTINCT c.clip_id)::integer FROM public.motion_clip_consensus c
       WHERE c.group_id = v_group_id AND c.cohort_kind = 'live'
         AND EXISTS (SELECT 1 FROM public.motion_clip_review_slots s2
           WHERE s2.clip_id = c.clip_id AND s2.reviewer_id = p_reviewer_id
             AND s2.cohort_kind = 'live' AND s2.activity_day_kst = v_priority)),
    (SELECT count(*)::integer FROM public.motion_clip_review_slots s3
       WHERE s3.reviewer_id = p_reviewer_id AND s3.cohort_kind = 'live'
         AND s3.activity_day_kst = v_priority AND s3.submitted_at IS NOT NULL),
    (SELECT count(*)::integer FROM public.motion_clip_review_slots s4
       WHERE s4.group_id = v_group_id AND s4.reviewer_id <> p_reviewer_id
         AND s4.cohort_kind = 'live' AND s4.activity_day_kst = v_priority
         AND s4.submitted_at IS NOT NULL),
    (SELECT count(*)::integer FROM public.motion_clip_consensus c2
       WHERE c2.group_id = v_group_id AND c2.cohort_kind = 'live' AND c2.status = 'agreed'),
    (SELECT count(*)::integer FROM public.motion_clip_consensus c3
       WHERE c3.group_id = v_group_id AND c3.cohort_kind = 'live' AND c3.status = 'conflict'),
    (SELECT count(*)::integer FROM public.motion_clip_consensus c4
       WHERE c4.group_id = v_group_id AND c4.cohort_kind = 'live' AND c4.status = 'awaiting'),
    (SELECT count(*)::integer FROM public.motion_clip_review_slots s5
       WHERE s5.reviewer_id = p_reviewer_id AND s5.cohort_kind = 'live'
         AND s5.submitted_at IS NULL
         AND s5.activity_day_kst > COALESCE(v_priority, v_floor)
         AND s5.activity_day_kst <= v_prev_closed),
    COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'display_name', mc.display_name, 'submitted_count', mc.submitted_count))
      FROM member_counts mc), '[]'::jsonb);
END;
$$;

REVOKE ALL ON FUNCTION public.fn_get_motion_blind_workspace(uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_motion_blind_workspace(uuid)
  TO service_role;

COMMIT;
