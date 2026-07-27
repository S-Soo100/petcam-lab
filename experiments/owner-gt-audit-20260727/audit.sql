-- Owner GT audit 2026-07-27
-- 모든 statement는 production에서 그대로 실행 가능한 SELECT-only 재계산 계약이야.
-- 결과에는 clip UUID, 사용자 UUID, 메모 원문, R2 key, 이메일을 반환하지 않아.

-- 1. Owner identity와 eligibility 경계
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
eligible AS (
  SELECT s.*
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
all_owner AS (
  SELECT s.*
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
)
SELECT
  now() AS snapshot_at_utc,
  (SELECT count(*) FROM owner_identity) AS owner_identity_count,
  (SELECT count(*) FROM all_owner) AS owner_sessions_total,
  (SELECT count(*) FROM eligible) AS eligible_completed,
  (SELECT count(*) FROM all_owner WHERE stage = 'gt_locked') AS in_progress_gt_locked,
  (SELECT count(*) FROM all_owner WHERE stage = 'draft') AS draft,
  (SELECT count(DISTINCT clip_id) FROM eligible) AS eligible_distinct_clips,
  (SELECT count(*) FROM eligible WHERE initial_gt IS NULL) AS initial_gt_null,
  (SELECT count(*) FROM eligible WHERE current_gt IS NULL) AS current_gt_null,
  (SELECT count(*) FROM eligible WHERE completed_at IS NULL) AS completed_at_null,
  (SELECT count(*) FROM eligible WHERE initial_gt IS DISTINCT FROM current_gt) AS initial_current_changed,
  (
    SELECT count(*)
    FROM public.motion_clip_labeling_session_revisions r
    JOIN eligible e ON e.id = r.session_id
  ) AS revision_rows,
  (
    SELECT count(*)
    FROM eligible e
    JOIN public.motion_clip_labeling_triage t ON t.clip_id = e.clip_id
    WHERE t.owner_decision = 'label'
  ) AS triage_label,
  (
    SELECT count(*)
    FROM eligible e
    JOIN public.motion_clip_system_exclusions x ON x.clip_id = e.clip_id
    WHERE x.state IN ('quarantined', 'media_deleted')
  ) AS terminal_system_excluded,
  (
    SELECT count(DISTINCT e.clip_id)
    FROM eligible e
    JOIN public.motion_clip_blind_submissions b
      ON b.clip_id = e.clip_id AND b.cohort_kind = 'canary'
  ) AS canary_clips_on_eligible,
  (
    SELECT count(*)
    FROM public.motion_clip_blind_submissions b
    JOIN owner_identity o ON o.id = b.reviewer_id
  ) AS owner_blind_submissions;

-- 1a. 운영 상태는 서로 다른 원장으로 분리 집계해.
SELECT 'triage' AS ledger, coalesce(owner_decision, 'unreviewed') AS state, count(*) AS n
FROM public.motion_clip_labeling_triage
GROUP BY owner_decision
UNION ALL
SELECT 'system_exclusion', state, count(*)
FROM public.motion_clip_system_exclusions
GROUP BY state
UNION ALL
SELECT 'blind_submission', cohort_kind, count(*)
FROM public.motion_clip_blind_submissions
GROUP BY cohort_kind
UNION ALL
SELECT
  'blind_distinct_clip',
  cohort_kind,
  count(DISTINCT clip_id)
FROM public.motion_clip_blind_submissions
GROUP BY cohort_kind
ORDER BY ledger, state;

-- 2. 카메라·날짜·길이 분포
WITH owner_identity AS (
  SELECT u.id
  FROM auth.users u
  JOIN public.user_profiles p ON p.id = u.id
  LEFT JOIN public.labelers l ON l.user_id = u.id
  WHERE p.display_name = '운영자'
    AND l.user_id IS NULL
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_sessions s WHERE s.reviewed_by = u.id
    )
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_triage_events e
      WHERE e.actor_id = u.id AND e.event_type = 'owner_started_labeling'
    )
),
eligible AS (
  SELECT
    c.name AS camera_name,
    mc.started_at,
    mc.duration_sec::double precision AS duration_sec
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  JOIN public.motion_clips mc ON mc.id = s.clip_id
  JOIN public.cameras c ON c.id = mc.camera_id
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
distribution AS (
  SELECT 'camera' AS dimension, camera_name AS value, count(*) AS n
  FROM eligible
  GROUP BY camera_name
  UNION ALL
  SELECT
    'capture_date_kst',
    (started_at AT TIME ZONE 'Asia/Seoul')::date::text,
    count(*)
  FROM eligible
  GROUP BY (started_at AT TIME ZONE 'Asia/Seoul')::date
  UNION ALL
  SELECT
    'duration_bin',
    CASE
      WHEN duration_sec < 35 THEN '30-<35'
      WHEN duration_sec < 55 THEN '35-<55'
      WHEN duration_sec < 61 THEN '55-<61'
      ELSE '61+'
    END,
    count(*)
  FROM eligible
  GROUP BY 2
)
SELECT dimension, value, n
FROM distribution
ORDER BY dimension, value;

-- 2a. 길이와 촬영·완료 시각 범위
WITH owner_identity AS (
  SELECT u.id
  FROM auth.users u
  JOIN public.user_profiles p ON p.id = u.id
  LEFT JOIN public.labelers l ON l.user_id = u.id
  WHERE p.display_name = '운영자'
    AND l.user_id IS NULL
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_sessions s WHERE s.reviewed_by = u.id
    )
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_triage_events e
      WHERE e.actor_id = u.id AND e.event_type = 'owner_started_labeling'
    )
),
eligible AS (
  SELECT
    mc.started_at,
    s.completed_at,
    mc.duration_sec::double precision AS duration_sec
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  JOIN public.motion_clips mc ON mc.id = s.clip_id
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
)
SELECT
  min(started_at) AS captured_min_utc,
  max(started_at) AS captured_max_utc,
  min(completed_at) AS completed_min_utc,
  max(completed_at) AS completed_max_utc,
  min(duration_sec) AS duration_min,
  percentile_cont(0.25) WITHIN GROUP (ORDER BY duration_sec) AS duration_p25,
  percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_sec) AS duration_p50,
  avg(duration_sec) AS duration_mean,
  percentile_cont(0.75) WITHIN GROUP (ORDER BY duration_sec) AS duration_p75,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_sec) AS duration_p95,
  max(duration_sec) AS duration_max
