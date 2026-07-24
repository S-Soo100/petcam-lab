-- 권한별 라벨링 read RPC 실제 DB probe (review-fix Task 3).
--
-- 목적: 정적 텍스트 테스트로는 못 잡는 런타임 정확성을 non-empty 합성 row 로 검증한다.
--   Codex 가 찾은 "column reference camera_id is ambiguous" 는 빈 테이블 호출로는 재현되지 않으므로
--   실제 row 를 넣고 library 를 호출해 (a) ambiguous 없이 실행되고 (b) 공개 우선순위(canary→live→
--   legacy)·재검수 은닉·서버측 final_decision 필터·101 lookahead 페이지네이션이 맞는지 ASSERT 한다.
--
-- 이 파일은 일회용 blind_probe_role_reads_* DB 에서만 실행되며 BEGIN … ROLLBACK 으로 합성 row 를
-- 전량 되돌린다(잔여물 0). 러너가 rollback 뒤 residue=0 을 재확인한다.
--
-- fixture(설계 §6.3·review-fix Task 2 8개):
--   f1  legacy 단일         → final / single_legacy / label
--   f1b legacy owner        → final / owner_legacy  / label
--   f2  legacy + open canary awaiting → re_review, decision/GT null (과거 GT 은닉)
--   f3  legacy + open canary conflict → re_review, decision/GT null
--   f4  open canary agreed        → final, canary decision/GT 공개
--   f5  open canary owner_resolved → final, canary decision/GT 공개
--   f6a live awaiting  → awaiting,      decision/GT null
--   f6b live conflict  → owner_review,  decision/GT null
--   f7  102 clip pagination  → p_limit=101 첫 page 101 + next cursor 1 (100 cap 아님)
--   f8  110 label + 3 exclude → p_final_decision=exclude 가 뒤 page 결과까지 서버에서 반환

BEGIN;

-- ── 공통 fixture ─────────────────────────────────────────────────────
INSERT INTO auth.users (id) VALUES
  ('00000000-0000-4000-8000-000000000001'),
  ('00000000-0000-4000-8000-000000000002'),
  ('00000000-0000-4000-8000-000000000003');
INSERT INTO public.labelers (user_id) VALUES
  ('00000000-0000-4000-8000-000000000002'),
  ('00000000-0000-4000-8000-000000000003');
INSERT INTO public.labeler_applications (user_id, status, display_name) VALUES
  ('00000000-0000-4000-8000-000000000002', 'approved', '라벨러 A'),
  ('00000000-0000-4000-8000-000000000003', 'approved', '라벨러 B');
INSERT INTO public.cameras (id, name) VALUES
  ('00000000-0000-4000-8000-000000000200', 'probe-main'),
  ('00000000-0000-4000-8000-000000000201', 'probe-page'),
  ('00000000-0000-4000-8000-000000000202', 'probe-filter');
INSERT INTO public.motion_labeling_review_groups (id, name, active, created_by) VALUES
  ('00000000-0000-4000-8000-000000000100', 'probe-group', true,
   '00000000-0000-4000-8000-000000000001');
INSERT INTO public.motion_labeling_review_group_members (group_id, user_id, assigned_by) VALUES
  ('00000000-0000-4000-8000-000000000100', '00000000-0000-4000-8000-000000000002',
   '00000000-0000-4000-8000-000000000001'),
  ('00000000-0000-4000-8000-000000000100', '00000000-0000-4000-8000-000000000003',
   '00000000-0000-4000-8000-000000000001');

