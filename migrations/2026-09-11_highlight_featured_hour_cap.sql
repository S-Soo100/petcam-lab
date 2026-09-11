-- ⭐ 대표 tier v0.1 — owner 결정 2026-09-11: "10분 묶기 + 시간당 3개, 하루 상한 없음"(실측 주 카메라 하룻밤 11개·최대 16).
-- 2026-09-10 함수(30분 묶기·하루 3개)를 같은 이름으로 교체한다: p_hour_cap 인자 추가, 기본값 p_gap_sec 1800→600,
-- p_top_n 3→NULL(하루 상한 없음), 출력에 episode_hour_rank 추가. RETURNS TABLE 이 바뀌므로 DROP 뒤 CREATE(한 트랜잭션).
-- PostgREST 호출자(petcam-api·라벨링 웹)는 이름 인자로 부르므로 p_hour_cap 을 안 넘기면 기본값 3 이 적용된다(배포 순서 무관).
--   tier = 대표 클립 이고 (하루 순위 ≤ p_top_n 또는 p_top_n NULL) 이고 (같은 시간대(KST 시) 안 순위 ≤ p_hour_cap 또는 NULL) 이면 'featured'
--   시간대 = 대표 클립 started_at 의 KST 시(hour). 사건 순위 정렬은 그대로(✨ > 사람 O > activity 합 > 최신).
BEGIN;

DROP FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text);

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
  p_hour_cap integer DEFAULT 3
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
  behavior_flagged boolean
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
           (bf.clip_id IS NOT NULL) AS flagged
      FROM public.motion_clips c
      LEFT JOIN public.cameras cam ON cam.id = c.camera_id
      LEFT JOIN LATERAL (
        SELECT v.verdict, v.initial_reason, v.reviewer_id
          FROM public.motion_clip_highlight_verdicts v
         WHERE v.clip_id = c.id ORDER BY v.created_at DESC, v.id DESC LIMIT 1
      ) vd ON true
      LEFT JOIN public.labeler_applications la ON la.user_id = vd.reviewer_id
      LEFT JOIN public.motion_clip_behavior_flags bf ON bf.clip_id = c.id
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
  )
  SELECT e.clip_id, e.camera_id, e.camera_name, e.started_at, e.duration_sec, e.day_key, e.episode_no,
         h.ep_start, h.ep_end, h.ep_count, round(h.ep_activity, 1), h.ep_rank, h.hour_rank,
         CASE WHEN h.rep_clip_id = e.clip_id
                   AND (p_top_n IS NULL OR h.ep_rank <= p_top_n)
                   AND (p_hour_cap IS NULL OR h.hour_rank <= p_hour_cap)
              THEN 'featured' ELSE 'candidate' END,
         (h.rep_clip_id = e.clip_id),
         round(coalesce(e.activity_sec, 0), 1),
         CASE WHEN e.human_verdict IS NOT NULL THEN 'human' ELSE 'rule' END,
         coalesce(e.human_reason, e.rule_reason, ''),
         e.reviewer_id, e.reviewer_display_name, e.flagged
    FROM ep e
    JOIN hour_ranked h ON h.camera_id = e.camera_id AND h.day_key = e.day_key AND h.episode_no = e.episode_no
   ORDER BY e.day_key DESC, e.camera_id, h.ep_rank ASC, e.started_at DESC;
END $$;

REVOKE ALL ON FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_highlight_featured(uuid[], timestamptz, timestamptz, text, text, text, integer, integer, integer, text, integer) TO service_role;

COMMIT;
