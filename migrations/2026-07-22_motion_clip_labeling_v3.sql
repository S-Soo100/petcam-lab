-- motion_clips 네이티브 운영 라벨링 v3 — 2026-07-22.
--
-- 설계 정본: docs/superpowers/specs/2026-07-22-motion-clips-native-labeling-design.md
-- 구현계획: docs/superpowers/plans/2026-07-22-motion-clips-native-labeling.md Task 1
--
-- forward-only 신규 파일. 적용된 기존 마이그레이션을 수정하지 않는다.
-- legacy 라벨링 v2·튜토리얼·GT 는 그대로 두고, 운영 라벨링만 motion_clips 를
-- 정본으로 쓰는 triage/events/sessions/revisions + service-role 전용 RPC 6개를 추가한다.
--
-- 왜 service_role 전용인가(설계 §7·§10): v2 세션은 authenticated 가 본인 세션을 직접
--   INSERT/UPDATE 하는 RLS 를 썼지만, v3 는 모든 상태 전환을 Next.js API 가 bearer 인증 +
--   owner/labeler 판정 후 service_role RPC 한 트랜잭션으로만 처리한다. 네 테이블 모두
--   RLS ON + anon/authenticated REVOKE + client policy 0 건.
--
-- 왜 append-only 트리거인가: service_role 유출/실수로도 감사 로그(events·revisions)를
--   UPDATE/DELETE/TRUNCATE 하지 못하게 실행 역할과 무관한 트리거로 강제한다(0A000).
--
-- 금지(설계 §11): legacy 정본 mirror, 자동 라벨 생성, Evidence GT/Python Evidence/Gate/
--   prelabel 참조를 하지 않는다. VLM 결과는 GT 잠금 시 snapshot 만 복사한다.
--
-- 에러 계약(API 매핑용 안정 SQLSTATE):
--   22023 invalid_parameter_value  → 400 (enum/note/uuid/jsonb 형식 오류)
--   P0002 no_data_found            → 404 (clip/session 없음)
--   PT409 stale_state              → 409 stale_state (optimistic concurrency)
--   PT410 labeling_started         → 409 labeling_started (세션 있는 clip skip)
--   PT403 labeler_forbidden        → labeler 권한 밖(API 는 404 로 은닉)
--   PT422 media_unavailable        → 409 (원본 영상 없음)
--   PT423 gt_locked                → 409 (이미 잠긴 GT 재잠금/불변 위반)
--   0A000 feature_not_supported    → 감사 로그 append-only 위반
--
-- ⏳ production 미적용. 구현·테스트 후 사용자 검토에서 멈춘다(계획 Global Constraints).

BEGIN;

-- ── 1. 현재 제품 라우팅 상태 테이블 (설계 §7.1) ────────────────────
-- row 없음 = 'unreviewed'. owner 결정이 null 이면 결정 메타도 null 이어야 한다.
-- clip 원본은 삭제하지 않는 계약(설계 §3.2)이라 ON DELETE RESTRICT 로 라벨링 작업을 보호한다.
CREATE TABLE public.motion_clip_labeling_triage (
  clip_id uuid PRIMARY KEY REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  owner_decision text CHECK (owner_decision IN ('label','hold','skip')),
  decided_by uuid REFERENCES auth.users(id) ON DELETE RESTRICT,
  decided_at timestamptz,
  decision_note text CHECK (decision_note IS NULL OR char_length(decision_note) BETWEEN 10 AND 500),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  -- owner 결정이 없으면 결정 메타(누가/언제/사유)도 전부 null(설계 §7.1).
  CHECK (
    (owner_decision IS NULL AND decided_by IS NULL AND decided_at IS NULL AND decision_note IS NULL)
    OR
    (owner_decision IS NOT NULL AND decided_by IS NOT NULL AND decided_at IS NOT NULL)
  )
);

COMMENT ON TABLE public.motion_clip_labeling_triage IS
  'motion_clips 운영 라벨링 라우팅 상태. row 없음=unreviewed. label 만 일반 라벨러 큐 포함(설계 §7.1).';

-- 상태 탭/큐 필터는 owner_decision + 최신순 커서로 접힌다(설계 §8).
CREATE INDEX idx_motion_clip_labeling_triage_state
  ON public.motion_clip_labeling_triage (owner_decision, updated_at DESC, clip_id DESC);

