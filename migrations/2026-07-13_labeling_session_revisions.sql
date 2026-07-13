-- owner 전용 현재 GT 보정 (append-only revision) — 2026-07-13.
--
-- ✅ Supabase 적용 완료 2026-07-13 (MCP apply_migration). rollback probe 통과:
--    원자적 보정 + initial_gt 불변 + 다른 reviewer/짧은 사유 차단, 전량 롤백 검증.
--    advisor: revision 테이블 INFO rls_enabled_no_policy 는 의도된 계약(§10, service_role 전용).
--
-- 라벨링 기준 GT·튜토리얼 UX 하드닝 설계 §7.
-- 최초 blind 답 initial_gt 는 절대 바꾸지 않고(protect_initial_labeling_gt 트리거 유지),
-- owner 가 본인이 검수 완료한 session 의 current_gt / VLM review 만 사유와 함께 보정한다.
-- 보정 전후 값과 behavior_labels mirror 갱신은 하나의 DB 트랜잭션으로 처리한다.
--
-- 계약:
--   1) initial_gt·prediction_snapshot·gt_locked_at·completed_at 는 변경하지 않는다.
--   2) revision 테이블은 RLS ON + client 정책 0건 + service_role 전용(설계 §10).
--   3) RPC 는 service_role 만 실행. Next.js API 가 호출 전 owner(DEV_USER_ID)를 검증한다.
--   4) completed session + reviewed_by = revised_by 만 보정 대상(다른 reviewer·미완료 차단).

BEGIN;

-- ── 1. append-only revision 테이블 (설계 §7.2) ─────────────────────
CREATE TABLE IF NOT EXISTS public.clip_labeling_session_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL
    REFERENCES public.clip_labeling_sessions(id) ON DELETE CASCADE,
  clip_id uuid NOT NULL
    REFERENCES public.camera_clips(id) ON DELETE CASCADE,
  revised_by uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  previous_gt jsonb NOT NULL,       -- 보정 전 current GT
  revised_gt jsonb NOT NULL,        -- 보정 후 current GT
  previous_vlm_review jsonb,        -- 보정 전 verdict/error_tags/note
  revised_vlm_review jsonb,         -- 보정 후 verdict/error_tags/note
  reason text NOT NULL CHECK (char_length(reason) BETWEEN 10 AND 500),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_clip_labeling_session_revisions_session
  ON public.clip_labeling_session_revisions (session_id, created_at DESC);

COMMENT ON TABLE public.clip_labeling_session_revisions IS
  'Append-only audit of owner corrections to current_gt / VLM review. initial_gt stays immutable.';

-- ── 2. RLS ON + service_role 전용 (client 정책 0건, 설계 §10) ───────
ALTER TABLE public.clip_labeling_session_revisions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.clip_labeling_session_revisions FROM PUBLIC;
REVOKE ALL ON TABLE public.clip_labeling_session_revisions FROM anon;
REVOKE ALL ON TABLE public.clip_labeling_session_revisions FROM authenticated;
GRANT ALL ON TABLE public.clip_labeling_session_revisions TO service_role;

-- ── 3. 원자적 보정 RPC (설계 §7.3) ─────────────────────────────────
-- 대상 session 은 clip_id + revised_by 로 서버가 결정한다(§10: session_id/clip_id 를
-- 클라이언트 신뢰 대상으로 쓰지 않음. API 는 URL clipId + bearer owner 만 넘긴다).
-- behavior_labels mirror 값(action/lick_target/note)은 호출부(Next.js)가 revised GT 에서
-- 계산해 넘긴다(mapLickTarget 로직을 TS 한 곳에 유지). initial_gt·prediction_snapshot·
-- gt_locked_at·completed_at 은 이 함수가 건드리지 않는다.
CREATE OR REPLACE FUNCTION public.fn_revise_clip_labeling_session(
  p_clip_id uuid,
  p_revised_by uuid,
  p_revised_gt jsonb,
  p_vlm_verdict text,
  p_vlm_error_tags text[],
  p_vlm_review_note text,
  p_reason text,
  p_action text,
  p_lick_target text,
  p_behavior_note text
) RETURNS public.clip_labeling_sessions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_session public.clip_labeling_sessions%ROWTYPE;
  v_updated public.clip_labeling_sessions%ROWTYPE;
