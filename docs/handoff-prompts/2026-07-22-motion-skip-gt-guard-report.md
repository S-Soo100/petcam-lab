# Motion Labeling v3 제외·보류 GT Guard — 구현 보고서

- 작업 ID: `motion-skip-gt-guard`
- execution_repo: `/Users/baek/petcam-lab/.worktrees/motion-skip-gt-guard`
- 브랜치: `codex/motion-skip-gt-guard`
- 시작 HEAD(manifest SHA): `e6041652d675c0148dbdb3a55866fee547088bef`
- 작성일: 2026-07-22

## 0. 시작 계약 검증 (HANDOFF_OK)

```
HANDOFF_OK task=motion-skip-gt-guard repo=motion-skip-gt-guard commit=e6041652 runtime=none
```

- `scripts/verify_agent_handoff.py --manifest /tmp/2026-07-22-motion-skip-gt-guard-handoff.md` → `HANDOFF_OK`.
- execution_repo 로 이동 후 `git rev-parse HEAD` == manifest `commit_sha` (`e6041652…`) 재확인. 일치.
- 격리 worktree(별도 브랜치/인덱스/HEAD)라 같은 워킹트리를 공유하는 다른 세션의 파괴적 git 과 무관.

## 1. Root cause + production 감사 증거

**증상:** owner 가 운영 영상 상세에서 `제외`(skip)/`보류`(hold)를 누른 뒤 같은 화면에서 사람 판정(GT)을 저장하면, 분류가 조용히 `label` 로 되돌아간다.

**원인:** `fn_lock_motion_clip_gt` 가 owner 잠금 시 triage 를 `label` 이 아닌 모든 상태에서 `label` 로 원자 전환한다(설계 §2). 상세 화면도 `skip/hold` 이후 GT 폼을 활성 상태로 유지했다. 즉 UI·DB 두 층 모두 hold/skip 을 GT 저장으로부터 보호하지 않았다.

**production 감사(2026-07-22, read-only 조회로 독립 확인):**

- `motion_clip_labeling_triage` 상태 분포: `label` 6건, 그 외 0건. `state=skip` 목록 0건.
- 6건 event 이력(설계 §2 와 일치):
  - 5건: `owner_skipped → owner_started_labeling`, 현재 `owner_decision=label`, session 1건.
  - 1건: `owner_started_labeling`(단독), 현재 `owner_decision=label`, session 1건.

| # | clip_id | owner_decision | session | updated_at (UTC) | event_seq |
|---|---|---|---|---|---|
| 1 | `32bc902a-7d5f-4887-9f66-8ce6473bd04e` | label | 1 | 2026-07-22 11:34:50.086851 | owner_skipped → owner_started_labeling |
| 2 | `8e48c4b7-f782-4a65-bf62-7c9a1a29e7bb` | label | 1 | 2026-07-22 11:35:49.316655 | owner_skipped → owner_started_labeling |
| 3 | `7d1ccf6a-1ce5-4361-9f06-65f0f469ed22` | label | 1 | 2026-07-22 11:38:17.976829 | owner_skipped → owner_started_labeling |
| 4 | `ba37b103-7c50-4c85-9e02-a16b1419e194` | label | 1 | 2026-07-22 11:38:56.933914 | owner_skipped → owner_started_labeling |
| 5 | `7599fdeb-3bb2-42d9-81c1-caac63d644fd` | label | 1 | 2026-07-22 11:42:45.969388 | owner_started_labeling |
| 6 | `c1502d30-5a15-44f9-9b45-8510a1b54204` | label | 1 | 2026-07-22 11:43:54.927472 | owner_skipped → owner_started_labeling |

이 6건은 **mutation-0 baseline** 이다(Task 5 에서 변경 0 증거로 재대조). `owner_skipped → owner_started_labeling` 시퀀스가 "제외 결정이 GT 저장으로 label 로 뒤집힘"의 DB 물증.

**pre-state:** production `fn_lock_motion_clip_gt` 에 아직 PT424 guard 없음(`pg_get_functiondef` 조회: `has_pt424_guard=false`, `decision_blocks_labeling` 없음, 원본 본문 유지). base v3 migration 은 적용돼 있음(테이블·데이터 존재).

