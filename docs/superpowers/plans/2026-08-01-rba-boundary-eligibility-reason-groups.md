# 사건 이어짐 자격검사 사유 분리 UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Owner 자격검사 선택지를 네 의미 영역으로 나누고 활동 오탐·영상 오류를 A/B/둘 다로 저장해 무효 clip을 정확히 전파한다.

**Architecture:** 기존 append-only 판정 table은 유지하고 forward-only SQL migration으로 decision domain과 제출 RPC만 확장한다. 웹은 단일 `BoundaryEligibilityDecision` 계약을 사용하되 화면에선 영역별 option 배열로 렌더한다. DB migration을 웹보다 먼저 production에 적용한다.

**Tech Stack:** PostgreSQL/Supabase RPC, Next.js 14, React 18, TypeScript, Vitest, pytest

## Global Constraints

- 1~22번 기존 판정 row는 수정·삭제하지 않는다.
- 22번 원본 `eligible`은 보존하고 append-only correction으로 `both_no_gecko_activity`를 기록한다.
- 선택은 기존처럼 제출 버튼을 눌러야 immutable하게 저장한다.
- holdout·Blind30·행동 GT·기존 교차검수는 건드리지 않는다.
- 사람 판정은 에이전트가 대신 제출하지 않는다.

---

### Task 1: Decision 계약과 UI 그룹

**Files:**
- Modify: `web/src/lib/rbaBoundaryServer.test.ts`
- Modify: `web/src/lib/rbaBoundaryServer.ts`
- Modify: `web/src/app/labeling/boundary/_eligibility-pair-view.test.tsx`
- Modify: `web/src/app/labeling/boundary/_eligibility-pair-view.tsx`

**Interfaces:**
- Consumes: `BoundaryEligibilityDecision`, `EligibilityPairView` props
- Produces: 새 side-aware decision 6개와 네 영역의 one-click UI

- [ ] **Step 1: decision guard 실패 테스트 작성**

  기존 5개와 아래 6개가 true이고 `no_gecko_activity` 같은 generic 값은 false임을 단언한다.

  ```ts
  'left_no_gecko_activity', 'right_no_gecko_activity', 'both_no_gecko_activity',
  'left_capture_or_media_error', 'right_capture_or_media_error',
  'both_capture_or_media_error'
  ```

- [ ] **Step 2: UI 실패 테스트 작성**

  렌더 결과에 `유효`, `게코가 안 보임`, `실제 게코 활동 없음`, `영상 자체를 확인할 수 없음`, 각 영역의
  `영상 A`·`영상 B`·`둘 다`가 있고 generic `촬영 오류 또는 화면 확인 불가` 버튼이 없는지 단언한다.
  각 label의 `data-decision` 매핑과 선택 callback·제출 callback 분리를 확인한다.

- [ ] **Step 3: RED 확인**

  Run: `cd web && npm test -- src/lib/rbaBoundaryServer.test.ts src/app/labeling/boundary/_eligibility-pair-view.test.tsx`
  Expected: 새 decision과 새 영역 문구가 없어 FAIL

- [ ] **Step 4: 최소 구현**

  `BOUNDARY_ELIGIBILITY_DECISIONS`에 6개 값을 추가한다. UI option을 유효 단독 button과 다음 구조의
  세 invalid group으로 나눈다.

  ```ts
  type EligibilityGroup = {
    title: string;
    help: string;
    options: { value: BoundaryEligibilityDecision; label: string }[];
  };
  ```

  각 group은 `rounded-xl border bg-zinc-50 p-3`, 내부 버튼은 `sm:grid-cols-3`을 사용하고 선택 강조와
  submit 동작은 기존 props를 그대로 사용한다.

- [ ] **Step 5: GREEN 확인**

  Run: `cd web && npm test -- src/lib/rbaBoundaryServer.test.ts src/app/labeling/boundary/_eligibility-pair-view.test.tsx`
  Expected: 두 파일의 모든 테스트 PASS

### Task 2: Forward-only DB migration

**Files:**
- Create: `migrations/2026-08-01_rba_boundary_eligibility_reason_groups.sql`
- Create: `tests/test_rba_boundary_eligibility_reason_groups_migration.py`
- Modify: `scripts/run_rba_boundary_sequence_eligibility_v2_probe.py`

**Interfaces:**
- Consumes: v2 table `rba_boundary_eligibility_reviews`, RPC `fn_submit_rba_boundary_eligibility`
- Produces: 확장 decision check와 side-aware invalid clip 계산

- [ ] **Step 1: migration 정적 실패 테스트 작성**

  새 migration이 constraint를 교체하고 6개 decision을 허용하며, `UPDATE`/`DELETE`로 기존 판정을
  재작성하지 않고, left/right invalid set에 각 side의 absence·activity·media decision을 포함하는지
  검사한다. correction table·append-only trigger·service-role RPC·effective decision 우선순위도 단언한다.

