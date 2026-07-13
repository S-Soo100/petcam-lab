-- 튜토리얼 하드닝 후속 마이그레이션 (2026-07-13).
--
-- 원본 `2026-07-13_labeling_tutorial.sql` 는 이미 production 에 적용됐으므로 수정하지 않고
-- 이 후속 마이그레이션으로 무결성을 강화한다.
--
-- 1) active/archived lesson 의 clip/reference_gt/prediction/reference_vlm_review/feedback
--    변경·삭제를 DB trigger 로 차단(활성화 뒤 정답 스냅샷 불변, 설계 §9).
-- 2) seed 는 draft set 에만 허용하고 owner completed session 의 vlm_verdict·
--    completion_reason='vlm_reviewed'·current_gt·prediction_snapshot·비어있지 않은 feedback 검사.
-- 3) activation 은 draft set 에만 허용하고 5개 lesson 의 VLM verdict·비어있지 않은 feedback 완전성 검사.

BEGIN;

-- ── 1. active/archived lesson 정답 불변 트리거 ─────────────────────
CREATE OR REPLACE FUNCTION public.protect_activated_tutorial_lesson()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  v_status TEXT;
BEGIN
  SELECT status INTO v_status FROM public.labeling_tutorial_sets
    WHERE id = COALESCE(NEW.tutorial_set_id, OLD.tutorial_set_id);
  IF v_status IN ('active', 'archived') THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'activated tutorial lesson is immutable (delete blocked)';
    END IF;
    IF NEW.clip_id IS DISTINCT FROM OLD.clip_id
       OR NEW.reference_gt IS DISTINCT FROM OLD.reference_gt
       OR NEW.prediction_snapshot IS DISTINCT FROM OLD.prediction_snapshot
       OR NEW.reference_vlm_review IS DISTINCT FROM OLD.reference_vlm_review
       OR NEW.feedback_content IS DISTINCT FROM OLD.feedback_content THEN
      RAISE EXCEPTION 'activated tutorial lesson content is immutable (clip/reference/prediction/feedback)';
    END IF;
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS protect_activated_tutorial_lesson
  ON public.labeling_tutorial_lessons;
CREATE TRIGGER protect_activated_tutorial_lesson
BEFORE UPDATE OR DELETE ON public.labeling_tutorial_lessons
FOR EACH ROW EXECUTE FUNCTION public.protect_activated_tutorial_lesson();

-- ── 2. seed RPC 하드닝 (draft-only + owner VLM review 완전성) ───────
CREATE OR REPLACE FUNCTION public.fn_seed_tutorial_lesson_from_owner(
  p_set_id UUID, p_position SMALLINT, p_clip_id UUID, p_owner_id UUID,
  p_title TEXT, p_objective TEXT, p_tip TEXT, p_feedback JSONB
) RETURNS public.labeling_tutorial_lessons
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_status TEXT;
  v_s public.clip_labeling_sessions%ROWTYPE;
  v_lesson public.labeling_tutorial_lessons%ROWTYPE;
BEGIN
  -- lesson 은 draft set 에만 seed 한다(활성/보관 set 은 불변).
  SELECT status INTO v_status FROM public.labeling_tutorial_sets WHERE id = p_set_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'tutorial set not found' USING ERRCODE = 'P0002';
  END IF;
  IF v_status <> 'draft' THEN
    RAISE EXCEPTION 'lessons can only be seeded into a draft set' USING ERRCODE = '22023';
  END IF;

  -- 비어있지 않은 feedback 필수.
  IF p_feedback IS NULL
     OR jsonb_typeof(p_feedback) <> 'object'
     OR p_feedback = '{}'::jsonb THEN
    RAISE EXCEPTION 'feedback_content must be a non-empty JSON object' USING ERRCODE = '22023';
  END IF;

  -- owner 가 완료한 session 이어야 하고, VLM review 를 실제로 남겼어야 한다.
  SELECT * INTO v_s FROM public.clip_labeling_sessions
    WHERE clip_id = p_clip_id AND reviewed_by = p_owner_id AND stage = 'completed';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'owner completed session not found for clip' USING ERRCODE = 'P0002';
  END IF;
  IF v_s.current_gt IS NULL OR v_s.prediction_snapshot IS NULL THEN
    RAISE EXCEPTION 'session missing current_gt or prediction_snapshot' USING ERRCODE = '22023';
  END IF;
  IF v_s.vlm_verdict IS NULL OR v_s.completion_reason IS DISTINCT FROM 'vlm_reviewed' THEN
    RAISE EXCEPTION 'session has no VLM review (need vlm_verdict and completion_reason=vlm_reviewed)'
      USING ERRCODE = '22023';
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

-- ── 3. activation RPC 하드닝 (draft-only + verdict/feedback 완전성) ─
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
  IF v_set.status <> 'draft' THEN
    RAISE EXCEPTION 'only a draft tutorial set can be activated' USING ERRCODE = '22023';
  END IF;

  -- position 1..5 · 기준 GT/prediction · VLM verdict 존재 · 비어있지 않은 feedback.
  SELECT COUNT(*) INTO v_ok_count
  FROM public.labeling_tutorial_lessons
  WHERE tutorial_set_id = p_set_id
    AND position BETWEEN 1 AND 5
    AND reference_gt IS NOT NULL
    AND prediction_snapshot IS NOT NULL
    AND reference_vlm_review IS NOT NULL
    AND (reference_vlm_review ->> 'verdict') IS NOT NULL
    AND feedback_content IS NOT NULL
    AND jsonb_typeof(feedback_content) = 'object'
    AND feedback_content <> '{}'::jsonb;

  SELECT COUNT(DISTINCT position) INTO v_distinct_positions
  FROM public.labeling_tutorial_lessons
  WHERE tutorial_set_id = p_set_id;

  IF v_ok_count <> 5 OR v_distinct_positions <> 5 THEN
    RAISE EXCEPTION 'tutorial set incomplete: need 5 lessons (positions 1..5) with reference GT/prediction/VLM verdict/non-empty feedback'
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

-- CREATE OR REPLACE 는 기존 ACL 을 보존하지만 명시적으로 재부여(방어).
REVOKE ALL ON FUNCTION public.fn_seed_tutorial_lesson_from_owner(UUID, SMALLINT, UUID, UUID, TEXT, TEXT, TEXT, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_seed_tutorial_lesson_from_owner(UUID, SMALLINT, UUID, UUID, TEXT, TEXT, TEXT, JSONB) TO service_role;
REVOKE ALL ON FUNCTION public.fn_activate_tutorial_set(UUID, UUID) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_activate_tutorial_set(UUID, UUID) TO service_role;

COMMIT;

-- ── 검증 ───────────────────────────────────────────────────────────
-- SELECT tgname FROM pg_trigger WHERE tgrelid = 'public.labeling_tutorial_lessons'::regclass;
--   기대: protect_activated_tutorial_lesson 존재.
-- 불변 트리거 동작은 DO 블록(롤백)으로 검증한다(REPORT 참고).

-- ── 롤백 ───────────────────────────────────────────────────────────
-- BEGIN;
-- DROP TRIGGER IF EXISTS protect_activated_tutorial_lesson ON public.labeling_tutorial_lessons;
-- DROP FUNCTION IF EXISTS public.protect_activated_tutorial_lesson();
-- -- seed/activation 함수는 원본 정의로 되돌리려면 원본 마이그레이션의 정의를 재적용한다.
-- COMMIT;
