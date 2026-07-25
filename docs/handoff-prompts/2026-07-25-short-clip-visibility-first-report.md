# 짧은 오류 영상 visibility-first — 구현·검증 보고서

- **설계 정본:** `docs/superpowers/specs/2026-07-25-short-clip-visibility-first-design.md`
- **구현 계획:** `docs/superpowers/plans/2026-07-25-short-clip-visibility-first.md`
- **실행 worktree:** `/Users/baek/petcam-lab/.worktrees/short-clip-visibility` (branch `codex/short-clip-visibility`)
- **handoff base commit:** `d9909906a385c1598b4c55473431883721d24d4c`
- **작성 시점 판정:** `SHORT_CLIP_VISIBILITY_FIRST_READY_FOR_DEPLOY` (Task 1~5 완료, Task 6 배포는 아래 "미검증 운영 항목")

## 0. 시작 계약

- branch=`codex/short-clip-visibility`, HEAD==`d9909906`, plan/design tracked·clean 확인.
- validator 전문:
  `HANDOFF_OK task=short-clip-visibility-first repo=short-clip-visibility commit=d9909906 runtime=launchagent@baeg-endeuui-Macmini.local`
- Lab `AGENTS.md` / `CLAUDE.md` / `.claude/rules/donts.md` / design / plan 정독.

## 1. 한 줄 요약

짧은 장치 오류 clip 을 R2 에서 지우지 않고, 시스템 원장(`motion_clip_system_exclusions`)을 단일 SOT
로 삼아 앱·라벨링 웹·backend media 발급에서만 숨긴다. "자동 제외 해제"는 시스템 격리만 되돌리고
사람 판정(triage skip/label)은 절대 바꾸지 않는다. 물리 삭제는 운영 범위 밖(`DELETE_ENABLED=0` 정본).

## 2. Task 별 RED → GREEN

### Task 1 — forward migration (restore·app RLS 경계) `5423a12`
- **RED:** `tests/test_short_clip_visibility_first_migration.py` (migration 파일 부재로 8 error).
- **GREEN:** `migrations/2026-07-25_short_clip_visibility_first.sql` 추가 후 8 passed.
- 계약: 복구 RPC 는 `motion_clip_labeling_triage`/`_events`/`owner_decision` 을 문자열 단위로 미참조,
  helper `fn_motion_clip_visible_to_owner` 는 `state IN ('quarantined','media_deleted')` 만 숨김 +
  `ALTER POLICY "own clips select"`, 물리 delete statement 신규 0. forward CREATE OR REPLACE 만(DROP/CREATE TABLE 0).

### Task 2 — 실제 PostgreSQL rollback probe `03a4b5e`
- **RED:** runner import 실패(`ModuleNotFoundError`) → runner 단위테스트 5 error.
- **GREEN:** prereqs/probe SQL + `scripts/run_short_clip_visibility_first_probe.py` + 단위테스트 5 passed(+1 skip).
- **실제 PG15 3회 실측 마커:**
  ```
  RESTORE_TRIAGE_IMMUTABLE_OK
  APP_RLS_VISIBILITY_OK
  PROBE_RESIDUE=0
  ```
  (일회용 `short_visibility_probe_<hex>` DB, BEGIN…ROLLBACK, 3회 재현 동일)
- probe 시나리오: skip/label triage md5 pre==post, no-triage→no-triage, quarantined→restored+owner_restored 1건·triage_event 0,
  active lease→PT409+fingerprint 불변, authenticated Owner 는 quarantined/media_deleted 0·restored/candidate visible,
  다른 Owner 0, service_role 전량 read.

### Task 3 — backend signed URL fail-closed guard `b164397`
- **RED:** `pytest -k "system_exclusion or signed_url"` 6 failed (guard 미구현, signer 통과).
- **GREEN:** `ensure_clip_media_visible` (`backend/clip_perms.py`) + 4개 엔드포인트 삽입 → focused 8 passed, 전체 clips 58 passed.
- 계약: quarantined→404(존재 숨김), media_deleted→410, 없음/restored→정상 발급, DB 조회 실패→502.
  차단 케이스 전부 **signer 호출 0회**(counting fake 로 검증). guard 응답에 exclusion UUID·rule·actor·R2 key 원문 미포함.
- 삽입 지점: `get_clip_file`·`get_clip_file_url`·`get_clip_thumbnail_url`·`get_clip_thumbnail`
  (모두 `load_clip_with_perms` 직후, signed URL 생성 전). 총 4곳(정확히 4).

### Task 4 — Owner 웹 문구 "시스템 해제" 교정 `478394f`
- **RED:** `_auto-excluded-list.test.tsx` 2 failed (컴포넌트가 옛 문구 `라벨 대상으로 복구`).
- **GREEN:** 버튼 `자동 제외만 해제` + 카드 안내(`기존 사람 판정은 유지돼.` / `라벨 대상으로 바꾸려면 영상 상세에서 별도로 변경해.`)
  + 성공 notice(`자동 제외를 해제했어. 기존 사람 판정은 유지돼.`) → 해당 파일 7 passed.
