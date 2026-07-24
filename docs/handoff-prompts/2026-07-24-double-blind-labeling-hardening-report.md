# 이중 블라인드 라벨링 하드닝 — 실행 보고서 (2026-07-24)

> **업데이트(2026-07-24 2차):** 최초 판정은 Docker daemon 부재로 `BLOCKED_DB_RUNTIME` 이었으나, owner 가 로컬 Homebrew PostgreSQL 15 로 blocker 를 해소했다. probe runner 에 local-postgres backend 를 TDD 로 추가해 **세 마커를 실제로 확보**했고, 판정을 `DOUBLE_BLIND_LABELING_HARDENED_READY_FOR_DB_PREVIEW` 로 정정한다. (아래 §3·§9)

## 0. Handoff 검증

```
HANDOFF_OK task=double-blind-labeling-hardening repo=double-blind-labeling-groups-design commit=a2dcb89b runtime=none
```

- validator: `uv run python scripts/verify_agent_handoff.py --manifest .../storage/handoffs/2026-07-24-double-blind-labeling-hardening-handoff.md`
- implementation_host: `BaekBook-Pro-14-M5` (일치), runtime_kind: `none`
- execution_repo: `/Users/baek/petcam-lab/.worktrees/double-blind-labeling-groups-design` (별도 worktree — main 트리의 다른 세션과 격리)
- 기준 구현 HEAD `7556009da15d919c5ecbdea8a6983d711bf09d24` 는 HEAD 의 ancestor (exit 0). 기존 push 커밋 amend/rebase/force-push 없음 — 하드닝은 새 커밋으로만 추가.

## 1. Task별 커밋

| Task | 커밋 | 내용 |
|---|---|---|
| 0 | (커밋 없음) | Handoff gate + baseline (Python 731 / web 705 / tsc 0) |
| 1 | `4afb091` | SQL slot 잠금 오류 제거 + live clip ownership 고정 |
| 2 | `846021f` | 이중 제출 경합 직렬화 + 합의 identity 검증 |
| 3 | `69eebb0` | 블라인드 GT 를 실제 영상 길이로 검증 |
| 4 | `8f3e9f3` | 블라인드 라벨 입력 임시 저장·복원 |
| 5 | `c508970` | canary 자격 + 활동일 입력 검증 강화 |
| 6 | `c2daf4b` | 이중 블라인드 DB 동시성 실증 (아티팩트) |
| 7 | `0bd508e` | 전체 검증·감사·리포트 (1차, BLOCKED) |
| 7b | (본 커밋) | local-postgres backend TDD 추가 + 세 마커 실측 → READY 정정 |

## 2. 발견 → 정확한 수정 매핑

