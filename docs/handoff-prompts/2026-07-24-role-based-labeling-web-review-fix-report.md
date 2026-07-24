# 권한별 라벨링 웹 독립리뷰 후속 수정 보고

**task_id:** role-based-labeling-web-review-fix
**execution_repo:** `/Users/baek/petcam-lab/.worktrees/double-blind-labeling-groups-design`
**feature branch:** `codex/role-based-labeling-web`
**최종 판정:** `ROLE_BASED_LABELING_WEB_HARDENED_READY_FOR_PREVIEW`

Codex 독립리뷰가 지적한 P0 2건·P1 4건을 전부 닫았다. `READY_FOR_DEPLOY_REVIEW` 는 수용하지 않고
main merge·migration apply·deploy 로 넘어가지 않았다.

---

## 1. 시작 계약

```text
HANDOFF_OK task=role-based-labeling-web-review-fix repo=double-blind-labeling-groups-design commit=8217bc00 runtime=none
```

- 시작 SHA: `8217bc00da291ebbb4d7193e754427229c7c5d12` (검증 시 local HEAD == origin/codex/role-based-labeling-web == manifest SHA 재확인).
- 시작 시 유일한 untracked = 허용된 handoff 문서 2개(review-fix·web). 이 worktree 는 primary checkout 과 분리돼 동시 세션 파괴적 git 으로부터 격리됨.
- branch `codex/role-based-labeling-web` 에서만 작업. 새 branch·checkout·reset·rebase·force push 없음.
- **production migration history read-only 확인**(`list_migrations`): 최신 = `20260724074146 motion_double_blind_labeling`. `2026-07-24_role_based_labeling_reads` 는 **production 미적용** → 규칙대로 신규 migration 파일을 직접 수정(correction migration 불필요).

## 2. Task 별 RED→GREEN + commit SHA

각 Task 는 RED 테스트 작성 → RED 출력 확인 → 최소 구현 → GREEN → 관련 회귀 → 명시 파일만 commit 순서를 지켰다.

| Task | commit | 제목 | RED→GREEN 요지 |
|---|---|---|---|
| 1 | `bdfd4f3` | fix: blind 라벨러의 motion v3 우회 경로 차단 | 라벨러 motion v3 상세/media/gt/vlm-review 테스트를 owner-only(404 은닉/403, DB·RPC 0회)로 뒤집어 RED → `_access.ts`/`gt`/`vlm-review`/`categorize` 수정 GREEN |
| 2 | `5594f75` | fix: 영상 보관함 blind 공개와 전체 필터 계약 교정 | canary 공개·re_review·final_decision·101 cap·ambiguous 정적/TS 테스트 RED → migration + roleServer/Data + library page GREEN |
| 3 | `13ad12d` | test: 권한별 라벨링 read RPC 실제 DB probe | 신규 probe(runner/SQL/unit). 실 local PG15 실행이 RED(미존재)→GREEN(4 마커 통과) |
| 4 | `f515aac` | fix: Canary reviewer snapshot과 제출률 정합화 | 멤버 교체 후 canary reviewer/총량 분모 테스트 RED(현재 group member 사용) → slot snapshot + slot_total GREEN |
| 5 | `5e4b04e` | fix: 라벨러 기록 필터와 역할별 안내 계약 보완 | history 시간대 필터 RED → RPC/parser/UI GREEN. 5B 거짓 링크 제거. 5C BLOCKED(계약대로) |
| 6 | (이 문서) | docs: 권한별 라벨링 웹 하드닝 보고 | 전체 검증·감사·보고 |

## 3. 두 P0 우회 전/후 증거

### P0-2 — motion v3 직접 API blind 우회 (Task 1)

**전:** `labelingRouteAccess.categorize('/labeling/<uuid>')` → `landing` → 라벨러 접근 허용. `_access.ts`
`loadMotionClipAccess` 가 `ownerDecision='label'` 또는 본인 세션이면 라벨러에게 상세/media 를 열어줬고,
`gt`·`vlm-review` 는 `requireProductionLabelingAccess`(owner+labeler)로 라벨러 write 를 허용.

