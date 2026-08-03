\set ON_ERROR_STOP on

INSERT INTO auth.users(id) VALUES
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'),
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');

INSERT INTO public.motion_clips(id) VALUES
  ('10000000-0000-4000-8000-000000000001'),
  ('10000000-0000-4000-8000-000000000002'),
  ('10000000-0000-4000-8000-000000000003'),
  ('10000000-0000-4000-8000-000000000004'),
  ('10000000-0000-4000-8000-000000000005'),
  ('10000000-0000-4000-8000-000000000006');

INSERT INTO public.motion_clip_consensus(
  id, clip_id, cohort_kind, status, comparator_version, final_decision, final_gt
) VALUES
  ('20000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000001',
   'live', 'agreed', 'motion-blind-v1', 'label', '{"primary_action":"moving"}'),
  ('20000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000002',
   'live', 'awaiting', NULL, NULL, NULL),
  ('20000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000003',
   'canary', 'agreed', 'motion-blind-v1', 'label', '{"primary_action":"eating"}'),
  ('20000000-0000-4000-8000-000000000005', '10000000-0000-4000-8000-000000000005',
   'live', 'owner_resolved', 'motion-blind-v1', 'label', '{"primary_action":"climbing"}'),
  ('20000000-0000-4000-8000-000000000006', '10000000-0000-4000-8000-000000000006',
   'live', 'agreed', 'motion-blind-v1', 'hold', NULL);

INSERT INTO public.motion_clip_labeling_sessions(
  id, clip_id, reviewed_by, stage, initial_gt, current_gt, completed_at
) VALUES
  ('30000000-0000-4000-8000-000000000004', '10000000-0000-4000-8000-000000000004',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'completed',
   '{"primary_action":"drinking"}', '{"primary_action":"drinking"}', now()),
  ('30000000-0000-4000-8000-000000000005', '10000000-0000-4000-8000-000000000005',
   'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'completed',
   '{"primary_action":"moving"}', '{"primary_action":"moving"}', now());

CREATE TEMP TABLE source_snapshot AS
SELECT
  (SELECT count(*) FROM public.motion_clip_consensus) AS consensus_count,
  (SELECT md5(string_agg(row_to_json(c)::text, '' ORDER BY c.id))
     FROM public.motion_clip_consensus c) AS consensus_digest,
  (SELECT count(*) FROM public.motion_clip_labeling_sessions) AS session_count,
  (SELECT md5(string_agg(row_to_json(s)::text, '' ORDER BY s.id))
     FROM public.motion_clip_labeling_sessions s) AS session_digest;

DO $$
DECLARE
  v_result jsonb;
BEGIN
  v_result := public.fn_project_motion_clip_canonical_gt(
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', false, 500, NULL,
    '40000000-0000-4000-8000-000000000001'
  );
  ASSERT (v_result->>'dry_run')::boolean;
  ASSERT (v_result->>'scanned')::integer = 5;
  ASSERT (v_result->>'inserted')::integer = 3;
  ASSERT (v_result->>'conflicts')::integer = 2;
  ASSERT (SELECT count(*) FROM public.motion_clip_gt_revisions) = 0;
  ASSERT (SELECT count(*) FROM public.motion_clip_gt_heads) = 0;
  ASSERT (SELECT count(*) FROM public.motion_clip_gt_reconciliation) = 0;
END;
$$;

CREATE FUNCTION public.fn_probe_fail_canonical_candidate()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.clip_id = '10000000-0000-4000-8000-000000000006'::uuid THEN
    RAISE EXCEPTION 'forced_candidate_failure' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER trg_probe_fail_canonical_candidate
  BEFORE INSERT ON public.motion_clip_gt_revisions
  FOR EACH ROW EXECUTE FUNCTION public.fn_probe_fail_canonical_candidate();

DO $$
BEGIN
  BEGIN
    PERFORM public.fn_project_motion_clip_canonical_gt(
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', true, 500, NULL,
      '40000000-0000-4000-8000-000000000099'
    );
    ASSERT false, 'forced batch failure must escape';
  EXCEPTION WHEN SQLSTATE '23514' THEN
    NULL;
  END;
  ASSERT (SELECT count(*) FROM public.motion_clip_gt_revisions) = 0;
  ASSERT (SELECT count(*) FROM public.motion_clip_gt_heads) = 0;
  ASSERT (SELECT count(*) FROM public.motion_clip_gt_reconciliation) = 0;
