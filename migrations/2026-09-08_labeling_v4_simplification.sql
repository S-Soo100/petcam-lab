BEGIN;

-- 라벨링 웹 v4: 단독 확정 + 카메라 배정(편의 필터) + blind 트랙 퇴역(코드 제거·테이블 보존·RPC EXECUTE 회수).

-- ── 배정 ────────────────────────────────────────────────────────────
CREATE TABLE public.labeler_camera_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  camera_id uuid NOT NULL REFERENCES public.cameras(id) ON DELETE RESTRICT,
  assigned_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
  assigned_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  ended_at timestamptz
);
COMMENT ON TABLE public.labeler_camera_assignments IS
  '회원 ↔ 카메라 배정. "먼저 보여줄 것"만 정하고 권한은 아니다(v4 스펙 §4.1).';
CREATE UNIQUE INDEX uq_labeler_camera_assignment_active
  ON public.labeler_camera_assignments (user_id, camera_id) WHERE ended_at IS NULL;
CREATE INDEX idx_labeler_camera_assignments_user_active
  ON public.labeler_camera_assignments (user_id) WHERE ended_at IS NULL;
ALTER TABLE public.labeler_camera_assignments ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.labeler_camera_assignments FROM PUBLIC, anon, authenticated, service_role;

-- 배정 갱신: 목록에 없는 활성 배정은 종료, 새 것은 추가(멱등).
CREATE FUNCTION public.fn_set_labeler_camera_assignments(
  p_user_id uuid, p_camera_ids uuid[], p_actor_id uuid
) RETURNS TABLE (camera_id uuid)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
  IF p_user_id IS NULL OR p_actor_id IS NULL THEN
    RAISE EXCEPTION 'required parameter is missing' USING ERRCODE = '22023';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.labelers l WHERE l.user_id = p_user_id) THEN
    RAISE EXCEPTION 'user is not an approved labeler' USING ERRCODE = 'PT403';
  END IF;
  IF EXISTS (SELECT 1 FROM unnest(coalesce(p_camera_ids, '{}')) cid
             WHERE NOT EXISTS (SELECT 1 FROM public.cameras c WHERE c.id = cid)) THEN
    RAISE EXCEPTION 'unknown camera' USING ERRCODE = 'P0002';
  END IF;
  UPDATE public.labeler_camera_assignments a
     SET ended_at = clock_timestamp()
   WHERE a.user_id = p_user_id AND a.ended_at IS NULL
     AND NOT (a.camera_id = ANY (coalesce(p_camera_ids, '{}')));
  INSERT INTO public.labeler_camera_assignments (user_id, camera_id, assigned_by)
  SELECT p_user_id, cid, p_actor_id
    FROM unnest(coalesce(p_camera_ids, '{}')) cid
   WHERE NOT EXISTS (SELECT 1 FROM public.labeler_camera_assignments a
                      WHERE a.user_id = p_user_id AND a.camera_id = cid AND a.ended_at IS NULL);
  RETURN QUERY SELECT a.camera_id FROM public.labeler_camera_assignments a
   WHERE a.user_id = p_user_id AND a.ended_at IS NULL ORDER BY a.assigned_at;
END $$;

-- 멤버 목록(owner 배정 UI). 이메일·UUID 외 개인정보 없음.
-- display_name 은 raw(nullable) — 표시명 해석(owner/기본값)은 API 의 단일 resolver 가 한다.
CREATE FUNCTION public.fn_list_labeling_v4_members()
RETURNS TABLE (user_id uuid, display_name text, camera_ids uuid[])
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT l.user_id,
         la.display_name,
         coalesce((SELECT array_agg(a.camera_id ORDER BY a.assigned_at)
                     FROM public.labeler_camera_assignments a
                    WHERE a.user_id = l.user_id AND a.ended_at IS NULL), '{}')
    FROM public.labelers l
    LEFT JOIN public.labeler_applications la ON la.user_id = l.user_id
   ORDER BY la.display_name NULLS LAST, l.user_id
$$;

-- 카메라 옵션(필터 칩). 배정 여부만 플래그로.
CREATE FUNCTION public.fn_list_labeling_v4_cameras(p_viewer_id uuid)
RETURNS TABLE (camera_id uuid, camera_name text, assigned boolean)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT c.id, coalesce(c.name, c.id::text),
         EXISTS (SELECT 1 FROM public.labeler_camera_assignments a
                  WHERE a.user_id = p_viewer_id AND a.camera_id = c.id AND a.ended_at IS NULL)
    FROM public.cameras c
   ORDER BY c.name NULLS LAST, c.id
