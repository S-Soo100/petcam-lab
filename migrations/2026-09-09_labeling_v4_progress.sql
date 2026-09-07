-- 라벨링 v4 라벨러 진행 집계 (UX ③, owner 결정 2026-09-08).
-- 라벨러 홈(내 카메라/전체)에 "오늘 내가 N개 · 남은 M개"를 보여주기 위한 읽기 전용 RPC.
-- 집계 방식은 fn_get_labeling_v4_overview 와 같다(clip 별 첫 확정 시각 1회 집계 + 운영 적격 가드).
-- unlabeled_mine 은 배정 카메라가 없으면 NULL(화면은 "배정 없음"으로 표시).
BEGIN;

CREATE FUNCTION public.fn_get_labeling_v4_progress(p_viewer_id uuid)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  WITH day AS (
    SELECT (now() AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date AS today
  ),
  mine AS (
    SELECT array_agg(a.camera_id) AS cams
      FROM public.labeler_camera_assignments a
     WHERE a.user_id = p_viewer_id AND a.ended_at IS NULL
  ),
  labeled AS (
    SELECT v.clip_id FROM public.motion_clip_highlight_verdicts v WHERE v.kind = 'initial' GROUP BY v.clip_id
  ),
  unlabeled AS (
    SELECT c.id, c.camera_id
      FROM public.motion_clips c
      LEFT JOIN labeled l ON l.clip_id = c.id
     WHERE c.r2_key IS NOT NULL
       AND l.clip_id IS NULL
       AND public.fn_is_motion_clip_production_labeling_eligible(c.id)
  )
  SELECT jsonb_build_object(
    'activity_day', (SELECT today FROM day),
    'labeled_today_me', (SELECT count(*) FROM public.motion_clip_highlight_verdicts v, day
                          WHERE v.kind = 'initial' AND v.reviewer_id = p_viewer_id
                            AND (v.created_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date = day.today),
    'labeled_today_all', (SELECT count(*) FROM public.motion_clip_highlight_verdicts v, day
                           WHERE v.kind = 'initial'
                             AND (v.created_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date = day.today),
    'unlabeled_all', (SELECT count(*) FROM unlabeled),
    'unlabeled_mine', (SELECT CASE WHEN m.cams IS NULL THEN NULL
                                   ELSE (SELECT count(*) FROM unlabeled u WHERE u.camera_id = ANY (m.cams)) END
                         FROM mine m)
  )
$$;

REVOKE ALL ON FUNCTION public.fn_get_labeling_v4_progress(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_labeling_v4_progress(uuid) TO service_role;

COMMIT;
