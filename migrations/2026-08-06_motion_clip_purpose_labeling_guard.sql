-- 펌웨어 개발용 test clip의 운영 라벨링 재진입을 DB read/materialization 경계에서 차단한다.
--
-- 소유권: motion_clips.clip_purpose 컬럼·CHECK·백필은 terra-server migration 소유다.
-- 이 migration은 해당 선행 계약이 없으면 즉시 실패하고 consumer RPC만 forward 교체한다.
-- 목적과 현재 경로를 모두 검사한다. `test/가 아님` 같은 음수 조건은 격리·삭제 namespace를
-- production으로 오인하므로 금지한다.

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'motion_clips'
      AND column_name = 'clip_purpose'
  ) THEN
    RAISE EXCEPTION 'motion_clips.clip_purpose prerequisite missing'
      USING ERRCODE = '55000';
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_is_motion_clip_production_labeling_eligible(
  p_clip_id uuid
) RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.motion_clips m
    WHERE m.id = p_clip_id
      AND m.clip_purpose = 'production'
      AND m.r2_key LIKE 'terra-clips/clips/%'
      AND NOT EXISTS (
        SELECT 1
        FROM public.motion_clip_system_exclusions sx
        WHERE sx.clip_id = m.id
          AND sx.state IN ('quarantined', 'media_deleted')
      )
  );
$$;