| 등급 | 발견 | 수정 | 커밋 |
|---|---|---|---|
| P0 | `fn_ensure_motion_review_slots` 가 aggregate 문장에 `FOR UPDATE` 를 붙여 **Postgres 런타임 오류**(FOR UPDATE is not allowed with aggregate functions) → 함수가 아예 못 돎 | 멤버 행 잠금(`PERFORM 1 ... ORDER BY user_id FOR UPDATE`)과 집계(`array_agg`)를 별도 문장으로 분리 | `4afb091` |
| P0 | live clip ownership 미고정 — 카메라/멤버 교체 시 clip×members CROSS JOIN 이 **세 번째 slot** 삽입 가능 | consensus row 를 ownership anchor 로 최초 그룹 고정. per-clip 상태머신(slot 0→2인 삽입 / 2→보존 / 그 외 `PT425`), 다른 그룹 소유 clip 은 skip. slot 교체는 `fn_reassign_motion_review_slot` 단일 경로 | `4afb091` |
| P0 | 동시 제출 유실 — 두 reviewer 가 공유 잠금 없이 제출해 **둘 다 peer 없음**으로 관측 가능 | `fn_submit_motion_blind_review` 가 공유 `motion_clip_consensus` row 를 slot 보다 먼저 `FOR UPDATE`. 둘째 트랜잭션은 첫째 커밋을 반드시 관측(peer_present=true). slot/consensus 그룹 일치 검증 | `846021f` |
| P1 | finalize 가 **교차 객체 pair**(다른 clip/group/cohort, 같은 reviewer)를 그대로 수용 | fail-closed identity 검증(22023): `v_a.clip_id/v_b.clip_id = p_clip_id`, `v_a.group_id = v_b.group_id = consensus.group_id`, 서로 다른 reviewer, 두 제출 cohort 일치. agreed/conflict payload shape 검증 | `846021f` |
| P1 | 멱등 finalize 재시도가 **매번 `auto_compared` event 추가** | `v_did_transition` — awaiting→판정 전이일 때만 event insert. 이미 판정된 행은 그대로 반환, event 미추가 | `846021f` |
| P0 | 라벨러/owner GT segment 를 관대한 `GT_DURATION_CAP=3600` 로만 검증 → **영상 길이 초과 GT 저장** | `GT_DURATION_CAP` 제거. `getAssignedBlindClip`(slot 인가 뒤 실제 duration) 으로 검증, 미배정=404 `not_assigned` 존재 은닉. owner resolve 는 `getOwnerClipDuration` 으로 실제 길이 검증 | `69eebb0` |
| P1 | 브라우저 draft **유실**(미사용 raw `draftKey` + `localStorage.removeItem` 만 있고 write/restore 없음) + 비밀 누출 위험 | `motionBlindDraft.ts` — user·clip·cohort·comparator version 격리 봉투, shape+segment-duration 검증, fail-soft. lease token·상대 제출·VLM·evidence·r2_key **미저장**. detail 에 실제 duration 로드 뒤 restore, 미제출 중 debounce 저장, 성공 시 같은 scope 만 clear | `8f3e9f3` |
| P1 | canary reviewer 자격을 **승인 application 만** 확인(labelers 소속·그룹 멤버십 미확인) | `labelers` 존재 + 승인 application + `p_group_id` 현재 active member(`ended_at IS NULL`) 3중 EXISTS, `PT425` | `c508970` |
| P1 | `isValidActivityDay` 가 정규식만 검사 → `2026-02-30`·`2026-04-31`·`2026-13-01` 통과 | 정규식 뒤 UTC 성분 round-trip 로 실제 달력 날짜 검증. 존재 않는 날짜는 DB 접근 전 400 | `c508970` |
| P0(검증) | 정적 문자열 테스트만으로 SQL 정상 동작을 주장 | disposable postgres:15 러너(docker/local backend) + prerequisites + rollback probe + 단위 테스트. **실제 PostgreSQL 15 에서 세 마커 실측 완료**(§3) | `c2daf4b` + 7b |

## 3. 실제 DB 런타임/동시성 마커 — ✅ 확보

owner 로컬 Homebrew PostgreSQL 15(127.0.0.1:5432)에서 무작위 `blind_probe_*` 임시 DB 를 만들어 실증했다.

```
$ uv run python scripts/run_motion_double_blind_concurrency_probe.py --backend local \
    --pg-bin /opt/homebrew/opt/postgresql@15/bin \
    --migration migrations/2026-07-23_motion_double_blind_labeling.sql \
    --prerequisites tests/sql/motion_double_blind_prerequisites.sql \
    --probe tests/sql/motion_double_blind_hardening_probe.sql
DB_RUNTIME_PROBE_OK
DB_CONCURRENCY_PROBE_OK
PROBE_RESIDUE=0
(exit 0)
```

