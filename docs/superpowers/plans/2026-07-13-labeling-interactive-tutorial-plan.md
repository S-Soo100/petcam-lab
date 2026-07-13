# 라벨링 대화형 튜토리얼 — 구현 계획서

> **구현 방식 (CAOF):** Critical 트랙(4+ 파일·새 시스템·보안 게이트). 이 계획을 task 단위로 메인이 직접 구현하고, 각 Phase 끝에서 커밋한다(동시 세션 안전). Steps는 `- [ ]` 체크박스.
> **선행 스펙(SOT):** [`docs/superpowers/specs/2026-07-13-labeling-interactive-tutorial-design.md`](../specs/2026-07-13-labeling-interactive-tutorial-design.md)
> **작성일:** 2026-07-13

**Goal:** 승인된 신규 라벨러가 일반 큐에 들어가기 전, owner가 고정한 5개 영상으로 `Blind GT → VLM 검수 → 기준 피드백`을 학습하게 하고, 튜토리얼 답안을 production GT와 완전히 분리한다.

**Architecture:** 새 테이블 4개(set/lesson/progress/attempt)는 RLS ENABLE + service_role 전용, 정답은 review 제출 전 절대 미노출. 접근 게이트는 기존 `requireLabelingAccess`/`loadClipWithPerms` 위에 튜토리얼 완료 체크를 얹은 `requireProductionLabelingAccess`로 강제(client redirect 아님). 답안 비교는 서버 순수 함수, active lesson은 불변. UI는 기존 상세 페이지의 플레이어·GT/VLM 폼을 mode-independent 컴포넌트로 추출해 production/tutorial이 공유하되 저장 API는 분리.

**Tech Stack:** Next.js App Router(client layout gate) · Supabase(Postgres RLS + SECURITY DEFINER RPC) · TypeScript · vitest(`npm test`) · R2 presignGet.

---

## 파일 구조 (create / modify)

**Create**
- `migrations/2026-07-13_labeling_tutorial.sql` — 4 테이블 + partial unique + 불변 트리거 + activation/acknowledge/reset/waive/seed RPC + 검증/롤백
- `web/src/lib/labelingTutorial.ts` — 튜토리얼 타입 + `compareTutorialAnswers` 순수 비교 함수 + `deepEqualAnswer`
- `web/src/lib/labelingTutorial.test.ts` — 비교/idempotency 순수 로직 테스트
- `web/src/lib/labelingTutorialGate.ts` — server-only: `loadActiveTutorial`, `getTutorialAccess`, `tutorialGateResponse`
- `web/src/lib/labelingTutorialGate.test.ts`
- `web/src/app/api/labeling-tutorial/route.ts` — overview
- `web/src/app/api/labeling-tutorial/lessons/[position]/route.ts` — lesson 상세(공개/제출후 분기)
- `web/src/app/api/labeling-tutorial/lessons/[position]/thumbnail/url/route.ts`
- `web/src/app/api/labeling-tutorial/lessons/[position]/file/url/route.ts`
- `web/src/app/api/labeling-tutorial/lessons/[position]/gt/route.ts`
- `web/src/app/api/labeling-tutorial/lessons/[position]/vlm-review/route.ts`
- `web/src/app/api/labeling-tutorial/lessons/[position]/acknowledge/route.ts`
- `web/src/app/api/labeling-tutorial/_helpers.ts` — lesson-by-position 로더 + attempt 로더
- `web/src/app/api/labeling-tutorial/team-progress/route.ts`
- `web/src/app/api/labeling-tutorial/users/[userId]/reset/route.ts`
- `web/src/app/api/labeling-tutorial/users/[userId]/waive/route.ts`
- `web/src/app/api/labeling-tutorial/lessons/[position]/vlm-review/route.test.ts` — reference 미노출 + 409
- `web/src/app/api/labeling-tutorial/lessons/[position]/gt/route.test.ts` — idempotency + 409
- `web/src/app/labeling/_labeling-forms.tsx` — 추출한 label maps + Choice/ChoiceRow/SelectField/SegmentRow + GroundTruthForm/VlmReviewCard/GtSummary/MetadataCard/VideoPlayer + emptyGt
- `web/src/app/labeling/tutorial/_tutorial-feedback.tsx` — matched/review/subjective 피드백 렌더
- `web/src/app/labeling/tutorial/page.tsx` — 요약/시작
- `web/src/app/labeling/tutorial/[position]/page.tsx` — lesson 상태 머신

**Modify**
- `web/src/lib/labelingAccess.ts` — `requireProductionLabelingAccess` 추가 (re-export `getTutorialAccess`)
- `web/src/lib/clipPerms.ts` — `loadClipWithPerms`에 튜토리얼 게이트(403 `tutorial_required`) 삽입
- `web/src/lib/labelingApi.ts` — tutorial 클라이언트 함수 + 타입, `LabelingAccessInfo.tutorial`
- `web/src/app/api/labeling-access/route.ts` — 응답에 `tutorial` 추가
- `web/src/app/api/labeling-v2/queue/route.ts` — `requireLabelingAccess` → `requireProductionLabelingAccess`
- `web/src/app/labeling/[clipId]/page.tsx` — 추출 컴포넌트로 교체(동작 동일)
- `web/src/app/labeling/layout.tsx` — tutorial 카테고리 + redirect + 내비 badge
- `web/src/app/labeling/team/page.tsx` — 튜토리얼 진행 섹션
- `docs/DATABASE.md`, `docs/FEATURES.md`, `specs/next-session.md`, 설계 문서 상태 갱신

---

## Phase 0 — Migration (데이터 모델·RPC)

**Files:** Create `migrations/2026-07-13_labeling_tutorial.sql`

- [ ] **Step 1: 4 테이블 + 인덱스 + 불변 트리거 작성**