-- ── 2. append-only 감사 이벤트 테이블 (설계 §7.2) ──────────────────
-- 이벤트는 clip 보다 오래 보존한다. FK CASCADE 를 걸면 append-only 차단 트리거가
-- motion_clips 삭제까지 막으므로 UUID 만 보존한다(v2 triage 이벤트와 동일 계약).
CREATE TABLE public.motion_clip_labeling_triage_events (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  clip_id uuid NOT NULL,
  event_type text NOT NULL CHECK (event_type IN ('owner_labeled','owner_held','owner_skipped','owner_reset','owner_started_labeling')),
  actor_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  before_state jsonb,
  after_state jsonb NOT NULL,
  reason text CHECK (reason IS NULL OR char_length(reason) <= 500),
  created_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.motion_clip_labeling_triage_events IS
  'Append-only. RPC 만 INSERT. UPDATE/DELETE/TRUNCATE 트리거 차단(0A000). 시스템 suggestion/evidence 없음.';

CREATE INDEX idx_motion_clip_labeling_triage_events_clip_created
  ON public.motion_clip_labeling_triage_events (clip_id, created_at DESC);

-- ── 3. blind GT 세션 테이블 (설계 §7.3) ───────────────────────────
-- v2 clip_labeling_sessions 의 blind GT 계약을 motion_clips FK 로 분리 구현한다.
-- 차이: v3 는 authenticated 직접 write RLS 를 두지 않고 service_role RPC 전용이다.
CREATE TABLE public.motion_clip_labeling_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  reviewed_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  stage text NOT NULL DEFAULT 'draft'
    CHECK (stage IN ('draft','gt_locked','completed')),
  initial_gt jsonb,       -- 최초 저장 뒤 불변(protect 트리거)
  current_gt jsonb,       -- owner revision 으로만 변경
  prediction_snapshot jsonb,  -- GT 잠금 시 서버가 최신 성공 clip_vlm_jobs.result 복사
  vlm_verdict text
    CHECK (vlm_verdict IN ('correct','partially_correct','incorrect','unjudgeable')),
  vlm_error_tags text[] NOT NULL DEFAULT '{}',
  vlm_review_note text,
  completion_reason text
    CHECK (completion_reason IN ('vlm_reviewed','no_prediction')),
  gt_locked_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (clip_id, reviewed_by),
  CHECK ((initial_gt IS NULL AND stage = 'draft') OR initial_gt IS NOT NULL),
  CHECK ((stage <> 'completed') OR completed_at IS NOT NULL)
);

COMMENT ON TABLE public.motion_clip_labeling_sessions IS
  'motion_clips blind human GT → VLM prediction review. prediction_snapshot 은 GT 잠금 시 서버만 복사.';

CREATE INDEX idx_motion_clip_labeling_sessions_reviewer_stage
  ON public.motion_clip_labeling_sessions (reviewed_by, stage, updated_at DESC);

-- initial_gt 불변 강제(설계 §7.3). v2 protect_initial_labeling_gt 와 동일 계약.
CREATE OR REPLACE FUNCTION public.fn_protect_motion_initial_gt()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  IF OLD.initial_gt IS NOT NULL AND NEW.initial_gt IS DISTINCT FROM OLD.initial_gt THEN
    RAISE EXCEPTION 'initial_gt is immutable after GT lock' USING ERRCODE = '22023';
  END IF;
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_protect_motion_initial_gt() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_protect_motion_initial_gt ON public.motion_clip_labeling_sessions;
CREATE TRIGGER trg_protect_motion_initial_gt
  BEFORE UPDATE ON public.motion_clip_labeling_sessions
  FOR EACH ROW EXECUTE FUNCTION public.fn_protect_motion_initial_gt();

-- ── 4. owner 보정 append-only revision 테이블 (설계 §7.4) ──────────
CREATE TABLE public.motion_clip_labeling_session_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL
    REFERENCES public.motion_clip_labeling_sessions(id) ON DELETE CASCADE,
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id) ON DELETE RESTRICT,
  revised_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
  previous_gt jsonb NOT NULL,
  revised_gt jsonb NOT NULL,
  previous_vlm_review jsonb,
  revised_vlm_review jsonb,
  reason text NOT NULL CHECK (char_length(reason) BETWEEN 10 AND 500),
  created_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.motion_clip_labeling_session_revisions IS
  'Append-only. owner 의 completed 세션 current_gt 보정 감사. initial_gt 는 불변 유지.';

CREATE INDEX idx_motion_clip_labeling_session_revisions_session
  ON public.motion_clip_labeling_session_revisions (session_id, created_at DESC);

-- ── 5. RLS + client write 차단 + service_role 전용 (설계 §7·§10) ────
ALTER TABLE public.motion_clip_labeling_triage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.motion_clip_labeling_triage_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.motion_clip_labeling_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.motion_clip_labeling_session_revisions ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.motion_clip_labeling_triage FROM PUBLIC;
REVOKE ALL ON TABLE public.motion_clip_labeling_triage FROM anon;
REVOKE ALL ON TABLE public.motion_clip_labeling_triage FROM authenticated;
GRANT ALL ON TABLE public.motion_clip_labeling_triage TO service_role;

REVOKE ALL ON TABLE public.motion_clip_labeling_triage_events FROM PUBLIC;
REVOKE ALL ON TABLE public.motion_clip_labeling_triage_events FROM anon;
REVOKE ALL ON TABLE public.motion_clip_labeling_triage_events FROM authenticated;
GRANT ALL ON TABLE public.motion_clip_labeling_triage_events TO service_role;