REVOKE ALL ON FUNCTION public.fn_is_motion_clip_production_labeling_eligible(uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_is_motion_clip_production_labeling_eligible(uuid)
  TO service_role;

-- 현재 활성본: 2026-07-27_motion_blind_slot_materialization_scale.sql.
CREATE OR REPLACE FUNCTION public.fn_ensure_motion_review_slots(
  p_reviewer_id uuid,
  p_activity_day date
) RETURNS integer
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_group_id uuid;
  v_members uuid[];
  v_from timestamptz;
  v_to timestamptz;
  v_materialized integer := 0;
BEGIN
  SELECT group_id INTO v_group_id
  FROM public.motion_labeling_review_group_members
  WHERE user_id = p_reviewer_id AND ended_at IS NULL;
  IF NOT FOUND THEN
    RETURN 0;
  END IF;

  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(v_group_id::text, 0)
  );

  PERFORM 1
  FROM public.motion_labeling_review_group_members
  WHERE group_id = v_group_id AND ended_at IS NULL
  ORDER BY user_id
  FOR UPDATE;

  SELECT array_agg(user_id ORDER BY user_id)
  INTO v_members
  FROM public.motion_labeling_review_group_members
  WHERE group_id = v_group_id AND ended_at IS NULL;

  IF v_members IS NULL OR array_length(v_members, 1) <> 2 THEN
    RAISE EXCEPTION 'group_invariant: active group must have two members'
      USING ERRCODE = 'PT425';
  END IF;

  v_from := public.fn_motion_activity_day_start(p_activity_day - 29);
  v_to := public.fn_motion_activity_day_start(p_activity_day + 1);

  INSERT INTO public.motion_clip_consensus
    (clip_id, group_id, cohort_kind, cohort_id, status)
  SELECT m.id, v_group_id, 'live', NULL, 'awaiting'
  FROM public.motion_clips m
  JOIN public.motion_labeling_review_group_cameras gc
    ON gc.camera_id = m.camera_id
   AND gc.group_id = v_group_id
   AND gc.ended_at IS NULL
  WHERE m.started_at >= v_from
    AND m.started_at < v_to
    AND public.fn_is_motion_clip_production_labeling_eligible(m.id)
  ON CONFLICT (clip_id) WHERE cohort_kind = 'live' DO NOTHING;

  IF EXISTS (
    SELECT s.clip_id
    FROM public.motion_clip_review_slots s
    JOIN public.motion_clip_consensus c
      ON c.clip_id = s.clip_id
     AND c.cohort_kind = 'live'
     AND c.group_id = v_group_id
    JOIN public.motion_clips m ON m.id = s.clip_id
    JOIN public.motion_labeling_review_group_cameras gc
      ON gc.camera_id = m.camera_id
     AND gc.group_id = v_group_id
     AND gc.ended_at IS NULL
    WHERE s.cohort_kind = 'live'
      AND m.started_at >= v_from
      AND m.started_at < v_to
      AND public.fn_is_motion_clip_production_labeling_eligible(m.id)
    GROUP BY s.clip_id
    HAVING count(*) <> 2
  ) THEN
    RAISE EXCEPTION 'live clip must have zero or two slots'
      USING ERRCODE = 'PT425';
  END IF;

  INSERT INTO public.motion_clip_review_slots
    (clip_id, group_id, reviewer_id, cohort_kind, cohort_id, activity_day_kst)
  SELECT
    m.id,
    v_group_id,
    mem.user_id,
    'live',
    NULL,
    (m.started_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date
  FROM public.motion_clips m
  JOIN public.motion_labeling_review_group_cameras gc
    ON gc.camera_id = m.camera_id
   AND gc.group_id = v_group_id
   AND gc.ended_at IS NULL
  JOIN public.motion_clip_consensus c
    ON c.clip_id = m.id
   AND c.cohort_kind = 'live'
   AND c.group_id = v_group_id
  CROSS JOIN unnest(v_members) AS mem(user_id)
  WHERE m.started_at >= v_from
    AND m.started_at < v_to
    AND public.fn_is_motion_clip_production_labeling_eligible(m.id)
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_review_slots existing
      WHERE existing.clip_id = m.id
        AND existing.cohort_kind = 'live'
    )
  ON CONFLICT (clip_id, reviewer_id) WHERE cohort_kind = 'live' DO NOTHING;

  IF EXISTS (
    SELECT c.clip_id
    FROM public.motion_clip_consensus c
    JOIN public.motion_clips m ON m.id = c.clip_id
    JOIN public.motion_labeling_review_group_cameras gc
      ON gc.camera_id = m.camera_id
     AND gc.group_id = v_group_id
     AND gc.ended_at IS NULL
    LEFT JOIN public.motion_clip_review_slots s
      ON s.clip_id = c.clip_id AND s.cohort_kind = 'live'
    WHERE c.cohort_kind = 'live'
      AND c.group_id = v_group_id
      AND m.started_at >= v_from
      AND m.started_at < v_to
      AND public.fn_is_motion_clip_production_labeling_eligible(m.id)
    GROUP BY c.clip_id
    HAVING count(s.id) <> 2
  ) THEN
    RAISE EXCEPTION 'live clip must have zero or two slots'
      USING ERRCODE = 'PT425';
  END IF;

  SELECT count(*) INTO v_materialized
  FROM public.motion_clip_consensus c
  JOIN public.motion_clips m ON m.id = c.clip_id
  JOIN public.motion_labeling_review_group_cameras gc
    ON gc.camera_id = m.camera_id
   AND gc.group_id = v_group_id
   AND gc.ended_at IS NULL
  WHERE c.cohort_kind = 'live'
    AND c.group_id = v_group_id
    AND m.started_at >= v_from
    AND m.started_at < v_to
    AND public.fn_is_motion_clip_production_labeling_eligible(m.id);

  RETURN v_materialized;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_ensure_motion_review_slots(uuid, date)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_ensure_motion_review_slots(uuid, date)
  TO service_role;

-- 현재 활성본: 2026-07-28_motion_blind_terminal_exclusion_normalization.sql.
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
    m.id,
    m.camera_id,
    cam.name,
    m.started_at,
    m.duration_sec,
    true,
    s.activity_day_kst,
    s.lease_expires_at
  FROM public.motion_clip_review_slots s
  JOIN public.motion_clips m ON m.id = s.clip_id
  LEFT JOIN public.cameras cam ON cam.id = m.camera_id
  WHERE s.reviewer_id = p_reviewer_id
    AND s.cohort_kind = p_cohort_kind
    AND (s.cohort_id IS NOT DISTINCT FROM p_cohort_id)
    AND (p_cohort_kind = 'canary' OR s.activity_day_kst = p_activity_day)
    AND s.submitted_at IS NULL
    AND public.fn_is_motion_clip_production_labeling_eligible(m.id)
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