```sql
-- 라벨링 대화형 튜토리얼: 고정 5개 lesson + 라벨러 시도 기록.
-- 정답(reference_gt/prediction_snapshot/reference_vlm_review/feedback_content)은
-- RLS + service_role 전용으로 보호하며 review 제출 전 API 응답에 넣지 않는다.
-- 튜토리얼 답안은 behavior_labels / clip_labeling_sessions 에 절대 쓰지 않는다.

BEGIN;

CREATE TABLE IF NOT EXISTS public.labeling_tutorial_sets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  version TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'active', 'archived')),
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  activated_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- status='active' 는 전체 1개만. partial unique index.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_one_active_tutorial_set
  ON public.labeling_tutorial_sets ((status)) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS public.labeling_tutorial_lessons (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tutorial_set_id UUID NOT NULL
    REFERENCES public.labeling_tutorial_sets(id) ON DELETE RESTRICT,
  position SMALLINT NOT NULL CHECK (position BETWEEN 1 AND 5),
  clip_id UUID NOT NULL REFERENCES public.camera_clips(id) ON DELETE RESTRICT,
  title TEXT NOT NULL,
  learning_objective TEXT NOT NULL,
  pre_submit_tip TEXT,
  reference_gt JSONB NOT NULL,
  prediction_snapshot JSONB NOT NULL,
  reference_vlm_review JSONB NOT NULL,
  feedback_content JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tutorial_set_id, position),
  UNIQUE (tutorial_set_id, clip_id)
);

CREATE TABLE IF NOT EXISTS public.labeling_tutorial_progress (
  tutorial_set_id UUID NOT NULL
    REFERENCES public.labeling_tutorial_sets(id) ON DELETE RESTRICT,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  current_run_no INTEGER NOT NULL DEFAULT 1,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  waived_at TIMESTAMPTZ,
  waived_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  waiver_reason TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (tutorial_set_id, user_id),
  CONSTRAINT tutorial_waiver_reason_len
    CHECK (waiver_reason IS NULL OR CHAR_LENGTH(waiver_reason) BETWEEN 1 AND 200)
);

CREATE TABLE IF NOT EXISTS public.labeling_tutorial_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tutorial_set_id UUID NOT NULL
    REFERENCES public.labeling_tutorial_sets(id) ON DELETE RESTRICT,
  lesson_id UUID NOT NULL
    REFERENCES public.labeling_tutorial_lessons(id) ON DELETE RESTRICT,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  run_no INTEGER NOT NULL DEFAULT 1,
  stage TEXT NOT NULL DEFAULT 'gt_locked'
    CHECK (stage IN ('draft', 'gt_locked', 'review_submitted', 'completed')),
  submitted_gt JSONB,
  submitted_vlm_review JSONB,
  comparison JSONB,
  gt_locked_at TIMESTAMPTZ,
  review_submitted_at TIMESTAMPTZ,
  feedback_viewed_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (tutorial_set_id, lesson_id, user_id, run_no)
);

CREATE INDEX IF NOT EXISTS idx_tutorial_attempts_user_set_run_stage
  ON public.labeling_tutorial_attempts (user_id, tutorial_set_id, run_no, stage);

-- 최초 제출값·비교는 불변. 클라이언트 덮어쓰기 backstop(라우트도 409 로 막지만 DB 가 최종 방어).
CREATE OR REPLACE FUNCTION public.protect_tutorial_attempt()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.submitted_gt IS NOT NULL
     AND NEW.submitted_gt IS DISTINCT FROM OLD.submitted_gt THEN
    RAISE EXCEPTION 'submitted_gt is immutable';
  END IF;
  IF OLD.submitted_vlm_review IS NOT NULL
     AND NEW.submitted_vlm_review IS DISTINCT FROM OLD.submitted_vlm_review THEN
    RAISE EXCEPTION 'submitted_vlm_review is immutable';
  END IF;
  IF OLD.comparison IS NOT NULL
     AND NEW.comparison IS DISTINCT FROM OLD.comparison THEN
    RAISE EXCEPTION 'comparison is immutable';
  END IF;
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS protect_tutorial_attempt ON public.labeling_tutorial_attempts;
CREATE TRIGGER protect_tutorial_attempt
BEFORE UPDATE ON public.labeling_tutorial_attempts
FOR EACH ROW EXECUTE FUNCTION public.protect_tutorial_attempt();
```

- [ ] **Step 2: RLS + service_role 전용 (4 테이블 모두)**

```sql
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'labeling_tutorial_sets','labeling_tutorial_lessons',
    'labeling_tutorial_progress','labeling_tutorial_attempts'
  ] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', t);
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC;', t);
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon;', t);
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM authenticated;', t);
    EXECUTE format('GRANT ALL ON TABLE public.%I TO service_role;', t);
  END LOOP;
END $$;
-- client role 정책은 만들지 않는다(§9). 정답 JSON 은 브라우저 직접 조회 불가.
```

- [ ] **Step 3: activation RPC — 정확히 5개·정답 완전성 검사 후 active 전환**

```sql
CREATE OR REPLACE FUNCTION public.fn_activate_tutorial_set(
  p_set_id UUID, p_owner_id UUID
) RETURNS public.labeling_tutorial_sets
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_set public.labeling_tutorial_sets%ROWTYPE;
  v_ok_count INTEGER;
BEGIN
  SELECT * INTO v_set FROM public.labeling_tutorial_sets
    WHERE id = p_set_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'set not found' USING ERRCODE='P0002'; END IF;

  -- position 1..5 가 정확히 채워지고 모든 기준 snapshot 이 존재해야 한다.
  SELECT COUNT(*) INTO v_ok_count FROM public.labeling_tutorial_lessons
    WHERE tutorial_set_id = p_set_id
      AND position BETWEEN 1 AND 5
      AND reference_gt IS NOT NULL AND prediction_snapshot IS NOT NULL
      AND reference_vlm_review IS NOT NULL AND feedback_content IS NOT NULL;
  IF v_ok_count <> 5
     OR (SELECT COUNT(DISTINCT position) FROM public.labeling_tutorial_lessons
         WHERE tutorial_set_id = p_set_id) <> 5 THEN
    RAISE EXCEPTION 'tutorial set incomplete: need 5 complete lessons'
      USING ERRCODE='22023';
  END IF;

  UPDATE public.labeling_tutorial_sets
    SET status='archived', updated_at=NOW()
    WHERE status='active' AND id <> p_set_id;
  UPDATE public.labeling_tutorial_sets
    SET status='active', activated_at=NOW(), updated_at=NOW()
    WHERE id = p_set_id RETURNING * INTO v_set;
  RETURN v_set;
END;
$$;
```

- [ ] **Step 4: acknowledge / reset / waive / seed RPC**