REVOKE ALL ON TABLE public.motion_clip_labeling_sessions FROM PUBLIC;
REVOKE ALL ON TABLE public.motion_clip_labeling_sessions FROM anon;
REVOKE ALL ON TABLE public.motion_clip_labeling_sessions FROM authenticated;
GRANT ALL ON TABLE public.motion_clip_labeling_sessions TO service_role;

REVOKE ALL ON TABLE public.motion_clip_labeling_session_revisions FROM PUBLIC;
REVOKE ALL ON TABLE public.motion_clip_labeling_session_revisions FROM anon;
REVOKE ALL ON TABLE public.motion_clip_labeling_session_revisions FROM authenticated;
GRANT ALL ON TABLE public.motion_clip_labeling_session_revisions TO service_role;

-- ── 6. 감사 로그 append-only 강제 트리거 (events + revisions 공용) ──
-- 실행 역할(service_role 포함)과 무관하게 발동한다. INSERT 만 허용.
CREATE OR REPLACE FUNCTION public.fn_block_motion_labeling_audit_mutation()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE', 'TRUNCATE') THEN
    RAISE EXCEPTION '% is append-only (UPDATE/DELETE/TRUNCATE 금지)', TG_TABLE_NAME
      USING ERRCODE = '0A000';  -- feature_not_supported
  END IF;
  RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION public.fn_block_motion_labeling_audit_mutation() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_block_motion_triage_event_row_mutation
  ON public.motion_clip_labeling_triage_events;
CREATE TRIGGER trg_block_motion_triage_event_row_mutation
  BEFORE UPDATE OR DELETE ON public.motion_clip_labeling_triage_events
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_motion_labeling_audit_mutation();

DROP TRIGGER IF EXISTS trg_block_motion_triage_event_truncate
  ON public.motion_clip_labeling_triage_events;
CREATE TRIGGER trg_block_motion_triage_event_truncate
  BEFORE TRUNCATE ON public.motion_clip_labeling_triage_events
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_motion_labeling_audit_mutation();

DROP TRIGGER IF EXISTS trg_block_motion_revision_row_mutation
  ON public.motion_clip_labeling_session_revisions;
CREATE TRIGGER trg_block_motion_revision_row_mutation
  BEFORE UPDATE OR DELETE ON public.motion_clip_labeling_session_revisions
  FOR EACH ROW EXECUTE FUNCTION public.fn_block_motion_labeling_audit_mutation();

DROP TRIGGER IF EXISTS trg_block_motion_revision_truncate
  ON public.motion_clip_labeling_session_revisions;
CREATE TRIGGER trg_block_motion_revision_truncate
  BEFORE TRUNCATE ON public.motion_clip_labeling_session_revisions
  FOR EACH STATEMENT EXECUTE FUNCTION public.fn_block_motion_labeling_audit_mutation();

-- ── 7. 최신순 큐 RPC (설계 §8) ─────────────────────────────────────
-- owner: motion_clips 전체(owner_id 필터 없음). labeler: label + 재생가능 + 본인 미완료.
-- 정본 정렬 (started_at DESC, id DESC) + keyset. 마이크로초는 timestamptz 로 verbatim 반환.
CREATE OR REPLACE FUNCTION public.fn_list_motion_clip_labeling_queue(
  p_reviewer_id uuid,
  p_is_owner boolean,
  p_state text DEFAULT NULL,
  p_camera_ids uuid[] DEFAULT NULL,
  p_date_from timestamptz DEFAULT NULL,
  p_date_to timestamptz DEFAULT NULL,
  p_media text DEFAULT NULL,
  p_cursor_started_at timestamptz DEFAULT NULL,
  p_cursor_id uuid DEFAULT NULL,
  p_limit integer DEFAULT 31
) RETURNS TABLE (
  clip_id uuid, camera_id uuid, camera_name text, started_at timestamptz,
  duration_sec double precision, media_ready boolean, state text,
  session_stage text, state_updated_at timestamptz
)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
BEGIN
  -- 입력 검증(잘못된 값=22023 → API 400). cursor 는 둘 다 있거나 둘 다 없어야 한다.
  IF p_state IS NOT NULL AND p_state NOT IN ('unreviewed','label','hold','skip') THEN
    RAISE EXCEPTION 'invalid state filter: %', p_state USING ERRCODE = '22023';
  END IF;
  IF p_media IS NOT NULL AND p_media NOT IN ('ready','unavailable') THEN
    RAISE EXCEPTION 'invalid media filter: %', p_media USING ERRCODE = '22023';
  END IF;
  IF (p_cursor_started_at IS NULL) <> (p_cursor_id IS NULL) THEN
    RAISE EXCEPTION 'cursor requires both started_at and id' USING ERRCODE = '22023';
  END IF;

  RETURN QUERY
  SELECT
    m.id AS clip_id,
    m.camera_id AS camera_id,
    cam.name AS camera_name,
    m.started_at AS started_at,
    m.duration_sec AS duration_sec,
    (m.r2_key IS NOT NULL) AS media_ready,
    COALESCE(t.owner_decision, 'unreviewed') AS state,
    s.stage AS session_stage,
    t.updated_at AS state_updated_at
  FROM public.motion_clips m
  LEFT JOIN public.cameras cam ON cam.id = m.camera_id
  LEFT JOIN public.motion_clip_labeling_triage t ON t.clip_id = m.id
  LEFT JOIN public.motion_clip_labeling_sessions s
    ON s.clip_id = m.id AND s.reviewed_by = p_reviewer_id
  WHERE
    (p_cursor_started_at IS NULL
     OR m.started_at < p_cursor_started_at
     OR (m.started_at = p_cursor_started_at AND m.id < p_cursor_id))
    AND (p_camera_ids IS NULL OR m.camera_id = ANY (p_camera_ids))
    AND (p_date_from IS NULL OR m.started_at >= p_date_from)
    AND (p_date_to IS NULL OR m.started_at < p_date_to)
    AND (p_media IS NULL
         OR (p_media = 'ready' AND m.r2_key IS NOT NULL)
         OR (p_media = 'unavailable' AND m.r2_key IS NULL))
    AND (
      CASE WHEN p_is_owner THEN
        -- owner: 전체. 선택적 state 필터만 적용(설계 §8.1).
        (p_state IS NULL
         OR (p_state = 'unreviewed' AND t.owner_decision IS NULL)
         OR (t.owner_decision = p_state))
      ELSE
        -- labeler: owner_decision='label' + 재생가능 + 본인 completed 없음(설계 §8.2).
        (t.owner_decision = 'label'
         AND m.r2_key IS NOT NULL
         AND NOT EXISTS (
           SELECT 1 FROM public.motion_clip_labeling_sessions cs
           WHERE cs.clip_id = m.id AND cs.reviewed_by = p_reviewer_id
             AND cs.stage = 'completed'))
      END
    )
  ORDER BY m.started_at DESC, m.id DESC
  LIMIT LEAST(GREATEST(p_limit, 1), 100);