END;
$$;

DROP TRIGGER trg_probe_fail_canonical_candidate ON public.motion_clip_gt_revisions;
DROP FUNCTION public.fn_probe_fail_canonical_candidate();

DO $$
DECLARE
  v_result jsonb;
BEGIN
  v_result := public.fn_project_motion_clip_canonical_gt(
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', true, 500, NULL,
    '40000000-0000-4000-8000-000000000002'
  );
  ASSERT (v_result->>'scanned')::integer = 5;
  ASSERT (v_result->>'inserted')::integer = 3;
  ASSERT (v_result->>'conflicts')::integer = 1;
  ASSERT (v_result->>'already_present')::integer = 1;
END;
$$;

DO $$
DECLARE
  v_result jsonb;
BEGIN
  ASSERT (SELECT count(*) FROM public.motion_clip_gt_revisions) = 3;
  ASSERT (SELECT count(*) FROM public.motion_clip_gt_heads) = 3;
  ASSERT (SELECT count(*) FROM public.motion_clip_gt_reconciliation WHERE status='pending') = 1;
  ASSERT NOT EXISTS (
    SELECT 1 FROM public.motion_clip_gt_revisions
    WHERE clip_id IN (
      '10000000-0000-4000-8000-000000000002',
      '10000000-0000-4000-8000-000000000003',
      '10000000-0000-4000-8000-000000000005'
    )
  );
  ASSERT EXISTS (
    SELECT 1 FROM public.motion_clip_gt_revisions
    WHERE clip_id='10000000-0000-4000-8000-000000000006'
      AND final_decision='hold' AND gt IS NULL
  );

  v_result := public.fn_project_motion_clip_canonical_gt(
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', true, 500, NULL,
    '40000000-0000-4000-8000-000000000003'
  );
  ASSERT (v_result->>'scanned')::integer = 0;
  ASSERT (SELECT count(*) FROM public.motion_clip_gt_revisions) = 3;
END;
$$;

DO $$
DECLARE
  v_awaiting jsonb;
  v_conflict jsonb;
  v_final jsonb;
BEGIN
  v_awaiting := public.fn_get_motion_clip_canonical_gt(
    '10000000-0000-4000-8000-000000000002',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  );
  ASSERT v_awaiting->>'status' = 'review_in_progress';
  ASSERT v_awaiting->'gt' = 'null'::jsonb;
  ASSERT NOT (v_awaiting ? 'candidates');

  v_conflict := public.fn_get_motion_clip_canonical_gt(
    '10000000-0000-4000-8000-000000000005',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  );
  ASSERT v_conflict->>'status' = 'conflict';
  ASSERT jsonb_array_length(v_conflict->'candidates') = 2;
  ASSERT NOT ((v_conflict->'candidates'->0) ? 'reviewer_id');

  v_final := public.fn_get_motion_clip_canonical_gt(
    '10000000-0000-4000-8000-000000000001',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
  );
  ASSERT v_final->>'status' = 'final';
  ASSERT v_final->'gt'->>'primary_action' = 'moving';
END;
$$;

DO $$
DECLARE
  v_old_revision uuid;
  v_new_revision uuid;
BEGIN
  SELECT revision_id INTO v_old_revision FROM public.motion_clip_gt_heads
  WHERE clip_id='10000000-0000-4000-8000-000000000001';
  v_new_revision := (public.fn_override_motion_clip_canonical_gt(
    '10000000-0000-4000-8000-000000000001',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', v_old_revision,
    '{"primary_action":"eating"}', '영상 전체를 다시 확인해 행동을 정정함'
  )->>'revision_id')::uuid;
  ASSERT v_new_revision IS NOT NULL AND v_new_revision <> v_old_revision;
  ASSERT (SELECT count(*) FROM public.motion_clip_gt_revisions
          WHERE clip_id='10000000-0000-4000-8000-000000000001') = 2;
  ASSERT (SELECT revision_id FROM public.motion_clip_gt_heads
          WHERE clip_id='10000000-0000-4000-8000-000000000001') = v_new_revision;

  BEGIN
    PERFORM public.fn_override_motion_clip_canonical_gt(
      '10000000-0000-4000-8000-000000000001',
      'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', v_old_revision,
      '{"primary_action":"moving"}', '오래된 화면에서 다시 저장하려는 정정 시도'
    );
    ASSERT false, 'stale override must fail';
  EXCEPTION WHEN SQLSTATE 'PT409' THEN
    NULL;
  END;
