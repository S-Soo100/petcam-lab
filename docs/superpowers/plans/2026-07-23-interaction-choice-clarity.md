# 놀이 상호작용 선택지 직관화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 라벨러가 쳇바퀴 상호작용 여섯 항목의 차이와 복수 선택 규칙을 별도 질문 없이 이해하고, 저장 전에 자신의 선택을 자연어로 확인하게 한다.

**Architecture:** 기존 저장값과 과거 피드백 문구는 유지하고 `labelingDisplay.ts`에 입력 화면 전용 복사·그룹·요약 순수 계약을 추가한다. 공용 `GroundTruthForm`은 이 계약을 소비해 칩 대신 설명 내장 선택 카드를 렌더하므로 legacy v2·motion v3·튜토리얼·보정 화면이 같은 UX를 공유한다.

**Tech Stack:** Next.js 14 App Router, React, TypeScript, Tailwind CSS, Vitest, pytest

## Global Constraints

- `InteractionType` enum, API payload, RPC, migration, DB와 기존 GT를 변경하지 않는다.
- 기존 `INTERACTION_LABELS`와 `formatDimensionValue()` 출력은 유지한다. 이번 문구는 입력 화면 전용이다.
- `GroundTruthForm`의 `interaction_types` 배열 toggle 의미와 선택 순서는 바꾸지 않는다.
- wheel에서만 `ride / push / rotate`를 우선 그룹으로 분리한다. 다른 사물은 여섯 항목을 한 목록으로 보여준다.
- 모바일 1열, `sm` 이상 2열, 카드 전체 버튼, `aria-pressed`, 텍스트 제목·설명을 제공한다.
- 새 UI 테스트 라이브러리나 패키지를 추가하지 않는다. 순수 표시 계약을 Vitest로 고정하고 컴포넌트는 해당 계약만 소비한다.
- VLM·Python Evidence·selector·behavior/activity·튜토리얼 데이터·production DB를 건드리지 않는다.
- TDD RED→GREEN, task별 conventional commit, force push·파괴적 git 금지.
- main merge·production deploy는 owner/Codex의 diff 및 preview 검수 전까지 금지한다.

---

### Task 1: 입력 화면 전용 표시 계약을 순수 함수로 고정

**Files:**
- Modify: `web/src/lib/labelingDisplay.ts`
- Modify: `web/src/lib/labelingDisplay.test.ts`

**Interfaces:**
- Produces: `InteractionChoiceCopy`
- Produces: `interactionChoiceCopy(type, enrichmentObject)`
- Produces: `interactionChoiceGroups(enrichmentObject)`
- Produces: `interactionSelectionSummary(enrichmentObject, selected)`

- [ ] **Step 1: 제목·설명 RED 테스트 작성**

여섯 enum의 입력 화면 제목과 설명을 표로 고정한다. `wheel` 문맥에서는 `물체`가 `쳇바퀴`로 바뀌어야 한다.

```ts
expect(interactionChoiceCopy('ride', 'wheel')).toEqual({
  title: '위·안에 올라감',
  description: '몸이나 발을 쳇바퀴 위 또는 안에 올렸어요.',
});
expect(interactionChoiceCopy('push', 'wheel')).toEqual({
  title: '밖에서 밀거나 건드림',
  description: '올라타지 않고 발·머리·몸으로 쳇바퀴를 밀었어요.',
});
expect(interactionChoiceCopy('rotate', 'wheel')).toEqual({
  title: '쳇바퀴를 실제로 돌림',
  description: '게코의 움직임 때문에 쳇바퀴가 회전했어요.',
});
```

나머지도 정확히 고정한다.

```text
chase          움직이는 물체를 따라감 / 돌아가거나 움직이는 물체를 쫓아갔어요.
repeated_return 떠났다가 다시 찾아옴 / 다른 곳에 갔다가 같은 물체로 여러 번 돌아왔어요.
other          다른 방식으로 상호작용함 / 위 설명에는 없지만 물체를 분명히 사용했어요.
```

