# 권한별 라벨링 웹 구현 보고

**task_id:** role-based-labeling-web
**execution_repo:** `/Users/baek/petcam-lab/.worktrees/double-blind-labeling-groups-design`
**feature branch:** `codex/role-based-labeling-web`
**최종 판정:** `ROLE_BASED_LABELING_WEB_READY_FOR_DEPLOY_REVIEW`

---

## 1. 시작 계약

```
HANDOFF_OK task=role-based-labeling-web repo=double-blind-labeling-groups-design commit=2287a197 runtime=none
```

- 시작 SHA: `2287a197435da6ff1888bce2080a6615a9ba31d1` (검증 시 execution_repo HEAD == manifest SHA 재확인).
- 시작 시 유일한 untracked = 이 handoff 문서(계약대로). 시작 SHA에서 `codex/role-based-labeling-web` 브랜치 생성 후 이 worktree에서만 작업.
- 이 worktree는 primary checkout(`/Users/baek/petcam-lab`)과 분리돼 동시 세션의 파괴적 git으로부터 격리됨(SessionStart 경고 대응).

## 2. Task별 commit SHA

| Task | commit | 제목 |
|---|---|---|
| 1 | `badc5da` | feat: 라벨링 웹 역할별 경로 계약 |
| 2 | `e7a79d0` | feat: 권한별 라벨링 읽기 모델 |
| 3 | `98d9591` | feat: 라벨링 역할별 읽기 API |
| 4 | `6ee8b70` | feat: 라벨링 웹 역할별 반응형 셸 |
| 5 | `6c3c55e` | feat: 라벨러 오늘 작업과 내 기록 |
| 6 | `ef0c446` | feat: 읽기 전용 영상 보관함 |
| 7 | `7366a93` | feat: Owner 운영 홈과 Canary 현황 |
| 8 | `cca2f5f` | test: 라벨링 역할 UX 권한과 반응형 계약 |
| 9 | (이 문서 커밋) | docs: 권한별 라벨링 웹 구현 보고 |

각 Task는 RED → GREEN → 관련 회귀 → 명시 파일만 commit 순서를 지켰다.

## 3. 변경 파일 (역할 shell / data / API / page 그룹)

**순수 계약 · data**
- `web/src/lib/labelingRoleNavigation.ts`(+test) — 역할 판정(Owner→라벨러→미승인)·홈·3메뉴.
- `web/src/lib/labelingRouteAccess.ts`(+test) — 8-카테고리 categorize + redirectTarget(landing/shared/labeler/owner…).
- `web/src/lib/labelingRoleData.ts`(+test) — 공개 타입·라벨 상태/출처 문구·`collapseFinalStatus`(확정됨/검수 중).

**서버 mapper · API**
- `web/src/lib/labelingRoleServer.ts`(+test) — scope-hash cursor·필터 파서·allowlist row 매퍼.
- `web/src/app/api/labeling-v3/blind/history/route.ts`(+test) — 라벨러 본인 기록(owner→403).
- `web/src/app/api/labeling-v3/library/route.ts`·`[clipId]/route.ts`·`[clipId]/file/url/route.ts`(+test) — 공용 읽기 전용.
- `web/src/app/api/labeling-v3/blind/owner/overview/route.ts`(+test) — Owner 운영 현황(owner-only).
- `web/src/app/api/labeling-v3/blind/canary/[cohortId]/route.ts`(+test) — 동일 링크 owner/labeler 분기 union.
- `web/src/lib/motionBlindReviewApi.ts` — 브라우저 클라이언트(history/library/overview/카메라 옵션) + `BlindCanaryResponse` union.

**shell · page**
- `web/src/app/labeling/_role-shell.tsx`·`_account-menu.tsx`(+test) — 반응형 역할 셸.
- `web/src/app/labeling/layout.tsx` — 인증 유지 + navigation을 RoleShell에 위임 + public bare 렌더.
- `web/src/app/labeling/_blind-review-queue.tsx`·`_blind-review-progress.tsx`·`_blind-review-view.ts`(+`_blind-review-ui.test.tsx`) — 오늘 작업 UX(상대 진행 라인 제거).
- `web/src/app/labeling/_labeler-history.tsx` — 내 기록.
- `web/src/app/labeling/library/page.tsx`·`library/[clipId]/page.tsx` — 읽기 전용 보관함.
- `web/src/app/labeling/owner/page.tsx`·`owner/research/page.tsx` — Owner 운영 홈·연구 허브.
- `web/src/app/labeling/blind/canary/[cohortId]/page.tsx` — 역할별 canary 화면.
- `web/src/app/labeling/me/page.tsx`·`_home-switch.tsx`·`page.tsx`·`team/page.tsx`·`pending/page.tsx`·`apply/page.tsx` — 역할 landing·팀/미승인.
- `web/src/app/labeling/_role-pages.test.tsx` — 주요 화면 SSR 계약(순수 서브컴포넌트).

**migration · 감사 · 문서**
- `migrations/2026-07-24_role_based_labeling_reads.sql`(+`tests/test_role_based_labeling_reads_migration.py`).
- `web/scripts/audit-labeling-role-ui.mjs` + `web/package.json`(`audit:labeling-role-ui`).
- `docs/FEATURES.md`·`docs/DATABASE.md`·`specs/next-session.md`·`.claude/donts-audit.md`(additive SOT).

## 4. 테스트 / 빌드 출력

