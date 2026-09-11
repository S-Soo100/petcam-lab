-- 행동 표시 4종 — 의미있는 행동(meaningful) · 쳇바퀴(wheel) · 추락(fall) · 예쁘게 나옴(closeup). owner 확정 2026-09-11(스펙 feature-behavior-marks §0·§0b, 계획서 v3 1단계).
-- ✨ 하나(종류 없음)를 종류 있는 표시로 넓힌다. 옛 행은 전부 meaningful. 영상당 종류별 1개, 종류끼리 독립. 미표시 = 미확인(음성 아님).
-- 쳇바퀴 = "제자리 활동" 정답 세트, 추락 = 수집용(대표 선정 무관), closeup = 자동 클로즈업(파생 지표) 검증용. O/X·유지율과 무관(런북 §6.x).
-- ⚠️ 영상당 여러 행이 되므로 목록·대표 함수의 bf 조인을 LATERAL 집계로 바꿔 행 중복을 막는다(둘 다 이 migration 안에서).
-- 대표 함수 v0.1.1 = v0.1 + 표시 집계(flagged = meaningful|wheel|closeup 중 하나, 추락 제외) + 하루·카메라당 예산 p_day_cap(owner 2026-09-11: 15, 임시).
BEGIN;

ALTER TABLE public.motion_clip_behavior_flags
  ADD COLUMN kind text NOT NULL DEFAULT 'meaningful' CHECK (kind IN ('meaningful','wheel','fall','closeup'));
ALTER TABLE public.motion_clip_behavior_flags DROP CONSTRAINT motion_clip_behavior_flags_pkey;
ALTER TABLE public.motion_clip_behavior_flags ADD PRIMARY KEY (clip_id, kind);
CREATE INDEX idx_motion_clip_behavior_flags_kind ON public.motion_clip_behavior_flags (kind, flagged_at DESC);