-- fixture clip(f1..f6b) — 전부 r2_key 있음(재생 가능).
INSERT INTO public.motion_clips (id, camera_id, started_at, duration_sec, r2_key) VALUES
  ('00000000-0000-4000-8000-000000001001', '00000000-0000-4000-8000-000000000200', now() - interval '1 min', 30, 'probe/f1.mp4'),
  ('00000000-0000-4000-8000-000000001002', '00000000-0000-4000-8000-000000000200', now() - interval '2 min', 30, 'probe/f1b.mp4'),
  ('00000000-0000-4000-8000-000000001003', '00000000-0000-4000-8000-000000000200', now() - interval '3 min', 30, 'probe/f2.mp4'),
  ('00000000-0000-4000-8000-000000001004', '00000000-0000-4000-8000-000000000200', now() - interval '4 min', 30, 'probe/f3.mp4'),
  ('00000000-0000-4000-8000-000000001005', '00000000-0000-4000-8000-000000000200', now() - interval '5 min', 30, 'probe/f4.mp4'),
  ('00000000-0000-4000-8000-000000001006', '00000000-0000-4000-8000-000000000200', now() - interval '6 min', 30, 'probe/f5.mp4'),
  ('00000000-0000-4000-8000-000000001007', '00000000-0000-4000-8000-000000000200', now() - interval '7 min', 30, 'probe/f6a.mp4'),
  ('00000000-0000-4000-8000-000000001008', '00000000-0000-4000-8000-000000000200', now() - interval '8 min', 30, 'probe/f6b.mp4');

-- legacy 세션: f1(단일=labelerA), f1b(owner), f2·f3(open canary 아래 숨겨질 legacy).
INSERT INTO public.motion_clip_labeling_sessions (clip_id, reviewed_by, stage, initial_gt) VALUES
  ('00000000-0000-4000-8000-000000001001', '00000000-0000-4000-8000-000000000002', 'gt_locked', '{"primary_action":"moving"}'),
  ('00000000-0000-4000-8000-000000001002', '00000000-0000-4000-8000-000000000001', 'gt_locked', '{"primary_action":"drinking"}'),
  ('00000000-0000-4000-8000-000000001003', '00000000-0000-4000-8000-000000000002', 'gt_locked', '{"primary_action":"eating_paste"}'),
  ('00000000-0000-4000-8000-000000001004', '00000000-0000-4000-8000-000000000002', 'gt_locked', '{"primary_action":"hiding"}');

-- open canary cohort(f2 awaiting / f3 conflict / f4 agreed / f5 owner_resolved).
INSERT INTO public.motion_blind_review_cohorts (id, kind, status, label, group_id, created_by) VALUES
  ('00000000-0000-4000-8000-000000000302', 'canary', 'open', 'c-await',    '00000000-0000-4000-8000-000000000100', '00000000-0000-4000-8000-000000000001'),
  ('00000000-0000-4000-8000-000000000303', 'canary', 'open', 'c-conflict', '00000000-0000-4000-8000-000000000100', '00000000-0000-4000-8000-000000000001'),
  ('00000000-0000-4000-8000-000000000304', 'canary', 'open', 'c-agreed',   '00000000-0000-4000-8000-000000000100', '00000000-0000-4000-8000-000000000001'),
  ('00000000-0000-4000-8000-000000000305', 'canary', 'open', 'c-resolved', '00000000-0000-4000-8000-000000000100', '00000000-0000-4000-8000-000000000001');

-- canary consensus: f2 awaiting, f3 conflict, f4 agreed(label+gt), f5 owner_resolved(exclude).
INSERT INTO public.motion_clip_consensus
  (clip_id, group_id, cohort_kind, cohort_id, status, final_decision, final_gt) VALUES
  ('00000000-0000-4000-8000-000000001003', '00000000-0000-4000-8000-000000000100', 'canary', '00000000-0000-4000-8000-000000000302', 'awaiting', NULL, NULL),
  ('00000000-0000-4000-8000-000000001004', '00000000-0000-4000-8000-000000000100', 'canary', '00000000-0000-4000-8000-000000000303', 'conflict', NULL, NULL),
  ('00000000-0000-4000-8000-000000001005', '00000000-0000-4000-8000-000000000100', 'canary', '00000000-0000-4000-8000-000000000304', 'agreed', 'label', '{"primary_action":"basking"}'),
  ('00000000-0000-4000-8000-000000001006', '00000000-0000-4000-8000-000000000100', 'canary', '00000000-0000-4000-8000-000000000305', 'owner_resolved', 'exclude', NULL);

