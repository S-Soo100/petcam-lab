# 그룹 이중 블라인드 라벨링 — 구현 완료 보고서

**Stop Point 판정:** `DOUBLE_BLIND_LABELING_READY_FOR_DEPLOY_REVIEW`

**작성:** 2026-07-23 · 격리 worktree `codex/double-blind-labeling-groups`
**설계:** `docs/superpowers/specs/2026-07-23-double-blind-labeling-groups-design.md`
**계획:** `docs/superpowers/plans/2026-07-23-double-blind-labeling-groups.md`

---

## 1. 시작 계약 (HANDOFF_OK 전문)

```text
HANDOFF_OK task=double-blind-labeling-groups repo=double-blind-labeling-groups-design commit=938607ef runtime=none
```

- `git rev-parse HEAD` = `938607efb92aa6a69715b53e1da7ad3def818eda` (front matter 40자리 SHA와 일치).
- working tree clean, handoff는 `storage/` gitignored라 status에 미노출.
- 구현 브랜치 `codex/double-blind-labeling-groups`를 `codex/double-blind-labeling-groups-design`에서 신규 생성(기존 동명 브랜치 없음).
- 읽기 순서 준수: AGENTS.md → CLAUDE.md → donts.md → design 전체 → plan 전체 → docs/decision-gate.md → specs/next-session.md.

---

## 2. Task별 commit SHA와 push 상태

| Task | 제목 | commit |
|---|---|---|
| 0 | Handoff gate + baseline | (게이트, 커밋 없음) |
| 1 | 이중 블라인드 판정 비교 계약 | `fd6b949` |
| 2 | 그룹 이중 라벨링 DB 계약 | `ae443f5` |
| 3 | 이중 라벨링 개인 큐 API | `f5c8bf6` |
| 4 | 이중 라벨 제출과 자동 합의 | `c0d140c` |
| 4A | 라벨링 버튼 상태와 쳇바퀴 입력 UX | `5e48ff2` |
| 5 | 라벨러 활동일 이중 검수 UX | `75b776c` |
| 6 | 이중 라벨 불일치 owner 검수 | `82d378d` |
| 7 | 그룹 이중 라벨링 구현 검증 기록 | (이 보고서 커밋, 아래) |

**push 상태:** 전 커밋을 `origin/codex/double-blind-labeling-groups`에 push함(브랜치 신규). main merge·force push·branch delete·reset 없음.

각 태스크는 TDD RED→GREEN을 지켰다(§4). Task 2 커밋은 구현 중 두 번 amend됨(queue RPC canary-aware, ensure RPC 30일 eager materialize — 둘 다 내 신규·미적용 migration 파일의 리팩토링이며 정적 계약 테스트 37 재통과).

---

## 3. 변경 파일 목록 (base `938607e` 대비 67 files, +7601/−76)

**신규 DB/계약**
- `migrations/2026-07-23_motion_double_blind_labeling.sql` — 9테이블 + RPC 11 (forward-only, 미적용)
- `tests/test_motion_double_blind_labeling_migration.py` — 정적 계약 37

**신규 순수 계약 / 서버 헬퍼 / 클라이언트**
- `web/src/lib/motionBlindReview.ts` (+ `.test.ts`) — comparator·활동일·decision copy·canonical pair
- `web/src/lib/motionBlindReviewServer.ts` (+ `.test.ts`) — allowlist 매퍼·scope cursor·SQLSTATE 매핑·labeler 가드·owner 매퍼
- `web/src/lib/motionBlindReviewApi.ts` — 브라우저 클라이언트

**신규 labeler API** — `web/src/app/api/labeling-v3/blind/`: `_access.ts`, `workspace/`, `queue/`, `canary/[cohortId]/`, `[clipId]/`, `[clipId]/file/url/`, `[clipId]/claim/`, `[clipId]/submit/` (각 route + test)

**신규 owner API** — `web/src/app/api/labeling-v3/blind/owner/`: `conflicts/`, `[clipId]/`, `[clipId]/resolve/`, `groups/`, `canary/` (각 route + test)

**신규 컨트롤/입력** — `web/src/components/ui/SelectionControl.tsx` (+ test), `web/src/app/labeling/_wheel-interaction-fields.tsx` (+ test)

**신규 labeler UI** — `web/src/app/labeling/`: `_blind-review-view.ts`, `_blind-review-onboarding.tsx`, `_blind-review-progress.tsx`, `_blind-review-queue.tsx`, `_blind-review-detail.tsx`, `_home-switch.tsx`, `_blind-review-ui.test.tsx`, `_blind-hardening.test.ts`, `blind/[clipId]/page.tsx`, `blind/canary/[cohortId]/page.tsx`, `blind/canary/[cohortId]/[clipId]/page.tsx`

