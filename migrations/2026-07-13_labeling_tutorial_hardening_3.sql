-- 튜토리얼 하드닝 3차 후속 마이그레이션 (2026-07-13).
--
-- ✅ Supabase 적용 완료 2026-07-13 (MCP apply_migration). preflight probe 통과:
--    mismatched position seed 호출이 'failed semantic preflight' 22023 로 차단됨(전량 롤백).
--
-- 1·2차 하드닝은 구조적 완전성(draft-only, owner completed session, verdict, 비어있지 않은
-- feedback)만 검사했다. lesson 목적과 reference GT 가 의미적으로 맞는지는 막지 못했다
-- (설계 §8: seed 사전검사). 이 3차는 seed RPC 를 재정의해 position 별 v1 lesson 의미 검사를
-- 추가한다. 하나라도 실패하면 INSERT 전에 transaction 을 중단(fail-loud)한다.
--
-- 검사(설계 §8.2, reference_gt = owner current_gt):
--   1 가시성·unseen  : absent + unseen + observed/segments 비어있음 + target none
--   2 일반 이동       : visible/partial + primary moving + observed moving + moving segment
--   3 wheel evidence  : wheel_interaction + enrichment wheel + interaction type>=1 + target<>tool + observed>=2
--   4 사람 급여       : primary hand_feeding + (licking|prey_capture) + target hand/tool + context human
--   5 VLM 오판 검수   : VLM action shedding + human primary<>shedding + verdict incorrect + error tag>=1
--
-- 오류 메시지는 clip prefix(8자)·position·사유만 담고 비밀값은 넣지 않는다.
-- 1차 하드닝 대비 추가된 것은 "-- ★ 의미 preflight" 블록뿐, 나머지는 동일하다.

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
  v_gt := v_s.current_gt;
  CASE p_position
    WHEN 1 THEN
      IF NOT (
        v_gt->>'visibility' = 'absent'
        AND v_gt->>'primary_action' = 'unseen'
        AND jsonb_array_length(COALESCE(v_gt->'observed_actions', '[]'::jsonb)) = 0
        AND jsonb_array_length(COALESCE(v_gt->'segments', '[]'::jsonb)) = 0
        AND v_gt->>'target' = 'none'
      ) THEN
        v_fail := 'position 1 must be absent/unseen with empty observed+segments and target none';
      END IF;
    WHEN 2 THEN
      IF NOT (
        v_gt->>'visibility' IN ('visible', 'partial')
        AND v_gt->>'primary_action' = 'moving'
        AND (v_gt->'observed_actions') ? 'moving'
        AND EXISTS (
          SELECT 1 FROM jsonb_array_elements(COALESCE(v_gt->'segments', '[]'::jsonb)) seg
          WHERE seg->>'action' = 'moving')
      ) THEN
        v_fail := 'position 2 must be visible/partial moving with a moving segment';
      END IF;
    WHEN 3 THEN
      IF NOT (
        (v_gt->'observed_actions') ? 'wheel_interaction'
        AND v_gt->>'enrichment_object' = 'wheel'
        AND jsonb_array_length(COALESCE(v_gt->'interaction_types', '[]'::jsonb)) >= 1
        AND v_gt->>'target' <> 'tool'
        AND jsonb_array_length(COALESCE(v_gt->'observed_actions', '[]'::jsonb)) >= 2
      ) THEN
        v_fail := 'position 3 must be wheel interaction (enrichment wheel + >=1 interaction type + target != tool + >=2 observed actions)';
      END IF;
    WHEN 4 THEN
      IF NOT (
        v_gt->>'primary_action' = 'hand_feeding'
        AND ((v_gt->'observed_actions') ? 'licking' OR (v_gt->'observed_actions') ? 'prey_capture')
        AND v_gt->>'target' IN ('hand', 'tool')
        AND (v_gt->'context_tags') ? 'human'
      ) THEN
        v_fail := 'position 4 must be hand_feeding (licking/prey_capture + target hand/tool + context human)';
      END IF;
    WHEN 5 THEN
      IF NOT (
        v_s.prediction_snapshot->>'action' = 'shedding'
        AND v_gt->>'primary_action' <> 'shedding'
        AND v_s.vlm_verdict = 'incorrect'
        AND COALESCE(array_length(v_s.vlm_error_tags, 1), 0) >= 1
      ) THEN
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
-- draft set + 각 position 의 owner completed session 을 만든 뒤:
--  (1) 올바른 reference GT 로 seed → 성공.
--  (2) position 3 clip 의 target 을 tool 로 바꾸면 → 'failed semantic preflight' 22023.
--  (3) position 4 clip 의 context human 을 빼면 → 22023.
-- 각각 확인 후 전량 롤백한다.

-- ── 롤백 ───────────────────────────────────────────────────────────
-- 함수를 2차 하드닝 정의(의미 preflight 없음)로 되돌리려면 `_hardening.sql` 의
-- fn_seed_tutorial_lesson_from_owner 정의를 재적용한다.
