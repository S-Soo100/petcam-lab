-- fn_list_labeling_v4_clips 성능 수정 (production EXPLAIN 2026-09-07):
-- 원래 함수는 LATERAL(최신 verdict·exact GME run·규칙 eval)을 전체 적격 영상(~2.2만)에 먼저 돌린 뒤
-- ORDER BY … LIMIT 을 적용해 페이지 하나에 statement timeout 이 났다.
-- 여기서는 keyset 순서(부분 인덱스 idx_motion_clips_library_started)로 200개씩 끊어 읽고,
-- 그 chunk 에만 자격 가드·LATERAL·필터를 적용해 p_limit 만큼 모이면 멈춘다.
-- 시그니처·반환 컬럼·정렬·필터 의미는 2026-09-08_labeling_v4_simplification.sql 과 동일.
BEGIN;

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
                        AND j.algorithm_version = p_algorithm_version AND j.status = 'failed_terminal') AS r_failed
        FROM chunk c
        LEFT JOIN public.cameras cam ON cam.id = c.camera_id
        LEFT JOIN LATERAL (
          SELECT v.* FROM public.motion_clip_highlight_verdicts v
           WHERE v.clip_id = c.id ORDER BY v.created_at DESC, v.id DESC LIMIT 1
        ) vd ON true
        LEFT JOIN public.labeler_applications la ON la.user_id = vd.reviewer_id
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
      RETURN NEXT;
      v_emitted := v_emitted + 1;
      EXIT WHEN v_emitted >= p_limit;
    END LOOP;
    EXIT WHEN v_emitted >= p_limit OR v_scanned < v_chunk;
  END LOOP;
END $$;

COMMIT;