```sql
-- 피드백 확인 → lesson 완료. 5개 완료면 같은 트랜잭션에서 progress.completed_at.
CREATE OR REPLACE FUNCTION public.fn_acknowledge_tutorial_lesson(
  p_attempt_id UUID, p_user_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_att public.labeling_tutorial_attempts%ROWTYPE;
  v_done INTEGER;
  v_total_completed BOOLEAN := FALSE;
BEGIN
  SELECT * INTO v_att FROM public.labeling_tutorial_attempts
    WHERE id = p_attempt_id AND user_id = p_user_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'attempt not found' USING ERRCODE='P0002'; END IF;
  IF v_att.stage NOT IN ('review_submitted','completed') THEN
    RAISE EXCEPTION 'feedback not available yet' USING ERRCODE='22023';
  END IF;

  IF v_att.stage <> 'completed' THEN
    UPDATE public.labeling_tutorial_attempts
      SET stage='completed', feedback_viewed_at=COALESCE(feedback_viewed_at,NOW()),
          completed_at=NOW()
      WHERE id = p_attempt_id RETURNING * INTO v_att;
  END IF;

  SELECT COUNT(*) INTO v_done FROM public.labeling_tutorial_attempts
    WHERE tutorial_set_id=v_att.tutorial_set_id AND user_id=p_user_id
      AND run_no=v_att.run_no AND stage='completed';
  IF v_done >= 5 THEN
    UPDATE public.labeling_tutorial_progress
      SET completed_at=COALESCE(completed_at,NOW()), updated_at=NOW()
      WHERE tutorial_set_id=v_att.tutorial_set_id AND user_id=p_user_id;
    v_total_completed := TRUE;
  END IF;

  RETURN jsonb_build_object('attempt', to_jsonb(v_att),
                            'tutorial_completed', v_total_completed);
END;
$$;

-- 다시 시작: run 번호만 +1, 기존 attempt 보존, progress 리셋.
CREATE OR REPLACE FUNCTION public.fn_reset_tutorial(
  p_set_id UUID, p_user_id UUID, p_owner_id UUID
) RETURNS public.labeling_tutorial_progress
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_p public.labeling_tutorial_progress%ROWTYPE;
BEGIN
  INSERT INTO public.labeling_tutorial_progress
    (tutorial_set_id,user_id,current_run_no,started_at,updated_at)
    VALUES (p_set_id,p_user_id,1,NOW(),NOW())
  ON CONFLICT (tutorial_set_id,user_id) DO UPDATE
    SET current_run_no = public.labeling_tutorial_progress.current_run_no + 1,
        started_at=NOW(), completed_at=NULL,
        waived_at=NULL, waived_by=NULL, waiver_reason=NULL, updated_at=NOW()
  RETURNING * INTO v_p;
  RETURN v_p;
END;
$$;

-- 완료 면제: 사유 1~200자 필수. audit(waived_by/at/reason) 보존.
CREATE OR REPLACE FUNCTION public.fn_waive_tutorial(
  p_set_id UUID, p_user_id UUID, p_owner_id UUID, p_reason TEXT
) RETURNS public.labeling_tutorial_progress
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE v_p public.labeling_tutorial_progress%ROWTYPE;
BEGIN
  IF p_reason IS NULL OR CHAR_LENGTH(BTRIM(p_reason)) NOT BETWEEN 1 AND 200 THEN
    RAISE EXCEPTION 'reason 1..200 chars required' USING ERRCODE='22023';
  END IF;
  INSERT INTO public.labeling_tutorial_progress
    (tutorial_set_id,user_id,current_run_no,started_at,
     waived_at,waived_by,waiver_reason,updated_at)
    VALUES (p_set_id,p_user_id,1,NOW(),NOW(),p_owner_id,BTRIM(p_reason),NOW())
  ON CONFLICT (tutorial_set_id,user_id) DO UPDATE
    SET waived_at=NOW(), waived_by=p_owner_id,
        waiver_reason=BTRIM(p_reason), updated_at=NOW()
  RETURNING * INTO v_p;
  RETURN v_p;
END;
$$;

-- seed: owner 의 완료된 clip_labeling_sessions 에서 기준 답을 복사(§14-3). draft lesson upsert.
-- 실제 clip_id·문구는 owner 가 나중에 실값으로 실행한다(Claude 커밋엔 실 UUID 없음).
CREATE OR REPLACE FUNCTION public.fn_seed_tutorial_lesson_from_owner(
  p_set_id UUID, p_position SMALLINT, p_clip_id UUID, p_owner_id UUID,
  p_title TEXT, p_objective TEXT, p_tip TEXT, p_feedback JSONB
) RETURNS public.labeling_tutorial_lessons
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  v_s public.clip_labeling_sessions%ROWTYPE;
  v_lesson public.labeling_tutorial_lessons%ROWTYPE;
BEGIN
  SELECT * INTO v_s FROM public.clip_labeling_sessions
    WHERE clip_id=p_clip_id AND reviewed_by=p_owner_id AND stage='completed';
  IF NOT FOUND THEN RAISE EXCEPTION 'owner completed session not found' USING ERRCODE='P0002'; END IF;
  IF v_s.current_gt IS NULL OR v_s.prediction_snapshot IS NULL THEN
    RAISE EXCEPTION 'session missing gt or prediction' USING ERRCODE='22023';
  END IF;

  INSERT INTO public.labeling_tutorial_lessons
    (tutorial_set_id,position,clip_id,title,learning_objective,pre_submit_tip,
     reference_gt,prediction_snapshot,reference_vlm_review,feedback_content,updated_at)
    VALUES (p_set_id,p_position,p_clip_id,p_title,p_objective,p_tip,
      v_s.current_gt, v_s.prediction_snapshot,
      jsonb_build_object('verdict',v_s.vlm_verdict,
                         'error_tags',to_jsonb(v_s.vlm_error_tags),
                         'note',v_s.vlm_review_note),
      p_feedback, NOW())
  ON CONFLICT (tutorial_set_id,position) DO UPDATE
    SET clip_id=EXCLUDED.clip_id, title=EXCLUDED.title,
        learning_objective=EXCLUDED.learning_objective,
        pre_submit_tip=EXCLUDED.pre_submit_tip,
        reference_gt=EXCLUDED.reference_gt,
        prediction_snapshot=EXCLUDED.prediction_snapshot,
        reference_vlm_review=EXCLUDED.reference_vlm_review,
        feedback_content=EXCLUDED.feedback_content, updated_at=NOW()
  RETURNING * INTO v_lesson;
  RETURN v_lesson;
END;
$$;
```

- [ ] **Step 5: RPC 권한 회수 + service_role 부여, COMMIT, 검증/롤백 주석**

```sql
DO $$
DECLARE f TEXT;
BEGIN
  FOREACH f IN ARRAY ARRAY[
    'fn_activate_tutorial_set(UUID,UUID)',
    'fn_acknowledge_tutorial_lesson(UUID,UUID)',
    'fn_reset_tutorial(UUID,UUID,UUID)',
    'fn_waive_tutorial(UUID,UUID,UUID,TEXT)',
    'fn_seed_tutorial_lesson_from_owner(UUID,SMALLINT,UUID,UUID,TEXT,TEXT,TEXT,JSONB)'
  ] LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION public.%s FROM PUBLIC;', f);
    EXECUTE format('REVOKE ALL ON FUNCTION public.%s FROM anon;', f);
    EXECUTE format('REVOKE ALL ON FUNCTION public.%s FROM authenticated;', f);
    EXECUTE format('GRANT EXECUTE ON FUNCTION public.%s TO service_role;', f);
  END LOOP;
END $$;

COMMIT;

-- 검증:
-- SELECT COUNT(*) FROM pg_policies WHERE tablename LIKE 'labeling_tutorial_%'; -- 기대 0
-- SELECT tablename, rowsecurity FROM pg_tables WHERE tablename LIKE 'labeling_tutorial_%'; -- 모두 t
-- 롤백: DROP FUNCTION ... ; DROP TABLE labeling_tutorial_attempts, _progress, _lessons, _sets CASCADE;
```

- [ ] **Step 6: Supabase 적용 후 검증 쿼리 실행** (사용자 승인 후 `mcp__supabase__apply_migration`)

Run 검증: `pg_policies` 0건, 4 테이블 rowsecurity=t.

- [ ] **Step 7: Commit** — `git commit -m "feat: 튜토리얼 테이블·RPC 마이그레이션(RLS service_role 전용)"`

---

## Phase 1 — 타입 + 비교 순수 함수

**Files:** Create `web/src/lib/labelingTutorial.ts`, `web/src/lib/labelingTutorial.test.ts`

- [ ] **Step 1: 실패 테스트 작성** (`labelingTutorial.test.ts`)

