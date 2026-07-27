-- Unified GT failure audit 2026-07-27.
-- 모든 statement는 SELECT-only이며 raw UUID/R2 key/email/note를 반환하지 않아.
-- :'audit_salt'는 실행 프로세스 메모리에서만 공급하고 저장하지 않아.

-- 1. 감사가 의존하는 실제 production column 계약.
SELECT
  table_name,
  column_name,
  data_type,
  is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN (
    'motion_clip_labeling_sessions',
    'motion_clip_labeling_session_revisions',
    'motion_clip_labeling_triage',
    'motion_clip_labeling_triage_events',
    'motion_clip_blind_submissions',
    'motion_clip_consensus',
    'clip_labeling_sessions',
    'clip_labeling_session_revisions',
    'behavior_labels',
    'behavior_logs',
    'clip_python_evidence_runs',
    'clip_prelabels',
    'clip_vlm_jobs'
  )
ORDER BY table_name, ordinal_position;

-- 2. Owner identity와 상태 분리.
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
  SELECT s.id, s.clip_id
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
)
SELECT
  now() AS snapshot_at_utc,
  (SELECT count(*) FROM owner_identity) AS owner_identity_count,
  (SELECT count(*) FROM eligible) AS owner_eligible_rows,
  (SELECT count(DISTINCT clip_id) FROM eligible) AS owner_eligible_unique_clips,
  (
    SELECT count(*)
    FROM public.motion_clip_labeling_sessions s
    JOIN owner_identity o ON o.id = s.reviewed_by
    WHERE s.stage = 'gt_locked'
  ) AS owner_in_progress,
  (
    SELECT count(*)
    FROM public.motion_clip_labeling_sessions s
    JOIN owner_identity o ON o.id = s.reviewed_by
    WHERE s.stage = 'draft'
  ) AS owner_draft,
  (
    SELECT count(*)
    FROM public.motion_clip_labeling_session_revisions r
    JOIN eligible e ON e.id = r.session_id
  ) AS owner_revision_rows,
  (
    SELECT count(DISTINCT b.clip_id)
    FROM public.motion_clip_blind_submissions b
    JOIN eligible e ON e.clip_id = b.clip_id
    WHERE b.cohort_kind = 'canary'
  ) AS owner_canary_overlap,
  (
    SELECT count(*)
    FROM public.motion_clip_blind_submissions b
    JOIN owner_identity o ON o.id = b.reviewer_id
  ) AS owner_blind_submissions;

-- 3. 서로 다른 운영 원장을 분리 집계.
SELECT 'motion_triage' AS source, coalesce(owner_decision, 'unreviewed') AS state, count(*) AS rows
FROM public.motion_clip_labeling_triage
GROUP BY owner_decision
UNION ALL
SELECT 'motion_blind', cohort_kind, count(*)
FROM public.motion_clip_blind_submissions
GROUP BY cohort_kind
UNION ALL
SELECT 'legacy_session', stage, count(*)
FROM public.clip_labeling_sessions
GROUP BY stage
UNION ALL
SELECT 'behavior_log', source, count(*)
FROM public.behavior_logs
GROUP BY source
ORDER BY source, state;