- [ ] **Step 2: 그룹·요약 RED 테스트 작성**

```ts
expect(interactionChoiceGroups('wheel')).toEqual({
  primary: ['ride', 'push', 'rotate'],
  secondary: ['chase', 'repeated_return', 'other'],
});
expect(interactionChoiceGroups('toy')).toEqual({
  primary: ['ride', 'push', 'rotate', 'chase', 'repeated_return', 'other'],
  secondary: [],
});
expect(interactionSelectionSummary('wheel', ['ride', 'rotate'])).toBe(
  '선택한 내용: 쳇바퀴 위·안에 올라감 · 쳇바퀴를 실제로 돌림',
);
expect(interactionSelectionSummary('wheel', [])).toBeNull();
```

선택 요약은 전달된 배열 순서를 보존한다. 임의 정렬하지 않는다.

- [ ] **Step 3: RED 확인**

Run from `web/`:

```bash
npx vitest run src/lib/labelingDisplay.test.ts
```

Expected: 신규 export가 없어 FAIL.

- [ ] **Step 4: 최소 구현**

기존 `INTERACTION_LABELS`는 그대로 두고 아래 입력용 계약을 별도로 추가한다.

```ts
export interface InteractionChoiceCopy {
  title: string;
  description: string;
}

const INTERACTION_CHOICE_COPY: Record<InteractionType, InteractionChoiceCopy> = {
  ride: {
    title: '위·안에 올라감',
    description: '몸이나 발을 물체 위 또는 안에 올렸어요.',
  },
  push: {
    title: '밖에서 밀거나 건드림',
    description: '올라타지 않고 발·머리·몸으로 물체를 밀었어요.',
  },
  rotate: {
    title: '물체를 실제로 돌림',
    description: '게코의 움직임 때문에 물체가 회전했어요.',
  },
  chase: {
    title: '움직이는 물체를 따라감',
    description: '돌아가거나 움직이는 물체를 쫓아갔어요.',
  },
  repeated_return: {
    title: '떠났다가 다시 찾아옴',
    description: '다른 곳에 갔다가 같은 물체로 여러 번 돌아왔어요.',
  },
  other: {
    title: '다른 방식으로 상호작용함',
    description: '위 설명에는 없지만 물체를 분명히 사용했어요.',
  },
};

const WHEEL_PRIMARY_INTERACTIONS: readonly InteractionType[] = [
  'ride', 'push', 'rotate',
];
const WHEEL_SECONDARY_INTERACTIONS: readonly InteractionType[] = [
  'chase', 'repeated_return', 'other',
];
```

`interactionChoiceCopy()`는 `wheel`일 때 제목·설명의 `물체`를 `쳇바퀴`로 치환한 새 객체를 반환한다. `interactionChoiceGroups()`는 배열 원본을 외부에서 바꾸지 못하도록 새 배열을 반환한다. `interactionSelectionSummary()`는 각 선택의 문맥 제목을 이어 붙인다.

- [ ] **Step 5: 기존 피드백 출력 불변 회귀 추가**

```ts
expect(INTERACTION_LABELS.ride).toBe('올라타기');
expect(formatDimensionValue('interaction_types', ['ride', 'rotate']))
  .toBe('올라타기, 회전시키기');
```

- [ ] **Step 6: GREEN 확인 후 커밋**

```bash
npx vitest run src/lib/labelingDisplay.test.ts
cd ..
git add web/src/lib/labelingDisplay.ts web/src/lib/labelingDisplay.test.ts
git commit -m "feat: 놀이 상호작용 표시 기준 추가"
```

### Task 2: 설명 내장 선택 카드와 선택 요약 적용

**Files:**
- Modify: `web/src/app/labeling/_labeling-forms.tsx`
- Modify: `web/src/lib/labelingDisplay.test.ts` only if a missing pure view contract is found

