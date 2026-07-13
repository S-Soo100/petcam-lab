-- ============================================================================
-- 튜토리얼 v1 seed/activation 템플릿 (실행용 아님 · owner 가 실값으로 실행)
-- ============================================================================
--
-- ⚠️ 이 파일은 실제 clip UUID·비밀값을 담지 않는 "템플릿"이다. 그대로 실행하면
--    placeholder clip 이 없어 RPC 가 raise 하며 실패한다(fail-loud). 아래 psql
--    변수(:'owner_id' 등)를 실값으로 채워 owner 가 직접 실행한다(설계 §14).
--
-- 선행 조건:
--   1) owner 가 후보 5개 clip 을 일반 v2 화면에서 "끝까지 검수 완료"해야 한다.
--      = clip_labeling_sessions.stage='completed' AND vlm_verdict NOT NULL
--        AND completion_reason='vlm_reviewed' AND current_gt/prediction_snapshot 존재.
--      (fn_seed 가 이 조건을 검사한다. VLM prediction 없는 clip 은 튜토리얼에 넣지 않는다.)
--   2) owner_id = 본인 auth.users.id (= DEV_USER_ID).
--
-- 실행: psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f 이_파일(변수 채운 사본)
--       또는 Supabase SQL editor 에서 :'...' 자리를 실값으로 치환.
-- ============================================================================

\set owner_id      'REPLACE-WITH-OWNER-UUID'
\set set_version   'tutorial-v1'
\set set_title     '라벨링 기준 5개 연습'

-- lesson 별 clip UUID (owner 완료 세션이 있는 clip). position 1..5.
\set clip1 'REPLACE-WITH-CLIP-1-UUID'   -- 가시성·unseen
\set clip2 'REPLACE-WITH-CLIP-2-UUID'   -- 일반 이동
\set clip3 'REPLACE-WITH-CLIP-3-UUID'   -- 대표 행동 대상 vs wheel evidence 분리
\set clip4 'REPLACE-WITH-CLIP-4-UUID'   -- 사람 급여의 객관 근거
\set clip5 'REPLACE-WITH-CLIP-5-UUID'   -- 모프·IR 로 인한 VLM 오판 검수

BEGIN;

-- ── 1. draft set 생성 (없으면) ─────────────────────────────────────
INSERT INTO public.labeling_tutorial_sets (version, title, status, created_by)
VALUES (:'set_version', :'set_title', 'draft', :'owner_id'::uuid)
ON CONFLICT (version) DO NOTHING;

-- 이후 단계에서 참조할 set_id 를 임시 psql 변수로 뽑는다.
SELECT id AS seed_set_id FROM public.labeling_tutorial_sets
  WHERE version = :'set_version' \gset

-- ── 2. 5개 lesson seed (owner completed session → 기준 답 복사) ─────
-- feedback_content 키는 comparison dimension 키와 일치시킨다:
--   visibility, primary_action, target, activity_intensity, enrichment_object,
--   observed_actions, interaction_types, segments, vlm_verdict, vlm_error_tags.
-- 각 값은 { "why": "...", "next": "..." }. 비어 있지 않아야 activation 을 통과한다.

SELECT public.fn_seed_tutorial_lesson_from_owner(
  :'seed_set_id'::uuid, 1::smallint, :'clip1'::uuid, :'owner_id'::uuid,
  '가시성과 unseen 구분',
  'visible/partial/absent/uncertain 를 구분하고, 안 보임(absent→unseen)과 판단 불가(uncertain)를 나눈다.',
  '게코가 프레임에 있는지부터 판단해. 안 보이면 unseen, 애매하면 uncertain.',
  '{"visibility":{"why":"프레임에서 게코 신체가 실제로 보이는지로 판단","next":"안 보임(absent)은 unseen, 애매하면 uncertain"}}'::jsonb
);

SELECT public.fn_seed_tutorial_lesson_from_owner(
  :'seed_set_id'::uuid, 2::smallint, :'clip2'::uuid, :'owner_id'::uuid,
  '일반 이동',
  '등반·위치 이동·자세 변경을 대표 행동 moving 으로 잡고, 행동 구간을 입력한다.',
  '빠르다는 이유만으로 놀이가 아니야. 이동/등반은 moving.',
  '{"primary_action":{"why":"이동/등반/자세변경은 moving","next":"빠르기만으로 playing 처리하지 않기"},"segments":{"why":"관찰 행동마다 구간이 필요","next":"각 행동의 시작/끝을 초 단위로"}}'::jsonb
);

