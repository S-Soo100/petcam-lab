# Owner Conflict Value Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Owner 불일치 검수 화면에 서로 다른 각 항목의 라벨러 A/B 실제 값을 한국어로 직접 표시한다.

**Architecture:** 기존 owner detail API가 이미 반환하는 두 `initial_gt`와 `differing_fields`를
표시 계층에서만 조합한다. 순수 formatter가 비교 행을 만들고, 전용 React 컴포넌트가 모바일
안전한 2열 카드로 렌더링한다. API·DB·판정 mutation은 불변이다.

**Tech Stack:** Next.js 14, React, TypeScript, Vitest, Tailwind CSS

## Global Constraints

- API·DB·consensus·resolve payload는 변경하지 않는다.
- 내부 enum 또는 알 수 없는 필드명을 화면에 노출하지 않는다.
- 320px에서 가로 스크롤 없이 A/B 대응 관계를 유지한다.
- 테스트를 먼저 실패시킨 뒤 최소 구현한다.

---

### Task 1: A/B 실제 값 formatter

**Files:**
- Modify: `web/src/app/labeling/_blind-review-view.ts`
- Test: `web/src/app/labeling/_blind-review-ui.test.tsx`

**Interfaces:**
- Consumes: `OwnerSubmissionView`, `formatDimensionValue`, `BLIND_DECISION_COPY`
- Produces: `ownerDifferenceRows(fields, submissionA, submissionB, durationSec)`

- [ ] **Step 1: Write the failing formatter tests**

`target`, 빈/복수 `context_tags`, `highlight_recommendation`, `segments`, 알 수 없는 필드가
각각 한국어 실제 값 또는 `확인 필요`로 변환되는 기대값을 추가한다.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `cd web && npm test -- --run src/app/labeling/_blind-review-ui.test.tsx`

Expected: `ownerDifferenceRows is not exported` 또는 실제 값 비교 assertion 실패.

- [ ] **Step 3: Implement the minimal pure formatter**

허용된 field label map과 기존 `formatDimensionValue`를 사용해
`{ key, label, aValue, bValue }[]`를 반환한다. 촬영 환경 빈 배열만 `해당 없음`으로 표시한다.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `cd web && npm test -- --run src/app/labeling/_blind-review-ui.test.tsx`

Expected: all tests pass.

### Task 2: 반응형 실제 값 비교 UI

**Files:**
- Create: `web/src/app/labeling/_owner-conflict-comparison.tsx`
- Create: `web/src/app/labeling/_owner-conflict-comparison.test.tsx`
- Modify: `web/src/app/labeling/blind/conflicts/[clipId]/page.tsx`

**Interfaces:**
- Consumes: `ownerDifferenceRows`, 두 `OwnerSubmissionView`, clip duration
- Produces: `<OwnerConflictComparison />`

- [ ] **Step 1: Write the failing SSR component test**

`행동 대상`, `유리/벽`, `일반 사물`, `촬영 환경`, `해당 없음`, `야간 IR`,
`하이라이트 여부`, `제외`, `포함`이 모두 렌더되고 raw enum은 보이지 않는지 단언한다.

- [ ] **Step 2: Run the component test and verify RED**

Run: `cd web && npm test -- --run src/app/labeling/_owner-conflict-comparison.test.tsx`

Expected: module/component missing.

- [ ] **Step 3: Implement and connect the component**

각 비교 행을 `min-w-0`, `break-words`, 2열 grid로 만들고 A/B를 같은 시각적 비중으로
표시한다. 상세 페이지의 항목명 전용 배너를 이 컴포넌트로 교체한다.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:
`cd web && npm test -- --run src/app/labeling/_owner-conflict-comparison.test.tsx src/app/labeling/_blind-review-ui.test.tsx`

Expected: all tests pass.

### Task 3: 회귀·빌드·배포 검증

**Files:**
- Modify: `.claude/donts-audit.md`

- [ ] **Step 1: Run full verification**

Run:

```bash
cd web && npm test
cd web && npx tsc --noEmit
uv run pytest -q
git diff --check
cd web && npm run build
```

Expected: all exit 0.

- [ ] **Step 2: Commit and push**

Commit only the design, plan, formatter, component, tests, page wiring, and audit line.

- [ ] **Step 3: Fast-forward main and deploy**

Use a clean integration worktree, fast-forward `origin/main`, then deploy the exact SHA to Vercel production.

- [ ] **Step 4: Browser smoke**

Open an Owner Canary conflict detail and verify actual A/B values are visible, responsive, and the
existing resolution buttons remain present. Do not submit or resolve a human judgment.

