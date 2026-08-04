-- Library와 dashboard가 append-only canonical head만 GT 정답으로 읽게 하는 additive RPC.
BEGIN;

CREATE OR REPLACE FUNCTION public.fn_list_motion_labeling_library_canonical(
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
  final_decision text, final_gt jsonb, gt_revision_id uuid,
  gt_source_type text, gt_updated_at timestamptz
)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF p_owner_id IS NULL THEN
    RAISE EXCEPTION 'owner required' USING ERRCODE='22023';
  END IF;
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
           h.revision_id, h.updated_at AS head_updated_at,
           r.final_decision AS head_decision, r.gt AS head_gt,
           r.source_type AS head_source_type,
           EXISTS (
             SELECT 1
             FROM public.motion_clip_review_slots cs
             JOIN public.motion_blind_review_cohorts co ON co.id = cs.cohort_id
             WHERE cs.clip_id = m.id AND cs.cohort_kind = 'canary'
               AND co.status = 'open'
           ) AS has_open_canary,
           COALESCE(ls.slot_count, 0) AS live_slot_count,
           (q.status = 'pending') AS has_pending_reconciliation
    FROM public.motion_clips m
    LEFT JOIN public.cameras cam ON cam.id = m.camera_id
    LEFT JOIN public.motion_clip_gt_heads h ON h.clip_id = m.id
    LEFT JOIN public.motion_clip_gt_revisions r
      ON r.id = h.revision_id AND r.clip_id = h.clip_id
    LEFT JOIN public.motion_clip_gt_reconciliation q ON q.clip_id = m.id
    LEFT JOIN LATERAL (
      SELECT count(*)::integer AS slot_count
      FROM public.motion_clip_review_slots s
      WHERE s.clip_id = m.id AND s.cohort_kind = 'live'
    ) ls ON true
    WHERE m.r2_key IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM public.motion_clip_system_exclusions sx
        WHERE sx.clip_id = m.id AND sx.state IN ('quarantined','media_deleted')
      )
      AND (p_clip_id IS NULL OR m.id = p_clip_id)
      AND (p_camera_ids IS NULL OR m.camera_id = ANY(p_camera_ids))
      AND (p_date_from IS NULL OR m.started_at >= p_date_from)
      AND (p_date_to IS NULL OR m.started_at <= p_date_to)
      AND (
        p_time_from IS NULL
        OR (
          p_time_from <= p_time_to
          AND to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI')
              BETWEEN p_time_from AND p_time_to
        )
        OR (
          p_time_from > p_time_to
          AND (
            to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI') >= p_time_from
            OR to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI') <= p_time_to
          )
        )
      )
  ), classified AS (
    SELECT b.*,
      CASE
        WHEN b.has_open_canary THEN 're_review'
        WHEN b.revision_id IS NOT NULL THEN 'final'
        WHEN b.has_pending_reconciliation THEN 'owner_review'
        WHEN b.live_slot_count > 0 THEN 'awaiting'
        ELSE 'unlabeled'
      END AS public_state,
      CASE
        WHEN b.has_open_canary THEN 'blind_consensus'
        WHEN b.head_source_type IN ('blind_consensus','owner_adjudication') THEN 'blind_consensus'
        WHEN b.head_source_type = 'owner_single_adopt' THEN 'owner_single_adopt'
        WHEN b.head_source_type IN ('owner_direct_legacy','owner_override') THEN 'owner_legacy'
        WHEN b.live_slot_count > 0 THEN 'blind_consensus'
        ELSE 'none'
      END AS public_source
    FROM base b
  )
  SELECT c.id, c.camera_id, c.camera_name, c.started_at, c.duration_sec,
         c.public_state, c.public_source,
         CASE WHEN c.public_state = 'final' THEN c.head_decision ELSE NULL END,
         CASE WHEN c.public_state = 'final' THEN c.head_gt ELSE NULL END,
         CASE WHEN c.public_state = 'final' THEN c.revision_id ELSE NULL END,
         CASE WHEN c.public_state = 'final' THEN c.head_source_type ELSE NULL END,
         CASE WHEN c.public_state = 'final' THEN c.head_updated_at ELSE NULL END
  FROM classified c
  WHERE (p_label_state IS NULL OR c.public_state = p_label_state)
    AND (p_label_source IS NULL OR c.public_source = p_label_source)
    AND (
      p_final_decision IS NULL
      OR (c.public_state = 'final' AND c.head_decision = p_final_decision)
    )
    AND (p_cursor_started_at IS NULL OR c.started_at < p_cursor_started_at
      OR (c.started_at = p_cursor_started_at AND c.id < p_cursor_id))
  ORDER BY c.started_at DESC, c.id DESC
  LIMIT LEAST(GREATEST(p_limit, 1), 101);
END;
$$;