**후(코드):**
- `categorize` 에 canonical UUID 단일 세그먼트 → `owner` 분기 추가. 라벨러는 `/labeling` 로 정렬.
- `loadMotionClipAccess`: `requireProductionLabelingAccess` 직후 `if (!access.isOwner) return notFound()` — clip/triage/session DB 조회 **0회**로 존재 은닉 404(상세·media 공용).
- `gt`·`vlm-review`: 접근 직후 `if (!isOwner) return 403` — DB query·write RPC **0회**.
- `decision`·`next`·`revise` 는 이미 owner-only(적대 테스트 확인). 같은 family 에 labeler 허용 잔존 0.

**후(테스트):** 라벨러 → 상세·media 404(`from` 미호출), gt·vlm-review 403(`from`/`rpc` 미호출) 적대 테스트로 고정.
`labelingRouteAccess.test.ts` 가 `/labeling/<uuid>`→owner + 라벨러 redirect `/labeling` 고정.

### P0-1 — open canary 재검수 중 기존 정답 누출 (Task 2)

**전:** `fn_list_motion_labeling_library` 가 `cohort_kind='live'` consensus 만 봤다. 과거 clip 이 open
canary 에 편입돼도 live consensus 가 없으면 legacy Owner/단일 GT 가 `final` 로 공개 → 라벨러가 자기 canary
queue 의 clip id 로 library 를 직접 쳐 기존 정답 열람 가능(설계 §2 blind·§6.3 위반).

**후(코드):** 공개 우선순위 **canary scope → live consensus → legacy**. canary consensus(생성 시 awaiting 으로
선생성)를 open 우선·`created_at DESC, id DESC` LATERAL 로 최신 하나 선택. canary/live awaiting·conflict →
`re_review`/`awaiting`/`owner_review`(decision·GT null). `agreed`/`owner_resolved` 만 공개. `re_review`
상태(`라벨 재검수 중`)를 `PublicLabelState`·문구·allowlist 에 추가.

**후(런타임 증거):** 실 DB probe fixture f2(legacy+open canary awaiting)·f3(conflict) 가
`label_state='re_review'` + `final_decision/final_gt IS NULL` 을 ASSERT(§4 마커 `ROLE_READS_BLIND_GUARD_OK`).

## 4. 실제 DB probe — 네 마커

`uv run python scripts/run_role_based_labeling_reads_probe.py --backend local-postgres` (127.0.0.1 Homebrew PG15):

```text
ROLE_READS_RUNTIME_OK
ROLE_READS_BLIND_GUARD_OK
ROLE_READS_PAGINATION_OK
PROBE_RESIDUE=0
```
exit 0. 임시 DB `blind_probe_role_reads_<hex>` 만 create/drop(prefix 재검증), 기존 DB·전역 role 불변, 잔여 synthetic row 0, 정리 실패 fail-closed.

- prereq → `2026-07-22_motion_clip_labeling_v3` → `2026-07-23_motion_double_blind_labeling` → read migration 순서 적용.
- **non-empty** 합성 row(8 fixture + 102/113 clip)로 history/library/overview 3 RPC 실호출.
- **Codex ambiguous-column 재현·차단:** library 를 non-empty 로 호출하는 fixture 가 `column reference "camera_id" is ambiguous` 없이 실행됨을 ASSERT(빈 테이블 호출로 성공 처리하지 않음). classified 를 `c.<col>` 로 한정한 P1-1 fix 를 런타임에서 확인.

## 5. library 100-boundary·server-side final filter 증거

- **P1-1 ambiguous:** outer SELECT/WHERE/ORDER BY 를 `FROM classified c` + `c.<col>` 로 전부 한정. 정적 테스트 `test_ambiguous_column_qualified_with_classified_alias` + 런타임 probe 로 이중 확인.
- **P1-2 페이지네이션:** history·library fetch cap 을 `LEAST(GREATEST(p_limit,1),101)` 로 상향(100→101 lookahead). probe f7: 102 clip 에서 `p_limit=101`→첫 page **101**(100 cap 이면 실패), 101번째 cursor→다음 page 1. TS `buildLibraryPage` 100-boundary 테스트(101 rows→100 노출 has_more true / 정확히 100→false).
- **P1-2 서버측 final_decision:** RPC 에 `p_final_decision` 추가(allowlist 밖 22023), classified 뒤·keyset 전 적용. `parseLibraryFilters`·cursor scope·API args 반영, library page client-side `shown` 좁힘 제거. probe f8: 110 label(최신)+3 exclude(오래됨)에서 필터없는 첫 page exclude 0, `p_final_decision=exclude`→뒤 page 결과 3건 전부 반환(client-side 좁힘이면 0). REVOKE/GRANT signature 갱신(13-type).

