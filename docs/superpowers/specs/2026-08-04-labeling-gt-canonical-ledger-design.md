# Labeling Web Canonical GT Ledger 설계

> 상태: 2026-08-04 사용자 방향 승인 · 구현 전 동결
>
> 목적: labeling web의 여러 사람 GT 경로를 하나의 최종 정답 읽기 계약으로 통일하되,
> 진행 중인 교차검수와 다른 `petcam-lab` 세션에는 영향을 주지 않는다.

## 1. 한 줄 결론

기존 direct GT 세션과 blind consensus를 서로 덮어쓰지 않고 그대로 보존한다. 그 위에 독립적인
append-only `motion_clip_gt_revisions`와 clip별 현재 revision을 가리키는
`motion_clip_gt_heads`를 추가해, 완료된 사람 GT만 canonical final GT로 승격한다.

## 2. 문제 정의와 확인된 운영 상태

현재 `motion_clips` 사람 GT는 두 개의 사실상 독립된 저장 경로를 가진다.

- direct GT: `motion_clip_labeling_sessions.current_gt ?? initial_gt`
- double-blind GT: `motion_clip_consensus.final_gt`

직접 GT 화면은 session만 읽고, 교차검수 합의·불일치 해결은 consensus만 쓴다. 공용 영상 보관함은
완료 consensus를 우선하고 session을 legacy fallback으로 읽는다. 따라서 같은 clip이 화면에 따라
다른 GT를 보거나, 교차검수가 끝났는데 direct GT 화면에는 정답이 나타나지 않을 수 있다.

2026-08-04 production read-only snapshot은 다음과 같다.

| 항목 | 건수 |
|---|---:|
| `motion_clip_consensus` 전체 | 20,904 |
| live awaiting | 20,585 |
| live owner_resolved | 251 |
| live agreed | 26 |
| canary awaiting / owner_resolved / agreed | 30 / 10 / 2 |
| `motion_clip_labeling_sessions` 전체 | 220 |
| session completed / gt_locked | 216 / 4 |
| live final consensus clip | 277 |
| session clip | 220 |
| 두 경로가 겹치는 clip | 2 |

겹치는 2건도 session current GT와 consensus final GT가 다르다. 그러므로 기존 어느 한 테이블을
무조건 승자로 정하거나 일괄 복사하는 것은 안전하지 않다.

## 3. 목표와 비목표

### 목표

- labeling web에서 들어오는 모든 **사람 행동 GT**의 현재 최종본과 이력을 한 계약으로 읽는다.
- blind 최초 제출, 합의, owner 판정, owner 정정의 provenance를 잃지 않는다.
- 진행 중인 blind review의 답과 상태를 노출하거나 변경하지 않는다.
- 현재 DB writer와 UI를 즉시 바꾸지 않고 shadow 비교 후 단계적으로 전환한다.
- 데이터셋, 대시보드, 보관함, direct GT 화면이 같은 canonical head를 읽게 한다.

### 비목표

- 기존 session, submission, consensus, event 행의 삭제·수정·재작성
- awaiting/conflict 답의 자동 선택 또는 peer 답 공개
- canary/tutorial을 production 행동 GT에 합치기
- VLM, Gate, Python Evidence, local router 결과를 사람 GT로 승격하기
- 사건 경계 GT를 행동 GT와 같은 schema로 합치기
- 이번 계획 단계에서 production DB, Vercel, R2를 변경하기

## 4. 전체 GT 분류

| 경로 | 역할 | canonical 행동 GT 포함 여부 |
|---|---|---|
| `motion_clip_labeling_sessions` | direct/legacy owner GT와 그 수정본 | 자격 충족 시 포함 |
| `motion_clip_blind_submissions` | 각 reviewer의 immutable 최초 답 | 직접 포함하지 않음 |
| `motion_clip_consensus` live agreed | 두 답의 완료 합의 | 포함 |
| `motion_clip_consensus` live owner_resolved | owner 최종 판정 | 포함 |
| owner single adopt | 한 명 답을 owner가 채택한 완료 판정 | 포함, provenance 명시 |
| canary consensus | UI/비교기 검증용 | 제외 |
| labeling tutorial | 교육용 snapshot/답 | 제외 |
| boundary review | 사건 이어짐 전용 task GT | 별도 canonical ledger 대상 |
| VLM/Gate/Python Evidence | 예측·관측 evidence | 제외, prediction/evidence ledger 유지 |
| legacy `camera_clips` v2 | 이전 시스템의 사람 GT | 별도 호환·이관 정책 전까지 현행 유지 |