$$;

-- ── 목록 ────────────────────────────────────────────────────────────
CREATE FUNCTION public.fn_list_labeling_v4_clips(
  p_viewer_id uuid,
  p_is_owner boolean,
  p_scope text,
  p_camera_ids uuid[],
  p_label_state text,
  p_highlight_state text,
  p_engine_schema_version text,
  p_algorithm_version text,
  p_detector_identity text,
  p_cursor_started_at timestamptz,
  p_cursor_id uuid,
  p_limit integer
) RETURNS TABLE (
  clip_id uuid,
  camera_id uuid,
  camera_name text,
  started_at timestamptz,
  duration_sec double precision,
  media_ready boolean,
  highlight_source text,   -- human | rule
  highlight_status text,   -- decided | pending | failed
  highlight_value boolean,
  highlight_reason text,
  reviewer_id uuid,             -- 사람 확정일 때만. API 가 표시명으로 바꾸고 공개 JSON 에서 뺀다.
  reviewer_display_name text,   -- labeler_applications.display_name raw(nullable)
  decided_at timestamptz
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_rule record;
  v_cameras uuid[];
BEGIN
  IF p_viewer_id IS NULL OR p_scope IS NULL OR p_scope NOT IN ('mine','all') THEN
    RAISE EXCEPTION 'invalid scope' USING ERRCODE = '22023';
  END IF;
  IF p_label_state IS NOT NULL AND p_label_state NOT IN ('unlabeled','labeled') THEN
    RAISE EXCEPTION 'invalid label state' USING ERRCODE = '22023';
  END IF;
  IF p_highlight_state IS NOT NULL AND p_highlight_state NOT IN ('yes','no','pending') THEN
    RAISE EXCEPTION 'invalid highlight state' USING ERRCODE = '22023';
  END IF;
  IF p_limit IS NULL OR p_limit < 1 OR p_limit > 101 THEN
    RAISE EXCEPTION 'invalid limit' USING ERRCODE = '22023';
  END IF;
  IF (p_cursor_started_at IS NULL) <> (p_cursor_id IS NULL) THEN
    RAISE EXCEPTION 'cursor must have both parts' USING ERRCODE = '22023';
  END IF;

  IF p_scope = 'mine' THEN
    SELECT array_agg(a.camera_id) INTO v_cameras
      FROM public.labeler_camera_assignments a
     WHERE a.user_id = p_viewer_id AND a.ended_at IS NULL;
    IF v_cameras IS NULL THEN RETURN; END IF;  -- 배정 없음 = 빈 목록
    IF p_camera_ids IS NOT NULL THEN
      SELECT array_agg(x) INTO v_cameras FROM unnest(v_cameras) x WHERE x = ANY (p_camera_ids);
      IF v_cameras IS NULL THEN RETURN; END IF;
    END IF;
  ELSE
    v_cameras := p_camera_ids;  -- NULL = 전체
  END IF;

  SELECT * INTO v_rule FROM public.fn_get_active_highlight_rule();
  IF v_rule.version IS NULL THEN
    RAISE EXCEPTION 'no active highlight rule' USING ERRCODE = 'PT428';
  END IF;

  RETURN QUERY
  SELECT c.id, c.camera_id, coalesce(cam.name, c.camera_id::text), c.started_at, c.duration_sec,
         (c.r2_key IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM public.motion_clip_system_exclusions x
             WHERE x.clip_id = c.id AND x.state = 'media_deleted')),
         CASE WHEN vd.id IS NOT NULL THEN 'human' ELSE 'rule' END,
         -- failed_terminal 조회는 스칼라 서브쿼리로 CASE 분기 안에서만 돈다(출력 행 중 run 없는 것만).
         CASE WHEN vd.id IS NOT NULL THEN 'decided'
              WHEN rr.run_id IS NOT NULL THEN 'decided'
              WHEN EXISTS (SELECT 1 FROM public.gme_jobs j
                            WHERE j.clip_id = c.id AND j.detector_identity = p_detector_identity
                              AND j.algorithm_version = p_algorithm_version AND j.status = 'failed_terminal')
                   THEN 'failed' ELSE 'pending' END,
         CASE WHEN vd.id IS NOT NULL THEN vd.verdict
              WHEN rr.run_id IS NOT NULL THEN ev.initial ELSE NULL END,
         CASE WHEN vd.id IS NOT NULL THEN vd.initial_reason
              WHEN rr.run_id IS NOT NULL THEN ev.reason
              WHEN EXISTS (SELECT 1 FROM public.gme_jobs j
                            WHERE j.clip_id = c.id AND j.detector_identity = p_detector_identity
                              AND j.algorithm_version = p_algorithm_version AND j.status = 'failed_terminal')
                   THEN '분석 실패' ELSE '분석 대기' END,
         vd.reviewer_id,
         CASE WHEN vd.id IS NOT NULL THEN la.display_name ELSE NULL END,
         vd.created_at
    FROM public.motion_clips c
    LEFT JOIN public.cameras cam ON cam.id = c.camera_id
    LEFT JOIN LATERAL (
      SELECT v.* FROM public.motion_clip_highlight_verdicts v
       WHERE v.clip_id = c.id ORDER BY v.created_at DESC, v.id DESC LIMIT 1
    ) vd ON true
    LEFT JOIN public.labeler_applications la ON la.user_id = vd.reviewer_id
    LEFT JOIN LATERAL (
      -- run_id 를 따로 꺼낸다: 복합값(run_row) IS [NOT] NULL 은 필드별 판정이라 nullable 컬럼 하나만 있어도 뒤집힌다.
      SELECT r AS run_row, r.id AS run_id
        FROM public.gme_jobs j
        JOIN public.gme_runs r ON r.id = j.result_run_id AND r.job_id = j.id
       WHERE j.clip_id = c.id
         AND j.engine_schema_version = p_engine_schema_version
         AND j.algorithm_version = p_algorithm_version
         AND j.detector_identity = p_detector_identity
         AND j.status = 'succeeded' AND r.status = 'ok'
       ORDER BY j.created_at ASC, j.id ASC LIMIT 1
    ) rr ON true
    LEFT JOIN LATERAL public.fn_highlight_rule_eval(rr.run_row, v_rule.params) ev ON rr.run_id IS NOT NULL
   -- r2_key IS NOT NULL 은 부분 인덱스(idx_motion_clips_library_started)를 타게 하고,
   -- 적격 가드는 test 목적·비 canonical 경로·격리/삭제 clip 을 목록에서 fail-closed 로 뺀다.
   WHERE c.r2_key IS NOT NULL
     AND public.fn_is_motion_clip_production_labeling_eligible(c.id)
     AND (v_cameras IS NULL OR c.camera_id = ANY (v_cameras))
     AND (p_cursor_started_at IS NULL
          OR (c.started_at, c.id) < (p_cursor_started_at, p_cursor_id))
     AND (p_label_state IS NULL
          OR (p_label_state = 'unlabeled' AND vd.id IS NULL)
          OR (p_label_state = 'labeled' AND vd.id IS NOT NULL))
     AND (p_highlight_state IS NULL
          OR (p_highlight_state = 'yes' AND coalesce(vd.verdict, ev.initial) = true)
          OR (p_highlight_state = 'no' AND coalesce(vd.verdict, ev.initial) = false)
          OR (p_highlight_state = 'pending' AND vd.id IS NULL AND rr.run_id IS NULL))
   ORDER BY c.started_at DESC, c.id DESC
   LIMIT p_limit;
