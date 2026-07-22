# Motion Labeling v3 연속 검수 UX — 구현·검증 보고

**task_id:** motion-labeling-continuous-review-ux
**execution_repo:** `/Users/baek/petcam-lab/.worktrees/motion-labeling-continuous-review-ux`
**branch:** `codex/motion-labeling-continuous-review-ux`
**implementation_host:** BaekBook-Pro-14-M5.local
**작성:** 2026-07-23

## 최종 판정

**`BLOCKED_PREVIEW`** — 코드 구현·TDD·전체 로컬 회귀·Vercel preview build까지 전부 통과했지만, **owner 인증이 필요한 preview 10-canary를 에이전트가 수행할 수 없어** hard 경계("preview 10건 미통과 상태에서 main 통합 금지")에서 정지했다. 코드 결함으로 인한 실패가 아니다. main FF 통합·production 배포·production canary는 이 gate 하위라 함께 미완이다. 아래 "미완 항목"의 절차를 owner가 실행하면 남은 gate를 닫을 수 있다.

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

## 5. preview 10건 canary — **미완 (owner 인증 필요)**

에이전트가 수행 불가한 이유:
1. **owner Supabase 인증 부재** — preview는 고유 `*.vercel.app` 도메인이라 `label.tera-ai.uk` 세션이 이월되지 않고, owner 로그인 credential이 없다.
2. **test-camera clip 식별** — reversible canary 대상(test-camera) 지정은 owner 지식.
3. preview는 production Supabase를 바라보므로 canary decision write는 production 데이터 변경(reversible이지만 owner가 수행해야 함).

**owner 실행 절차** (Vercel preview URL은 Vercel 대시보드/PR 코멘트에서 확인 — deploy `F3jKvjHLj7zyyYBN7Ddvgd9AVUrG`):

| 조합 | 기대 |
|---|---|
| skip ×3 | 상세 유지 + "제외로 저장됨" + 결정 취소·다음 미분류 영상 노출, GT 폼 미렌더 |
| hold ×3 | 상세 유지 + "보류로 저장됨" + 결정 취소·다음 미분류 영상 |
| label ×2 | "라벨 대상으로 저장됨" + "지금 사람 판정 작성"(GT 스크롤)·"나중에 라벨링하고 다음 영상" |
| same-timestamp/필터 경계 ×2 | 다음 미분류 이동 시 중복·누락 0 |

**원상복구:** 각 canary clip은 상세의 `분류 초기화`(reset) 또는 결과 카드의 `결정 취소`로 `unreviewed` 복구. GT는 저장하지 않는다(reset은 append-only event만 추가).

## 6. main FF-only·Vercel deployment — **미완**

- 현재 `origin/main` = `4b48038ee29ab2635b02abc89c0b68aca9773282` (세션 중 불변).
- HEAD `f43ccd8`는 여전히 `origin/main`의 descendant → **`--ff-only` FF-safe**.
- hard 경계상 preview 10-canary 통과 전 main 통합 금지 → **미실행**.

**owner 실행 절차** (preview canary 통과 후):
```bash
# clean disposable worktree에서
git fetch origin
git checkout -b _ff-motion-continuous origin/main
git merge --ff-only origin/codex/motion-labeling-continuous-review-ux
git push origin _ff-motion-continuous:main
# → Vercel production 자동 배포, deployment SHA 기록
```

## 7. production canary·reset — **미완**

배포 후 owner가 test-camera clip으로 확인(설계 §10.4):
- `제외 → 상세 유지 → 결정 취소 → unreviewed 복구`
- `보류 → 상세 유지 → 다음 미분류 → 원래 필터 유지`
- `목록 복귀 → scroll 복원` · `다음 없음 → 완료 안내`

canary 분류는 종료 시 전부 `reset`, GT 저장 안 함.

## 8. 미검증 항목 + rollback 절차

**미검증(에이전트 범위 밖):**
- in-session 실 `npm run build`(세션 훅) — Vercel CI build로 대체 검증됨.
- 브라우저 UI 워크스루/preview 10-canary — owner 인증 필요.
- main FF·production 배포·production canary — 상위 gate 미통과로 미도달.

**rollback (결함 발견 시):**
- 코드: feature commit 범위 `origin/main..f43ccd8` revert 또는 미통합 상태 유지(아직 main 미반영이라 rollback 불필요).
- 배포(만약 진행했다면): Vercel을 직전 Ready deployment로 promote.
- **DB rollback 불필요** — 신규 migration/schema 0, 데이터 mutation은 reversible canary decision뿐(reset으로 복구).

## 9. 다음 액션 (owner)

1. Vercel preview에서 §5 10-canary 수행 → 통과 시 §6 `--ff-only` main 통합.
2. Vercel production 배포 → §7 production canary + 전부 `reset`.
3. 통과하면 판정을 `MOTION_CONTINUOUS_REVIEW_UX_VERIFIED`로 승격하고 §11.7.1 상태 뱃지를 🟢로 갱신.