이 설계의 첫 적용 범위는 `motion_clips` 행동 GT다. `camera_clips` v2와 boundary GT는 같은
“revision + head” 원칙을 재사용할 수 있지만 서로 다른 task/schema이므로 첫 migration에 섞지 않는다.

## 5. 채택안과 기각한 대안

### 채택: 독립 canonical revision ledger

원천 테이블은 사실 기록으로 보존하고, 최종 소비자가 읽을 안정적인 projection을 별도로 둔다.
승격과 정정은 모두 새 revision을 추가한 뒤 head만 이동한다.

### 기각: consensus를 session으로 복사

교차검수 결과를 특정 reviewer의 direct session처럼 위장한다. 최초 답과 최종 판정의 의미가 섞이고,
현재 session UI/상태 머신에 예기치 않은 변화가 생길 수 있다.

### 기각: `motion_clip_consensus` 자체를 범용 SOT로 사용

direct-only GT, owner 사후 정정, 다른 source provenance를 자연스럽게 표현하지 못한다. consensus는
두 blind 답의 비교 결과라는 좁은 의미를 유지해야 한다.

### 기각: 읽을 때마다 여러 테이블을 우선순위로 합성

소비자마다 SQL이 복제돼 다시 서로 다른 정답을 읽게 된다. 충돌을 감사 가능하게 해결할 head와
revision id도 남지 않는다.

## 6. 데이터 계약

### 6.1 `motion_clip_gt_revisions`

append-only 최종 GT 원장이다. 최소 필드는 다음과 같다.

- `id`, `clip_id`, `revision_no`
- `final_decision`: 기존 consensus와 같은 `label | hold | exclude`. direct session은 `label`
- `gt`: decision이 label일 때만 non-null
- `source_type`: `blind_consensus | owner_adjudication | owner_override |
  owner_direct_legacy | owner_single_adopt`
- `source_table`, `source_id`, `source_version`
- `parent_revision_id`: owner 정정 또는 재판정 전 head
- `reason`: owner override에서는 필수
- `actor_id`: 자동 projection이면 null, 사람 판정이면 해당 owner
- `created_at`, `projection_run_id`

`(clip_id, revision_no)`와 원천 event에 대한 idempotency key를 unique로 둔다. UPDATE, DELETE,
TRUNCATE는 service role을 포함해 append-only trigger로 막는다.

### 6.2 `motion_clip_gt_heads`

clip당 현재 canonical revision 하나를 가리키는 작은 projection이다.

- `clip_id` primary key
- `revision_id` unique foreign key
- `updated_at`

head 이동은 새 revision 생성과 같은 transaction에서만 수행한다. 소비자용 RPC/view는 head에서
revision을 join하고, 원천 테이블별 우선순위를 자체 구현하지 않는다.

### 6.3 불변식

1. canary, tutorial, awaiting, conflict는 revision을 만들지 않는다.
2. `final_decision='label'`이면 유효한 GT가 필수이고, `hold|exclude`이면 GT는 null이다.
3. blind 최초 submission은 immutable이며 canonical ledger가 수정하지 않는다.
4. 기존 consensus/session/event 행은 canonical projection 때문에 수정되지 않는다.
5. owner override는 reason과 parent revision 없이 생성할 수 없다.
6. 한 원천 final event를 재처리해도 revision이 중복 생성되지 않는다.
7. head가 가리키는 revision은 반드시 같은 clip이다.
8. 예측·evidence는 GT revision의 source가 될 수 없다.

## 7. 승격·충돌 규칙

### 7.1 신규 완료 결과

