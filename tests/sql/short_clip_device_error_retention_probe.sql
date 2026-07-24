-- 짧은 영상 장치 오류 격리·보존 실제 DB probe (adversarial runtime verification).
--
-- 정적 텍스트 테스트로는 못 잡는 런타임 정확성을 non-empty 합성 row 로 검증한다. 일회용
-- blind_probe_short_clip_* DB 에서만 실행되며 BEGIN … ROLLBACK 으로 합성 row 를 전량 되돌린다.
-- 러너가 rollback 뒤 residue=0 을 재확인한다.
--
-- 필수 시나리오(설계 §9 / handoff):
--   1. 4/11 매칭 정책 → quarantined                        (SHORT_CLIP_DETECT_OK)
--   2. 12초·다른 카메라 → candidate                        (SHORT_CLIP_DETECT_OK)
--   3. 사람 session/slot/submission → 자동 격리 차단        (SHORT_CLIP_DETECT_OK)
--   4. 동일 감지 재실행 → 현재 row 1 + 전이 1(멱등)         (SHORT_CLIP_DETECT_OK)
--   5. 복구 → triage label + system restored 원자성          (SHORT_CLIP_RESTORE_OK)
--   6. restored 동일 rule 재감지 → 재격리 0                 (SHORT_CLIP_RESTORE_OK)
--   7. wrong/expired delete lease → complete 차단           (SHORT_CLIP_DELETE_LEASE_OK)
--   8. claim 31/blank host 거부, 보호/active job → claim 0  (SHORT_CLIP_DELETE_LEASE_OK)
--   9. queued Python Evidence job mutation 0                (SHORT_CLIP_DELETE_LEASE_OK)
--  10. event UPDATE/DELETE/TRUNCATE → 0A000                 (SHORT_CLIP_APPEND_ONLY_OK)
--  11. 내구성 일일 Slack claim(중복 성공 0)                 (SHORT_CLIP_NOTIFY_OK)
--  12. rollback 후 잔여 row 0                               (러너가 확인)

BEGIN;

-- ── 공통 fixture ─────────────────────────────────────────────────────
INSERT INTO auth.users (id) VALUES
  ('00000000-0000-4000-8000-0000000000a1');

INSERT INTO public.cameras (id, name) VALUES
  ('00000000-0000-4000-8000-0000000000c1', 'probe-P4-Cam2-dev'),   -- 정책 카메라
  ('00000000-0000-4000-8000-0000000000c2', 'probe-other-cam');     -- 정책 없음

INSERT INTO public.camera_short_clip_policies (
  camera_id, candidate_under_sec, auto_exclude_display_seconds,
  retention_hours, rule_version, enabled, created_by, updated_by
) VALUES (
  '00000000-0000-4000-8000-0000000000c1', 15, ARRAY[4,11],
  168, 'short-device-error-v1', true,
  '00000000-0000-4000-8000-0000000000a1', '00000000-0000-4000-8000-0000000000a1'
);

-- clip fixtures. 전부 nonblank r2_key(삭제 테스트용). camA=정책, camB=정책 없음.
INSERT INTO public.motion_clips (id, camera_id, started_at, duration_sec, r2_key) VALUES
  ('00000000-0000-4000-8000-0000000000d1', '00000000-0000-4000-8000-0000000000c1', '2026-07-20 00:00:01+00', 3.6,  'terra-clips/clips/d1.mp4'),
  ('00000000-0000-4000-8000-0000000000d2', '00000000-0000-4000-8000-0000000000c1', '2026-07-20 00:00:02+00', 11.4, 'terra-clips/clips/d2.mp4'),
  ('00000000-0000-4000-8000-0000000000d3', '00000000-0000-4000-8000-0000000000c2', '2026-07-20 00:00:03+00', 4.2,  'terra-clips/clips/d3.mp4'),
  ('00000000-0000-4000-8000-0000000000d4', '00000000-0000-4000-8000-0000000000c1', '2026-07-20 00:00:04+00', 12.3, 'terra-clips/clips/d4.mp4'),
  ('00000000-0000-4000-8000-0000000000d5', '00000000-0000-4000-8000-0000000000c1', '2026-07-20 00:00:05+00', 4.0,  'terra-clips/clips/d5.mp4'),
  ('00000000-0000-4000-8000-0000000000d6', '00000000-0000-4000-8000-0000000000c1', '2026-07-20 00:00:06+00', 4.0,  'terra-clips/clips/d6.mp4'),
  ('00000000-0000-4000-8000-0000000000d7', '00000000-0000-4000-8000-0000000000c1', '2026-07-20 00:00:07+00', 4.0,  'terra-clips/clips/d7.mp4'),
  ('00000000-0000-4000-8000-0000000000d8', '00000000-0000-4000-8000-0000000000c1', '2026-07-20 00:00:08+00', 4.0,  'terra-clips/clips/d8.mp4'),
  ('00000000-0000-4000-8000-0000000000d9', '00000000-0000-4000-8000-0000000000c1', '2026-07-20 00:00:09+00', 4.0,  'terra-clips/clips/d9.mp4');

