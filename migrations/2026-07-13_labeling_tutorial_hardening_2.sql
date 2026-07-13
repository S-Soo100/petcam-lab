-- 튜토리얼 하드닝 2차 후속 마이그레이션 (2026-07-13).
--
-- 1차 `_hardening.sql` 는 이미 production 에 적용됐으므로 수정하지 않고 이 2차 후속
-- 마이그레이션으로 트리거를 강화한다.
--
-- 1차 트리거의 두 허점을 막는다:
--   (a) 상태 판단이 COALESCE(NEW.tutorial_set_id, OLD.tutorial_set_id) 였다 →
--       active lesson 의 tutorial_set_id 를 draft set 으로 바꾸면 NEW 가 draft 라
--       차단을 우회할 수 있었다. **판단을 반드시 OLD.tutorial_set_id 기준**으로 바꾼다.
--   (b) 차단 대상이 clip/reference/prediction/reference_vlm_review/feedback 5필드뿐이었다 →
--       tutorial_set_id/position/title/learning_objective/pre_submit_tip 변경 우회가 가능했다.
--       **10필드 전체**(정답 + 배치 필드)를 차단한다.
--
-- 트리거 정의(BEFORE UPDATE OR DELETE)는 1차와 동일하므로 함수 본문만 교체한다.

BEGIN;

CREATE OR REPLACE FUNCTION public.protect_activated_tutorial_lesson()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  v_status TEXT;
BEGIN
  -- 판단은 반드시 lesson 이 "현재 속한" set(OLD)의 상태 기준. active lesson 을
  -- draft set 으로 옮기는 우회(NEW.tutorial_set_id=draft)를 이 지점에서 차단한다.
  SELECT status INTO v_status FROM public.labeling_tutorial_sets
    WHERE id = OLD.tutorial_set_id;

  IF v_status IN ('active', 'archived') THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'activated tutorial lesson is immutable (delete blocked)';
    END IF;
    -- 정답 스냅샷 + 배치 필드(set/position/문구) 모두 잠근다.
    IF NEW.tutorial_set_id IS DISTINCT FROM OLD.tutorial_set_id
       OR NEW.position IS DISTINCT FROM OLD.position
       OR NEW.clip_id IS DISTINCT FROM OLD.clip_id
       OR NEW.title IS DISTINCT FROM OLD.title
       OR NEW.learning_objective IS DISTINCT FROM OLD.learning_objective
       OR NEW.pre_submit_tip IS DISTINCT FROM OLD.pre_submit_tip
       OR NEW.reference_gt IS DISTINCT FROM OLD.reference_gt
       OR NEW.prediction_snapshot IS DISTINCT FROM OLD.prediction_snapshot
       OR NEW.reference_vlm_review IS DISTINCT FROM OLD.reference_vlm_review
       OR NEW.feedback_content IS DISTINCT FROM OLD.feedback_content THEN
      RAISE EXCEPTION 'activated tutorial lesson is immutable (set/position/clip/title/objective/tip/reference/prediction/feedback locked)';
    END IF;
  END IF;

  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

COMMIT;

-- ── 검증 (DO 블록 롤백, REPORT 참고) ──────────────────────────────
-- active lesson 을 (1) draft set 으로 이동, (2) position 변경, (3) title 변경,
-- (4) reference_gt 변경, (5) 삭제 — 각각 차단되는지 확인 후 전량 롤백한다.

-- ── 롤백 ───────────────────────────────────────────────────────────
-- 함수를 1차 정의로 되돌리려면 `_hardening.sql` 의 protect_activated_tutorial_lesson
-- 정의를 재적용한다(트리거는 그대로 유지).