CREATE OR REPLACE FUNCTION public.fn_get_labeling_data_dashboard_canonical(p_owner_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  WITH playable AS (
    SELECT m.id
    FROM public.motion_clips m
    WHERE m.r2_key IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM public.motion_clip_system_exclusions sx
        WHERE sx.clip_id = m.id AND sx.state IN ('quarantined','media_deleted')
      )
  ), canonical AS (
    SELECT p.id AS clip_id, r.id AS revision_id, r.final_decision, r.gt
    FROM playable p
    JOIN public.motion_clip_gt_heads h ON h.clip_id = p.id
    JOIN public.motion_clip_gt_revisions r
      ON r.id = h.revision_id AND r.clip_id = h.clip_id
    WHERE NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_review_slots cs
      JOIN public.motion_blind_review_cohorts co ON co.id = cs.cohort_id
      WHERE cs.clip_id = p.id AND cs.cohort_kind = 'canary'
        AND co.status = 'open'
    )
  ), behavior AS (
    SELECT c.gt ->> 'primary_action' AS primary_action, count(*) AS clip_count
    FROM canonical c
    WHERE c.final_decision = 'label'
      AND c.gt IS NOT NULL
      AND jsonb_typeof(c.gt) = 'object'
      AND COALESCE(c.gt ->> 'primary_action', '') <> ''
    GROUP BY c.gt ->> 'primary_action'
  )
  SELECT jsonb_build_object(
    'video_record_count', (SELECT count(*) FROM public.motion_clips),
    'playable_video_count', (SELECT count(*) FROM playable),
    'gt_labeled_video_count', (SELECT COALESCE(sum(clip_count), 0) FROM behavior),
    'behavior_counts', COALESCE(
      (SELECT jsonb_object_agg(primary_action, clip_count ORDER BY primary_action) FROM behavior),
      '{}'::jsonb
    ),
    'gt_revision_count', (SELECT count(*) FROM canonical),
    'gt_revision_digest', (
      SELECT encode(extensions.digest(convert_to(COALESCE(string_agg(
        clip_id::text || '|' || revision_id::text, E'\n' ORDER BY clip_id
      ), ''), 'UTF8'), 'sha256'), 'hex')
      FROM canonical
    ),
    'generated_at', now()
  );
$$;

CREATE OR REPLACE VIEW public.motion_clip_canonical_gt_export
WITH (security_invoker = true) AS
SELECT h.clip_id, r.id AS revision_id, r.final_decision, r.gt,
       r.source_type, r.source_version, h.updated_at
FROM public.motion_clip_gt_heads h
JOIN public.motion_clip_gt_revisions r
  ON r.id = h.revision_id AND r.clip_id = h.clip_id
JOIN public.motion_clips m ON m.id = h.clip_id AND m.r2_key IS NOT NULL
WHERE NOT EXISTS (
  SELECT 1 FROM public.motion_clip_system_exclusions sx
  WHERE sx.clip_id = h.clip_id AND sx.state IN ('quarantined','media_deleted')
)
AND NOT EXISTS (
  SELECT 1
  FROM public.motion_clip_review_slots cs
  JOIN public.motion_blind_review_cohorts co ON co.id = cs.cohort_id
  WHERE cs.clip_id = h.clip_id AND cs.cohort_kind = 'canary'
    AND co.status = 'open'
);

CREATE OR REPLACE FUNCTION public.fn_get_motion_clip_canonical_gt_export_snapshot()
RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
  WITH export_rows AS (
    SELECT e.clip_id, e.revision_id
    FROM public.motion_clip_canonical_gt_export e
  ), canonical_digest AS (
    SELECT count(*)::integer AS head_count,
           encode(extensions.digest(convert_to(COALESCE(string_agg(
             clip_id::text || '|' || revision_id::text, E'\n' ORDER BY clip_id
           ), ''), 'UTF8'), 'sha256'), 'hex') AS head_digest
    FROM export_rows
  ), source_audit AS (
    SELECT public.fn_audit_motion_clip_canonical_gt() AS value
  )
  SELECT jsonb_build_object(
    'head_count', d.head_count,
    'head_digest', d.head_digest,
    'source_mutation_digest', a.value->>'source_mutation_digest'
  )
  FROM canonical_digest d CROSS JOIN source_audit a;
$$;

REVOKE ALL ON TABLE public.motion_clip_canonical_gt_export
  FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.motion_clip_canonical_gt_export TO service_role;

REVOKE ALL ON FUNCTION public.fn_get_motion_clip_canonical_gt_export_snapshot()
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_motion_clip_canonical_gt_export_snapshot()
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_list_motion_labeling_library_canonical(
  uuid, uuid, text, uuid[], timestamptz, timestamptz,
  text, text, text, text, timestamptz, uuid, integer
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_labeling_library_canonical(
  uuid, uuid, text, uuid[], timestamptz, timestamptz,
  text, text, text, text, timestamptz, uuid, integer
) TO service_role;

REVOKE ALL ON FUNCTION public.fn_get_labeling_data_dashboard_canonical(uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_labeling_data_dashboard_canonical(uuid)
  TO service_role;

COMMIT;