END $$;

-- ── 운영 현황(집계만) ───────────────────────────────────────────────
CREATE FUNCTION public.fn_get_labeling_v4_overview(
  p_engine_schema_version text, p_algorithm_version text, p_detector_identity text
) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  WITH day AS (
    SELECT (now() AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date AS today
  ),
  labeled AS (
    SELECT v.clip_id, v.reviewer_id, v.created_at, c.camera_id
      FROM public.motion_clip_highlight_verdicts v
      JOIN public.motion_clips c ON c.id = v.clip_id
     WHERE v.kind = 'initial'
  )
  SELECT jsonb_build_object(
    'activity_day', (SELECT today FROM day),
    'unlabeled_total', (SELECT count(*) FROM public.motion_clips c
                         WHERE c.r2_key IS NOT NULL
                           AND NOT EXISTS (SELECT 1 FROM labeled l WHERE l.clip_id = c.id)),
    'labeled_today', (SELECT count(*) FROM labeled l, day
                       WHERE (l.created_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date = day.today),
    'labeled_7d', (SELECT count(*) FROM labeled l WHERE l.created_at >= now() - interval '7 days'),
    'members', coalesce((
      SELECT jsonb_agg(jsonb_build_object('user_id', m.reviewer_id, 'display_name', la.display_name, 'labeled_7d', m.n) ORDER BY m.n DESC)
        FROM (SELECT reviewer_id, count(*) AS n FROM labeled WHERE created_at >= now() - interval '7 days' GROUP BY reviewer_id) m
        LEFT JOIN public.labeler_applications la ON la.user_id = m.reviewer_id), '[]'::jsonb),
    'cameras', coalesce((
      SELECT jsonb_agg(jsonb_build_object('camera_name', coalesce(cam.name, cam.id::text),
                                          'unlabeled', s.unlabeled, 'labeled_7d', s.labeled_7d) ORDER BY cam.name NULLS LAST)
        FROM (SELECT c.camera_id,
                     count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM labeled l WHERE l.clip_id = c.id)) AS unlabeled,
                     count(*) FILTER (WHERE EXISTS (SELECT 1 FROM labeled l WHERE l.clip_id = c.id AND l.created_at >= now() - interval '7 days')) AS labeled_7d
                FROM public.motion_clips c WHERE c.r2_key IS NOT NULL GROUP BY c.camera_id) s
        JOIN public.cameras cam ON cam.id = s.camera_id), '[]'::jsonb)
  )