```ts
import { describe, expect, it } from 'vitest';
import { compareTutorialAnswers, deepEqualAnswer } from './labelingTutorial';
import type { GroundTruthInput, VlmReviewInput } from './labelingV2';

const baseGt: GroundTruthInput = {
  visibility: 'visible', primary_action: 'drinking', observed_actions: ['licking'],
  segments: [{ action: 'licking', start_sec: 2, end_sec: 8 }], target: 'water',
  human_confidence: 'certain', context_tags: ['ir'], activity_intensity: 'low',
  enrichment_object: 'none', interaction_types: [], note: null,
};
const baseReview: VlmReviewInput = { verdict: 'incorrect', error_tags: ['action_confusion'], note: null };

describe('compareTutorialAnswers', () => {
  it('exact 필드 불일치를 review 로 분류한다', () => {
    const yours = { ...baseGt, primary_action: 'moving' as const };
    const cmp = compareTutorialAnswers(yours, baseReview, baseGt, baseReview);
    const primary = cmp.dimensions.find((d) => d.key === 'primary_action')!;
    expect(primary.group).toBe('review');
  });
  it('set 필드는 순서 무관 동일 집합이면 matched', () => {
    const ref = { ...baseGt, observed_actions: ['licking', 'moving'] as const };
    const yours = { ...baseGt, observed_actions: ['moving', 'licking'] as const };
    const cmp = compareTutorialAnswers(yours, baseReview, ref, baseReview);
    expect(cmp.dimensions.find((d) => d.key === 'observed_actions')!.group).toBe('matched');
  });
  it('segment 는 같은 action start/end 1초 이내면 matched', () => {
    const yours = { ...baseGt, segments: [{ action: 'licking' as const, start_sec: 2.7, end_sec: 8.9 }] };
    expect(compareTutorialAnswers(yours, baseReview, baseGt, baseReview)
      .dimensions.find((d) => d.key === 'segments')!.group).toBe('matched');
  });
  it('segment 오차 1초 초과는 review', () => {
    const yours = { ...baseGt, segments: [{ action: 'licking' as const, start_sec: 2, end_sec: 10.5 }] };
    expect(compareTutorialAnswers(yours, baseReview, baseGt, baseReview)
      .dimensions.find((d) => d.key === 'segments')!.group).toBe('review');
  });
  it('human_confidence/context_tags/note 는 subjective', () => {
    const cmp = compareTutorialAnswers({ ...baseGt, human_confidence: 'likely' }, baseReview, baseGt, baseReview);
    expect(cmp.dimensions.find((d) => d.key === 'human_confidence')!.group).toBe('subjective');
  });
  it('aggregate pass/fail 을 계산하지 않는다', () => {
    const cmp = compareTutorialAnswers(baseGt, baseReview, baseGt, baseReview);
    expect(cmp).not.toHaveProperty('score');
    expect(cmp).not.toHaveProperty('passed');
  });
});

describe('deepEqualAnswer', () => {
  it('키 순서·배열 동일성 판정(idempotency 용)', () => {
    expect(deepEqualAnswer({ a: 1, b: [1, 2] }, { b: [1, 2], a: 1 })).toBe(true);
    expect(deepEqualAnswer({ a: 1 }, { a: 2 })).toBe(false);
  });
});
```

- [ ] **Step 2: 테스트 실패 확인** — Run `cd web && npx vitest run src/lib/labelingTutorial.test.ts` · Expected: FAIL (module not found)

- [ ] **Step 3: 구현** (`labelingTutorial.ts`)

```ts
import type {
  ActionSegment, GroundTruthInput, VlmReviewInput,
} from './labelingV2';

// 답안 비교 — 서버 순수 함수(§10). aggregate pass/fail 을 만들지 않는다.
// dimension 을 matched / review / subjective 세 그룹으로만 분류한다.
export type DimensionGroup = 'matched' | 'review' | 'subjective';
export interface DimensionResult {
  key: string;
  group: DimensionGroup;
  yours: unknown;
  reference: unknown;
}
export interface TutorialComparison { dimensions: DimensionResult[] }

const SEGMENT_TOLERANCE_SEC = 1;

// exact: 스칼라 동일. set: 순서 무관 동일 집합. segment: 같은 action start/end 1초 이내.
export function compareTutorialAnswers(
  yoursGt: GroundTruthInput, yoursReview: VlmReviewInput,
  refGt: GroundTruthInput, refReview: VlmReviewInput,
): TutorialComparison {
  const dims: DimensionResult[] = [];
  const exact = (key: string, a: unknown, b: unknown) =>
    dims.push({ key, group: a === b ? 'matched' : 'review', yours: a, reference: b });
  const set = (key: string, a: readonly string[], b: readonly string[]) =>
    dims.push({ key, group: sameSet(a, b) ? 'matched' : 'review', yours: a, reference: b });
  const subjective = (key: string, a: unknown, b: unknown) =>
    dims.push({ key, group: 'subjective', yours: a, reference: b });

  exact('visibility', yoursGt.visibility, refGt.visibility);
  exact('primary_action', yoursGt.primary_action, refGt.primary_action);
  exact('target', yoursGt.target, refGt.target);
  exact('activity_intensity', yoursGt.activity_intensity, refGt.activity_intensity);
  exact('enrichment_object', yoursGt.enrichment_object, refGt.enrichment_object);
  set('observed_actions', yoursGt.observed_actions, refGt.observed_actions);
  set('interaction_types', yoursGt.interaction_types, refGt.interaction_types);
  dims.push({
    key: 'segments',
    group: segmentsMatch(yoursGt.segments, refGt.segments) ? 'matched' : 'review',
    yours: yoursGt.segments, reference: refGt.segments,
  });
  exact('vlm_verdict', yoursReview.verdict, refReview.verdict);
  set('vlm_error_tags', yoursReview.error_tags, refReview.error_tags);
  subjective('human_confidence', yoursGt.human_confidence, refGt.human_confidence);
  subjective('context_tags', yoursGt.context_tags, refGt.context_tags);
  subjective('note', yoursGt.note, refGt.note);
  return { dimensions: dims };
}

function sameSet(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const sb = new Set(b);
  return a.every((x) => sb.has(x));
}

// 각 기준 segment 에 같은 action + start/end 1초 이내 매칭이 있고, 개수도 같아야 matched.
function segmentsMatch(yours: ActionSegment[], ref: ActionSegment[]): boolean {
  if (yours.length !== ref.length) return false;
  const used = new Array(yours.length).fill(false);
  return ref.every((r) => {
    const i = yours.findIndex((y, idx) =>
      !used[idx] && y.action === r.action &&
      Math.abs(y.start_sec - r.start_sec) <= SEGMENT_TOLERANCE_SEC &&
      Math.abs(y.end_sec - r.end_sec) <= SEGMENT_TOLERANCE_SEC);
    if (i === -1) return false;
    used[i] = true;
    return true;
  });
}

// idempotency 판정용 — 키 순서 무관 deep-equal(JSON 값 한정).
export function deepEqualAnswer(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((x, i) => deepEqualAnswer(x, b[i]));
  }
  if (a && b && typeof a === 'object') {
    const ka = Object.keys(a as object).sort();
    const kb = Object.keys(b as object).sort();
    if (ka.length !== kb.length || ka.some((k, i) => k !== kb[i])) return false;
    return ka.every((k) => deepEqualAnswer((a as Record<string, unknown>)[k],
      (b as Record<string, unknown>)[k]));
  }
  return false;
}

// 클라이언트 표시용 튜토리얼 타입 (labelingApi 재-export).
export type TutorialStatus =
  | 'not_started' | 'in_progress' | 'completed' | 'waived' | 'unavailable';
export interface TutorialAccess {
  required: boolean;
  status: TutorialStatus;
  completed_lessons: number;
  total_lessons: 5;
}
export type TutorialAttemptStage =
  | 'draft' | 'gt_locked' | 'review_submitted' | 'completed';
```

