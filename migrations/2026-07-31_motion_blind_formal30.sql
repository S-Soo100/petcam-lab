-- Formal Blind30 infrastructure only: exact-30 reservation without creating a cohort yet.
--
-- This forward migration adds one service-role-only RPC. It never rewrites existing
-- slots, submissions, consensus, events, or final values. Actual reservation remains
-- a separate human-gated operation after a qualified reviewer pair exists.

BEGIN;

CREATE OR REPLACE FUNCTION public.fn_create_motion_blind_formal30(
  p_actor_id uuid,
  p_group_id uuid,
  p_clip_ids uuid[],
  p_reviewer_ids uuid[],
  p_manifest_sha256 text,
  p_selection_t0 timestamptz
) RETURNS uuid
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_cohort_id uuid;
  v_clip_count integer;
  v_qualified_reviewers integer;
  v_slot_count integer;
  v_consensus_count integer;
BEGIN
  IF p_actor_id IS NULL OR p_group_id IS NULL THEN
    RAISE EXCEPTION 'formal30 actor and group are required' USING ERRCODE = '22023';
  END IF;
  IF p_selection_t0 IS NULL OR p_selection_t0 >= clock_timestamp() THEN
    RAISE EXCEPTION 'formal30 invalid T0' USING ERRCODE = '22023';
  END IF;
  IF p_manifest_sha256 IS NULL OR p_manifest_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'formal30 invalid manifest hash' USING ERRCODE = '22023';
  END IF;
  IF p_clip_ids IS NULL OR array_length(p_clip_ids, 1) <> 30 THEN
    RAISE EXCEPTION 'formal30 needs 30 distinct clips' USING ERRCODE = '22023';
  END IF;
  IF (
    SELECT count(DISTINCT clip_id)
    FROM unnest(p_clip_ids) AS requested(clip_id)
  ) <> 30 THEN
    RAISE EXCEPTION 'formal30 needs 30 distinct clips' USING ERRCODE = '22023';
  END IF;
  IF EXISTS (SELECT 1 FROM unnest(p_clip_ids) AS requested(clip_id) WHERE clip_id IS NULL) THEN
    RAISE EXCEPTION 'formal30 clip id cannot be null' USING ERRCODE = '22023';
  END IF;

  IF p_reviewer_ids IS NULL OR array_length(p_reviewer_ids, 1) <> 2 THEN
    RAISE EXCEPTION 'formal30 needs two distinct reviewers' USING ERRCODE = 'PT425';
  END IF;
  IF (
    SELECT count(DISTINCT reviewer_id)
    FROM unnest(p_reviewer_ids) AS requested(reviewer_id)
  ) <> 2 THEN
    RAISE EXCEPTION 'formal30 needs two distinct reviewers' USING ERRCODE = 'PT425';
  END IF;
  IF EXISTS (
    SELECT 1 FROM unnest(p_reviewer_ids) AS requested(reviewer_id)
    WHERE reviewer_id IS NULL
  ) THEN
    RAISE EXCEPTION 'formal30 reviewer id cannot be null' USING ERRCODE = 'PT425';
  END IF;
  IF p_actor_id = ANY(p_reviewer_ids) THEN
    RAISE EXCEPTION 'formal30 actor cannot be reviewer' USING ERRCODE = 'PT425';
  END IF;

  -- Lock the active group and its exact two-member snapshot before qualification.
  PERFORM 1
  FROM public.motion_labeling_review_groups g
  WHERE g.id = p_group_id AND g.active
  FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'formal30 requires active group' USING ERRCODE = 'PT425';
  END IF;

  PERFORM 1
  FROM public.motion_labeling_review_group_members gm
  WHERE gm.group_id = p_group_id AND gm.ended_at IS NULL
  ORDER BY gm.user_id
  FOR UPDATE;
  IF (
    SELECT count(*)
    FROM public.motion_labeling_review_group_members gm
    WHERE gm.group_id = p_group_id AND gm.ended_at IS NULL
  ) <> 2 THEN
    RAISE EXCEPTION 'formal30 group must have exactly two active members'
      USING ERRCODE = 'PT425';
  END IF;

  SELECT count(*) INTO v_qualified_reviewers
  FROM unnest(p_reviewer_ids) AS requested(reviewer_id)
  WHERE EXISTS (
      SELECT 1 FROM public.labelers l
      WHERE l.user_id = requested.reviewer_id
    )
    AND EXISTS (
      SELECT 1 FROM public.labeler_applications a
      WHERE a.user_id = requested.reviewer_id AND a.status = 'approved'
    )
    AND EXISTS (
      SELECT 1
      FROM public.motion_labeling_review_group_members gm
      WHERE gm.group_id = p_group_id
        AND gm.user_id = requested.reviewer_id
        AND gm.ended_at IS NULL
    )
    AND EXISTS (
      SELECT 1
      FROM public.labeling_tutorial_sets ts
      JOIN public.labeling_tutorial_progress tp
        ON tp.tutorial_set_id = ts.id
       AND tp.user_id = requested.reviewer_id
      JOIN public.labeling_tutorial_lessons tl
        ON tl.tutorial_set_id = ts.id
      JOIN public.labeling_tutorial_attempts ta
        ON ta.tutorial_set_id = ts.id
       AND ta.lesson_id = tl.id
       AND ta.user_id = requested.reviewer_id
       AND ta.run_no = tp.current_run_no
       AND ta.stage = 'completed'
       AND ta.completed_at IS NOT NULL
      WHERE ts.version = 'tutorial-v1'
        AND ts.status = 'active'
        AND tp.completed_at IS NOT NULL
        AND tp.waived_at IS NULL
      GROUP BY ts.id, tp.user_id, tp.current_run_no
      HAVING count(DISTINCT tl.position) = 5
    );
  IF v_qualified_reviewers <> 2 THEN
    RAISE EXCEPTION 'formal30 reviewers are not qualified' USING ERRCODE = 'PT425';
  END IF;

  -- Stable clip locking serializes two formal reservations and freezes eligibility checks.
  PERFORM 1
  FROM public.motion_clips m
  WHERE m.id = ANY(p_clip_ids)
  ORDER BY m.id
  FOR UPDATE;

  SELECT count(*) INTO v_clip_count
  FROM public.motion_clips m
  WHERE m.id = ANY(p_clip_ids)
    AND m.started_at < p_selection_t0
    AND m.r2_key IS NOT NULL
    AND public.fn_motion_blind_clip_is_labelable(m.id)
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_system_exclusions sx
      WHERE sx.clip_id = m.id
        AND sx.state IN ('quarantined','media_deleted')
    )
    AND NOT EXISTS (
      SELECT 1
      FROM public.labeling_tutorial_lessons tl
      WHERE tl.clip_id = m.id
    )
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_review_slots cs
      WHERE cs.clip_id = m.id
        AND cs.cohort_kind = 'canary'
    )
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_consensus cc
      WHERE cc.clip_id = m.id
        AND cc.cohort_kind = 'canary'
    )
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_blind_submissions bs
      WHERE bs.clip_id = m.id
    )
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_labeling_sessions ls
      WHERE ls.clip_id = m.id
    )
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_consensus lc
      WHERE lc.clip_id = m.id
        AND lc.cohort_kind = 'live'
        AND lc.status IN ('agreed','conflict','owner_resolved')
    );
  IF v_clip_count <> 30 THEN
    RAISE EXCEPTION 'formal30 clip eligibility changed' USING ERRCODE = '22023';
  END IF;

  INSERT INTO public.motion_blind_review_cohorts (
    kind, status, label, group_id, created_by
  ) VALUES (
    'canary', 'open', 'b30v1:' || p_manifest_sha256, p_group_id, p_actor_id
  )
  RETURNING id INTO v_cohort_id;

  INSERT INTO public.motion_clip_review_slots (
    clip_id, group_id, reviewer_id, cohort_kind, cohort_id, activity_day_kst
  )
  SELECT
    m.id,
    p_group_id,
    reviewer.reviewer_id,
    'canary',
    v_cohort_id,
    (m.started_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date
  FROM public.motion_clips m
  CROSS JOIN unnest(p_reviewer_ids) AS reviewer(reviewer_id)
  WHERE m.id = ANY(p_clip_ids)
  ORDER BY m.id, reviewer.reviewer_id;
  GET DIAGNOSTICS v_slot_count = ROW_COUNT;
  IF v_slot_count <> 60 THEN
    RAISE EXCEPTION 'formal30 slot invariant failed' USING ERRCODE = 'PT425';
  END IF;

  INSERT INTO public.motion_clip_consensus (
    clip_id, group_id, cohort_kind, cohort_id, status
  )
  SELECT m.id, p_group_id, 'canary', v_cohort_id, 'awaiting'
  FROM public.motion_clips m
  WHERE m.id = ANY(p_clip_ids)
  ORDER BY m.id;
  GET DIAGNOSTICS v_consensus_count = ROW_COUNT;
  IF v_consensus_count <> 30 THEN
    RAISE EXCEPTION 'formal30 consensus invariant failed' USING ERRCODE = 'PT425';
  END IF;

  RETURN v_cohort_id;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_create_motion_blind_formal30(
  uuid, uuid, uuid[], uuid[], text, timestamptz
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_create_motion_blind_formal30(
  uuid, uuid, uuid[], uuid[], text, timestamptz
) TO service_role;

COMMIT;
