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
\set clip3 'REPLACE-WITH-CLIP-3-UUID'   -- wheel interaction
\set clip4 'REPLACE-WITH-CLIP-4-UUID'   -- 복수 행동·object interaction
\set clip5 'REPLACE-WITH-CLIP-5-UUID'   -- 모호한 케어 행동·VLM 오류

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
  'wheel interaction',
  '빠른 움직임을 playing 으로 단정하지 않고, wheel + ride/push/rotate evidence 와 activity intensity 를 분리한다.',
  '쳇바퀴는 enrichment_object=wheel + interaction type 으로 기록. 활동 강도는 별도.',
  '{"enrichment_object":{"why":"쳇바퀴 상호작용은 wheel","next":"interaction type(ride/push/rotate) 함께"},"interaction_types":{"why":"어떻게 상호작용했는지 근거","next":"추측 대신 관찰된 동작만"}}'::jsonb
);

SELECT public.fn_seed_tutorial_lesson_from_owner(
  :'seed_set_id'::uuid, 4::smallint, :'clip4'::uuid, :'owner_id'::uuid,
  '복수 행동·object interaction',
  '대표 행동 1개와 관찰 행동 여러 개, target, enrichment object, interaction type, 구간을 함께 입력한다.',
  '대표 행동 하나만 primary. 나머지는 observed_actions 로.',
  '{"observed_actions":{"why":"관찰된 모든 행동을 담되 대표는 하나","next":"대표 1 + 관찰 다수"},"target":{"why":"행동 대상 명시","next":"물/그릇/사물 등 실제 대상"}}'::jsonb
);

SELECT public.fn_seed_tutorial_lesson_from_owner(
  :'seed_set_id'::uuid, 5::smallint, :'clip5'::uuid, :'owner_id'::uuid,
  '모호한 케어 행동·VLM 오류',
  '실제 shedding 과 의심 장면을 나누고, confidence/unjudgeable 를 쓰며 VLM 오류 tag 를 고른다.',
  '허물이 실제로 벗겨지는지 확인. 애매하면 확신도를 낮춰.',
  '{"vlm_verdict":{"why":"VLM 판정이 맞았는지 독립적으로","next":"근거 부족이면 unjudgeable"},"vlm_error_tags":{"why":"틀린 이유를 유형으로","next":"morph_confusion vs action_confusion 구분"}}'::jsonb
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
