-- 앱 "움직임부터 재생"(owner 2026-09-11 "app에서도 움직임부터 재생하게 할까?" → 시작): 목록·대표 함수 출력에 first_moving_sec 을 더한다.
-- 값 = 활성 계약 run 의 state_intervals 중 첫 moving 구간 시작(초) — fn_highlight_rule_eval 이 이미 features.first_moving_sec 으로 계산하던 값을 그대로 노출.
-- 재생 시작점(리드 1.5초·첫 움직임 3초 이후만) 계산은 petcam-api(backend/routers/highlights.py play_from_sec)가 한다. 라벨링 웹은 overlay 로 이미 같은 동작(변경 없음).
-- 왜 DROP+CREATE 인가: RETURNS TABLE 컬럼 추가는 CREATE OR REPLACE 로 못 바꾼다. 옛 13/12-인자 wrapper 는 LANGUAGE sql `SELECT *` 라 14-인자 컬럼이 늘면 실행 시 "return type mismatch" 가 나므로 함께 다시 만든다.
-- 본문은 2026-09-11_behavior_marks.sql 과 동일(생성 스크립트로 컬럼만 패치). 규칙 params·유지율·표본과 무관.
BEGIN;

DROP FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, timestamptz, uuid, integer);
DROP FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, text, timestamptz, uuid, integer);
DROP FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, text, text, timestamptz, uuid, integer);

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
  behavior_flagged_at timestamptz,
  first_moving_sec numeric
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
  IF p_behavior_flag IS NOT NULL AND p_behavior_flag NOT IN ('yes','meaningful','wheel','fall','closeup') THEN
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
                OR EXISTS (SELECT 1 FROM public.motion_clip_behavior_flags f WHERE f.clip_id = c.id
                             AND (p_behavior_flag = 'yes' OR f.kind = p_behavior_flag)))
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
             (ev.features->>'first_moving_sec')::numeric AS ev_first,
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
        -- 표시가 영상당 여러 행(종류별)이라 집계로 1행 — 첫 표시(가장 이른 flagged_at)의 사람·시각.
        LEFT JOIN LATERAL (
          SELECT (array_agg(f.flagged_by ORDER BY f.flagged_at, f.kind))[1] AS flagged_by,
                 min(f.flagged_at) AS flagged_at
            FROM public.motion_clip_behavior_flags f WHERE f.clip_id = c.id
        ) bf ON true
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
      -- 재생 시작점 재료(앱 2026-09-11): 활성 계약 run 의 첫 moving 구간 시작(초). 사람 확정이어도 run 이 있으면 채우고, run 없으면 NULL.
      first_moving_sec := v_row.ev_first;
      RETURN NEXT;
      v_emitted := v_emitted + 1;
      EXIT WHEN v_emitted >= p_limit;
    END LOOP;
    EXIT WHEN v_emitted >= p_limit OR v_scanned < v_chunk;
  END LOOP;
END $$;

-- 13-인자 wrapper(p_sample_id 없음 — 라벨링 웹 목록이 표본 필터 없을 때 이걸 부른다). SELECT * 라 반환 컬럼이 늘면 같이 다시 만들어야 한다.
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
  behavior_flagged_at timestamptz,
  first_moving_sec numeric
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT * FROM public.fn_list_labeling_v4_clips(
    p_viewer_id, p_is_owner, p_scope, p_camera_ids, p_label_state, p_highlight_state, p_behavior_flag, NULL::text,
    p_engine_schema_version, p_algorithm_version, p_detector_identity, p_cursor_started_at, p_cursor_id, p_limit);
$$;

