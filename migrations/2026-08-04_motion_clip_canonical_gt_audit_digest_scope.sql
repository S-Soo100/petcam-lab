-- 진행 중 교차검수의 상태 변화와 확정 GT 원천의 불변성 감사를 분리한다.
BEGIN;

CREATE OR REPLACE FUNCTION public.fn_audit_motion_clip_canonical_gt()
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
  WITH source_counts AS (
    SELECT
      count(*) FILTER (
        WHERE c.cohort_kind = 'live'
          AND c.status IN ('agreed', 'owner_resolved')
      )::integer AS live_final,
      count(*) FILTER (
        WHERE c.cohort_kind = 'live' AND c.status = 'awaiting'
      )::integer AS live_awaiting,
      count(*) FILTER (
        WHERE c.cohort_kind = 'live' AND c.status = 'conflict'
      )::integer AS live_conflict,
      count(*) FILTER (WHERE c.cohort_kind = 'canary')::integer AS canary
    FROM public.motion_clip_consensus c
  ), session_counts AS (
    SELECT count(*) FILTER (
      WHERE s.stage = 'completed'
    )::integer AS completed
    FROM public.motion_clip_labeling_sessions s
  ), canonical_counts AS (
    SELECT
      (SELECT count(*)::integer FROM public.motion_clip_gt_revisions) AS revisions,
      (SELECT count(*)::integer FROM public.motion_clip_gt_heads) AS heads,
      (SELECT count(*)::integer FROM public.motion_clip_gt_reconciliation
       WHERE status = 'pending') AS reconciliation_pending
  ), overlap AS (
    SELECT count(*)::integer AS value
    FROM public.motion_clip_consensus c
    WHERE c.cohort_kind = 'live'
      AND c.status IN ('agreed', 'owner_resolved')
      AND EXISTS (
        SELECT 1 FROM public.motion_clip_labeling_sessions s
        WHERE s.clip_id = c.clip_id AND s.stage = 'completed'
          AND COALESCE(s.current_gt, s.initial_gt) IS NOT NULL
      )
  ), integrity AS (
    SELECT count(*)::integer AS orphan_heads
    FROM public.motion_clip_gt_heads h
    LEFT JOIN public.motion_clip_gt_revisions r
      ON r.id = h.revision_id AND r.clip_id = h.clip_id
    WHERE r.id IS NULL
  ), expected_sources AS (
    SELECT c.clip_id, c.final_decision AS decision,
           CASE WHEN c.final_decision = 'label' THEN c.final_gt ELSE NULL END AS gt,
           'motion_clip_consensus:' || c.id::text || ':' || COALESCE(c.comparator_version, 'unknown') AS source_event_key
    FROM public.motion_clip_consensus c
    WHERE c.cohort_kind = 'live'
      AND c.status IN ('agreed', 'owner_resolved')
      AND c.final_decision IN ('label', 'hold', 'exclude')
      AND (c.final_decision <> 'label' OR c.final_gt IS NOT NULL)
    UNION ALL
    SELECT s.clip_id, 'label', COALESCE(s.current_gt, s.initial_gt),
           'motion_clip_labeling_sessions:' || s.id::text || ':motion-labeling-v3'
    FROM public.motion_clip_labeling_sessions s
    WHERE s.stage = 'completed'
      AND COALESCE(s.current_gt, s.initial_gt) IS NOT NULL
  ), parity_mismatches AS (
    SELECT count(*)::integer AS value
    FROM expected_sources e
    WHERE NOT EXISTS (
      SELECT 1 FROM public.motion_clip_gt_reconciliation q
      WHERE q.clip_id = e.clip_id
    )
      AND (
        NOT EXISTS (
          SELECT 1
          FROM public.motion_clip_gt_revisions r
          WHERE r.source_event_key = e.source_event_key
            AND r.final_decision = e.decision
            AND r.gt IS NOT DISTINCT FROM e.gt
        )
        OR NOT EXISTS (
          SELECT 1
          FROM public.motion_clip_gt_heads h
          JOIN public.motion_clip_gt_revisions current_revision
            ON current_revision.id = h.revision_id
            AND current_revision.clip_id = h.clip_id
          WHERE h.clip_id = e.clip_id
        )
      )
  ), digests AS (
    SELECT encode(extensions.digest(convert_to(
      COALESCE((
        SELECT string_agg(
          concat_ws('|', c.id::text, c.clip_id::text, c.cohort_kind, c.status,
            COALESCE(c.comparator_version, ''), COALESCE(c.final_decision, ''),
            COALESCE(c.final_gt::text, '')),
          E'\n' ORDER BY c.id
        ) FROM public.motion_clip_consensus c
        WHERE c.cohort_kind = 'live'
          AND c.status IN ('agreed', 'owner_resolved')
          AND c.final_decision IN ('label', 'hold', 'exclude')
          AND (c.final_decision <> 'label' OR c.final_gt IS NOT NULL)
      ), '') || E'\n--sessions--\n' || COALESCE((
        SELECT string_agg(
          concat_ws('|', s.id::text, s.clip_id::text, s.reviewed_by::text, s.stage,
            COALESCE(s.initial_gt::text, ''), COALESCE(s.current_gt::text, '')),
          E'\n' ORDER BY s.id
        ) FROM public.motion_clip_labeling_sessions s
        WHERE s.stage = 'completed'
          AND COALESCE(s.current_gt, s.initial_gt) IS NOT NULL
      ), ''), 'UTF8'), 'sha256'), 'hex') AS source_digest,
      encode(extensions.digest(convert_to(
        COALESCE((
          SELECT string_agg(
            concat_ws('|', c.id::text, c.clip_id::text, c.cohort_kind, c.status,
              COALESCE(c.comparator_version, ''), COALESCE(c.final_decision, ''),
              COALESCE(c.final_gt::text, '')),
            E'\n' ORDER BY c.id
          ) FROM public.motion_clip_consensus c
        ), '') || E'\n--sessions--\n' || COALESCE((
          SELECT string_agg(
            concat_ws('|', s.id::text, s.clip_id::text, s.reviewed_by::text, s.stage,
              COALESCE(s.initial_gt::text, ''), COALESCE(s.current_gt::text, '')),
            E'\n' ORDER BY s.id
          ) FROM public.motion_clip_labeling_sessions s
        ), ''), 'UTF8'), 'sha256'), 'hex') AS workflow_digest
  )
  SELECT jsonb_build_object(
    'source_counts', jsonb_build_object(
      'live_final', sc.live_final,
      'direct_completed', ss.completed
    ),
    'canonical_counts', jsonb_build_object(
      'revisions', cc.revisions,
      'heads', cc.heads
    ),
    'excluded_counts', jsonb_build_object(
      'live_awaiting', sc.live_awaiting,
      'live_conflict', sc.live_conflict,
      'canary', sc.canary
    ),
    'overlap_count', o.value,
    'reconciliation_pending', cc.reconciliation_pending,
    'orphan_head_count', i.orphan_heads,
    'source_mutation_digest', d.source_digest,
    'workflow_observation_digest', d.workflow_digest,
    'parity_mismatch_count', p.value
  )
  FROM source_counts sc
  CROSS JOIN session_counts ss
  CROSS JOIN canonical_counts cc
  CROSS JOIN overlap o
  CROSS JOIN integrity i
  CROSS JOIN parity_mismatches p
  CROSS JOIN digests d;
$$;

REVOKE ALL ON FUNCTION public.fn_audit_motion_clip_canonical_gt()
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_audit_motion_clip_canonical_gt()
  TO service_role;

COMMIT;
