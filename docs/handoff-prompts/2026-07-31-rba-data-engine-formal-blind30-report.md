# RBA Data Engine formal Blind30 인프라 구현·배포 보고

## 판정

- `FORMAL30_INFRA_DEPLOYED_NO_RESERVATION`
- `BLIND30_BLOCKED_REVIEWER_PAIR`
- Task 7 표본 동결·예약과 Task 8 실행·채점은 수행하지 않았다.

## 범위와 정본

- project ref: `slxjvzzfisxqwnghvrit`
- 구현·production 적용 기준 SHA: `69e12ef57967b2442a375a4ced07f81cc797153c`
- migration: `migrations/2026-07-31_motion_blind_formal30.sql`
- migration SHA-256: `46dfcd20b25b2ca89a299b6ab31f3cacb1ea4f117991ed7875eb344e13c17e00`
- SQL Editor 결과: `Success. No rows returned`

migration은 exact 30 clips, qualified reviewers 2명, slots 60개, awaiting consensus 30개를
단일 transaction으로 예약하는 `service_role` 전용 RPC와 guard·unique 제약만 추가한다. 기존
`motion-blind-v1` comparator, live 원장 row, slot/submission/consensus/event/final row를
수정하거나 다시 쓰는 DML은 포함하지 않는다.

## 구현과 검증

- exact-30 selector는 live unsubmitted slot과 awaiting consensus를 후보로 허용하고,
  canary/formal history, any submission, terminal consensus를 제외한다.
- camera-night 및 5분 near-duplicate 누수 방지와 deterministic selection을 고정했다.
- scorer는 immutable raw submission만 입력으로 사용하고 abstain, segment matching,
  owner adjudication, pass/fail을 daily comparator와 분리했다.
- manifest는 mode `0600`, secret 제외, canonical hash 계약으로 고정했다.

RED에서 원자성, reviewer tutorial 5/5, `service_role` 권한, 후보 제외 규칙, raw submission
채점 계약을 먼저 재현한 뒤 GREEN으로 구현했다. 독립 review의 actionable finding을
최소 수정으로 반영하고 다시 검증했다.

검증 결과:

- applicable Python: `906 passed, 4 skipped`
- unrelated absolute-path test: `1 deselected`
- Web: `869 passed`
- TypeScript: PASS
- labeling role UI audit: PASS
- preview/local DB probe: `FORMAL30_PROBE_OK`
- preview/local DB residue: `PROBE_RESIDUE=0`
- 기존 comparator/live 원장 구현 diff: `0`

UI/runtime 코드는 바뀌지 않았으므로 Vercel 재배포는 하지 않았다.

## Production 권한·구조

적용 후 read-only 검증 결과:

- `function_exists=true`
- `anon_execute=false`
- `authenticated_execute=false`
- `service_role_execute=true`
- `guard_trigger_exists=true`
- `unique_index_exists=true`

formal30 production row:

- cohort: `0`
- slot: `0`
- submission: `0`
- consensus: `0`

실제 metadata selection, manifest 생성, cohort reservation, reviewer URL 생성도 모두 `0`이다.

## 기존 원장 관찰과 caveat

배포 전 기준:

| 원장 | count | hash |
|---|---:|---|
| all slots | 36,948 | `08122d5d5c24548652361603089aef55` |
| all submissions | 251 | `b25d7ef08be3361dd6e85acfab2f35bd` |
| all consensus | 18,474 | `a019333756d28b273448abf29bf1944b` |

사후 consensus는 `18,474`건과 hash
`a019333756d28b273448abf29bf1944b`로 정확히 불변이었다. 다만 적용·검증 중
`2026-07-30 17:22:44.799039+00`부터 `17:24:54.50682+00` 사이에 일상 운영 live
submission 3건이 동시 유입됐다. provenance는 `live=3`, `canary=0`, `formal30=0`이며,
이에 따라 submission row와 관련 slot `submitted_at`이 정상 갱신되어 global
slot/submission hash exact-equality는 관측할 수 없었다.

따라서 global slot/submission 전체 hash 불변을 통과로 주장하지 않는다. production
migration에 기존 row DML이 없고, consensus가 정확히 불변이며, formal30 subset이 계속
0이고, 관측된 변화가 동시 live 제출 3건으로 설명된다는 범위에서 배포를 판정한다.

## 남은 사람 조치

같은 active group의 두 번째 qualified non-owner가 waiver 없이 실제 tutorial-v1 5/5를
완료해야 한다. 그 증거가 준비되고 별도 승인을 받기 전에는 Task 7의 exact 30 selection,
manifest, cohort reservation, URL 생성을 시작하지 않는다.