- live consensus가 `agreed` 또는 `owner_resolved`로 완료되면 shadow projector가 이를 읽어
  canonical revision 후보로 만든다.
- blind finalize RPC에 trigger나 동기 write를 추가하지 않는다. projection 실패가 현재 교차검수
  제출·합의·불일치 해결을 막아서는 안 된다.
- projector는 cursor + idempotency key로 반복 실행 가능하고, 실패 항목은 별도 운영 로그에 남긴다.

### 7.2 direct GT

- 과거 direct-only 완료 session은 `owner_direct_legacy`로 후보화한다.
- canonical cutover 뒤 owner가 direct 화면에서 저장하는 정정은 `owner_override` revision을 만들고
  head를 이동한다. 기존 `initial_gt`와 session revision 이력은 그대로 둔다.

### 7.3 과거 두 원천의 충돌

같은 clip에 완료 consensus와 direct session이 함께 있고 의미가 다르면 자동 우선순위를 적용하지
않는다. reconciliation queue에 넣고 owner가 두 provenance를 본 뒤 하나를 채택하거나 새 GT로
정정한다. 판정 전에는 기존 production read를 유지하고 canonical head를 공개하지 않는다.

동일한 경우에도 두 원천을 삭제하거나 합치지 않는다. canonical revision은 채택 source를 가리키고
다른 source는 감사 가능한 후보로 보존한다.

owner reconciliation은 실제 해결 API와 UI를 가진다. owner는 두 source의 GT와 provenance를 보고
`consensus 채택`, `direct 채택`, `새 GT 입력` 중 하나를 고른 뒤 10~500자 사유를 제출한다. RPC는
reconciliation row와 현재 head를 `FOR UPDATE`로 잠그고 새 revision 생성, head 이동,
reconciliation 완료를 한 transaction에서 수행한다. 자동 source 우선순위는 끝까지 두지 않는다.

### 7.4 동시성 계약

- projection은 clip advisory lock과 head row lock을 잡은 뒤 revision 번호를 계산한다.
- owner override/reconciliation은 `expected_revision_id`를 잠근 head와 비교한다. 다르면 `PT409`로
  전체 transaction을 취소한다.
- 같은 head에 동시에 들어온 두 owner write 중 하나만 성공하며 다른 하나는 revision을 남기지 않는다.
- 한 projection batch는 PostgreSQL RPC transaction 전체가 성공하거나 전체가 rollback된다.
  일부만 성공한 상태를 정상 결과로 반환하지 않는다.

## 8. 사용자 체험 시뮬레이션

### 8.1 진행 중인 교차검수

`[화면] 라벨러는 기존 B그룹 작업 화면과 본인 남은 수를 그대로 봄`

→ `[조작] 기존처럼 답을 제출`

→ `[반응] 상대 답은 보이지 않고 다음 영상으로 이동`

→ `[감정] GT 통합 작업이 진행 중인지 알 필요 없이 기존 작업이 그대로 이어짐`

### 8.2 완료 GT 열기

`[화면] owner가 direct GT 화면에서 완료된 clip을 엶`

→ `[반응] canonical GT와 ‘두 사람 합의/owner 판정/legacy 직접 확정’ source가 함께 표시됨`

→ `[조작] 읽기만 하거나 ‘정정’을 선택`

→ `[감정] 어느 화면을 열어도 같은 최종 정답이라는 확신을 가짐`

### 8.3 owner 정정

`[화면] 현재 canonical GT와 source provenance, 과거 revision을 봄`

→ `[조작] GT를 고치고 필수 사유를 입력한 뒤 확인`

→ `[반응] 새 revision이 생성되고 현재 head가 이동하며 과거 값은 남음`

→ `[감정] 수정은 가능하지만 과거 정답을 지우지는 않았음을 이해함`

### 8.4 미완료 또는 불일치 clip

`[화면] direct GT 화면에 ‘교차검수 진행 중’ 또는 ‘owner 해결 대기’가 표시됨`

→ `[반응] peer 답과 임시 GT는 표시되지 않음`

→ `[감정] 미완료 답을 최종 정답으로 오해하지 않음`

## 9. 무영향·세션 충돌 방지 계약

