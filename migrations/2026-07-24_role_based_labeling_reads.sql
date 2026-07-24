-- role-based labeling web read models — forward-only, read-only RPC.
-- 기존 2026-07-22/23 migration은 수정하지 않는다.
--
-- 설계 정본: docs/superpowers/specs/2026-07-24-role-based-labeling-web-design.md
-- 구현계획:   docs/superpowers/plans/2026-07-24-role-based-labeling-web.md Task 2
--
-- 왜 SECURITY INVOKER + search_path='' 인가(설계 §10): 세 함수 모두 순수 읽기 전용이고, Next.js
--   API 가 bearer 인증 + 역할 판정 뒤 service_role 로만 호출한다. service_role 만 EXECUTE 를 받고,
--   빈 search_path 로 모든 참조를 public. 로 스키마 한정해 search_path 오염을 막는다. 세 함수의
--   본문은 READ/END-READ 마커 주석으로 감싸 write 문이 없음을 정적으로 감사한다
--   (tests/test_role_based_labeling_reads_migration.py).
--
-- 왜 확정 전 라벨을 숨기나(설계 §6·Global Constraints): 영상 보관함(library)은 consensus 가
--   agreed/owner_resolved 인 새 blind 라벨과 기존 단일/Owner legacy 라벨만 최종으로 공개한다.
--   awaiting/conflict 는 개별 답과 GT 를 숨기고 상태 문자열(awaiting/owner_review)만 노출한다.
--
-- ⏳ production 미적용. 구현·테스트 후 owner 검토 경계에서 멈춘다(Preview Deployment Gate).
--   migration apply·rollback probe 실행은 이번 구현 세션 밖(owner 승인) 소관이다.

BEGIN;

-- ══════════════════════════════════════════════════════════════════
-- 1. 라벨러 개인 blind 제출 기록 (설계 §5.2) — 본인 제출만, 상대 원문 0
-- ══════════════════════════════════════════════════════════════════
-- reviewer 본인의 immutable 제출을 최신순 keyset 으로 반환한다. 상대 제출·digest·reviewer UUID·
-- lease 는 컬럼조차 반환하지 않는다. final_status 는 consensus 상태 한 단어만(개별 답 비노출).
-- READ FUNCTION BODY
CREATE OR REPLACE FUNCTION public.fn_list_motion_blind_history(
  p_reviewer_id uuid,
  p_cursor_submitted_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_decision text DEFAULT NULL,
  p_camera_ids uuid[] DEFAULT NULL,
  p_date_from timestamptz DEFAULT NULL,
  p_date_to timestamptz DEFAULT NULL,
  p_cohort_kind text DEFAULT NULL,
  p_limit integer DEFAULT 31
) RETURNS TABLE (
  submission_id uuid, clip_id uuid, camera_id uuid, camera_name text,
  started_at timestamptz, duration_sec double precision, media_ready boolean,
  submitted_at timestamptz, decision text, reason_code text,
  initial_gt jsonb, note text, cohort_kind text, final_status text
)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF p_decision IS NOT NULL AND p_decision NOT IN ('label','hold','exclude') THEN
    RAISE EXCEPTION 'invalid decision' USING ERRCODE='22023';
  END IF;
  IF p_cohort_kind IS NOT NULL AND p_cohort_kind NOT IN ('live','canary') THEN
    RAISE EXCEPTION 'invalid cohort kind' USING ERRCODE='22023';
  END IF;
  IF (p_cursor_submitted_at IS NULL) <> (p_cursor_id IS NULL) THEN
    RAISE EXCEPTION 'cursor requires both fields' USING ERRCODE='22023';
  END IF;
  RETURN QUERY
  SELECT s.id, s.clip_id, m.camera_id, cam.name, m.started_at, m.duration_sec,
         m.r2_key IS NOT NULL, s.submitted_at, s.decision, s.reason_code,
         s.initial_gt, s.note, s.cohort_kind, c.status
  FROM public.motion_clip_blind_submissions s
  JOIN public.motion_clips m ON m.id=s.clip_id
  LEFT JOIN public.cameras cam ON cam.id=m.camera_id
  LEFT JOIN public.motion_clip_consensus c
    ON c.clip_id=s.clip_id AND c.cohort_kind=s.cohort_kind
   AND c.cohort_id IS NOT DISTINCT FROM s.cohort_id
  WHERE s.reviewer_id=p_reviewer_id
    AND (p_decision IS NULL OR s.decision=p_decision)
    AND (p_camera_ids IS NULL OR m.camera_id=ANY(p_camera_ids))
    AND (p_date_from IS NULL OR m.started_at>=p_date_from)
    AND (p_date_to IS NULL OR m.started_at<=p_date_to)
    AND (p_cohort_kind IS NULL OR s.cohort_kind=p_cohort_kind)
    AND (p_cursor_submitted_at IS NULL OR s.submitted_at<p_cursor_submitted_at
      OR (s.submitted_at=p_cursor_submitted_at AND s.id<p_cursor_id))
  ORDER BY s.submitted_at DESC, s.id DESC
  LIMIT LEAST(GREATEST(p_limit,1),100);