**Consumes:**
- `interactionChoiceCopy()`
- `interactionChoiceGroups()`
- `interactionSelectionSummary()`

- [ ] **Step 1: 구현 전 사용자 체험을 주석으로 대조**

코드 작성 전에 설계 §4의 흐름을 폼 구조에 대조한다.

```text
[화면] 쳇바퀴 선택 → [반응] 쳇바퀴 질문·복수 선택 안내
[조작] 설명 카드 복수 선택 → [반응] 체크 상태·자연어 선택 요약
[조작] 희소 행동 확인 → [반응] 별도 보조 그룹에서 선택
```

이 흐름과 다른 자동 선택·자동 저장·자동 이동을 추가하지 않는다.

- [ ] **Step 2: 폼이 소비할 view contract RED 보강**

Task 1 테스트만으로 다음 세 조건이 완전히 고정됐는지 확인한다.

1. wheel 제목·설명이 `쳇바퀴` 문맥이다.
2. wheel primary/secondary 순서가 고정된다.
3. 비-wheel은 secondary 없이 여섯 항목을 보여준다.

빠진 조건이 있으면 `labelingDisplay.test.ts`에 실패 테스트를 먼저 추가하고 RED를 확인한다. 새 React 테스트 의존성은 추가하지 않는다.

- [ ] **Step 3: 카드 컴포넌트 추가**

`_labeling-forms.tsx` 내부 presentational helper로 추가한다.

```tsx
function InteractionChoiceCard({
  active,
  title,
  description,
  onClick,
}: {
  active: boolean;
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={active
        ? 'w-full rounded-xl border border-violet-500 bg-violet-100 p-3 text-left ring-2 ring-violet-200'
        : 'w-full rounded-xl border border-violet-200 bg-white p-3 text-left hover:border-violet-400'}
    >
      <span className="flex items-center gap-2 text-sm font-semibold text-violet-950">
        <span aria-hidden="true">{active ? '✓' : '○'}</span>
        {title}
      </span>
      <span className="mt-1 block text-xs leading-5 text-violet-700">
        {description}
      </span>
    </button>
  );
}
```

색상·간격은 기존 violet section과 조화되게 최소 조정할 수 있지만, 카드 전체 버튼·`aria-pressed`·제목·설명·선택 체크 계약은 유지한다.

- [ ] **Step 4: interaction section 교체**

- wheel 제목: `쳇바퀴에서 실제로 본 행동은?`
- 그 외 제목: `이 물체를 어떻게 사용했나?`
- 공통 도움말: `여러 개 선택할 수 있어. 실제로 확인한 행동을 모두 골라줘.`
- wheel primary 앞에 `자주 확인하는 행동`을 표시한다.
- secondary가 있을 때만 `그 밖에 함께 본 행동`을 표시한다.
- 각 그룹은 `grid grid-cols-1 gap-2 sm:grid-cols-2`를 사용한다.
- 선택이 있으면 violet 계열의 읽기 전용 요약 박스에 `interactionSelectionSummary()`를 표시한다.
- 기존 `FieldError(interaction_types)`는 카드·요약 아래에 유지한다.

toggle 구현은 아래 의미를 그대로 유지한다.

```ts
gt.interaction_types.includes(type)
  ? gt.interaction_types.filter((value) => value !== type)
  : [...gt.interaction_types, type]
```

- [ ] **Step 5: focused GREEN 확인**

```bash
npx vitest run src/lib/labelingDisplay.test.ts
npx tsc --noEmit
cd ..
```

- [ ] **Step 6: 정적 범위 감사 후 커밋**

```bash
rg -n "interaction_types|INTERACTION_LABELS|InteractionChoiceCard" \
  src/app/labeling/_labeling-forms.tsx src/lib/labelingDisplay.ts
git diff --check
git add web/src/app/labeling/_labeling-forms.tsx web/src/lib/labelingDisplay.test.ts
git commit -m "feat: 놀이 상호작용 설명 카드 적용"
```