## 6. canary reviewer snapshot·분모 증거 (P1-3)

- **reviewer 정본 = slot snapshot:** `ownerDashboard` 가 현재 group member 조회를 제거하고 `motion_clip_review_slots`(cohort_id) 의 distinct reviewer_id 를 정본으로 사용. display_name 만 `labeler_applications` lookup. 테스트: 그룹 멤버가 uc/ud 로 교체돼도 owner 화면은 slot snapshot 의 원래 reviewer(ua/ub) 두 명을 보이고, `motion_labeling_review_group_members` 를 조회하지 않음(from 호출 테이블 assert).
- **reviewer 별 submitted/total:** 응답 reviewers 에 `total_count` 추가. `clip_total=8`, ua 8/8·ub 7/8 → `{submitted 8, total 8}`,`{submitted 7, total 8}`. canary owner UI 는 `submitted/total 완료`.
- **owner 홈 진행률 분모:** overview open_canaries 에 `slot_total`(=reviewer 2인이면 2×clip_total) 추가. owner 홈은 `submitted_total/slot_total` 로 렌더(`clip_total` 분모 제거 → 15/16, not 15/8). `OwnerOverviewCanary`·`mapOwnerOverview`·`_role-pages` 테스트 반영.
- reviewer UUID·이메일·개별 제출 body 응답 0(테스트 `not.toContain('reviewer_id')` + slot reviewer_id 는 서버측 counting 전용).

## 7. 전체 테스트 정확한 개수

| 검증 | 명령 | 결과 |
|---|---|---|
| 웹 유닛 | `cd web && npm test` | **Test Files 80 passed / Tests 809 passed** |
| TypeScript | `cd web && npx tsc --noEmit` | **exit 0** |
| Python | `uv run pytest -q` | **771 passed, 1 skipped** (skip = opt-in live probe 통합 테스트 `ROLE_READS_PROBE_LIVE`) |
| 정적 UI 감사 | `cd web && npm run audit:labeling-role-ui` | **exit 0** (`통과 — 역할 셸 반응형·3메뉴 계약 OK`) |
| 실 DB probe | `uv run python scripts/run_role_based_labeling_reads_probe.py --backend local-postgres` | **exit 0**, 4 마커 |
| diff check | `git diff --check 8217bc00..HEAD` | **exit 0**(공백·conflict 마커 0) |

시작 대비 웹 797→809(+12), Python 757→771(+14, migration 정적 + runtime probe unit).

## 8. build 검증/미검증 구분