- **3회 연속 동일**(안정), flaky 없음.
- `DB_RUNTIME_PROBE_OK`: `hardening_probe.sql` 14개 assertion 이 실제 Postgres 15 에서 전부 통과 — aggregate 실행(FOR UPDATE 오류 없음)·ownership freeze(멤버 교체·카메라 재배정에도 세 번째 slot 0)·cross-clip/group/cohort/same-reviewer finalize 22023·agreed/conflict payload shape 22023·유효 finalize 후 `auto_compared` event 1·동일 재시도에도 1·canary 자격(labelers 미소속·group 외부 reviewer 거부, 유효 pair 성공). 전량 ROLLBACK.
- `DB_CONCURRENCY_PROBE_OK`: 두 psql 세션을 **실제 동시**로 열어(A 가 consensus 잠금 확보+`pg_sleep` 유지, B 는 커밋까지 대기) 같은 clip 제출 → 두 immutable 제출 보존, `peer_present` 다중집합 `{false, true}`, finalize 후 event 1.
- `PROBE_RESIDUE=0`: rollback probe 뒤 합성 row 0.

**안전 계약 준수(전량 확인):** ①무작위 `blind_probe_*` 임시 DB 만 createdb ②DB 이름 `blind_probe_<hex>` prefix 검증(`validate_temp_database_name`, create·drop 양쪽) ③prerequisites→migration→rollback probe→동시성 probe ④finally 에서 그 임시 DB 만 dropdb ⑤기존 DB(`my_first_api`/`postgres`/`template*`) 무손상 확인 ⑥127.0.0.1 외 접속 금지(`validate_database_url`+host 검증) ⑦Docker backend(`DockerBackend`)는 그대로 보존 ⑧production migration/main merge/deploy/group mapping/canary 0. 추가로 migration 의 REVOKE/GRANT 대상 전역 role(anon/authenticated/service_role)은 사전 존재분을 제외하고 **probe 가 만든 것만** finally 에서 self-clean — 실행 후 임시 DB·role 모두 잔여 0 확인.

> 러너 수정 2건(이 과정에서 실측으로 발견·수정): (a) `_run_concurrency_race` 가 `communicate()` 로 순차 전송되던 것을 stdin write+close(staggered)로 **진짜 동시성**으로 교정 — 그전엔 lock serialization 을 검증하지 못했다. (b) 제출 SRF 를 `FROM fn(...)` 로 호출해 정확히 한 번 평가.

## 4. 전체 테스트/빌드 결과

