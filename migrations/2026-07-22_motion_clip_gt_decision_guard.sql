-- motion_clips 운영 라벨링 v3 — 제외·보류 GT guard (결함 수정) — 2026-07-22.
--
-- 설계 정본: docs/superpowers/specs/2026-07-22-motion-skip-gt-guard-design.md
-- 구현계획:   docs/superpowers/plans/2026-07-22-motion-skip-gt-guard.md Task 2
--
-- 왜 이 migration 인가(설계 §1·§2):
--   owner 가 상세 화면에서 `제외`(skip)/`보류`(hold)를 누른 뒤 같은 화면에서 사람 판정을
--   저장하면, fn_lock_motion_clip_gt 가 triage 를 무조건 label 로 원자 전환하면서 결정을
--   조용히 덮어쓴다(production 감사 6건: owner_skipped → owner_started_labeling → label).
--   최종 경합 경계를 DB 에서 강제해, owner 이고 기존 triage 가 hold/skip 이면 세션을 쓰기
--   전에 PT424 로 거부한다. `unreviewed`(row 없음/owner_decision NULL) 와 `label` 은 기존
--   흐름 그대로다.
--
-- forward-only:
--   원본 2026-07-22_motion_clip_labeling_v3.sql 을 수정하지 않는다. 이 파일은 동일 시그니처의
--   fn_lock_motion_clip_gt 를 CREATE OR REPLACE 로 교체(idempotent)하며, 기존 lock 순서·media
--   검증(PT422)·labeler 권한(PT403)·initial GT 불변·prediction snapshot·session upsert 계약을
--   글자 그대로 보존하고 guard 한 블록만 추가한다. 실행 권한은 CREATE OR REPLACE 가 보존한다.
--
-- 에러 계약(추가된 안정 SQLSTATE — API 가 409 로 매핑):
--   PT424 decision_blocks_labeling → 409 (owner 가 hold/skip 인 clip 을 GT 잠금 시도)
--
-- 롤백: 이 파일을 되돌리려면 원본 migration 의 fn_lock_motion_clip_gt 정의를 다시
--   CREATE OR REPLACE 로 적용한다(별도 forward migration 으로만; 원본 파일 편집 금지).

BEGIN;

-- ── fn_lock_motion_clip_gt 재정의 (PT424 guard 추가) ──────────────────
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

  -- 결함 수정(설계 §5.2): owner 가 이미 hold/skip 으로 접은 clip 은 GT 잠금이 결정을
  -- 조용히 label 로 되돌리지 못하게, 세션/이벤트를 쓰기 전에 거부한다. labeler 는 아래
  -- 권한 검사에서 이미 PT403 으로 걸리므로 owner 흐름만 대상으로 한다. `unreviewed`
  -- (row 없음/owner_decision NULL) 와 `label` 은 통과시킨다.
  IF p_is_owner
     AND v_triage.clip_id IS NOT NULL
     AND v_triage.owner_decision IN ('hold','skip') THEN
    RAISE EXCEPTION 'decision_blocks_labeling' USING ERRCODE = 'PT424';
  END IF;

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

-- 실행 권한은 CREATE OR REPLACE 가 보존하지만, 안전을 위해 service_role 전용 계약을 재확인한다.
REVOKE ALL ON FUNCTION public.fn_lock_motion_clip_gt(
  uuid, uuid, boolean, jsonb, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_lock_motion_clip_gt(
  uuid, uuid, boolean, jsonb, jsonb) TO service_role;

COMMIT;

-- ── 검증 (트랜잭션 롤백 probe, REPORT 참고) ──────────────────────────
-- 아래는 apply 후 트랜잭션 안에서 검증하고 전량 롤백하는 예시다. <clip*>/<owner> 대입.
-- BEGIN;
--   -- skip 결정 clip 에 owner GT 잠금 시도 → PT424, 세션/이벤트 delta 0
--   SELECT public.fn_decide_motion_clip_labeling('<clip-skip>'::uuid, '<owner>'::uuid, 'skip', NULL, NULL);
--   SELECT public.fn_lock_motion_clip_gt('<clip-skip>'::uuid, '<owner>'::uuid, true,
--     '{"visibility":"visible"}'::jsonb, NULL);                                   -- PT424 decision_blocks_labeling
--   -- hold 결정 clip 도 동일 → PT424
--   SELECT public.fn_decide_motion_clip_labeling('<clip-hold>'::uuid, '<owner>'::uuid, 'hold', NULL, NULL);
--   SELECT public.fn_lock_motion_clip_gt('<clip-hold>'::uuid, '<owner>'::uuid, true,
--     '{"visibility":"visible"}'::jsonb, NULL);                                   -- PT424 decision_blocks_labeling
--   -- unreviewed owner 는 기존처럼 label 전환 + 세션 gt_locked
--   SELECT public.fn_lock_motion_clip_gt('<clip-unreviewed>'::uuid, '<owner>'::uuid, true,
--     '{"visibility":"visible"}'::jsonb, NULL);
--   SELECT owner_decision FROM public.motion_clip_labeling_triage WHERE clip_id='<clip-unreviewed>'; -- 'label'
--   SELECT stage FROM public.motion_clip_labeling_sessions
--     WHERE clip_id='<clip-unreviewed>' AND reviewed_by='<owner>';                -- 'gt_locked'
-- ROLLBACK;  -- 모든 probe row 0 로 복귀

-- ── 롤백 (별도 forward migration 으로만; 이 파일·원본 파일 편집 금지) ──
-- 원본 2026-07-22_motion_clip_labeling_v3.sql §9 의 fn_lock_motion_clip_gt 정의(guard 없음)를
-- CREATE OR REPLACE 로 다시 적용하면 이 결함 수정 이전 동작으로 복귀한다.