- [ ] **Step 4: 테스트 통과 확인** — Run `cd web && npx vitest run src/lib/labelingTutorial.test.ts` · Expected: PASS

- [ ] **Step 5: Commit** — `git commit -m "feat: 튜토리얼 답안 비교 순수 함수 + 타입"`

---

## Phase 2 — 접근 게이트 (production 차단)

**Files:** Create `web/src/lib/labelingTutorialGate.ts`(+test); Modify `web/src/lib/labelingAccess.ts`, `web/src/lib/clipPerms.ts`

- [ ] **Step 1: `labelingTutorialGate.ts` 구현**

```ts
import 'server-only';
import { NextResponse } from 'next/server';
import { supabaseAdmin } from '@/lib/supabase';
import type { TutorialAccess } from '@/lib/labelingTutorial';

// active set + lesson 수. lessons<5 또는 active 없음이면 fail closed(§5.7).
export async function loadActiveTutorial(): Promise<
  { setId: string; version: string; title: string; lessonCount: number } | null
> {
  const { data, error } = await supabaseAdmin
    .from('labeling_tutorial_sets')
    .select('id, version, title')
    .eq('status', 'active')
    .limit(1);
  if (error || !(data ?? [])[0]) return null;
  const set = data![0];
  const { count } = await supabaseAdmin
    .from('labeling_tutorial_lessons')
    .select('id', { count: 'exact', head: true })
    .eq('tutorial_set_id', set.id);
  return { setId: set.id, version: set.version, title: set.title, lessonCount: count ?? 0 };
}

// 접근 상태 계산(§11 access 계약). owner 는 required=false(면제·preview).
export async function getTutorialAccess(
  userId: string, isOwner: boolean,
): Promise<TutorialAccess> {
  const active = await loadActiveTutorial();
  const total = 5 as const;
  if (!active || active.lessonCount < 5) {
    // fail closed: labeler 는 준비 중(차단), owner 는 required=false.
    return { required: !isOwner, status: 'unavailable', completed_lessons: 0, total_lessons: total };
  }
  const { data } = await supabaseAdmin
    .from('labeling_tutorial_progress')
    .select('current_run_no, completed_at, waived_at')
    .eq('tutorial_set_id', active.setId).eq('user_id', userId).limit(1);
  const p = (data ?? [])[0];
  const completedLessons = p
    ? await countCompleted(active.setId, userId, p.current_run_no) : 0;
  if (isOwner) {
    const status = p?.waived_at ? 'waived' : p?.completed_at ? 'completed'
      : p ? 'in_progress' : 'not_started';
    return { required: false, status, completed_lessons: completedLessons, total_lessons: total };
  }
  if (p?.waived_at) return { required: false, status: 'waived', completed_lessons: completedLessons, total_lessons: total };
  if (p?.completed_at) return { required: false, status: 'completed', completed_lessons: 5, total_lessons: total };
  if (p) return { required: true, status: 'in_progress', completed_lessons: completedLessons, total_lessons: total };
  return { required: true, status: 'not_started', completed_lessons: 0, total_lessons: total };
}

async function countCompleted(setId: string, userId: string, runNo: number): Promise<number> {
  const { count } = await supabaseAdmin
    .from('labeling_tutorial_attempts')
    .select('id', { count: 'exact', head: true })
    .eq('tutorial_set_id', setId).eq('user_id', userId)
    .eq('run_no', runNo).eq('stage', 'completed');
  return count ?? 0;
}

// production 게이트: 통과면 null, 미완료 labeler 면 403 tutorial_required(§8).
export async function tutorialGateResponse(userId: string): Promise<NextResponse | null> {
  const access = await getTutorialAccess(userId, false);
  if (!access.required) return null;
  return NextResponse.json({ detail: 'tutorial_required' }, { status: 403 });
}
```

- [ ] **Step 2: `requireProductionLabelingAccess` 추가** (`labelingAccess.ts` 하단)

```ts
import { tutorialGateResponse } from '@/lib/labelingTutorialGate';
export { getTutorialAccess } from '@/lib/labelingTutorialGate';

// 큐·일반 clip 접근용 — requireLabelingAccess + 튜토리얼 완료/면제(owner bypass, §12).
export async function requireProductionLabelingAccess(
  req: NextRequest,
): Promise<LabelingAccessResult> {
  const base = await requireLabelingAccess(req);
  if (!base.ok) return base;
  if (base.isOwner) return base;
  const blocked = await tutorialGateResponse(base.userId);
  if (blocked) return { ok: false, response: blocked };
  return base;
}
```

- [ ] **Step 3: `loadClipWithPerms` 에 게이트 삽입** (`clipPerms.ts`, owner-or-labeler 확인 직후)

```ts
// 기존:
//   if (!isOwnerId(userId) && !(await isLabeler(userId))) { ...404 }
// 아래로 교체 — labeler 는 튜토리얼 완료 전 일반 clip 접근 차단(403 tutorial_required).
const owner = isOwnerId(userId);
if (!owner && !(await isLabeler(userId))) {
  return { ok: false, response: NextResponse.json({ detail: 'not found' }, { status: 404 }) };
}
if (!owner) {
  const { tutorialGateResponse } = await import('@/lib/labelingTutorialGate');
  const blocked = await tutorialGateResponse(userId);
  if (blocked) return { ok: false, response: blocked };
}
```
> dynamic import 로 clipPerms→gate 단방향 유지(gate 는 clipPerms 를 import 하지 않음 → 순환 없음).

- [ ] **Step 4: 게이트 테스트** (`labelingTutorialGate.test.ts`) — active 없음→unavailable/required(labeler)·owner required=false, completed→required=false, in_progress→required=true. `vi.mock('@/lib/supabase')` 로 set/lesson/progress/attempt 쿼리 스텁.

- [ ] **Step 5: Run** `cd web && npx vitest run src/lib/labelingTutorialGate.test.ts` · Expected PASS

- [ ] **Step 6: Commit** — `git commit -m "feat: production 라벨링 접근 게이트(튜토리얼 완료 강제)"`

---

## Phase 3 — 튜토리얼 읽기 API + 미디어

**Files:** Create `web/src/app/api/labeling-tutorial/_helpers.ts`, `route.ts`, `lessons/[position]/route.ts`, `.../thumbnail/url/route.ts`, `.../file/url/route.ts`

- [ ] **Step 1: `_helpers.ts`** — active set·lesson·attempt 로더