- API 시그니처(`restoreMotionSystemExclusion(clipId, reason)`)·엔드포인트·payload shape 유지. tsc 0.

## 3. 전체 회귀 (Task 5)

- backend: `uv run pytest -q` → **828 passed, 3 skipped**.
- web: `npm test` → **841 passed (84 files)**, `npx tsc --noEmit` → 0.
- `git diff --check d9909906..HEAD` → clean.

## 4. 금지동작 감사 (added-line 기준)

| 항목 | 결과 |
|---|---|
| R2 delete code 신규 | **0** |
| `SHORT_CLIP_RETENTION_DELETE_ENABLED=1` 신규 | **0** |
| restore 함수 내 triage write | **0** (정적 계약 + PG probe `RESTORE_TRIAGE_IMMUTABLE_OK`) |
| Flutter 변경 | **0** (`.dart` 0) |
| raw key/token/UUID 응답 | guard 는 상태만 status code 로 변환, DB 원문 미포함 |
| delete lease/claim RPC·DELETE policy | 미참조(migration 정적 계약으로 고정) |

## 5. 변경 파일 (`d9909906..HEAD`, 4 커밋)

```
backend/clip_perms.py                                 (+46)  ensure_clip_media_visible
backend/routers/clips.py                              (+/-)  4개 media 엔드포인트 guard 호출
migrations/2026-07-25_short_clip_visibility_first.sql (+134) helper + policy + restore 교체
scripts/run_short_clip_visibility_first_probe.py      (+227) 로컬 PG probe 러너
tests/sql/short_clip_visibility_first_prerequisites.sql (+56)
tests/sql/short_clip_visibility_first_probe.sql       (+211)
tests/test_clips_api.py                               (+161) guard 8 테스트
tests/test_short_clip_visibility_first_migration.py   (+120) 정적 계약 8
tests/test_short_clip_visibility_first_runtime_probe.py (+77) runner 단위 6
web/.../auto-excluded/_auto-excluded-list.tsx         (+/-)  문구/notice
web/.../auto-excluded/_auto-excluded-list.test.tsx    (+/-)  RED 문구 테스트
web/src/lib/labelingV3Api.ts                          (+/-)  주석 정정(시그니처 유지)
```

## 6. 미검증 운영 항목 (Task 6 배포에서 채운다)

아래는 production 접속·SSH 가 필요해 이 로컬 단계에서는 미실행이다. Task 6 에서 실측 후 이 보고서에 append 한다.

- production 사람 triage/session/GT/consensus + 기존 40 quarantined pre/post fingerprint 동치
- production forward migration apply(07-25 만) + 합성 transaction rollback probe
- Vercel production + Fly API `/health` 배포·smoke + deployment ID/commit
- 앱 Owner JWT direct list/single/activity view 격리 0 vs 웹 자동 제외 40 노출
- signed URL signer quarantined 0회 (production)
- Mac mini hostname/HEAD/plist flags(`1/1/0`)/exit code
- 1회 kickstart + 자연 hourly cycle 결과
- R2 delete/claim/lease 0

## 7. 절대 경계 준수 확인

- `SHORT_CLIP_RETENTION_DELETE_ENABLED=0` 유지(신규 1 설정 0).
- 기존 40 quarantined·823 exclusion·824 event 미참조/미수정.
- 사람 GT·triage·session·blind·behavior·activity·VLM/Python Evidence 결과 미변경.
- 다른 카메라·표시 4/11초 외 clip 자동 격리 로직 미추가(감지 RPC 불변).
- Flutter repo·다른 세션 primary checkout·untracked 파일 미접촉.

## 8. Task 6 — production 배포 실측 (2026-07-25)

배포 게이트: Fly 미인증 발견 → owner 가 `flyctl auth login`(terraaidev@gmail.com) 후 전체 배포 진행.

### 8.1 배포 전 production 재확인 (read-only)
handoff 숫자와 정확히 일치: exclusions **823**, events **824**, quarantined **40**(전부 표시 4/11·카메라 1개 P4 Cam2 dev·사람 triage **skip 40/40**), active_lease **0**, delete_claimed/completed **0**. `own clips select` policy·`motion_clips.owner_id`·`auth.uid()`·restore fn 존재, helper 미존재 확인.

### 8.2 FF-only main 통합
`origin/main` `926e5f6..72aa56d` fast-forward(force 아님). 통합 후 origin/main=`72aa56d`.

### 8.3 production migration apply + 지문 대조
Supabase `apply_migration`(BEGIN/COMMIT 제외 DDL) `{"success":true}`.
- **데이터 지문 7개 전부 pre==post byte-identical**: triage `f9845e76…`, triage_events `0639afad…`, sessions `400a7527…`, consensus `e2bce247…`, blind_submissions `949fff16…`, exclusions `b7aaf910…`, exclusion_events `270268fb…` → 사람 판정·시스템 원장 **무변경**.
- DDL 변경(의도): policy USING `(auth.uid() = owner_id)` → `fn_motion_clip_visible_to_owner(id, owner_id)`; helper 생성; restore fn md5 `ae5fe9af…`→`c3388069…`. 원장 823/824/40/40skip/lease0 불변.