END;
$$;

-- labeler 카메라 필터도 실제 처리 가능 큐와 같은 조건을 쓴다. DISTINCT 를 DB에서 수행해
-- PostgREST 기본 최대 행 수에 잘려 카메라 옵션이 누락되는 경로를 없앤다.
CREATE OR REPLACE FUNCTION public.fn_list_motion_clip_labeling_camera_options(
  p_reviewer_id uuid
) RETURNS TABLE (camera_id uuid, camera_name text)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT DISTINCT cam.id AS camera_id, cam.name AS camera_name
  FROM public.motion_clip_labeling_triage t
  JOIN public.motion_clips m ON m.id = t.clip_id
  JOIN public.cameras cam ON cam.id = m.camera_id
  WHERE t.owner_decision = 'label'
    AND m.r2_key IS NOT NULL
    AND NOT EXISTS (
      SELECT 1
      FROM public.motion_clip_labeling_sessions cs
      WHERE cs.clip_id = m.id
        AND cs.reviewed_by = p_reviewer_id
        AND cs.stage = 'completed'
    )
  ORDER BY cam.name ASC NULLS LAST, cam.id ASC;
$$;

-- ── 8. owner 분류 결정 RPC (설계 §5.3·§7.5) ────────────────────────
-- label|hold|skip|reset. optimistic concurrency(expected_updated_at)로 stale 탭 차단.
-- skip 은 세션이 있는 clip 에서 거부. row 없으면 첫 결정 시 INSERT.
CREATE OR REPLACE FUNCTION public.fn_decide_motion_clip_labeling(
  p_clip_id uuid,
  p_actor_id uuid,
  p_decision text,
  p_expected_updated_at timestamptz DEFAULT NULL,
  p_note text DEFAULT NULL
) RETURNS public.motion_clip_labeling_triage
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_row public.motion_clip_labeling_triage%ROWTYPE;
  v_before jsonb;
  v_event_type text;
  v_found boolean;