## 2. 상태 계약 (설계 §4)

| 현재 상태 | owner GT 잠금 | labeler GT 잠금 |
|---|---:|---:|
| `unreviewed` | 허용(기존처럼 `label` 원자 전환) | 거부(PT403) |
| `label` | 허용 | 허용 |
| `hold` | **거부(PT424)** | 거부(PT403) |
| `skip` | **거부(PT424)** | 거부(PT403) |

## 3. Task별 RED → GREEN

### Task 1 — 공유 상태 규칙 + 상세 UI 차단 (commit `23d485c`)
- **RED:** `labelingV3.test.ts` 에 `canWriteMotionGt`/`motionDecisionListPath` 기대 추가 → `TypeError: … is not a function` (4 fail).
- **GREEN:** `labelingV3.ts` 순수 함수 2개 구현 → 13 pass. 상세 페이지 연결(`actionsEnabled = videoReady && !videoFailed && canWriteGt`, hold/skip 안내 Card, `onDecided` 후 `motionDecisionListPath` 로 탭 이동). 분류 버튼은 계속 활성.
- 규칙: `canWriteMotionGt` = `unreviewed|label` 만 true. `motionDecisionListPath` = `hold|skip` 만 `/labeling/motion?state=<state>`, 그 외 null.

### Task 2 — DB 최종 guard forward migration (commit `c8327c8`)
- **RED:** migration 계약 테스트 7개 추가 → 신규 파일 없어 `FileNotFoundError` (7 error, 기존 27 pass).
- **GREEN:** `migrations/2026-07-22_motion_clip_gt_decision_guard.sql` 작성 → 34 pass.
- 함수 본문은 원본 §9 를 그대로 복사, triage `SELECT … FOR UPDATE` 직후·session 쓰기 전에 guard 한 블록만 추가:
  ```sql
  IF p_is_owner
     AND v_triage.clip_id IS NOT NULL
     AND v_triage.owner_decision IN ('hold','skip') THEN
    RAISE EXCEPTION 'decision_blocks_labeling' USING ERRCODE = 'PT424';
  END IF;
  ```
- `diff` 확인: 원본 함수 대비 **오직 guard 10줄만 추가**, 나머지 바이트 동일(lock 순서·PT422/PT403/PT423·prediction·session upsert 보존).

### Task 3 — API 안정 오류 계약 (commit `2429fb1`)
- **RED:** `labelingV3Server.test.ts` PT424 매핑 기대 + `gt/route.test.ts` PT424→409/원문비노출 기대 → PT424 미매핑이라 502 로 떨어져 fail (2 fail).
- **GREEN:** `RPC_ERROR_MAP` 에 `PT424 → {409, decision_blocks_labeling, '보류 또는 제외된 영상이야. 먼저 라벨 대상으로 보내줘.'}` 추가 → 29 pass. 상세 페이지 `lockGt` catch 에 `code === 'decision_blocks_labeling'` 분기(같은 안내 문구 + `load()` 로 stale 화면 복구).

## 4. 변경 파일 · commit SHA

| 파일 | Task |
|---|---|
| `web/src/lib/labelingV3.ts` | 1 |
| `web/src/lib/labelingV3.test.ts` | 1 |
| `web/src/app/labeling/motion/[clipId]/page.tsx` | 1, 3 |
| `migrations/2026-07-22_motion_clip_gt_decision_guard.sql` | 2 |
| `tests/test_motion_clip_labeling_v3_migration.py` | 2 |
| `web/src/lib/labelingV3Server.ts` | 3 |
| `web/src/lib/labelingV3Server.test.ts` | 3 |
| `web/src/app/api/labeling-v3/[clipId]/gt/route.test.ts` | 3 |

- Task 1: `23d485c` · Task 2: `c8327c8` · Task 3: `2429fb1`
- 보고서 draft: `<Task4 commit>` (push 후 갱신)
- push: `origin/codex/motion-skip-gt-guard`
- main FF SHA: ⏳ Task 5
- Vercel production SHA: ⏳ Task 5