```ts
import { supabaseAdmin } from '@/lib/supabase';
import { loadActiveTutorial } from '@/lib/labelingTutorialGate';

export function parsePosition(raw: string): number | null {
  const n = Number(raw);
  return Number.isInteger(n) && n >= 1 && n <= 5 ? n : null;
}

export async function loadActiveSetId(): Promise<string | null> {
  const a = await loadActiveTutorial();
  return a && a.lessonCount >= 5 ? a.setId : null;
}

export async function loadLessonByPosition(setId: string, position: number) {
  const { data } = await supabaseAdmin.from('labeling_tutorial_lessons')
    .select('*').eq('tutorial_set_id', setId).eq('position', position).limit(1);
  return (data ?? [])[0] ?? null;
}

export async function loadProgress(setId: string, userId: string) {
  const { data } = await supabaseAdmin.from('labeling_tutorial_progress')
    .select('*').eq('tutorial_set_id', setId).eq('user_id', userId).limit(1);
  return (data ?? [])[0] ?? null;
}

export async function loadAttempt(setId: string, lessonId: string, userId: string, runNo: number) {
  const { data } = await supabaseAdmin.from('labeling_tutorial_attempts')
    .select('*').eq('tutorial_set_id', setId).eq('lesson_id', lessonId)
    .eq('user_id', userId).eq('run_no', runNo).limit(1);
  return (data ?? [])[0] ?? null;
}
```

- [ ] **Step 2: `GET /api/labeling-tutorial`** — requireLabelingAccess. `getTutorialAccess` + lesson 목록(공개 metadata: position/title/learning_objective) + 각 lesson state(현재 run attempts 기반: completed→completed, review_submitted→in_progress, gt_locked→in_progress, 없음+이전 완료→available, 그 외→locked). unavailable 이면 lessons=[].

- [ ] **Step 3: `GET /api/labeling-tutorial/lessons/[position]`** — 핵심 보안 분기

```ts
// requireLabelingAccess → active set → parsePosition → loadLessonByPosition
// 순서 강제(§13): 이전 position 미완료면 409 { detail, current_position }.
// attempt 로드. 응답 조립:
const attempt = await loadAttempt(setId, lesson.id, userId, runNo);
const stage = attempt?.stage ?? 'draft';
const body: Record<string, unknown> = {
  position, title: lesson.title, learning_objective: lesson.learning_objective,
  pre_submit_tip: lesson.pre_submit_tip,
  clip: { id: lesson.clip_id, duration_sec: clip.duration_sec, started_at: clip.started_at },
  attempt: attempt ? {
    stage, submitted_gt: attempt.submitted_gt,
    submitted_vlm_review: attempt.submitted_vlm_review,
  } : null,
};
// GT 잠금 후에만 고정 VLM 공개
if (stage === 'gt_locked' || stage === 'review_submitted' || stage === 'completed') {
  body.prediction_snapshot = lesson.prediction_snapshot;
}
// review 제출 후에만 reference/comparison/feedback — 그 전엔 key 자체를 넣지 않는다(§13).
if (stage === 'review_submitted' || stage === 'completed') {
  body.reference = { gt: lesson.reference_gt, vlm_review: lesson.reference_vlm_review };
  body.comparison = attempt!.comparison;
  body.feedback = lesson.feedback_content;
}
return NextResponse.json(body);
```
> clip 은 `camera_clips` 에서 duration/started_at 만 select(민감 필드 최소). reference_* 는 위 분기 밖에서 절대 참조하지 않음.

- [ ] **Step 4: 미디어 라우트 2개** — `thumbnail/url`, `file/url`

```ts
// requireLabelingAccess(owner or labeler; owner preview 가능) → active set →
// parsePosition(범위 밖 404) → loadLessonByPosition(없으면 404) →
// camera_clips 에서 r2_key/thumbnail_r2_key 조회 → presignGet.
// 요청 lesson 의 clip 만 서명한다. 일반 clip UUID 입력 경로가 없어 우회 불가(§12).
```
file/url: `presignGet(clip.r2_key, SIGNED_URL_TTL_SEC)` → `{url, ttl_sec, type:'r2'}`.
thumbnail/url: `presignGet(thumbnailKeyForClip(clip), SIGNED_URL_TTL_SEC)`.

- [ ] **Step 5: Run** `cd web && npm test` (회귀 없음 확인) + `next build` 타입체크. **Commit** — `git commit -m "feat: 튜토리얼 읽기 API + lesson 미디어(정답 미노출 분기)"`

---

## Phase 4 — 튜토리얼 쓰기 API (idempotency·불변)

**Files:** Create `.../gt/route.ts`(+test), `.../vlm-review/route.ts`(+test), `.../acknowledge/route.ts`

- [ ] **Step 1: gt route 실패 테스트** (`gt/route.test.ts`) — ① 최초 제출→prediction_snapshot 반환·reference 미포함 ② 같은 payload 재전송→200 동일 ③ 다른 payload→409 ④ 이전 lesson 미완료→409.

- [ ] **Step 2: `POST .../gt`** 구현

```ts
// requireLabelingAccess → active set → position/lesson → clip.duration_sec →
// validateGroundTruth(body, duration). progress upsert(run_no 확보):
//   loadProgress || insert {current_run_no:1, started_at}. runNo = progress.current_run_no.
// 순서 강제: position>1 이면 이전 position attempt.stage='completed' 필요, 아니면 409.
// attempt = loadAttempt(...).
const now = new Date().toISOString();
if (attempt?.submitted_gt) {
  if (!deepEqualAnswer(attempt.submitted_gt, gt)) {
    return NextResponse.json({ detail: 'gt_already_submitted' }, { status: 409 });
  }
  return NextResponse.json({ prediction_snapshot: lesson.prediction_snapshot }); // idempotent
}
const payload = {
  tutorial_set_id: setId, lesson_id: lesson.id, user_id: userId, run_no: runNo,
  stage: 'gt_locked', submitted_gt: gt, gt_locked_at: now, updated_at: now,
};
// attempt 없으면 insert, draft 행 있으면 update. behavior_labels/clip_labeling_sessions 미기록.
return NextResponse.json({ prediction_snapshot: lesson.prediction_snapshot });
```

- [ ] **Step 3: Run** gt 테스트 PASS.

- [ ] **Step 4: vlm-review 실패 테스트** — ① GT 전 호출→409 ② 최초 제출→reference+comparison+feedback 반환 ③ 재전송 동일→200 ④ 다른 payload→409.

- [ ] **Step 5: `POST .../vlm-review`** 구현

```ts
// requireLabelingAccess → set/position/lesson → validateVlmReview(body) → attempt.
if (!attempt?.submitted_gt) return 409 '먼저 GT 잠금'.
if (attempt.submitted_vlm_review) {
  if (!deepEqualAnswer(attempt.submitted_vlm_review, review)) return 409 'review_already_submitted';
  return NextResponse.json(revealPayload(lesson, attempt.comparison)); // idempotent
}
const comparison = compareTutorialAnswers(
  attempt.submitted_gt, review, lesson.reference_gt, lesson.reference_vlm_review);
// update: stage='review_submitted', submitted_vlm_review=review, comparison, review_submitted_at.
return NextResponse.json({
  reference: { gt: lesson.reference_gt, vlm_review: lesson.reference_vlm_review },
  comparison, feedback: lesson.feedback_content,
});
```