-- 12-인자 wrapper(petcam-api GET /highlights 가 부른다). 표시 컬럼은 빼고 first_moving_sec 만 더한다.
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
  highlight_source text,
  highlight_status text,
  highlight_value boolean,
  highlight_reason text,
  reviewer_id uuid,
  reviewer_display_name text,
  decided_at timestamptz,
  first_moving_sec numeric
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT l.clip_id, l.camera_id, l.camera_name, l.started_at, l.duration_sec, l.media_ready,
         l.highlight_source, l.highlight_status, l.highlight_value, l.highlight_reason,
         l.reviewer_id, l.reviewer_display_name, l.decided_at, l.first_moving_sec
    FROM public.fn_list_labeling_v4_clips(
      p_viewer_id, p_is_owner, p_scope, p_camera_ids, p_label_state, p_highlight_state, NULL::text,
      p_engine_schema_version, p_algorithm_version, p_detector_identity, p_cursor_started_at, p_cursor_id, p_limit) l;
$$;

-- ── 대표 함수 v0.1.2 = v0.1.1 + first_moving_sec ──
DROP FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer, integer);

CREATE FUNCTION public.fn_highlight_featured(
  p_camera_ids uuid[],
  p_from timestamptz,
  p_to timestamptz,
  p_engine_schema_version text,
  p_algorithm_version text,
  p_detector_identity text,
  p_top_n integer DEFAULT NULL,
  p_gap_sec integer DEFAULT 600,
  p_day_start_hour integer DEFAULT 20,
  p_tz text DEFAULT 'Asia/Seoul',
  p_hour_cap integer DEFAULT 3,
  p_day_cap integer DEFAULT 15               -- 하루·카메라당 대표 예산(owner 2026-09-11, 임시). NULL = 없음
) RETURNS TABLE (
  clip_id uuid,
  camera_id uuid,
  camera_name text,
  started_at timestamptz,
  duration_sec double precision,
  day_key date,
  episode_no integer,
  episode_started_at timestamptz,
  episode_ended_at timestamptz,
  episode_clip_count integer,
  episode_activity_sec numeric,
  episode_rank integer,
  episode_hour_rank integer,
  tier text,
  is_representative boolean,
  activity_sec numeric,
  highlight_source text,
  highlight_reason text,
  reviewer_id uuid,
  reviewer_display_name text,
  behavior_flagged boolean,
  behavior_kinds text[],
  first_moving_sec numeric
)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
#variable_conflict use_column
DECLARE
  v_rule record;