| 항목 | 결과 |
|---|---|
| `uv run pytest -q` | **748 passed** (baseline 731 → +17: migration 정적 +8, runtime 러너 단위 +9) |
| `cd web && npm test` (vitest) | **723 passed** (baseline 705 → +18) |
| `cd web && npx tsc --noEmit` | **exit 0** |
| `git diff --check` | clean |
| DB runtime/concurrency probe (local Homebrew PG15) | **DB_RUNTIME_PROBE_OK · DB_CONCURRENCY_PROBE_OK · PROBE_RESIDUE=0** (§3) |
| `cd web && npm run build` | **UNVERIFIED** — repository safety hook(`dangerous-guard.sh`, donts#9)이 세션 내 `npm run build` 차단. tsc 를 빌드 증거로 대체하지 않음. owner 터미널/Vercel preview 에서 별도 확인(계획 Step 2 계약대로 owner-unverified 허용) |

러너 단위 테스트: `tests/test_motion_double_blind_runtime_probe.py` 9 passed — `validate_database_url`(운영 DB 접속 차단)·`parse_probe_rows`(peer_present {f,t})·`temp_database_name`/`validate_temp_database_name`(임시 DB prefix 안전) 순수 로직.

## 5. 블라인드 누출·비밀 정적 감사

- `rg "peer_(decision|initial_gt|note|digest)|lease_token|r2_key|evidence|vlm" web/src/app/api/labeling-v3/blind web/src/lib/motionBlindDraft.ts`
  - `motionBlindDraft.ts`: **0 매치** — draft 봉투에 상대 제출·lease·r2_key·vlm·evidence 없음.
  - submit 라우트의 `peer_*`·`lease_token`: **서버 내부 RPC row/입력 토큰** 뿐. 브라우저 응답은 `{ status, differing_fields }` 로 고정(상대 원문 0).
  - `_access.ts` 의 `r2_key`: 기존 `loadBlindSlotAccess`(detail/media)에서 `media_ready` boolean 산출용, 응답 미포함. 신규 `getAssignedBlindClip`(id,duration_sec)·`getOwnerClipDuration`(duration_sec)은 r2_key 미조회.
  - 그 외 매치는 전부 "누출 안 됨"을 검증하는 테스트 assertion.
- `rg "@...(com|net|kr)|SUPABASE_SERVICE_ROLE|R2_SECRET|BEGIN (RSA|OPENSSH) PRIVATE" migrations/... tests/sql scripts/run_...py`: **NO_MATCHES** (이메일·서비스키·개인키 없음). prerequisites·probe 는 합성 schema/row 만(production row/secret 미복사).
- `git diff --name-only 7556009..HEAD | rg '\.(mp4|mov|avi|mkv|jpg|jpeg|png)$'`: **NO_MEDIA** (새 tracked 미디어 없음).

## 6. 변경 파일

DB 계약: `migrations/2026-07-23_motion_double_blind_labeling.sql`, `tests/test_motion_double_blind_labeling_migration.py`, `tests/sql/motion_double_blind_prerequisites.sql`(신규), `tests/sql/motion_double_blind_hardening_probe.sql`(신규), `scripts/run_motion_double_blind_concurrency_probe.py`(신규, docker+local backend), `tests/test_motion_double_blind_runtime_probe.py`(신규).

Server/API: `web/src/app/api/labeling-v3/blind/_access.ts`, `.../[clipId]/submit/route.ts(.test.ts)`, `.../owner/[clipId]/resolve/route.ts(.test.ts)`, `.../queue/route.test.ts`, `web/src/lib/motionBlindReviewServer.ts(.test.ts)`.

Draft: `web/src/lib/motionBlindDraft.ts`(신규), `web/src/lib/motionBlindDraft.test.ts`(신규), `web/src/app/labeling/_blind-review-detail.tsx`, `web/src/app/labeling/_blind-hardening.test.ts`.

문서: `docs/DATABASE.md`, `docs/FEATURES.md`, `specs/next-session.md`, `.claude/donts-audit.md`, 본 리포트. 하드닝 범위 밖 리팩토링/기능 확장 없음(owner v3·legacy v2·tutorial·VLM·Gate·Python Evidence·activity 계산·UI copy/selection 불변).

## 7. 미검증 항목 (known unverified)

1. **production build** — repository safety hook(`dangerous-guard.sh`, donts#9)이 세션 내 `npm run build` 를 차단. tsc(exit 0)로 타입은 통과했으나 빌드는 owner 터미널/Vercel preview 확인 필요(계획 Step 2 가 허용하는 owner-unverified). 그 외 항목은 없음 — DB 런타임/동시성은 §3 에서 실측 완료.

## 8. 명시적 non-actions (범위 밖 · 미수행)

- production migration apply **안 함** (production applied = false)
- main merge **안 함** (main merged = false)
- Vercel production deploy **안 함**
- 실제 사용자·그룹 mapping **안 함** (real groups mapped = false)
- canary 생성 **안 함**
- Owner Pilot 151 dataset manifest 생성 **안 함**
- 기존 push 커밋 amend/rebase/force-push **안 함**
- OrbStack/Docker **미조작**(owner 지시대로) — 실증은 local Homebrew PostgreSQL 임시 DB 로만

## 9. 최종 판정

```
DOUBLE_BLIND_LABELING_HARDENED_READY_FOR_DB_PREVIEW
```

정적 SQL 회귀·API/draft 단위 테스트·러너 단위 테스트가 모두 통과했고, **disposable PostgreSQL 15 에서 rollback runtime probe·동시성 probe·잔여물 검사 세 마커를 실제로 확보**했다(§3). 유일한 owner-unverified 항목은 repository safety hook 이 세션 내 실행을 막은 production build 뿐이다(계획이 허용하는 경계).

**다음 게이트:** Codex 하드닝 diff + disposable DB evidence 리뷰 → 별도 preview deployment handoff(safe DB 에 migration 적용 + owner 승인 12-clip 격리 canary) → 수용 후에만 main/production 통합 → Owner Pilot 151 frozen manifest. 이 문서를 Stop Point 로 정지한다.

---

## 10. Codex 독립 리뷰 P1 3건 반영 (2026-07-24 3차, additive)

Codex 독립 리뷰가 P1 3건을 지적해 TDD(RED→GREEN)로 최소 수정했다. production 적용은 계속 금지(migration apply/main merge/deploy/group mapping/canary 0). 판정은 `DOUBLE_BLIND_LABELING_HARDENED_READY_FOR_DB_PREVIEW` 유지 — 수정 후 세 마커를 **재확보**했다.

| # | 지적 | 수정 |
|---|---|---|
| P1-1 | `fn_finalize` 가 submission 의 denormalize 필드만 검사하고 **참조 slot 의 identity 는 미검증** — slot_id 가 다른 reviewer/clip 의 slot 을 가리키는 위조 제출이 통과 가능 | 공통 잠금 순서를 `consensus → slots(id asc) → submissions(id asc)` 로 확장. 두 제출의 slot 을 잠금·재조회해 slot 의 clip_id/group_id/reviewer_id/cohort_kind/cohort_id 가 **해당 submission 및 consensus identity 와 정확히 일치**하지 않으면 22023. rollback probe 에 forged slot mismatch(denormalize=clip1/B 지만 slot=clip2/B) 실 DB assertion 추가 |
| P1-2 | `fn_ensure` 가 reviewer **자기 membership 을 먼저 FOR UPDATE** 한 뒤 전체 멤버를 잠가, 두 reviewer 가 서로 다른 첫 행을 잡고 공유 멤버셋을 반대로 원하면 **deadlock** | reviewer 자기 membership 선잠금 제거(group_id 만 비-lock read). 모든 호출이 **공유 멤버셋(전체 멤버, user_id 순)부터 동일 순서로** 잠그게 통일. 두 reviewer 동시 ensure → deadlock 없이 완료 + live slot 정확히 2 를 실 DB 동시성 probe 로 증명 |
| P1-3 | local probe runner 가 **기존 role 조회 실패를 빈 집합으로 처리** → 전부 "probe 생성"으로 오분류돼 기존 role 삭제 위험. dropdb·role cleanup returncode 미검사 | `_existing_blind_roles` 조회 실패 시 `role_query_failed` 로 **fail-closed**(조회 못 하면 아무 role 도 정리 안 함). dropdb·role cleanup returncode 검사 후 실패 시 nonzero/`cleanup_failed` fail-closed. 순수 `roles_to_cleanup` 로 분리해 **기존 role 은 어떤 경로에서도 삭제 대상 미분류**를 단위 테스트로 고정 |

**커밋:** (본 3차 커밋). 기준 구현 HEAD `7556009` 이후 새 커밋만 추가(기존 push 커밋 amend/rebase 없음).

**재확보 결과** (owner 로컬 Homebrew PostgreSQL 15 임시 DB, 4회 안정, 무흔적):
```
DB_RUNTIME_PROBE_OK        # 14+1(forged slot) assertion 전량 통과
DB_CONCURRENCY_PROBE_OK    # ensure 동시성(deadlock 없음·2 slot) + submit 경합({f,t}·event 1) 둘 다
PROBE_RESIDUE=0
```

**테스트:** pytest **754**(748→+6: finalize slot·ensure lock 정적 +2, forged marker +0[기존 test 강화], runner role fail-closed 단위 +4) · web **723** · tsc **0** · `git diff --check` clean · 실행 후 임시 DB·role 잔여 0. `npm run build` 는 여전히 dangerous-guard(donts#9) 차단 → **owner-unverified**(정직 표기 유지).

**non-actions(불변):** production migration apply·main merge·Vercel deploy·실제 group mapping·canary 생성·Owner Pilot 151 manifest = 전부 미수행. OrbStack/Docker 미조작.
