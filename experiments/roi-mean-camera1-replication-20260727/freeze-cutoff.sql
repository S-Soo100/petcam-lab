-- Camera 1 raw roi_mean future replication: cutoff/identity freeze.
-- SELECT-only. camera_id, user identity, clip identity, GT JSON 을 반환하지 않아.
-- timestamp 는 세션 TimeZone 과 무관하게 UTC "Z" 로 고정한다.
-- 선행 benchmark.sql 의 owner_identity 와 완료 Owner cohort 를 그대로 재구성한 뒤
-- camera_id 오름차순 dense_rank() = 1 을 target camera_1 로 잡는다.

WITH owner_identity AS (
  SELECT u.id
  FROM auth.users u
  JOIN public.user_profiles p ON p.id = u.id
  LEFT JOIN public.labelers l ON l.user_id = u.id
  WHERE p.display_name = '운영자'
    AND l.user_id IS NULL
    AND EXISTS (
      SELECT 1
      FROM public.motion_clip_labeling_sessions s
      WHERE s.reviewed_by = u.id
    )
    AND EXISTS (
      SELECT 1
      FROM public.motion_clip_labeling_triage_events e
      WHERE e.actor_id = u.id
        AND e.event_type = 'owner_started_labeling'
    )
),
cohort AS (
  SELECT
    s.*,
    mc.camera_id,
    mc.started_at,
    mc.duration_sec,
    mc.file_size
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  JOIN public.motion_clips mc ON mc.id = s.clip_id
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
camera_counts AS (
  SELECT camera_id, count(*) AS owner_eligible_count
  FROM cohort
  GROUP BY camera_id
),
ranked AS (
  SELECT
    camera_id,
    owner_eligible_count,
    dense_rank() OVER (ORDER BY camera_id) AS camera_rank
  FROM camera_counts
)
SELECT jsonb_build_object(
  'schema_version', 'roi-camera1-freeze-v1',
  'frozen_at_utc', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'future_cutoff_utc', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'target_camera_group', 'camera_1',
  'target_camera_count', count(*) FILTER (WHERE camera_rank = 1),
  'prior_target_owner_eligible_count',
    max(owner_eligible_count) FILTER (WHERE camera_rank = 1),
  'prior_owner_eligible_count', (SELECT count(*) FROM cohort)
) AS freeze_manifest
FROM ranked;
