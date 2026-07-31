-- Live comparator v2 disposable PostgreSQL probe. Synthetic rows only; all rows roll back.

\set ON_ERROR_STOP on
BEGIN;

DO $probe$
DECLARE
  v_owner uuid := gen_random_uuid();
  v_a uuid := gen_random_uuid();
  v_b uuid := gen_random_uuid();
  v_camera uuid := gen_random_uuid();
  v_group uuid := gen_random_uuid();
  v_before uuid := gen_random_uuid();
  v_after uuid := gen_random_uuid();
  v_mixed uuid := gen_random_uuid();
  v_canary_clip uuid := gen_random_uuid();
  v_cohort uuid := gen_random_uuid();
  v_before_sub_a uuid := gen_random_uuid();
  v_before_sub_b uuid := gen_random_uuid();
  v_after_sub_a uuid := gen_random_uuid();
  v_after_sub_b uuid := gen_random_uuid();
  v_mixed_sub_a uuid := gen_random_uuid();
  v_mixed_sub_b uuid := gen_random_uuid();
  v_canary_sub_a uuid := gen_random_uuid();
  v_canary_sub_b uuid := gen_random_uuid();
  v_version text;
  v_count integer;
BEGIN
  INSERT INTO auth.users (id) VALUES (v_owner), (v_a), (v_b);
  INSERT INTO public.cameras (id, name) VALUES (v_camera, 'live-v2-probe');
  INSERT INTO public.motion_clips (id, camera_id, started_at, duration_sec, r2_key)
  VALUES
    (v_before, v_camera, '2026-07-31T00:00:00Z', 30, 'probe/before.mp4'),
    (v_after, v_camera, '2026-08-01T00:00:00Z', 30, 'probe/after.mp4'),
    (v_mixed, v_camera, '2026-08-01T01:00:00Z', 30, 'probe/mixed.mp4'),
    (v_canary_clip, v_camera, '2026-08-01T02:00:00Z', 30, 'probe/canary.mp4');
  INSERT INTO public.motion_labeling_review_groups (id, name, created_by)
  VALUES (v_group, 'live-v2-probe', v_owner);
  INSERT INTO public.motion_blind_review_cohorts
    (id, kind, status, label, group_id, created_by)
  VALUES (v_cohort, 'canary', 'open', 'live-v2-probe', v_group, v_owner);

  INSERT INTO public.motion_clip_consensus
    (clip_id, group_id, cohort_kind, cohort_id)
  VALUES
    (v_before, v_group, 'live', NULL),
    (v_after, v_group, 'live', NULL),
    (v_mixed, v_group, 'live', NULL),
    (v_canary_clip, v_group, 'canary', v_cohort);

  INSERT INTO public.motion_clip_review_slots
    (clip_id, group_id, reviewer_id, cohort_kind, cohort_id, activity_day_kst)
  VALUES
    (v_before, v_group, v_a, 'live', NULL, DATE '2026-07-31'),
    (v_before, v_group, v_b, 'live', NULL, DATE '2026-07-31'),
    (v_after, v_group, v_a, 'live', NULL, DATE '2026-08-01'),
    (v_after, v_group, v_b, 'live', NULL, DATE '2026-08-01'),
    (v_mixed, v_group, v_a, 'live', NULL, DATE '2026-08-01'),
    (v_mixed, v_group, v_b, 'live', NULL, DATE '2026-08-01'),
    (v_canary_clip, v_group, v_a, 'canary', v_cohort, DATE '2026-08-01'),
    (v_canary_clip, v_group, v_b, 'canary', v_cohort, DATE '2026-08-01');

  SELECT MIN(comparator_version) INTO v_version
  FROM public.motion_clip_review_slots WHERE clip_id = v_before;
  IF v_version <> 'motion-blind-v1' THEN
    RAISE EXCEPTION 'pre-activation slot is %', v_version USING ERRCODE = 'P0001';
  END IF;
  SELECT MIN(comparator_version) INTO v_version
  FROM public.motion_clip_review_slots WHERE clip_id = v_after;
  IF v_version <> 'motion-blind-live-v2-highlight-soft' THEN
    RAISE EXCEPTION 'post-activation slot is %', v_version USING ERRCODE = 'P0001';
  END IF;
  SELECT MIN(comparator_version) INTO v_version
  FROM public.motion_clip_review_slots WHERE clip_id = v_canary_clip;
  IF v_version <> 'motion-blind-v1' THEN
    RAISE EXCEPTION 'canary slot is %', v_version USING ERRCODE = 'P0001';
  END IF;

  BEGIN
    UPDATE public.motion_clip_review_slots
    SET comparator_version = 'motion-blind-v1'
    WHERE clip_id = v_after AND reviewer_id = v_a;
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: mutable slot version' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate '0A000' THEN NULL;
  END;

  INSERT INTO public.motion_clip_blind_submissions
    (id, slot_id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
     decision, reason_code, initial_gt, note, digest)
  SELECT v_before_sub_a, id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
         'exclude', 'gecko_absent', NULL, NULL, 'before-a'
  FROM public.motion_clip_review_slots WHERE clip_id = v_before AND reviewer_id = v_a;
  INSERT INTO public.motion_clip_blind_submissions
    (id, slot_id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
     decision, reason_code, initial_gt, note, digest)
  SELECT v_before_sub_b, id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
         'exclude', 'gecko_absent', NULL, NULL, 'before-b'
  FROM public.motion_clip_review_slots WHERE clip_id = v_before AND reviewer_id = v_b;
  INSERT INTO public.motion_clip_blind_submissions
    (id, slot_id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
     decision, reason_code, initial_gt, note, digest)
  SELECT v_after_sub_a, id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
         'exclude', 'gecko_absent', NULL, NULL, 'after-a'
  FROM public.motion_clip_review_slots WHERE clip_id = v_after AND reviewer_id = v_a;
  INSERT INTO public.motion_clip_blind_submissions
    (id, slot_id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
     decision, reason_code, initial_gt, note, digest)
  SELECT v_after_sub_b, id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
         'exclude', 'gecko_absent', NULL, NULL, 'after-b'
  FROM public.motion_clip_review_slots WHERE clip_id = v_after AND reviewer_id = v_b;
  INSERT INTO public.motion_clip_blind_submissions
    (id, slot_id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
     decision, reason_code, initial_gt, note, digest)
  SELECT v_mixed_sub_a, id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
         'exclude', 'gecko_absent', NULL, NULL, 'mixed-a'
  FROM public.motion_clip_review_slots WHERE clip_id = v_mixed AND reviewer_id = v_a;
  INSERT INTO public.motion_clip_blind_submissions
    (id, slot_id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
     decision, reason_code, initial_gt, note, digest)
  SELECT v_mixed_sub_b, id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
         'exclude', 'gecko_absent', NULL, NULL, 'mixed-b'
  FROM public.motion_clip_review_slots WHERE clip_id = v_mixed AND reviewer_id = v_b;
  INSERT INTO public.motion_clip_blind_submissions
    (id, slot_id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
     decision, reason_code, initial_gt, note, digest)
  SELECT v_canary_sub_a, id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
         'exclude', 'gecko_absent', NULL, NULL, 'canary-a'
  FROM public.motion_clip_review_slots WHERE clip_id = v_canary_clip AND reviewer_id = v_a;
  INSERT INTO public.motion_clip_blind_submissions
    (id, slot_id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
     decision, reason_code, initial_gt, note, digest)
  SELECT v_canary_sub_b, id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
         'exclude', 'gecko_absent', NULL, NULL, 'canary-b'
  FROM public.motion_clip_review_slots WHERE clip_id = v_canary_clip AND reviewer_id = v_b;

  BEGIN
    PERFORM public.fn_finalize_motion_blind_consensus(
      v_canary_clip, 'canary', v_cohort, v_canary_sub_a, v_canary_sub_b,
      'canary-a', 'canary-b', 'motion-blind-live-v2-highlight-soft',
      'agreed', 'exclude', NULL, '{}');
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: canary v2' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;

  BEGIN
    PERFORM public.fn_finalize_motion_blind_consensus(
      v_after, 'live', NULL, v_after_sub_a, v_after_sub_b,
      'after-a', 'after-b', 'motion-blind-v1',
      'agreed', 'exclude', NULL, '{}');
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: v2 slots with v1' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;

  BEGIN
    PERFORM public.fn_finalize_motion_blind_consensus(
      v_after, 'live', NULL, v_after_sub_a, v_after_sub_b,
      'after-a', 'after-b', 'unknown',
      'agreed', 'exclude', NULL, '{}');
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: unknown comparator' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;

  EXECUTE 'ALTER TABLE public.motion_clip_review_slots '
    'DISABLE TRIGGER trg_guard_motion_blind_slot_comparator_version_update';
  UPDATE public.motion_clip_review_slots
  SET comparator_version = 'motion-blind-v1'
  WHERE clip_id = v_mixed AND reviewer_id = v_a;
  EXECUTE 'ALTER TABLE public.motion_clip_review_slots '
    'ENABLE TRIGGER trg_guard_motion_blind_slot_comparator_version_update';
  BEGIN
    PERFORM public.fn_finalize_motion_blind_consensus(
      v_mixed, 'live', NULL, v_mixed_sub_a, v_mixed_sub_b,
      'mixed-a', 'mixed-b', 'motion-blind-live-v2-highlight-soft',
      'agreed', 'exclude', NULL, '{}');
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: mixed slot versions' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate 'PT425' THEN NULL;
  END;

  PERFORM public.fn_finalize_motion_blind_consensus(
    v_before, 'live', NULL, v_before_sub_a, v_before_sub_b,
    'before-a', 'before-b', 'motion-blind-v1',
    'agreed', 'exclude', NULL, '{}');
  PERFORM public.fn_finalize_motion_blind_consensus(
    v_after, 'live', NULL, v_after_sub_a, v_after_sub_b,
    'after-a', 'after-b', 'motion-blind-live-v2-highlight-soft',
    'agreed', 'exclude', NULL, '{}');

  SELECT COUNT(*) INTO v_count
  FROM public.motion_clip_consensus
  WHERE status = 'agreed'
    AND comparator_version IN (
      'motion-blind-v1',
      'motion-blind-live-v2-highlight-soft'
    );
  IF v_count <> 2 THEN
    RAISE EXCEPTION 'valid finalized consensus count is %', v_count USING ERRCODE = 'P0001';
  END IF;
END;
$probe$;

SELECT 'MOTION_BLIND_LIVE_V2_HIGHLIGHT_SOFT_PROBE_OK' AS marker;

ROLLBACK;
