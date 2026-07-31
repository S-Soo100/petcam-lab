# 사건 이어짐 v2 Owner 선별 구현 계획

> 실행 정본: `docs/superpowers/specs/2026-08-01-rba-sequence-eligibility-review-design.md`

**목표:** 기존 독립 120쌍 cohort를 감사 이력으로 닫고, 겹치는 인접 경계 120개를 Owner가 먼저
유효/무효 선별한 뒤 유효한 경계만 Owner와 peer가 검수할 수 있게 production까지 배포한다.

**구조:** 기존 boundary 도메인에 forward-only migration을 추가한다. 새 cohort는
`eligibility_open`에서 시작하고 immutable eligibility review 120개가 끝나는 transaction에서
유효 수를 검사해 assignments를 만든다. 웹 workspace는 `eligibility / boundary / waiting` mode를
명시적으로 렌더링한다.

**스택:** Python 3.12, pytest, PostgreSQL/Supabase RPC, Next.js 14, TypeScript, Vitest/Testing Library,
R2 signed URL, Vercel

---

## Task 1: 기존 상태와 private source 계약 확인

**Files:**
- Read: `scripts/prepare_rba_event_grouping_shadow.py`
- Read: `scripts/run_rba_event_grouping_shadow.py`
- Read: `scripts/seed_rba_boundary_review.py`
- Read: `tests/test_prepare_rba_event_grouping_shadow.py`

1. Mac mini private artifact의 파일 목록과 JSON key만 SSH read-only로 확인한다.
2. 기존 production cohort의 submissions/resolutions가 0인지 aggregate만 확인한다.
3. current branch에서 baseline을 실행한다.

```bash
uv run pytest -q
cd web && npm test -- --run && npx tsc --noEmit
```

Expected: 기존 suite green. 실패 시 새 변경과 분리해 원인을 기록한다.

## Task 2: 연속 경계 selector를 TDD로 추가

**Files:**
- Create: `scripts/prepare_rba_sequence_review.py`
- Create: `tests/test_prepare_rba_sequence_review.py`

1. RED: fixture에서 exact120, 같은 night 인접성, 2 cameras/6 nights, clip overlap, 결정론, 부족 시
   fail-closed를 검사한다.
2. `build_adjacent_pairs` 결과에서 development nights만 사용하고 chain 연속성을 보존하는 결정론적
   selector를 최소 구현한다.
3. manifest에는 schema version, source digest, selector seed, pair rows, unique clip count, diversity,
   canonical digest만 넣는다.
4. 선택 테스트만 green으로 만든다.

```bash
uv run pytest tests/test_prepare_rba_sequence_review.py -q
```

## Task 3: additive SQL migration을 TDD로 추가

**Files:**
- Create: `migrations/2026-08-01_rba_boundary_sequence_eligibility_v2.sql`
- Create: `tests/test_rba_boundary_sequence_eligibility_v2_migration.py`
- Create: `scripts/run_rba_boundary_sequence_eligibility_v2_probe.py`
- Create: `tests/test_rba_boundary_sequence_eligibility_v2_runtime_probe.py`

1. RED 정적 테스트: 새 status, reviewer columns, eligibility table/enum, append-only trigger, RLS/revoke,
   seed/invalidate/workspace/media/submit RPC signature를 요구한다.
2. migration을 작성한다.
   - old status check/index를 forward-only 교체
   - `owner_id`, `peer_id` 추가
   - eligibility table과 immutable trigger
   - `fn_seed_rba_boundary_sequence_review_v2`
   - `fn_invalidate_rba_boundary_review_v1`
   - eligibility-aware access/workspace/media RPC 교체
   - `fn_submit_rba_boundary_eligibility`
   - 기존 boundary submit/conflict는 valid assignment만 허용
3. RED runtime probe: 잘못된 reviewer, duplicate eligibility, early assignment, peer leakage, 마지막 판정
   atomic transition, invalid pair 미배정, insufficient valid, old cohort nonzero 답 invalidation 거절을 검사한다.
4. disposable PostgreSQL에서 probe를 green으로 만든다.

```bash
uv run pytest tests/test_rba_boundary_sequence_eligibility_v2_migration.py \
  tests/test_rba_boundary_sequence_eligibility_v2_runtime_probe.py -q
```

## Task 4: seed/preflight CLI를 TDD로 추가

**Files:**
- Create: `scripts/seed_rba_boundary_sequence_review.py`
- Create: `tests/test_seed_rba_boundary_sequence_review.py`

1. RED: exact120, development-only, ordinal 1..120, overlap 존재, digest 재계산, 2 cameras/6 nights,
   reviewer 분리, R2 preflight 전 seed 금지를 검사한다.
