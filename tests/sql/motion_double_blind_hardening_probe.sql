-- 이중 블라인드 하드닝 rollback runtime probe (Task 6).
--
-- 최소 prerequisite schema + migration 이 적용된 일회용 컨테이너에서, 합성 UUID 만으로 한 트랜잭션
-- 안에서 하드닝 불변식을 검증하고 전량 ROLLBACK 한다. 예상 실패는 raw message 가 아니라 SQLSTATE 로
-- 단언한다. 모든 assertion 통과 시에만 DB_RUNTIME_PROBE_OK 를 출력한다. production DB 에는 절대
-- 적용하지 않는다 — 오직 disposable 컨테이너 전용.
--
-- 검증 항목:
--   1) fn_ensure 가 aggregate FOR UPDATE 오류 없이 실행
--   2) 첫 ensure 는 clip 당 정확히 2 live slot
--   3) 멤버 교체 후 재-ensure 해도 세 번째 slot 안 생김(ownership freeze)
--   4) 카메라 재배정이 기존 consensus.group_id 를 바꾸지 않음
--   5) cross-clip / cross-group / cross-cohort / same-reviewer finalize → 22023
--   6) 잘못된 agreed/conflict payload shape → 22023
--   7) 유효 finalize 는 agreed + auto_compared event 1, 동일 재시도에도 1
--   8) canary: labelers 미소속 승인자·group 외부 reviewer 거부(PT425), 유효 active pair 성공
--   9) 최종 ROLLBACK 후 합성 row 0 (runner 가 별도 확인)

\set ON_ERROR_STOP on
BEGIN;

