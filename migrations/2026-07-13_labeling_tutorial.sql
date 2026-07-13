-- 라벨링 대화형 튜토리얼: 고정 5개 lesson + 라벨러 시도 기록.
--
-- 상태: 작성 완료. 적용 순서(설계 §17): 이 migration 적용 → owner 5개 seed →
--   activation RPC 로 active → 테스트 라벨러 E2E → production.
--
-- 정답(reference_gt / prediction_snapshot / reference_vlm_review / feedback_content)은
-- RLS + service_role 전용으로 보호하며, VLM 검수 제출 전에는 API 응답/HTML/props/로그에
-- 넣지 않는다(설계 §12). 튜토리얼 답안은 behavior_labels / clip_labeling_sessions 에
-- 절대 쓰지 않는다(학습 시도와 운영 GT provenance 분리, 설계 §1).

BEGIN;

-- ── 1. tutorial set ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.labeling_tutorial_sets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  version TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'active', 'archived')),
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  activated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- status='active' 는 전체 1개만 허용(partial unique index).
CREATE UNIQUE INDEX IF NOT EXISTS uniq_one_active_tutorial_set
  ON public.labeling_tutorial_sets (status) WHERE status = 'active';

COMMENT ON TABLE public.labeling_tutorial_sets IS
  '라벨링 튜토리얼 버전. active 는 partial unique 로 전체 1개. activation RPC 로만 전환.';

-- ── 2. tutorial lessons (고정 5개) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS public.labeling_tutorial_lessons (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tutorial_set_id UUID NOT NULL
    REFERENCES public.labeling_tutorial_sets(id) ON DELETE RESTRICT,
  position SMALLINT NOT NULL CHECK (position BETWEEN 1 AND 5),
  clip_id UUID NOT NULL REFERENCES public.camera_clips(id) ON DELETE RESTRICT,
  title TEXT NOT NULL,
  learning_objective TEXT NOT NULL,
  pre_submit_tip TEXT,
  reference_gt JSONB NOT NULL,
  prediction_snapshot JSONB NOT NULL,
  reference_vlm_review JSONB NOT NULL,
  feedback_content JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tutorial_set_id, position),
  UNIQUE (tutorial_set_id, clip_id)
);

COMMENT ON TABLE public.labeling_tutorial_lessons IS
  '활성화 뒤 clip/reference/prediction/feedback 불변. 변경은 새 tutorial version 으로.';
COMMENT ON COLUMN public.labeling_tutorial_lessons.prediction_snapshot IS
  '활성화 시 고정한 VLM 판정 snapshot. GT 잠금 후 라벨러에게 공개.';
COMMENT ON COLUMN public.labeling_tutorial_lessons.reference_gt IS
  'owner 가 확정한 기준 GT. VLM 검수 제출 전에는 절대 노출하지 않는다.';

-- ── 3. per-user progress (본 큐 gate hot path) ─────────────────────
CREATE TABLE IF NOT EXISTS public.labeling_tutorial_progress (
  tutorial_set_id UUID NOT NULL
    REFERENCES public.labeling_tutorial_sets(id) ON DELETE RESTRICT,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  current_run_no INTEGER NOT NULL DEFAULT 1,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  waived_at TIMESTAMPTZ,
  waived_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  waiver_reason TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (tutorial_set_id, user_id),
  CONSTRAINT tutorial_waiver_reason_len
    CHECK (waiver_reason IS NULL OR CHAR_LENGTH(waiver_reason) BETWEEN 1 AND 200)
);

COMMENT ON TABLE public.labeling_tutorial_progress IS
  '본 큐 접근 조건 = owner 또는 completed_at/waived_at NOT NULL. gate 는 이 한 row 만 조회.';

-- ── 4. per-lesson attempts (최초 답 불변) ──────────────────────────
CREATE TABLE IF NOT EXISTS public.labeling_tutorial_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tutorial_set_id UUID NOT NULL
    REFERENCES public.labeling_tutorial_sets(id) ON DELETE RESTRICT,
  lesson_id UUID NOT NULL
    REFERENCES public.labeling_tutorial_lessons(id) ON DELETE RESTRICT,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  run_no INTEGER NOT NULL DEFAULT 1,
  stage TEXT NOT NULL DEFAULT 'gt_locked'
    CHECK (stage IN ('draft', 'gt_locked', 'review_submitted', 'completed')),
  submitted_gt JSONB,
  submitted_vlm_review JSONB,
  comparison JSONB,
  gt_locked_at TIMESTAMPTZ,
  review_submitted_at TIMESTAMPTZ,
  feedback_viewed_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tutorial_set_id, lesson_id, user_id, run_no)
);

