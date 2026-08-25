BEGIN;

INSERT INTO auth.users (id) VALUES
  ('10000000-0000-0000-0000-000000000001'),
  ('10000000-0000-0000-0000-000000000002'),
  ('10000000-0000-0000-0000-000000000003');
INSERT INTO public.cameras (id, name)
VALUES ('20000000-0000-0000-0000-000000000001', 'probe-camera');
INSERT INTO public.motion_clips (id, camera_id, started_at, duration_sec, r2_key, clip_purpose)
VALUES (
  '30000000-0000-0000-0000-000000000001',
  '20000000-0000-0000-0000-000000000001',
  now(), 60, 'local-probe/video.mp4', 'production'
);
INSERT INTO public.motion_labeling_review_groups (id, name, created_by)
VALUES (
  '40000000-0000-0000-0000-000000000001', 'probe-group',
  '10000000-0000-0000-0000-000000000003'
);
INSERT INTO public.motion_clip_review_slots (
  id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id, activity_day_kst
) VALUES (
  '50000000-0000-0000-0000-000000000001',
  '30000000-0000-0000-0000-000000000001',
  '40000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  'live', NULL, current_date
);
INSERT INTO public.motion_blind_review_cohorts (
  id, status, label, group_id, created_by, closed_at
) VALUES (
  '60000000-0000-0000-0000-000000000001', 'closed', 'probe-closed',
  '40000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000003', clock_timestamp()
);
INSERT INTO public.motion_clip_review_slots (
  id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id, activity_day_kst
) VALUES (
  '50000000-0000-0000-0000-000000000002',
  '30000000-0000-0000-0000-000000000001',
  '40000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000002',
  'canary', '60000000-0000-0000-0000-000000000001', current_date
);
INSERT INTO public.motion_blind_review_cohorts (
  id, status, label, group_id, created_by
) VALUES (
  '60000000-0000-0000-0000-000000000002', 'open', 'probe-open',
  '40000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000003'
);
INSERT INTO public.motion_clip_review_slots (
  id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id, activity_day_kst
) VALUES (
  '50000000-0000-0000-0000-000000000003',
  '30000000-0000-0000-0000-000000000001',
  '40000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  'canary', '60000000-0000-0000-0000-000000000002', current_date
);

INSERT INTO public.gme_jobs (id, clip_id, status, completed_at)
VALUES (
  '70000000-0000-0000-0000-000000000001',
  '30000000-0000-0000-0000-000000000001', 'succeeded', now()
);
INSERT INTO public.gme_runs (
  id, clip_id, job_id, status, candidate_moving_sec_any_gecko,
  visible_sec, max_simultaneous_geckos, state_intervals,
  detector_identity, duration_sec, permanent_artifact_key,
  permanent_artifact_sha256, permanent_artifact_bytes
) VALUES (
  '80000000-0000-0000-0000-000000000001',
  '30000000-0000-0000-0000-000000000001',
  '70000000-0000-0000-0000-000000000001', 'ok', 10, 20, 1, '[]',
  repeat('a', 64), 60, 'local-probe/artifact.json.gz', repeat('b', 64), 100
);
UPDATE public.gme_jobs
SET result_run_id = '80000000-0000-0000-0000-000000000001'
WHERE id = '70000000-0000-0000-0000-000000000001';

DO $$
DECLARE v_id uuid;
BEGIN
  SELECT event_id INTO v_id FROM public.fn_append_motion_clip_gme_miss(
    '90000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'live', NULL,
    '80000000-0000-0000-0000-000000000001', repeat('b', 64), 12.3454
  );
  IF v_id <> '90000000-0000-0000-0000-000000000001' THEN
    RAISE EXCEPTION 'MISS_APPEND_FAILED';
  END IF;
  RAISE NOTICE 'MISS_APPEND_OK';
END $$;

DO $$
DECLARE v_count integer;
BEGIN
  PERFORM public.fn_append_motion_clip_gme_miss(
    '90000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'live', NULL,
    '80000000-0000-0000-0000-000000000001', repeat('b', 64), 12.3454
  );
  SELECT count(*) INTO v_count FROM public.motion_clip_gme_miss_events;
  IF v_count <> 1 THEN RAISE EXCEPTION 'MISS_DUPLICATE_NOT_IDEMPOTENT'; END IF;
  RAISE NOTICE 'MISS_DUPLICATE_IDEMPOTENT_OK';
END $$;

DO $$
DECLARE v_count integer;
BEGIN
  PERFORM public.fn_append_motion_clip_gme_miss(
    '90000000-0000-0000-0000-000000000003',
    '30000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'live', NULL,
    '80000000-0000-0000-0000-000000000001', repeat('b', 64), 14.0004
  );
  SELECT count(*) INTO v_count FROM public.motion_clip_gme_miss_events;
  IF v_count <> 2 THEN RAISE EXCEPTION 'MISS_OTHER_TIMESTAMP_FAILED'; END IF;
  RAISE NOTICE 'MISS_OTHER_TIMESTAMP_OK';