-- 현재 활성본: 2026-07-24_short_clip_device_error_retention.sql.
CREATE OR REPLACE FUNCTION public.fn_list_motion_clip_labeling_queue(
  p_reviewer_id uuid,
  p_is_owner boolean,
  p_state text DEFAULT NULL,
  p_camera_ids uuid[] DEFAULT NULL,
  p_date_from timestamptz DEFAULT NULL,
  p_date_to timestamptz DEFAULT NULL,
  p_media text DEFAULT NULL,
  p_cursor_started_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 31
) RETURNS TABLE (
  clip_id uuid, camera_id uuid, camera_name text, started_at timestamptz,
  duration_sec double precision, media_ready boolean, state text,
  session_stage text, state_updated_at timestamptz
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  IF p_state IS NOT NULL AND p_state NOT IN ('unreviewed','label','hold','skip') THEN
    RAISE EXCEPTION 'invalid state filter: %', p_state USING ERRCODE = '22023';
  END IF;
  IF p_media IS NOT NULL AND p_media NOT IN ('ready','unavailable') THEN
    RAISE EXCEPTION 'invalid media filter: %', p_media USING ERRCODE = '22023';
  END IF;
  IF (p_cursor_started_at IS NULL) <> (p_cursor_id IS NULL) THEN
    RAISE EXCEPTION 'cursor requires both started_at and id' USING ERRCODE = '22023';
  END IF;

  RETURN QUERY
  SELECT
    m.id,
    m.camera_id,
    cam.name,
    m.started_at,
    m.duration_sec,
    true,
    COALESCE(t.owner_decision, 'unreviewed'),
    s.stage,
    t.updated_at
  FROM public.motion_clips m
  LEFT JOIN public.cameras cam ON cam.id = m.camera_id
  LEFT JOIN public.motion_clip_labeling_triage t ON t.clip_id = m.id
  LEFT JOIN public.motion_clip_labeling_sessions s
    ON s.clip_id = m.id AND s.reviewed_by = p_reviewer_id
  WHERE public.fn_is_motion_clip_production_labeling_eligible(m.id)
    AND (p_cursor_started_at IS NULL
     OR m.started_at < p_cursor_started_at
     OR (m.started_at = p_cursor_started_at AND m.id < p_cursor_id))
    AND (p_camera_ids IS NULL OR m.camera_id = ANY (p_camera_ids))
    AND (p_date_from IS NULL OR m.started_at >= p_date_from)
    AND (p_date_to IS NULL OR m.started_at < p_date_to)
    AND (p_media IS NULL OR p_media = 'ready')
    AND (
      CASE WHEN p_is_owner THEN
        (p_state IS NULL
         OR (p_state = 'unreviewed' AND t.owner_decision IS NULL)
         OR t.owner_decision = p_state)
      ELSE
        (t.owner_decision = 'label'
         AND NOT EXISTS (
           SELECT 1 FROM public.motion_clip_labeling_sessions cs
           WHERE cs.clip_id = m.id AND cs.reviewed_by = p_reviewer_id
             AND cs.stage = 'completed'))
      END
    )
  ORDER BY m.started_at DESC, m.id DESC
  LIMIT LEAST(GREATEST(p_limit, 1), 100);
END;
$$;

REVOKE ALL ON FUNCTION public.fn_list_motion_clip_labeling_queue(
  uuid, boolean, text, uuid[], timestamptz, timestamptz, text,
  timestamptz, uuid, integer
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_clip_labeling_queue(
  uuid, boolean, text, uuid[], timestamptz, timestamptz, text,
  timestamptz, uuid, integer
) TO service_role;

-- 현재 활성본: 2026-07-30_motion_blind_single_adopt_provenance.sql.
CREATE OR REPLACE FUNCTION public.fn_list_motion_labeling_library(
  p_owner_id uuid,
  p_clip_id uuid DEFAULT NULL,
  p_label_state text DEFAULT NULL,
  p_camera_ids uuid[] DEFAULT NULL,
  p_date_from timestamptz DEFAULT NULL,
  p_date_to timestamptz DEFAULT NULL,
  p_time_from text DEFAULT NULL,
  p_time_to text DEFAULT NULL,
  p_label_source text DEFAULT NULL,
  p_final_decision text DEFAULT NULL,
  p_cursor_started_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 31
) RETURNS TABLE (
  clip_id uuid, camera_id uuid, camera_name text, started_at timestamptz,
  duration_sec double precision, label_state text, label_source text,
  final_decision text, final_gt jsonb
)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF p_label_state IS NOT NULL
     AND p_label_state NOT IN ('final','awaiting','owner_review','unlabeled','re_review') THEN
    RAISE EXCEPTION 'invalid label state' USING ERRCODE='22023';
  END IF;
  IF p_label_source IS NOT NULL
     AND p_label_source NOT IN (
       'blind_consensus','owner_single_adopt','owner_legacy','single_legacy','none'
     ) THEN
    RAISE EXCEPTION 'invalid label source' USING ERRCODE='22023';
  END IF;
  IF p_final_decision IS NOT NULL AND p_final_decision NOT IN ('label','hold','exclude') THEN
    RAISE EXCEPTION 'invalid final decision' USING ERRCODE='22023';
  END IF;
  IF (p_cursor_started_at IS NULL) <> (p_cursor_id IS NULL) THEN
    RAISE EXCEPTION 'cursor requires both fields' USING ERRCODE='22023';
  END IF;
  IF (p_time_from IS NULL) <> (p_time_to IS NULL)
     OR (p_time_from IS NOT NULL AND p_time_from !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$')
     OR (p_time_to IS NOT NULL AND p_time_to !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$') THEN
    RAISE EXCEPTION 'invalid time range' USING ERRCODE='22023';
  END IF;

  RETURN QUERY
  WITH base AS (
    SELECT m.id, m.camera_id, cam.name AS camera_name, m.started_at, m.duration_sec,
           lc.status AS live_status, lc.comparator_version AS live_comparator_version,
           lc.final_decision AS live_decision, lc.final_gt AS live_gt,
           cy.canary_status, cy.canary_comparator_version,
           cy.canary_decision, cy.canary_gt,
           ls.reviewed_by AS legacy_reviewer, ls.legacy_gt
    FROM public.motion_clips m
    LEFT JOIN public.cameras cam ON cam.id=m.camera_id
    LEFT JOIN public.motion_clip_consensus lc
      ON lc.clip_id=m.id AND lc.cohort_kind='live'
    LEFT JOIN LATERAL (
      SELECT cc.status AS canary_status,
             cc.comparator_version AS canary_comparator_version,
             cc.final_decision AS canary_decision, cc.final_gt AS canary_gt
      FROM public.motion_clip_consensus cc
      JOIN public.motion_blind_review_cohorts co ON co.id=cc.cohort_id
      WHERE cc.clip_id=m.id AND cc.cohort_kind='canary'
      ORDER BY (co.status='open') DESC, co.created_at DESC, cc.id DESC
      LIMIT 1
    ) cy ON true
    LEFT JOIN LATERAL (
      SELECT s.reviewed_by, COALESCE(s.current_gt,s.initial_gt) AS legacy_gt
      FROM public.motion_clip_labeling_sessions s
      WHERE s.clip_id=m.id AND s.initial_gt IS NOT NULL
      ORDER BY (s.reviewed_by=p_owner_id) DESC, s.updated_at DESC, s.id DESC
      LIMIT 1
    ) ls ON true
    WHERE public.fn_is_motion_clip_production_labeling_eligible(m.id)
      AND (p_clip_id IS NULL OR m.id=p_clip_id)
      AND (p_camera_ids IS NULL OR m.camera_id=ANY(p_camera_ids))
      AND (p_date_from IS NULL OR m.started_at>=p_date_from)
      AND (p_date_to IS NULL OR m.started_at<=p_date_to)
      AND (
        p_time_from IS NULL
        OR (
          p_time_from<=p_time_to
          AND to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI')
              BETWEEN p_time_from AND p_time_to
        )
        OR (
          p_time_from>p_time_to
          AND (
            to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI')>=p_time_from
            OR to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI')<=p_time_to
          )
        )
      )
  ), classified AS (
    SELECT base.*,
      CASE
        WHEN canary_status IN ('agreed','owner_resolved') THEN 'final'
        WHEN canary_status IN ('awaiting','conflict') THEN 're_review'
        WHEN live_status IN ('agreed','owner_resolved') THEN 'final'
        WHEN live_status = 'conflict' THEN 'owner_review'
        WHEN live_status = 'awaiting' THEN 'awaiting'
        WHEN legacy_gt IS NOT NULL THEN 'final'
        ELSE 'unlabeled'
      END AS public_state,
      CASE
        WHEN canary_status IS NOT NULL
          AND canary_comparator_version = 'owner-single-adopt-v1'
          THEN 'owner_single_adopt'
        WHEN canary_status IS NOT NULL THEN 'blind_consensus'
        WHEN live_status IS NOT NULL
          AND live_comparator_version = 'owner-single-adopt-v1'
          THEN 'owner_single_adopt'
        WHEN live_status IS NOT NULL THEN 'blind_consensus'
        WHEN legacy_gt IS NOT NULL AND legacy_reviewer=p_owner_id THEN 'owner_legacy'
        WHEN legacy_gt IS NOT NULL THEN 'single_legacy'
        ELSE 'none'
      END AS public_source,
      CASE
        WHEN canary_status IN ('agreed','owner_resolved') THEN canary_decision
        WHEN canary_status IS NOT NULL THEN NULL::text
        WHEN live_status IN ('agreed','owner_resolved') THEN live_decision
        WHEN live_status IS NOT NULL THEN NULL::text
        WHEN legacy_gt IS NOT NULL THEN 'label'
        ELSE NULL::text
      END AS public_decision,
      CASE
        WHEN canary_status IN ('agreed','owner_resolved') THEN canary_gt
        WHEN canary_status IS NOT NULL THEN NULL::jsonb
        WHEN live_status IN ('agreed','owner_resolved') THEN live_gt
        WHEN live_status IS NOT NULL THEN NULL::jsonb
        WHEN legacy_gt IS NOT NULL THEN legacy_gt
        ELSE NULL::jsonb
      END AS public_gt
    FROM base
  )
  SELECT c.id, c.camera_id, c.camera_name, c.started_at, c.duration_sec,
         c.public_state, c.public_source, c.public_decision, c.public_gt
  FROM classified c
  WHERE (p_label_state IS NULL OR c.public_state=p_label_state)
    AND (p_label_source IS NULL OR c.public_source=p_label_source)
    AND (p_final_decision IS NULL OR c.public_decision=p_final_decision)
    AND (p_cursor_started_at IS NULL OR c.started_at<p_cursor_started_at
      OR (c.started_at=p_cursor_started_at AND c.id<p_cursor_id))
  ORDER BY c.started_at DESC, c.id DESC
  LIMIT LEAST(GREATEST(p_limit,1),101);
END;
$$;

REVOKE ALL ON FUNCTION public.fn_list_motion_labeling_library(
  uuid, uuid, text, uuid[], timestamptz, timestamptz,
  text, text, text, text, timestamptz, uuid, integer
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_labeling_library(
  uuid, uuid, text, uuid[], timestamptz, timestamptz,
  text, text, text, text, timestamptz, uuid, integer
) TO service_role;

COMMIT;