-- live consensus: f6a awaiting, f6b conflict.
INSERT INTO public.motion_clip_consensus
  (clip_id, group_id, cohort_kind, cohort_id, status, final_decision, final_gt) VALUES
  ('00000000-0000-4000-8000-000000001007', '00000000-0000-4000-8000-000000000100', 'live', NULL, 'awaiting', NULL, NULL),
  ('00000000-0000-4000-8000-000000001008', '00000000-0000-4000-8000-000000000100', 'live', NULL, 'conflict', NULL, NULL);

-- ── ROLE_READS_RUNTIME_OK: non-empty 호출 + 공개 라벨 정확성(f1/f1b/f4/f5) ──
DO $$
DECLARE r record;
BEGIN
  -- f1 단일 legacy.
  SELECT * INTO r FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_clip_id  => '00000000-0000-4000-8000-000000001001'::uuid);
  ASSERT r.label_state = 'final', format('f1 state=%s', r.label_state);
  ASSERT r.label_source = 'single_legacy', format('f1 source=%s', r.label_source);
  ASSERT r.final_decision = 'label', format('f1 decision=%s', r.final_decision);
  ASSERT r.final_gt IS NOT NULL, 'f1 gt null';

  -- f1b owner legacy.
  SELECT * INTO r FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_clip_id  => '00000000-0000-4000-8000-000000001002'::uuid);
  ASSERT r.label_source = 'owner_legacy', format('f1b source=%s', r.label_source);
  ASSERT r.final_decision = 'label', format('f1b decision=%s', r.final_decision);

  -- f4 open canary agreed → canary final 공개.
  SELECT * INTO r FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_clip_id  => '00000000-0000-4000-8000-000000001005'::uuid);
  ASSERT r.label_state = 'final', format('f4 state=%s', r.label_state);
  ASSERT r.label_source = 'blind_consensus', format('f4 source=%s', r.label_source);
  ASSERT r.final_decision = 'label', format('f4 decision=%s', r.final_decision);
  ASSERT r.final_gt IS NOT NULL, 'f4 gt null';

  -- f5 open canary owner_resolved(exclude) → canary final 공개, GT null(비-label).
  SELECT * INTO r FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_clip_id  => '00000000-0000-4000-8000-000000001006'::uuid);
  ASSERT r.label_state = 'final', format('f5 state=%s', r.label_state);
  ASSERT r.final_decision = 'exclude', format('f5 decision=%s', r.final_decision);
  ASSERT r.final_gt IS NULL, 'f5 gt not null';

  -- history RPC non-empty 호출(labelerA 본인 제출)은 아래 pagination 블록에서 검증한다.
  -- overview RPC non-empty 호출: 활성 그룹·열린 canary 를 집계로 반환한다.
  PERFORM public.fn_get_motion_blind_owner_overview(current_date);
END $$;
SELECT 'ROLE_READS_RUNTIME_OK';