DO $probe$
DECLARE
  v_owner uuid := gen_random_uuid();
  v_a uuid := gen_random_uuid();       -- G 멤버 + 제출자
  v_b uuid := gen_random_uuid();       -- G 멤버 + 제출자
  v_e uuid := gen_random_uuid();       -- G 에서 b 를 대체
  v_c uuid := gen_random_uuid();       -- group2 멤버
  v_d uuid := gen_random_uuid();       -- group2 멤버
  v_napp uuid := gen_random_uuid();    -- 승인 application 이지만 labelers 미소속
  v_outsider uuid := gen_random_uuid();-- labeler+approved 이지만 G 비멤버
  v_cam uuid := gen_random_uuid();
  v_cam2 uuid := gen_random_uuid();
  v_clip1 uuid := gen_random_uuid();
  v_clip2 uuid := gen_random_uuid();
  v_clip3 uuid := gen_random_uuid();
  v_group uuid;
  v_group2 uuid;
  v_cohort uuid;
  v_day date := (now() AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date;
  v_count integer;
  v_owned uuid;
  v_status text;
  v_events integer;
  v_tok uuid;
  v_sub_a uuid; v_dig_a text;
  v_sub_b uuid; v_dig_b text;
  v_sub_c2 uuid; v_dig_c2 text;   -- clip2, reviewer a
  v_sub_g2 uuid; v_dig_g2 text;   -- clip3, reviewer c (group2)
  v_slot_b2 uuid;                 -- clip2 의 reviewer b slot(미제출) — forged slot 테스트용
  v_sub_forged uuid;              -- 위조 제출(denormalize=clip1/B 지만 slot 은 clip2/B)
  v_sub_can uuid; v_dig_can text; -- clip1 canary, reviewer a
BEGIN
  -- ── setup: 사람·라벨러·승인·카메라·클립 ──
  INSERT INTO auth.users (id) VALUES
    (v_owner),(v_a),(v_b),(v_e),(v_c),(v_d),(v_napp),(v_outsider);
  INSERT INTO public.labelers (user_id) VALUES (v_a),(v_b),(v_e),(v_c),(v_d),(v_outsider);
  INSERT INTO public.labeler_applications (user_id, status, display_name) VALUES
    (v_a,'approved','A'),(v_b,'approved','B'),(v_e,'approved','E'),
    (v_c,'approved','C'),(v_d,'approved','D'),
    (v_napp,'approved','NAPP'),(v_outsider,'approved','OUT');
  INSERT INTO public.cameras (id,name) VALUES (v_cam,'probe-cam'),(v_cam2,'probe-cam2');
  INSERT INTO public.motion_clips (id,camera_id,started_at,duration_sec,r2_key) VALUES
    (v_clip1,v_cam,now(),30,'probe/c1.mp4'),
    (v_clip2,v_cam,now(),30,'probe/c2.mp4'),
    (v_clip3,v_cam2,now(),30,'probe/c3.mp4');

  v_group  := public.fn_manage_motion_review_group(NULL, v_owner, 'probe-G',  ARRAY[v_a,v_b], ARRAY[v_cam]);
  v_group2 := public.fn_manage_motion_review_group(NULL, v_owner, 'probe-G2', ARRAY[v_c,v_d], ARRAY[v_cam2]);

  -- ── 1) ensure 실행(aggregate FOR UPDATE 오류 없음) ──
  PERFORM public.fn_ensure_motion_review_slots(v_a, v_day);
  PERFORM public.fn_ensure_motion_review_slots(v_c, v_day);

  -- ── 2) 첫 ensure 는 clip1 에 정확히 2 live slot ──
  SELECT count(*) INTO v_count FROM public.motion_clip_review_slots
    WHERE clip_id = v_clip1 AND cohort_kind = 'live';
  IF v_count <> 2 THEN
    RAISE EXCEPTION 'expected 2 live slots on clip1, got %', v_count USING ERRCODE = 'P0001';
  END IF;

  -- ── 제출: clip1(a,b), clip2(a), clip3(c, group2) ──
  v_tok := gen_random_uuid();
  PERFORM public.fn_claim_motion_review_slot(v_clip1, v_a, 'live', NULL, v_tok);
  SELECT own_submission_id, own_digest INTO v_sub_a, v_dig_a
    FROM public.fn_submit_motion_blind_review(v_clip1, v_a, 'live', NULL, 'exclude','gecko_absent',NULL,NULL, v_tok);

  v_tok := gen_random_uuid();
  PERFORM public.fn_claim_motion_review_slot(v_clip1, v_b, 'live', NULL, v_tok);
  SELECT own_submission_id, own_digest INTO v_sub_b, v_dig_b
    FROM public.fn_submit_motion_blind_review(v_clip1, v_b, 'live', NULL, 'exclude','gecko_absent',NULL,NULL, v_tok);

  v_tok := gen_random_uuid();
  PERFORM public.fn_claim_motion_review_slot(v_clip2, v_a, 'live', NULL, v_tok);
  SELECT own_submission_id, own_digest INTO v_sub_c2, v_dig_c2
    FROM public.fn_submit_motion_blind_review(v_clip2, v_a, 'live', NULL, 'exclude','gecko_absent',NULL,NULL, v_tok);

  v_tok := gen_random_uuid();
  PERFORM public.fn_claim_motion_review_slot(v_clip3, v_c, 'live', NULL, v_tok);
  SELECT own_submission_id, own_digest INTO v_sub_g2, v_dig_g2
    FROM public.fn_submit_motion_blind_review(v_clip3, v_c, 'live', NULL, 'exclude','gecko_absent',NULL,NULL, v_tok);

  -- canary cohort(clip1, [a,b], group G) + a 의 canary 제출 → cross-cohort 검증 재료.
  v_cohort := public.fn_manage_motion_blind_canary('create', v_owner, NULL, 'probe-canary',
    v_group, ARRAY[v_clip1], ARRAY[v_a, v_b]);
  v_tok := gen_random_uuid();
  PERFORM public.fn_claim_motion_review_slot(v_clip1, v_a, 'canary', v_cohort, v_tok);
  SELECT own_submission_id, own_digest INTO v_sub_can, v_dig_can
    FROM public.fn_submit_motion_blind_review(v_clip1, v_a, 'canary', v_cohort, 'exclude','gecko_absent',NULL,NULL, v_tok);

  -- ── 5) finalize 교차 객체 identity → 22023 ──
  -- same-reviewer (동일 제출 두 번).
  BEGIN
    PERFORM public.fn_finalize_motion_blind_consensus(v_clip1,'live',NULL,
      v_sub_a, v_sub_a, v_dig_a, v_dig_a, 'motion-blind-v1','agreed','exclude',NULL,'{}');
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: same-reviewer finalize' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  -- cross-clip (clip2 제출을 clip1 finalize 에).
  BEGIN
    PERFORM public.fn_finalize_motion_blind_consensus(v_clip1,'live',NULL,
      v_sub_a, v_sub_c2, v_dig_a, v_dig_c2, 'motion-blind-v1','agreed','exclude',NULL,'{}');
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: cross-clip finalize' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  -- cross-group (group2 제출을 clip1 finalize 에).
  BEGIN
    PERFORM public.fn_finalize_motion_blind_consensus(v_clip1,'live',NULL,
      v_sub_a, v_sub_g2, v_dig_a, v_dig_g2, 'motion-blind-v1','agreed','exclude',NULL,'{}');
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: cross-group finalize' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  -- cross-cohort (canary 제출을 live finalize 에).
  BEGIN
    PERFORM public.fn_finalize_motion_blind_consensus(v_clip1,'live',NULL,
      v_sub_a, v_sub_can, v_dig_a, v_dig_can, 'motion-blind-v1','agreed','exclude',NULL,'{}');
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: cross-cohort finalize' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  -- forged slot mismatch(Codex P1-1): denormalize 필드는 clip1/B/live 로 맞지만 slot_id 는 clip2/B
  -- slot 을 가리키는 위조 제출 → finalize 의 slot identity 검증이 22023 으로 거부해야 한다.
  SELECT id INTO v_slot_b2 FROM public.motion_clip_review_slots
    WHERE clip_id = v_clip2 AND reviewer_id = v_b AND cohort_kind = 'live';
  INSERT INTO public.motion_clip_blind_submissions
    (slot_id, clip_id, group_id, reviewer_id, cohort_kind, cohort_id,
     decision, reason_code, initial_gt, note, digest)
  VALUES (v_slot_b2, v_clip1, v_group, v_b, 'live', NULL,
     'exclude', 'gecko_absent', NULL, NULL, 'forged')
  RETURNING id INTO v_sub_forged;
  BEGIN
    PERFORM public.fn_finalize_motion_blind_consensus(v_clip1,'live',NULL,
      v_sub_a, v_sub_forged, v_dig_a, 'forged', 'motion-blind-v1','agreed','exclude',NULL,'{}');
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: forged slot mismatch finalize' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;

  -- ── 6) 잘못된 agreed/conflict payload shape → 22023 ──
  -- agreed 인데 final_decision NULL.
  BEGIN
    PERFORM public.fn_finalize_motion_blind_consensus(v_clip1,'live',NULL,
      v_sub_a, v_sub_b, v_dig_a, v_dig_b, 'motion-blind-v1','agreed',NULL,NULL,'{}');
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: agreed without decision' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;
  -- conflict 인데 final_decision 존재.
  BEGIN
    PERFORM public.fn_finalize_motion_blind_consensus(v_clip1,'live',NULL,
      v_sub_a, v_sub_b, v_dig_a, v_dig_b, 'motion-blind-v1','conflict','exclude',NULL,'{}');
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: conflict with decision' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate '22023' THEN NULL;
  END;

  -- ── 7) 유효 finalize → agreed, auto_compared event 1, 재시도에도 1 ──
  PERFORM public.fn_finalize_motion_blind_consensus(v_clip1,'live',NULL,
    v_sub_a, v_sub_b, v_dig_a, v_dig_b, 'motion-blind-v1','agreed','exclude',NULL,'{}');
  SELECT status INTO v_status FROM public.motion_clip_consensus
    WHERE clip_id = v_clip1 AND cohort_kind = 'live';
  IF v_status <> 'agreed' THEN
    RAISE EXCEPTION 'consensus not agreed after finalize: %', v_status USING ERRCODE = 'P0001';
  END IF;
  -- 동일 finalize 재시도(멱등).
  PERFORM public.fn_finalize_motion_blind_consensus(v_clip1,'live',NULL,
    v_sub_a, v_sub_b, v_dig_a, v_dig_b, 'motion-blind-v1','agreed','exclude',NULL,'{}');
  SELECT count(*) INTO v_events FROM public.motion_clip_consensus_events
    WHERE clip_id = v_clip1 AND cohort_kind = 'live' AND event_type = 'auto_compared';
  IF v_events <> 1 THEN
    RAISE EXCEPTION 'auto_compared event count is % (expected 1)', v_events USING ERRCODE = 'P0001';
  END IF;

  -- ── 3) 멤버 교체 후 재-ensure 해도 세 번째 slot 안 생김 ──
  v_group := public.fn_manage_motion_review_group(v_group, v_owner, 'probe-G', ARRAY[v_a,v_e], ARRAY[v_cam]);
  PERFORM public.fn_ensure_motion_review_slots(v_a, v_day);
  SELECT count(*) INTO v_count FROM public.motion_clip_review_slots
    WHERE clip_id = v_clip1 AND cohort_kind = 'live';
  IF v_count <> 2 THEN
    RAISE EXCEPTION 'ownership expanded to % live slots after member swap', v_count USING ERRCODE = 'P0001';
  END IF;

  -- ── 4) 카메라 재배정이 기존 consensus.group_id 를 안 바꿈 ──
  UPDATE public.motion_labeling_review_group_cameras
    SET ended_at = clock_timestamp()
    WHERE camera_id = v_cam AND group_id = v_group AND ended_at IS NULL;
  v_group2 := public.fn_manage_motion_review_group(v_group2, v_owner, 'probe-G2',
    ARRAY[v_c,v_d], ARRAY[v_cam, v_cam2]);
  PERFORM public.fn_ensure_motion_review_slots(v_c, v_day);
  SELECT group_id INTO v_owned FROM public.motion_clip_consensus
    WHERE clip_id = v_clip1 AND cohort_kind = 'live';
  IF v_owned <> v_group THEN
    RAISE EXCEPTION 'consensus ownership changed on camera reassignment' USING ERRCODE = 'P0001';
  END IF;
  SELECT count(*) INTO v_count FROM public.motion_clip_review_slots
    WHERE clip_id = v_clip1 AND cohort_kind = 'live';
  IF v_count <> 2 THEN
    RAISE EXCEPTION 'reassignment expanded clip1 slots to %', v_count USING ERRCODE = 'P0001';
  END IF;

  -- ── 8) canary 자격 ──
  -- 승인 application 이지만 labelers 미소속 → PT425.
  BEGIN
    PERFORM public.fn_manage_motion_blind_canary('create', v_owner, NULL, 'x',
      v_group, ARRAY[v_clip2], ARRAY[v_a, v_napp]);
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: canary napp' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate 'PT425' THEN NULL;
  END;
  -- labeler+approved 이지만 group 외부 reviewer → PT425.
  BEGIN
    PERFORM public.fn_manage_motion_blind_canary('create', v_owner, NULL, 'x',
      v_group, ARRAY[v_clip2], ARRAY[v_a, v_outsider]);
    RAISE EXCEPTION 'MISSING_EXPECTED_ERROR: canary outsider' USING ERRCODE = 'P0001';
  EXCEPTION WHEN sqlstate 'PT425' THEN NULL;
  END;
  -- 유효 active pair(둘 다 G 현재 멤버 = a,e) → 성공.
  PERFORM public.fn_manage_motion_blind_canary('create', v_owner, NULL, 'ok',
    v_group, ARRAY[v_clip2], ARRAY[v_a, v_e]);

  RAISE NOTICE 'motion double blind hardening probe: all assertions passed';
END;
$probe$;

-- 모든 assertion 통과 시에만 여기 도달한다.
SELECT 'DB_RUNTIME_PROBE_OK' AS marker;

-- 합성 row 전량 폐기 — production 오염 0.
ROLLBACK;
