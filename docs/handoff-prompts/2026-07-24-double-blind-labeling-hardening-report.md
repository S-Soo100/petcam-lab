# 이중 블라인드 라벨링 하드닝 — 실행 보고서 (2026-07-24)

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
| 7 | (본 문서 커밋) | 전체 검증·감사·리포트 |

브랜치 HEAD: `c2daf4b` → (Task 7 문서 커밋 후 갱신).

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
| P0(검증공백) | 정적 문자열 테스트만으로 SQL 정상 동작을 주장 | disposable postgres:15 러너 + prerequisites + rollback probe + 단위 테스트. **런타임 실증은 BLOCKED**(아래 §3) | `c2daf4b` |

## 3. 실제 DB 런타임/동시성 마커 — ⛔ BLOCKED

disposable PostgreSQL 실증을 **이 세션에서 실행할 수 없다.** 정적/단위 테스트만으로 READY 를 주장하지 않는다.

```
DB_RUNTIME_PROBE_OK       : NOT OBTAINED
DB_CONCURRENCY_PROBE_OK   : NOT OBTAINED
PROBE_RESIDUE             : NOT MEASURED
```

러너 실행 결과(fail-closed 정상 동작):
```
$ uv run python scripts/run_motion_double_blind_concurrency_probe.py \
    --migration migrations/2026-07-23_motion_double_blind_labeling.sql \
    --prerequisites tests/sql/motion_double_blind_prerequisites.sql \
    --probe tests/sql/motion_double_blind_hardening_probe.sql
DOUBLE_BLIND_LABELING_HARDENING_BLOCKED_DB_RUNTIME: docker_daemon_unavailable: failed to connect to the docker API at unix:///Users/baek/.orbstack/run/docker.sock ...
(exit 2)
```

**근본 원인:** OrbStack VM 기동 실패 — 데이터 이미지 잠금 permission denied.
```
level=fatal msg="failed to lock data: Permission denied while opening data image.
This is usually caused by Migration Assistant changing its owner to root.
To fix it, run: sudo chown -R $USER ~/Library/Group\ Containers/HUAQ24HBR6.dev.orbstack/data"
```
`sudo chown` 은 사용자 시스템 파일 대상이라 에이전트가 임의로 실행하지 않는다(사용자 비밀번호 필요).

**언블록 절차(사용자):**
1. `sudo chown -R $USER ~/Library/Group\ Containers/HUAQ24HBR6.dev.orbstack/data`
2. `orb start` 로 Docker daemon 기동, `docker image inspect postgres:15` 로 이미지 캐시 확인(없으면 `docker pull postgres:15` 는 **승인된 download**로 간주)
3. `uv run python scripts/run_motion_double_blind_concurrency_probe.py --migration ... --prerequisites ... --probe ...` 재실행 → `DB_RUNTIME_PROBE_OK` · `DB_CONCURRENCY_PROBE_OK` · `PROBE_RESIDUE=0` 3개 마커 확인

> `tests/sql/motion_double_blind_hardening_probe.sql` 와 러너 오케스트레이션은 **작성 완료 · 런타임 미검증**(Docker 부재). 위 언블록 뒤 실측하거나, Post-Hardening Sequence 의 preview deployment 리뷰에서 확인한다.

## 4. 전체 테스트/빌드 결과