$$;

-- ── blind 트랙 RPC EXECUTE 회수(존재할 때만, DROP 없음) ────────────────
DO $$
DECLARE
  sig text;
BEGIN
  FOREACH sig IN ARRAY ARRAY[
    'public.fn_manage_motion_review_group(uuid, uuid, text, uuid[], uuid[])',
    'public.fn_ensure_motion_review_slots(uuid, date)',
    'public.fn_list_motion_blind_queue(uuid, date, text, uuid, timestamptz, uuid, integer)',
    'public.fn_list_motion_blind_queue(uuid, date, text, uuid, boolean, numeric, timestamptz, uuid, integer)',
    'public.fn_get_motion_blind_workspace(uuid)',
    'public.fn_claim_motion_review_slot(uuid, uuid, text, uuid, uuid, uuid)',
    'public.fn_submit_motion_blind_review(uuid, uuid, text, uuid, text, text, jsonb, text, uuid)',
    'public.fn_finalize_motion_blind_consensus(uuid, text, uuid, uuid, uuid, text, text, text, text, text, jsonb, text[])',
    'public.fn_list_motion_blind_conflicts(timestamptz, uuid, integer)',
    'public.fn_resolve_motion_blind_consensus(uuid, text, uuid, uuid, text, text, jsonb, text, timestamptz)',
    'public.fn_reassign_motion_review_slot(uuid, uuid, uuid)',
    'public.fn_manage_motion_blind_canary(text, uuid, uuid, text, uuid, uuid[], uuid[])',
    'public.fn_list_motion_blind_history(uuid, timestamptz, uuid, text, uuid[], timestamptz, timestamptz, text, text, text, integer)',
    'public.fn_get_motion_blind_owner_overview(date)'
  ] LOOP
    IF to_regprocedure(sig) IS NOT NULL THEN
      EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM service_role', sig);
    END IF;
  END LOOP;
END $$;

-- ── 권한 ──────────────────────────────────────────────────────────
REVOKE ALL ON FUNCTION public.fn_set_labeler_camera_assignments(uuid, uuid[], uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_set_labeler_camera_assignments(uuid, uuid[], uuid) TO service_role;
REVOKE ALL ON FUNCTION public.fn_list_labeling_v4_members() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_labeling_v4_members() TO service_role;
REVOKE ALL ON FUNCTION public.fn_list_labeling_v4_cameras(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_labeling_v4_cameras(uuid) TO service_role;
REVOKE ALL ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, timestamptz, uuid, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, timestamptz, uuid, integer) TO service_role;
REVOKE ALL ON FUNCTION public.fn_get_labeling_v4_overview(text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_labeling_v4_overview(text, text, text) TO service_role;

COMMIT;