- [ ] **Step 2: runtime probe에 보존·matrix·정정 단언 추가**

  v2에서 먼저 21개 원본을 제출하고 count·digest snapshot을 잡은 뒤 migration을 적용한다. snapshot
  불변, 22번 `eligible`→`both_no_gecko_activity` correction, 서로 떨어진 30·40·50·60·70·80번에
  신규 6개 decision, 90번에 generic 오류를 제출한다. 최종 assignment 204개와 각 판정의 이전·현재·
  다음 pair assignment를 확인해 left/right/both 전파 방향을 독립적으로 증명한다.

- [ ] **Step 3: RED 확인**

  Run: `uv run pytest tests/test_rba_boundary_eligibility_reason_groups_migration.py tests/test_rba_boundary_sequence_eligibility_v2_runtime_probe.py -q`
  Expected: 새 migration이 없어 FAIL

- [ ] **Step 4: migration 최소 구현**

  `rba_boundary_eligibility_reviews_decision_check`를 drop/add하고 기존 5개+새 6개를 허용한다.
  `fn_submit_rba_boundary_eligibility`를 v2 본문과 같은 잠금·append-only 흐름으로 교체하되:

  ```sql
  -- left invalid
  r.decision IN (
    'left_gecko_absent','both_gecko_absent',
    'left_no_gecko_activity','both_no_gecko_activity',
    'left_capture_or_media_error','both_capture_or_media_error'
  )
  -- right invalid
  r.decision IN (
    'right_gecko_absent','both_gecko_absent',
    'right_no_gecko_activity','both_no_gecko_activity',
    'right_capture_or_media_error','both_capture_or_media_error'
  )
  ```

  generic `capture_or_media_error`는 해당 row가 `eligible`이 아니게만 하고 clip set에는 넣지 않는다.
  함수 권한은 service_role 전용으로 다시 고정한다.
  append-only `rba_boundary_eligibility_corrections`와 service-role correction RPC를 추가하고 final
  aggregation은 replacement decision을 우선한다.

- [ ] **Step 5: GREEN 확인**

  Run: `uv run pytest tests/test_rba_boundary_eligibility_reason_groups_migration.py tests/test_rba_boundary_sequence_eligibility_v2_runtime_probe.py -q`
  Expected: PASS

### Task 3: 회귀검증, production 적용, 문서 정합화

**Files:**
- Modify: `docs/superpowers/specs/2026-08-01-rba-sequence-eligibility-review-design.md`
- Modify: `specs/next-session.md`

**Interfaces:**
- Consumes: Task 1 웹, Task 2 migration
- Produces: production에서 22번부터 사용할 배포와 감사 기록

- [ ] **Step 1: 전체 로컬 검증**

  Run: `cd web && npm test && npx tsc --noEmit && npm run build`
  Expected: test 0 failures, TypeScript exit 0, Next build exit 0

  Run: `uv run pytest tests/test_rba_boundary_sequence_eligibility_v2_migration.py tests/test_rba_boundary_eligibility_reason_groups_migration.py tests/test_rba_boundary_sequence_eligibility_v2_runtime_probe.py -q`
  Expected: PASS

- [ ] **Step 2: production preflight read-only**

  Owner workspace가 `mode=eligibility`, `completed=22`, `total=120`, 다음 ordinal=23인지 aggregate만 확인한다.
  다르면 DB·웹 write 없이 중단하고 실제 수치를 보고한다.

- [ ] **Step 3: DB migration 먼저 적용**

  production Supabase에 새 migration 한 개만 적용하고, check constraint·function definition·Owner progress
  22/120을 read-only 재확인한다. 기존 eligibility row count와 digest는 적용 전후 같아야 한다. 이어
  22번 correction을 한 건 기록하고 원본 불변과 effective decision만 바뀌었는지 확인한다.

- [ ] **Step 4: 웹 production 배포**

  Vercel production build를 배포하고 `label.tera-ai.uk` alias가 Ready deployment를 가리키는지 확인한다.

- [ ] **Step 5: 23번 smoke와 문서 갱신**

  Owner 화면에서 네 영역·side-aware 버튼·23번·A/B media ready를 확인하되 어떤 버튼도 제출하지 않는다.
  설계 정본과 `specs/next-session.md` 최상단에 migration/deployment/검증 결과를 기록한다.

- [ ] **Step 6: 최종 검증과 커밋**

  변경 파일만 stage하고 `feat: 자격검사 무효 사유와 UI 영역 분리`로 커밋한다. `git status --short`,
  HEAD, upstream을 확인하고 완료 근거를 보고한다.