`labelingDisplay.test.ts`가 Task 2에서 바뀌지 않았다면 add 목록에서 제외한다.

### Task 3: 전체 회귀·문서·preview 전달

**Files:**
- Modify: `docs/FEATURES.md`
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`
- Create: `docs/handoff-prompts/2026-07-23-interaction-choice-clarity-report.md`

- [ ] **Step 1: 전체 자동 검증**

```bash
cd /Users/baek/petcam-lab/.worktrees/interaction-help-ui/web
npm test -- --run
npx tsc --noEmit
npm run build

cd /Users/baek/petcam-lab/.worktrees/interaction-help-ui
uv run pytest -q
git diff --check
```

`npm run build`가 세션 안전 훅으로 차단되면 실패를 숨기지 않는다. `tsc`를 build 성공으로 대체 주장하지 말고, owner/Codex 터미널 실행 명령과 미검증 상태를 보고서에 남긴다.

- [ ] **Step 2: 저장 계약 불변 정적 감사**

```bash
git diff --name-only 7da1510a6555148694877e320bfc0717fc20ef5c..HEAD
git diff 7da1510a6555148694877e320bfc0717fc20ef5c..HEAD -- \
  web/src/lib/labelingV2.ts web/src/app/api migrations
```

두 번째 명령은 출력 0이어야 한다. migration·API·enum 변경이 보이면 구현을 완료 처리하지 말고 범위 밖 변경을 분리해 보고한다.

- [ ] **Step 3: 문서와 감사 기록 갱신**

- `docs/FEATURES.md`: 공용 GT 폼의 놀이 상호작용 카드·복수 선택·선택 요약을 한 단락으로 기록한다.
- `specs/next-session.md`: branch·검증 결과·미배포 상태를 상단 최신 블록에 additive 기록한다.
- `.claude/donts-audit.md`: 내부 enum을 짧은 단어로 그대로 노출하면 라벨러 기준이 사라진다는 교훈을 한 줄 추가한다.
- 과거 history를 삭제하거나 재작성하지 않는다.

- [ ] **Step 4: 구현 보고서 작성**

보고서는 다음을 반드시 포함한다.

1. `HANDOFF_OK` 전문
2. 변경 파일과 화면 전/후
3. enum/API/DB 불변 증거
4. RED→GREEN 테스트와 전체 검증 수치
5. 공유 화면 영향 범위(legacy v2·motion v3·튜토리얼·보정)
6. 미검증 항목과 정확한 owner preview 절차
7. 최종 commit SHA·push·working tree 상태

- [ ] **Step 5: 문서 커밋·feature branch push**

```bash
git add docs/FEATURES.md specs/next-session.md .claude/donts-audit.md \
  docs/handoff-prompts/2026-07-23-interaction-choice-clarity-report.md
git commit -m "docs: 놀이 상호작용 UX 검증 기록"
git push origin codex/interaction-help-ui
```

- [ ] **Step 6: Stop Point**

여기서 정지한다. 다음은 이번 구현에서 하지 않는다.

- main FF/merge
- Vercel production 배포
- production DB write
- 저장 enum·API·migration 변경
- 영상 예시·새 패키지·자동 판정 추가

owner/Codex가 diff와 preview에서 다음을 확인한 뒤 별도 승인한다.

```text
wheel 선택 → 질문·복수 안내
ride만 선택 → 위·안에 올라감 요약
push+rotate 선택 → 두 카드와 두 요약 모두 유지
secondary 선택 → 드문 행동 그룹에서 정상 토글
모바일 폭 → 1열, sm 이상 → 2열
저장 payload → 기존 enum 배열과 동일
```

최종 준비 판정명은 `INTERACTION_CHOICE_CLARITY_READY_FOR_DEPLOY_REVIEW`다.