-- clip5 는 사람 라벨링 세션이 붙어 보호 대상이다.
INSERT INTO public.motion_clip_labeling_sessions (clip_id, reviewed_by) VALUES
  ('00000000-0000-4000-8000-0000000000d5', '00000000-0000-4000-8000-0000000000a1');

-- ── Task 2 소비자 가드용 fresh 셋업(camC + 그룹 g1 + reviewer 2인 + clip e1/e2) ──
INSERT INTO auth.users (id) VALUES
  ('00000000-0000-4000-8000-0000000000b1'),
  ('00000000-0000-4000-8000-0000000000b2');
INSERT INTO public.labelers (user_id) VALUES
  ('00000000-0000-4000-8000-0000000000b1'),
  ('00000000-0000-4000-8000-0000000000b2');
INSERT INTO public.labeler_applications (user_id, status, display_name) VALUES
  ('00000000-0000-4000-8000-0000000000b1', 'approved', 'probe 라벨러1'),
  ('00000000-0000-4000-8000-0000000000b2', 'approved', 'probe 라벨러2');

INSERT INTO public.cameras (id, name) VALUES
  ('00000000-0000-4000-8000-0000000000c3', 'probe-group-cam');
INSERT INTO public.camera_short_clip_policies (
  camera_id, candidate_under_sec, auto_exclude_display_seconds,
  retention_hours, rule_version, enabled, created_by, updated_by
) VALUES (
  '00000000-0000-4000-8000-0000000000c3', 15, ARRAY[4,11],
  168, 'short-device-error-v1', true,
  '00000000-0000-4000-8000-0000000000a1', '00000000-0000-4000-8000-0000000000a1'
);

INSERT INTO public.motion_labeling_review_groups (id, name, active, created_by) VALUES
  ('00000000-0000-4000-8000-0000000000e0', 'probe-group', true, '00000000-0000-4000-8000-0000000000a1');
INSERT INTO public.motion_labeling_review_group_members (group_id, user_id, assigned_by) VALUES
  ('00000000-0000-4000-8000-0000000000e0', '00000000-0000-4000-8000-0000000000b1', '00000000-0000-4000-8000-0000000000a1'),
  ('00000000-0000-4000-8000-0000000000e0', '00000000-0000-4000-8000-0000000000b2', '00000000-0000-4000-8000-0000000000a1');
INSERT INTO public.motion_labeling_review_group_cameras (group_id, camera_id, assigned_by) VALUES
  ('00000000-0000-4000-8000-0000000000e0', '00000000-0000-4000-8000-0000000000c3', '00000000-0000-4000-8000-0000000000a1');

-- e1 = 격리 대상(4초), e2 = 후보 대조군(12초). 같은 activity day 창(2026-07-20 KST).
INSERT INTO public.motion_clips (id, camera_id, started_at, duration_sec, r2_key) VALUES
  ('00000000-0000-4000-8000-0000000000e1', '00000000-0000-4000-8000-0000000000c3', '2026-07-20 01:00:01+00', 4.0,  'terra-clips/clips/e1.mp4'),
  ('00000000-0000-4000-8000-0000000000e2', '00000000-0000-4000-8000-0000000000c3', '2026-07-20 01:00:02+00', 12.0, 'terra-clips/clips/e2.mp4');