-- ── ROLE_READS_BLIND_GUARD_OK: 재검수/미확정 은닉(f2/f3/f6a/f6b) ──
DO $$
DECLARE r record; o jsonb;
BEGIN
  -- f2 legacy + open canary awaiting → re_review, 과거 GT/decision 은닉.
  SELECT * INTO r FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_clip_id  => '00000000-0000-4000-8000-000000001003'::uuid);
  ASSERT r.label_state = 're_review', format('f2 state=%s', r.label_state);
  ASSERT r.final_decision IS NULL, format('f2 decision leaked=%s', r.final_decision);
  ASSERT r.final_gt IS NULL, 'f2 gt leaked';

  -- f3 legacy + open canary conflict → re_review, 은닉.
  SELECT * INTO r FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_clip_id  => '00000000-0000-4000-8000-000000001004'::uuid);
  ASSERT r.label_state = 're_review', format('f3 state=%s', r.label_state);
  ASSERT r.final_decision IS NULL, 'f3 decision leaked';
  ASSERT r.final_gt IS NULL, 'f3 gt leaked';

  -- f6a live awaiting → 'awaiting', 은닉.
  SELECT * INTO r FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_clip_id  => '00000000-0000-4000-8000-000000001007'::uuid);
  ASSERT r.label_state = 'awaiting', format('f6a state=%s', r.label_state);
  ASSERT r.final_decision IS NULL, 'f6a decision leaked';

  -- f6b live conflict → 'owner_review', 은닉.
  SELECT * INTO r FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_clip_id  => '00000000-0000-4000-8000-000000001008'::uuid);
  ASSERT r.label_state = 'owner_review', format('f6b state=%s', r.label_state);
  ASSERT r.final_decision IS NULL, 'f6b decision leaked';

  -- label_state=re_review 필터가 정확히 f2·f3 두 건만 반환(main 카메라 한정).
  ASSERT (SELECT count(*) FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_camera_ids => ARRAY['00000000-0000-4000-8000-000000000200']::uuid[],
    p_label_state => 're_review')) = 2, 're_review filter count';

  -- overview 는 집계만 반환하고 개별 제출 body·reviewer UUID 를 노출하지 않는다(열린 canary 4개).
  o := public.fn_get_motion_blind_owner_overview(current_date);
  ASSERT jsonb_typeof(o->'groups') = 'array', 'overview groups not array';
  ASSERT jsonb_array_length(o->'open_canaries') = 4, format('overview open canaries=%s', jsonb_array_length(o->'open_canaries'));
END $$;
SELECT 'ROLE_READS_BLIND_GUARD_OK';

-- ── pagination fixture(f7) + 서버측 final_decision 필터(f8) ──
-- f7: page 카메라에 102 clip(라벨 없음) — p_limit=101 이 101 을 반환(100 cap 아님) + next cursor 1.
INSERT INTO public.motion_clips (id, camera_id, started_at, duration_sec, r2_key)
SELECT ('00000000-0000-4000-8000-1000' || lpad(to_hex(g), 8, '0'))::uuid,
       '00000000-0000-4000-8000-000000000201'::uuid,
       now() - (g || ' seconds')::interval, 30, 'probe/page.mp4'
FROM generate_series(1, 102) AS g;

-- f8: filter 카메라에 110 label(최신) + 3 exclude(가장 오래됨) live consensus.
INSERT INTO public.motion_clips (id, camera_id, started_at, duration_sec, r2_key)
SELECT ('00000000-0000-4000-8000-2000' || lpad(to_hex(g), 8, '0'))::uuid,
       '00000000-0000-4000-8000-000000000202'::uuid,
       now() - (g || ' minutes')::interval, 30, 'probe/lbl.mp4'
FROM generate_series(1, 110) AS g;
INSERT INTO public.motion_clip_consensus (clip_id, group_id, cohort_kind, cohort_id, status, final_decision, final_gt)
SELECT ('00000000-0000-4000-8000-2000' || lpad(to_hex(g), 8, '0'))::uuid,
       '00000000-0000-4000-8000-000000000100'::uuid, 'live', NULL, 'agreed', 'label', '{"primary_action":"moving"}'
FROM generate_series(1, 110) AS g;
INSERT INTO public.motion_clips (id, camera_id, started_at, duration_sec, r2_key)
SELECT ('00000000-0000-4000-8000-3000' || lpad(to_hex(g), 8, '0'))::uuid,
       '00000000-0000-4000-8000-000000000202'::uuid,
       now() - interval '300 minutes' - (g || ' minutes')::interval, 30, 'probe/exc.mp4'
FROM generate_series(1, 3) AS g;
INSERT INTO public.motion_clip_consensus (clip_id, group_id, cohort_kind, cohort_id, status, final_decision, final_gt)
SELECT ('00000000-0000-4000-8000-3000' || lpad(to_hex(g), 8, '0'))::uuid,
       '00000000-0000-4000-8000-000000000100'::uuid, 'live', NULL, 'agreed', 'exclude', NULL
FROM generate_series(1, 3) AS g;