- [ ] **Step 6: `POST .../acknowledge`** — attempt 로드 → `fn_acknowledge_tutorial_lesson` RPC. 이미 completed면 동일 반환(idempotent). `{ tutorial_completed }` 반환.

- [ ] **Step 7: Run** vlm-review 테스트 PASS + `npm test`. **Commit** — `git commit -m "feat: 튜토리얼 GT/VLM/acknowledge 쓰기 API(idempotency·불변)"`

---

## Phase 5 — owner API (진행·reset·waive)

**Files:** Create `team-progress/route.ts`, `users/[userId]/reset/route.ts`, `users/[userId]/waive/route.ts`

- [ ] **Step 1: `GET .../team-progress`** — requireOwner. active set → 각 labeler(`labelers` join `labeler_applications` for name) progress + 현재 run lesson별 mismatch dimension 수(comparison.dimensions 중 group='review' count). `{ items: [{user_id, display_name, status, completed_lessons, lessons:[{position, mismatch_count}]}] }`.
- [ ] **Step 2: `POST .../users/[userId]/reset`** — requireOwner → `fn_reset_tutorial(setId, userId, ownerId)`.
- [ ] **Step 3: `POST .../users/[userId]/waive`** — requireOwner → body `{reason}` 1..200 검증 → `fn_waive_tutorial`.
- [ ] **Step 4: Commit** — `git commit -m "feat: 튜토리얼 owner 진행·다시 시작·완료 면제 API"`

---

## Phase 6 — access API 확장 + 큐 게이트 교체

**Files:** Modify `web/src/app/api/labeling-access/route.ts`, `web/src/app/api/labeling-v2/queue/route.ts`

- [ ] **Step 1: access 응답에 tutorial 추가**

```ts
// getLabelingAccess 후:
const isOwner = access.status === 'owner';
const tutorial = await getTutorialAccess(user.id, isOwner);
return NextResponse.json({ ...access, tutorial });
```
> `access='labeler'` 의미는 멤버십으로 유지, tutorial 은 별도 축(§11).

- [ ] **Step 2: 큐 게이트 교체** — `requireLabelingAccess` → `requireProductionLabelingAccess` (import 변경 1줄 + 호출 1줄).
- [ ] **Step 3: Run** `npm test`. **Commit** — `git commit -m "feat: labeling-access 에 tutorial 상태 + 큐 production 게이트"`

---

## Phase 7 — 클라이언트 API

**Files:** Modify `web/src/lib/labelingApi.ts`

- [ ] **Step 1: 타입 + 함수 추가**

```ts
import type { TutorialAccess, TutorialComparison, TutorialAttemptStage } from './labelingTutorial';
// LabelingAccessInfo 에 추가:
//   tutorial?: TutorialAccess;
export interface TutorialLessonMeta { position: number; title: string;
  learning_objective: string; state: 'locked'|'available'|'in_progress'|'completed'; }
export interface TutorialOverview {
  tutorial: TutorialAccess; set: { version: string; title: string } | null;
  lessons: TutorialLessonMeta[]; current_run_no: number;
}
export interface TutorialLessonView {
  position: number; title: string; learning_objective: string; pre_submit_tip: string | null;
  clip: { id: string; duration_sec: number | null; started_at: string };
  attempt: { stage: TutorialAttemptStage; submitted_gt: GroundTruthInput | null;
    submitted_vlm_review: VlmReviewInput | null } | null;
  prediction_snapshot?: Record<string, unknown>;
  reference?: { gt: GroundTruthInput; vlm_review: VlmReviewInput };
  comparison?: TutorialComparison;
  feedback?: Record<string, { why?: string; next?: string }>;
}
export const getTutorialOverview = () => request<TutorialOverview>('/api/labeling-tutorial');
export const getTutorialLesson = (p: number) =>
  request<TutorialLessonView>(`/api/labeling-tutorial/lessons/${p}`);
export const saveTutorialGt = (p: number, gt: GroundTruthInput) =>
  request<{ prediction_snapshot: Record<string, unknown> }>(
    `/api/labeling-tutorial/lessons/${p}/gt`, { method:'POST', body: JSON.stringify(gt) });
export const saveTutorialVlmReview = (p: number, r: VlmReviewInput) =>
  request<{ reference: TutorialLessonView['reference']; comparison: TutorialComparison;
    feedback: TutorialLessonView['feedback'] }>(
    `/api/labeling-tutorial/lessons/${p}/vlm-review`, { method:'POST', body: JSON.stringify(r) });
export const acknowledgeTutorialLesson = (p: number) =>
  request<{ tutorial_completed: boolean }>(
    `/api/labeling-tutorial/lessons/${p}/acknowledge`, { method:'POST', body: '{}' });
export const getTutorialFileUrl = (p: number) =>
  request<PlaybackUrl>(`/api/labeling-tutorial/lessons/${p}/file/url`).then(resolveLocalUrl);
// team-progress / reset / waive 도 동일 패턴.
```

- [ ] **Step 2: Run** `next build` 타입체크. **Commit** — `git commit -m "feat: 튜토리얼 클라이언트 API + 타입"`

---

## Phase 8 — 공유 UI 컴포넌트 추출 (production 동작 불변)

**Files:** Create `web/src/app/labeling/_labeling-forms.tsx`; Modify `web/src/app/labeling/[clipId]/page.tsx`

- [ ] **Step 1: `_labeling-forms.tsx` 로 이동** — `[clipId]/page.tsx` 의 label maps(ACTION/OBSERVED/TARGET/CONTEXT/INTERACTION/ERROR_LABELS) + `emptyGt` + `Choice/ChoiceRow/SelectField/SegmentRow` + `GroundTruthForm/VlmReviewCard/GtSummary/MetadataCard` 를 그대로 export. 추가로 `VideoPlayer`(video ref + −1/+1 frame + 속도 select 를 감싼 컴포넌트) 분리.
- [ ] **Step 2: `[clipId]/page.tsx` 에서 import 로 교체** — 로컬 정의 삭제, `_labeling-forms` 에서 import. 페이지 동작/JSX 결과 동일.
- [ ] **Step 3: Run** `cd web && npm test && npx next build` — 타입·빌드 통과(동작 회귀 없음). 수동 스모크: production `/labeling/[clipId]` GT 폼·VLM 카드 렌더 동일.
- [ ] **Step 4: Commit** — `git commit -m "refactor: 라벨링 GT/VLM 폼·플레이어를 공유 컴포넌트로 추출"`

---

## Phase 9 — 튜토리얼 UI (요약 + lesson 상태 머신)

**Files:** Create `web/src/app/labeling/tutorial/page.tsx`, `web/src/app/labeling/tutorial/[position]/page.tsx`, `web/src/app/labeling/tutorial/_tutorial-feedback.tsx`

- [ ] **Step 1: `_tutorial-feedback.tsx`** — comparison.dimensions 를 `일치`/`다시 보기`/`개인차 가능`(matched/review/subjective) 3그룹으로 렌더. 각 review dimension 에 `네 답`·`기준`·feedback[key].why(`왜`)·feedback[key].next(`다음 영상에서`). 숫자 총점·`불합격` 미표시(§10, §8).