BEGIN
  IF p_from IS NULL OR p_to IS NULL OR p_from >= p_to THEN
    RAISE EXCEPTION 'invalid range' USING ERRCODE = '22023';
  END IF;
  IF p_to - p_from > interval '31 days' THEN
    RAISE EXCEPTION 'range too wide (max 31 days)' USING ERRCODE = '22023';
  END IF;
  IF p_top_n IS NOT NULL AND (p_top_n < 1 OR p_top_n > 50) THEN
    RAISE EXCEPTION 'invalid top_n (1..50 or null)' USING ERRCODE = '22023';
  END IF;
  IF p_hour_cap IS NOT NULL AND (p_hour_cap < 1 OR p_hour_cap > 10) THEN
    RAISE EXCEPTION 'invalid hour_cap (1..10 or null)' USING ERRCODE = '22023';
  END IF;
  IF p_day_cap IS NOT NULL AND (p_day_cap < 1 OR p_day_cap > 100) THEN
    RAISE EXCEPTION 'invalid day_cap (1..100 or null)' USING ERRCODE = '22023';
  END IF;
  IF p_gap_sec IS NULL OR p_gap_sec < 60 OR p_gap_sec > 21600 THEN
    RAISE EXCEPTION 'invalid gap_sec (60..21600)' USING ERRCODE = '22023';
  END IF;
  IF p_day_start_hour IS NULL OR p_day_start_hour < 0 OR p_day_start_hour > 23 THEN
    RAISE EXCEPTION 'invalid day_start_hour (0..23)' USING ERRCODE = '22023';
  END IF;
  IF p_tz IS NULL THEN
    RAISE EXCEPTION 'invalid time zone' USING ERRCODE = '22023';
  END IF;
  SELECT * INTO v_rule FROM public.fn_get_active_highlight_rule();
  IF v_rule.version IS NULL THEN
    RAISE EXCEPTION 'no active highlight rule' USING ERRCODE = 'PT428';
  END IF;

  RETURN QUERY
  WITH base AS (
    SELECT c.id AS clip_id, c.camera_id, coalesce(cam.name, c.camera_id::text) AS camera_name,
           c.started_at, c.duration_sec,
           vd.verdict AS human_verdict, vd.initial_reason AS human_reason,
           vd.reviewer_id, la.display_name AS reviewer_display_name,
           ev.initial AS rule_initial, ev.reason AS rule_reason,
           (ev.features->>'activity_sec')::numeric AS activity_sec,
           (ev.features->>'first_moving_sec')::numeric AS first_moving_sec,
           -- 1위 승격 = 의미있는 행동·쳇바퀴·📸 중 하나라도(추락은 수집용이라 제외).
           -- kinds 가 NULL(표시 없음)이면 && 도 NULL → ORDER BY DESC 에서 true 보다 앞서므로 반드시 false 로.
           coalesce(bf.kinds && ARRAY['meaningful','wheel','closeup'], false) AS flagged,
           coalesce(bf.kinds, '{}'::text[]) AS kinds
      FROM public.motion_clips c
      LEFT JOIN public.cameras cam ON cam.id = c.camera_id
      LEFT JOIN LATERAL (
        SELECT v.verdict, v.initial_reason, v.reviewer_id
          FROM public.motion_clip_highlight_verdicts v
         WHERE v.clip_id = c.id ORDER BY v.created_at DESC, v.id DESC LIMIT 1
      ) vd ON true
      LEFT JOIN public.labeler_applications la ON la.user_id = vd.reviewer_id
      LEFT JOIN LATERAL (
        SELECT array_agg(f.kind ORDER BY array_position(ARRAY['meaningful','wheel','fall','closeup'], f.kind)) AS kinds
          FROM public.motion_clip_behavior_flags f WHERE f.clip_id = c.id
      ) bf ON true
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
      -- composite IS NOT NULL 함정: run_row 가 아니라 run_id 로 존재 판정(목록 함수와 동일).
      LEFT JOIN LATERAL public.fn_highlight_rule_eval(rr.run_row, v_rule.params) ev ON rr.run_id IS NOT NULL
     WHERE c.started_at >= p_from AND c.started_at < p_to
       AND c.r2_key IS NOT NULL
       AND (p_camera_ids IS NULL OR c.camera_id = ANY (p_camera_ids))
       AND public.fn_is_motion_clip_production_labeling_eligible(c.id)
       AND NOT EXISTS (SELECT 1 FROM public.motion_clip_system_exclusions x
                        WHERE x.clip_id = c.id AND x.state = 'media_deleted')
  ),
  cur AS (
    SELECT b.*, coalesce(b.human_verdict, b.rule_initial) AS current_value,
           ((b.started_at AT TIME ZONE p_tz) - make_interval(hours => p_day_start_hour))::date AS day_key
      FROM base b
  ),
  o AS (SELECT * FROM cur WHERE current_value IS TRUE),
  gaps AS (
    SELECT o.*,
           CASE WHEN lag(o.started_at + make_interval(secs => coalesce(o.duration_sec, 60))) OVER w IS NULL
                  OR o.started_at - lag(o.started_at + make_interval(secs => coalesce(o.duration_sec, 60))) OVER w
                     > make_interval(secs => p_gap_sec)
                THEN 1 ELSE 0 END AS is_new
      FROM o
    WINDOW w AS (PARTITION BY o.camera_id, o.day_key ORDER BY o.started_at, o.clip_id)
  ),
  ep AS (
    SELECT g.*,
           sum(g.is_new) OVER (PARTITION BY g.camera_id, g.day_key ORDER BY g.started_at, g.clip_id
                               ROWS UNBOUNDED PRECEDING)::integer AS episode_no
      FROM gaps g
  ),
  agg AS (
    SELECT e.camera_id, e.day_key, e.episode_no,
           min(e.started_at) AS ep_start,
           max(e.started_at + make_interval(secs => coalesce(e.duration_sec, 60))) AS ep_end,
           count(*)::integer AS ep_count,
           sum(coalesce(e.activity_sec, 0)) AS ep_activity,
           bool_or(e.flagged) AS ep_flagged,
           bool_or(e.human_verdict IS TRUE) AS ep_human_o
      FROM ep e
     GROUP BY e.camera_id, e.day_key, e.episode_no
  ),
  ranked AS (
    SELECT a.*,
           row_number() OVER (PARTITION BY a.camera_id, a.day_key
                              ORDER BY a.ep_flagged DESC, a.ep_human_o DESC, a.ep_activity DESC, a.ep_start DESC)::integer AS ep_rank
      FROM agg a
  ),
  rep AS (
    SELECT t.camera_id, t.day_key, t.episode_no, t.clip_id AS rep_clip_id, t.started_at AS rep_started_at
      FROM (SELECT e.*,
                   row_number() OVER (PARTITION BY e.camera_id, e.day_key, e.episode_no
                                      ORDER BY e.flagged DESC, (e.human_verdict IS TRUE) DESC,
                                               e.activity_sec DESC NULLS LAST, e.started_at ASC) AS rn
              FROM ep e) t
     WHERE t.rn = 1
  ),
  -- 시간대 상한: 대표 클립의 KST 시(hour) 안에서 사건 순위(ep_rank) 순으로 다시 번호를 매긴다.
  hour_ranked AS (
    SELECT r.*, p.rep_clip_id,
           row_number() OVER (PARTITION BY r.camera_id, r.day_key,
                                           extract(hour FROM (p.rep_started_at AT TIME ZONE p_tz))
                              ORDER BY r.ep_rank)::integer AS hour_rank
      FROM ranked r
      JOIN rep p ON p.camera_id = r.camera_id AND p.day_key = r.day_key AND p.episode_no = r.episode_no
  ),
  -- 하루 예산: 시간당 상한을 통과한 사건만 사건 순위로 다시 세어 p_day_cap 까지(상한에 걸린 사건은 예산을 안 먹음).
  day_ranked AS (
    SELECT h.*,
           row_number() OVER (PARTITION BY h.camera_id, h.day_key, (p_hour_cap IS NULL OR h.hour_rank <= p_hour_cap)
                              ORDER BY h.ep_rank)::integer AS day_rank
      FROM hour_ranked h
  )
  SELECT e.clip_id, e.camera_id, e.camera_name, e.started_at, e.duration_sec, e.day_key, e.episode_no,
         h.ep_start, h.ep_end, h.ep_count, round(h.ep_activity, 1), h.ep_rank, h.hour_rank,
         CASE WHEN h.rep_clip_id = e.clip_id
                   AND (p_top_n IS NULL OR h.ep_rank <= p_top_n)
                   AND (p_hour_cap IS NULL OR h.hour_rank <= p_hour_cap)
                   AND (p_day_cap IS NULL OR h.day_rank <= p_day_cap)
              THEN 'featured' ELSE 'candidate' END,
         (h.rep_clip_id = e.clip_id),
         round(coalesce(e.activity_sec, 0), 1),
         CASE WHEN e.human_verdict IS NOT NULL THEN 'human' ELSE 'rule' END,
         coalesce(e.human_reason, e.rule_reason, ''),
         e.reviewer_id, e.reviewer_display_name, e.flagged, e.kinds, e.first_moving_sec
    FROM ep e
    JOIN day_ranked h ON h.camera_id = e.camera_id AND h.day_key = e.day_key AND h.episode_no = e.episode_no
   ORDER BY e.day_key DESC, e.camera_id, h.ep_rank ASC, e.started_at DESC;
END $$;

REVOKE ALL ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, text, text, timestamptz, uuid, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, text, text, timestamptz, uuid, integer) TO service_role;
REVOKE ALL ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, text, timestamptz, uuid, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, text, timestamptz, uuid, integer) TO service_role;
REVOKE ALL ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, timestamptz, uuid, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_labeling_v4_clips(uuid, boolean, text, uuid[], text, text, text, text, text, timestamptz, uuid, integer) TO service_role;
REVOKE ALL ON FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer, integer) TO service_role;

COMMIT;
