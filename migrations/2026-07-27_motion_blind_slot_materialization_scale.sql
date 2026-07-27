-- 이중 블라인드 live slot 운영 규모 자재화 — forward-only.
--
-- 기존 함수는 최근 30일 clip을 한 행씩 잠그고 consensus/slot을 생성했다. P4 Cam (dev)
-- 14,561건에서 PostgREST statement timeout(57014)을 재현했으므로, 동일한 ownership·
-- 2-reviewer·short-clip 격리 계약을 set-based INSERT로 바꾼다.

BEGIN;

CREATE OR REPLACE FUNCTION public.fn_ensure_motion_review_slots(
  p_reviewer_id uuid,
  p_activity_day date
) RETURNS integer
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_group_id uuid;
  v_members uuid[];
  v_from timestamptz;
  v_to timestamptz;
  v_materialized integer := 0;
BEGIN
  SELECT group_id INTO v_group_id
  FROM public.motion_labeling_review_group_members
  WHERE user_id = p_reviewer_id AND ended_at IS NULL;
  IF NOT FOUND THEN
    RETURN 0;
  END IF;

  -- 같은 그룹의 두 브라우저가 동시에 workspace를 열어도 bulk INSERT는 한 번씩만 수행한다.
  PERFORM pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(v_group_id::text, 0)
  );

  -- 그룹 변경 RPC의 membership UPDATE와 직렬화하고 두 reviewer snapshot을 고정한다.
  PERFORM 1
  FROM public.motion_labeling_review_group_members
  WHERE group_id = v_group_id AND ended_at IS NULL
  ORDER BY user_id
  FOR UPDATE;

  SELECT array_agg(user_id ORDER BY user_id)
  INTO v_members
  FROM public.motion_labeling_review_group_members
  WHERE group_id = v_group_id AND ended_at IS NULL;

  IF v_members IS NULL OR array_length(v_members, 1) <> 2 THEN
    RAISE EXCEPTION 'group_invariant: active group must have two members'
      USING ERRCODE = 'PT425';
  END IF;

  v_from := public.fn_motion_activity_day_start(p_activity_day - 29);
  v_to := public.fn_motion_activity_day_start(p_activity_day + 1);

  -- 최초 live consensus가 clip ownership을 고정한다. 이미 다른 그룹 소유면 그대로 보존한다.
  INSERT INTO public.motion_clip_consensus
    (clip_id, group_id, cohort_kind, cohort_id, status)
  SELECT m.id, v_group_id, 'live', NULL, 'awaiting'
  FROM public.motion_clips m
  JOIN public.motion_labeling_review_group_cameras gc
    ON gc.camera_id = m.camera_id
   AND gc.group_id = v_group_id
   AND gc.ended_at IS NULL
  WHERE m.started_at >= v_from
    AND m.started_at < v_to
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_system_exclusions sx
      WHERE sx.clip_id = m.id
        AND sx.state IN ('quarantined','media_deleted')
    )
  ON CONFLICT (clip_id) WHERE cohort_kind = 'live' DO NOTHING;

  -- 기존 데이터가 1개/3개 slot처럼 불완전하면 자동 보정하지 않고 fail-closed한다.
  IF EXISTS (
    SELECT s.clip_id
    FROM public.motion_clip_review_slots s
    JOIN public.motion_clip_consensus c
      ON c.clip_id = s.clip_id
     AND c.cohort_kind = 'live'
     AND c.group_id = v_group_id
    JOIN public.motion_clips m ON m.id = s.clip_id
    JOIN public.motion_labeling_review_group_cameras gc
      ON gc.camera_id = m.camera_id
     AND gc.group_id = v_group_id
     AND gc.ended_at IS NULL
    WHERE s.cohort_kind = 'live'
      AND m.started_at >= v_from
      AND m.started_at < v_to
      AND NOT EXISTS (
        SELECT 1
        FROM public.motion_clip_system_exclusions sx
        WHERE sx.clip_id = m.id
          AND sx.state IN ('quarantined','media_deleted')
      )
    GROUP BY s.clip_id
    HAVING count(*) <> 2
  ) THEN
    RAISE EXCEPTION 'live clip must have zero or two slots'
      USING ERRCODE = 'PT425';
  END IF;

  -- slot이 없는, 이 그룹 소유 clip만 reviewer 2명으로 한 번에 자재화한다.
  INSERT INTO public.motion_clip_review_slots
    (clip_id, group_id, reviewer_id, cohort_kind, cohort_id, activity_day_kst)
  SELECT
    m.id,
    v_group_id,
    mem.user_id,
    'live',
    NULL,
    (m.started_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date
  FROM public.motion_clips m
  JOIN public.motion_labeling_review_group_cameras gc
    ON gc.camera_id = m.camera_id
   AND gc.group_id = v_group_id
   AND gc.ended_at IS NULL
  JOIN public.motion_clip_consensus c
    ON c.clip_id = m.id
   AND c.cohort_kind = 'live'
   AND c.group_id = v_group_id
  CROSS JOIN unnest(v_members) AS mem(user_id)
  WHERE m.started_at >= v_from
    AND m.started_at < v_to
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_system_exclusions sx
      WHERE sx.clip_id = m.id
        AND sx.state IN ('quarantined','media_deleted')
    )
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_review_slots existing
      WHERE existing.clip_id = m.id
        AND existing.cohort_kind = 'live'
    )
  ON CONFLICT (clip_id, reviewer_id) WHERE cohort_kind = 'live' DO NOTHING;

  -- bulk INSERT 뒤에도 모든 owned clip이 정확히 두 slot인지 검증한다.
  IF EXISTS (
    SELECT c.clip_id
    FROM public.motion_clip_consensus c
    JOIN public.motion_clips m ON m.id = c.clip_id
    JOIN public.motion_labeling_review_group_cameras gc
      ON gc.camera_id = m.camera_id
     AND gc.group_id = v_group_id
     AND gc.ended_at IS NULL
    LEFT JOIN public.motion_clip_review_slots s
      ON s.clip_id = c.clip_id AND s.cohort_kind = 'live'
    WHERE c.cohort_kind = 'live'
      AND c.group_id = v_group_id
      AND m.started_at >= v_from
      AND m.started_at < v_to
      AND NOT EXISTS (
        SELECT 1
        FROM public.motion_clip_system_exclusions sx
        WHERE sx.clip_id = m.id
          AND sx.state IN ('quarantined','media_deleted')
      )
    GROUP BY c.clip_id
    HAVING count(s.id) <> 2
  ) THEN
    RAISE EXCEPTION 'live clip must have zero or two slots'
      USING ERRCODE = 'PT425';
  END IF;

  SELECT count(*) INTO v_materialized
  FROM public.motion_clip_consensus c
  JOIN public.motion_clips m ON m.id = c.clip_id
  JOIN public.motion_labeling_review_group_cameras gc
    ON gc.camera_id = m.camera_id
   AND gc.group_id = v_group_id
   AND gc.ended_at IS NULL
  WHERE c.cohort_kind = 'live'
    AND c.group_id = v_group_id
    AND m.started_at >= v_from
    AND m.started_at < v_to
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_system_exclusions sx
      WHERE sx.clip_id = m.id
        AND sx.state IN ('quarantined','media_deleted')
    );

  RETURN v_materialized;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_ensure_motion_review_slots(uuid, date)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_ensure_motion_review_slots(uuid, date)
  TO service_role;

COMMIT;