| 항목 | 결과 |
|---|---|
| `uv run pytest -q` | **745 passed** (baseline 731 → +14: migration 정적 +8, runtime 러너 단위 +6) |
| `cd web && npm test` (vitest) | **723 passed** (baseline 705 → +18) |
| `cd web && npx tsc --noEmit` | **exit 0** |
| `git diff --check` | clean (whitespace 오류 없음) |
| `cd web && npm run build` | **UNVERIFIED** — repository safety hook(`dangerous-guard.sh`, donts#9)이 세션 내 `npm run build` 차단. tsc 를 빌드 증거로 대체하지 않음. 사용자 터미널에서 별도 확인 필요 |
| DB runtime/concurrency probe | **BLOCKED**(§3) |

러너 단위 테스트: `tests/test_motion_double_blind_runtime_probe.py` 6 passed — `validate_database_url`(운영 DB 접속 차단)·`parse_probe_rows`(peer_present 다중집합 {f,t}) 순수 로직 검증(Docker 불요).

## 5. 블라인드 누출·비밀 정적 감사

- `rg "peer_(decision|initial_gt|note|digest)|lease_token|r2_key|evidence|vlm" web/src/app/api/labeling-v3/blind web/src/lib/motionBlindDraft.ts`
  - `motionBlindDraft.ts`: **0 매치** — draft 봉투에 상대 제출·lease·r2_key·vlm·evidence 없음.
  - submit 라우트의 `peer_*`·`lease_token`: **서버 내부 RPC row/입력 토큰** 뿐. 브라우저 응답은 `{ status, differing_fields }` 로 고정(상대 원문 0).
  - `_access.ts` 의 `r2_key`: 기존 `loadBlindSlotAccess`(detail/media)에서 `media_ready` boolean 산출용, 응답 미포함. 신규 `getAssignedBlindClip`(id,duration_sec)·`getOwnerClipDuration`(duration_sec)은 r2_key 미조회.
  - 그 외 매치는 전부 "누출 안 됨"을 검증하는 테스트 assertion.
- `rg "@...(com|net|kr)|SUPABASE_SERVICE_ROLE|R2_SECRET|BEGIN (RSA|OPENSSH) PRIVATE" migrations/... tests/sql scripts/run_...py`: **NO_MATCHES** (이메일·서비스키·개인키 없음). prerequisites 는 최소 schema 만(production row/secret 미복사).
- `git diff --name-only 7556009..HEAD | rg '\.(mp4|mov|avi|mkv|jpg|jpeg|png)$'`: **NO_MEDIA** (새 tracked 미디어 없음).

## 6. 변경 파일 (19)

DB 계약: `migrations/2026-07-23_motion_double_blind_labeling.sql`, `tests/test_motion_double_blind_labeling_migration.py`, `tests/sql/motion_double_blind_prerequisites.sql`(신규), `tests/sql/motion_double_blind_hardening_probe.sql`(신규), `scripts/run_motion_double_blind_concurrency_probe.py`(신규), `tests/test_motion_double_blind_runtime_probe.py`(신규).

Server/API: `web/src/app/api/labeling-v3/blind/_access.ts`, `.../[clipId]/submit/route.ts(.test.ts)`, `.../owner/[clipId]/resolve/route.ts(.test.ts)`, `.../queue/route.test.ts`, `web/src/lib/motionBlindReviewServer.ts(.test.ts)`.

Draft: `web/src/lib/motionBlindDraft.ts`(신규), `web/src/lib/motionBlindDraft.test.ts`(신규), `web/src/app/labeling/_blind-review-detail.tsx`, `web/src/app/labeling/_blind-hardening.test.ts`.

diff --stat: 19 files, +2672 / −70. 하드닝 범위 밖 리팩토링/기능 확장 없음(owner v3·legacy v2·tutorial·VLM·Gate·Python Evidence·activity 계산·UI copy/selection 불변).

## 7. 미검증 항목 (known unverified)

1. **disposable DB 런타임/동시성 실증** — Docker daemon 부재로 미실행(§3). 러너·probe SQL·prerequisites 는 작성 완료·런타임 미검증.
2. **production build** — repository safety hook 차단으로 세션 내 미실행. 사용자 터미널 확인 필요.

## 8. 명시적 non-actions (범위 밖 · 미수행)

- production migration apply **안 함** (production applied = false)
- main merge **안 함** (main merged = false)
- Vercel production deploy **안 함**
- 실제 사용자·그룹 mapping **안 함** (real groups mapped = false)
- canary 생성 **안 함**
- Owner Pilot 151 dataset manifest 생성 **안 함**
- 기존 push 커밋 amend/rebase/force-push **안 함**

## 9. 최종 판정

```
DOUBLE_BLIND_LABELING_HARDENING_BLOCKED_DB_RUNTIME
```

정적 SQL 회귀·API/draft 단위 테스트·러너 단위 테스트는 전부 통과했으나, **disposable PostgreSQL 동시성 실증을 실행하지 못했다**(Docker daemon 부재 — OrbStack 데이터 이미지 permission). 계획 Global Constraints 와 owner 지시에 따라 READY 를 주장하지 않고 BLOCKED 로 멈춘다.

**다음 게이트:** (사용자) OrbStack 언블록 → 러너 재실행으로 3개 마커 확보 → Codex 하드닝 diff + disposable DB evidence 리뷰 → 별도 preview deployment handoff(safe DB 에 migration 적용 + owner 승인 12-clip 격리 canary) → 수용 후에만 main/production 통합 → Owner Pilot 151 frozen manifest.