- `cd web && npm test` → **Test Files 80 passed / Tests 797 passed**.
- `cd web && npx tsc --noEmit` → **exit 0**.
- `uv run pytest -q` → **757 passed**.
- `cd web && npm run audit:labeling-role-ui` → **exit 0** (`통과 — 역할 셸 반응형·3메뉴 계약 OK`).
- `cd web && npm run build` → **`BUILD_UNVERIFIED_SAFETY_HOOK`**. repo safety hook(`~/.claude/hooks/dangerous-guard.sh`, donts#9)이 차단:
  > `donts#9 위반: Claude Code 안에서 npm run build 금지. 리소스 경합으로 세션 불안정. 타입 체크는 tsc --noEmit, 실제 빌드는 사용자 터미널에서.`
  tsc 성공을 build 성공으로 바꿔 말하지 않는다. 실제 build/route 등록 검증은 owner 터미널 또는 Vercel preview 소관.

## 5. Blind 누출 감사

`rg "r2_key|reviewer_id|digest|lease_token|prediction_snapshot|evidence_snapshot|rank_features"`를 새 API 3디렉토리(library·blind/history·blind/owner/overview)에 실행 — **모든 히트가 (a) 서버측 select(예: file/url이 서명용으로 `r2_key`만 읽고 응답엔 `{url, expires_in}`만), (b) 매퍼 명시 생략을 설명하는 주석, (c) 네거티브 테스트(주입 후 응답에서 배제 assert)** 중 하나였고, 어떤 응답 mapper도 금지 필드를 포함하지 않는다.

- 매퍼는 RPC row spread 없이 지정 필드만 새 객체로 뽑는다(`labelingRoleServer` `mapLibraryRow`/`mapHistoryRow`/`mapOwnerOverview`).
- 라벨러 history: consensus 원시 status를 `확정됨/검수 중` 2단계로 접어 conflict 발생 여부조차 은닉.
- Owner overview·canary owner: reviewer UUID·이메일·개별 제출 body 없이 display_name+count만.
- 라이브러리 file/url·canary owner에 금지 필드 전체 목록 주입 후 배제 회귀 포함.

## 6. Migration 정적/런타임 상태

- `2026-07-24_role_based_labeling_reads.sql` = forward-only, 읽기 전용 RPC 3 + 인덱스 2(부분). 기존 2026-07-22/23 migration 미수정.
- 정적 계약 테스트 `tests/test_role_based_labeling_reads_migration.py` 통과(service_role 전용 REVOKE/GRANT·write 문 부재 마커·확정 전 라벨 은닉 분류).
- **런타임 미검증:** 라이브 DB에 apply하지 않았다. RPC 본문 런타임 정확성(SECURITY INVOKER 실행·SRF 컬럼·time-range wrap·legacy LATERAL 정렬)은 Preview Deployment Gate의 disposable/local PostgreSQL dry probe에서 검증한다. 그래서 SQL은 coherent·correct-looking에 집중했다.

## 7. 미검증 항목

- `npm run build`(safety hook 차단) — Next build·route 등록 미확인.
- 6-width(320/360/390/768/1024/1440) 스크린샷 회귀·200% 확대·키보드 포커스 — 정적 반응형 감사(토큰)만 실행, 실제 브라우저 렌더 미실행.
- RPC 런타임(라이브 DB apply 전).
- 실제 owner/labeler/미승인 계정 브라우저 워크스루(로그인 불가).

## 8. 하지 않은 것 (배포 경계 준수)

production migration apply · production DB write · main merge/push · Vercel production deploy · 실제 그룹·카메라·Canary 변경 · 기존 적용 migration 수정 · GT/comparator/submission payload 변경 · VLM/Python Evidence/Gate/router 결과 공개 · 다른 세션 파일 add/commit/delete · reset/rebase/force push — **전부 0**.

## 9. 브랜치/HEAD/tree 상태

- branch: `codex/role-based-labeling-web`, HEAD: `cca2f5f`(이 문서 커밋 전 기준). 이 문서 커밋 후 push하여 `local HEAD == origin`·clean tree를 확인하고 Stop Point에서 정지한다.
- untracked: handoff 문서 1개만(허용).

## 10. 다음 배포 게이트 (이번 세션 실행 금지 — 별도 owner/Codex 승인)

1. migration rollback probe: disposable/local PostgreSQL에 dry apply → rollback → residue 0.
2. production migration apply(rollback probe·residue 0) → Vercel preview build.
3. Vercel preview에서 owner/labeler/미승인 role routing.
4. 6-width 스크린샷 매트릭스: 가로 overflow 0(`scrollWidth <= innerWidth`)·메뉴/숫자 단일 라인·계정 메뉴 도달·200% 확대 핵심 작업.
5. owner canary 동일 URL 현황판 + labeler 자기 큐 · library 전 카메라 읽기 전용/확정 전 라벨 비공개.
6. 전 게이트 통과 후에만 main FF-only 통합 + production 배포 리뷰.

---

**참고 — 계획 대비 최소 편차(임의 확장 아님):**
1. library `최종 라벨`(`final_decision`) 필터: read RPC에 대응 파라미터가 없어 로드된 페이지 한정 client-side 좁힘(page-scoped). 나머지 필터(날짜/시간대/카메라/상태/출처)는 서버 keyset으로 전량 반영.
2. team page `Canary 생성·종료` 링크: 전용 canary 생성 페이지가 아직 없어 `/labeling/blind/groups`로 임시 연결(canary 생성 UI는 후속 작업).
3. 미승인 튜토리얼 접근: 설계 §3.3은 "튜토리얼 계속하기"를 언급하나 plan의 redirectTarget 계약은 pending/unregistered를 각각 대기/신청 화면으로만 정렬한다 → plan 계약 우선(원 layout 동작과도 일치).
