-- 짧은 오류 영상 visibility-first 실제 DB probe (adversarial runtime verification).
--
-- 정적 텍스트 테스트로는 못 잡는 런타임 정확성을 non-empty 합성 row 로 검증한다. 일회용
-- short_visibility_probe_* DB 에서만 실행되며 BEGIN … ROLLBACK 으로 합성 row 를 전량 되돌린다.
-- 러너가 rollback 뒤 residue=0 을 재확인한다.
--
-- 필수 시나리오(설계 §7 / 계획 Task 2):
--   A. 복구가 사람 판정을 절대 안 바꾼다               (RESTORE_TRIAGE_IMMUTABLE_OK)
--      1. skip triage + quarantined → restore 후 triage md5 pre==post
--      2. label triage + quarantined → restore 후 triage md5 pre==post
--      3. triage 없음 → restore 후에도 triage 없음
--      4. quarantined → restored + owner_restored system event 정확히 1, triage_event 0
--      5. active lease → PT409, exclusion fingerprint 불변(state quarantined 유지)
--   B. 앱 RLS 가시성                                     (APP_RLS_VISIBILITY_OK)
--      6. authenticated Owner: quarantined/media_deleted 0, restored/candidate visible
--      7. 다른 Owner clip 은 계속 숨김(A↔B)
--      8. service_role 은 전량 read(운영/감사)
--   9. rollback 후 잔여 row 0                            (러너가 확인)

BEGIN;

-- ── 공통 fixture ─────────────────────────────────────────────────────
-- Owner A / Owner B.
INSERT INTO auth.users (id) VALUES
  ('00000000-0000-4000-8000-0000000000a1'),   -- Owner A
  ('00000000-0000-4000-8000-0000000000a2');   -- Owner B

INSERT INTO public.cameras (id, name) VALUES
  ('00000000-0000-4000-8000-0000000000c1', 'probe-P4-Cam2-dev'),   -- 정책 카메라
  ('00000000-0000-4000-8000-0000000000c2', 'probe-other-cam');     -- 정책 없음(사용 안 함)

INSERT INTO public.camera_short_clip_policies (
  camera_id, candidate_under_sec, auto_exclude_display_seconds,
  retention_hours, rule_version, enabled, created_by, updated_by
) VALUES (
  '00000000-0000-4000-8000-0000000000c1', 15, ARRAY[4,11],
  168, 'short-device-error-v1', true,
  '00000000-0000-4000-8000-0000000000a1', '00000000-0000-4000-8000-0000000000a1'
);

-- clip fixtures. 표시 4초(=display 4) → 정책 매칭 → quarantine 대상. d8/d9 는 12초 → candidate.
-- owner_id 로 RLS 소유자를 명시한다(d1~d8=A, d9=B). 전부 nonblank r2_key.
INSERT INTO public.motion_clips (id, camera_id, started_at, duration_sec, r2_key, owner_id) VALUES
  ('00000000-0000-4000-8000-0000000000d1', '00000000-0000-4000-8000-0000000000c1', '2026-07-24 00:00:01+00', 4.0,  'terra-clips/clips/d1.mp4', '00000000-0000-4000-8000-0000000000a1'),
  ('00000000-0000-4000-8000-0000000000d2', '00000000-0000-4000-8000-0000000000c1', '2026-07-24 00:00:02+00', 4.0,  'terra-clips/clips/d2.mp4', '00000000-0000-4000-8000-0000000000a1'),
  ('00000000-0000-4000-8000-0000000000d3', '00000000-0000-4000-8000-0000000000c1', '2026-07-24 00:00:03+00', 4.0,  'terra-clips/clips/d3.mp4', '00000000-0000-4000-8000-0000000000a1'),
  ('00000000-0000-4000-8000-0000000000d4', '00000000-0000-4000-8000-0000000000c1', '2026-07-24 00:00:04+00', 4.0,  'terra-clips/clips/d4.mp4', '00000000-0000-4000-8000-0000000000a1'),
  ('00000000-0000-4000-8000-0000000000d5', '00000000-0000-4000-8000-0000000000c1', '2026-07-24 00:00:05+00', 4.0,  'terra-clips/clips/d5.mp4', '00000000-0000-4000-8000-0000000000a1'),
  ('00000000-0000-4000-8000-0000000000d6', '00000000-0000-4000-8000-0000000000c1', '2026-07-24 00:00:06+00', 4.0,  'terra-clips/clips/d6.mp4', '00000000-0000-4000-8000-0000000000a1'),
  ('00000000-0000-4000-8000-0000000000d7', '00000000-0000-4000-8000-0000000000c1', '2026-07-24 00:00:07+00', 4.0,  'terra-clips/clips/d7.mp4', '00000000-0000-4000-8000-0000000000a1'),
  ('00000000-0000-4000-8000-0000000000d8', '00000000-0000-4000-8000-0000000000c1', '2026-07-24 00:00:08+00', 12.0, 'terra-clips/clips/d8.mp4', '00000000-0000-4000-8000-0000000000a1'),
  ('00000000-0000-4000-8000-0000000000d9', '00000000-0000-4000-8000-0000000000c1', '2026-07-24 00:00:09+00', 12.0, 'terra-clips/clips/d9.mp4', '00000000-0000-4000-8000-0000000000a2');

