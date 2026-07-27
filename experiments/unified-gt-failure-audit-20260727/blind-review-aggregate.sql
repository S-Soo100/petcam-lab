-- Blind review 별칭 순서와 primary cause를 DB episode/camera-night에 다시 연결한다.
-- UUID, R2 key, signed URL은 반환하지 않는다.
WITH review_labels(review_index, primary_cause) AS (
  VALUES
    (1,'VISIBILITY_SCALE_OCCLUSION'),(2,'INPUT_QUALITY'),
    (3,'VISIBILITY_SCALE_OCCLUSION'),(4,'TEMPORAL_SAMPLING'),
    (5,'VISIBILITY_SCALE_OCCLUSION'),(6,'VISIBILITY_SCALE_OCCLUSION'),
    (7,'TEMPORAL_SAMPLING'),(8,'VISIBILITY_SCALE_OCCLUSION'),
    (9,'INPUT_QUALITY'),(10,'VISIBILITY_SCALE_OCCLUSION'),
    (11,'TEMPORAL_SAMPLING'),(12,'INPUT_QUALITY'),
    (13,'TEMPORAL_SAMPLING'),(14,'INPUT_QUALITY'),
    (15,'TEMPORAL_SAMPLING'),(16,'TEMPORAL_SAMPLING'),
    (17,'VISIBILITY_SCALE_OCCLUSION'),(18,'VISIBILITY_SCALE_OCCLUSION'),
    (19,'VISIBILITY_SCALE_OCCLUSION'),(20,'INPUT_QUALITY'),
    (21,'IR_LIGHT_REFLECTION'),(22,'VISIBILITY_SCALE_OCCLUSION'),
    (23,'INPUT_QUALITY'),(24,'INPUT_QUALITY'),
    (25,'VISIBILITY_SCALE_OCCLUSION'),(26,'TEMPORAL_SAMPLING'),
    (27,'VISIBILITY_SCALE_OCCLUSION'),(28,'TEMPORAL_SAMPLING'),
    (29,'TEMPORAL_SAMPLING'),(30,'INPUT_QUALITY'),
    (31,'VISIBILITY_SCALE_OCCLUSION'),(32,'TEMPORAL_SAMPLING'),
    (33,'VISIBILITY_SCALE_OCCLUSION'),(34,'VISIBILITY_SCALE_OCCLUSION'),
    (35,'VISIBILITY_SCALE_OCCLUSION'),(36,'VISIBILITY_SCALE_OCCLUSION'),
    (37,'VISIBILITY_SCALE_OCCLUSION'),(38,'VISIBILITY_SCALE_OCCLUSION'),
    (39,'TEMPORAL_SAMPLING'),(40,'VISIBILITY_SCALE_OCCLUSION'),
    (41,'VISIBILITY_SCALE_OCCLUSION'),(42,'TEMPORAL_SAMPLING'),
    (43,'TEMPORAL_SAMPLING'),(44,'TEMPORAL_SAMPLING')
),
labels AS (
  SELECT
    clip_id,
    count(DISTINCT action) AS distinct_actions,
    min(action) AS gt_action
  FROM public.behavior_labels
  GROUP BY clip_id
),
latest_vlm AS (
  SELECT DISTINCT ON (clip_id)
    clip_id,
    action AS vlm_action
  FROM public.behavior_logs
  WHERE source = 'vlm'
  ORDER BY clip_id, created_at DESC, id DESC
),
all_mismatches AS (
  SELECT
    l.clip_id,
    c.started_at,
    coalesce(c.camera_id::text, 'no-camera') AS camera_key,
    coalesce(c.r2_key, c.file_path) AS object_key,
    c.duration_sec,
    c.file_size,
    CASE
      WHEN l.gt_action IN ('moving', 'basking') AND v.vlm_action = 'shedding'
        THEN 'morph_shedding_overcall'
      WHEN l.gt_action = 'moving'
        AND v.vlm_action IN ('eating_paste', 'drinking')
        THEN 'motion_as_licking_care'
      WHEN l.gt_action = 'hand_feeding'
        AND v.vlm_action IN ('eating_paste', 'eating_prey')
        THEN 'feeding_context_lost'
      ELSE 'other'
    END AS failure_mode
  FROM labels l
  JOIN latest_vlm v USING (clip_id)
  JOIN public.camera_clips c ON c.id = l.clip_id
  WHERE l.distinct_actions = 1
    AND l.gt_action <> v.vlm_action
),
ordered AS (
  SELECT
    *,
    lag(started_at) OVER (
      PARTITION BY camera_key ORDER BY started_at, clip_id
    ) AS previous_start
  FROM all_mismatches
),
numbered AS (
  SELECT
    *,
    sum(
      CASE
        WHEN previous_start IS NULL
          OR started_at - previous_start > interval '5 minutes'
        THEN 1 ELSE 0
      END
    ) OVER (
      PARTITION BY camera_key ORDER BY started_at, clip_id
    ) AS episode_number
  FROM ordered
),
selected AS (
  SELECT
    *,
    row_number() OVER (ORDER BY md5(clip_id::text)) AS review_index
  FROM numbered
  WHERE failure_mode IN (
    'morph_shedding_overcall',
    'motion_as_licking_care'
  )
),
linked AS (
  SELECT
    s.*,
    r.primary_cause,
    concat_ws('|', camera_key, episode_number::text) AS episode_key,
    concat_ws(
      '|',
      camera_key,
      (started_at AT TIME ZONE 'Asia/Seoul')::date::text
    ) AS camera_night_key,
    concat_ws(
      '|',
      object_key,
      started_at::text,
      duration_sec::text,
      file_size::text
    ) AS capture_key
  FROM selected s
  JOIN review_labels r USING (review_index)
),
cause_summary AS (
  SELECT
    primary_cause,
    count(*) AS clips,
    count(DISTINCT episode_key) AS independent_episodes,
    count(DISTINCT camera_night_key) AS camera_nights,
    count(DISTINCT failure_mode) AS failure_modes
  FROM linked
  GROUP BY primary_cause
),
capture_summary AS (
  SELECT
    primary_cause,
    max(group_rows) AS largest_group
  FROM (
    SELECT primary_cause, capture_key, count(*) AS group_rows
    FROM linked
    GROUP BY primary_cause, capture_key
  ) capture_groups
  GROUP BY primary_cause
)
SELECT
  c.primary_cause,
  c.clips,
  c.independent_episodes,
  c.camera_nights,
  c.failure_modes,
  round(c.clips::numeric / 44, 4) AS selected_clip_share,
  round(p.largest_group::numeric / c.clips, 4) AS largest_duplicate_share,
  (
    c.independent_episodes >= 10
    AND c.camera_nights >= 2
    AND p.largest_group::numeric / c.clips <= 0.20
  ) AS qualified
FROM cause_summary c
JOIN capture_summary p USING (primary_cause)
ORDER BY c.independent_episodes DESC, c.primary_cause;