-- ── SHORT_CLIP_DETECT_OK: 감지·격리·후보·보호·멱등·shadow ──────────
DO $$
DECLARE v_route text; v_state text; v_cnt integer;
BEGIN
  -- (1) clip1 표시 4초 매칭 → quarantined + 168h 보존.
  SELECT route, resulting_state INTO v_route, v_state
    FROM public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d1', now(), true);
  ASSERT v_route = 'quarantined', format('clip1 route=%s', v_route);
  PERFORM 1 FROM public.motion_clip_system_exclusions
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d1'
      AND state = 'quarantined'
      AND delete_after = quarantined_at + interval '168 hours';
  ASSERT FOUND, 'clip1 168h retention missing';

  -- (4) 동일 감지 재실행 → reused, 현재 row 1 + auto_quarantined event 1(멱등).
  SELECT route INTO v_route
    FROM public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d1', now(), true);
  ASSERT v_route = 'reused', format('clip1 dup route=%s', v_route);
  SELECT count(*) INTO v_cnt FROM public.motion_clip_system_exclusions
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d1';
  ASSERT v_cnt = 1, format('clip1 current rows=%s', v_cnt);
  SELECT count(*) INTO v_cnt FROM public.motion_clip_system_exclusion_events
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d1' AND event_type = 'auto_quarantined';
  ASSERT v_cnt = 1, format('clip1 quarantine events=%s', v_cnt);

  -- (1) clip2 표시 11초 매칭 → quarantined.
  SELECT route INTO v_route
    FROM public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d2', now(), true);
  ASSERT v_route = 'quarantined', format('clip2 route=%s', v_route);

  -- (2) clip3 다른 카메라(정책 없음) → candidate.
  SELECT route INTO v_route
    FROM public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d3', now(), true);
  ASSERT v_route = 'candidate', format('clip3 route=%s', v_route);

  -- (2) clip4 12초 camA(매칭 밖) → candidate.
  SELECT route INTO v_route
    FROM public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d4', now(), true);
  ASSERT v_route = 'candidate', format('clip4 route=%s', v_route);

  -- (3) clip5 4초지만 사람 세션 있음 → protected/deletion_blocked(격리 아님).
  SELECT route, resulting_state INTO v_route, v_state
    FROM public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d5', now(), true);
  ASSERT v_route = 'protected', format('clip5 route=%s', v_route);
  ASSERT v_state = 'deletion_blocked', format('clip5 state=%s', v_state);
  PERFORM 1 FROM public.motion_clip_system_exclusions
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d5' AND state = 'deletion_blocked';
  ASSERT FOUND, 'clip5 not deletion_blocked';

  -- shadow(write=false)는 격리를 계산하되 쓰지 않는다.
  SELECT route INTO v_route
    FROM public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d7', now(), false);
  ASSERT v_route = 'quarantined', format('clip7 shadow route=%s', v_route);
  SELECT count(*) INTO v_cnt FROM public.motion_clip_system_exclusions
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d7';
  ASSERT v_cnt = 0, format('clip7 shadow wrote rows=%s', v_cnt);
END $$;
SELECT 'SHORT_CLIP_DETECT_OK';