-- 4. legacy 사람 GT 후보. 자동 결과와 tutorial은 포함하지 않아.
WITH legacy_sessions AS (
  SELECT
    count(*) AS rows,
    count(DISTINCT clip_id) AS unique_clips,
    count(*) FILTER (WHERE initial_gt IS NOT NULL) AS initial_gt_rows,
    count(*) FILTER (WHERE current_gt IS NOT NULL) AS current_gt_rows,
    count(*) FILTER (WHERE prediction_snapshot IS NOT NULL) AS exposed_to_vlm_rows
  FROM public.clip_labeling_sessions
  WHERE stage = 'completed'
    AND initial_gt IS NOT NULL
    AND current_gt IS NOT NULL
    AND completed_at IS NOT NULL
),
legacy_labels AS (
  SELECT
    count(*) AS rows,
    count(DISTINCT clip_id) AS unique_clips,
    count(DISTINCT labeled_by) AS human_labelers
  FROM public.behavior_labels
),
legacy_human_logs AS (
  SELECT
    count(*) AS rows,
    count(DISTINCT clip_id) AS unique_clips
  FROM public.behavior_logs
  WHERE source = 'human'
)
SELECT
  (SELECT rows FROM legacy_sessions) AS completed_session_rows,
  (SELECT unique_clips FROM legacy_sessions) AS completed_session_unique_clips,
  (SELECT initial_gt_rows FROM legacy_sessions) AS initial_gt_rows,
  (SELECT current_gt_rows FROM legacy_sessions) AS current_gt_rows,
  (SELECT exposed_to_vlm_rows FROM legacy_sessions) AS exposed_to_vlm_rows,
  (SELECT rows FROM legacy_labels) AS behavior_label_rows,
  (SELECT unique_clips FROM legacy_labels) AS behavior_label_unique_clips,
  (SELECT human_labelers FROM legacy_labels) AS behavior_label_humans,
  (SELECT rows FROM legacy_human_logs) AS human_behavior_log_rows,
  (SELECT unique_clips FROM legacy_human_logs) AS human_behavior_log_unique_clips;

-- 5. Owner source의 기존 Evidence/Gate/VLM coverage. 자동 결과를 GT로 쓰지 않아.
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
    count(*) FILTER (WHERE level0_status = 'ok' AND level1_status = 'ok') AS ok_rows,
    count(DISTINCT concat_ws(
      '|', evidence_schema_version, algorithm_version, model_name, model_version,
      checkpoint_sha256, threshold, sampler_version, schema_version, frames_sampled
    )) AS provenance_contracts
  FROM public.clip_python_evidence_runs
  GROUP BY clip_id
),
gate_runs AS (
  SELECT
    clip_id,
    count(*) AS run_rows,
    count(DISTINCT concat_ws(
      '|', model_name, model_version, checkpoint_sha256, threshold,
      sampler_version, schema_version, frames_sampled
    )) AS provenance_contracts
  FROM public.clip_prelabels
  GROUP BY clip_id
),
vlm_runs AS (
  SELECT
    clip_id,
    count(*) AS job_rows,
    count(*) FILTER (WHERE status = 'succeeded') AS success_rows
  FROM public.clip_vlm_jobs
  GROUP BY clip_id
)
SELECT
  count(*) AS owner_eligible,
  count(*) FILTER (WHERE p.clip_id IS NOT NULL) AS python_covered,
  count(*) FILTER (WHERE p.run_rows = p.ok_rows) AS python_all_ok,
  count(*) FILTER (WHERE p.provenance_contracts = 1) AS python_one_contract,
  count(*) FILTER (WHERE g.clip_id IS NOT NULL) AS gate_covered,
  count(*) FILTER (WHERE g.provenance_contracts = 1) AS gate_one_contract,
  count(*) FILTER (WHERE v.clip_id IS NOT NULL) AS vlm_any,
  coalesce(sum(v.success_rows), 0) AS vlm_success_rows
FROM eligible e
LEFT JOIN python_runs p USING (clip_id)
LEFT JOIN gate_runs g USING (clip_id)
LEFT JOIN vlm_runs v USING (clip_id);

