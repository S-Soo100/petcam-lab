# `motion_clips` 네이티브 운영 라벨링 v3 구현 보고

## 1. 시작 계약
- HANDOFF_OK: `HANDOFF_OK task=motion-clips-native-labeling repo=motion-clips-labeling-native commit=a8533fcd runtime=none`
- starting HEAD: `a8533fcd93ee12a2025de1632fac5b08784faaa4`
- shared_web_gate: `clear`
  - 판정 근거: `local-vlm-evidence-web-gt` worktree는 working tree clean, 브랜치(미푸시 6커밋 포함) 변경이 공용 web 파일(`web/src/app/labeling`, `web/src/lib/labelingApi.ts`, `web/src/lib/labelingV2.ts`)을 전혀 건드리지 않음. origin·local ref diff 둘 다 empty.
  - 주의: 그쪽 세션은 `[ahead 6]`(미푸시=active) 상태 → Task 9 Step 1 재확인 게이트에서 다시 검증. 그 시점에 공용 파일 겹침이 생기면 `V3_PREVIEW_READY_INTEGRATION_BLOCKED`로 전환.
- baseline: Python 660 passed / Web 374 passed / tsc exit 0
- forbidden: production migration/deploy/main merge/mirror/Evidence GT mutation/behavior label 자동생성/VLM 실행/env 변경/production canary

## 2. 변경 파일과 task별 commit

| Task | commit | 지정 파일 |
|---|---|---|
| 0 | `0439a63` | `docs/handoff-prompts/2026-07-22-...-report.md`(시작 계약) |
| 1 | `00f2977` | `migrations/2026-07-22_motion_clip_labeling_v3.sql`, `tests/test_motion_clip_labeling_v3_migration.py` |
| 2 | `12c0507` | `web/src/lib/labelingV3.ts` `.test.ts`, `labelingV3Server.ts` `.test.ts` |
| 3 | `4124285` | `web/src/app/api/labeling-v3/queue/**`, `cameras/**`, `web/src/lib/labelingV3Api.ts` |
| 4 | `416f811` | `web/src/app/api/labeling-v3/[clipId]/route*`, `[clipId]/file/url/route*`, `_access.ts`, `labelingV3Api.ts` |
| 5 | `0f903b3` | `web/src/app/api/labeling-v3/[clipId]/decision/route*`, `labelingV3Api.ts` |
| 6 | `e8eeeb1` | `web/src/app/api/labeling-v3/[clipId]/{gt,vlm-review,revise}/route*`, `labelingV3Api.ts` |
| 7 | `70f36ea` | `web/src/app/labeling/_motion-filter-bar.tsx`, `_motion-queue.tsx`, `motion/page.tsx`, `web/src/lib/labelingV3QueueClient.ts` `.test.ts` |
| 8 | `02b81b4` | `web/src/app/labeling/motion/[clipId]/page.tsx`, `motion/_motion-decision-controls.tsx`, `_labeling-forms.tsx`(VideoPlayer 콜백 additive), `labelingV3.ts` `.test.ts`, `labelingV3Server.ts` `.test.ts`, `_access.ts`, `[clipId]/route.ts`(state_updated_at 노출) |
| 9 | `d88f3f1` | `web/src/app/labeling/page.tsx`(server wrapper), `_legacy-queue.tsx`, `legacy/page.tsx`, `labelingV3.ts` `.test.ts`, `web/.env.example` |
| 10 | (본 커밋) | `docs/DATABASE.md`, `docs/FEATURES.md`, `.claude/donts-audit.md`, 본 보고서 |

**계획 밖 보강(정당화):** ① Task 8에서 owner decision optimistic concurrency를 위해 `state_updated_at`을 detail 계약(`labelingV3.ts`/`Server.ts`/`_access.ts`/`[clipId]/route.ts`)에 노출 — RPC가 기존 triage row에 정확한 `expected_updated_at`을 요구(null이면 stale)하므로 UI가 현재 version을 알아야 함. ② GT를 화이트리스트(`sanitizeGroundTruth`)로 정제 — `validateGroundTruth`가 raw cast라 추가 필드가 GT jsonb로 샐 수 있음. ③ `_access.ts`(공유 접근 판정) 추가 — detail/media 두 route가 보안 크리티컬 접근 로직을 단일 소스로 공유.

## 3. RED→GREEN 증거