-- ── SHORT_CLIP_RESTORE_OK: 복구 원자성 + 재격리 0 ──────────────────
DO $$
DECLARE v_route text; v_dec text; v_by uuid; v_state text; v_cnt integer;
BEGIN
  -- (5) clip6 격리 → 복구.
  SELECT route INTO v_route
    FROM public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d6', now(), true);
  ASSERT v_route = 'quarantined', format('clip6 quarantine route=%s', v_route);

  PERFORM public.fn_restore_short_clip_exclusion(
    '00000000-0000-4000-8000-0000000000d6',
    '00000000-0000-4000-8000-0000000000a1',
    '정상 행동 오격리 복구 검증', now());

  -- triage 가 label + Owner actor 로 복귀.
  SELECT owner_decision, decided_by INTO v_dec, v_by
    FROM public.motion_clip_labeling_triage WHERE clip_id = '00000000-0000-4000-8000-0000000000d6';
  ASSERT v_dec = 'label', format('clip6 triage decision=%s', v_dec);
  ASSERT v_by = '00000000-0000-4000-8000-0000000000a1'::uuid, 'clip6 decided_by not owner';

  -- system 원장 restored + 삭제 deadline 취소.
  SELECT state INTO v_state
    FROM public.motion_clip_system_exclusions WHERE clip_id = '00000000-0000-4000-8000-0000000000d6';
  ASSERT v_state = 'restored', format('clip6 system state=%s', v_state);
  PERFORM 1 FROM public.motion_clip_system_exclusions
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d6' AND delete_after IS NULL;
  ASSERT FOUND, 'clip6 delete_after not cleared';

  -- 양쪽 append-only 감사 각 1.
  SELECT count(*) INTO v_cnt FROM public.motion_clip_labeling_triage_events
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d6' AND event_type = 'owner_labeled';
  ASSERT v_cnt = 1, format('clip6 triage events=%s', v_cnt);
  SELECT count(*) INTO v_cnt FROM public.motion_clip_system_exclusion_events
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d6' AND event_type = 'owner_restored';
  ASSERT v_cnt = 1, format('clip6 restored events=%s', v_cnt);

  -- (6) 같은 규칙 재감지 → reused_restored, 여전히 restored(재격리 0).
  SELECT route INTO v_route
    FROM public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d6', now(), true);
  ASSERT v_route = 'reused_restored', format('clip6 redetect route=%s', v_route);
  SELECT state INTO v_state
    FROM public.motion_clip_system_exclusions WHERE clip_id = '00000000-0000-4000-8000-0000000000d6';
  ASSERT v_state = 'restored', format('clip6 re-quarantined state=%s', v_state);
END $$;
SELECT 'SHORT_CLIP_RESTORE_OK';


-- ── SHORT_CLIP_DELETE_LEASE_OK: lease fail-closed + 보호/active job ──
DO $$
DECLARE v_route text; v_excl uuid; v_clip uuid; v_key text; v_tok uuid;
        v_ok boolean; v_state text; v_cnt integer; v_caught boolean;