END $$;

DO $$
DECLARE v_count integer;
BEGIN
  PERFORM public.fn_append_motion_clip_gme_miss(
    '90000000-0000-0000-0000-000000000004',
    '30000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'canary', '60000000-0000-0000-0000-000000000002',
    '80000000-0000-0000-0000-000000000001', repeat('b', 64), 12.3454
  );
  SELECT count(*) INTO v_count FROM public.motion_clip_gme_miss_events;
  IF v_count <> 3 THEN RAISE EXCEPTION 'MISS_SCOPE_NOT_DISTINCT'; END IF;
  RAISE NOTICE 'MISS_SCOPE_DISTINCT_OK';
END $$;

SET ROLE service_role;
DO $$
BEGIN
  PERFORM public.fn_append_motion_clip_gme_miss(
    '90000000-0000-0000-0000-000000000005',
    '30000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'live', NULL,
    '80000000-0000-0000-0000-000000000001', repeat('b', 64), 22
  );
  RAISE NOTICE 'MISS_SERVICE_RPC_OK';
END $$;
DO $$
BEGIN
  INSERT INTO public.motion_clip_gme_miss_events (
    id, clip_id, reviewer_id, cohort_kind, cohort_id, gme_run_id,
    detector_identity, permanent_artifact_sha256, timestamp_sec, digest
  ) VALUES (
    gen_random_uuid(),
    '30000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'live', NULL,
    '80000000-0000-0000-0000-000000000001',
    repeat('a', 64), repeat('b', 64), 23, repeat('c', 64)
  );
  RAISE EXCEPTION 'MISS_SERVICE_DIRECT_INSERT_ACCEPTED';
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'MISS_SERVICE_DIRECT_INSERT_BLOCKED';
END $$;
RESET ROLE;

DO $$
BEGIN
  PERFORM public.fn_append_motion_clip_gme_miss(
    gen_random_uuid(), '30000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000003', 'live', NULL,
    '80000000-0000-0000-0000-000000000001', repeat('b', 64), 16
  );
  RAISE EXCEPTION 'MISS_WRONG_REVIEWER_ACCEPTED';
EXCEPTION WHEN SQLSTATE 'PT403' THEN
  RAISE NOTICE 'MISS_WRONG_REVIEWER_REJECTED';
END $$;

DO $$
BEGIN
  PERFORM public.fn_append_motion_clip_gme_miss(
    gen_random_uuid(), '30000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001', 'live', NULL,
    '80000000-0000-0000-0000-000000000001', repeat('c', 64), 18
  );
  RAISE EXCEPTION 'MISS_STALE_OVERLAY_ACCEPTED';
EXCEPTION WHEN SQLSTATE 'PT409' THEN
  RAISE NOTICE 'MISS_STALE_OVERLAY_REJECTED';
END $$;

DO $$
BEGIN
  PERFORM public.fn_append_motion_clip_gme_miss(
    gen_random_uuid(), '30000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000002', 'canary',
    '60000000-0000-0000-0000-000000000001',
    '80000000-0000-0000-0000-000000000001', repeat('b', 64), 20
  );
  RAISE EXCEPTION 'MISS_CLOSED_CANARY_ACCEPTED';
EXCEPTION WHEN SQLSTATE 'PT427' THEN
  RAISE NOTICE 'MISS_CANARY_CLOSED_REJECTED';
END $$;

DO $$ BEGIN
  UPDATE public.motion_clip_gme_miss_events SET timestamp_sec = 1;
  RAISE EXCEPTION 'MISS_UPDATE_ACCEPTED';
EXCEPTION WHEN SQLSTATE '0A000' THEN RAISE NOTICE 'MISS_UPDATE_BLOCKED'; END $$;
DO $$ BEGIN
  DELETE FROM public.motion_clip_gme_miss_events;
  RAISE EXCEPTION 'MISS_DELETE_ACCEPTED';
EXCEPTION WHEN SQLSTATE '0A000' THEN RAISE NOTICE 'MISS_DELETE_BLOCKED'; END $$;
DO $$ BEGIN
  TRUNCATE public.motion_clip_gme_miss_events;
  RAISE EXCEPTION 'MISS_TRUNCATE_ACCEPTED';
EXCEPTION WHEN SQLSTATE '0A000' THEN RAISE NOTICE 'MISS_TRUNCATE_BLOCKED'; END $$;

SELECT 'GME_MISS_EVENTS_RUNTIME_PROBE_OK';
ROLLBACK;
