# 짧은 영상 장치 오류 격리·보존 Lab — 실행 보고서 (Task 1~3)

**작성일:** 2026-07-25
**실행 repo:** `/private/tmp/petcam-role-web-integrate-20260724`
**브랜치:** `codex/short-clip-retention` (새 branch/worktree 생성 없음, primary checkout 미변경)
**최종 판정:** `SHORT_CLIP_RETENTION_LAB_READY_FOR_RUNTIME_HANDOFF`

---

## 0. 시작 계약

핸드오프 validator 전문:

```
HANDOFF_OK task=short-clip-retention-lab repo=petcam-role-web-integrate-20260724 commit=14c32905 runtime=none
```

- 시작 시 `git status --short` = handoff 파일 하나만 untracked → 계약 충족(다른 변경 없음).
- 시작 HEAD = `14c32905f0c8dc49ff27d2b276083d12135705b9` (origin `codex/short-clip-retention` 과 동일).
- 읽은 순서: `AGENTS.md` → `CLAUDE.md` → `.claude/rules/donts.md` → design → plan → 이 handoff.
- 실제 실행 범위: 계획서 **Task 1~3만**. Mac mini worker / R2 삭제 / LaunchAgent / production apply·deploy 는 미착수(다음 handoff).

---

## 1. Task별 RED → GREEN 증거

### Task 1 — DB policy / exclusion ledger / append-only audit

- **RED**: `tests/test_short_clip_device_error_retention_migration.py` 작성 후 `uv run pytest -q` → **18 errors**(migration 파일 없음, `FileNotFoundError`).
- **구현**: `migrations/2026-07-24_short_clip_device_error_retention.sql` — helper `fn_valid_short_clip_seconds` + 4 테이블(`camera_short_clip_policies`, `motion_clip_system_exclusions`, `motion_clip_system_exclusion_events`(append-only), `short_clip_retention_notifications`) + RPC 10종.
- **GREEN**: 정적 계약 **18 passed**. 이후 Task 2 계약 6개 추가 → **24 passed**.
- **회귀**: `tests/test_motion_clip_labeling_v3_migration.py` 통과 유지.

### Task 2 — consumer guards + media-deleted read semantics

- **RED**: `test_task2_*` 6개 추가 → `-k task2` **6 failed**(가드 미구현).
- **구현**: 배포된 소비자 함수 6종을 같은 migration 파일에 forward-copy + 가드:
  - `fn_list_motion_clip_labeling_queue`(owner+labeler 큐) — eligible 제외 + `media_ready` 가드
  - `fn_ensure_motion_review_slots` — live slot 자재화 eligible 제외
  - `fn_list_motion_blind_queue` — `media_ready` 가드
  - `fn_manage_motion_blind_canary` — 요청 clip 격리/삭제 시 `PT428` 거부
  - `fn_claim_python_evidence_jobs` — claim 후보 서브쿼리 제외(queued job 미변경)
  - `fn_list_motion_labeling_library` — 라이브러리 base 제외
- **GREEN**: **24 passed**. 회귀(motion_v3 / double_blind / role_reads 정적) 유지.

### Task 3 — Owner-only automatic exclusion API + UI

- **RED**: 신규 route/list 테스트가 대상 모듈 부재로 실패.
- **구현**: 타입(`labelingV3.ts`), 매퍼·`isMotionMediaDeleted`·PT428 매핑(`labelingV3Server.ts`), client(`labelingV3Api.ts`),
  `GET /system-exclusions` + `POST /system-exclusions/:clipId/restore`, 세 signed-URL route 의 `media_deleted` 410,
  `/labeling/motion/auto-excluded` 페이지·리스트·큐 진입점.
- **GREEN**: 신규/변경 테스트 통과 → 전체 web **841 passed (84 files)**, `tsc --noEmit` clean.

---

## 2. 실제 DB probe (필수 적대 검증)

로컬 disposable **Homebrew PostgreSQL 15**(127.0.0.1:5432, `blind_probe_short_clip_<hex>` 일회용 DB)에서
`prerequisites → motion_v3 → double_blind → role_reads → short_clip_prereqs → 이 migration → probe SQL` 을 적용하고
`BEGIN … ROLLBACK` 안에서 실증. 러너: `scripts/run_short_clip_retention_probe.py`.