-- 격리(quarantine)는 triage 를 붙이기 "전"에 해야 한다. label triage 가 먼저 있으면 fn_record 가
-- protected(deletion_blocked) 로 처리하기 때문(설계 보호 술어). d1~d7 을 표시 4초로 quarantine,
-- d8/d9 는 12초 → genuine candidate exclusion.
SELECT public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d1', now(), true);
SELECT public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d2', now(), true);
SELECT public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d3', now(), true);
SELECT public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d4', now(), true);
SELECT public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d5', now(), true);
SELECT public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d6', now(), true);
SELECT public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d7', now(), true);
SELECT public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d8', now(), true);
SELECT public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d9', now(), true);

-- 격리 이후 사람 판정(triage)을 붙인다. d1=skip, d2=label. (d3 는 무판정 유지.)
INSERT INTO public.motion_clip_labeling_triage (clip_id, owner_decision, decided_by, decided_at, decision_note) VALUES
  ('00000000-0000-4000-8000-0000000000d1', 'skip', '00000000-0000-4000-8000-0000000000a1', now(), NULL),
  ('00000000-0000-4000-8000-0000000000d2', 'label', '00000000-0000-4000-8000-0000000000a1', now(), '사람이 라벨 대상으로 확정한 기존 판정 노트');

-- d4 에 활성 delete lease 를 발급(복구 vs 물리삭제 경합 차단 검증용).
UPDATE public.motion_clip_system_exclusions
  SET delete_lease_token = gen_random_uuid(),
      delete_lease_expires_at = now() + interval '15 minutes',
      delete_worker_host = 'probe-delete-worker'
  WHERE clip_id = '00000000-0000-4000-8000-0000000000d4';

-- d6 을 media_deleted 로 직접 전환(RLS 가시성 대조군). CHECK: quarantined_at/delete_after 유지 + media_deleted_at.
UPDATE public.motion_clip_system_exclusions
  SET state = 'media_deleted', media_deleted_at = now()
  WHERE clip_id = '00000000-0000-4000-8000-0000000000d6';

-- d7 을 복구(RLS 가시성 대조군: restored 는 보임).
SELECT public.fn_restore_short_clip_exclusion(
  '00000000-0000-4000-8000-0000000000d7',
  '00000000-0000-4000-8000-0000000000a1',
  '정상 행동으로 확인되어 자동 제외만 해제하는 복구 검증', now());


-- ── A. 복구가 사람 판정을 절대 안 바꾼다 ────────────────────────────
DO $$
DECLARE
  v_pre text; v_post text; v_cnt integer; v_state text; v_raised boolean;
BEGIN
  -- 1) skip triage 불변.
  SELECT md5(t::text) INTO v_pre FROM public.motion_clip_labeling_triage t
    WHERE t.clip_id = '00000000-0000-4000-8000-0000000000d1';
  PERFORM public.fn_restore_short_clip_exclusion(
    '00000000-0000-4000-8000-0000000000d1',
    '00000000-0000-4000-8000-0000000000a1',
    '오격리로 판단되어 자동 제외만 해제', now());
  SELECT md5(t::text) INTO v_post FROM public.motion_clip_labeling_triage t
    WHERE t.clip_id = '00000000-0000-4000-8000-0000000000d1';
  ASSERT v_pre IS NOT NULL AND v_pre = v_post, format('skip triage mutated pre=%s post=%s', v_pre, v_post);

  -- 4) exclusion restored + owner_restored 정확히 1 + triage_event 0.
  SELECT state INTO v_state FROM public.motion_clip_system_exclusions
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d1';
  ASSERT v_state = 'restored', format('d1 system state=%s', v_state);
  SELECT count(*) INTO v_cnt FROM public.motion_clip_system_exclusion_events
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d1' AND event_type = 'owner_restored';
  ASSERT v_cnt = 1, format('d1 owner_restored events=%s', v_cnt);
  SELECT count(*) INTO v_cnt FROM public.motion_clip_labeling_triage_events
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d1';
  ASSERT v_cnt = 0, format('d1 triage events created=%s', v_cnt);

  -- 2) label triage 불변.
  SELECT md5(t::text) INTO v_pre FROM public.motion_clip_labeling_triage t
    WHERE t.clip_id = '00000000-0000-4000-8000-0000000000d2';
  PERFORM public.fn_restore_short_clip_exclusion(
    '00000000-0000-4000-8000-0000000000d2',
    '00000000-0000-4000-8000-0000000000a1',
    '라벨 대상이지만 시스템 격리만 해제', now());
  SELECT md5(t::text) INTO v_post FROM public.motion_clip_labeling_triage t
    WHERE t.clip_id = '00000000-0000-4000-8000-0000000000d2';
  ASSERT v_pre IS NOT NULL AND v_pre = v_post, format('label triage mutated pre=%s post=%s', v_pre, v_post);
  SELECT count(*) INTO v_cnt FROM public.motion_clip_labeling_triage_events
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d2';
  ASSERT v_cnt = 0, format('d2 triage events created=%s', v_cnt);

  -- 3) triage 없음 → 복구 후에도 없음.
  SELECT count(*) INTO v_cnt FROM public.motion_clip_labeling_triage
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d3';
  ASSERT v_cnt = 0, format('d3 pre triage rows=%s', v_cnt);
  PERFORM public.fn_restore_short_clip_exclusion(
    '00000000-0000-4000-8000-0000000000d3',
    '00000000-0000-4000-8000-0000000000a1',
    '무판정 clip 자동 제외만 해제', now());
  SELECT count(*) INTO v_cnt FROM public.motion_clip_labeling_triage
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d3';
  ASSERT v_cnt = 0, format('d3 post triage rows=%s', v_cnt);

  -- 5) active lease → PT409, exclusion fingerprint 불변.
  SELECT md5(e::text) INTO v_pre FROM public.motion_clip_system_exclusions e
    WHERE e.clip_id = '00000000-0000-4000-8000-0000000000d4';
  v_raised := false;
  BEGIN
    PERFORM public.fn_restore_short_clip_exclusion(
      '00000000-0000-4000-8000-0000000000d4',
      '00000000-0000-4000-8000-0000000000a1',
      '활성 lease 존재 시 복구 거부 검증', now());
  EXCEPTION WHEN sqlstate 'PT409' THEN
    v_raised := true;
  END;
  ASSERT v_raised, 'd4 active lease restore did not raise PT409';
  SELECT md5(e::text) INTO v_post FROM public.motion_clip_system_exclusions e
    WHERE e.clip_id = '00000000-0000-4000-8000-0000000000d4';
  ASSERT v_pre = v_post, format('d4 exclusion mutated under active lease pre=%s post=%s', v_pre, v_post);
  SELECT state INTO v_state FROM public.motion_clip_system_exclusions
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d4';
  ASSERT v_state = 'quarantined', format('d4 state changed=%s', v_state);
