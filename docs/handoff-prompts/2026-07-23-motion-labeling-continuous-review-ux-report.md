# Motion Labeling v3 연속 검수 UX — 구현·검증 보고

**task_id:** motion-labeling-continuous-review-ux
**execution_repo:** `/Users/baek/petcam-lab/.worktrees/motion-labeling-continuous-review-ux`
**branch:** `codex/motion-labeling-continuous-review-ux`
**implementation_host:** BaekBook-Pro-14-M5.local
**작성:** 2026-07-23

## 최종 판정

**`MOTION_CONTINUOUS_REVIEW_UX_VERIFIED`** — preview 가역 canary 10건·목록 문맥 복원·독립 회귀를 통과한 커밋을 main에 FF-only 통합했고, Vercel production Ready와 운영 가역 smoke까지 확인했다. 제외·보류 결정 뒤 상세 유지, 결정 취소, 수동 다음 영상, 필터 유지, GT 폼 노출 규칙이 production에서 정상이며 canary는 모두 `unreviewed`로 원복했다.

---

## 1. 시작 계약 — `HANDOFF_OK` 전문

```
HANDOFF_OK task=motion-labeling-continuous-review-ux repo=motion-labeling-continuous-review-ux commit=62279c9f runtime=none
```

- HEAD == manifest commit_sha `62279c9f22068d010082fe8e5bcf154c02ffd58f` (검증 시점) ✅
- untracked = handoff 문서 자기 자신뿐(validator 구조상 정상) ✅
- plan/design은 지정 commit에 tracked ✅
- 격리: `.worktrees/` 전용 worktree(다른 6개 세션은 main 워킹트리 — git isolated) ✅

## 2. Task별 RED→GREEN + commit SHA

| Task | 내용 | RED 증거 | GREEN | commit |
|---|---|---|---|---|
| 1 | 미분류 기본 탭 + 목록 문맥 helper | `motionDetailPath is not a function` 등 7 fail | 17 pass | `5830773` |
| 2 | 스크롤 복원(one-shot parser) + 완료 안내 | `readStoredMotionQueueScroll` 4 fail | 21 pass | `a6e9814` |
| 3 | owner 전용 다음 미분류 API(+큐 파서 추출) | 모듈/route 부재로 `no tests` | server 10 + queue 13(byte-equiv) + next 11 pass | `c078727` |
| 4 | 결과 확인·undo·다음 영상 UX | `motionUndoDecision`/continuation 모듈 부재 fail | 18 pass | `f43ccd8` |
| 5 | 전체 회귀·감사·문서 | — | 아래 §4 | (문서 커밋 별도) |

TDD 원칙 준수: 각 Task 실제 테스트 코드 먼저 작성 → 실패(RED) 확인 → 최소 구현 → 통과(GREEN) → 커밋.

## 3. 변경 파일 + 금지 범위 0 증거

### 변경 파일 (origin/main..HEAD, 코드)
- 신규: `web/src/app/api/labeling-v3/[clipId]/next/route.ts` + `route.test.ts`, `web/src/lib/labelingV3QueueServer.ts` + `.test.ts`, `web/src/app/labeling/motion/_motion-review-continuation.tsx` + `_motion-review-continuation-view.ts` + `.test.tsx`
- 수정: `web/src/app/api/labeling-v3/queue/route.ts`(파서 추출, byte-equivalent), `web/src/app/labeling/_motion-queue.tsx`, `web/src/app/labeling/motion/[clipId]/page.tsx`, `web/src/app/labeling/motion/_motion-decision-controls.tsx`, `web/src/lib/labelingV3.ts` + `.test.ts`, `web/src/lib/labelingV3Api.ts`, `web/src/lib/labelingV3QueueClient.ts` + `.test.ts`
- 문서: `docs/FEATURES.md`(§11.7.1 추가), `specs/next-session.md`, `.claude/donts-audit.md`, 본 보고서

### 금지 범위 감사 (grep 증거)
| 금지 항목 | 결과 |
|---|---|
| migration/RPC/DB schema 변경 | **0** (migration/`.sql`/`supabase/` 파일 diff 없음) |
| backend/Python/behavior/activity/evidence 변경 | **0** (diff --name-only 매치 없음) |
| legacy/tutorial 변경 | **0** |
| 결정 성공 후 hold/skip 카테고리 `router.push` | **0** (`motionDecisionListPath` 제거, 잔존 `state=hold/skip`은 테스트 query·주석뿐) |
| 외부 `returnTo` / open redirect | **0** (허용된 큐 query만 사용) |
| 자동 next navigation | **0** (`goNext`는 onClick 3곳에서만 호출, useEffect 자동호출 없음) |
| GT/session/event 삭제·수정 | **0** (next route는 read-only: RPC list + `select`만; undo/reset은 기존 decision RPC append-only) |
| PT424 guard 약화 | **0** (`canWriteMotionGt`·PT424 catch 그대로 유지) |