### 9.1 현재 작업 경계

이 설계/계획은 `origin/main`의 40자리 SHA
`547d34e0227b3a621948305a04114f9e385bd39c`에서 만든 격리 worktree
`/Users/baek/petcam-lab/.worktrees/labeling-gt-canonical-plan`의 새 문서만 소유한다.

주 checkout과 다른 worktree의 dirty 파일은 수정하지 않는다. 특히 진행 중인
`codex/rba-boundary-blind-hardening` 작업이 소유한 `docs/DATABASE.md`, `pyproject.toml`,
`uv.lock`, `web/src/app/labeling/_role-shell.tsx`, `web/src/lib/labelingRoleNavigation*`,
`web/src/lib/labelingV3Server.ts`와 겹치는 구현은 해당 세션이 통합된 뒤 최신 main에서 다시
ownership audit를 통과하기 전 시작하지 않는다.

### 9.2 runtime 무영향

- 계획/리뷰 단계에는 production DB write, migration apply, backfill, Vercel/Fly 배포가 없다.
- 첫 구현 migration은 additive schema/RPC만 포함하고 기존 함수 signature와 writer를 바꾸지 않는다.
- shadow 단계는 canonical 결과를 현행 UI/API에 노출하지 않는다.
- 기존 20,585건 live awaiting 작업의 row/state/count를 migration 전후 aggregate로 비교한다.
- canary와 tutorial은 projection query와 DB constraint 양쪽에서 제외한다.

## 10. 단계적 rollout과 rollback

### Phase 0 — 계약·기준선 동결

- producer/consumer inventory와 production aggregate snapshot을 고정한다.
- 최신 main 및 active worktree ownership을 다시 검사한다.
- implementation handoff가 있으면 manifest에 execution repo, 40자리 SHA, host/runtime을 쓰고
  `verify_agent_handoff.py`의 `HANDOFF_OK`를 통과한다.

### Phase 1 — 미사용 additive schema

- revision/head/reconciliation 구조와 service-role RPC를 추가한다.
- 기존 writer, route, UI는 변경하지 않는다.
- static migration test와 disposable PostgreSQL probe로 append-only, 권한, 원자성, idempotency를
  검증한다.

### Phase 2 — shadow projection

- 완료 live consensus와 자격 있는 direct session을 dry-run report로 분류한다.
- 신규 완료 건은 비동기 projector가 revision/head에 반영하되 어떤 기존 소비자도 읽지 않는다.
- 과거 중복/불일치 건은 reconciliation queue로 보내며 자동 head를 만들지 않는다.
- batch 중 한 후보가 실패하면 그 RPC batch의 revision/head/reconciliation write 전체가 rollback된다.
  다음 실행은 같은 cursor에서 idempotent하게 재시도한다.

### Phase 3 — parity와 숨은 owner canary

- 현행 library/direct/dashboard 결과와 canonical candidate를 clip 단위로 비교한다.
- 차이는 source별로 설명 가능해야 하며 unexplained mismatch는 0이어야 한다.
- owner-only feature flag로 소수 clip의 canonical read와 provenance 표시를 확인한다.
- projection health는 `last_success_at`, source-to-head lag, last error code를 반환한다. 20분 이상
  성공 실행이 없거나 final source가 canonical head보다 20분 이상 앞서면 consumer cutover를 막고
  owner 운영 화면에 경고한다.

### Phase 4 — 읽기 전환

1. direct GT read
2. owner override write
3. library와 dashboard
4. Dataset v2/export/manifest

순서로 각각 별도 flag와 rollback gate를 둔다. 한 소비자의 실패가 다음 전환으로 전파되지 않는다.

### Phase 5 — legacy 보존

legacy 테이블과 RPC는 즉시 제거하지 않는다. 최소 한 운영 관측 기간 동안 read-only 호환 경로와
reconciliation 근거로 유지한다. 제거는 별도 승인·계획의 대상이다.

### rollback