각 task는 RED(테스트 먼저·실패 확인)→구현→GREEN 순으로 커밋. 대표:
- Task 1: contract test 24건 RED(파일 없음 24 errors) → migration 작성 → GREEN(24 passed).
- Task 2: `labelingV3.test.ts`/`labelingV3Server.test.ts` RED(module not found) → 구현 → 19 passed.
- Task 3: queue/cameras route test RED(no tests) → 구현 → 17 passed.
- Task 4: detail/media route test RED → 구현(+`_access` 경로 오타 1회 수정) → 16 passed.
- Task 5: decision route test RED → 구현 → 12 passed.
- Task 6: gt/vlm-review/revise test RED → 구현(+vlm-review note 정규화 수정) → 27 passed.
- Task 7: `labelingV3QueueClient.test.ts` RED → 구현 → 10 passed.
- Task 8: `decideMotionDetailPhase` 테스트 GREEN(+5) → detail page(tsc gate).
- Task 9: `resolveLabelingQueueSource` 테스트 GREEN(+1) → env wrapper 전환.

## 4. 전체 테스트·build (최종)

- **Python: 684 passed** (`uv run pytest -q`; baseline 660 + migration contract 24).
- **Web: 481 passed** (`cd web && npm test`; baseline 374 + v3 107).
- **TypeScript: exit 0** (`npx tsc --noEmit`).
- `git diff --check`: clean · `git status`: clean.
- ⚠️ **프로덕션 빌드(`next build`)는 이 레포 hook(donts#9: 세션 내 리소스 경합 금지)으로 세션 내 실행 불가.** `tsc --noEmit` 통과를 in-session 타입 게이트로 대체했고, 실제 빌드는 **사용자 터미널**에서 실행해야 함(App Router 라우트는 파일 구조로 결정론적 등록: `app/labeling/motion/**` → `/labeling/motion**`). 계획 Task 7~10의 `npm run build`는 이 이유로 미실행.

## 5. shared_web_gate와 기본 전환 여부

- **Task 0 판정: `clear`.** local-vlm-evidence-web-gt 브랜치(당시 ahead-6 미푸시 포함)가 공용 web 파일(`web/src/app/labeling`, `labelingApi.ts`, `labelingV2.ts`)을 전혀 안 건드림.
- **Task 9 재확인(2단 게이트): `clear` 유지.** 재fetch 후 그쪽 worktree는 clean·origin 동기화 상태, 공용 파일(page.tsx, [clipId]/page.tsx, _labeling-forms.tsx, labelingApi.ts) 겹침 origin·local ref 둘 다 empty.
- 따라서 **기본 전환 수행** — `/labeling`을 env wrapper로 전환(코드 기본 `legacy`), legacy 큐 verbatim 이관 + `/labeling/legacy`, `.env.example`에 `LABELING_QUEUE_SOURCE=legacy` 추가(로컬/prod env 미변경). verdict는 `INTEGRATION_BLOCKED`가 아니라 아래 §9.

## 6. 금지동작 0 증거

- `rg` audit(계획 Task 10 Step 1): `web/src/app/api/labeling-v3`, `web/src/lib/labelingV3*`, migration에서 `camera_clips insert`/`behavior_labels`/`local_vlm_evidence`/`clip_python_evidence_runs`/`clip_prelabels`/`clip_activity_assessments` 실행 참조 **0건**. 매치는 전부 **테스트 negative assertion**(`.not.toContain('behavior_labels')` 등, 부재 증명)과 doc 코멘트 1건(`legacy(camera_clips)` 소스 라벨).
- v3 route DB 접근 테이블: `motion_clips`(read), `clip_vlm_jobs`(read, prediction snapshot — 설계 §9 허용), `cameras`(read), v3 4테이블(RPC 경유). mirror INSERT/UPDATE·자동 라벨 생성·Evidence GT mutation·VLM 실행 0.

**8차원 적대 리뷰 (계획 Task 10 Step 3):**
1. owner access가 `motion_clips.owner_id`로 스코프됨 — **PASS** (queue RPC/route에 `m.owner_id`/`p_owner_id` 없음, 정적 테스트로 고정).
2. labeler가 `owner_decision=label` 밖 접근 — **PASS** (queue/detail/media/gt-lock 전부 label+본인세션만, 그 외 404/PT403).
3. GT 잠금 전 prediction/evidence 누출 — **PASS** (mapMotionDetailRow가 gt_locked/completed에서만 prediction, 그 외 키 없음; queue 미노출).
4. cursor 마이크로초 절삭/중복·누락 — **PASS** (verbatim cursor 재사용, keyset+id tie-break, merge 마이크로초 보존).
5. skip/session 경합·stale — **PASS** (RPC row lock+PT409/PT410, detail이 state_updated_at 노출).
6. raw R2 key/DB 원문/secret 누출 — **PASS** ({url,expires_in}만·서명실패 502 일반화·매퍼 r2_key 제거·DB원문 미노출).
7. legacy tutorial/v2 회귀 — **PASS** (v2 파일 불변, `_labeling-forms.tsx`만 additive 콜백; page.tsx verbatim 이관; 전 스위트 GREEN).
8. `camera_clips` mirror/Evidence GT mutation — **PASS** (§6 audit 0건).

→ P0/P1 없음.

## 7. 미실행 (Stop Point 준수)

- production/preview **migration apply 0** (`migrations/2026-07-22_motion_clip_labeling_v3.sql`는 파일만 존재, DB 미적용).
- **Vercel deploy 0**, **main merge 0**, **local/production env 변경 0**, **production canary 0**, **대량 seed/worker 실행 0**.
- `other worktree`(local-vlm-evidence-web-gt) 수정·checkout·reset **0**.
- `next build` 미실행(§4 사유) — 사용자 터미널 몫.

## 8. 다음 deployment handoff의 Gate A~F (이 handoff는 미실행)

- **Gate A:** Codex 독립 diff 리뷰는 `bc5ba84..5d8ab2f` 후속까지 PASS. migration 실 DB 적대 probe는 Gate B에서 수행.
- **Gate B:** preview migration apply + rollback probe, residue 0.
- **Gate C:** preview owner/labeler E2E + 숨은 `/labeling/motion` 재생.
- **Gate D:** production schema/API 배포(기본 legacy 유지).
- **Gate E:** owner canary — 최신 clip·세 카메라·2번 캠 2026-07-21 16:30~17:30 41건·GT 1건 트랜잭션.
- **Gate F:** owner 명시 승인 후 `LABELING_QUEUE_SOURCE=motion` production redeploy(롤백=legacy).
- 새 tracked deployment plan + 새 HANDOFF_OK 만이 위 게이트를 실행한다.

## 9. Codex 독립 리뷰 후속 (2026-07-22)

Claude 구현 종료 뒤 Codex가 branch 전체를 독립 재검토해 세 경계 결함을 발견했고, `5d8ab2f`에서 TDD로 닫았다.

- 공개 `limit=100`이 RPC 100행 clamp와 충돌해 `has_more=false`가 되던 문제 → 공개 페이지 상한 99 + sentinel 1행으로 고정.
- GT 잠금 경합에서 `media_unavailable`과 `gt_already_locked`가 모두 `PT423`이던 문제 → media=`PT422`, locked=`PT423`으로 분리.
- 일반 라벨러 카메라 옵션이 media 없는 clip·본인 completed clip까지 포함하던 문제 → service-role-only distinct RPC로 실제 처리 가능 큐 조건을 DB에서 일치시킴.

재판정한 두 항목은 수정하지 않았다. `state_updated_at`은 Task 8에서 이미 상세 응답에 추가됐고, `PT403→404`는 일반 라벨러에게 clip 존재를 숨기는 설계 §10 보안 계약이다.

후속 검증: Python **687 passed**, Web **484 passed**, `npx tsc --noEmit` exit 0, `git diff --check` clean. `next build`는 donts#9 hook이 Codex 실행도 차단해 사용자 터미널 확인만 남았다.

## 10. 최종 verdict

**`V3_PREVIEW_READY_FOR_DEPLOY_REVIEW`**

- 코드/테스트: Python 687 · Web 484 · tsc 0 · git clean. Codex 독립 리뷰에서 발견한 실제 결함 3건은 `5d8ab2f`에서 수정했고, 금지동작 실행코드 0. shared_web_gate=clear로 기본 전환까지 포함(코드 기본 legacy).
- 미실행 운영 항목(§7)은 코드 결과와 분리해 명확히 보고. 실 빌드·migration apply·배포·canary는 배포 handoff Gate A~F 몫이며 이 handoff는 Stop Point에서 멈춘다.
- 잔여 확인: 사용자 터미널 `next build` 그린 확인. migration apply·실 DB 적대 probe는 별도 deployment handoff Gate B에서 수행.