BEGIN
  -- (8) claim 인자 가드: 31 초과 / blank host.
  v_caught := false;
  BEGIN
    PERFORM 1 FROM public.fn_claim_short_clip_media_deletions(31, 'probe-host', now());
  EXCEPTION WHEN invalid_parameter_value THEN v_caught := true;
  END;
  ASSERT v_caught, 'claim limit 31 not rejected';

  v_caught := false;
  BEGIN
    PERFORM 1 FROM public.fn_claim_short_clip_media_deletions(1, '   ', now());
  EXCEPTION WHEN invalid_parameter_value THEN v_caught := true;
  END;
  ASSERT v_caught, 'claim blank host not rejected';

  -- clip7 격리 후 삭제 기한 만료.
  PERFORM public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d7', now(), true);
  UPDATE public.motion_clip_system_exclusions
    SET delete_after = now() - interval '1 hour'
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d7';

  -- claim → exclusion/clip/r2_key/lease 만 반환.
  SELECT exclusion_id, clip_id, r2_key, lease_token INTO v_excl, v_clip, v_key, v_tok
    FROM public.fn_claim_short_clip_media_deletions(1, 'probe-host', now());
  ASSERT v_excl IS NOT NULL, 'clip7 not claimed';
  ASSERT v_key IS NOT NULL AND btrim(v_key) <> '', 'clip7 blank r2_key returned';
  ASSERT v_tok IS NOT NULL, 'clip7 no lease token';

  -- (7) 잘못된 lease → false, 여전히 quarantined.
  SELECT public.fn_complete_short_clip_media_delete(v_excl, gen_random_uuid(), 'fp', now()) INTO v_ok;
  ASSERT v_ok = false, 'wrong lease completed';
  SELECT state INTO v_state FROM public.motion_clip_system_exclusions WHERE id = v_excl;
  ASSERT v_state = 'quarantined', format('clip7 after wrong lease=%s', v_state);

  -- (7) 만료 lease → false.
  UPDATE public.motion_clip_system_exclusions
    SET delete_lease_expires_at = now() - interval '1 minute' WHERE id = v_excl;
  SELECT public.fn_complete_short_clip_media_delete(v_excl, v_tok, 'fp', now()) INTO v_ok;
  ASSERT v_ok = false, 'expired lease completed';

  -- 유효 lease → media_deleted + delete_completed 1.
  UPDATE public.motion_clip_system_exclusions
    SET delete_lease_expires_at = now() + interval '15 minutes' WHERE id = v_excl;
  SELECT public.fn_complete_short_clip_media_delete(v_excl, v_tok, 'sha256-fingerprint', now()) INTO v_ok;
  ASSERT v_ok = true, 'valid lease not completed';
  SELECT state INTO v_state FROM public.motion_clip_system_exclusions WHERE id = v_excl;
  ASSERT v_state = 'media_deleted', format('clip7 not media_deleted=%s', v_state);
  PERFORM 1 FROM public.motion_clip_system_exclusions WHERE id = v_excl AND media_deleted_at IS NOT NULL;
  ASSERT FOUND, 'clip7 media_deleted_at null';
  SELECT count(*) INTO v_cnt FROM public.motion_clip_system_exclusion_events
    WHERE exclusion_id = v_excl AND event_type = 'delete_completed';
  ASSERT v_cnt = 1, format('clip7 complete events=%s', v_cnt);

  -- 중복 complete → false(이중 삭제 이벤트 0).
  SELECT public.fn_complete_short_clip_media_delete(v_excl, v_tok, 'sha256-fingerprint', now()) INTO v_ok;
  ASSERT v_ok = false, 'duplicate complete succeeded';

  -- media_deleted → 복구 PT428 거부.
  v_caught := false;
  BEGIN
    PERFORM public.fn_restore_short_clip_exclusion(
      '00000000-0000-4000-8000-0000000000d7',
      '00000000-0000-4000-8000-0000000000a1', '삭제된 미디어 복구 시도', now());
  EXCEPTION WHEN SQLSTATE 'PT428' THEN v_caught := true;
  END;
  ASSERT v_caught, 'media_deleted restore not rejected';

  -- (8) clip8 사람 attachment 보호 → claim 0 + deletion_blocked + lease 없음.
  PERFORM public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d8', now(), true);
  INSERT INTO public.behavior_logs (clip_id) VALUES ('00000000-0000-4000-8000-0000000000d8');
  UPDATE public.motion_clip_system_exclusions
    SET delete_after = now() - interval '1 hour' WHERE clip_id = '00000000-0000-4000-8000-0000000000d8';
  SELECT count(*) INTO v_cnt
    FROM public.fn_claim_short_clip_media_deletions(30, 'probe-host', now())
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d8';
  ASSERT v_cnt = 0, format('clip8 protected but claimed=%s', v_cnt);
  SELECT state INTO v_state FROM public.motion_clip_system_exclusions
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d8';
  ASSERT v_state = 'deletion_blocked', format('clip8 state=%s', v_state);
  PERFORM 1 FROM public.motion_clip_system_exclusions
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d8' AND delete_lease_token IS NULL;
  ASSERT FOUND, 'clip8 got a lease';

  -- (9) clip9 active python_evidence_job → claim 0 + job row unchanged.
  PERFORM public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000d9', now(), true);
  INSERT INTO public.python_evidence_jobs (clip_id, status) VALUES ('00000000-0000-4000-8000-0000000000d9', 'queued');
  UPDATE public.motion_clip_system_exclusions
    SET delete_after = now() - interval '1 hour' WHERE clip_id = '00000000-0000-4000-8000-0000000000d9';
  SELECT count(*) INTO v_cnt
    FROM public.fn_claim_short_clip_media_deletions(30, 'probe-host', now())
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d9';
  ASSERT v_cnt = 0, format('clip9 active-job but claimed=%s', v_cnt);
  SELECT count(*) INTO v_cnt FROM public.python_evidence_jobs
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d9' AND status = 'queued';
  ASSERT v_cnt = 1, 'clip9 evidence job mutated';
END $$;
SELECT 'SHORT_CLIP_DELETE_LEASE_OK';


-- ── SHORT_CLIP_APPEND_ONLY_OK: event UPDATE/DELETE/TRUNCATE → 0A000 ──
DO $$
DECLARE v_caught boolean;
BEGIN
  v_caught := false;
  BEGIN
    UPDATE public.motion_clip_system_exclusion_events SET reason_code = 'x';
  EXCEPTION WHEN feature_not_supported THEN v_caught := true;
  END;
  ASSERT v_caught, 'event UPDATE not blocked';

  v_caught := false;
  BEGIN
    DELETE FROM public.motion_clip_system_exclusion_events;
  EXCEPTION WHEN feature_not_supported THEN v_caught := true;
  END;
  ASSERT v_caught, 'event DELETE not blocked';

  v_caught := false;
  BEGIN
    TRUNCATE public.motion_clip_system_exclusion_events;
  EXCEPTION WHEN feature_not_supported THEN v_caught := true;
  END;
  ASSERT v_caught, 'event TRUNCATE not blocked';