END;
$$;

DO $$
DECLARE
  v_revision uuid;
BEGIN
  v_revision := (public.fn_resolve_motion_clip_gt_reconciliation(
    '10000000-0000-4000-8000-000000000005',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', NULL,
    'consensus', NULL, '두 원천을 다시 확인하고 consensus를 채택함'
  )->>'revision_id')::uuid;
  ASSERT v_revision IS NOT NULL;
  ASSERT (SELECT status FROM public.motion_clip_gt_reconciliation
          WHERE clip_id='10000000-0000-4000-8000-000000000005') = 'resolved';
  ASSERT (SELECT revision_id FROM public.motion_clip_gt_heads
          WHERE clip_id='10000000-0000-4000-8000-000000000005') = v_revision;
END;
$$;

DO $$
DECLARE
  v_before source_snapshot%ROWTYPE;
BEGIN
  SELECT * INTO v_before FROM source_snapshot;
  ASSERT (SELECT count(*) FROM public.motion_clip_consensus) = v_before.consensus_count;
  ASSERT (SELECT md5(string_agg(row_to_json(c)::text, '' ORDER BY c.id))
          FROM public.motion_clip_consensus c) = v_before.consensus_digest;
  ASSERT (SELECT count(*) FROM public.motion_clip_labeling_sessions) = v_before.session_count;
  ASSERT (SELECT md5(string_agg(row_to_json(s)::text, '' ORDER BY s.id))
          FROM public.motion_clip_labeling_sessions s) = v_before.session_digest;
END;
$$;

DO $$
DECLARE
  v_audit jsonb;
BEGIN
  v_audit := public.fn_audit_motion_clip_canonical_gt();
  ASSERT (v_audit->>'parity_mismatch_count')::integer = 0,
    'owner override와 reconciliation 뒤에도 source projection parity는 유지돼야 함';
  ASSERT length(v_audit->>'source_mutation_digest') = 64;
END;
$$;

BEGIN;
DELETE FROM public.motion_clip_gt_heads
WHERE clip_id='10000000-0000-4000-8000-000000000001';
DO $$
DECLARE
  v_audit jsonb;
BEGIN
  v_audit := public.fn_audit_motion_clip_canonical_gt();
  ASSERT (v_audit->>'parity_mismatch_count')::integer > 0,
    'eligible clip의 missing head를 audit가 탐지해야 함';
END;
$$;
ROLLBACK;

DO $$
BEGIN
  ASSERT NOT has_table_privilege('anon', 'public.motion_clip_gt_revisions', 'SELECT');
  ASSERT NOT has_table_privilege('authenticated', 'public.motion_clip_gt_heads', 'SELECT');
  ASSERT NOT has_function_privilege(
    'anon', 'public.fn_get_motion_clip_canonical_gt(uuid,uuid)', 'EXECUTE'
  );
  ASSERT NOT has_function_privilege(
    'authenticated',
    'public.fn_override_motion_clip_canonical_gt(uuid,uuid,uuid,jsonb,text)',
    'EXECUTE'
  );
END;
$$;

DO $$
BEGIN
  BEGIN
    UPDATE public.motion_clip_gt_revisions SET reason='forbidden';
    ASSERT false, 'revision update must fail';
  EXCEPTION WHEN SQLSTATE '0A000' THEN NULL;
  END;
  BEGIN
    TRUNCATE public.motion_clip_gt_projection_runs;
    ASSERT false, 'projection run truncate must fail';
  EXCEPTION WHEN SQLSTATE '0A000' THEN NULL;
  END;
END;
$$;

SELECT 'CANONICAL_GT_LEDGER_PROBE_OK';
