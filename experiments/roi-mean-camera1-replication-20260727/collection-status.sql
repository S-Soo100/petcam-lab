-- Camera 1 raw roi_mean future replication: collection status + source fingerprint.
-- 두 statement 모두 SELECT-only. 결과 값(roi_mean/AUROC/CI/분포)을 반환하지 않고
-- class 별 clip·5분 episode·camera-night 수, Evidence coverage, provenance 계약 일치만 익명 집계한다.
-- roi_mean 은 finite 여부(boolean)로만 쓰고 값 자체를 select/aggregate 하지 않는다.
--
-- provenance 계약: future evidence-ready 는 단순 distinct count 가 아니라 이전 Owner GT 172
-- cohort 에서 재계산한 frozen provenance contract(정확히 1개 tuple 기대) 에 tuple 이 정확히
-- 포함될 때만 인정한다. tuple 문자열 자체는 절대 output 하지 않고 count 로만 노출한다.
--
-- :'future_cutoff_utc' 는 psql 스타일 리터럴 마커다. psql 변수 미지원 도구로 실행할 때는
-- freeze-manifest 의 정확한 UTC 문자열을 메모리에서 치환하고, 이 파일에는 치환본을 commit 하지 않는다.

-- 1. cutoff 이후 camera_1 익명 collection status
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
historical_cohort AS (
  SELECT
    s.clip_id,
    mc.camera_id
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  JOIN public.motion_clips mc ON mc.id = s.clip_id
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
frozen_provenance AS (
  -- 이전 172 cohort 의 canonical provenance tuple 집합 (benchmark 기준 정확히 1개).
  SELECT DISTINCT concat_ws(
    '|',
    r.evidence_schema_version,
    r.algorithm_version,
    r.model_name,
    r.model_version,
    r.checkpoint_sha256,
    r.threshold,
    r.sampler_version,
    r.schema_version,
    r.frames_sampled
  ) AS provenance_tuple
  FROM historical_cohort hc
  JOIN public.clip_python_evidence_runs r ON r.clip_id = hc.clip_id
),
target_camera AS (
  SELECT camera_id
  FROM (
    SELECT
      camera_id,
      dense_rank() OVER (ORDER BY camera_id) AS camera_rank
    FROM historical_cohort
    GROUP BY camera_id
  ) ranked
  WHERE camera_rank = 1
),
future_owner_completed AS (
  SELECT
    s.clip_id,
    s.initial_gt,
    mc.started_at,
    mc.camera_id
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  JOIN public.motion_clips mc ON mc.id = s.clip_id
  JOIN target_camera tc ON tc.camera_id = mc.camera_id
  WHERE mc.started_at > :'future_cutoff_utc'::timestamptz
    AND s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
future_with_evidence AS (
  SELECT
    f.clip_id,
    f.initial_gt,
    f.started_at,
    f.camera_id,
    e.provenance_tuple,
    (
      coalesce(e.run_count, 0) = 1
      AND coalesce(e.ok_finite_run_count, 0) = 1
    ) AS evidence_shape_ok,
    (
      e.provenance_tuple IS NOT NULL
      AND e.provenance_tuple IN (SELECT provenance_tuple FROM frozen_provenance)
    ) AS provenance_in_contract
  FROM future_owner_completed f
  LEFT JOIN (
    SELECT
      r.clip_id,
      count(*) AS run_count,
      count(*) FILTER (
        WHERE r.level0_status = 'ok'
          AND r.level1_status = 'ok'
          AND r.motion_summary->>'roi_mean' ~ '^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$'
      ) AS ok_finite_run_count,
      min(
        concat_ws(
          '|',
          r.evidence_schema_version,
          r.algorithm_version,
          r.model_name,
          r.model_version,
          r.checkpoint_sha256,
          r.threshold,
          r.sampler_version,
          r.schema_version,
          r.frames_sampled
        )
      ) AS provenance_tuple
    FROM public.clip_python_evidence_runs r
    GROUP BY r.clip_id
  ) e ON e.clip_id = f.clip_id
),
classified AS (
  -- evidence-ready = shape ok(정확히 1 run, level0/level1 ok, roi_mean finite)
  --   AND frozen provenance contract 정확히 포함.
  SELECT
    clip_id,
    started_at,
    camera_id,
    provenance_tuple,
    CASE
      WHEN initial_gt->'observed_actions' ? 'moving' THEN 'moving'
      WHEN initial_gt->'observed_actions' ? 'static'
       AND NOT (initial_gt->'observed_actions' ? 'moving') THEN 'static_only'
      ELSE 'excluded'
    END AS label
  FROM future_with_evidence
  WHERE evidence_shape_ok
    AND provenance_in_contract
),
episode_ordered AS (
  SELECT
    *,
    lag(started_at) OVER (
      PARTITION BY camera_id
      ORDER BY started_at, clip_id
    ) AS previous_start
  FROM classified
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
  FROM episode_ordered
),
aggregate_status AS (
  SELECT
    (SELECT count(*) FROM future_owner_completed) AS owner_completed_clips,
    (
      SELECT count(*)
      FROM future_with_evidence
      WHERE evidence_shape_ok
        AND NOT provenance_in_contract
    ) AS provenance_mismatch_clips,
    (SELECT count(*) FROM frozen_provenance) AS frozen_provenance_contract_count,
    count(*) AS evidence_ready_clips,
    count(*) FILTER (WHERE label = 'moving') AS moving_clips,
    count(*) FILTER (WHERE label = 'static_only') AS static_only_clips,
    count(*) FILTER (WHERE label = 'excluded') AS excluded_class_clips,
    count(DISTINCT episode_number) FILTER (WHERE label = 'moving') AS moving_episodes,
    count(DISTINCT episode_number) FILTER (WHERE label = 'static_only') AS static_only_episodes,
    count(DISTINCT (started_at AT TIME ZONE 'Asia/Seoul')::date)
      FILTER (WHERE label = 'moving') AS moving_nights,
    count(DISTINCT (started_at AT TIME ZONE 'Asia/Seoul')::date)
      FILTER (WHERE label = 'static_only') AS static_only_nights,
    count(DISTINCT (started_at AT TIME ZONE 'Asia/Seoul')::date)
      FILTER (WHERE label IN ('moving', 'static_only')) AS discrimination_nights,
    count(DISTINCT provenance_tuple) AS provenance_contract_count
  FROM episode_numbered
)
SELECT jsonb_build_object(
  'schema_version', 'roi-camera1-collection-v1',
  'snapshot_at_utc', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'future_cutoff_utc', :'future_cutoff_utc',
  'target_camera_group', 'camera_1',
  'prior_target_owner_eligible_count', (
    SELECT count(*)
    FROM historical_cohort hc
    JOIN target_camera tc ON tc.camera_id = hc.camera_id
  ),
  'future', jsonb_build_object(
    'owner_completed_clips', owner_completed_clips,
    'evidence_ready_clips', evidence_ready_clips,
    'provenance_mismatch_clips', provenance_mismatch_clips,
    'excluded_class_clips', excluded_class_clips,
    'camera_nights', discrimination_nights,
    'moving', jsonb_build_object(
      'clips', moving_clips,
      'episodes', moving_episodes,
      'camera_nights', moving_nights
    ),
    'static_only', jsonb_build_object(
      'clips', static_only_clips,
      'episodes', static_only_episodes,
      'camera_nights', static_only_nights
    )
  ),
  'coverage', jsonb_build_object(
    'evidence_ready_fraction',
      CASE
        WHEN owner_completed_clips > 0
          THEN round(evidence_ready_clips::numeric / owner_completed_clips, 6)
        ELSE NULL
      END,
    'provenance_contract_count', provenance_contract_count,
    'frozen_provenance_contract_count', frozen_provenance_contract_count,
    'future_provenance_contract_match', (provenance_mismatch_clips = 0)
  ),
  'minimum_met', (
    moving_clips >= 30
    AND static_only_clips >= 30
    AND moving_episodes >= 20
    AND static_only_episodes >= 20
    AND discrimination_nights >= 3
    AND moving_nights >= 2
    AND static_only_nights >= 2
  ),
  'verdict',
    CASE
      WHEN frozen_provenance_contract_count <> 1
        THEN 'ROI_REPLICATION_HOLD_PROVENANCE_CONTRACT_DRIFT'
      WHEN (
        moving_clips >= 30
        AND static_only_clips >= 30
        AND moving_episodes >= 20
        AND static_only_episodes >= 20
        AND discrimination_nights >= 3
        AND moving_nights >= 2
        AND static_only_nights >= 2
      )
      THEN 'ROI_REPLICATION_HOLD_UNEXPECTED_MINIMUM_AT_KICKOFF'
      ELSE 'ROI_CAMERA1_REPLICATION_COLLECTING'
    END
) AS collection_status
FROM aggregate_status;

-- 2. source table count 와 canonical fingerprint (benchmark.sql statement 2 동일)
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