END $$;
SELECT 'SHORT_CLIP_APPEND_ONLY_OK';


-- ── SHORT_CLIP_NOTIFY_OK: 내구성 일일 Slack claim(중복 성공 0) ──────
DO $$
DECLARE t1 uuid; t2 uuid; v_ok boolean;
BEGIN
  SELECT public.fn_claim_short_clip_retention_notification(DATE '2026-07-24', 'probe-host', now()) INTO t1;
  ASSERT t1 IS NOT NULL, 'first claim null';
  -- 아직 미전송이면 재claim 가능(새 token).
  SELECT public.fn_claim_short_clip_retention_notification(DATE '2026-07-24', 'probe-host', now()) INTO t2;
  ASSERT t2 IS NOT NULL, 're-claim null';
  -- complete 로 sent_at 기록.
  SELECT public.fn_complete_short_clip_retention_notification(DATE '2026-07-24', t2, now()) INTO v_ok;
  ASSERT v_ok, 'complete failed';
  -- 전송 뒤 claim 은 NULL(오늘 카드 중복 금지).
  SELECT public.fn_claim_short_clip_retention_notification(DATE '2026-07-24', 'probe-host', now()) INTO t1;
  ASSERT t1 IS NULL, 'claim after sent not null';
  -- 전송된 것은 release 되지 않는다.
  SELECT public.fn_release_short_clip_retention_notification(DATE '2026-07-24', t2) INTO v_ok;
  ASSERT v_ok = false, 'release after sent succeeded';
END $$;
SELECT 'SHORT_CLIP_NOTIFY_OK';


-- ── SHORT_CLIP_CONSUMER_GUARD_OK: 신규 소비 제외 + media-deleted 읽기 + 기존 row 불변 ──
DO $$
DECLARE
  v_cnt integer; v_ready boolean; v_state text; v_caught boolean;
  v_slots integer; v_cohort uuid;
  v_sessions_before integer; v_sessions_after integer;