```
SHORT_CLIP_DETECT_OK
SHORT_CLIP_RESTORE_OK
SHORT_CLIP_DELETE_LEASE_OK
SHORT_CLIP_APPEND_ONLY_OK
SHORT_CLIP_NOTIFY_OK
SHORT_CLIP_CONSUMER_GUARD_OK
PROBE_RESIDUE=0
```

필수 시나리오 매핑(전부 통과):

| # | 시나리오 | 실증 마커 |
|---|---|---|
| 1 | 4/11 매칭 정책 → quarantined | DETECT |
| 2 | 12초·다른 카메라 → candidate | DETECT |
| 3 | 사람 session/slot/submission → 자동 격리 차단(deletion_blocked) | DETECT |
| 4 | 동일 감지 재실행 → 현재 row 1 + 전이 1(멱등) | DETECT |
| 5 | 복구 → triage label + system restored 원자성 | RESTORE |
| 6 | restored 동일 rule 재감지 → 재격리 0(`reused_restored`) | RESTORE |
| 7 | wrong/expired delete lease → complete 차단 | DELETE_LEASE |
| 8 | claim 31/blank host 거부, 보호/active job → claim 0 | DELETE_LEASE |
| 9 | queued Python Evidence/VLM job mutation 0 | DELETE_LEASE + CONSUMER_GUARD |
| 10 | event UPDATE/DELETE/TRUNCATE → `0A000` | APPEND_ONLY |
| 11 | probe rollback residue 0 | `PROBE_RESIDUE=0` |

추가 실증: media_deleted → 복구 `PT428`, 중복 complete false(이중 삭제 이벤트 0), 내구성 일일 Slack claim(전송 후 재claim NULL),
소비자 가드(queue/library 제외·`media_ready=false`·slot 자재화 제외·canary `PT428`·python evidence claim 제외 + queued job 불변·기존 세션 수 불변).

opt-in pytest live 실증(`SHORT_CLIP_PROBE_LIVE=1`)도 통과. 기본 `uv run pytest` 는 DB 미기동(순수 로직만).

---

## 3. 검증 명령 결과