## 4. 전체 web/Python/tsc/build 결과

| 검사 | 명령 | 결과 |
|---|---|---|
| web 단위/통합 | `cd web && npx vitest run` | **527 passed** (51 files) |
| TypeScript | `cd web && npx tsc --noEmit` | **exit 0** (에러 0) |
| Python 회귀 | `uv run pytest -q` | **694 passed** (6.34s) |
| whitespace | `git diff --check origin/main` | **0 errors** |
| **실 Next build** | `cd web && npm run build` | **in-session 실행 불가** — 세션 안전 훅 `~/.claude/hooks/dangerous-guard.sh`가 `npm run build`를 차단("리소스 경합, 실제 빌드는 사용자 터미널에서"). tsc를 build 성공으로 쓰지 않음. |
| **build 대체 검증** | Vercel preview (push `f43ccd8`) | **`state=success`** — "Deployment has completed" (Vercel deployment `F3jKvjHLj7zyyYBN7Ddvgd9AVUrG`, GitHub commit status). 실제 `next build`가 CI에서 통과. |

> owner가 로컬에서 직접 build를 확인하려면 터미널에서: `cd /Users/baek/petcam-lab/.worktrees/motion-labeling-continuous-review-ux/web && npm run build`

## 5. preview 10건 canary — **통과**

owner 계정으로 preview alias에서 2026-07-23 02:40~03:00 KST에 수행했다.

| 조합 | 결과 |
|---|---|
| skip ×3 | 상세 유지·성공 안내·GT 미렌더·결정 취소 후 `unreviewed` 복구 ✅ |
| hold ×3 | 상세 유지·성공 안내·수동 다음 영상·결정 취소 ✅ |
| label ×2 | GT 폼 유지·즉시 작성/나중에 다음 선택 분리·결정 취소 ✅ |
| 카메라 필터 경계 ×2 | 다음 미분류 이동 시 `camera_id` 유지·같은 카메라 영상으로 이동 ✅ |
| 목록 문맥 | `state=unreviewed` 유지, 실제 사람 클릭 왕복에서 scrollY `1000 → 1000` 정확 복원 ✅ |

- 모든 canary는 종료 전에 `unreviewed`로 원복했고 GT는 저장하지 않았다.
- 자동화 클릭이 요소를 화면 중앙으로 옮긴 1회는 `1000 → 499`로 보였으나, 화면에 이미 보이는 카드를 사람 조작 방식으로 다시 눌러 `1000 → 1000`을 확인했다. 제품 결함이 아니라 자동화의 사전 스크롤 영향이었다.
- live 표본에 동일 `started_at` 쌍은 없어 그 경계는 route/unit 회귀로 유지했고, 실제 브라우저 경계 검수는 카메라 필터 2건으로 대체했다.

## 6. main FF-only·Vercel deployment — **통과**

- preview 검수 기록 commit `710f5052215e51ce5fb3043e8dbf6bfd2aef216e`까지 clean disposable worktree에서 `origin/main`에 `--ff-only` 통합·push했다. force/non-FF 0.
- Vercel production deployment `dpl_3mSq6JttvsJqrtc7juED7JCfBQB4`가 **Ready**이고 `https://label.tera-ai.uk` alias가 연결됐다.
- 신규 migration/schema/env 변경은 없다.

## 7. production canary·reset — **통과**

- test-camera clip `de9566f5…`: `제외 → 상세 유지 → GT 폼 미렌더 → 결정 취소 → unreviewed·GT 폼 복구` ✅
- test-camera clip `c9f24427…`: `보류 → 상세 유지 → 다음 미분류 → state query 유지 → 새 clip unreviewed` ✅
- 원본 보류 clip은 `분류 초기화`로 `unreviewed` 복구했고 GT는 저장하지 않았다. 제외 canary도 결정 취소로 원복했다.
- 다음 조회는 production에서 약 4.8초 걸렸지만 이동 중 상태가 노출되고 정상 완료됐다.

## 8. 미검증 항목 + rollback 절차

**미검증(비차단):**
- in-session 실 `npm run build`는 세션 훅으로 미실행했지만 preview·production Vercel CI build가 모두 Ready다.
- live 표본에 동일 `started_at` 쌍이 없어 실제 브라우저 동률 경계는 미재현이며 route/unit 회귀로 검증했다.

**rollback (결함 발견 시):**
- 코드: `710f505`까지의 기능 커밋을 역순 revert하고 main에 push한다.
- 배포: 필요 시 직전 Ready deployment를 production으로 promote한다.
- **DB rollback 불필요** — 신규 migration/schema 0, 데이터 mutation은 reversible canary decision뿐(reset으로 복구).

## 9. 완료 상태

연속 검수 UX 구현·preview·main 통합·production 배포·가역 smoke까지 닫혔다. 이후 owner는 `https://label.tera-ai.uk/labeling/motion`의 기본 `미분류` 탭에서 실제 검수를 이어가면 된다.