BEGIN
  SELECT count(*) INTO v_sessions_before FROM public.motion_clip_labeling_sessions;

  -- (queue) Owner 기본 큐: quarantined(d1)/media_deleted(d7) 제외, restored(d6) 재노출.
  SELECT count(*) INTO v_cnt FROM public.fn_list_motion_clip_labeling_queue(
    '00000000-0000-4000-8000-0000000000a1', true, NULL,
    ARRAY['00000000-0000-4000-8000-0000000000c1']::uuid[], NULL, NULL, NULL, NULL, NULL, 100)
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d1';
  ASSERT v_cnt = 0, 'quarantined clip in owner queue';
  SELECT count(*) INTO v_cnt FROM public.fn_list_motion_clip_labeling_queue(
    '00000000-0000-4000-8000-0000000000a1', true, NULL,
    ARRAY['00000000-0000-4000-8000-0000000000c1']::uuid[], NULL, NULL, NULL, NULL, NULL, 100)
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d7';
  ASSERT v_cnt = 0, 'media_deleted clip in owner queue';
  SELECT count(*) INTO v_cnt FROM public.fn_list_motion_clip_labeling_queue(
    '00000000-0000-4000-8000-0000000000a1', true, NULL,
    ARRAY['00000000-0000-4000-8000-0000000000c1']::uuid[], NULL, NULL, NULL, NULL, NULL, 100)
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d6';
  ASSERT v_cnt = 1, 'restored clip not re-listed in owner queue';

  -- (read) 자동 제외 목록: media_deleted(d7) media_ready=false.
  SELECT media_ready, state INTO v_ready, v_state
    FROM public.fn_list_short_clip_system_exclusions(NULL, NULL, 100)
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d7';
  ASSERT v_state = 'media_deleted', format('d7 excl state=%s', v_state);
  ASSERT v_ready = false, 'media_deleted media_ready not false';

  -- (library) 라이브러리에서 quarantined(d1)/media_deleted(d7) 숨김.
  SELECT count(*) INTO v_cnt FROM public.fn_list_motion_labeling_library(
    '00000000-0000-4000-8000-0000000000a1', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 200)
    WHERE clip_id IN ('00000000-0000-4000-8000-0000000000d1','00000000-0000-4000-8000-0000000000d7');
  ASSERT v_cnt = 0, 'quarantined/media_deleted clip in library';

  -- (python evidence) 격리 clip(d1) job 은 claim 제외 + queued 유지, 후보(d4) job 은 claim 됨.
  INSERT INTO public.python_evidence_jobs (clip_id, status) VALUES
    ('00000000-0000-4000-8000-0000000000d1', 'queued'),
    ('00000000-0000-4000-8000-0000000000d4', 'queued');
  PERFORM 1 FROM public.fn_claim_python_evidence_jobs(10, 'probe-host', now());
  SELECT status INTO v_state FROM public.python_evidence_jobs
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d1';
  ASSERT v_state = 'queued', format('quarantined evidence job mutated=%s', v_state);
  SELECT status INTO v_state FROM public.python_evidence_jobs
    WHERE clip_id = '00000000-0000-4000-8000-0000000000d4';
  ASSERT v_state = 'processing', format('candidate evidence job not claimed=%s', v_state);

  -- (slot 자재화) e1 격리 → live slot 0, e2 후보 → live slot 2.
  PERFORM public.fn_record_short_clip_detection('00000000-0000-4000-8000-0000000000e1', now(), true);
  SELECT state INTO v_state FROM public.motion_clip_system_exclusions
    WHERE clip_id = '00000000-0000-4000-8000-0000000000e1';
  ASSERT v_state = 'quarantined', format('e1 state=%s', v_state);
  PERFORM public.fn_ensure_motion_review_slots('00000000-0000-4000-8000-0000000000b1', DATE '2026-07-20');
  SELECT count(*) INTO v_slots FROM public.motion_clip_review_slots
    WHERE clip_id = '00000000-0000-4000-8000-0000000000e1' AND cohort_kind = 'live';
  ASSERT v_slots = 0, format('quarantined e1 got live slots=%s', v_slots);
  SELECT count(*) INTO v_slots FROM public.motion_clip_review_slots
    WHERE clip_id = '00000000-0000-4000-8000-0000000000e2' AND cohort_kind = 'live';
  ASSERT v_slots = 2, format('candidate e2 live slots=%s', v_slots);

  -- (canary) 격리 clip(e1) 포함 create → PT428, 후보 clip(e2) → 성공.
  v_caught := false;
  BEGIN
    PERFORM public.fn_manage_motion_blind_canary('create',
      '00000000-0000-4000-8000-0000000000a1', NULL, 'probe-canary',
      '00000000-0000-4000-8000-0000000000e0',
      ARRAY['00000000-0000-4000-8000-0000000000e1']::uuid[],
      ARRAY['00000000-0000-4000-8000-0000000000b1','00000000-0000-4000-8000-0000000000b2']::uuid[]);
  EXCEPTION WHEN SQLSTATE 'PT428' THEN v_caught := true;
  END;
  ASSERT v_caught, 'canary with quarantined clip not rejected';
  SELECT public.fn_manage_motion_blind_canary('create',
    '00000000-0000-4000-8000-0000000000a1', NULL, 'probe-canary-ok',
    '00000000-0000-4000-8000-0000000000e0',
    ARRAY['00000000-0000-4000-8000-0000000000e2']::uuid[],
    ARRAY['00000000-0000-4000-8000-0000000000b1','00000000-0000-4000-8000-0000000000b2']::uuid[]) INTO v_cohort;
  ASSERT v_cohort IS NOT NULL, 'canary with candidate clip failed';

  -- 기존 사람 세션 row 불변(수 변화 0).
  SELECT count(*) INTO v_sessions_after FROM public.motion_clip_labeling_sessions;
  ASSERT v_sessions_after = v_sessions_before, 'existing labeling sessions changed';
END $$;
SELECT 'SHORT_CLIP_CONSUMER_GUARD_OK';

ROLLBACK;
