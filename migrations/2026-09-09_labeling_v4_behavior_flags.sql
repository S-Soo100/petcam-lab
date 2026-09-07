-- 라벨링 v4 "의미있는 행동" 체크 (owner 결정 2026-09-08).
-- 하이라이트 O/X 와 별개로, 사람이 보기에 VLM/GT 라벨 대상 행동(물 마시기·허물·밥 등)이 보이는 영상을
-- 종류 판정 없이 표시만 해 둔다. 나중에 이 표시만 모아 기존 행동 라벨링(GT)을 붙이는 후보 목록이 된다.
--
-- 계약:
-- - 영상당 최대 1개(PK clip_id). 승인 사용자면 누구나 체크. 해제는 체크한 사람 본인 또는 owner 만(PT403).
-- - 운영 비적격·미존재 영상은 같은 P0002 (verdict 와 동일하게 존재 여부를 새지 않는다).
-- - 테이블은 RPC 로만 접근(service_role 포함 직접 권한 없음, RLS on).
-- - fn_list_labeling_v4_clips 에 p_behavior_flag('yes'|NULL) 필터와 behavior_flagged* 컬럼을 더한 13-인자
--   버전을 추가하고, 기존 12-인자 시그니처는 위임 wrapper 로 남겨 migration→웹 배포 사이에 끊김이 없게 한다.
BEGIN;