CREATE INDEX IF NOT EXISTS idx_tutorial_attempts_user_set_run_stage
  ON public.labeling_tutorial_attempts (user_id, tutorial_set_id, run_no, stage);

COMMENT ON TABLE public.labeling_tutorial_attempts IS
  '학습 시도. 최초 submitted_gt/submitted_vlm_review/comparison 은 trigger 로 불변.';

-- 최초 제출값·비교는 불변. 라우트도 409 로 막지만 DB 가 최종 방어선(설계 §9).
CREATE OR REPLACE FUNCTION public.protect_tutorial_attempt()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.submitted_gt IS NOT NULL
     AND NEW.submitted_gt IS DISTINCT FROM OLD.submitted_gt THEN
    RAISE EXCEPTION 'submitted_gt is immutable';
  END IF;
  IF OLD.submitted_vlm_review IS NOT NULL
     AND NEW.submitted_vlm_review IS DISTINCT FROM OLD.submitted_vlm_review THEN
    RAISE EXCEPTION 'submitted_vlm_review is immutable';
  END IF;
  IF OLD.comparison IS NOT NULL
     AND NEW.comparison IS DISTINCT FROM OLD.comparison THEN
    RAISE EXCEPTION 'comparison is immutable';
  END IF;
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS protect_tutorial_attempt
  ON public.labeling_tutorial_attempts;
CREATE TRIGGER protect_tutorial_attempt
BEFORE UPDATE ON public.labeling_tutorial_attempts
FOR EACH ROW EXECUTE FUNCTION public.protect_tutorial_attempt();

-- ── 5. RLS + service_role 전용 (4 테이블) ──────────────────────────
-- client role 정책은 만들지 않는다(설계 §9). 정답 JSON 은 브라우저 직접 조회 불가.
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'labeling_tutorial_sets', 'labeling_tutorial_lessons',
    'labeling_tutorial_progress', 'labeling_tutorial_attempts'
  ] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', t);
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC;', t);
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon;', t);
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM authenticated;', t);
    EXECUTE format('GRANT ALL ON TABLE public.%I TO service_role;', t);
  END LOOP;
END $$;

-- ── 6. activation RPC ──────────────────────────────────────────────
-- 정확히 5개(position 1..5)·모든 기준 snapshot 존재 검사 후 active 전환.
-- Next.js API 가 호출 전 owner(DEV_USER_ID)를 검증한다. service_role 침해 =
-- DB 전체 침해이므로 함수가 별도 owner allowlist 를 중복 보유하지 않는다.
CREATE OR REPLACE FUNCTION public.fn_activate_tutorial_set(
  p_set_id UUID, p_owner_id UUID
) RETURNS public.labeling_tutorial_sets
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_set public.labeling_tutorial_sets%ROWTYPE;
  v_ok_count INTEGER;
  v_distinct_positions INTEGER;
BEGIN
  SELECT * INTO v_set FROM public.labeling_tutorial_sets
    WHERE id = p_set_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'tutorial set not found' USING ERRCODE = 'P0002';
  END IF;

  SELECT COUNT(*) INTO v_ok_count
  FROM public.labeling_tutorial_lessons
  WHERE tutorial_set_id = p_set_id
    AND position BETWEEN 1 AND 5
    AND reference_gt IS NOT NULL
    AND prediction_snapshot IS NOT NULL
    AND reference_vlm_review IS NOT NULL
    AND feedback_content IS NOT NULL;

  SELECT COUNT(DISTINCT position) INTO v_distinct_positions
  FROM public.labeling_tutorial_lessons
  WHERE tutorial_set_id = p_set_id;

  IF v_ok_count <> 5 OR v_distinct_positions <> 5 THEN
    RAISE EXCEPTION 'tutorial set incomplete: need 5 complete lessons (positions 1..5)'
      USING ERRCODE = '22023';
  END IF;

  UPDATE public.labeling_tutorial_sets
    SET status = 'archived', updated_at = NOW()
    WHERE status = 'active' AND id <> p_set_id;

  UPDATE public.labeling_tutorial_sets
    SET status = 'active', activated_at = NOW(), updated_at = NOW()
    WHERE id = p_set_id
    RETURNING * INTO v_set;

  RETURN v_set;
END;
$$;