## 5. 테스트 / build 결과

- web vitest 전체: **490 pass** (48 files). `npm test`.
- tsc: **clean** (`npx tsc --noEmit`, exit 0).
- pytest 전체: **694 pass** (`uv run pytest -q`).
- `git diff --check` / `git diff origin/main...HEAD --check`: clean.
- `npm run build`: **미실행** — 사용자 보안 훅 `~/.claude/hooks/dangerous-guard.sh`(donts#9)이 Claude Code 내 `npm run build` 를 차단함("리소스 경합으로 세션 불안정. 타입 체크는 tsc --noEmit, 실제 빌드는 사용자 터미널에서"). tsc 로 타입 검증은 통과. **잔여 검증: 사용자 터미널에서 `cd web && npm run build` 1회 권장**(내 페이지 변경은 `useSearchParams` 추가 없음 → 기존 Suspense 경계 트랩과 무관).

## 6. 독립 리뷰 (교차 검수)

- 외부 교차모델 CLI 2종 모두 인프라성 실패로 사용 불가: Codex CLI `gpt-5.6-sol` 버전 비호환(400), Gemini CLI free-tier 폐기(IneligibleTierError). → 재시도해도 안 풀리는 인증/버전 문제라 포기.
- 대안: **독립 컨텍스트 Claude 서브에이전트** adversarial 리뷰(구현 편향 차단). 7개 항목 전부 **PASS**, 진짜 결함 0:
  1. plpgsql FOUND 오염 없음 — bare `IF … RAISE` 는 FOUND 를 안 바꿈(FOUND 는 SELECT INTO/PERFORM/INSERT/UPDATE/DELETE/FETCH/MOVE/FOR 만 세팅). labeler 검사의 `IF NOT FOUND` 는 여전히 triage SELECT 의 FOUND 참조.
  2. PT424 가 session/event INSERT 보다 코드상 먼저.
  3. unreviewed owner(triage row 없음)·label owner/labeler 흐름 비회귀.
  4. 원본 §9 대비 guard 블록만 추가, 나머지 계약 보존.
  5. `canWriteMotionGt('label')=true` → completed(항상 label) owner 보정 안 막힘. hold/skip 만 GT 폼 disabled.
  6. PT424 매핑이 기존 매핑 비파괴, Postgres 원문 비노출.
  7. scope 위반 0.
- non-blocking 관찰: "session/event delta=0" 이 정적 문자열 테스트뿐 → **production apply 전 live rollback probe 로 굳히라**(Task 5 Step 2 가 정확히 수행).

## 7. Migration 이름 · rollback probe

- migration: `migrations/2026-07-22_motion_clip_gt_decision_guard.sql` (forward-only, `CREATE OR REPLACE FUNCTION`).
- rollback probe 결과: ⏳ Task 5 (트랜잭션 안에서 skip/hold→PT424 delta 0, unreviewed/label 정상 확인 후 전량 롤백).

## 8. Canary · 기존 6건 mutation 0

- 새 canary(기존 6건 아닌 미분류·재생가능 clip 1건): ⏳ Task 5.
- 기존 6건 mutation 0 증거(§1 baseline 재대조): ⏳ Task 5.

## 9. Rollback 방법

- 코드: `git revert` 로 commit `23d485c`/`c8327c8`/`2429fb1` 역적용(force push·파괴적 git 없음).
- DB: 원본 `2026-07-22_motion_clip_labeling_v3.sql` §9 의 guard 없는 `fn_lock_motion_clip_gt` 정의를 별도 forward migration 으로 다시 `CREATE OR REPLACE`(원본 파일 편집 금지).

## 10. 미검증 / 잔여 항목

- `npm run build`: 훅 차단으로 미실행(§5). 사용자 터미널 1회 권장.
- production migration apply · rollback probe · Vercel deploy · canary: Task 5 에서 수행 후 §7·§8·§4 갱신.

## 11. 최종 판정

⏳ Task 5(production apply·probe·canary) 완료 후 확정. 현재까지(Task 1~4): 구현·회귀·독립리뷰·정적감사 전부 통과.