- [ ] **Step 2: `tutorial/page.tsx` (요약)** — `getTutorialOverview`.
  - `tutorial.status==='unavailable'` → `튜토리얼 준비 중 · 관리자에게 문의`.
  - 아니면 목적·예상 15~25분·`점수 합격선 없음` 안내 + 5개 lesson 카드(state별 잠금/진행/완료) + `시작`/`계속하기`(첫 미완료 position 으로) .
  - `status==='completed'|'waived'` → `해설 다시 보기` + `라벨 대기 큐로 이동`.

- [ ] **Step 3: `tutorial/[position]/page.tsx` (상태 머신)** — 기존 상세 페이지 구조 미러, 튜토리얼 API 사용.

```
[상태 분기] attempt.stage 기준:
- draft:            VideoPlayer + GroundTruthForm(onSave=saveTutorialGt) → 성공 시 prediction 세팅·stage=gt_locked
- gt_locked:        GtSummary + VlmReviewCard(onComplete=saveTutorialVlmReview) → 성공 시 reference/comparison/feedback 세팅·stage=review_submitted
- review_submitted: TutorialFeedback + `해설 확인하고 다음`(acknowledgeTutorialLesson) → 다음 position or 완료
- completed:        읽기전용 요약 + `다음`(다음 미완료 position)/마지막이면 완료 화면
상단: `N/5`, 교육 목표, 진행 bar. 제출 전 tip = pre_submit_tip(이 영상 답 미노출).
```
> reference/feedback 은 서버가 review 제출 후에만 내려주므로, 클라이언트는 그 전에는 표시할 데이터 자체가 없다(2중 안전).

- [ ] **Step 4: 완료 화면** — 5개째 acknowledge 의 `tutorial_completed` true → `튜토리얼 완료 · 이제 날짜별 본작업을 시작할 수 있어` + lesson별 핵심 교정 요약 + `라벨 대기 큐로 이동`(access refresh 후 `/labeling`).

- [ ] **Step 5: Run** `npx next build`. **Commit** — `git commit -m "feat: 튜토리얼 요약·lesson 상태 머신·피드백 UI"`

---

## Phase 10 — 내비게이션 게이트 + owner 팀 진행

**Files:** Modify `web/src/app/labeling/layout.tsx`, `web/src/app/labeling/team/page.tsx`

- [ ] **Step 1: layout categorize + redirect**

```ts
// categorize: pathname.startsWith('/labeling/tutorial') → 'tutorial'
// RouteCategory 에 'tutorial' 추가.
// redirectTarget(labeler):
//   cat==='work' && access.tutorial?.required → '/labeling/tutorial'
//   cat==='tutorial' → null (labeler·owner 항상 허용)
//   그 외 기존 로직.
// owner: cat==='tutorial'|'work'|'owner' → null.
```
> `redirectTarget` 시그니처에 `tutorial: TutorialAccess | undefined` 인자 추가, 호출부에서 `access?.tutorial` 전달.

- [ ] **Step 2: 내비 badge** — labeler 에게 `튜토리얼` 링크. `tutorial.required` 면 강조 badge `필수 · {completed_lessons}/5`, 아니면 `튜토리얼`. owner 는 `튜토리얼(미리보기)`.

- [ ] **Step 3: team/page.tsx 튜토리얼 진행 섹션** — `getTutorialTeamProgress`. 팀원별 `튜토리얼 0/5`·`진행 중 3/5`·`완료`·`면제` + lesson별 mismatch dimension. owner action `다시 시작`(reset)·`완료 면제`(waive, 사유 prompt 1~200자).

- [ ] **Step 4: Run** `npx next build`. **Commit** — `git commit -m "feat: 튜토리얼 내비 게이트 + owner 팀 진행 관리"`

---

## Phase 11 — 문서·SOT + 검증

**Files:** Modify `docs/DATABASE.md`, `docs/FEATURES.md`, `specs/next-session.md`, 설계 문서 상태 헤더

- [ ] **Step 1: DATABASE.md** — 4 테이블 스키마·RLS·RPC 기록.
- [ ] **Step 2: FEATURES.md** — 튜토리얼 기능·게이트·provenance 분리 기록.
- [ ] **Step 3: next-session.md** — 배포 순서(§17: DB→preview→owner 5개 seed→active→테스트 라벨러 E2E→prod) + 미완 항목.
- [ ] **Step 4: 전체 검증** — `cd web && npm test && npx next build` 통과. 설계 §15 unit/API 체크리스트 대조.
- [ ] **Step 5: Commit** — `git commit -m "docs: 튜토리얼 DB/기능/배포 SOT 갱신"`

---

## 결정 사항 (설계 해석)

1. **draft 서버 미저장** — production 과 동일하게 GT 는 잠금 전 서버 저장 안 함. `attempt` 는 gt_locked 부터 생성, `draft` 이탈 복구는 client localStorage(§6.3 "저장된 draft 가 있다면"). enum 의 draft 는 보존하되 API 가 draft 행을 만들지 않음.
2. **게이트 위치** — `loadClipWithPerms`(clips/* 6 + labeling-v2/[clipId] 3 + router-review) + queue(`requireProductionLabelingAccess`)에 삽입. owner 전면 bypass. router-review 도 미완료 labeler 차단(§ 취지 일관, 무해).
3. **seed** — 실 clip UUID·문구는 커밋하지 않음(§14, §18). `fn_seed_tutorial_lesson_from_owner` RPC 만 제공, owner 가 실값으로 실행.
4. **비교 feedback** — comparison(matched/review/subjective 분류)은 서버 계산·불변 저장, `왜`/`다음 영상에서` 문구는 lesson.feedback_content 에서 병합.

## Self-Review (스펙 대조)

- §5 운영정책 8개 → Phase 2/4/5/9/10 (fail closed=Phase2 unavailable, 면제=Phase5 waive, 다시 시작 run+1=Phase0 fn_reset).
- §8 라우팅 3화면 → Phase 3/9/10. 직접 URL 403 tutorial_required → Phase2.
- §9 테이블 4개·불변·RLS → Phase0. behavior_labels 미기록 → Phase4.
- §10 exact/set/segment(1초)/subjective → Phase1. aggregate 없음 → 테스트로 고정.
- §11 API 전부 → Phase3/4/5/6. idempotency 재전송/409 → Phase4 테스트.
- §12 보안: reference 조기 미노출(Phase3 분기·테스트) · service_role 전용(Phase0) · lesson clip 만(Phase3 미디어).
- §13 예외: 순서 건너뛰기 409(Phase3/4) · reference key 생략(Phase3) · acknowledge 재호출(Phase4).
- §15 검증: unit/API 는 Phase1/2/4 테스트, E2E 는 배포 후 수동(Phase11 체크리스트).
- §18 파일 경계 → 파일 구조 준수, 거대 페이지 복제 대신 `_labeling-forms` 추출(Phase8).
- placeholder 스캔: 비교/게이트/마이그레이션/idempotency 실제 코드 포함. UI(Phase9/10)는 기존 상세 페이지 패턴 미러 + 상태 머신 명시.
- 타입 일관성: `TutorialAccess`(labelingTutorial.ts 정의)를 gate/api/client 가 공유. `TutorialComparison.dimensions[].group ∈ matched|review|subjective` 일관.