2. service-role RPC payload builder와 aggregate-only 출력 CLI를 구현한다.
3. R2 HEAD 결과는 raw key를 출력하지 않고 checked/missing count와 digest만 출력한다.
4. 선택 테스트를 green으로 만든다.

## Task 5: workspace 타입/API를 TDD로 확장

**Files:**
- Modify: `web/src/lib/rbaBoundaryServer.ts`
- Modify: `web/src/lib/rbaBoundaryServer.test.ts`
- Modify: `web/src/lib/rbaBoundaryApi.ts`
- Create: `web/src/app/api/rba-boundary/pairs/[pairId]/eligibility/route.ts`
- Create: `web/src/app/api/rba-boundary/pairs/[pairId]/eligibility/route.test.ts`
- Modify: `web/src/app/api/rba-boundary/workspace/route.test.ts`
- Modify: `web/src/app/api/rba-boundary/pairs/[pairId]/file/url/route.test.ts`

1. RED: `mode`, eligibility choices, waiting workspace parser, Owner eligibility route guard/body/RPC/immutable
   error를 검사한다.
2. parser/client/route 최소 구현으로 green을 만든다.
3. bearer guard에서만 reviewer ID를 얻고 raw DB/R2 오류를 숨기는 기존 보안 계약을 유지한다.

```bash
cd web && npm test -- --run src/lib/rbaBoundaryServer.test.ts \
  'src/app/api/rba-boundary/pairs/[pairId]/eligibility/route.test.ts' \
  src/app/api/rba-boundary/workspace/route.test.ts
```

## Task 6: Owner 자격 UI를 TDD로 추가

**Files:**
- Modify: `web/src/app/labeling/boundary/page.tsx`
- Create: `web/src/app/labeling/boundary/_eligibility-pair-view.tsx`
- Create: `web/src/app/labeling/boundary/_eligibility-pair-view.test.tsx`
- Modify: `web/src/app/labeling/boundary/_boundary-pair-view.test.tsx`

1. RED: eligibility mode에 1단계 제목, 5개 선택지, immutable 안내가 보이고 사건 선택지는 보이지
   않는지 검사한다.
2. boundary mode는 기존 UI를 그대로 유지하고 waiting은 peer/insufficient 상태를 쉬운 문장으로
   표시한다.
3. 제출 성공 뒤 workspace/media를 다시 불러오며 중복 클릭을 막는다.

```bash
cd web && npm test -- --run src/app/labeling/boundary
```

## Task 7: 전체 검증과 외부 교차리뷰

**Files:**
- Modify as required by findings only
- Modify: `.claude/donts-audit.md`
- Modify: `specs/next-session.md`

1. Python/Web/TS/build를 fresh 실행한다.
2. iTerm 공식 AppleScript로 기존 Claude Fable5/high 세션에 design/plan/diff read-only 리뷰를 요청한다.
3. 보안, 편향, 무효 중간 clip chain 차단, holdout 비사용을 별도 체크한다.
4. actionable finding만 TDD로 수정하고 suite를 다시 돌린다.
5. 실행 이력과 현재 단계 문서를 갱신한다.

```bash
uv run pytest -q
cd web && npm test -- --run && npx tsc --noEmit && npm run build
git diff --check
```

## Task 8: production migration, private seed, main 통합, Vercel 배포

1. production aggregate로 old cohort answers=0을 재확인한다.
2. forward migration을 적용하고 old cohort invalidation RPC를 실행한다.
3. Mac mini 격리 clone에서 sequence manifest를 만들고 unique R2 media 1차 HEAD를 통과한다.
4. seed 직전 2차 HEAD를 통과한 같은 digest만 seed한다.
5. DB aggregate로 새 cohort `eligibility_open`, pair120, eligibility0, assignments0을 확인한다.
6. 리뷰 완료 commit을 `main`에 fast-forward 통합하고 push한다.
7. Vercel production을 배포하고 도메인 alias/HEAD를 확인한다.

## Task 9: Owner 실제 시작 가능 검증

1. Chrome의 기존 Owner 로그인 세션으로 `https://label.tera-ai.uk/labeling/boundary`를 연다.
2. `1단계: 영상 자격 확인 0/120`, A/B 영상 readyState, 다섯 버튼을 확인한다.
3. 실제 eligibility 답은 대신 제출하지 않는다.
4. peer가 eligibility 단계에서 영상을 볼 수 없는지 API 또는 peer 세션으로 확인한다.
5. production HEAD, Vercel deployment, DB aggregate, git clean/upstream을 최종 보고한다.