-- 6. 시작·종료에 같은 statement를 실행하는 관찰 범위 fingerprint.
WITH fingerprints AS (
  SELECT 'motion_clip_labeling_sessions' AS table_name, count(*) AS row_count,
    md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), ''))
      AS ordered_fingerprint_md5
  FROM public.motion_clip_labeling_sessions t
  UNION ALL
  SELECT 'motion_clip_labeling_triage', count(*),
    md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), ''))
  FROM public.motion_clip_labeling_triage t
  UNION ALL
  SELECT 'motion_clip_labeling_triage_events', count(*),
    md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), ''))
  FROM public.motion_clip_labeling_triage_events t
  UNION ALL
  SELECT 'motion_clip_blind_submissions', count(*),
    md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), ''))
  FROM public.motion_clip_blind_submissions t
  UNION ALL
  SELECT 'motion_clip_consensus', count(*),
    md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), ''))
  FROM public.motion_clip_consensus t
  UNION ALL
  SELECT 'clip_labeling_sessions', count(*),
    md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), ''))
  FROM public.clip_labeling_sessions t
  UNION ALL
  SELECT 'clip_labeling_session_revisions', count(*),
    md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), ''))
  FROM public.clip_labeling_session_revisions t
  UNION ALL
  SELECT 'behavior_labels', count(*),
    md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), ''))
  FROM public.behavior_labels t
  UNION ALL
  SELECT 'behavior_logs', count(*),
    md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), ''))
  FROM public.behavior_logs t
  UNION ALL
  SELECT 'clip_python_evidence_runs', count(*),
    md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), ''))
  FROM public.clip_python_evidence_runs t
  UNION ALL
  SELECT 'clip_prelabels', count(*),
    md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), ''))
  FROM public.clip_prelabels t
  UNION ALL
  SELECT 'clip_vlm_jobs', count(*),
    md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), ''))
  FROM public.clip_vlm_jobs t
)
SELECT now() AS snapshot_at_utc, table_name, row_count, ordered_fingerprint_md5
FROM fingerprints
ORDER BY table_name;

-- 7. Owner row-level hashed export. 출력은 반드시 ignored raw/에만 저장해.
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
)
SELECT
  'owner_motion' AS source,
  encode(digest(:'audit_salt' || s.clip_id::text, 'sha256'), 'hex') AS canonical_clip_key,
  encode(digest(:'audit_salt' || s.id::text, 'sha256'), 'hex') AS source_record_hash,
  encode(digest(:'audit_salt' || mc.camera_id::text, 'sha256'), 'hex') AS camera_hash,
  extract(epoch FROM mc.started_at)::bigint AS started_at_epoch,
  round(mc.duration_sec::numeric * 1000)::bigint AS duration_ms,
  s.initial_gt,
  s.current_gt,
  (s.initial_gt IS NOT NULL) AS immutable_initial_gt,
  true AS human,
  true AS blind,
  true AS provenance_complete,
  false AS automatic,
  false AS tutorial,
  jsonb_build_object(
    'level0_status', p.level0_status,
    'level1_status', p.level1_status,
    'roi_mean', nullif(p.motion_summary->>'roi_mean', '')::double precision,
    'observed_sec', nullif(p.spatial_dwell->>'observed_sec', '')::double precision,
    'peak_autocorr', nullif(p.periodicity_summary->>'peak_autocorr', '')::double precision
  ) AS python_evidence,
  jsonb_build_object('gecko_visible', g.gecko_visible) AS gate,
  s.prediction_snapshot AS vlm_prediction,
  v.status AS vlm_status,
  (p.clip_id IS NOT NULL) AS python_covered,
  (g.clip_id IS NOT NULL) AS gate_covered,
  (v.clip_id IS NOT NULL) AS vlm_covered
FROM public.motion_clip_labeling_sessions s
JOIN owner_identity o ON o.id = s.reviewed_by
JOIN public.motion_clips mc ON mc.id = s.clip_id
LEFT JOIN LATERAL (
  SELECT r.*
  FROM public.clip_python_evidence_runs r
  WHERE r.clip_id = s.clip_id
  ORDER BY r.created_at DESC, r.id DESC
  LIMIT 1
) p ON true
LEFT JOIN LATERAL (
  SELECT pre.*
  FROM public.clip_prelabels pre
  WHERE pre.clip_id = s.clip_id
  ORDER BY pre.created_at DESC, pre.id DESC
  LIMIT 1
) g ON true
LEFT JOIN LATERAL (
  SELECT j.*
  FROM public.clip_vlm_jobs j
  WHERE j.clip_id = s.clip_id
  ORDER BY j.created_at DESC, j.id DESC
  LIMIT 1
) v ON true
WHERE s.stage = 'completed'
  AND s.initial_gt IS NOT NULL
  AND s.current_gt IS NOT NULL
  AND s.completed_at IS NOT NULL
ORDER BY source_record_hash;