| 명령 | 결과 |
|---|---|
| `uv run pytest -q tests/test_short_clip_device_error_retention_migration.py` | 24 passed |
| `uv run pytest -q tests/test_motion_clip_labeling_v3_migration.py` | passed |
| `uv run pytest -q` (전체) | **800 passed, 2 skipped**(skip = opt-in live probe 등) |
| `npm test` (web 전체) | **841 passed (84 files)** |
| `npx tsc --noEmit` | clean |
| `git diff --check` | clean |
| `scripts/run_short_clip_retention_probe.py` | 6 마커 + `PROBE_RESIDUE=0` |
| `npm run build` | **`BUILD_UNVERIFIED_SAFETY_HOOK`** — `~/.claude/hooks/dangerous-guard.sh`(donts#9)가 세션 내 실행을 차단. `tsc --noEmit` clean 을 build 성공으로 대체 주장하지 않음. 실제 build 는 owner 터미널 필요. |

---

## 4. 변경 파일 · Task별 commit SHA

- **Task 1** — `aac4991` `feat: 짧은 영상 장치 오류 격리·보존 DB 계약`
  - `migrations/2026-07-24_short_clip_device_error_retention.sql`(신규)
  - `tests/test_short_clip_device_error_retention_migration.py`(신규)
  - `tests/sql/short_clip_device_error_retention_probe.sql`(신규)
  - `tests/sql/short_clip_device_error_retention_prerequisites.sql`(신규, probe 전용 최소 외부 테이블)
  - `scripts/run_short_clip_retention_probe.py`(신규, probe 러너)
  - `tests/test_short_clip_retention_runtime_probe.py`(신규, 러너 안전계약 + opt-in live)
- **Task 2** — `69ed9e2` `feat: 자동 격리 영상의 신규 소비·재생 차단`
  - 위 migration/test/probe/러너에 소비자 가드 forward-append.
- **Task 3** — `600953c` `feat: Owner 자동 제외 검수·복구 화면`
  - `migrations/...retention.sql`(자동 제외 목록 RPC 에 keyset 커서 컬럼 추가)
  - `web/src/lib/labelingV3.ts` · `labelingV3Api.ts` · `labelingV3Server.ts`
  - `web/src/app/api/labeling-v3/system-exclusions/route.ts(.test.ts)`
  - `web/src/app/api/labeling-v3/system-exclusions/[clipId]/restore/route.ts(.test.ts)`
  - `web/src/app/api/labeling-v3/[clipId]|blind|library/file/url/route.ts(.test.ts)` — media_deleted 410
  - `web/src/app/labeling/motion/auto-excluded/page.tsx · _auto-excluded-list.tsx(.test.tsx)`
  - `web/src/app/labeling/_motion-queue.tsx` — Owner 전용 `자동 제외` 진입점

> 계획서 Task 1 명시 3파일 외에 probe 러너·prereqs·러너 테스트를 추가했다(실제 rollback probe 실행에 필수). Task 3 은 keyset 페이지네이션을 위해 미적용 migration 을 보강했다(production 미적용이라 handoff 허용 범위).

---

## 5. 보안 · raw-field 누출 감사

- migration 금지 statement 0: `DELETE FROM public.motion_clips` / labeling_sessions / review_slots / blind_submissions / consensus / behavior_* / `list_objects` / prefix·bucket delete **없음**.
- 클라이언트 정책·grant 0: `CREATE POLICY` 0, `GRANT … TO anon/authenticated` 0. 4 테이블 RLS ON + REVOKE, 함수 17개 모두 `REVOKE … FROM PUBLIC, anon, authenticated` + `GRANT EXECUTE … TO service_role`.
- signed URL: media_deleted 시 410 `media_deleted` + **signer 호출 0**(세 route 테스트가 `presignGet` 미호출 검증). unknown DB 오류는 일반화된 502.
- API 응답 raw 미노출: 자동 제외 목록 매퍼는 지정 필드만 통과. `r2_key` · lease token · worker host · fingerprint · actor UUID · `detected_at`/exclusion id 커서를 응답 item 에 담지 않음(커서는 opaque base64 로만). GET/restore 테스트가 leak 문자열 부재를 검증.
- 시스템 판정은 Owner `decided_by` 위조 안 함: 감지/삭제 event `actor_id = NULL`, `owner_labeled`/`decided_by` 는 오직 `fn_restore_short_clip_exclusion`(bearer Owner)만.

---

## 6. 기존 사람 / Canary / 151 frozen set / VLM / Evidence mutation 0 근거

- 이 migration 은 **production 미적용**(다음 handoff). 이번 세션의 모든 DB 실행은 **일회용 rollback DB** 안에서만 이뤄졌고 `PROBE_RESIDUE=0`.
- Task 2 forward-copy 는 기존 함수 본문을 그대로 두고 **`NOT EXISTS` 제외 술어만** 더했다 — 사람 GT / blind slot·submission / consensus / VLM result / Python Evidence result row 에 대한 UPDATE/DELETE 없음.
- probe `SHORT_CLIP_CONSUMER_GUARD_OK`: 격리 clip 의 queued python_evidence_jobs 는 `queued` 유지, 후보 clip job 만 claim, **기존 라벨링 세션 수 불변** 확인.
- 40건 baseline / 151 frozen set / camera policy 는 이번 세션에서 INSERT·enable 하지 않음(P4 Cam 2 정책 production INSERT 없음).

---

## 7. Git 동기화

- 브랜치 `codex/short-clip-retention`, upstream `origin/codex/short-clip-retention`.
- origin 시작점 `14c32905`. 이번 3 커밋: `aac4991` → `69ed9e2` → `600953c`.
- push 후 local HEAD = origin HEAD = `600953c…`(§9 참고). untracked = handoff 파일 하나(의도적으로 미커밋).

---

## 8. 미검증 항목 (out-of-scope / 불가)

- `npm run build`(safety hook 차단, `BUILD_UNVERIFIED_SAFETY_HOOK`) — owner 터미널에서 별도 실행 필요.
- production migration apply / Supabase advisor / main merge / Vercel preview·production.
- Mac mini 감지·삭제 worker, R2 GET/DELETE, LaunchAgent, Slack 실제 전송(다음 handoff Task 4~10).
- 실제 카메라 policy INSERT/enable, 40건·151 frozen set 상태 변경.
- 실제 브라우저에서 Owner 화면 렌더/복구 E2E(정적 markup + 단위 테스트로만 검증).

---

## 9. 다음 nightly handoff 가 소비할 RPC · 타입 계약

**service_role 전용 RPC (Task 4~5 worker/삭제):**

- `fn_list_short_clip_detection_candidates(p_candidate_under_sec double precision, p_cursor_started_at timestamptz, p_cursor_id uuid, p_limit integer)` → `(clip_id, camera_id, camera_name, started_at, duration_sec, displayed_duration_sec, current_state)`
- `fn_record_short_clip_detection(p_clip_id uuid, p_now timestamptz, p_write boolean)` → `(route, exclusion_id, resulting_state)` — route ∈ `candidate|quarantined|protected|reused|reused_restored|ineligible`. `p_write=false` = shadow(무쓰기). caller 는 clip UUID·now·write 만 넘긴다(정책·표시길이·camera 는 DB 재도출).
- `fn_claim_short_clip_media_deletions(p_limit integer[1..30], p_worker_host text, p_now timestamptz)` → `(exclusion_id, clip_id, r2_key, lease_token)` — 15분 lease. blank r2_key 미반환, 보호/active job 은 `deletion_blocked`.
- `fn_complete_short_clip_media_delete(p_exclusion_id uuid, p_lease_token uuid, p_result_fingerprint text, p_now timestamptz)` → boolean. quarantined + 자기 lease + 미만료일 때만 `media_deleted`.
- `fn_fail_short_clip_media_delete(p_exclusion_id uuid, p_lease_token uuid, p_result_code text, p_now timestamptz)` → boolean. **allowlist code**: `r2_delete_failed|audit_write_failed|worker_host_mismatch|internal_error`. fingerprint 는 DB 가 code 의 SHA-256 으로 파생. ⚠️ 계획서 Task 5 의 `fail_media_delete(code, fingerprint)` 2-인자 서명과 다름 — interface 목록의 4-인자 서명을 정본으로 채택(nightly 는 allowlist code 만 전달).
- `fn_claim/complete/release_short_clip_retention_notification(summary_date_kst date, …)` — KST 날짜당 내구성 1 카드. claim → (Slack) → complete(`sent_at`) / release(재시도). 전송 후 재claim = NULL.

**활성 job 판정 리터럴(worker 동결용):** `clip_vlm_jobs.status IN ('queued','submitted','failed_retryable')`, `python_evidence_jobs.status IN ('queued','processing','failed_retryable')`.

**web 소비 타입(Task 3 확정):** `SystemExclusionState`, `MotionSystemExclusionItem`(raw 미포함), `MotionSystemExclusionsResponse`. API: `GET /api/labeling-v3/system-exclusions`(opaque 커서), `POST /api/labeling-v3/system-exclusions/:clipId/restore`(reason 10~500).

**적용 순서(deployment):** 이 migration 은 아직 미적용. Phase A shadow(write=0) → Phase B P4 Cam 2 canary(정책 enable, 표시 4/11 만 quarantine) → Phase C 최대 30건 R2 삭제 canary. 각 단계 별도 owner 승인.

---

## 10. 최종 판정

**`SHORT_CLIP_RETENTION_LAB_READY_FOR_RUNTIME_HANDOFF`**

Task 1~3(DB 계약·소비자 가드·Owner API/UI)이 RED→GREEN + 로컬 PostgreSQL rollback probe(필수 적대 시나리오 전부 + residue 0) + 전체 pytest/web/tsc/diff-check 로 검증됨. 유일한 미검증은 safety-hook 로 차단된 `npm run build`(= `BUILD_UNVERIFIED_SAFETY_HOOK`, tsc clean 으로 대체 주장 안 함)와 명시적 out-of-scope 인 production apply·runtime 작업. 다음 handoff 는 §9 계약으로 Phase A shadow 부터 진행한다.