BEGIN
  IF p_reason IS NULL
     OR char_length(p_reason) < 10
     OR char_length(p_reason) > 500 THEN
    RAISE EXCEPTION 'reason must be 10..500 chars' USING ERRCODE = '22023';
  END IF;

  -- 보정 대상은 owner 본인이 검수 완료(stage='completed')한 session 뿐. 잠근다.
  -- (clip_id, reviewed_by) 는 유니크라 한 건이다. 미완료·다른 reviewer·미존재는 모두
  -- 여기서 P0002 (API 가 404 로 매핑).
  SELECT * INTO v_session FROM public.clip_labeling_sessions
    WHERE clip_id = p_clip_id AND reviewed_by = p_revised_by AND stage = 'completed'
    FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'completed session not found for reviewer' USING ERRCODE = 'P0002';
  END IF;

  -- 보정 전후를 append-only 로 박제.
  INSERT INTO public.clip_labeling_session_revisions
    (session_id, clip_id, revised_by, previous_gt, revised_gt,
     previous_vlm_review, revised_vlm_review, reason)
  VALUES (
    v_session.id, v_session.clip_id, p_revised_by,
    v_session.current_gt, p_revised_gt,
    jsonb_build_object(
      'verdict', v_session.vlm_verdict,
      'error_tags', to_jsonb(v_session.vlm_error_tags),
      'note', v_session.vlm_review_note),
    jsonb_build_object(
      'verdict', p_vlm_verdict,
      'error_tags', to_jsonb(COALESCE(p_vlm_error_tags, '{}')),
      'note', p_vlm_review_note),
    p_reason);

  -- current_gt / VLM review 만 갱신. initial_gt 는 protect_initial_labeling_gt 트리거가
  -- 재차 보호한다(여기서도 건드리지 않는다).
  UPDATE public.clip_labeling_sessions
    SET current_gt = p_revised_gt,
        vlm_verdict = p_vlm_verdict,
        vlm_error_tags = COALESCE(p_vlm_error_tags, '{}'),
        vlm_review_note = p_vlm_review_note,
        updated_at = now()
    WHERE id = v_session.id
    RETURNING * INTO v_updated;

  -- behavior_labels mirror 갱신(같은 트랜잭션). gt route 와 동일 upsert 계약.
  INSERT INTO public.behavior_labels
    (clip_id, labeled_by, action, lick_target, note, labeled_at)
  VALUES (v_session.clip_id, p_revised_by, p_action, p_lick_target, p_behavior_note, now())
  ON CONFLICT (clip_id, labeled_by) DO UPDATE
    SET action = EXCLUDED.action,
        lick_target = EXCLUDED.lick_target,
        note = EXCLUDED.note,
        labeled_at = EXCLUDED.labeled_at;

  RETURN v_updated;
END;
$$;

-- ── 4. 함수 실행권한 — service_role 전용 (설계 §10) ────────────────
REVOKE ALL ON FUNCTION public.fn_revise_clip_labeling_session(
  uuid, uuid, jsonb, text, text[], text, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.fn_revise_clip_labeling_session(
  uuid, uuid, jsonb, text, text[], text, text, text, text, text) FROM anon;
REVOKE ALL ON FUNCTION public.fn_revise_clip_labeling_session(
  uuid, uuid, jsonb, text, text[], text, text, text, text, text) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.fn_revise_clip_labeling_session(
  uuid, uuid, jsonb, text, text[], text, text, text, text, text) TO service_role;

COMMIT;

-- ── 검증 (DO 블록 롤백 probe, REPORT 참고) ─────────────────────────
-- 아래는 실제 데이터로 apply 후 트랜잭션 안에서 검증하고 전량 롤백하는 예시다.
-- (1) completed session 보정 → revision 1건 + session.current_gt 갱신 + behavior_labels 갱신 원자성.
-- (2) 보정이 initial_gt 를 바꾸려 하면 protect_initial_labeling_gt 가 차단(회귀).
-- (3) 미완료(stage<>'completed') session 보정 → P0002.
-- (4) 다른 reviewer 의 session 보정(p_revised_by 불일치) → P0002.
-- (5) reason 9자 이하/501자 이상 → 22023.
-- 예:
-- BEGIN;
--   SELECT public.fn_revise_clip_labeling_session(
--     '<clip-uuid>'::uuid, '<owner-uuid>'::uuid,
--     '{"visibility":"visible", ...}'::jsonb,
--     'correct', ARRAY[]::text[], NULL,
--     '기준 GT 대상 오기입 정정: wheel → water_bowl', 'drinking', 'dish', NULL);
--   SELECT count(*) FROM public.clip_labeling_session_revisions
--     WHERE clip_id = '<clip-uuid>'; -- 1
--   SELECT initial_gt = current_gt FROM public.clip_labeling_sessions
--     WHERE clip_id = '<clip-uuid>' AND reviewed_by = '<owner-uuid>'; -- initial 불변 확인
-- ROLLBACK;

-- ── 롤백 ───────────────────────────────────────────────────────────
-- BEGIN;
-- DROP FUNCTION IF EXISTS public.fn_revise_clip_labeling_session(
--   uuid, uuid, jsonb, text, text[], text, text, text, text, text);
-- DROP TABLE IF EXISTS public.clip_labeling_session_revisions;
-- COMMIT;