END;
$$;
-- END READ FUNCTION BODY

-- ══════════════════════════════════════════════════════════════════
-- 2. 공용 읽기 전용 영상 보관함 (설계 §5.3·§6) — 모든 카메라, 확정 라벨만
-- ══════════════════════════════════════════════════════════════════
-- R2 재생 가능한 clip 전부(그룹 필터 없음). label_state/source 는 CTE classified 에서 고정 분류.
-- agreed/owner_resolved 와 legacy 만 최종 라벨/GT 를 공개하고, awaiting/conflict 는 상태만 노출한다.
-- READ FUNCTION BODY
CREATE OR REPLACE FUNCTION public.fn_list_motion_labeling_library(
  p_owner_id uuid,
  p_clip_id uuid DEFAULT NULL,
  p_label_state text DEFAULT NULL,
  p_camera_ids uuid[] DEFAULT NULL,
  p_date_from timestamptz DEFAULT NULL,
  p_date_to timestamptz DEFAULT NULL,
  p_time_from text DEFAULT NULL,
  p_time_to text DEFAULT NULL,
  p_label_source text DEFAULT NULL,
  p_cursor_started_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 31
) RETURNS TABLE (
  clip_id uuid, camera_id uuid, camera_name text, started_at timestamptz,
  duration_sec double precision, label_state text, label_source text,
  final_decision text, final_gt jsonb
)
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  IF p_label_state IS NOT NULL
     AND p_label_state NOT IN ('final','awaiting','owner_review','unlabeled') THEN
    RAISE EXCEPTION 'invalid label state' USING ERRCODE='22023';
  END IF;
  IF p_label_source IS NOT NULL
     AND p_label_source NOT IN ('blind_consensus','owner_legacy','single_legacy','none') THEN
    RAISE EXCEPTION 'invalid label source' USING ERRCODE='22023';
  END IF;
  IF (p_cursor_started_at IS NULL) <> (p_cursor_id IS NULL) THEN
    RAISE EXCEPTION 'cursor requires both fields' USING ERRCODE='22023';
  END IF;
  IF (p_time_from IS NULL) <> (p_time_to IS NULL)
     OR (p_time_from IS NOT NULL AND p_time_from !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$')
     OR (p_time_to IS NOT NULL AND p_time_to !~ '^([01][0-9]|2[0-3]):[0-5][0-9]$') THEN
    RAISE EXCEPTION 'invalid time range' USING ERRCODE='22023';
  END IF;

  RETURN QUERY
  WITH base AS (
    SELECT m.id, m.camera_id, cam.name AS camera_name, m.started_at, m.duration_sec,
           bc.status AS consensus_status, bc.final_decision AS consensus_decision,
           bc.final_gt AS consensus_gt,
           ls.reviewed_by AS legacy_reviewer, ls.legacy_gt
    FROM public.motion_clips m
    LEFT JOIN public.cameras cam ON cam.id=m.camera_id
    LEFT JOIN public.motion_clip_consensus bc
      ON bc.clip_id=m.id AND bc.cohort_kind='live'
    LEFT JOIN LATERAL (
      SELECT s.reviewed_by, COALESCE(s.current_gt,s.initial_gt) AS legacy_gt
      FROM public.motion_clip_labeling_sessions s
      WHERE s.clip_id=m.id AND s.initial_gt IS NOT NULL
      ORDER BY (s.reviewed_by=p_owner_id) DESC, s.updated_at DESC, s.id DESC
      LIMIT 1
    ) ls ON true
    WHERE m.r2_key IS NOT NULL
      AND (p_clip_id IS NULL OR m.id=p_clip_id)
      AND (p_camera_ids IS NULL OR m.camera_id=ANY(p_camera_ids))
      AND (p_date_from IS NULL OR m.started_at>=p_date_from)
      AND (p_date_to IS NULL OR m.started_at<=p_date_to)
      AND (
        p_time_from IS NULL
        OR (
          p_time_from<=p_time_to
          AND to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI')
              BETWEEN p_time_from AND p_time_to
        )
        OR (
          p_time_from>p_time_to
          AND (
            to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI')>=p_time_from
            OR to_char(m.started_at AT TIME ZONE 'Asia/Seoul','HH24:MI')<=p_time_to
          )
        )
      )
  ), classified AS (
    SELECT base.*,
      CASE
        WHEN consensus_status IN ('agreed','owner_resolved') THEN 'final'
        WHEN consensus_status = 'conflict' THEN 'owner_review'
        WHEN consensus_status = 'awaiting' THEN 'awaiting'
        WHEN legacy_gt IS NOT NULL THEN 'final'
        ELSE 'unlabeled'
      END AS public_state,
      CASE
        WHEN consensus_status IS NOT NULL THEN 'blind_consensus'
        WHEN legacy_gt IS NOT NULL AND legacy_reviewer=p_owner_id THEN 'owner_legacy'
        WHEN legacy_gt IS NOT NULL THEN 'single_legacy'
        ELSE 'none'
      END AS public_source,
      CASE
        WHEN consensus_status IN ('agreed','owner_resolved') THEN consensus_decision
        WHEN consensus_status IS NULL AND legacy_gt IS NOT NULL THEN 'label'
        ELSE NULL::text
      END AS public_decision,
      CASE
        WHEN consensus_status IN ('agreed','owner_resolved') THEN consensus_gt
        WHEN consensus_status IS NULL AND legacy_gt IS NOT NULL THEN legacy_gt
        ELSE NULL::jsonb
      END AS public_gt
    FROM base
  )
  SELECT id, camera_id, camera_name, started_at, duration_sec,
         public_state, public_source, public_decision, public_gt
  FROM classified
  WHERE (p_label_state IS NULL OR public_state=p_label_state)
    AND (p_label_source IS NULL OR public_source=p_label_source)
    AND (p_cursor_started_at IS NULL OR started_at<p_cursor_started_at
      OR (started_at=p_cursor_started_at AND id<p_cursor_id))
  ORDER BY started_at DESC, id DESC
  LIMIT LEAST(GREATEST(p_limit,1),100);
END;
$$;
-- END READ FUNCTION BODY

-- ══════════════════════════════════════════════════════════════════
-- 3. Owner 운영 현황 (설계 §7.1·§8) — 집계만, 제출 원문·이메일·UUID 비노출
-- ══════════════════════════════════════════════════════════════════
-- 그룹별 제출률·불일치/대기/합의 수 + 열린 canary 현황을 JSON 한 행으로 반환한다. 라벨러는
-- display_name(없으면 '라벨러')과 완료 수만 노출한다. reviewer UUID·이메일·개별 제출 body 는 없다.
-- READ FUNCTION BODY
CREATE OR REPLACE FUNCTION public.fn_get_motion_blind_owner_overview(
  p_activity_day date
) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path = '' AS $$
  SELECT jsonb_build_object(
    'activity_day', p_activity_day,
    'groups', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'group_id', g.id, 'group_name', g.name,
        'clip_total', (SELECT count(DISTINCT s.clip_id) FROM public.motion_clip_review_slots s
          WHERE s.group_id=g.id AND s.cohort_kind='live' AND s.activity_day_kst=p_activity_day),
        'members', (SELECT COALESCE(jsonb_agg(jsonb_build_object(
          'display_name', COALESCE(a.display_name,'라벨러'),
          'submitted_count', (SELECT count(*) FROM public.motion_clip_review_slots s2
            WHERE s2.group_id=g.id AND s2.reviewer_id=gm.user_id
              AND s2.cohort_kind='live' AND s2.activity_day_kst=p_activity_day
              AND s2.submitted_at IS NOT NULL)
        ) ORDER BY gm.user_id),'[]'::jsonb)
          FROM public.motion_labeling_review_group_members gm
          LEFT JOIN public.labeler_applications a ON a.user_id=gm.user_id
          WHERE gm.group_id=g.id AND gm.ended_at IS NULL),
        'agreed_count', (SELECT count(*) FROM public.motion_clip_consensus c
          WHERE c.group_id=g.id AND c.cohort_kind='live' AND c.status='agreed'
            AND EXISTS (SELECT 1 FROM public.motion_clip_review_slots x
              WHERE x.clip_id=c.clip_id AND x.activity_day_kst=p_activity_day)),
        'conflict_count', (SELECT count(*) FROM public.motion_clip_consensus c
          WHERE c.group_id=g.id AND c.cohort_kind='live' AND c.status='conflict'
            AND EXISTS (SELECT 1 FROM public.motion_clip_review_slots x
              WHERE x.clip_id=c.clip_id AND x.activity_day_kst=p_activity_day)),
        'awaiting_count', (SELECT count(*) FROM public.motion_clip_consensus c
          WHERE c.group_id=g.id AND c.cohort_kind='live' AND c.status='awaiting'
            AND EXISTS (SELECT 1 FROM public.motion_clip_review_slots x
              WHERE x.clip_id=c.clip_id AND x.activity_day_kst=p_activity_day))
      ) ORDER BY g.name)
      FROM public.motion_labeling_review_groups g WHERE g.active
    ), '[]'::jsonb),
    'open_canaries', COALESCE((
      SELECT jsonb_agg(jsonb_build_object(
        'cohort_id', c.id, 'label', c.label, 'group_id', c.group_id,
        'clip_total', (SELECT count(DISTINCT s.clip_id) FROM public.motion_clip_review_slots s
          WHERE s.cohort_id=c.id),
        'submitted_total', (SELECT count(*) FROM public.motion_clip_review_slots s
          WHERE s.cohort_id=c.id AND s.submitted_at IS NOT NULL),
        'conflict_count', (SELECT count(*) FROM public.motion_clip_consensus x
          WHERE x.cohort_id=c.id AND x.status='conflict')
      ) ORDER BY c.created_at DESC)
      FROM public.motion_blind_review_cohorts c WHERE c.status='open'
    ), '[]'::jsonb)
  );