DO $$
DECLARE n int; v_t timestamptz; v_id uuid; bad int;
BEGIN
  -- f7: p_limit=101 → 첫 page 정확히 101(100 cap 이면 여기서 실패).
  SELECT count(*) INTO n FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_camera_ids => ARRAY['00000000-0000-4000-8000-000000000201']::uuid[],
    p_limit => 101);
  ASSERT n = 101, format('f7 first page=%s (expected 101 lookahead)', n);

  -- 101 번째 행을 cursor 로 다음 page → 나머지 1건(총 102).
  SELECT started_at, clip_id INTO v_t, v_id FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_camera_ids => ARRAY['00000000-0000-4000-8000-000000000201']::uuid[],
    p_limit => 101) OFFSET 100 LIMIT 1;
  SELECT count(*) INTO n FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_camera_ids => ARRAY['00000000-0000-4000-8000-000000000201']::uuid[],
    p_cursor_started_at => v_t, p_cursor_id => v_id, p_limit => 101);
  ASSERT n = 1, format('f7 next page=%s (expected 1)', n);

  -- f8: 필터 없는 첫 page(101)에는 exclude 가 0(전부 최신 label). 서버 필터만이 뒤 page 결과를 낸다.
  SELECT count(*) INTO bad FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_camera_ids => ARRAY['00000000-0000-4000-8000-000000000202']::uuid[],
    p_limit => 101) WHERE final_decision = 'exclude';
  ASSERT bad = 0, format('f8 unfiltered first page exclude=%s (expected 0, all newest are label)', bad);

  -- p_final_decision=exclude → 서버가 뒤 page 의 exclude 3건을 모두 반환(client-side page 좁힘이면 0).
  SELECT count(*) INTO n FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_camera_ids => ARRAY['00000000-0000-4000-8000-000000000202']::uuid[],
    p_final_decision => 'exclude', p_limit => 101);
  ASSERT n = 3, format('f8 filtered exclude=%s (expected 3)', n);
  SELECT count(*) INTO bad FROM public.fn_list_motion_labeling_library(
    p_owner_id => '00000000-0000-4000-8000-000000000001'::uuid,
    p_camera_ids => ARRAY['00000000-0000-4000-8000-000000000202']::uuid[],
    p_final_decision => 'exclude', p_limit => 101) WHERE final_decision <> 'exclude';
  ASSERT bad = 0, format('f8 filter leaked non-exclude=%s', bad);
END $$;

-- history RPC pagination: labelerA 의 102 제출(page clip 재사용) → p_limit=101 이 101 을 반환.
INSERT INTO public.motion_clip_review_slots (id, clip_id, group_id, reviewer_id, cohort_kind, activity_day_kst, submitted_at)
SELECT ('00000000-0000-4000-8000-4000' || lpad(to_hex(g), 8, '0'))::uuid,
       ('00000000-0000-4000-8000-1000' || lpad(to_hex(g), 8, '0'))::uuid,
       '00000000-0000-4000-8000-000000000100'::uuid,
       '00000000-0000-4000-8000-000000000002'::uuid, 'live', current_date, now()
FROM generate_series(1, 102) AS g;
INSERT INTO public.motion_clip_blind_submissions
  (slot_id, clip_id, group_id, reviewer_id, cohort_kind, decision, reason_code, digest, submitted_at)
SELECT ('00000000-0000-4000-8000-4000' || lpad(to_hex(g), 8, '0'))::uuid,
       ('00000000-0000-4000-8000-1000' || lpad(to_hex(g), 8, '0'))::uuid,
       '00000000-0000-4000-8000-000000000100'::uuid,
       '00000000-0000-4000-8000-000000000002'::uuid, 'live', 'exclude', 'gecko_absent', 'd' || g,
       now() - (g || ' seconds')::interval
FROM generate_series(1, 102) AS g;

DO $$
DECLARE n int;
BEGIN
  -- history non-empty 호출 + 101 lookahead cap.
  SELECT count(*) INTO n FROM public.fn_list_motion_blind_history(
    p_reviewer_id => '00000000-0000-4000-8000-000000000002'::uuid,
    p_limit => 101);
  ASSERT n = 101, format('history first page=%s (expected 101 lookahead)', n);
END $$;
SELECT 'ROLE_READS_PAGINATION_OK';

ROLLBACK;