- `cd web && npm run build` → **`BUILD_UNVERIFIED_SAFETY_HOOK`**. repo safety hook(`~/.claude/hooks/dangerous-guard.sh`, donts#9)이 차단:
  > `donts#9 위반: Claude Code 안에서 npm run build 금지. 리소스 경합으로 세션 불안정. 타입 체크는 tsc --noEmit, 실제 빌드는 사용자 터미널에서.`
- `tsc --noEmit`(exit 0)을 build 성공으로 바꿔 말하지 않는다. 실제 Next build·route 등록·6-width 화면 검증은 **Preview Gate**(owner 터미널/Vercel preview) 소관이다.

## 9. mutation·secret·raw field 감사

- **라벨러 motion v3 차단:** `/labeling/[clipId]` 및 `/api/labeling-v3/[clipId]/**`(route·decision·gt·next·revise·vlm-review·file/url) 전부 owner-only. 라벨러 write 흐름은 `/labeling/blind/**` 뿐.
- **open/misresolved canary legacy 공개 0:** canary awaiting/conflict → re_review(decision/GT null), live awaiting/conflict → 은닉. probe BLIND_GUARD + 정적/TS 테스트로 고정.
- **raw field 응답 0:** `rg "r2_key|reviewer_id|digest|lease_token|prediction_snapshot|evidence_snapshot|rank_features|peer_"` (library·blind/history·blind/owner/overview) 히트는 전부 (a) 서명용 서버 select(`file/url` 이 `r2_key` 만 읽고 응답은 `{url, expires_in}`), (b) 주석, (c) bearer 유래 RPC 입력(`p_reviewer_id`) 중 하나. 매퍼는 지정 필드만 새 객체로 뽑는다(RPC row spread 금지). canary owner route 의 `reviewer_id` 는 서버측 counting 전용, 응답 미포함.
- **read GET write RPC 0:** library/history/owner overview GET 는 read RPC(`fn_list_motion_labeling_library`/`fn_list_motion_blind_history`/`fn_get_motion_blind_owner_overview`)만 호출. 세 read 함수는 SECURITY INVOKER·write 문 부재(정적 마커 + probe rollback residue 0).
- **production DB write 0:** migration apply·production write·main merge/push·deploy·그룹/카메라/canary 변경·comparator/GT/submission payload 변경·다른 worktree 수정·reset/rebase/force push — 전부 0.

## 10. 미해결 사항과 다음 Preview Gate

**미해결(계약대로 fail-closed):**
- **5C `BLOCKED_TUTORIAL_ACCESS_CONTRACT`** — 모든 튜토리얼 콘텐츠 API(`/api/labeling-tutorial/**`)가 `requireLabelingAccess`(owner 또는 approved labeler 전용, pending/rejected/unregistered 403)를 쓴다. 승인 전 안전하게 동작하는 public/tutorial 경로가 **없다**. 미승인 사용자에게 `튜토리얼 계속하기` CTA·route access 를 복구하려면 승인 라벨러 전용 API 를 약화해야만 하므로, 계약대로 권한을 넓히지 않고 pending/apply·tutorial auth 를 변경하지 않았다. 전용 public tutorial preview 흐름은 **별도 설계 승인 대상**이다. (보안 하드닝 항목이 아니라 UX 완결성 gap)

**미검증(Preview Gate 소관):**
- 실제 Next build·route 등록(safety hook 차단).
- 6-width(320/360/390/768/1024/1440) 스크린샷 회귀·200% 확대·키보드 포커스(정적 토큰 감사만 실행).
- read migration 라이브 DB apply(현재 미적용, local disposable probe 로만 검증).
- 실제 owner/labeler/미승인 계정 브라우저 워크스루.

**다음 Preview Gate(별도 owner/Codex 승인 handoff):**
1. read migration rollback probe(disposable/local PG → apply → rollback → residue 0).
2. production migration apply(rollback probe·residue 0) → Vercel preview build.
3. Vercel preview 에서 owner/labeler/미승인 role routing.
4. 6-width 스크린샷 매트릭스(가로 overflow 0·메뉴/숫자 단일 라인·계정 메뉴 도달·200% 확대).
5. owner canary 동일 URL 현황판 + labeler 자기 큐 · library 전 카메라 읽기 전용/확정 전(re_review 포함) 라벨 비공개.
6. 전 게이트 통과 후에만 main FF-only 통합 + production 배포 리뷰.

---

## 브랜치/HEAD/tree 상태

- branch `codex/role-based-labeling-web`, HEAD `5e4b04e`(이 문서 커밋 전 기준). 이 문서 커밋 + push 후 `local HEAD == origin/codex/role-based-labeling-web` · 허용 handoff 외 clean tree 확인하고 Stop Point 에서 정지한다.
- 허용 untracked: handoff 문서(review-fix·web) + 이 보고서.

---

## 후속 하드닝 (독립 검수 반영)

Owner 전용 motion v3 경로의 가드를 `requireProductionLabelingAccess()`+`isOwner` 방식에서
`requireOwner()` 로 통일했다(대상: `_access.ts` 상세·미디어 공통, `[clipId]/gt`, `[clipId]/vlm-review`,
`[clipId]/next`). 라벨러(비-owner)·미승인 요청은 이제 bearer 검증 + `DEV_USER_ID` env 비교만으로
끝나 `labelers`/tutorial DB 조회를 하지 않는다(이전엔 거부 전에 두 조회를 탔다). 상세·미디어의
라벨러 응답은 존재 은닉 404 → owner-only 403 으로 통일됐다(gt·vlm-review·next 는 기존대로 403).
`requireOwner` 자체가 owner/비-owner/DEV_USER_ID 누락/인증 실패 모두 `supabaseAdmin.from` 0회임을
`labelingAccess.test.ts` 로 고정했고, 네 라우트 테스트에 인증 실패·DEV_USER_ID 누락·owner 성공·
비-owner 403(DB 0) 회귀를 추가했다. GT/comparator/submission payload·public 계약은 불변.

**최종 판정:** `ROLE_BASED_LABELING_WEB_HARDENED_READY_FOR_PREVIEW`
