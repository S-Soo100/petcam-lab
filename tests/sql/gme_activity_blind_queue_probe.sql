-- GME 활동 컨텍스트 + blind queue 순위 disposable runtime probe.
-- 합성 UUID만 사용하고 모든 row를 마지막에 ROLLBACK한다.

\set ON_ERROR_STOP on
BEGIN;

DO $probe$
DECLARE
  v_owner uuid := gen_random_uuid();
  v_a uuid := gen_random_uuid();
  v_b uuid := gen_random_uuid();
  v_cam uuid := gen_random_uuid();
  v_group uuid;
  v_cohort uuid;
  v_day date := (now() AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date;
  v_detected_9 uuid := gen_random_uuid();
  v_detected_2 uuid := gen_random_uuid();
  v_not_detected uuid := gen_random_uuid();
  v_old_job uuid := gen_random_uuid();
  v_new_job uuid := gen_random_uuid();
  v_failed_job uuid := gen_random_uuid();
  v_two_job uuid := gen_random_uuid();
  v_absent_job uuid := gen_random_uuid();
  v_old_run uuid := gen_random_uuid();
  v_new_run uuid := gen_random_uuid();
  v_two_run uuid := gen_random_uuid();
  v_absent_run uuid := gen_random_uuid();
  v_current_run uuid;
  v_detected boolean;
  v_activity numeric;
  v_order uuid[];
  v_canary_order uuid[];
  v_page_1 uuid[];
  v_page_2 uuid[];
  v_pages uuid[];
  v_cursor_detected boolean;
  v_cursor_activity numeric;
  v_cursor_started_at timestamptz;
  v_cursor_id uuid;
  v_distinct integer;
BEGIN
  INSERT INTO auth.users (id) VALUES (v_owner), (v_a), (v_b);
  INSERT INTO public.labelers (user_id) VALUES (v_a), (v_b);
  INSERT INTO public.labeler_applications (user_id, status, display_name) VALUES
    (v_a, 'approved', 'A'),
    (v_b, 'approved', 'B');
  INSERT INTO public.cameras (id, name) VALUES (v_cam, 'gme-queue-probe');

  -- started_at은 GME 우선순위와 반대로 둬 rank가 실제로 시간순을 이기는지 확인한다.
  INSERT INTO public.motion_clips
    (id, camera_id, started_at, duration_sec, r2_key, clip_purpose)
  VALUES
    (v_detected_9, v_cam, public.fn_motion_activity_day_start(v_day) + interval '1 hour',
      60, 'probe/detected-9.mp4', 'production'),
    (v_detected_2, v_cam, public.fn_motion_activity_day_start(v_day) + interval '2 hours',
      60, 'probe/detected-2.mp4', 'production'),
    (v_not_detected, v_cam, public.fn_motion_activity_day_start(v_day) + interval '3 hours',
      60, 'probe/not-detected.mp4', 'production');

  v_group := public.fn_manage_motion_review_group(
    NULL, v_owner, 'gme-queue-group', ARRAY[v_a, v_b], ARRAY[v_cam]
  );

  -- detected-9에는 old/new 성공과 더 최신 실패 job을 함께 둔다. current 함수는 실패를 무시하고
  -- completed_at 기준 최신 성공(new run)만 골라야 한다.
  INSERT INTO public.gme_jobs (id, clip_id, status, completed_at) VALUES
    (v_old_job, v_detected_9, 'succeeded', now() - interval '3 minutes'),
    (v_new_job, v_detected_9, 'succeeded', now() - interval '2 minutes'),
    (v_failed_job, v_detected_9, 'failed_terminal', now() - interval '1 minute'),
    (v_two_job, v_detected_2, 'succeeded', now() - interval '2 minutes'),
    (v_absent_job, v_not_detected, 'succeeded', now() - interval '2 minutes');

  INSERT INTO public.gme_runs
    (id, clip_id, job_id, status, candidate_moving_sec_any_gecko,
     visible_sec, max_simultaneous_geckos, state_intervals)
  VALUES
    (v_old_run, v_detected_9, v_old_job, 'ok', 1, 10, 1, '[]'),
    (v_new_run, v_detected_9, v_new_job, 'ok', 9, 10, 1, '[]'),
    (v_two_run, v_detected_2, v_two_job, 'ok', 2, 10, 1, '[]'),
    (v_absent_run, v_not_detected, v_absent_job, 'ok', 0, 0, 0, '[]');

  UPDATE public.gme_jobs SET result_run_id = v_old_run WHERE id = v_old_job;
  UPDATE public.gme_jobs SET result_run_id = v_new_run WHERE id = v_new_job;
  UPDATE public.gme_jobs SET result_run_id = v_two_run WHERE id = v_two_job;
  UPDATE public.gme_jobs SET result_run_id = v_absent_run WHERE id = v_absent_job;

  SELECT run_id, detected, activity_sec
  INTO v_current_run, v_detected, v_activity
  FROM public.fn_current_gme_activity(v_detected_9);
  ASSERT v_current_run = v_new_run, 'latest successful GME run was not selected';
  ASSERT v_detected, 'visible gecko run must be detected';
  ASSERT v_activity = 9, 'latest successful activity must be 9 seconds';

  PERFORM public.fn_ensure_motion_review_slots(v_a, v_day);

  -- 함수가 실제 emit한 순서를 ordinality로 고정한다. 기대 rank 식으로 재정렬하면 함수 내부
  -- ORDER BY 회귀를 가려버리므로 probe에서는 절대 다시 정렬하지 않는다.
  SELECT array_agg(q.clip_id ORDER BY q.ordinality)
  INTO v_order
  FROM public.fn_list_motion_blind_queue(
    v_a, v_day, 'live', NULL, NULL, NULL, NULL, NULL, 100
  ) WITH ORDINALITY AS q;

  ASSERT v_order = ARRAY[v_detected_9, v_detected_2, v_not_detected],
    'live queue must keep all eligible clips and rank detected activity descending';
  ASSERT (SELECT count(*) FROM public.motion_clip_review_slots
          WHERE clip_id = v_detected_9) = 2,
    'detected eligible clip must have two reviewer slots';
  ASSERT (SELECT count(*) FROM public.motion_clip_review_slots
          WHERE clip_id = v_not_detected) = 2,
    'not-detected eligible clip must remain with two reviewer slots';
  ASSERT (SELECT run_id FROM public.fn_current_gme_activity(v_detected_9)) = v_new_run,
    'current GME context must keep the new successful run';

  WITH first_page AS MATERIALIZED (
    SELECT q.*
    FROM public.fn_list_motion_blind_queue(
      v_a, v_day, 'live', NULL, NULL, NULL, NULL, NULL, 2
    ) WITH ORDINALITY AS q
  )
  SELECT
    (SELECT array_agg(fp.clip_id ORDER BY fp.ordinality) FROM first_page AS fp),
    last_row.rank_detected,
    last_row.rank_activity_sec,
    last_row.started_at,
    last_row.clip_id
  INTO v_page_1, v_cursor_detected, v_cursor_activity, v_cursor_started_at, v_cursor_id
  FROM first_page AS last_row
  ORDER BY last_row.ordinality DESC
  LIMIT 1;

  SELECT array_agg(q.clip_id ORDER BY q.ordinality)
  INTO v_page_2
  FROM public.fn_list_motion_blind_queue(
    v_a, v_day, 'live', NULL,
    v_cursor_detected, v_cursor_activity, v_cursor_started_at, v_cursor_id, 2
  ) WITH ORDINALITY AS q;

  v_pages := v_page_1 || v_page_2;
  SELECT count(DISTINCT clip_id) INTO v_distinct FROM unnest(v_pages) AS clip_id;
  ASSERT v_pages = ARRAY[v_detected_9, v_detected_2, v_not_detected],
    'two keyset pages must preserve the complete order';
  ASSERT cardinality(v_pages) = v_distinct,
    'two keyset pages must contain no duplicates';

  -- canary는 GME rank를 false/0으로 고정하고 기존 started_at DESC 순서를 유지한다.
  v_cohort := public.fn_manage_motion_blind_canary(
    'create', v_owner, NULL, 'gme-queue-canary', v_group,
    ARRAY[v_detected_9, v_detected_2, v_not_detected], ARRAY[v_a, v_b]
  );
  SELECT array_agg(q.clip_id ORDER BY q.ordinality)
  INTO v_canary_order
  FROM public.fn_list_motion_blind_queue(
    v_a, NULL, 'canary', v_cohort, NULL, NULL, NULL, NULL, 100
  ) WITH ORDINALITY AS q
  WHERE q.rank_detected = false AND q.rank_activity_sec = 0;
  ASSERT v_canary_order = ARRAY[v_not_detected, v_detected_2, v_detected_9],
    'canary queue must keep frozen time order';

  RAISE NOTICE 'GME activity context assertions passed';
  RAISE NOTICE 'GME activity blind queue assertions passed';
END;
$probe$;

SELECT 'GME_ACTIVITY_CONTEXT_OK' AS marker;
SELECT 'GME_ACTIVITY_BLIND_QUEUE_OK' AS marker;
SELECT 'DB_RUNTIME_PROBE_OK' AS marker;

ROLLBACK;