-- 8. Legacy session row-level hashed export. 출력은 반드시 ignored raw/에만 저장해.
SELECT
  'legacy_session' AS source,
  encode(digest(:'audit_salt' || s.clip_id::text, 'sha256'), 'hex') AS canonical_clip_key,
  encode(digest(:'audit_salt' || s.id::text, 'sha256'), 'hex') AS source_record_hash,
  encode(digest(:'audit_salt' || coalesce(c.camera_id::text, 'no-camera'), 'sha256'), 'hex')
    AS camera_hash,
  extract(epoch FROM c.started_at)::bigint AS started_at_epoch,
  round(c.duration_sec::numeric * 1000)::bigint AS duration_ms,
  s.initial_gt,
  s.current_gt,
  (s.initial_gt IS NOT NULL) AS immutable_initial_gt,
  true AS human,
  true AS blind,
  true AS provenance_complete,
  false AS automatic,
  false AS tutorial,
  (s.prediction_snapshot IS NOT NULL) AS historical_model_exposure,
  s.prediction_snapshot AS vlm_prediction,
  s.vlm_verdict,
  s.vlm_error_tags
FROM public.clip_labeling_sessions s
JOIN public.camera_clips c ON c.id = s.clip_id
WHERE s.stage = 'completed'
  AND s.initial_gt IS NOT NULL
  AND s.current_gt IS NOT NULL
  AND s.completed_at IS NOT NULL
ORDER BY source_record_hash;

-- 9. Legacy behavior label row-level hashed export. 출력은 반드시 ignored raw/에만 저장해.
SELECT
  'legacy_behavior_label' AS source,
  encode(digest(:'audit_salt' || bl.clip_id::text, 'sha256'), 'hex') AS canonical_clip_key,
  encode(digest(:'audit_salt' || bl.id::text, 'sha256'), 'hex') AS source_record_hash,
  encode(digest(:'audit_salt' || coalesce(c.camera_id::text, 'no-camera'), 'sha256'), 'hex')
    AS camera_hash,
  extract(epoch FROM c.started_at)::bigint AS started_at_epoch,
  round(c.duration_sec::numeric * 1000)::bigint AS duration_ms,
  jsonb_build_object(
    'primary_action', bl.action,
    'lick_target', bl.lick_target
  ) AS current_gt,
  false AS immutable_initial_gt,
  true AS human,
  false AS blind,
  true AS provenance_complete,
  false AS automatic,
  false AS tutorial,
  true AS historical_model_exposure
FROM public.behavior_labels bl
JOIN public.camera_clips c ON c.id = bl.clip_id
ORDER BY source_record_hash;

-- 10. Legacy human behavior log는 provenance가 약한 T3 후보로만 내보내.
SELECT
  'legacy_human_log' AS source,
  encode(digest(:'audit_salt' || b.clip_id::text, 'sha256'), 'hex') AS canonical_clip_key,
  encode(digest(:'audit_salt' || b.id::text, 'sha256'), 'hex') AS source_record_hash,
  encode(digest(:'audit_salt' || coalesce(c.camera_id::text, 'no-camera'), 'sha256'), 'hex')
    AS camera_hash,
  extract(epoch FROM c.started_at)::bigint AS started_at_epoch,
  round(c.duration_sec::numeric * 1000)::bigint AS duration_ms,
  jsonb_build_object('primary_action', b.action) AS current_gt,
  false AS immutable_initial_gt,
  true AS human,
  false AS blind,
  false AS provenance_complete,
  false AS automatic,
  false AS tutorial,
  true AS historical_model_exposure
FROM public.behavior_logs b
JOIN public.camera_clips c ON c.id = b.clip_id
WHERE b.source = 'human'
ORDER BY source_record_hash;