### 8.4 production 합성 rollback probe
합성 fixture(실제 user id 재사용, 실 사람 clip 미사용)로 배포된 restore RPC + helper 실측 후 마지막 `RAISE`로 전량 롤백 → `ERROR: P0001: PROBE_ROLLBACK_OK`(모든 ASSERT 통과: skip triage md5 pre==post·restored·owner_restored 1·triage_event 0·helper quarantined→false/restored→true/other-owner→false). 롤백 후 **잔여 0**(probe camera/clip 0), 지문 불변.

### 8.5 security advisor
신규 ERROR/critical **0**. 신규 WARN 1건 = `fn_motion_clip_visible_to_owner` authenticated SECURITY DEFINER RPC 노출 — **의도된 trade-off**(RLS USING 식이 authenticated 역할로 helper 실행 → EXECUTE 필수). 직접 호출해도 boolean만·자기 auth.uid()일 때만 true·raw/타유저 데이터 미노출 = RLS row 누출 아님. 기존 `handle_new_user`와 동급.

### 8.6 Vercel + Fly 배포
- **Fly**: `flyctl deploy --config fly.api.toml` → release **v2 complete**(terraaidev@gmail.com). `https://api.tera-ai.uk/health` **200** `{"status":"ok"}`, `petcam-api.fly.dev/health` 200. (배포 중 "not listening" 경고는 rolling deploy 일시적, health 통과.)
- **Vercel**: git 자동배포 미발생(최신 production githubCommitSha 없음) → 명시 `vercel --prod`(rootDirectory=web) 배포 **READY**, deployment `dpl_5XyQsX9BG6BDjP1oJ4mmweZx4jpb`, **label.tera-ai.uk aliased**. HTTP 307(auth redirect, 정상).

### 8.7 app/web read-only smoke
- **앱 motion_clips RLS 재현**(40 quarantined owner 로 authenticated): 격리 clip 가시성 `list=0`·`activity(v_clip_effective_activity)=0`, owner 나머지 **17666** 정상 노출.
- **web 소비 경로**(service_role RPC): 자동 제외 화면 `quarantined_shown=40`(total 40), 기본 라벨링 큐 `quarantined_in_default_queue=0`.
- **backend**: `/clips` unauth **401**, `/clips/{id}/file` unauth **401·redirect 없음**(signer 미발급). authenticated-quarantined signer 0회는 배포된 코드(Fly v2=테스트 코드)+8 unit(signer 카운트 0)+production helper probe+40 quarantined 상태로 검증(live 인증 HTTP 는 Owner JWT 부재로 미실행 — 대체 검증).

### 8.8 Mac mini write enable (`1/1/0`) + kickstart
`ssh home-mac`(hostname `baeg-endeuui-Macmini.local` = runtime_host). worker=petcam-nightly-reporter(HEAD `75819399`=nightly origin/main, main clean) `reporter.short_clip_retention_worker`, LaunchAgent `com.petcam.short-clip-retention`.
`install-launchd-short-clip-retention.sh`(EXPECTED_HOST=baeg-endeuui-Macmini.local 정확 전달=우회 아님, host 가드 통과) → plist **ENABLED=1/WRITE_ENABLED=1/DELETE_ENABLED=0**, lint+bootstrap.
- kickstart(RunAtLoad) **last exit code 0**, 로그 `candidate=0 quarantined=0 reused=783 failed=0 write_enabled=1`(멱등 replay, 새 격리 0).
- DB 수용조건: human triage fingerprint pre==post(`f9845e76`), off-target quarantine **0**(표시 4/11 외 0·카메라 1개), R2 delete/claim/lease **0**, temporary media 0, 원장 823/824/40/40skip 불변.

### 8.9 남은 항목 — 자연 hourly cycle
StartInterval 3600 → 다음 자연 cycle은 kickstart 후 ~1시간. **미검증(대기)**. 이 cycle 이 exit 0·멱등·off-target 0·human fingerprint 불변으로 확인되면 최종 `DEPLOYED_VERIFIED`.

## 9. 판정

Task 1~5 + Task 6 배포(8.1~8.8) 통과. 자연 hourly cycle(8.9) 1회 검증만 남음.

```
SHORT_CLIP_VISIBILITY_FIRST_DEPLOYED — NATURAL_HOURLY_CYCLE_PENDING
PHYSICAL_DELETE=DISABLED / OUT_OF_SCOPE
```

(자연 cycle 검증 완료 시 `SHORT_CLIP_VISIBILITY_FIRST_DEPLOYED_VERIFIED` 로 승격.)

---
_이전 판정(Task 5 시점): `SHORT_CLIP_VISIBILITY_FIRST_READY_FOR_DEPLOY`._