FROM eligible;

-- 3. GT 필드 분포. 배열 축은 clip 비율 계산 시 분모를 eligible 172로 둬.
WITH owner_identity AS (
  SELECT u.id
  FROM auth.users u
  JOIN public.user_profiles p ON p.id = u.id
  LEFT JOIN public.labelers l ON l.user_id = u.id
  WHERE p.display_name = '운영자'
    AND l.user_id IS NULL
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_sessions s WHERE s.reviewed_by = u.id
    )
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_triage_events e
      WHERE e.actor_id = u.id AND e.event_type = 'owner_started_labeling'
    )
),
eligible AS (
  SELECT s.current_gt AS gt
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
distribution AS (
  SELECT 'primary_action' AS dimension, gt->>'primary_action' AS value, count(*) AS n
  FROM eligible GROUP BY 2
  UNION ALL
  SELECT 'visibility', gt->>'visibility', count(*) FROM eligible GROUP BY 2
  UNION ALL
  SELECT 'target', gt->>'target', count(*) FROM eligible GROUP BY 2
  UNION ALL
  SELECT 'human_confidence', gt->>'human_confidence', count(*) FROM eligible GROUP BY 2
  UNION ALL
  SELECT 'highlight', gt->>'highlight_recommendation', count(*) FROM eligible GROUP BY 2
  UNION ALL
  SELECT 'enrichment_object', gt->>'enrichment_object', count(*) FROM eligible GROUP BY 2
  UNION ALL
  SELECT 'activity_intensity', coalesce(gt->>'activity_intensity', 'null'), count(*)
  FROM eligible GROUP BY 2
  UNION ALL
  SELECT 'observed_action', x, count(*)
  FROM eligible
  CROSS JOIN LATERAL jsonb_array_elements_text(gt->'observed_actions') x
  GROUP BY x
  UNION ALL
  SELECT 'context_tag', x, count(*)
  FROM eligible
  CROSS JOIN LATERAL jsonb_array_elements_text(gt->'context_tags') x
  GROUP BY x
  UNION ALL
  SELECT 'interaction_type', x, count(*)
  FROM eligible
  CROSS JOIN LATERAL jsonb_array_elements_text(gt->'interaction_types') x
  GROUP BY x
)
SELECT dimension, value, n
FROM distribution
ORDER BY dimension, n DESC, value;

-- 3a. 필수 key, scalar/array enum, segment shape, note type의 구조 감사
WITH owner_identity AS (
  SELECT u.id
  FROM auth.users u
  JOIN public.user_profiles p ON p.id = u.id
  LEFT JOIN public.labelers l ON l.user_id = u.id
  WHERE p.display_name = '운영자'
    AND l.user_id IS NULL
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_sessions s WHERE s.reviewed_by = u.id
    )
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_triage_events e
      WHERE e.actor_id = u.id AND e.event_type = 'owner_started_labeling'
    )
),
eligible AS (
  SELECT s.current_gt AS gt
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
allowed_keys(key) AS (
  VALUES
    ('visibility'),
    ('primary_action'),
    ('observed_actions'),
    ('segments'),
    ('target'),
    ('human_confidence'),
    ('context_tags'),
    ('activity_intensity'),
    ('highlight_recommendation'),
    ('enrichment_object'),
    ('interaction_types'),
    ('note')
)
SELECT
  count(*) FILTER (
    WHERE NOT (
      gt ?& ARRAY[
        'visibility',
        'primary_action',
        'observed_actions',
        'segments',
        'target',
        'human_confidence',
        'context_tags',
        'activity_intensity',
        'highlight_recommendation',
        'enrichment_object',
        'interaction_types',
        'note'
      ]
    )
  ) AS missing_required_key,
  count(*) FILTER (
    WHERE EXISTS (
      SELECT 1
      FROM jsonb_object_keys(gt) present_key
      WHERE present_key NOT IN (SELECT key FROM allowed_keys)
    )
  ) AS unexpected_key,
  count(*) FILTER (
    WHERE gt->>'visibility' NOT IN ('visible', 'partial', 'absent', 'uncertain')
       OR gt->>'primary_action' NOT IN (
         'eating_paste',
         'drinking',
         'moving',
         'unknown',
         'eating_prey',
         'defecating',
         'shedding',
         'basking',
         'unseen',
         'hand_feeding'
       )
       OR gt->>'target' NOT IN (
         'water',
         'water_bowl',
         'food_bowl',
         'paste',
         'prey',
         'glass',
         'floor',
         'hand',
         'tool',
         'object',
         'none',
         'uncertain'
       )
       OR gt->>'human_confidence' NOT IN ('certain', 'likely', 'uncertain', 'unjudgeable')
       OR gt->>'highlight_recommendation' NOT IN ('exclude', 'uncertain', 'include')
       OR gt->>'enrichment_object' NOT IN ('wheel', 'toy', 'other', 'none', 'uncertain')
       OR (
         gt->'activity_intensity' <> 'null'::jsonb
         AND gt->>'activity_intensity' NOT IN ('low', 'medium', 'high')
       )
  ) AS invalid_scalar_enum,
  count(*) FILTER (
    WHERE jsonb_typeof(gt->'observed_actions') <> 'array'
       OR jsonb_typeof(gt->'segments') <> 'array'
       OR jsonb_typeof(gt->'context_tags') <> 'array'
       OR jsonb_typeof(gt->'interaction_types') <> 'array'
  ) AS invalid_array_type,
  count(*) FILTER (
    WHERE EXISTS (
      SELECT 1 FROM jsonb_array_elements_text(gt->'observed_actions') value
      WHERE value NOT IN (
        'moving',
        'static',
        'licking',
        'prey_capture',
        'defecating',
        'shed_removal',
        'wheel_interaction',
        'object_interaction'
      )
    )
    OR EXISTS (
      SELECT 1 FROM jsonb_array_elements_text(gt->'context_tags') value
      WHERE value NOT IN (
        'ir',
        'glare',
        'occlusion',
        'distant',
        'blur',
        'overexposure',
        'edge',
        'human',
        'shadow',
        'camera_motion',
        'empty_scene'
      )
    )
    OR EXISTS (
      SELECT 1 FROM jsonb_array_elements_text(gt->'interaction_types') value
      WHERE value NOT IN ('ride', 'push', 'rotate', 'chase', 'repeated_return', 'other')
    )
  ) AS invalid_array_enum,
  count(*) FILTER (
    WHERE EXISTS (
      SELECT 1
      FROM jsonb_array_elements(gt->'segments') segment
      WHERE jsonb_typeof(segment) <> 'object'
         OR segment->>'action' NOT IN (
           'moving',
           'static',
           'licking',
           'prey_capture',
           'defecating',
           'shed_removal',
           'wheel_interaction',
           'object_interaction'
         )
         OR jsonb_typeof(segment->'start_sec') <> 'number'
         OR jsonb_typeof(segment->'end_sec') <> 'number'
    )
  ) AS invalid_segment_shape,
  count(*) FILTER (
    WHERE jsonb_typeof(gt->'note') NOT IN ('string', 'null')
       OR length(coalesce(gt->>'note', '')) > 2000
  ) AS invalid_note
FROM eligible;

-- 4. 웹 validator와 같은 의미 규칙. 1ms 이하는 float4 왕복 오차로 분리해.
WITH owner_identity AS (
  SELECT u.id
  FROM auth.users u
  JOIN public.user_profiles p ON p.id = u.id
  LEFT JOIN public.labelers l ON l.user_id = u.id
  WHERE p.display_name = '운영자'
    AND l.user_id IS NULL
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_sessions s WHERE s.reviewed_by = u.id
    )
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_triage_events e
      WHERE e.actor_id = u.id AND e.event_type = 'owner_started_labeling'
    )
),
eligible AS (
  SELECT s.current_gt AS gt, mc.duration_sec::double precision AS duration_sec
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  JOIN public.motion_clips mc ON mc.id = s.clip_id
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
issue_counts AS (
  SELECT 'absent_requires_unseen' AS code, count(*) AS n
  FROM eligible WHERE gt->>'visibility' = 'absent' AND gt->>'primary_action' <> 'unseen'
  UNION ALL
  SELECT 'absent_no_observed', count(*)
  FROM eligible WHERE gt->>'visibility' = 'absent' AND jsonb_array_length(gt->'observed_actions') > 0
  UNION ALL
  SELECT 'absent_no_segments', count(*)
  FROM eligible WHERE gt->>'visibility' = 'absent' AND jsonb_array_length(gt->'segments') > 0
  UNION ALL
  SELECT 'absent_target_none', count(*)
  FROM eligible WHERE gt->>'visibility' = 'absent' AND gt->>'target' <> 'none'
  UNION ALL
  SELECT 'absent_enrichment_none', count(*)
  FROM eligible WHERE gt->>'visibility' = 'absent' AND gt->>'enrichment_object' <> 'none'
  UNION ALL
  SELECT 'absent_no_interaction', count(*)
  FROM eligible WHERE gt->>'visibility' = 'absent' AND jsonb_array_length(gt->'interaction_types') > 0
  UNION ALL
  SELECT 'absent_highlight_exclude', count(*)
  FROM eligible
  WHERE gt->>'visibility' = 'absent' AND gt->>'highlight_recommendation' <> 'exclude'
  UNION ALL
  SELECT 'unseen_requires_absent', count(*)
  FROM eligible WHERE gt->>'primary_action' = 'unseen' AND gt->>'visibility' <> 'absent'
  UNION ALL
  SELECT 'observed_required', count(*)
  FROM eligible
  WHERE gt->>'visibility' <> 'absent' AND jsonb_array_length(gt->'observed_actions') = 0
  UNION ALL
  SELECT 'segment_missing_or_duplicate', count(*)
  FROM eligible e
  WHERE EXISTS (
    SELECT 1
    FROM jsonb_array_elements_text(e.gt->'observed_actions') oa
    WHERE (
      SELECT count(*)
      FROM jsonb_array_elements(e.gt->'segments') seg
      WHERE seg->>'action' = oa
    ) <> 1
  )
  UNION ALL
  SELECT 'segment_orphan', count(*)
  FROM eligible e
  WHERE EXISTS (
    SELECT 1
    FROM jsonb_array_elements(e.gt->'segments') seg
    WHERE NOT (e.gt->'observed_actions' ? (seg->>'action'))
  )
  UNION ALL
  SELECT 'segment_range_over_1ms', count(*)
  FROM eligible e
  WHERE EXISTS (
    SELECT 1
    FROM jsonb_array_elements(e.gt->'segments') seg
    WHERE (seg->>'start_sec')::double precision < 0
       OR (seg->>'start_sec')::double precision >= (seg->>'end_sec')::double precision
       OR (seg->>'end_sec')::double precision > e.duration_sec + 0.001
  )
  UNION ALL
  SELECT 'interaction_enrichment_required', count(*)
  FROM eligible
  WHERE (gt->'observed_actions' ? 'wheel_interaction'
      OR gt->'observed_actions' ? 'object_interaction')
    AND gt->>'enrichment_object' = 'none'
  UNION ALL
  SELECT 'interaction_type_required', count(*)
  FROM eligible
  WHERE (gt->'observed_actions' ? 'wheel_interaction'
      OR gt->'observed_actions' ? 'object_interaction')
    AND jsonb_array_length(gt->'interaction_types') = 0
  UNION ALL
  SELECT 'drinking_target_invalid', count(*)
  FROM eligible
  WHERE gt->>'primary_action' = 'drinking'
    AND gt->>'target' NOT IN ('water', 'water_bowl', 'glass', 'floor', 'uncertain')
  UNION ALL
  SELECT 'hand_feeding_action', count(*)
  FROM eligible
  WHERE gt->>'primary_action' = 'hand_feeding'
    AND NOT (gt->'observed_actions' ? 'licking' OR gt->'observed_actions' ? 'prey_capture')
  UNION ALL
  SELECT 'hand_feeding_target', count(*)
  FROM eligible
  WHERE gt->>'primary_action' = 'hand_feeding' AND gt->>'target' NOT IN ('hand', 'tool')
  UNION ALL
  SELECT 'hand_feeding_context', count(*)
  FROM eligible
  WHERE gt->>'primary_action' = 'hand_feeding' AND NOT (gt->'context_tags' ? 'human')
)
SELECT code, n
FROM issue_counts
WHERE n > 0
ORDER BY code;

-- 5. 동일·근접 영상과 의미상 중복 후보
WITH owner_identity AS (
  SELECT u.id
  FROM auth.users u
  JOIN public.user_profiles p ON p.id = u.id
  LEFT JOIN public.labelers l ON l.user_id = u.id
  WHERE p.display_name = '운영자'
    AND l.user_id IS NULL
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_sessions s WHERE s.reviewed_by = u.id
    )
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_triage_events e
      WHERE e.actor_id = u.id AND e.event_type = 'owner_started_labeling'
    )
),
eligible AS (
  SELECT
    s.clip_id,
    s.current_gt - 'note' AS gt_without_note,
    mc.camera_id,
    mc.started_at,
    mc.duration_sec::double precision AS duration_sec,
    mc.file_size
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  JOIN public.motion_clips mc ON mc.id = s.clip_id
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
pairs AS (
  SELECT
    a.started_at,
    a.duration_sec,
    a.file_size,
    a.gt_without_note,
    b.started_at AS b_started_at,
    b.duration_sec AS b_duration_sec,
    b.file_size AS b_file_size,
    b.gt_without_note AS b_gt_without_note,
    abs(extract(epoch FROM b.started_at - a.started_at)) AS delta_sec
  FROM eligible a
  JOIN eligible b ON a.camera_id = b.camera_id AND a.clip_id < b.clip_id
),
ordered AS (
  SELECT
    *,
    lag(started_at) OVER (PARTITION BY camera_id ORDER BY started_at, clip_id) AS previous_start
  FROM eligible
)
SELECT
  (SELECT count(*) FROM pairs WHERE started_at = b_started_at) AS exact_same_start_pairs,
  (
    SELECT count(*) FROM pairs
    WHERE started_at = b_started_at
      AND duration_sec = b_duration_sec
      AND file_size = b_file_size
  ) AS exact_metadata_duplicate_pairs,
  (SELECT count(*) FROM pairs WHERE delta_sec <= 60) AS near_60s_pairs,
  (SELECT count(*) FROM pairs WHERE delta_sec <= 300) AS near_5m_pairs,
  (SELECT count(*) FROM pairs WHERE delta_sec <= 600) AS near_10m_pairs,
  (
    SELECT count(*) FROM pairs
    WHERE delta_sec <= 300 AND gt_without_note = b_gt_without_note
  ) AS near_5m_identical_gt_pairs,
  (
    SELECT count(*) FROM ordered
    WHERE previous_start IS NULL OR started_at - previous_start > interval '5 minutes'
  ) AS episode_clusters_5m,
  (
    SELECT count(*) FROM ordered
    WHERE previous_start IS NULL OR started_at - previous_start > interval '10 minutes'
  ) AS episode_clusters_10m,
  (SELECT count(DISTINCT gt_without_note) FROM eligible) AS semantic_signature_count,
  (
    SELECT count(*)
    FROM (
      SELECT gt_without_note
      FROM eligible
      GROUP BY gt_without_note
      HAVING count(*) > 1
    ) repeated
  ) AS repeated_signature_groups;

-- 6. Python Evidence, Gate, VLM, selector coverage만 연결해. 결과를 서로 정답으로 쓰지 않아.
WITH owner_identity AS (
  SELECT u.id
  FROM auth.users u
  JOIN public.user_profiles p ON p.id = u.id
  LEFT JOIN public.labelers l ON l.user_id = u.id
  WHERE p.display_name = '운영자'
    AND l.user_id IS NULL
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_sessions s WHERE s.reviewed_by = u.id
    )
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_triage_events e
      WHERE e.actor_id = u.id AND e.event_type = 'owner_started_labeling'
    )
),
eligible AS (
  SELECT s.clip_id
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
python_runs AS (
  SELECT
    clip_id,
    count(*) AS run_rows,
    count(*) FILTER (WHERE level0_status <> 'ok') AS level0_not_ok,
    count(*) FILTER (WHERE level1_status <> 'ok') AS level1_not_ok,
    count(DISTINCT concat_ws(
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
    )) AS provenance_contracts,
    min(concat_ws(
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
    )) AS provenance_contract
  FROM public.clip_python_evidence_runs
  GROUP BY clip_id
),
gate_runs AS (
  SELECT
    clip_id,
    count(*) AS run_rows,
    count(DISTINCT concat_ws(
      '|',
      model_name,
      model_version,
      checkpoint_sha256,
      threshold,
      sampler_version,
      schema_version,
      frames_sampled
    )) AS provenance_contracts,
    min(concat_ws(
      '|',
      model_name,
      model_version,
      checkpoint_sha256,
      threshold,
      sampler_version,
      schema_version,
      frames_sampled
    )) AS provenance_contract
  FROM public.clip_prelabels
  GROUP BY clip_id
),
vlm_runs AS (
  SELECT
    clip_id,
    count(*) AS job_rows,
    count(*) FILTER (WHERE status = 'succeeded') AS succeeded_rows,
    count(*) FILTER (WHERE status = 'failed_terminal') AS failed_terminal_rows,
    count(*) FILTER (WHERE episode_key IS NULL) AS episode_key_null
  FROM public.clip_vlm_jobs
  GROUP BY clip_id
)
SELECT
  count(*) AS eligible,
  count(*) FILTER (WHERE p.clip_id IS NOT NULL) AS python_any,
  count(*) FILTER (WHERE p.run_rows = 1) AS python_exactly_one,
  count(*) FILTER (WHERE p.level0_not_ok = 0) AS python_all_level0_ok,
  count(*) FILTER (WHERE p.level1_not_ok = 0) AS python_all_level1_ok,
  count(DISTINCT p.provenance_contract) AS python_global_provenance_contracts,
  count(*) FILTER (WHERE p.provenance_contracts <> 1) AS python_multi_contract_clips,
  count(*) FILTER (WHERE g.clip_id IS NOT NULL) AS gate_any,
  count(*) FILTER (WHERE g.run_rows = 1) AS gate_exactly_one,
  count(DISTINCT g.provenance_contract) AS gate_global_provenance_contracts,
  count(*) FILTER (WHERE g.provenance_contracts <> 1) AS gate_multi_contract_clips,
  count(*) FILTER (WHERE v.clip_id IS NOT NULL) AS vlm_job_any,
  coalesce(sum(v.succeeded_rows), 0) AS vlm_succeeded_rows,
  coalesce(sum(v.failed_terminal_rows), 0) AS vlm_failed_terminal_rows,
  count(*) FILTER (WHERE v.episode_key_null = 0 AND v.clip_id IS NOT NULL)
    AS selector_selected_all_episode_keys,
  count(*) FILTER (
    WHERE p.level0_not_ok = 0
      AND p.level1_not_ok = 0
      AND g.clip_id IS NOT NULL
      AND v.succeeded_rows > 0
  ) AS all_three_success
FROM eligible e
LEFT JOIN python_runs p USING (clip_id)
LEFT JOIN gate_runs g USING (clip_id)
LEFT JOIN vlm_runs v USING (clip_id);

-- 6a. Gate visibility confusion, VLM exact match/lock timing, selector yield
WITH owner_identity AS (
  SELECT u.id
  FROM auth.users u
  JOIN public.user_profiles p ON p.id = u.id
  LEFT JOIN public.labelers l ON l.user_id = u.id
  WHERE p.display_name = '운영자'
    AND l.user_id IS NULL
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_sessions s WHERE s.reviewed_by = u.id
    )
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_triage_events e
      WHERE e.actor_id = u.id AND e.event_type = 'owner_started_labeling'
    )
),
eligible AS (
  SELECT s.clip_id, s.current_gt, s.prediction_snapshot, s.gt_locked_at
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
joined AS (
  SELECT
    e.*,
    p.gecko_visible,
    j.status AS vlm_status,
    j.completed_at AS vlm_completed_at,
    j.selector_version
  FROM eligible e
  LEFT JOIN public.clip_prelabels p ON p.clip_id = e.clip_id
  LEFT JOIN public.clip_vlm_jobs j ON j.clip_id = e.clip_id
)
SELECT
  count(*) FILTER (
    WHERE gecko_visible AND current_gt->>'visibility' <> 'absent'
  ) AS gate_tp,
  count(*) FILTER (
    WHERE gecko_visible AND current_gt->>'visibility' = 'absent'
  ) AS gate_fp,
  count(*) FILTER (
    WHERE NOT gecko_visible AND current_gt->>'visibility' <> 'absent'
  ) AS gate_fn,
  count(*) FILTER (
    WHERE NOT gecko_visible AND current_gt->>'visibility' = 'absent'
  ) AS gate_tn,
  count(*) FILTER (WHERE vlm_status = 'succeeded') AS vlm_success,
  count(*) FILTER (
    WHERE vlm_status = 'succeeded'
      AND prediction_snapshot->>'primary_action' = current_gt->>'primary_action'
  ) AS vlm_primary_exact,
  count(*) FILTER (
    WHERE vlm_status = 'succeeded' AND vlm_completed_at <= gt_locked_at
  ) AS vlm_completed_by_lock,
  count(*) FILTER (
    WHERE vlm_status = 'succeeded' AND vlm_completed_at > gt_locked_at
  ) AS vlm_completed_after_lock,
  count(*) FILTER (
    WHERE vlm_status IS NOT NULL
      AND current_gt->>'primary_action' IN ('drinking', 'eating_paste')
  ) AS selected_care,
  count(*) FILTER (
    WHERE vlm_status IS NOT NULL
      AND current_gt->>'highlight_recommendation' = 'include'
  ) AS selected_highlight_include,
  count(*) FILTER (
    WHERE vlm_status IS NOT NULL AND current_gt->>'visibility' = 'absent'
  ) AS selected_absent,
  count(DISTINCT selector_version) FILTER (WHERE vlm_status IS NOT NULL)
    AS selector_version_count
FROM joined;

-- 7. Owner eligible cohort 자체의 강한 ordered fingerprint
WITH owner_identity AS (
  SELECT u.id
  FROM auth.users u
  JOIN public.user_profiles p ON p.id = u.id
  LEFT JOIN public.labelers l ON l.user_id = u.id
  WHERE p.display_name = '운영자'
    AND l.user_id IS NULL
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_sessions s WHERE s.reviewed_by = u.id
    )
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_triage_events e
      WHERE e.actor_id = u.id AND e.event_type = 'owner_started_labeling'
    )
),
eligible AS (
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
row_hashes AS (
  SELECT
    clip_id,
    encode(digest(to_jsonb(e)::text, 'sha256'), 'hex') AS row_hash
  FROM eligible e
)
SELECT
  now() AS snapshot_at_utc,
  count(*) AS eligible_count,
  encode(
    digest(coalesce(string_agg(row_hash, '' ORDER BY clip_id), ''), 'sha256'),
    'hex'
  ) AS eligible_ordered_sha256
FROM row_hashes;

-- 7a. display_name을 쓰지 않는 독립 재계산: owner_started_labeling actor 경로
WITH audit_actor AS (
  SELECT DISTINCT e.actor_id AS id
  FROM public.motion_clip_labeling_triage_events e
  LEFT JOIN public.labelers l ON l.user_id = e.actor_id
  WHERE e.event_type = 'owner_started_labeling'
    AND l.user_id IS NULL
    AND EXISTS (
      SELECT 1
      FROM public.motion_clip_labeling_sessions s
      WHERE s.reviewed_by = e.actor_id
    )
),
eligible AS (
  SELECT
    s.*,
    mc.camera_id,
    mc.started_at,
    mc.duration_sec,
    mc.file_size
  FROM public.motion_clip_labeling_sessions s
  JOIN audit_actor a ON a.id = s.reviewed_by
  JOIN public.motion_clips mc ON mc.id = s.clip_id
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
row_hashes AS (
  SELECT
    clip_id,
    encode(digest(to_jsonb(e)::text, 'sha256'), 'hex') AS row_hash
  FROM eligible e
)
SELECT
  now() AS snapshot_at_utc,
  (SELECT count(*) FROM audit_actor) AS audit_actor_count,
  count(*) AS eligible_count,
  min(started_at) AS captured_min_utc,
  max(started_at) AS captured_max_utc,
  count(DISTINCT camera_id) AS camera_count,
  encode(
    digest(coalesce(string_agg(row_hash, '' ORDER BY clip_id), ''), 'sha256'),
    'hex'
  ) AS eligible_ordered_sha256
FROM row_hashes
JOIN eligible USING (clip_id);