-- 11. 통합 source row → unique domain clip → 5분 episode 재계산.
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
owner_rows AS (
  SELECT
    'owner_motion'::text AS source,
    s.clip_id,
    mc.camera_id::text AS camera_key,
    mc.started_at,
    s.current_gt AS gt
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  JOIN public.motion_clips mc ON mc.id = s.clip_id
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
legacy_session_rows AS (
  SELECT
    'legacy_session'::text AS source,
    s.clip_id,
    coalesce(c.camera_id::text, 'no-camera') AS camera_key,
    c.started_at,
    s.current_gt AS gt
  FROM public.clip_labeling_sessions s
  JOIN public.camera_clips c ON c.id = s.clip_id
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
behavior_label_rows AS (
  SELECT
    'legacy_behavior_label'::text AS source,
    b.clip_id,
    coalesce(c.camera_id::text, 'no-camera') AS camera_key,
    c.started_at,
    jsonb_build_object('primary_action', b.action) AS gt
  FROM public.behavior_labels b
  JOIN public.camera_clips c ON c.id = b.clip_id
),
human_log_rows AS (
  SELECT
    'legacy_human_log'::text AS source,
    b.clip_id,
    coalesce(c.camera_id::text, 'no-camera') AS camera_key,
    c.started_at,
    jsonb_build_object('primary_action', b.action) AS gt
  FROM public.behavior_logs b
  JOIN public.camera_clips c ON c.id = b.clip_id
  WHERE b.source = 'human'
),
all_rows AS (
  SELECT * FROM owner_rows
  UNION ALL SELECT * FROM legacy_session_rows
  UNION ALL SELECT * FROM behavior_label_rows
  UNION ALL SELECT * FROM human_log_rows
),
unique_domain_clips AS (
  SELECT DISTINCT
    CASE
      WHEN source = 'owner_motion' THEN 'motion:' || clip_id::text
      ELSE 'legacy:' || clip_id::text
    END AS domain_clip_key,
    camera_key,
    started_at
  FROM all_rows
),
ordered AS (
  SELECT
    *,
    lag(started_at) OVER (
      PARTITION BY camera_key ORDER BY started_at, domain_clip_key
    ) AS previous_start
  FROM unique_domain_clips
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
      PARTITION BY camera_key ORDER BY started_at, domain_clip_key
    ) AS episode_number
  FROM ordered
)
SELECT jsonb_build_object(
  'catalog_rows', (SELECT count(*) FROM all_rows),
  'catalog_unique_domain_clips', (SELECT count(*) FROM unique_domain_clips),
  'catalog_independent_episodes', (
    SELECT count(DISTINCT concat_ws('|', camera_key, episode_number::text))
    FROM numbered
  ),
  'catalog_camera_nights', (
    SELECT count(DISTINCT concat_ws(
      '|', camera_key, (started_at AT TIME ZONE 'Asia/Seoul')::date::text
    ))
    FROM numbered
  ),
  'legacy_union_unique_clips', (
    SELECT count(DISTINCT clip_id)
    FROM (
      SELECT clip_id FROM legacy_session_rows
      UNION SELECT clip_id FROM behavior_label_rows
      UNION SELECT clip_id FROM human_log_rows
    ) legacy_union
  ),
  'behavior_label_human_log_overlap', (
    SELECT count(DISTINCT b.clip_id)
    FROM public.behavior_labels b
    JOIN public.behavior_logs l USING (clip_id)
    WHERE l.source = 'human'
  )
) AS catalog_summary;

-- 12. Legacy 사람 GT와 최신 기존 VLM의 retrospective exact/mismatch.
WITH labels AS (
  SELECT
    clip_id,
    count(*) AS label_rows,
    count(DISTINCT action) AS distinct_actions,
    array_agg(DISTINCT action ORDER BY action) AS actions
  FROM public.behavior_labels
  GROUP BY clip_id
),
latest_vlm AS (
  SELECT DISTINCT ON (clip_id)
    clip_id,
    action,
    vlm_model,
    created_at
  FROM public.behavior_logs
  WHERE source = 'vlm'
  ORDER BY clip_id, created_at DESC, id DESC
),
resolved AS (
  SELECT
    l.*,
    v.action AS vlm_action,
    (v.clip_id IS NOT NULL) AS vlm_present
  FROM labels l
  LEFT JOIN latest_vlm v USING (clip_id)
)
SELECT jsonb_build_object(
  'label_unique_clips', (SELECT count(*) FROM resolved),
  'multi_label_rows', (SELECT count(*) FROM resolved WHERE label_rows > 1),
  'human_action_conflict_clips', (
    SELECT count(*) FROM resolved WHERE distinct_actions > 1
  ),
  'vlm_covered', (SELECT count(*) FROM resolved WHERE vlm_present),
  'single_gt_vlm_covered', (
    SELECT count(*) FROM resolved WHERE vlm_present AND distinct_actions = 1
  ),
  'single_gt_vlm_exact', (
    SELECT count(*)
    FROM resolved
    WHERE vlm_present AND distinct_actions = 1 AND actions[1] = vlm_action
  ),
  'single_gt_vlm_mismatch', (
    SELECT count(*)
    FROM resolved
    WHERE vlm_present AND distinct_actions = 1 AND actions[1] <> vlm_action
  )
) AS legacy_vlm_comparison;

-- 13. 반복 VLM mismatch mode의 clip·episode·camera-night.
WITH labels AS (
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
mismatches AS (
  SELECT
    l.clip_id,
    l.gt_action,
    v.vlm_action,
    c.started_at,
    coalesce(c.camera_id::text, 'no-camera') AS camera_key,
    coalesce(c.r2_key, c.file_path) AS object_key,
    c.duration_sec,
    c.file_size,
    CASE
      WHEN l.gt_action IN ('moving', 'basking') AND v.vlm_action = 'shedding'
        THEN 'morph_shedding_overcall'
      WHEN l.gt_action = 'moving' AND v.vlm_action IN ('eating_paste', 'drinking')
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
  FROM mismatches
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
mode_summary AS (
  SELECT
    failure_mode,
    count(*) AS clips,
    count(DISTINCT concat_ws('|', camera_key, episode_number::text))
      AS independent_episodes,
    count(DISTINCT concat_ws(
      '|', camera_key, (started_at AT TIME ZONE 'Asia/Seoul')::date::text
    )) AS camera_nights
  FROM numbered
  GROUP BY failure_mode
),
capture_groups AS (
  SELECT
    failure_mode,
    object_key,
    started_at,
    duration_sec,
    file_size,
    count(*) AS group_rows
  FROM mismatches
  GROUP BY failure_mode, object_key, started_at, duration_sec, file_size
),
capture_summary AS (
  SELECT
    failure_mode,
    sum(group_rows) AS clips,
    count(*) AS distinct_capture_tuples,
    max(group_rows) AS largest_group
  FROM capture_groups
  GROUP BY failure_mode
)
SELECT
  m.failure_mode,
  m.clips,
  m.independent_episodes,
  m.camera_nights,
  c.distinct_capture_tuples,
  c.largest_group,
  round(c.largest_group::numeric / m.clips, 4) AS largest_capture_tuple_share
FROM mode_summary m
JOIN capture_summary c USING (failure_mode)
ORDER BY m.clips DESC, m.failure_mode;

-- 14. 사람이 확정한 legacy VLM error tag의 독립 episode support.
WITH completed AS (
  SELECT
    s.clip_id,
    s.reviewed_by,
    s.vlm_error_tags,
    c.started_at,
    coalesce(c.camera_id::text, 'no-camera') AS camera_key
  FROM public.clip_labeling_sessions s
  JOIN public.camera_clips c ON c.id = s.clip_id
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
ordered AS (
  SELECT
    *,
    lag(started_at) OVER (
      PARTITION BY camera_key ORDER BY started_at, clip_id
    ) AS previous_start
  FROM completed
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
expanded AS (
  SELECT
    unnest(vlm_error_tags) AS error_tag,
    clip_id,
    reviewed_by,
    camera_key,
    started_at,
    episode_number
  FROM numbered
)
SELECT
  error_tag,
  count(*) AS session_rows,
  count(DISTINCT clip_id) AS unique_clips,
  count(DISTINCT concat_ws('|', camera_key, episode_number::text))
    AS independent_episodes,
  count(DISTINCT concat_ws(
    '|', camera_key, (started_at AT TIME ZONE 'Asia/Seoul')::date::text
  )) AS camera_nights,
  count(DISTINCT reviewed_by) AS reviewers
FROM expanded
GROUP BY error_tag
ORDER BY independent_episodes DESC, error_tag;
