-- 튜토리얼 하드닝 4차 후속 마이그레이션 (2026-07-13).
--
-- 3차(_hardening_3.sql)를 CREATE OR REPLACE 로 대체한다(3차 파일은 수정하지 않는다).
-- 3차 대비 바뀐 것 딱 두 가지:
--   (A) NULL 안전 — 모든 의미 검사를 `IF NOT (condition)` 에서 `IF (condition) IS NOT TRUE`
--       로 바꿨다. JSON 키가 없으면 `v_gt->>'x'` 가 NULL 이고, `x = 'y'` 는 NULL,
--       AND 체인 전체가 NULL 이 된다. `NOT (NULL)` 도 NULL 이라 `IF NULL THEN` 은
--       발동하지 않아 → 필드 누락 reference 가 preflight 를 통과해버렸다(구멍).
--       `IS NOT TRUE` 는 NULL·FALSE 를 모두 TRUE 로 판정하므로 필드 누락이면 반드시 막힌다.
--   (B) position 3 강화 — `target <> 'tool'` 만으로는 moving+wheel 같은 잘못된 reference 도
--       통과했다. lesson 3 은 "drinking 의 target 은 물, wheel 은 별도 enrichment" 를
--       가르치므로 reference 는 primary_action='drinking' + target ∈ 물 집합
--       {water,water_bowl,glass,floor,uncertain}(설계 §6.2 규칙 7, DRINKING_TARGETS)이어야 한다.
--
-- 나머지(구조 검사·오류 메시지 형식·ACL)는 3차와 동일하다. 오류 메시지는 여전히
-- clip prefix(8자)·position·사유만 담고 비밀값을 넣지 않는다.
--
-- ✅ Supabase 적용 완료 2026-07-13 (MCP apply_migration). rollback probe 통과:
--    (1) current_gt 에서 primary_action 키를 제거한 세션으로 seed → 22023 차단(NULL 안전).
--    (2) position 3 에 primary moving / target tool reference → 22023 차단.
--    (3) position 3 에 drinking + target water_bowl + wheel reference → 통과(전량 롤백).

BEGIN;

CREATE OR REPLACE FUNCTION public.fn_seed_tutorial_lesson_from_owner(
  p_set_id UUID, p_position SMALLINT, p_clip_id UUID, p_owner_id UUID,
  p_title TEXT, p_objective TEXT, p_tip TEXT, p_feedback JSONB
) RETURNS public.labeling_tutorial_lessons
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_status TEXT;
  v_s public.clip_labeling_sessions%ROWTYPE;
  v_lesson public.labeling_tutorial_lessons%ROWTYPE;
  v_gt JSONB;
  v_fail TEXT;
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

  -- ★ 의미 preflight (설계 §8.2). reference_gt = owner current_gt.
  --   모든 검사는 `(양성 조건) IS NOT TRUE` 형태 — 키 누락으로 NULL 이 나오면 반드시 막는다.
  v_gt := v_s.current_gt;
  CASE p_position
    WHEN 1 THEN
      IF (
        v_gt->>'visibility' = 'absent'
        AND v_gt->>'primary_action' = 'unseen'
        AND jsonb_array_length(COALESCE(v_gt->'observed_actions', '[]'::jsonb)) = 0
        AND jsonb_array_length(COALESCE(v_gt->'segments', '[]'::jsonb)) = 0
        AND v_gt->>'target' = 'none'
      ) IS NOT TRUE THEN
        v_fail := 'position 1 must be absent/unseen with empty observed+segments and target none';
      END IF;
    WHEN 2 THEN
      IF (
        v_gt->>'visibility' IN ('visible', 'partial')
        AND v_gt->>'primary_action' = 'moving'
        AND (v_gt->'observed_actions') ? 'moving'
        AND EXISTS (
          SELECT 1 FROM jsonb_array_elements(COALESCE(v_gt->'segments', '[]'::jsonb)) seg
          WHERE seg->>'action' = 'moving')
      ) IS NOT TRUE THEN
        v_fail := 'position 2 must be visible/partial moving with a moving segment';
      END IF;
    WHEN 3 THEN
      -- drinking+wheel: 대표 행동은 drinking, target 은 물 집합(wheel/tool 아님),
      -- wheel 은 enrichment_object 로 따로 기록(설계 §5.5·§6.2 규칙 7).
      IF (
        v_gt->>'primary_action' = 'drinking'
        AND v_gt->>'target' IN ('water', 'water_bowl', 'glass', 'floor', 'uncertain')
        AND (v_gt->'observed_actions') ? 'wheel_interaction'
        AND v_gt->>'enrichment_object' = 'wheel'
        AND jsonb_array_length(COALESCE(v_gt->'interaction_types', '[]'::jsonb)) >= 1
        AND jsonb_array_length(COALESCE(v_gt->'observed_actions', '[]'::jsonb)) >= 2
      ) IS NOT TRUE THEN
        v_fail := 'position 3 must be drinking+wheel: primary drinking, target in {water,water_bowl,glass,floor,uncertain}, wheel interaction + enrichment wheel + >=1 interaction type + >=2 observed actions';
      END IF;
    WHEN 4 THEN
      IF (
        v_gt->>'primary_action' = 'hand_feeding'
        AND ((v_gt->'observed_actions') ? 'licking' OR (v_gt->'observed_actions') ? 'prey_capture')
        AND v_gt->>'target' IN ('hand', 'tool')
        AND (v_gt->'context_tags') ? 'human'
      ) IS NOT TRUE THEN
        v_fail := 'position 4 must be hand_feeding (licking/prey_capture + target hand/tool + context human)';
      END IF;
    WHEN 5 THEN
      IF (
        v_s.prediction_snapshot->>'action' = 'shedding'
        AND v_gt->>'primary_action' <> 'shedding'
        AND v_s.vlm_verdict = 'incorrect'
        AND COALESCE(array_length(v_s.vlm_error_tags, 1), 0) >= 1
      ) IS NOT TRUE THEN
        v_fail := 'position 5 must be a VLM shedding misjudge (VLM action shedding, human primary != shedding, verdict incorrect, >=1 error tag)';
      END IF;
    ELSE
      v_fail := 'position must be 1..5';
  END CASE;

  IF v_fail IS NOT NULL THEN
    RAISE EXCEPTION 'lesson % (clip %) failed semantic preflight: %',
      p_position, left(p_clip_id::text, 8), v_fail
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

-- CREATE OR REPLACE 는 기존 ACL 을 보존하지만 명시적으로 재부여(방어).
REVOKE ALL ON FUNCTION public.fn_seed_tutorial_lesson_from_owner(UUID, SMALLINT, UUID, UUID, TEXT, TEXT, TEXT, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_seed_tutorial_lesson_from_owner(UUID, SMALLINT, UUID, UUID, TEXT, TEXT, TEXT, JSONB) TO service_role;

COMMIT;

-- ── 검증 (DO 블록 롤백, REPORT 참고) ──────────────────────────────
-- 실제 vlm_reviewed 세션 하나를 빌려 draft set 에 seed 를 시도하고 전량 롤백한다.
--  (1) current_gt 에서 primary_action 키 제거 → 어떤 position 이든 22023 (NULL 안전).
--  (2) position 3 에 primary_action='moving' / target='tool' → 22023.
--  (3) position 3 에 primary_action='drinking' + target='water_bowl' + wheel → 통과.

-- ── 롤백 ───────────────────────────────────────────────────────────
-- 3차 정의로 되돌리려면 `_hardening_3.sql` 의 fn_seed_tutorial_lesson_from_owner 를 재적용한다.