**신규 owner UI** — `blind/conflicts/page.tsx`, `blind/conflicts/[clipId]/page.tsx`, `blind/groups/page.tsx`

**수정(기존)**
- `web/src/components/ui/Button.tsx` — labeling variant 3종 추가, 기존 variant byte-equivalent
- `web/src/app/labeling/`: `_labeling-forms.tsx`(Choice→SelectionChip·wheel 흐름·종료 안내), `_date-controls.tsx`, `_motion-filter-bar.tsx`, `_motion-queue.tsx`, `quarantine/page.tsx`, `quarantine/[clipId]/page.tsx`, `router-review/[clipId]/page.tsx`, `motion/_motion-decision-controls.tsx`, `motion/_motion-review-continuation.tsx` — 검은 active 제거·labeling variant
- `web/src/app/labeling/page.tsx`·`_owner-context.tsx`·`layout.tsx` — 홈 role 스위치·`useIsLabeler`·owner nav
- `web/src/lib/labelingDisplay.ts` (+ test) — 쳇바퀴 질문 helper
- `web/src/lib/labelingRouteAccess.ts` (+ test) — blind 경로 분류
- `web/vitest.config.ts` — `oxc:{jsx:{runtime:'automatic'}}` (테스트 전용 JSX 트랜스폼; testing-library 미추가)
- docs: `docs/DATABASE.md`, `docs/FEATURES.md`, `specs/next-session.md`, `.claude/donts-audit.md`, 이 보고서

---

## 4. RED→GREEN 증거

각 태스크에서 테스트 파일을 먼저 작성 → 실패(RED) 확인 → 구현 → 통과(GREEN). 대표 로그:

- **Task 1:** `motionBlindReview.test.ts` RED = `Test Files 1 failed / Tests no tests`(모듈 없음) → 구현 후 `24 passed`.
- **Task 2:** `pytest tests/test_motion_double_blind_labeling_migration.py` RED = `37 errors`(파일 없음, read_text 실패) → 구현 후 `37 passed`. + v3 회귀 `test_motion_clip_labeling_v3_migration.py` 동시 통과(총 71).
- **Task 3:** blind 서버/route 테스트 6파일 RED(모듈/route 없음) → GREEN `55 passed`.
- **Task 4:** claim/submit/comparator RED → GREEN `45 passed`.
- **Task 4A:** `SelectionControl.test.tsx` RED(컴포넌트/variant 없음) → GREEN. wheel/labelingDisplay RED(helper 없음/순서 불일치) → GREEN `74 passed`.
- **Task 5:** `_blind-review-ui.test.tsx`·`labelingRouteAccess.test.ts` → GREEN `43 passed`.
- **Task 6:** owner API 5파일 RED → GREEN `27 passed`.

---

## 5. 최종 검증 결과 (정확한 수치)