BEGIN
  IF p_decision NOT IN ('label','hold','skip','reset') THEN
    RAISE EXCEPTION 'invalid decision: %', p_decision USING ERRCODE = '22023';
  END IF;
  IF p_note IS NOT NULL AND char_length(p_note) NOT BETWEEN 10 AND 500 THEN
    RAISE EXCEPTION 'note must be 10..500 chars' USING ERRCODE = '22023';
  END IF;

  -- lock 순서 통일: motion_clips → triage(다른 RPC 와 동일, deadlock 방지).
  PERFORM 1 FROM public.motion_clips WHERE id = p_clip_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'motion_clip not found: %', p_clip_id USING ERRCODE = 'P0002';
  END IF;

  SELECT * INTO v_row FROM public.motion_clip_labeling_triage
    WHERE clip_id = p_clip_id FOR UPDATE;
  v_found := FOUND;

  -- optimistic concurrency: 기존 row 면 updated_at 일치 필수(설계 §7.5 409 stale_state).
  -- 첫 결정(row 없음)은 expected 도 null 이어야 한다.
  IF v_found THEN
    IF v_row.updated_at IS DISTINCT FROM p_expected_updated_at THEN
      RAISE EXCEPTION 'stale_state' USING ERRCODE = 'PT409';
    END IF;
  ELSE
    IF p_expected_updated_at IS NOT NULL THEN
      RAISE EXCEPTION 'stale_state' USING ERRCODE = 'PT409';
    END IF;
    IF p_decision = 'reset' THEN
      RAISE EXCEPTION 'motion_clip triage not found' USING ERRCODE = 'P0002';
    END IF;
  END IF;

  -- skip 은 이미 라벨링 세션이 있는 clip 에서 거부(설계 §5.3 409 labeling_started).
  IF p_decision = 'skip'
     AND EXISTS (SELECT 1 FROM public.motion_clip_labeling_sessions WHERE clip_id = p_clip_id) THEN
    RAISE EXCEPTION 'labeling_started' USING ERRCODE = 'PT410';
  END IF;

  v_before := CASE WHEN v_found THEN to_jsonb(v_row) ELSE NULL END;

  IF p_decision = 'reset' THEN
    UPDATE public.motion_clip_labeling_triage
      SET owner_decision = NULL, decided_by = NULL, decided_at = NULL,
          decision_note = NULL, updated_at = clock_timestamp()
      WHERE clip_id = p_clip_id
      RETURNING * INTO v_row;
    v_event_type := 'owner_reset';
  ELSIF v_found THEN
    UPDATE public.motion_clip_labeling_triage
      SET owner_decision = p_decision, decided_by = p_actor_id,
          decided_at = clock_timestamp(), decision_note = p_note,
          updated_at = clock_timestamp()
      WHERE clip_id = p_clip_id
      RETURNING * INTO v_row;
    v_event_type := CASE p_decision
      WHEN 'label' THEN 'owner_labeled'
      WHEN 'hold'  THEN 'owner_held'
      ELSE 'owner_skipped' END;
  ELSE
    INSERT INTO public.motion_clip_labeling_triage
      (clip_id, owner_decision, decided_by, decided_at, decision_note)
    VALUES (p_clip_id, p_decision, p_actor_id, clock_timestamp(), p_note)
    RETURNING * INTO v_row;
    v_event_type := CASE p_decision
      WHEN 'label' THEN 'owner_labeled'
      WHEN 'hold'  THEN 'owner_held'
      ELSE 'owner_skipped' END;
  END IF;

  INSERT INTO public.motion_clip_labeling_triage_events
    (clip_id, event_type, actor_id, before_state, after_state, reason)
  VALUES (p_clip_id, v_event_type, p_actor_id, v_before, to_jsonb(v_row), p_note);

  RETURN v_row;
END;
$$;

-- ── 9. blind GT 잠금 RPC (설계 §5.2·§7.3) ──────────────────────────
-- owner 직접 라벨링: triage label 전환 + 세션 gt_locked 를 한 트랜잭션에 만든다.
-- labeler: owner_decision='label' 인 clip 만 잠글 수 있다. prediction_snapshot 은 서버가 넘긴다.
CREATE OR REPLACE FUNCTION public.fn_lock_motion_clip_gt(
  p_clip_id uuid,
  p_reviewer_id uuid,
  p_is_owner boolean,
  p_gt jsonb,
  p_prediction_snapshot jsonb DEFAULT NULL
) RETURNS public.motion_clip_labeling_sessions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_session public.motion_clip_labeling_sessions%ROWTYPE;
  v_triage public.motion_clip_labeling_triage%ROWTYPE;
  v_before jsonb;
  v_r2_key text;
