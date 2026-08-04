\set ON_ERROR_STOP on

BEGIN;

INSERT INTO auth.users(id) VALUES
  ('10000000-0000-4000-8000-000000000001'),
  ('10000000-0000-4000-8000-000000000002');
INSERT INTO public.cameras(id, name) VALUES
  ('20000000-0000-4000-8000-000000000001', 'canonical-consumer-probe');
INSERT INTO public.motion_labeling_review_groups(id, name, active, created_by) VALUES
  ('30000000-0000-4000-8000-000000000001', 'canonical-consumer-probe', true,
   '10000000-0000-4000-8000-000000000001');
INSERT INTO public.motion_clips(id, camera_id, started_at, duration_sec, r2_key) VALUES
  ('40000000-0000-4000-8000-000000000001', '20000000-0000-4000-8000-000000000001', now() - interval '1 min', 60, 'probe/final.mp4'),
  ('40000000-0000-4000-8000-000000000002', '20000000-0000-4000-8000-000000000001', now() - interval '2 min', 60, 'probe/awaiting.mp4'),
  ('40000000-0000-4000-8000-000000000003', '20000000-0000-4000-8000-000000000001', now() - interval '3 min', 60, 'probe/canary.mp4');

INSERT INTO public.motion_blind_review_cohorts(
  id, kind, status, label, group_id, created_by
) VALUES (
  '50000000-0000-4000-8000-000000000001', 'canary', 'open', 'consumer-probe',
  '30000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000001'
);
INSERT INTO public.motion_clip_review_slots(
  id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id, activity_day_kst
) VALUES
  ('60000000-0000-4000-8000-000000000001', '40000000-0000-4000-8000-000000000002',
   '30000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000002',
   'live', NULL, current_date),
  ('60000000-0000-4000-8000-000000000002', '40000000-0000-4000-8000-000000000003',
   '30000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000002',
   'canary', '50000000-0000-4000-8000-000000000001', current_date);

INSERT INTO public.motion_clip_gt_revisions(
  id, clip_id, revision_no, final_decision, gt, source_type, source_table,
  source_id, source_version, source_event_key
) VALUES
  ('70000000-0000-4000-8000-000000000001', '40000000-0000-4000-8000-000000000001',
   1, 'label', '{"primary_action":"moving"}', 'blind_consensus', 'probe',
   '80000000-0000-4000-8000-000000000001', 'motion-blind-v1', 'probe:final'),
  ('70000000-0000-4000-8000-000000000003', '40000000-0000-4000-8000-000000000003',
   1, 'label', '{"primary_action":"drinking"}', 'blind_consensus', 'probe',
   '80000000-0000-4000-8000-000000000003', 'motion-blind-v1', 'probe:canary');
INSERT INTO public.motion_clip_gt_heads(clip_id, revision_id) VALUES
  ('40000000-0000-4000-8000-000000000001', '70000000-0000-4000-8000-000000000001'),
  ('40000000-0000-4000-8000-000000000003', '70000000-0000-4000-8000-000000000003');

DO $$
DECLARE
  v_final record;
  v_awaiting record;
  v_canary record;
  v_dashboard jsonb;
BEGIN
  SELECT * INTO v_final
  FROM public.fn_list_motion_labeling_library_canonical(
    '10000000-0000-4000-8000-000000000001',
    '40000000-0000-4000-8000-000000000001'
  );
  ASSERT v_final.label_state = 'final';
  ASSERT v_final.gt_revision_id = '70000000-0000-4000-8000-000000000001';
  ASSERT v_final.final_gt = '{"primary_action":"moving"}'::jsonb;

  SELECT * INTO v_awaiting
  FROM public.fn_list_motion_labeling_library_canonical(
    '10000000-0000-4000-8000-000000000001',
    '40000000-0000-4000-8000-000000000002'
  );
  ASSERT v_awaiting.label_state = 'awaiting';
  ASSERT v_awaiting.final_gt IS NULL AND v_awaiting.gt_revision_id IS NULL;

  SELECT * INTO v_canary
  FROM public.fn_list_motion_labeling_library_canonical(
    '10000000-0000-4000-8000-000000000001',
    '40000000-0000-4000-8000-000000000003'
  );
  ASSERT v_canary.label_state = 're_review';
  ASSERT v_canary.final_gt IS NULL AND v_canary.gt_revision_id IS NULL;

  v_dashboard := public.fn_get_labeling_data_dashboard_canonical(
    '10000000-0000-4000-8000-000000000001'
  );
  ASSERT (v_dashboard->>'gt_labeled_video_count')::integer = 1;
  ASSERT v_dashboard->'behavior_counts'->>'moving' = '1';
  ASSERT v_dashboard->'source_revision_ids'->>'40000000-0000-4000-8000-000000000001'
    = '70000000-0000-4000-8000-000000000001';
  ASSERT NOT (v_dashboard->'source_revision_ids' ? '40000000-0000-4000-8000-000000000003');

  ASSERT (SELECT revision_id FROM public.motion_clip_canonical_gt_export
          WHERE clip_id = '40000000-0000-4000-8000-000000000001')
    = v_final.gt_revision_id;
  ASSERT (SELECT gt FROM public.motion_clip_canonical_gt_export
          WHERE clip_id = '40000000-0000-4000-8000-000000000001')
    = v_final.final_gt;
  ASSERT NOT EXISTS (
    SELECT 1 FROM public.motion_clip_canonical_gt_export
    WHERE clip_id = '40000000-0000-4000-8000-000000000003'
  );
END;
$$;

DO $$
BEGIN
  ASSERT NOT has_function_privilege(
    'anon',
    'public.fn_list_motion_labeling_library_canonical(uuid,uuid,text,uuid[],timestamptz,timestamptz,text,text,text,text,timestamptz,uuid,integer)',
    'EXECUTE'
  );
  ASSERT NOT has_function_privilege(
    'authenticated', 'public.fn_get_labeling_data_dashboard_canonical(uuid)', 'EXECUTE'
  );
  ASSERT NOT has_table_privilege(
    'authenticated', 'public.motion_clip_canonical_gt_export', 'SELECT'
  );
END;
$$;

SELECT 'CANONICAL_GT_CONSUMERS_PROBE_OK';
ROLLBACK;