$$;
-- END READ FUNCTION BODY

-- ══════════════════════════════════════════════════════════════════
-- 4. 인덱스 (없을 때만) — keyset 조회 지원
-- ══════════════════════════════════════════════════════════════════
CREATE INDEX IF NOT EXISTS idx_motion_blind_history_reviewer_submitted
  ON public.motion_clip_blind_submissions (reviewer_id, submitted_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_motion_clips_library_started
  ON public.motion_clips (started_at DESC, id DESC) WHERE r2_key IS NOT NULL;

-- ══════════════════════════════════════════════════════════════════
-- 5. service_role 전용 EXECUTE (설계 §10) — client(anon/authenticated) 접근 0
-- ══════════════════════════════════════════════════════════════════
REVOKE ALL ON FUNCTION public.fn_list_motion_blind_history(
  uuid, timestamptz, uuid, text, uuid[], timestamptz, timestamptz, text, integer
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_blind_history(
  uuid, timestamptz, uuid, text, uuid[], timestamptz, timestamptz, text, integer
) TO service_role;

REVOKE ALL ON FUNCTION public.fn_list_motion_labeling_library(
  uuid, uuid, text, uuid[], timestamptz, timestamptz, text, text, text, timestamptz, uuid, integer
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_labeling_library(
  uuid, uuid, text, uuid[], timestamptz, timestamptz, text, text, text, timestamptz, uuid, integer
) TO service_role;

REVOKE ALL ON FUNCTION public.fn_get_motion_blind_owner_overview(date)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_get_motion_blind_owner_overview(date)
  TO service_role;

-- ══════════════════════════════════════════════════════════════════
-- 6. ROLLBACK 참고 (수동 복구용) — 이 migration 을 되돌리려면:
--   DROP FUNCTION IF EXISTS public.fn_list_motion_blind_history(
--     uuid, timestamptz, uuid, text, uuid[], timestamptz, timestamptz, text, integer);
--   DROP FUNCTION IF EXISTS public.fn_list_motion_labeling_library(
--     uuid, uuid, text, uuid[], timestamptz, timestamptz, text, text, text, timestamptz, uuid, integer);
--   DROP FUNCTION IF EXISTS public.fn_get_motion_blind_owner_overview(date);
--   DROP INDEX IF EXISTS public.idx_motion_blind_history_reviewer_submitted;
--   DROP INDEX IF EXISTS public.idx_motion_clips_library_started;
-- 인덱스는 IF NOT EXISTS 로 생성했으므로 기존에 있었다면 되돌릴 때 남겨도 무방하다.
-- ══════════════════════════════════════════════════════════════════

COMMIT;