-- ── 7. acknowledge RPC (피드백 확인 → lesson 완료, 5개면 progress 완료) ─
CREATE OR REPLACE FUNCTION public.fn_acknowledge_tutorial_lesson(
  p_attempt_id UUID, p_user_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_att public.labeling_tutorial_attempts%ROWTYPE;
  v_done INTEGER;
  v_total_completed BOOLEAN := FALSE;
BEGIN
  SELECT * INTO v_att FROM public.labeling_tutorial_attempts
    WHERE id = p_attempt_id AND user_id = p_user_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'attempt not found' USING ERRCODE = 'P0002';
  END IF;
  IF v_att.stage NOT IN ('review_submitted', 'completed') THEN
    RAISE EXCEPTION 'feedback not available yet' USING ERRCODE = '22023';
  END IF;

  IF v_att.stage <> 'completed' THEN
    UPDATE public.labeling_tutorial_attempts
      SET stage = 'completed',
          feedback_viewed_at = COALESCE(feedback_viewed_at, NOW()),
          completed_at = NOW()
      WHERE id = p_attempt_id
      RETURNING * INTO v_att;
  END IF;

  SELECT COUNT(*) INTO v_done FROM public.labeling_tutorial_attempts
    WHERE tutorial_set_id = v_att.tutorial_set_id AND user_id = p_user_id
      AND run_no = v_att.run_no AND stage = 'completed';

  IF v_done >= 5 THEN
    UPDATE public.labeling_tutorial_progress
      SET completed_at = COALESCE(completed_at, NOW()), updated_at = NOW()
      WHERE tutorial_set_id = v_att.tutorial_set_id AND user_id = p_user_id;
    v_total_completed := TRUE;
  END IF;

  RETURN jsonb_build_object(
    'attempt', to_jsonb(v_att),
    'tutorial_completed', v_total_completed);
END;
$$;

-- ── 8. reset RPC (run+1, 기존 attempt 보존) ────────────────────────
CREATE OR REPLACE FUNCTION public.fn_reset_tutorial(
  p_set_id UUID, p_user_id UUID, p_owner_id UUID
) RETURNS public.labeling_tutorial_progress
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_p public.labeling_tutorial_progress%ROWTYPE;
BEGIN
  INSERT INTO public.labeling_tutorial_progress
    (tutorial_set_id, user_id, current_run_no, started_at, updated_at)
    VALUES (p_set_id, p_user_id, 1, NOW(), NOW())
  ON CONFLICT (tutorial_set_id, user_id) DO UPDATE
    SET current_run_no = labeling_tutorial_progress.current_run_no + 1,
        started_at = NOW(),
        completed_at = NULL,
        waived_at = NULL,
        waived_by = NULL,
        waiver_reason = NULL,
        updated_at = NOW()
  RETURNING * INTO v_p;
  RETURN v_p;
END;
$$;

-- ── 9. waive RPC (완료 면제, 사유 1~200자 필수, audit 보존) ─────────
CREATE OR REPLACE FUNCTION public.fn_waive_tutorial(
  p_set_id UUID, p_user_id UUID, p_owner_id UUID, p_reason TEXT
) RETURNS public.labeling_tutorial_progress
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_p public.labeling_tutorial_progress%ROWTYPE;
BEGIN
  IF p_reason IS NULL
     OR CHAR_LENGTH(BTRIM(p_reason)) NOT BETWEEN 1 AND 200 THEN
    RAISE EXCEPTION 'waiver reason must be 1..200 chars' USING ERRCODE = '22023';
  END IF;
  INSERT INTO public.labeling_tutorial_progress
    (tutorial_set_id, user_id, current_run_no, started_at,
     waived_at, waived_by, waiver_reason, updated_at)
    VALUES (p_set_id, p_user_id, 1, NOW(), NOW(), p_owner_id, BTRIM(p_reason), NOW())
  ON CONFLICT (tutorial_set_id, user_id) DO UPDATE
    SET waived_at = NOW(),
        waived_by = p_owner_id,
        waiver_reason = BTRIM(p_reason),
        updated_at = NOW()
  RETURNING * INTO v_p;
  RETURN v_p;
END;
$$;

-- ── 10. seed RPC (owner 완료 session → lesson 기준 답 복사, §14-3) ──
-- 실제 clip_id·교육 문구는 owner 가 나중에 실값으로 실행한다(커밋엔 실 UUID 없음, §18).
CREATE OR REPLACE FUNCTION public.fn_seed_tutorial_lesson_from_owner(
  p_set_id UUID, p_position SMALLINT, p_clip_id UUID, p_owner_id UUID,
  p_title TEXT, p_objective TEXT, p_tip TEXT, p_feedback JSONB
) RETURNS public.labeling_tutorial_lessons
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_s public.clip_labeling_sessions%ROWTYPE;
  v_lesson public.labeling_tutorial_lessons%ROWTYPE;
BEGIN
  SELECT * INTO v_s FROM public.clip_labeling_sessions
    WHERE clip_id = p_clip_id AND reviewed_by = p_owner_id AND stage = 'completed';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'owner completed session not found for clip' USING ERRCODE = 'P0002';
  END IF;
  IF v_s.current_gt IS NULL OR v_s.prediction_snapshot IS NULL THEN
    RAISE EXCEPTION 'session missing current_gt or prediction_snapshot' USING ERRCODE = '22023';
  END IF;

  INSERT INTO public.labeling_tutorial_lessons
    (tutorial_set_id, position, clip_id, title, learning_objective, pre_submit_tip,
     reference_gt, prediction_snapshot, reference_vlm_review, feedback_content, updated_at)
    VALUES (p_set_id, p_position, p_clip_id, p_title, p_objective, p_tip,
      v_s.current_gt,
      v_s.prediction_snapshot,
      jsonb_build_object(
        'verdict', v_s.vlm_verdict,
        'error_tags', to_jsonb(v_s.vlm_error_tags),
        'note', v_s.vlm_review_note),
      p_feedback, NOW())
  ON CONFLICT (tutorial_set_id, position) DO UPDATE
    SET clip_id = EXCLUDED.clip_id,
        title = EXCLUDED.title,
        learning_objective = EXCLUDED.learning_objective,
        pre_submit_tip = EXCLUDED.pre_submit_tip,
        reference_gt = EXCLUDED.reference_gt,
        prediction_snapshot = EXCLUDED.prediction_snapshot,
        reference_vlm_review = EXCLUDED.reference_vlm_review,
        feedback_content = EXCLUDED.feedback_content,
        updated_at = NOW()
  RETURNING * INTO v_lesson;
  RETURN v_lesson;
END;
$$;

-- ── 11. RPC 권한 회수 + service_role 부여 ──────────────────────────
DO $$
DECLARE f TEXT;
BEGIN
  FOREACH f IN ARRAY ARRAY[
    'fn_activate_tutorial_set(UUID, UUID)',
    'fn_acknowledge_tutorial_lesson(UUID, UUID)',
    'fn_reset_tutorial(UUID, UUID, UUID)',
    'fn_waive_tutorial(UUID, UUID, UUID, TEXT)',
    'fn_seed_tutorial_lesson_from_owner(UUID, SMALLINT, UUID, UUID, TEXT, TEXT, TEXT, JSONB)'
  ] LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION public.%s FROM PUBLIC;', f);
    EXECUTE format('REVOKE ALL ON FUNCTION public.%s FROM anon;', f);
    EXECUTE format('REVOKE ALL ON FUNCTION public.%s FROM authenticated;', f);
    EXECUTE format('GRANT EXECUTE ON FUNCTION public.%s TO service_role;', f);
  END LOOP;
END $$;

COMMIT;

-- ── 적용 후 검증 쿼리 ──────────────────────────────────────────────
-- SELECT COUNT(*) AS tutorial_client_policies FROM pg_policies
--   WHERE schemaname='public' AND tablename LIKE 'labeling_tutorial_%';
-- 기대값: 0 (client role 정책 없음).
--
-- SELECT tablename, rowsecurity FROM pg_tables
--   WHERE schemaname='public' AND tablename LIKE 'labeling_tutorial_%';
-- 기대값: 4 테이블 모두 rowsecurity = t.

-- ── 롤백 (웹 코드를 먼저 이전한 뒤 실행) ───────────────────────────
-- BEGIN;
-- DROP FUNCTION IF EXISTS public.fn_seed_tutorial_lesson_from_owner(UUID, SMALLINT, UUID, UUID, TEXT, TEXT, TEXT, JSONB);
-- DROP FUNCTION IF EXISTS public.fn_waive_tutorial(UUID, UUID, UUID, TEXT);
-- DROP FUNCTION IF EXISTS public.fn_reset_tutorial(UUID, UUID, UUID);
-- DROP FUNCTION IF EXISTS public.fn_acknowledge_tutorial_lesson(UUID, UUID);
-- DROP FUNCTION IF EXISTS public.fn_activate_tutorial_set(UUID, UUID);
-- DROP TABLE IF EXISTS public.labeling_tutorial_attempts;
-- DROP TABLE IF EXISTS public.labeling_tutorial_progress;
-- DROP TABLE IF EXISTS public.labeling_tutorial_lessons;
-- DROP TABLE IF EXISTS public.labeling_tutorial_sets;
-- COMMIT;