BEGIN
  IF p_gt IS NULL OR jsonb_typeof(p_gt) <> 'object' THEN
    RAISE EXCEPTION 'gt must be a JSON object' USING ERRCODE = '22023';
  END IF;
  IF p_prediction_snapshot IS NOT NULL AND jsonb_typeof(p_prediction_snapshot) <> 'object' THEN
    RAISE EXCEPTION 'prediction_snapshot must be a JSON object' USING ERRCODE = '22023';
  END IF;

  -- lock 순서: motion_clips → triage → session. 재생 가능(r2_key) 확인.
  SELECT r2_key INTO v_r2_key FROM public.motion_clips WHERE id = p_clip_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'motion_clip not found: %', p_clip_id USING ERRCODE = 'P0002';
  END IF;
  IF v_r2_key IS NULL THEN
    RAISE EXCEPTION 'media_unavailable' USING ERRCODE = 'PT422';
  END IF;

  SELECT * INTO v_triage FROM public.motion_clip_labeling_triage
    WHERE clip_id = p_clip_id FOR UPDATE;

  -- 권한: labeler 는 owner_decision='label' 인 clip 만. owner 는 어떤 clip 이든 가능.
  IF NOT p_is_owner THEN
    IF NOT FOUND OR v_triage.owner_decision IS DISTINCT FROM 'label' THEN
      RAISE EXCEPTION 'labeler_forbidden' USING ERRCODE = 'PT403';
    END IF;
  END IF;

  -- 이미 잠긴 세션이 있으면 재잠금 거부(initial_gt 불변 계약, 설계 §7.3).
  SELECT * INTO v_session FROM public.motion_clip_labeling_sessions
    WHERE clip_id = p_clip_id AND reviewed_by = p_reviewer_id FOR UPDATE;
  IF FOUND AND v_session.initial_gt IS NOT NULL THEN
    RAISE EXCEPTION 'gt_already_locked' USING ERRCODE = 'PT423';
  END IF;

  -- owner 직접 라벨링: 아직 label 이 아니면 triage 를 label 로 원자 전환(설계 §5.2).
  IF p_is_owner AND (v_triage.clip_id IS NULL OR v_triage.owner_decision IS DISTINCT FROM 'label') THEN
    v_before := CASE WHEN v_triage.clip_id IS NULL THEN NULL ELSE to_jsonb(v_triage) END;
    INSERT INTO public.motion_clip_labeling_triage
      (clip_id, owner_decision, decided_by, decided_at, decision_note)
    VALUES (p_clip_id, 'label', p_reviewer_id, clock_timestamp(), NULL)
    ON CONFLICT (clip_id) DO UPDATE
      SET owner_decision = 'label', decided_by = p_reviewer_id,
          decided_at = clock_timestamp(), decision_note = NULL,
          updated_at = clock_timestamp()
    RETURNING * INTO v_triage;
    INSERT INTO public.motion_clip_labeling_triage_events
      (clip_id, event_type, actor_id, before_state, after_state, reason)
    VALUES (p_clip_id, 'owner_started_labeling', p_reviewer_id, v_before, to_jsonb(v_triage), NULL);
  END IF;

  -- 세션 gt_locked upsert. 클라이언트는 reviewer/stage/prediction 을 못 넘긴다(서버 결정).
  -- 위에서 initial_gt 있는 세션은 이미 gt_already_locked 로 raise 했으므로, 여기 도달하는
  -- 충돌은 draft(initial_gt NULL)뿐이고 그건 잠그는 게 맞다. WHERE 를 걸지 않아 DO UPDATE 가
  -- 항상 발동 → RETURNING 이 빈 결과로 빈 row 를 반환하는 경로를 원천 제거한다.
  INSERT INTO public.motion_clip_labeling_sessions
    (clip_id, reviewed_by, stage, initial_gt, current_gt, prediction_snapshot, gt_locked_at)
  VALUES (p_clip_id, p_reviewer_id, 'gt_locked', p_gt, p_gt, p_prediction_snapshot, clock_timestamp())
  ON CONFLICT (clip_id, reviewed_by) DO UPDATE
    SET stage = 'gt_locked', initial_gt = EXCLUDED.initial_gt,
        current_gt = EXCLUDED.current_gt,
        prediction_snapshot = EXCLUDED.prediction_snapshot,
        gt_locked_at = clock_timestamp()
  RETURNING * INTO v_session;

  RETURN v_session;
END;
$$;

-- ── 10. VLM 검수 완료 RPC (설계 §7.3) ──────────────────────────────
-- prediction 있으면 verdict 필수(vlm_reviewed), 없으면 no_prediction 으로 완료.
-- 다른 정본에 자동 라벨을 mirror 하지 않는다(설계 §11).
CREATE OR REPLACE FUNCTION public.fn_complete_motion_clip_vlm_review(
  p_clip_id uuid,
  p_reviewer_id uuid,
  p_verdict text,
  p_error_tags text[] DEFAULT '{}',
  p_review_note text DEFAULT NULL
) RETURNS public.motion_clip_labeling_sessions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_session public.motion_clip_labeling_sessions%ROWTYPE;
  v_reason text;
  v_verdict text;
BEGIN
  SELECT * INTO v_session FROM public.motion_clip_labeling_sessions
    WHERE clip_id = p_clip_id AND reviewed_by = p_reviewer_id AND stage = 'gt_locked'
    FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'gt_locked session not found' USING ERRCODE = 'P0002';
  END IF;

  IF v_session.prediction_snapshot IS NOT NULL THEN
    IF p_verdict IS NULL
       OR p_verdict NOT IN ('correct','partially_correct','incorrect','unjudgeable') THEN
      RAISE EXCEPTION 'verdict required when prediction exists' USING ERRCODE = '22023';
    END IF;
    v_verdict := p_verdict;
    v_reason := 'vlm_reviewed';
  ELSE
    -- prediction 없음: verdict 무시(no_prediction). 스냅샷을 지어내지 않는다.
    v_verdict := NULL;
    v_reason := 'no_prediction';
  END IF;

  UPDATE public.motion_clip_labeling_sessions
    SET stage = 'completed',
        vlm_verdict = v_verdict,
        vlm_error_tags = COALESCE(p_error_tags, '{}'),
        vlm_review_note = p_review_note,
        completion_reason = v_reason,
        completed_at = clock_timestamp(),
        updated_at = clock_timestamp()
    WHERE id = v_session.id
    RETURNING * INTO v_session;

  RETURN v_session;
