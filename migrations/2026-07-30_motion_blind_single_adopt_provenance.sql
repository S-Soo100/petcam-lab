-- owner-single-adopt-v1은 한 reviewer 제출을 Owner가 운영 final로 채택한 provenance다.
-- final 값과 append-only 원장은 보존하고, library read source만 paired consensus와 분리한다.

BEGIN;

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
    WHERE m.r2_key IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM public.motion_clip_system_exclusions sx
        WHERE sx.clip_id=m.id AND sx.state IN ('quarantined','media_deleted')
      )
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