| 항목 | 결과 |
|---|---|
| **web (vitest)** | `Test Files 69 passed (69)` · `Tests 705 passed (705)` (baseline 536 → +169) |
| **TypeScript (`tsc --noEmit`)** | `tsc-exit=0` (에러 0) |
| **Python (`uv run pytest -q`)** | `731 passed` (baseline 694 → +37 migration 계약) |
| **whitespace (`git diff --check`)** | clean |
| **production build (`npm run build`)** | ⛔ **미검증** — dangerous-guard(donts#9) 훅이 차단. 차단 전문 ↓ |

`npm run build` 차단 전문(handoff 계약대로 tsc를 build 증거로 대체하지 않음):

```text
PreToolUse:Bash hook error: [~/.claude/hooks/dangerous-guard.sh]: donts#9 위반: Claude Code 안에서 npm run build 금지. 리소스 경합으로 세션 불안정. 타입 체크는 tsc --noEmit, 실제 빌드는 사용자 터미널에서.
```

→ Next.js production build는 **owner-terminal 또는 Vercel preview build로 별도 확인 필요**. 새 dynamic API/route(`/api/labeling-v3/blind/**`, `/labeling/blind/**`) 등록은 이 build에서만 검증된다.

---

## 6. comparator · blind leakage · 경합 · canary 격리 검증

- **comparator(`motion-blind-v1`):** decision 3×3 agree/conflict, exclude 사유 무관 일치, 배열 dedup+canonical sort, segment 경계 500ms=일치·501ms=불일치, scalar mismatch, segment count/action mismatch, malformed label GT reject, note 비교 제외+원문 보존 — `motionBlindReview.test.ts`(24) + `_blind-hardening.test.ts`(대칭성·HTML-like note opaque·boundary) 커버. 순서 무관 대칭 + `canonicalSubmissionPair`로 동시 제출 시 finalize (a,b) 순서 동일 → 중복 consensus 방지.
- **blind leakage:** 매퍼 leak 테스트가 `peer_reviewer_id/peer_decision/peer_initial_gt/peer_note/r2_key/evidence_snapshot/digest`를 매퍼 출력 JSON에서 0 확인. queue/detail/canary/workspace route 응답에 상대 원문·r2_key 미포함. workspace는 멤버별 제출 수만 노출(라벨/보류/제외 분포 0). 정적 감사: `peer_*`는 submit route **서버측** RPC row 처리에만 등장하고 `NextResponse.json` 바디는 `{status, differing_fields}`·`{status:'awaiting_peer'}`·오류 봉투뿐(§소스 grep). `service_role` 리터럴은 migration에만, TS에 0.
- **경합:** claim RPC 다른 탭 토큰=`PT423 slot_in_use`(→409), 같은 토큰 renew, submit 중복(다른 내용)=`PT410 already_submitted`(→409)·같은 내용=멱등, second submission=서버 비교+finalize(digest 검증), stale digest=`PT409`시 재조회 후 1회 재시도. 동시 두 번째 제출→consensus 1건(멱등 유니크+finalize awaiting→상태 전이). route 테스트로 고정.
- **canary 격리:** slot/submission/consensus에 `cohort_kind(live|canary)`+`cohort_id`, 일반 queue/workspace/conflicts RPC는 `cohort_kind='live'` 하드 필터. canary route는 open cohort만·해당 cohort scope로만 slot 반환. cohort 종료=status closed(삭제 트리거 `0A000`). scope-embedded cursor가 다른 날짜/live↔canary 복사를 400으로 거부.

---

## 7. 버튼 상태 검증 + 검은 active 잔여 감사

- **SelectionChip/SelectionCard:** 선택=의미색 배경+2px 테두리+`✓`+보이는 `선택됨`+`aria-pressed="true"`, 비선택=`border-zinc-300`+`aria-pressed="false"`(선택됨 없음), 비활성=`disabled`+`cursor-not-allowed`, 최소 높이 `min-h-11`(44px), `focus-visible:ring-2`. 톤별 색: success→emerald / warning→amber / danger→rose / neutral→sky. `renderToStaticMarkup` 계약 테스트(`SelectionControl.test.tsx` 10).
- **모바일/데스크톱:** blind 큐·상세는 `max-w-3xl`+`grid-cols-1`(모바일 1열), 컨트롤 카드는 `sm:grid-cols-2`. 정적 렌더 계약으로 클래스 확인(실제 브라우저 반응형 워크스루는 확장 미연결로 미실행 — §9).
- **검은 active 잔여 감사:** `rg "bg-zinc-900 text-white|border-zinc-900 bg-zinc-900"`를 9개 대상 파일(`_date-controls`·`_motion-filter-bar`·`_motion-queue`·`quarantine/page`·`quarantine/[clipId]`·`router-review/[clipId]`·`motion/_motion-decision-controls`·`motion/_motion-review-continuation`·`_labeling-forms`)에 실행 → **0 matches**. blind 화면 11파일에도 `_blind-hardening.test.ts`가 매 실행 재확인.
- **Button:** 기존 `primary`는 byte-equivalent(`SelectionControl.test.tsx` source-contract 테스트가 원문 문자열 확인), `labelingPrimary/Secondary/Danger` 3종 추가. `layout.tsx`·login/signup/account/team·video `bg-black`·modal backdrop·Toast는 미수정(git status로 확인).

---

## 8. 쳇바퀴 질문 순서 · secondary 복원 · 종료 문구 · payload 불변

- **순서:** `wheelInteractionGroups()` = `{primary:['ride','rotate','push'], secondary:['chase','repeated_return','other']}`. 렌더에서 ride→rotate→push 순서 확인.
- **secondary 기본 접힘 + 복원:** 기본 `다른 행동도 기록하기`(labelingSecondary, `aria-expanded="false"`) 아래 숨김. 이미 secondary enum(`repeated_return` 등) 선택된 draft는 `shouldOpenSecondaryWheelChoices`로 자동 펼침(비동기 복원 대응). 렌더 테스트 고정.
- **종료 문구:** `WheelSegmentEndHelp`가 승인된 두 문장을 정확히 렌더(`WHEEL_SEGMENT_END_HELP`), `SegmentRow`에서 `segment.action==='wheel_interaction'`일 때만 종료시간 아래 표시. `떠남` enum 미추가.
- **payload 불변:** `INTERACTION_TYPES`=`['ride','push','rotate','chase','repeated_return','other']` 정확히 보존(하드닝 테스트), `onToggle`은 기존 enum 값 그대로 전달, 비-wheel 사물은 기존 6카드 흐름 유지. 저장 enum·`interaction_types` payload·API·migration 변경 0.

---

## 9. 알려진 편차와 미검증 항목

- **`npm run build` 미실행** (dangerous-guard 차단, §5). Next.js production build로만 검증 가능한 dynamic route 등록·번들은 owner-terminal/Vercel preview 필요.
- **RPC 런타임 미실행:** migration은 **정적 계약 테스트만**(라이브 DB 미접속) 통과했고, API route 테스트는 Supabase RPC를 mock한다. 따라서 RPC 본문의 런타임 정확성(SQL 실행·rollback probe·인덱스)은 **Task 8 preview apply**에서 검증한다(내 스코프 밖·설계 §11). SQL은 coherent·correct-looking·기존 v3 컨벤션 준수로 작성했고 정적 토큰 계약(SECURITY INVOKER·search_path=''·row lock·append-only·SQLSTATE 11·no dynamic SQL·no email literal)은 통과.
- **브라우저 UI 워크스루/반응형 실측 미실행** — Claude-in-Chrome 확장 미연결. 렌더 계약은 `renderToStaticMarkup`+순수 view-model로 대체 검증. 실제 클릭 흐름(lease 갱신·draft 복원·다중 탭)은 preview canary(설계 §10.2)에서 실계정으로 확인 필요.
- **plan vs handoff 편차 — lease token 반환:** plan Task 4는 claim 응답에 `{lease_token, lease_expires_at}` 반환을 적었으나, handoff 보안계약(line 92 "lease token을 labeler 응답에 노출하지 않는다")을 우선해 **claim 응답은 `{lease_expires_at}`만** 반환하도록 구현(토큰은 브라우저 생성·sessionStorage 보관·응답 미echo).
- **plan vs 실측 편차 — 테스트 인프라:** repo 관례가 순수 view-model 테스트(JSX 렌더 안 함)라 JSX 트랜스폼이 미설정이었다. plan의 `renderToStaticMarkup`/`screen.getByText`(testing-library) 중, testing-library는 handoff 계약(Task 4A "testing-library 의존 추가 금지")대로 **미추가**하고, `oxc.jsx` 트랜스폼만 켜서 `renderToStaticMarkup`로 렌더 계약을 검증했다. UI 상호작용은 순수 view-model(`_blind-review-view.ts` 등)로 분리해 테스트.
- **workspace `oldest_unlocked` 후진·priority 계산**은 eager 30일 materialize 전제로 SQL을 작성했다. 이 로직의 실제 동작은 preview apply에서 확인 대상.

---

## 10. 배포 경계 = 0 (증거)

handoff "명시적 금지 범위" 전부 미실행:

- **migration apply = 0** — `mcp__supabase__apply_migration`/`execute_sql` 호출 0. migration 파일은 `⏳ production 미적용` 주석·정적 테스트만.
- **production DB write = 0** — 어떤 RPC도 라이브 실행 안 함. route 테스트는 전부 mock.
- **실제 그룹 계정 매핑 = 0** — 이메일/auth UUID를 migration·소스·tracked 문서에 하드코딩하지 않음(`@gmail.com`은 "거부됨을 확인하는" 부정 테스트에만 등장).
- **main merge = 0** — 작업은 `codex/double-blind-labeling-groups` 브랜치에만. FF/merge/rebase 없음.
- **Vercel deploy = 0**, **preview/production canary = 0**.
- **기존 migration 수정 = 0** — `2026-07-22_motion_clip_labeling_v3.sql`·`_gt_decision_guard.sql` 불변, `fn_lock_motion_clip_gt` CREATE OR REPLACE 없음(정적 테스트 확인).
- **기존 owner v3·legacy v2·튜토리얼·VLM·Gate·Python Evidence·activity 계산 변경 = 0** — 관련 테이블/함수/enum 미참조, Button 기존 variant byte-equivalent, layout/login/signup/account/team 미개편.
- **reset/rebase/force push/branch delete = 0.**

---

## Stop Point

```text
DOUBLE_BLIND_LABELING_READY_FOR_DEPLOY_REVIEW
```

Task 8(deployment review·preview canary·production gate)은 **미실행** — 별도 owner 승인 경계다. 다음 단계: (1) owner-terminal/Vercel preview에서 `npm run build` 성공 확인, (2) preview에 migration apply + 문서화된 rollback probe 실행, (3) 12-clip canary, (4) owner 승인 후 FF-only main + deploy + 실그룹 매핑, (5) production 첫 30개 감사.
