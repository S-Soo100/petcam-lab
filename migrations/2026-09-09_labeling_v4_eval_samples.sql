-- 하이라이트 봉인 평가 표본 (2.6.1 전환 준비 Task 1, owner 결정 2026-09-08).
-- 2.6.1 은 무조건 전체 적용이므로 표본은 검출기 채택 판정용이 아니라, 전환 당일 규칙 숫자(10초/5초)를 바로
-- 재보정하기 위한 **사람 O/X 기준선**이다. 카메라 × 규칙 initial(O/X) 층화 무작위(스크립트, seed 고정).
--
-- 계약:
-- - 표본은 (sample_id, clip_id) 1행, 층(stratum) 문자열과 등록자를 남긴다. 등록은 owner 만(PT403), 운영 비적격 clip 은 건너뛴다.
-- - 테이블은 RPC 전용(service_role 직접 권한 없음, RLS on). 사람 확정은 기존 원장 그대로(재작성 없음).
-- - 목록 함수에 p_sample_id 를 더한 14-인자 버전을 추가하고, 13-인자는 위임 wrapper 로 남겨 migration→웹 배포 사이 무중단.
BEGIN;

CREATE TABLE public.motion_clip_eval_samples (
  sample_id text NOT NULL CHECK (sample_id ~ '^[a-z0-9-]{3,40}$'),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  stratum text NOT NULL,
  registered_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  registered_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (sample_id, clip_id)
);
CREATE INDEX idx_motion_clip_eval_samples_clip ON public.motion_clip_eval_samples (clip_id);
ALTER TABLE public.motion_clip_eval_samples ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.motion_clip_eval_samples FROM PUBLIC, anon, authenticated, service_role;

-- 등록: owner 만, 운영 적격 clip 만, 이미 있는 (sample, clip) 은 무시. 새로 들어간 수를 돌려준다.
CREATE FUNCTION public.fn_register_eval_sample(p_sample_id text, p_items jsonb, p_actor uuid, p_is_owner boolean)
RETURNS integer
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_n integer := 0;
  v_item jsonb;
  v_clip uuid;
BEGIN
  IF NOT coalesce(p_is_owner, false) THEN
    RAISE EXCEPTION 'owner only' USING ERRCODE = 'PT403';
  END IF;
  IF p_sample_id IS NULL OR p_sample_id !~ '^[a-z0-9-]{3,40}$' THEN
    RAISE EXCEPTION 'invalid sample id' USING ERRCODE = '22023';
  END IF;
  IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array' THEN
    RAISE EXCEPTION 'items must be a JSON array' USING ERRCODE = '22023';
  END IF;
  FOR v_item IN SELECT * FROM jsonb_array_elements(p_items) LOOP
    BEGIN
      v_clip := (v_item->>'clip_id')::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
      RAISE EXCEPTION 'invalid clip id in items' USING ERRCODE = '22023';
    END;
    IF NOT public.fn_is_motion_clip_production_labeling_eligible(v_clip) THEN CONTINUE; END IF;
    INSERT INTO public.motion_clip_eval_samples (sample_id, clip_id, stratum, registered_by)
    VALUES (p_sample_id, v_clip, coalesce(v_item->>'stratum', '?'), p_actor)
    ON CONFLICT DO NOTHING;
    IF FOUND THEN v_n := v_n + 1; END IF;
  END LOOP;
  RETURN v_n;
END $$;

-- 진행: 표본 전체 / 사람 initial 확정 수.
CREATE FUNCTION public.fn_eval_sample_progress(p_sample_id text)
RETURNS TABLE (total bigint, labeled bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT count(*)::bigint,
         count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM public.motion_clip_highlight_verdicts v WHERE v.clip_id = s.clip_id AND v.kind = 'initial'))::bigint
    FROM public.motion_clip_eval_samples s
   WHERE s.sample_id = p_sample_id;
$$;

-- 보고: 층별 n · 확정 · 규칙 initial O · 사람 O · 4분할(최초 initial verdict 기준).
CREATE FUNCTION public.fn_eval_sample_report(p_sample_id text)
RETURNS TABLE (stratum text, total bigint, labeled bigint, rule_o bigint, human_o bigint, o_to_o bigint, o_to_x bigint, x_to_o bigint, x_to_x bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT s.stratum, count(*)::bigint, count(v.id)::bigint,
         count(*) FILTER (WHERE v.initial = true)::bigint,
         count(*) FILTER (WHERE v.verdict = true)::bigint,
         count(*) FILTER (WHERE v.initial = true AND v.verdict = true)::bigint,
         count(*) FILTER (WHERE v.initial = true AND v.verdict = false)::bigint,
         count(*) FILTER (WHERE v.initial = false AND v.verdict = true)::bigint,
         count(*) FILTER (WHERE v.initial = false AND v.verdict = false)::bigint
    FROM public.motion_clip_eval_samples s
    LEFT JOIN public.motion_clip_highlight_verdicts v ON v.clip_id = s.clip_id AND v.kind = 'initial'
   WHERE s.sample_id = p_sample_id
   GROUP BY s.stratum
   ORDER BY s.stratum;
$$;

-- 목록: 2026-09-09_labeling_v4_behavior_flags.sql 의 13-인자 본문 + p_sample_id 필터(프로그램 변환).
CREATE FUNCTION public.fn_list_labeling_v4_clips(
  p_viewer_id uuid,
  p_is_owner boolean,
  p_scope text,
  p_camera_ids uuid[],
  p_label_state text,
  p_highlight_state text,
  p_behavior_flag text,
  p_sample_id text,
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
  IF p_sample_id IS NOT NULL AND p_sample_id !~ '^[a-z0-9-]{3,40}$' THEN
    RAISE EXCEPTION 'invalid sample id' USING ERRCODE = '22023';
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
           -- 평가 표본 필터(2.6.1 준비 Task 1): PK 조회라 chunk 단계에서 싸게 걸러진다.
           AND (p_sample_id IS NULL
                OR EXISTS (SELECT 1 FROM public.motion_clip_eval_samples s WHERE s.sample_id = p_sample_id AND s.clip_id = c.id))
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

-- 13-인자 시그니처는 위임 wrapper 로 유지(반환 컬럼 동일).
CREATE OR REPLACE FUNCTION public.fn_list_labeling_v4_clips(
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
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT * FROM public.fn_list_labeling_v4_clips(
    p_viewer_id, p_is_owner, p_scope, p_camera_ids, p_label_state, p_highlight_state, p_behavior_flag, NULL::text,
    p_engine_schema_version, p_algorithm_version, p_detector_identity, p_cursor_started_at, p_cursor_id, p_limit);
$$;

REVOKE ALL ON FUNCTION public.fn_register_eval_sample(text, jsonb, uuid, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_register_eval_sample(text, jsonb, uuid, boolean) TO service_role;
REVOKE ALL ON FUNCTION public.fn_eval_sample_progress(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_eval_sample_progress(text) TO service_role;
REVOKE ALL ON FUNCTION public.fn_eval_sample_report(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_eval_sample_report(text) TO service_role;
REVOKE ALL ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, text, text, timestamptz, uuid, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, text, text, timestamptz, uuid, integer) TO service_role;

COMMIT;
