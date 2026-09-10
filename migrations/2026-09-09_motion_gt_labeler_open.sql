-- motion v3 행동 GT 라벨링을 승인 라벨러에게 개방 (owner 결정 2026-09-08).
--
-- 배경: v4 "의미있는 행동" 체크로 모은 영상을 팀원이 기존 행동 GT 화면(/labeling/motion/<id>)에서 직접
-- 라벨링한다. 이중 blind 교차검증 트랙은 2026-09-08 퇴역했으므로 "라벨러가 기존 정답을 본다"는 우려는
-- 더 이상 경계가 아니다. 웹 가드(requireOwner→requireLabelingAccess)와 짝으로 적용한다.
--
-- 바뀌는 것 (fn_lock_motion_clip_gt):
-- - 라벨러도 triage 가 없음/unreviewed/label 인 clip 의 GT 를 잠글 수 있다(이전엔 label 만, 아니면 PT403).
-- - hold/skip 으로 접힌 clip 은 owner·라벨러 모두 PT424(이전엔 owner 만 PT424, 라벨러는 PT403).
-- - 잠글 때 triage 가 label 이 아니면 label 로 원자 전환하는 건 같고, 이벤트 종류만 행위자에 따라
--   owner_started_labeling / labeler_started_labeling 으로 나눈다(감사 추적).
-- 안 바뀌는 것: 세션 (clip, reviewer) 유니크·initial_gt 불변(PT423)·미디어 없음(PT422)·prediction 은 서버 결정.
BEGIN;

-- 이벤트 종류에 labeler_started_labeling 추가. 인라인 CHECK 의 자동 이름에 의존하지 않고 컬럼 기준으로 찾아 교체한다.
DO $$
DECLARE c text;
BEGIN
  FOR c IN
    SELECT conname FROM pg_constraint
     WHERE conrelid = 'public.motion_clip_labeling_triage_events'::regclass
       AND contype = 'c'
       AND pg_get_constraintdef(oid) LIKE '%event_type%'
  LOOP
    EXECUTE format('ALTER TABLE public.motion_clip_labeling_triage_events DROP CONSTRAINT %I', c);
  END LOOP;
END $$;
ALTER TABLE public.motion_clip_labeling_triage_events
  ADD CONSTRAINT motion_clip_labeling_triage_events_event_type_check
  CHECK (event_type IN ('owner_labeled','owner_held','owner_skipped','owner_reset','owner_started_labeling','labeler_started_labeling'));

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

  -- owner 가 hold/skip 으로 접은 clip 은 누구도 GT 잠금으로 결정을 되돌리지 못한다(설계 §5.2).
  IF v_triage.clip_id IS NOT NULL AND v_triage.owner_decision IN ('hold','skip') THEN
    RAISE EXCEPTION 'decision_blocks_labeling' USING ERRCODE = 'PT424';
  END IF;

  -- 이미 잠긴 세션이 있으면 재잠금 거부(initial_gt 불변 계약, 설계 §7.3).
  SELECT * INTO v_session FROM public.motion_clip_labeling_sessions
    WHERE clip_id = p_clip_id AND reviewed_by = p_reviewer_id FOR UPDATE;
  IF FOUND AND v_session.initial_gt IS NOT NULL THEN
    RAISE EXCEPTION 'gt_already_locked' USING ERRCODE = 'PT423';
  END IF;

  -- 아직 label 이 아니면 triage 를 label 로 원자 전환. 행위자에 따라 이벤트 종류를 나눈다.
  IF v_triage.clip_id IS NULL OR v_triage.owner_decision IS DISTINCT FROM 'label' THEN
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
    VALUES (p_clip_id,
            CASE WHEN p_is_owner THEN 'owner_started_labeling' ELSE 'labeler_started_labeling' END,
            p_reviewer_id, v_before, to_jsonb(v_triage), NULL);
  END IF;

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

REVOKE ALL ON FUNCTION public.fn_lock_motion_clip_gt(uuid, uuid, boolean, jsonb, jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_lock_motion_clip_gt(uuid, uuid, boolean, jsonb, jsonb) TO service_role;

COMMIT;
