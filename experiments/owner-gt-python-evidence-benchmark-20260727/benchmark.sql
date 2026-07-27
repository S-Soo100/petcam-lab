-- Owner GT × Python Evidence descriptive benchmark.
-- 두 statement 모두 SELECT-only이며 UUID·메모·URL·R2 key·이메일을 반환하지 않아.

-- 1. 익명화된 benchmark snapshot
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
cohort_fingerprint AS (
  SELECT
    count(*) AS eligible_count,
    encode(
      digest(
        coalesce(string_agg(row_hash, '' ORDER BY clip_id), ''),
        'sha256'
      ),
      'hex'
    ) AS eligible_ordered_sha256
  FROM (
    SELECT
      clip_id,
      encode(digest(to_jsonb(c)::text, 'sha256'), 'hex') AS row_hash
    FROM cohort c
  ) hashed
),
eligible AS (
  SELECT
    c.clip_id,
    c.current_gt,
    c.camera_id,
    c.started_at,
    r.level0_status,
    r.level1_status,
    r.evidence_schema_version,
    r.algorithm_version,
    r.model_name,
    r.model_version,
    r.checkpoint_sha256,
    r.threshold,
    r.sampler_version,
    r.schema_version,
    r.frames_sampled,
    r.source_prelabel_identity,
    r.decoded_frame_count,
    r.motion_summary,
    r.spatial_dwell,
    r.periodicity_summary,
    jsonb_array_length(r.global_motion_series) AS global_series_length,
    jsonb_array_length(r.roi_motion_series) AS roi_series_length
  FROM cohort c
  JOIN public.clip_python_evidence_runs r ON r.clip_id = c.clip_id
),
ordered AS (
  SELECT
    *,
    lag(started_at) OVER (
      PARTITION BY camera_id
      ORDER BY started_at, clip_id
    ) AS previous_start
  FROM eligible
),
episode_numbered AS (
  SELECT
    *,
    sum(
      CASE
        WHEN previous_start IS NULL
          OR started_at - previous_start > interval '5 minutes'
        THEN 1
        ELSE 0
      END
    ) OVER (
      PARTITION BY camera_id
      ORDER BY started_at, clip_id
    ) AS episode_number
  FROM ordered
),
anonymous_rows AS (
  SELECT
    substr(encode(digest(clip_id::text, 'sha256'), 'hex'), 1, 16) AS sample_key,
    substr(
      encode(
        digest(camera_id::text || ':' || episode_number::text, 'sha256'),
        'hex'
      ),
      1,
      16
    ) AS episode_key,
    'camera_' || (dense_rank() OVER (ORDER BY camera_id))::text AS camera_group,
    'camera_' || (dense_rank() OVER (ORDER BY camera_id))::text
      || ':' || (started_at AT TIME ZONE 'Asia/Seoul')::date::text AS camera_night,
    CASE
      WHEN current_gt->'observed_actions' ? 'moving' THEN 'moving'
      WHEN current_gt->'observed_actions' ? 'static'
        AND NOT (current_gt->'observed_actions' ? 'moving') THEN 'static_only'
      ELSE 'excluded'
    END AS label,
    level0_status,
    level1_status,
    decoded_frame_count,
    global_series_length,
    roi_series_length,
    nullif(motion_summary->>'roi_mean', '')::double precision AS roi_mean,
    nullif(spatial_dwell->>'observed_sec', '')::double precision AS observed_sec,
    nullif(periodicity_summary->>'peak_autocorr', '')::double precision
      AS peak_autocorr,
    evidence_schema_version,
    algorithm_version,
    model_name,
    model_version,
    checkpoint_sha256,
    threshold,
    sampler_version,
    schema_version,
    frames_sampled,
    source_prelabel_identity
  FROM episode_numbered
)
SELECT jsonb_build_object(
  'contract',
  jsonb_build_object(
    'snapshot_at_utc', now(),
    'eligible_count', count(*),
    'eligible_ordered_sha256',
      (SELECT eligible_ordered_sha256 FROM cohort_fingerprint),
    'episode_count', count(DISTINCT episode_key),
    'moving_count', count(*) FILTER (WHERE label = 'moving'),
    'static_only_count', count(*) FILTER (WHERE label = 'static_only'),
    'excluded_count', count(*) FILTER (WHERE label = 'excluded'),
    'provenance_contract_count',
      count(
        DISTINCT concat_ws(
          '|',
          evidence_schema_version,
          algorithm_version,
          model_name,
          model_version,
          checkpoint_sha256,
          threshold,
          sampler_version,
          schema_version,
          frames_sampled
        )
      )
  ),
  'records',
  jsonb_agg(
    to_jsonb(anonymous_rows)
      - 'evidence_schema_version'
      - 'algorithm_version'
      - 'model_name'
      - 'model_version'
      - 'checkpoint_sha256'
      - 'threshold'
      - 'sampler_version'
      - 'schema_version'
      - 'frames_sampled'
      - 'source_prelabel_identity'
    ORDER BY sample_key
  )
) AS snapshot
FROM anonymous_rows;

-- 2. source table count와 canonical fingerprint
SELECT
  now() AS snapshot_at_utc,
  'motion_clips' AS table_name,
  count(*) AS row_count,
  md5(
    coalesce(
      string_agg(
        md5(to_jsonb(t)::text),
        ''
        ORDER BY md5(to_jsonb(t)::text)
      ),
      ''
    )
  ) AS ordered_fingerprint_md5
FROM public.motion_clips t
UNION ALL
SELECT
  now(),
  'motion_clip_labeling_triage',
  count(*),
  md5(
    coalesce(
      string_agg(
        md5(to_jsonb(t)::text),
        ''
        ORDER BY md5(to_jsonb(t)::text)
      ),
      ''
    )
  )
FROM public.motion_clip_labeling_triage t
UNION ALL
SELECT
  now(),
  'motion_clip_labeling_sessions',
  count(*),
  md5(
    coalesce(
      string_agg(
        md5(to_jsonb(t)::text),
        ''
        ORDER BY md5(to_jsonb(t)::text)
      ),
      ''
    )
  )
FROM public.motion_clip_labeling_sessions t
UNION ALL
SELECT
  now(),
  'motion_clip_labeling_session_revisions',
  count(*),
  md5(
    coalesce(
      string_agg(
        md5(to_jsonb(t)::text),
        ''
        ORDER BY md5(to_jsonb(t)::text)
      ),
      ''
    )
  )
FROM public.motion_clip_labeling_session_revisions t
UNION ALL
SELECT
  now(),
  'clip_python_evidence_runs',
  count(*),
  md5(
    coalesce(
      string_agg(
        md5(to_jsonb(t)::text),
        ''
        ORDER BY md5(to_jsonb(t)::text)
      ),
      ''
    )
  )
FROM public.clip_python_evidence_runs t
UNION ALL
SELECT
  now(),
  'clip_prelabels',
  count(*),
  md5(
    coalesce(
      string_agg(
        md5(to_jsonb(t)::text),
        ''
        ORDER BY md5(to_jsonb(t)::text)
      ),
      ''
    )
  )
FROM public.clip_prelabels t
ORDER BY table_name;