SELECT public.fn_seed_tutorial_lesson_from_owner(
  :'seed_set_id'::uuid, 3::smallint, :'clip3'::uuid, :'owner_id'::uuid,
  '대표 행동 대상과 wheel evidence 분리',
  '대표 행동 대상(target)과 놀이 상호작용 대상(enrichment_object)은 서로 다른 질문이야. wheel 은 대표 행동 대상이 아니라 enrichment evidence 로 기록한다. drinking 의 target 은 게코가 영상에서 실제로 접촉해 핥은 대상을 근거로 고르고, 물이 화면에 직접 안 보여도 관찰된 접촉 대상으로 판단해.',
  '쳇바퀴는 target 이 아니라 enrichment_object=wheel + interaction type(ride/push/rotate)으로 기록해. 대표 행동 대상 칸에 wheel 을 넣지 마.',
  '{"target":{"why":"이 영상에서 게코가 직접 핥은 대상은 유리 표면이므로 target=glass야. wheel 은 대표 행동 대상이 아니라 별도 놀이 근거야.","next":"drinking 은 실제 접촉한 대상을 water/water_bowl/glass/floor/uncertain 중에서 골라."},"enrichment_object":{"why":"놀이 상호작용 대상은 별도 축","next":"쳇바퀴는 enrichment_object=wheel"},"interaction_types":{"why":"어떻게 상호작용했는지 근거","next":"ride/push/rotate 중 관찰된 것"}}'::jsonb
);

SELECT public.fn_seed_tutorial_lesson_from_owner(
  :'seed_set_id'::uuid, 4::smallint, :'clip4'::uuid, :'owner_id'::uuid,
  '사람 급여의 객관 근거',
  '사람 급여(hand_feeding)는 손/도구의 존재만으로 정하지 않아. 음식이 입으로 직접 전달되는 장면이어야 하고, 실제 세부 동작은 licking 또는 prey capture 로, target 은 hand/tool, context 는 human 으로 기록한다.',
  '손이 보여도 먹이 전달·게코 반응(핥기/포획)이 없으면 hand_feeding 이 아니야.',
  '{"primary_action":{"why":"손/도구가 먹이를 입으로 직접 전달하는 장면","next":"근거 없으면 hand_feeding 아님"},"observed_actions":{"why":"실제 세부 동작은 licking 또는 prey_capture","next":"대표는 하나, 관찰 동작은 실제 본 것"},"target":{"why":"급여 대상은 손 또는 도구","next":"hand/tool 중 하나"},"context_tags":{"why":"사람 손·도구가 등장하는 급여 상황은 context_tags 에 human 을 넣어 표시한다","next":"hand_feeding 은 target hand/tool 과 함께 context human 이 있어야 근거가 완성돼"}}'::jsonb
);

SELECT public.fn_seed_tutorial_lesson_from_owner(
  :'seed_set_id'::uuid, 5::smallint, :'clip5'::uuid, :'owner_id'::uuid,
  '모프·IR로 인한 VLM 오판 검수',
  '모프 무늬나 야간 IR 로 VLM 이 shedding 등을 오판할 수 있어. 사람 GT 가 shedding 이 아닌데 VLM 이 shedding 이면 verdict incorrect + 오류 유형(morph_confusion/ir_or_glare 등)을 고른다.',
  'VLM action 이 shedding 이어도 실제 허물이 안 벗겨지면 오답이야. 왜 틀렸는지 유형까지 골라.',
  '{"vlm_verdict":{"why":"VLM 판정을 사람 GT 기준으로 독립 평가","next":"근거 부족이면 unjudgeable"},"vlm_error_tags":{"why":"틀린 이유를 유형으로","next":"morph_confusion vs ir_or_glare 구분"}}'::jsonb
);

-- ── 3. preview (activation 전 확인) ────────────────────────────────
SELECT position, title,
       (reference_vlm_review ->> 'verdict') AS vlm_verdict,
       jsonb_object_keys(feedback_content) AS feedback_dims
FROM public.labeling_tutorial_lessons
WHERE tutorial_set_id = :'seed_set_id'::uuid
ORDER BY position;

COMMIT;

-- ── 4. 활성화 (완전성 검사 통과 시 active 전환) ───────────────────
-- draft·5개·verdict·비어있지 않은 feedback 을 모두 만족해야 성공한다.
-- SELECT public.fn_activate_tutorial_set(:'seed_set_id'::uuid, :'owner_id'::uuid);

-- ── 5. 활성화 검증 ─────────────────────────────────────────────────
-- SELECT version, status, activated_at FROM public.labeling_tutorial_sets
--   WHERE status = 'active';
-- 기대: 방금 set 하나만 active.

-- ── 재작업 필요 시 (설계 §6·§17) ──────────────────────────────────
-- active set 은 불변이므로 수정하려면 archive 후 새 version 을 만든다:
-- UPDATE public.labeling_tutorial_sets SET status='archived' WHERE version='tutorial-v1';
-- 그다음 새 version(tutorial-v2)으로 위 절차를 반복한다.