END;
$$;

-- ── 11. owner GT 보정 RPC (설계 §7.4) ──────────────────────────────
-- completed + 본인 세션의 current_gt 만 사유와 함께 보정. initial_gt 는 불변(trigger).
-- v2 와 달리 자동 라벨 mirror 를 하지 않는다(설계 §11 — 운영 v3 는 자동 라벨 생성 금지).
CREATE OR REPLACE FUNCTION public.fn_revise_motion_clip_gt(
  p_clip_id uuid,
  p_actor_id uuid,
  p_new_gt jsonb,
  p_reason text
) RETURNS public.motion_clip_labeling_sessions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_session public.motion_clip_labeling_sessions%ROWTYPE;
  v_updated public.motion_clip_labeling_sessions%ROWTYPE;
BEGIN
  IF p_new_gt IS NULL OR jsonb_typeof(p_new_gt) <> 'object' THEN
    RAISE EXCEPTION 'new_gt must be a JSON object' USING ERRCODE = '22023';
  END IF;
  IF p_reason IS NULL OR char_length(p_reason) NOT BETWEEN 10 AND 500 THEN
    RAISE EXCEPTION 'reason must be 10..500 chars' USING ERRCODE = '22023';
  END IF;

  SELECT * INTO v_session FROM public.motion_clip_labeling_sessions
    WHERE clip_id = p_clip_id AND reviewed_by = p_actor_id AND stage = 'completed'
    FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'completed session not found for reviewer' USING ERRCODE = 'P0002';
  END IF;

  INSERT INTO public.motion_clip_labeling_session_revisions
    (session_id, clip_id, revised_by, previous_gt, revised_gt,
     previous_vlm_review, revised_vlm_review, reason)
  VALUES (
    v_session.id, v_session.clip_id, p_actor_id,
    v_session.current_gt, p_new_gt,
    jsonb_build_object('verdict', v_session.vlm_verdict,
                       'error_tags', to_jsonb(v_session.vlm_error_tags),
                       'note', v_session.vlm_review_note),
    jsonb_build_object('verdict', v_session.vlm_verdict,
                       'error_tags', to_jsonb(v_session.vlm_error_tags),
                       'note', v_session.vlm_review_note),
    p_reason);

  UPDATE public.motion_clip_labeling_sessions
    SET current_gt = p_new_gt, updated_at = clock_timestamp()
    WHERE id = v_session.id
    RETURNING * INTO v_updated;

  RETURN v_updated;
END;
$$;