- 소비자 flag를 현행 read로 되돌리는 것이 1차 rollback이다.
- projector를 중지해도 기존 교차검수 writer는 계속 동작해야 한다.
- 생성된 revision/event는 감사 이력이므로 삭제하지 않는다. 잘못된 head는 검증된 새 revision 또는
  head 복구 RPC로 교정한다.
- additive schema drop이나 기존 데이터 rewrite는 rollback 절차에 포함하지 않는다.

## 11. 검증·완료 기준

### 정적·DB 계약

- migration에 기존 GT/session/submission/consensus DELETE 또는 rewrite가 없다.
- service-role 전용, RLS enabled, PUBLIC/anon/authenticated 직접 권한 0건이다.
- revision append-only와 head 동일-clip FK/trigger가 probe에서 검증된다.
- projection 재실행 전후 revision/head digest가 같다.

### blind 안전성

- 기존 blind queue/workspace/submit/resolve 테스트가 그대로 통과한다.
- awaiting/conflict의 `final_gt`와 peer 답은 canonical API에서도 null/비공개다.
- migration/shadow 전후 slot, submission, consensus status별 row 수와 digest가 같다.
- canonical 테이블/RPC는 service_role만 접근하며 별도 blind writer DB role/policy를 만들지 않는다.

### canonical 일관성

- 완료 source 하나인 clip은 예상 source/revision/head 하나를 가진다.
- 상충 source가 있는 clip은 owner 판정 전 head가 없다.
- direct, library, dashboard, export가 같은 revision id와 GT digest를 반환한다.
- owner override 후 이전 revision은 조회 가능하고 모든 소비자는 새 head를 읽는다.

### 배포 gate

- Preview role matrix와 owner canary를 통과하기 전 production read flag를 켜지 않는다.
- 각 단계 전후 현재 교차검수 완료율과 오류율을 비교하고 이상 시 즉시 flag rollback한다.
- production backfill은 dry-run count/digest와 명시적 별도 승인을 받은 뒤에만 수행한다.

## 12. 구현 전 필수 재확인

1. 최신 `origin/main` HEAD와 이 문서 기준 SHA의 차이를 검토한다.
2. 모든 active worktree의 dirty/owned 파일을 다시 수집한다.
3. GT producer/consumer inventory에 새 route/export가 추가됐는지 `rg`로 재탐색한다.
4. production snapshot을 read-only로 다시 측정하고 수치 차이를 기록한다.
5. Claude read-only 교차검수에서 누락된 source, blind leakage, migration/rollback 위험을 확인한다.
6. 사용자에게 구현 범위와 production mutation gate를 다시 승인받는다.

## 13. Claude 읽기 전용 교차검수 반영 (2026-08-04)

Claude Sonnet/Haiku 교차검수의 최종 판정은 동시성·RLS·부분 실패·cron 누락·reconciliation 운영
경로를 보강하기 전 `HOLD`, 보강 후 `GO`였다.

### 반영

- owner override/reconciliation의 `FOR UPDATE` + expected revision + 동시 경합 probe를 명시했다.
- projection batch를 all-or-nothing transaction으로 고정하고 실패 후 동일 cursor 재실행을 검증한다.
- scheduled projection의 20분 staleness/lag health gate를 추가했다.
- 충돌을 실제로 해소할 owner API/UI와 필수 사유 계약을 추가했다.
- peer 답 비공개와 service-role-only 권한을 DB probe에서 직접 검증한다.

### 기각

- Claude가 제안한 `blind_writer` INSERT policy는 기각한다. 이 프로젝트의 web DB 접근은
  `service_role` 서버 경로이고 canonical ledger에 blind writer 직접 권한을 주지 않는 것이 더 좁은
  보안 경계다.
- Claude가 예시로 든 consensus 자동 우선 reconciliation은 기각한다. 실제 overlap 2건의 GT가
  다르므로 자동 선택은 이 설계의 “과거 divergence 무음 선택 금지” 원칙을 위반한다.
- 특정 CloudWatch/Datadog 도입은 현재 stack에 없는 새 의존성이므로 채택하지 않는다. 대신 DB 기반
  projection health와 owner-visible 경고를 먼저 구현하고 외부 알림은 별도 운영 승인 대상으로 둔다.