END $$;
SELECT 'RESTORE_TRIAGE_IMMUTABLE_OK';


-- ── B. 앱 RLS 가시성 ────────────────────────────────────────────────
-- 대조군: d5=quarantined, d6=media_deleted(숨김) / d7=restored, d8=candidate(보임, owner A) / d9=candidate(owner B).
DO $$
DECLARE v_cnt integer;
BEGIN
  -- 6) Owner A: quarantined/media_deleted 0, restored/candidate 보임.
  PERFORM set_config('request.jwt.claims',
    json_build_object('sub', '00000000-0000-4000-8000-0000000000a1')::text, true);
  SET LOCAL ROLE authenticated;
  SELECT count(*) INTO v_cnt FROM public.motion_clips
    WHERE id IN ('00000000-0000-4000-8000-0000000000d5','00000000-0000-4000-8000-0000000000d6');
  ASSERT v_cnt = 0, format('A sees terminal-excluded=%s (want 0)', v_cnt);
  SELECT count(*) INTO v_cnt FROM public.motion_clips
    WHERE id IN ('00000000-0000-4000-8000-0000000000d7','00000000-0000-4000-8000-0000000000d8');
  ASSERT v_cnt = 2, format('A restored+candidate visible=%s (want 2)', v_cnt);
  -- 7) 다른 Owner(B) clip 은 A 에게 숨김.
  SELECT count(*) INTO v_cnt FROM public.motion_clips
    WHERE id = '00000000-0000-4000-8000-0000000000d9';
  ASSERT v_cnt = 0, format('A sees other-owner clip=%s (want 0)', v_cnt);
  RESET ROLE;

  -- 7) Owner B: 자기 clip 보임, A 의 restored 는 안 보임.
  PERFORM set_config('request.jwt.claims',
    json_build_object('sub', '00000000-0000-4000-8000-0000000000a2')::text, true);
  SET LOCAL ROLE authenticated;
  SELECT count(*) INTO v_cnt FROM public.motion_clips
    WHERE id = '00000000-0000-4000-8000-0000000000d9';
  ASSERT v_cnt = 1, format('B sees own clip=%s (want 1)', v_cnt);
  SELECT count(*) INTO v_cnt FROM public.motion_clips
    WHERE id = '00000000-0000-4000-8000-0000000000d7';
  ASSERT v_cnt = 0, format('B sees A restored=%s (want 0)', v_cnt);
  RESET ROLE;

  -- 8) service_role: 전량 read(운영/감사) — 모든 상태.
  SET LOCAL ROLE service_role;
  SELECT count(*) INTO v_cnt FROM public.motion_clips
    WHERE id IN ('00000000-0000-4000-8000-0000000000d5','00000000-0000-4000-8000-0000000000d6',
                 '00000000-0000-4000-8000-0000000000d7','00000000-0000-4000-8000-0000000000d8',
                 '00000000-0000-4000-8000-0000000000d9');
  ASSERT v_cnt = 5, format('service_role sees=%s of 5', v_cnt);
  RESET ROLE;
END $$;
SELECT 'APP_RLS_VISIBILITY_OK';

ROLLBACK;