-- 종류별 4행(항상). 없는 종류는 flagged=false.
CREATE FUNCTION public.fn_get_motion_clip_behavior_flags(p_clip_id uuid)
RETURNS TABLE (kind text, flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT k.kind, (f.clip_id IS NOT NULL) AS flagged, f.flagged_by, la.display_name, f.flagged_at
    FROM (VALUES ('meaningful'), ('wheel'), ('fall'), ('closeup')) AS k(kind)
    LEFT JOIN public.motion_clip_behavior_flags f ON f.clip_id = p_clip_id AND f.kind = k.kind
    LEFT JOIN public.labeler_applications la ON la.user_id = f.flagged_by
   ORDER BY array_position(ARRAY['meaningful','wheel','fall','closeup'], k.kind);
$$;

-- 옛 단일 get = meaningful 만(구버전 웹·테스트 호환).
CREATE OR REPLACE FUNCTION public.fn_get_motion_clip_behavior_flag(p_clip_id uuid)
RETURNS TABLE (flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT (f.clip_id IS NOT NULL) AS flagged, f.flagged_by, la.display_name, f.flagged_at
    FROM (SELECT p_clip_id AS id) x
    LEFT JOIN public.motion_clip_behavior_flags f ON f.clip_id = x.id AND f.kind = 'meaningful'
    LEFT JOIN public.labeler_applications la ON la.user_id = f.flagged_by;
$$;

CREATE FUNCTION public.fn_set_motion_clip_behavior_flag(
  p_clip_id uuid, p_user_id uuid, p_is_owner boolean, p_kind text, p_flagged boolean
) RETURNS TABLE (kind text, flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
#variable_conflict use_column
DECLARE
  v_existing_by uuid;
BEGIN
  IF p_clip_id IS NULL OR p_user_id IS NULL OR p_flagged IS NULL THEN
    RAISE EXCEPTION 'invalid arguments' USING ERRCODE = '22023';
  END IF;
  IF p_kind IS NULL OR p_kind NOT IN ('meaningful','wheel','fall','closeup') THEN
    RAISE EXCEPTION 'invalid kind' USING ERRCODE = '22023';
  END IF;
  IF NOT public.fn_is_motion_clip_production_labeling_eligible(p_clip_id) THEN
    RAISE EXCEPTION 'motion clip not found' USING ERRCODE = 'P0002';
  END IF;
  IF p_flagged THEN
    INSERT INTO public.motion_clip_behavior_flags (clip_id, kind, flagged_by)
    VALUES (p_clip_id, p_kind, p_user_id)
    ON CONFLICT (clip_id, kind) DO NOTHING;  -- 첫 체크한 사람 유지(멱등)
  ELSE
    SELECT f.flagged_by INTO v_existing_by FROM public.motion_clip_behavior_flags f WHERE f.clip_id = p_clip_id AND f.kind = p_kind;
    IF v_existing_by IS NOT NULL AND v_existing_by <> p_user_id AND NOT coalesce(p_is_owner, false) THEN
      RAISE EXCEPTION 'only the flagger or owner can unflag' USING ERRCODE = 'PT403';
    END IF;
    DELETE FROM public.motion_clip_behavior_flags f WHERE f.clip_id = p_clip_id AND f.kind = p_kind;
  END IF;
  RETURN QUERY SELECT * FROM public.fn_get_motion_clip_behavior_flags(p_clip_id);
END $$;

-- 옛 4-인자 set = meaningful 위임(반환 모양은 옛 그대로 1행). 웹 구버전이 migration 뒤에도 동작.
CREATE OR REPLACE FUNCTION public.fn_set_motion_clip_behavior_flag(
  p_clip_id uuid, p_user_id uuid, p_is_owner boolean, p_flagged boolean
) RETURNS TABLE (flagged boolean, flagged_by uuid, flagged_by_display_name text, flagged_at timestamptz)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = '' AS $$
  SELECT r.flagged, r.flagged_by, r.flagged_by_display_name, r.flagged_at
    FROM public.fn_set_motion_clip_behavior_flag(p_clip_id, p_user_id, p_is_owner, 'meaningful', p_flagged) r
   WHERE r.kind = 'meaningful';
$$;

-- 목록 카드 배지용 배치 조회(웹이 페이지 항목 id 로 한 번).
CREATE FUNCTION public.fn_get_motion_clip_behavior_kinds(p_clip_ids uuid[])
RETURNS TABLE (clip_id uuid, kinds text[])
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT f.clip_id, array_agg(f.kind ORDER BY array_position(ARRAY['meaningful','wheel','fall','closeup'], f.kind)) AS kinds
    FROM public.motion_clip_behavior_flags f
   WHERE f.clip_id = ANY (p_clip_ids)
   GROUP BY f.clip_id;
$$;

REVOKE ALL ON FUNCTION public.fn_get_motion_clip_behavior_flags(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_motion_clip_behavior_flags(uuid) TO service_role;
REVOKE ALL ON FUNCTION public.fn_set_motion_clip_behavior_flag(uuid, uuid, boolean, text, boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_set_motion_clip_behavior_flag(uuid, uuid, boolean, text, boolean) TO service_role;
REVOKE ALL ON FUNCTION public.fn_get_motion_clip_behavior_kinds(uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_motion_clip_behavior_kinds(uuid[]) TO service_role;

-- ── 목록 14-인자: 2026-09-09_labeling_v4_eval_samples.sql 본문 + 종류 필터 + bf 집계(프로그램 변환, 반환 타입 불변 → 13/12-인자 wrapper 무변경) ──
CREATE OR REPLACE FUNCTION public.fn_list_labeling_v4_clips(
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
      RETURN NEXT;
      v_emitted := v_emitted + 1;
      EXIT WHEN v_emitted >= p_limit;
    END LOOP;
    EXIT WHEN v_emitted >= p_limit OR v_scanned < v_chunk;
  END LOOP;
END $$;

-- ── 대표 함수 v0.1.1 = v0.1(2026-09-11_highlight_featured_hour_cap) + 표시 집계 + 하루 예산 p_day_cap ──
DROP FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer);

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
  behavior_kinds text[]
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
         e.reviewer_id, e.reviewer_display_name, e.flagged, e.kinds
    FROM ep e
    JOIN day_ranked h ON h.camera_id = e.camera_id AND h.day_key = e.day_key AND h.episode_no = e.episode_no
   ORDER BY e.day_key DESC, e.camera_id, h.ep_rank ASC, e.started_at DESC;
END $$;

REVOKE ALL ON FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer, integer) TO service_role;

COMMIT;
