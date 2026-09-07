-- 집계 함수 2개 성능·단순화 (code-review 2026-09-07 효율·단순화 항목, 시그니처·반환 동일):
-- 1) fn_get_labeling_v4_overview — 영상마다 labeled CTE 를 두 번 상관 EXISTS 로 훑던 것을
--    clip 별 최신 확정 시각 한 번 집계 + LEFT JOIN 으로 바꾼다. 카메라 breakdown 은 LEFT JOIN 으로
--    camera 미매칭 영상도 합계와 어긋나지 않게 한다.
-- 2) fn_highlight_rule_stats — reason_counts 를 그룹마다 재조회하던 상관 서브쿼리 대신
--    같은 행 집합에서 FILTER 로 계산한다(사유 enum 6개 고정).
BEGIN;

CREATE OR REPLACE FUNCTION public.fn_get_labeling_v4_overview(
  p_engine_schema_version text, p_algorithm_version text, p_detector_identity text
) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  WITH day AS (
    SELECT (now() AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date AS today
  ),
  latest AS (
    SELECT v.clip_id, min(v.created_at) AS first_at
      FROM public.motion_clip_highlight_verdicts v
     WHERE v.kind = 'initial'
     GROUP BY v.clip_id
  ),
  eligible AS (
    SELECT c.id, c.camera_id, l.first_at
      FROM public.motion_clips c
      LEFT JOIN latest l ON l.clip_id = c.id
     WHERE c.r2_key IS NOT NULL
       AND public.fn_is_motion_clip_production_labeling_eligible(c.id)
  ),
  per_camera AS (
    SELECT e.camera_id,
           count(*) FILTER (WHERE e.first_at IS NULL) AS unlabeled,
           count(*) FILTER (WHERE e.first_at >= now() - interval '7 days') AS labeled_7d
      FROM eligible e
     GROUP BY e.camera_id
  )
  SELECT jsonb_build_object(
    'activity_day', (SELECT today FROM day),
    'unlabeled_total', (SELECT count(*) FROM eligible e WHERE e.first_at IS NULL),
    'labeled_today', (SELECT count(*) FROM public.motion_clip_highlight_verdicts v, day
                       WHERE v.kind = 'initial'
                         AND (v.created_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date = day.today),
    'labeled_7d', (SELECT count(*) FROM public.motion_clip_highlight_verdicts v
                    WHERE v.kind = 'initial' AND v.created_at >= now() - interval '7 days'),
    'members', coalesce((
      SELECT jsonb_agg(jsonb_build_object('user_id', m.reviewer_id, 'display_name', la.display_name, 'labeled_7d', m.n) ORDER BY m.n DESC)
        FROM (SELECT v.reviewer_id, count(*) AS n
                FROM public.motion_clip_highlight_verdicts v
               WHERE v.kind = 'initial' AND v.created_at >= now() - interval '7 days'
               GROUP BY v.reviewer_id) m
        LEFT JOIN public.labeler_applications la ON la.user_id = m.reviewer_id), '[]'::jsonb),
    'cameras', coalesce((
      SELECT jsonb_agg(jsonb_build_object('camera_name', coalesce(cam.name, pc.camera_id::text, '(카메라 없음)'),
                                          'unlabeled', pc.unlabeled, 'labeled_7d', pc.labeled_7d)
                       ORDER BY cam.name NULLS LAST, pc.camera_id)
        FROM per_camera pc
        LEFT JOIN public.cameras cam ON cam.id = pc.camera_id), '[]'::jsonb)
  )
$$;

CREATE OR REPLACE FUNCTION public.fn_highlight_rule_stats(p_from timestamptz, p_to timestamptz)
RETURNS TABLE (
  rule_version text,
  camera_id uuid,
  camera_name text,
  verdict_count bigint,
  kept_count bigint,
  decided_count bigint,
  o_to_x bigint,
  x_to_o bigint,
  pending_initial bigint,
  reason_counts jsonb
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT
    v.rule_version,
    c.camera_id,
    cam.name,
    count(*)::bigint,
    count(*) FILTER (WHERE v.changed = false)::bigint,
    count(*) FILTER (WHERE v.initial IS NOT NULL)::bigint,
    count(*) FILTER (WHERE v.initial = true AND v.verdict = false)::bigint,
    count(*) FILTER (WHERE v.initial = false AND v.verdict = true)::bigint,
    count(*) FILTER (WHERE v.initial IS NULL)::bigint,
    -- 사유 enum 은 CHECK 로 6개 고정 — 같은 행 집합에서 FILTER 로 세고 0 은 뺀다.
    jsonb_strip_nulls(jsonb_build_object(
      'false_detection',         nullif(count(*) FILTER (WHERE v.change_reason = 'false_detection'), 0),
      'gecko_not_visible',       nullif(count(*) FILTER (WHERE v.change_reason = 'gecko_not_visible'), 0),
      'camera_shake',            nullif(count(*) FILTER (WHERE v.change_reason = 'camera_shake'), 0),
      'too_short',               nullif(count(*) FILTER (WHERE v.change_reason = 'too_short'), 0),
      'interesting_low_numbers', nullif(count(*) FILTER (WHERE v.change_reason = 'interesting_low_numbers'), 0),
      'other',                   nullif(count(*) FILTER (WHERE v.change_reason = 'other'), 0)
    ))
  FROM public.motion_clip_highlight_verdicts v
  JOIN public.motion_clips c ON c.id = v.clip_id
  LEFT JOIN public.cameras cam ON cam.id = c.camera_id
  WHERE v.kind = 'initial' AND v.created_at >= p_from AND v.created_at < p_to
  GROUP BY v.rule_version, c.camera_id, cam.name
  ORDER BY v.rule_version DESC, cam.name NULLS LAST
$$;

COMMIT;