CREATE TABLE public.motion_clip_behavior_flags (
  clip_id uuid PRIMARY KEY REFERENCES public.motion_clips(id) ON DELETE CASCADE,
  flagged_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  flagged_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_motion_clip_behavior_flags_flagged_at ON public.motion_clip_behavior_flags (flagged_at DESC);
ALTER TABLE public.motion_clip_behavior_flags ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.motion_clip_behavior_flags FROM PUBLIC, anon, authenticated, service_role;

-- 현재 체크 상태(항상 1행). display_name 은 raw(nullable) — 문자열 결정은 API resolver 가 한다.
CREATE FUNCTION public.fn_get_motion_clip_behavior_flag(p_clip_id uuid)
RETURNS TABLE (flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT (f.clip_id IS NOT NULL) AS flagged, f.flagged_by, la.display_name, f.flagged_at
    FROM (SELECT p_clip_id AS id) x
    LEFT JOIN public.motion_clip_behavior_flags f ON f.clip_id = x.id
    LEFT JOIN public.labeler_applications la ON la.user_id = f.flagged_by;
$$;

CREATE FUNCTION public.fn_set_motion_clip_behavior_flag(
  p_clip_id uuid, p_user_id uuid, p_is_owner boolean, p_flagged boolean
) RETURNS TABLE (flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_existing_by uuid;
BEGIN
  IF p_clip_id IS NULL OR p_user_id IS NULL OR p_flagged IS NULL THEN
    RAISE EXCEPTION 'invalid arguments' USING ERRCODE = '22023';
  END IF;
  IF NOT public.fn_is_motion_clip_production_labeling_eligible(p_clip_id) THEN
    RAISE EXCEPTION 'motion clip not found' USING ERRCODE = 'P0002';
  END IF;

  IF p_flagged THEN
    -- 이미 체크돼 있으면 첫 체크한 사람을 유지(멱등).
    INSERT INTO public.motion_clip_behavior_flags (clip_id, flagged_by)
    VALUES (p_clip_id, p_user_id)
    ON CONFLICT (clip_id) DO NOTHING;
  ELSE
    SELECT f.flagged_by INTO v_existing_by FROM public.motion_clip_behavior_flags f WHERE f.clip_id = p_clip_id;
    IF v_existing_by IS NOT NULL AND v_existing_by <> p_user_id AND NOT coalesce(p_is_owner, false) THEN
      RAISE EXCEPTION 'only the flagger or owner can unflag' USING ERRCODE = 'PT403';
    END IF;
    DELETE FROM public.motion_clip_behavior_flags f WHERE f.clip_id = p_clip_id;
  END IF;

  RETURN QUERY SELECT * FROM public.fn_get_motion_clip_behavior_flag(p_clip_id);
END $$;

-- 목록: 2026-09-08_labeling_v4_list_chunked.sql 과 동일 + p_behavior_flag 필터 + behavior_flagged* 컬럼.
CREATE FUNCTION public.fn_list_labeling_v4_clips(
  p_viewer_id uuid,
  p_is_owner boolean,
  p_scope text,
  p_camera_ids uuid[],
  p_label_state text,
  p_highlight_state text,
  p_behavior_flag text,
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
  highlight_source text,
  highlight_status text,
  highlight_value boolean,
  highlight_reason text,
  reviewer_id uuid,
  reviewer_display_name text,
  decided_at timestamptz,
  behavior_flagged boolean,
  behavior_flagged_by uuid,
  behavior_flagged_by_display_name text,
  behavior_flagged_at timestamptz
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_rule record;
  v_cameras uuid[];
  v_cur_started timestamptz := p_cursor_started_at;
  v_cur_id uuid := p_cursor_id;
  v_chunk constant integer := 200;
  v_emitted integer := 0;
  v_scanned integer;
  v_row record;
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
  IF p_behavior_flag IS NOT NULL AND p_behavior_flag NOT IN ('yes') THEN
    RAISE EXCEPTION 'invalid behavior flag filter' USING ERRCODE = '22023';
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
    IF v_cameras IS NULL THEN RETURN; END IF;
    IF p_camera_ids IS NOT NULL THEN
      SELECT array_agg(x) INTO v_cameras FROM unnest(v_cameras) x WHERE x = ANY (p_camera_ids);
      IF v_cameras IS NULL THEN RETURN; END IF;
    END IF;
  ELSE
    v_cameras := p_camera_ids;
  END IF;

  SELECT * INTO v_rule FROM public.fn_get_active_highlight_rule();
  IF v_rule.version IS NULL THEN
    RAISE EXCEPTION 'no active highlight rule' USING ERRCODE = 'PT428';
  END IF;

  LOOP
    v_scanned := 0;
    FOR v_row IN
      WITH chunk AS (
        SELECT c.id, c.camera_id, c.started_at, c.duration_sec
          FROM public.motion_clips c
         WHERE c.r2_key IS NOT NULL
           AND (v_cameras IS NULL OR c.camera_id = ANY (v_cameras))
           AND (v_cur_started IS NULL OR (c.started_at, c.id) < (v_cur_started, v_cur_id))
           AND (p_label_state IS NULL
                OR (p_label_state = 'unlabeled' AND NOT EXISTS (
                      SELECT 1 FROM public.motion_clip_highlight_verdicts v WHERE v.clip_id = c.id))
                OR (p_label_state = 'labeled' AND EXISTS (
                      SELECT 1 FROM public.motion_clip_highlight_verdicts v WHERE v.clip_id = c.id)))
           -- 희소 필터라 chunk 단계에서 걸러야 전체 스캔이 안 된다(PK 조회).
           AND (p_behavior_flag IS NULL
                OR EXISTS (SELECT 1 FROM public.motion_clip_behavior_flags f WHERE f.clip_id = c.id))
           AND (p_highlight_state IS DISTINCT FROM 'pending'
                OR (NOT EXISTS (SELECT 1 FROM public.motion_clip_highlight_verdicts v WHERE v.clip_id = c.id)
                    AND NOT EXISTS (
                      SELECT 1 FROM public.gme_jobs j
                        JOIN public.gme_runs r ON r.id = j.result_run_id AND r.job_id = j.id
                       WHERE j.clip_id = c.id
                         AND j.engine_schema_version = p_engine_schema_version
                         AND j.algorithm_version = p_algorithm_version
                         AND j.detector_identity = p_detector_identity
                         AND j.status = 'succeeded' AND r.status = 'ok')))
         ORDER BY c.started_at DESC, c.id DESC
         LIMIT v_chunk
      )
      SELECT c.id AS r_clip_id, c.camera_id AS r_camera_id,
             coalesce(cam.name, c.camera_id::text) AS r_camera_name,
             c.started_at AS r_started_at, c.duration_sec AS r_duration_sec,
             public.fn_is_motion_clip_production_labeling_eligible(c.id) AS r_eligible,
             NOT EXISTS (SELECT 1 FROM public.motion_clip_system_exclusions x
                          WHERE x.clip_id = c.id AND x.state = 'media_deleted') AS r_media_ready,
             vd.id AS vd_id, vd.verdict AS vd_verdict, vd.initial_reason AS vd_reason,
             vd.reviewer_id AS vd_reviewer, vd.created_at AS vd_at, la.display_name AS vd_name,
             rr.run_id AS r_run_id, ev.initial AS ev_initial, ev.reason AS ev_reason,
             EXISTS (SELECT 1 FROM public.gme_jobs j
                      WHERE j.clip_id = c.id AND j.detector_identity = p_detector_identity
                        AND j.algorithm_version = p_algorithm_version AND j.status = 'failed_terminal') AS r_failed,
             bf.flagged_by AS bf_by, bf.flagged_at AS bf_at, bla.display_name AS bf_name
        FROM chunk c
        LEFT JOIN public.cameras cam ON cam.id = c.camera_id
        LEFT JOIN LATERAL (
          SELECT v.* FROM public.motion_clip_highlight_verdicts v
           WHERE v.clip_id = c.id ORDER BY v.created_at DESC, v.id DESC LIMIT 1
        ) vd ON true
        LEFT JOIN public.labeler_applications la ON la.user_id = vd.reviewer_id
        LEFT JOIN public.motion_clip_behavior_flags bf ON bf.clip_id = c.id
        LEFT JOIN public.labeler_applications bla ON bla.user_id = bf.flagged_by
        LEFT JOIN LATERAL (
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
       ORDER BY c.started_at DESC, c.id DESC
    LOOP
      v_scanned := v_scanned + 1;
      v_cur_started := v_row.r_started_at;
      v_cur_id := v_row.r_clip_id;
      CONTINUE WHEN NOT v_row.r_eligible;
      CONTINUE WHEN p_label_state = 'unlabeled' AND v_row.vd_id IS NOT NULL;
      CONTINUE WHEN p_label_state = 'labeled' AND v_row.vd_id IS NULL;
      CONTINUE WHEN p_highlight_state = 'yes'
        AND coalesce(v_row.vd_verdict, v_row.ev_initial) IS DISTINCT FROM true;
      CONTINUE WHEN p_highlight_state = 'no'
        AND coalesce(v_row.vd_verdict, v_row.ev_initial) IS DISTINCT FROM false;
      CONTINUE WHEN p_highlight_state = 'pending'
        AND NOT (v_row.vd_id IS NULL AND v_row.r_run_id IS NULL);

      clip_id := v_row.r_clip_id;
      camera_id := v_row.r_camera_id;
      camera_name := v_row.r_camera_name;
      started_at := v_row.r_started_at;
      duration_sec := v_row.r_duration_sec;
      media_ready := v_row.r_media_ready;
      highlight_source := CASE WHEN v_row.vd_id IS NOT NULL THEN 'human' ELSE 'rule' END;
      highlight_status := CASE WHEN v_row.vd_id IS NOT NULL OR v_row.r_run_id IS NOT NULL THEN 'decided'
                               WHEN v_row.r_failed THEN 'failed' ELSE 'pending' END;
      highlight_value := CASE WHEN v_row.vd_id IS NOT NULL THEN v_row.vd_verdict
                              WHEN v_row.r_run_id IS NOT NULL THEN v_row.ev_initial ELSE NULL END;
      highlight_reason := CASE WHEN v_row.vd_id IS NOT NULL THEN v_row.vd_reason
                               WHEN v_row.r_run_id IS NOT NULL THEN v_row.ev_reason
                               WHEN v_row.r_failed THEN '분석 실패' ELSE '분석 대기' END;
      reviewer_id := v_row.vd_reviewer;
      reviewer_display_name := CASE WHEN v_row.vd_id IS NOT NULL THEN v_row.vd_name ELSE NULL END;
      decided_at := v_row.vd_at;
      behavior_flagged := v_row.bf_by IS NOT NULL;
      behavior_flagged_by := v_row.bf_by;
      behavior_flagged_by_display_name := v_row.bf_name;
      behavior_flagged_at := v_row.bf_at;
      RETURN NEXT;
      v_emitted := v_emitted + 1;
      EXIT WHEN v_emitted >= p_limit;
    END LOOP;
    EXIT WHEN v_emitted >= p_limit OR v_scanned < v_chunk;
  END LOOP;
END $$;

-- 기존 12-인자 시그니처는 위임 wrapper 로 유지(반환 컬럼·의미 동일). 웹 배포 뒤 다음 정리 migration 에서 제거 가능.
CREATE OR REPLACE FUNCTION public.fn_list_labeling_v4_clips(
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
  highlight_source text,
  highlight_status text,
  highlight_value boolean,
  highlight_reason text,
  reviewer_id uuid,
  reviewer_display_name text,
  decided_at timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT l.clip_id, l.camera_id, l.camera_name, l.started_at, l.duration_sec, l.media_ready,
         l.highlight_source, l.highlight_status, l.highlight_value, l.highlight_reason,
         l.reviewer_id, l.reviewer_display_name, l.decided_at
    FROM public.fn_list_labeling_v4_clips(
      p_viewer_id, p_is_owner, p_scope, p_camera_ids, p_label_state, p_highlight_state, NULL::text,
      p_engine_schema_version, p_algorithm_version, p_detector_identity, p_cursor_started_at, p_cursor_id, p_limit) l;
$$;

REVOKE ALL ON FUNCTION public.fn_get_motion_clip_behavior_flag(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_motion_clip_behavior_flag(uuid) TO service_role;
REVOKE ALL ON FUNCTION public.fn_set_motion_clip_behavior_flag(uuid, uuid, boolean, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_set_motion_clip_behavior_flag(uuid, uuid, boolean, boolean) TO service_role;
REVOKE ALL ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, text, timestamptz, uuid, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, text, timestamptz, uuid, integer) TO service_role;

COMMIT;