-- ── 12. 함수 실행권한 — service_role 전용 (설계 §7·§10) ─────────────
REVOKE ALL ON FUNCTION public.fn_list_motion_clip_labeling_queue(
  uuid, boolean, text, uuid[], timestamptz, timestamptz, text, timestamptz, uuid, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_clip_labeling_queue(
  uuid, boolean, text, uuid[], timestamptz, timestamptz, text, timestamptz, uuid, integer)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_list_motion_clip_labeling_camera_options(uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_list_motion_clip_labeling_camera_options(uuid)
  TO service_role;

REVOKE ALL ON FUNCTION public.fn_decide_motion_clip_labeling(
  uuid, uuid, text, timestamptz, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_decide_motion_clip_labeling(
  uuid, uuid, text, timestamptz, text) TO service_role;

REVOKE ALL ON FUNCTION public.fn_lock_motion_clip_gt(
  uuid, uuid, boolean, jsonb, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_lock_motion_clip_gt(
  uuid, uuid, boolean, jsonb, jsonb) TO service_role;

REVOKE ALL ON FUNCTION public.fn_complete_motion_clip_vlm_review(
  uuid, uuid, text, text[], text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_complete_motion_clip_vlm_review(
  uuid, uuid, text, text[], text) TO service_role;

REVOKE ALL ON FUNCTION public.fn_revise_motion_clip_gt(
  uuid, uuid, jsonb, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_revise_motion_clip_gt(
  uuid, uuid, jsonb, text) TO service_role;

COMMIT;

-- ── 검증 (DO/트랜잭션 롤백 probe, REPORT 참고) ─────────────────────
-- 아래는 preview apply 후 트랜잭션 안에서 검증하고 전량 롤백하는 예시다. <clip>/<owner> 대입.
-- BEGIN;
--   -- owner 직접 GT: triage label 전환 + 세션 gt_locked + owner_started_labeling 원자성
--   SELECT public.fn_lock_motion_clip_gt('<clip>'::uuid, '<owner>'::uuid, true,
--     '{"visibility":"visible"}'::jsonb, NULL);
--   SELECT owner_decision FROM public.motion_clip_labeling_triage WHERE clip_id='<clip>'; -- 'label'
--   SELECT stage FROM public.motion_clip_labeling_sessions
--     WHERE clip_id='<clip>' AND reviewed_by='<owner>';                                   -- 'gt_locked'
--   SELECT count(*) FROM public.motion_clip_labeling_triage_events
--     WHERE clip_id='<clip>' AND event_type='owner_started_labeling';                     -- 1
--
--   -- prediction 없음 → no_prediction 완료
--   SELECT public.fn_complete_motion_clip_vlm_review('<clip>'::uuid, '<owner>'::uuid, NULL);
--   SELECT completion_reason FROM public.motion_clip_labeling_sessions
--     WHERE clip_id='<clip>' AND reviewed_by='<owner>';                                   -- 'no_prediction'
--
--   -- initial_gt 불변: current_gt 보정은 되고 initial 은 유지
--   SELECT public.fn_revise_motion_clip_gt('<clip>'::uuid, '<owner>'::uuid,
--     '{"visibility":"partial"}'::jsonb, '기준 GT 대상 정정: visible → partial');
--   SELECT initial_gt <> current_gt FROM public.motion_clip_labeling_sessions
--     WHERE clip_id='<clip>' AND reviewed_by='<owner>';                                   -- true (initial 불변)
--
--   -- stale 결정 거부: 잘못된 expected_updated_at → PT409
--   SELECT public.fn_decide_motion_clip_labeling('<clip2>'::uuid, '<owner>'::uuid, 'hold',
--     'epoch'::timestamptz, NULL);                                                        -- PT409 stale_state
--
--   -- 세션 있는 clip skip 거부 → PT410
--   SELECT public.fn_decide_motion_clip_labeling('<clip>'::uuid, '<owner>'::uuid, 'skip',
--     (SELECT updated_at FROM public.motion_clip_labeling_triage WHERE clip_id='<clip>'), NULL); -- PT410
--
--   -- append-only: 이벤트/리비전 UPDATE·DELETE·TRUNCATE → 0A000
--   -- UPDATE public.motion_clip_labeling_triage_events SET reason='x' WHERE clip_id='<clip>';  -- 0A000
--   -- DELETE FROM public.motion_clip_labeling_session_revisions WHERE clip_id='<clip>';        -- 0A000
--   -- TRUNCATE public.motion_clip_labeling_triage_events;                                       -- 0A000
--
--   -- labeler 권한: owner_decision<>'label' clip 을 labeler 로 잠그면 PT403
--   SELECT public.fn_lock_motion_clip_gt('<clip3-unreviewed>'::uuid, '<labeler>'::uuid, false,
--     '{"visibility":"visible"}'::jsonb, NULL);                                            -- PT403
-- ROLLBACK;  -- 모든 probe row 0 로 복귀

-- ── 롤백 (별도 forward migration 으로만 수행, 이 파일은 수정 금지) ──
-- BEGIN;
-- DROP FUNCTION IF EXISTS public.fn_revise_motion_clip_gt(uuid, uuid, jsonb, text);
-- DROP FUNCTION IF EXISTS public.fn_complete_motion_clip_vlm_review(uuid, uuid, text, text[], text);
-- DROP FUNCTION IF EXISTS public.fn_lock_motion_clip_gt(uuid, uuid, boolean, jsonb, jsonb);
-- DROP FUNCTION IF EXISTS public.fn_decide_motion_clip_labeling(uuid, uuid, text, timestamptz, text);
-- DROP FUNCTION IF EXISTS public.fn_list_motion_clip_labeling_camera_options(uuid);
-- DROP FUNCTION IF EXISTS public.fn_list_motion_clip_labeling_queue(
--   uuid, boolean, text, uuid[], timestamptz, timestamptz, text, timestamptz, uuid, integer);
-- DROP TRIGGER IF EXISTS trg_block_motion_revision_truncate ON public.motion_clip_labeling_session_revisions;
-- DROP TRIGGER IF EXISTS trg_block_motion_revision_row_mutation ON public.motion_clip_labeling_session_revisions;
-- DROP TRIGGER IF EXISTS trg_block_motion_triage_event_truncate ON public.motion_clip_labeling_triage_events;
-- DROP TRIGGER IF EXISTS trg_block_motion_triage_event_row_mutation ON public.motion_clip_labeling_triage_events;
-- DROP FUNCTION IF EXISTS public.fn_block_motion_labeling_audit_mutation();
-- DROP TRIGGER IF EXISTS trg_protect_motion_initial_gt ON public.motion_clip_labeling_sessions;
-- DROP FUNCTION IF EXISTS public.fn_protect_motion_initial_gt();
-- DROP TABLE IF EXISTS public.motion_clip_labeling_session_revisions;
-- DROP TABLE IF EXISTS public.motion_clip_labeling_sessions;
-- DROP TABLE IF EXISTS public.motion_clip_labeling_triage_events;
-- DROP TABLE IF EXISTS public.motion_clip_labeling_triage;
-- COMMIT;
