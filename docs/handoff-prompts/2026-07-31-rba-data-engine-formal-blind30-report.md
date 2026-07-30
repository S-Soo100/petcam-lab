# RBA Data Engine formal Blind30 인프라 구현·배포 보고

## 판정

- `FORMAL30_INFRA_DEPLOYED_NO_RESERVATION`
- `BLIND30_RESERVATION_APPROVED_PREFLIGHT_READY`
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

## Task 7 실행 전 효과성·해석 동결

production B그룹의 서로 다른 두 non-owner는 approved labeler, current active member,
active `tutorial-v1` current run position 1..5 completed, waiver 0을 모두 만족한다. membership
history는 각각 1행이고 later reassignment는 0이다. 그룹 배정과 tutorial 완료의 시간 선후는
TEST-SHEET·Task 7 plan·production RPC의 자격 조건이 아니다.

metadata dry-run은 eligible `15,671`, exact 30, camera 3, camera-night 30, selected 5-minute
duplicate 0으로 selection 계약을 만족했다. Claude 독립 효과성 심사는 natural-distribution
measurement-system gate로 `EFFECTIVE/GO`를 판정했고 owner가 Task 7 실행을 승인했다.

결과를 보기 전에 해석 범위를 다음처럼 고정한다.

- PASS는 natural production distribution의 2인 일치도, abstain, owner adjudication 부담,
  제출·blind·표본 운영무결성만 인증한다.
- 희소 행동별 일치도, taxonomy 유효성, train/validation GT 품질, 모델/VLM/Gate/router/P0
  성능, chance-corrected agreement는 인증하지 않는다.
- 실현 class 분포와 class별 일치는 descriptive-only로 보고하고 작은 분모에서 추론하지 않는다.
- rare-behavior challenge set은 향후 별도 TEST-SHEET로 사전 동결한다.

이 선커밋 시점의 실제 selection, manifest, cohort reservation, URL 생성은 0이다. 다음은 새 실
T0와 production zero-state를 다시 확인한 뒤 RPC를 정확히 한 번 호출하고 human 제출에서
멈추는 Task 7이다.

## Task 7 reservation 실행 결과

판정은 `BLIND30_PREFROZEN_READY`다.

- host: `baeg-endeuui-Macmini.local`
- 실 T0: `2026-07-31T03:44:27.183403+09:00`
- raw projected / eligible / selected: `19,279 / 15,678 / 30`
- selected cameras / camera-nights / 5-minute duplicates: `3 / 30 / 0`
- reviewer fingerprints: `34345bea7568`, `b3cdaf01e7d8`
- ordered-list SHA-256: `2b23ccc43fda4559a7feedf5067493293aeac27e357360f68011cb46d78c5f3b`
- manifest SHA-256: `e335c82a642f2cfe63e0c9d42d8f7fb92c9918e5a76e4333acf36722c7426377`
- audit directory / manifest mode: `0700 / 0600`
- RPC 호출: 정확히 `1`
- DB insert: cohort `1` + slots `60` + awaiting consensus `30` = `91`
- 사후 상태: open cohort `1`, reviewer별 slots `30/30`, awaiting consensus `30`,
  submission `0`
- reviewer 자격: qualified non-owner `2`, owner reviewer `0`

RPC 직전·직후 formal 범위 밖 live 원장은 정확히 불변이다.

| live 원장 | count | SHA-256 |
|---|---:|---|
| slots | 36,924 | `a729fc4120f5e62e077d7a85ca3952c20ad735577659648e435565723642dc70` |
| submissions | 238 | `3d3ce13a8c7da97305b79daa310768668ee5a7913edfc87d88db2f6f8444e9a1` |
| consensus | 18,462 | `81bcff7550b9afd18871c4cb15793ef6c4c80b9e42b7f28ae44d846696ea27ac` |

agent submission과 owner adjudication은 0이다. 다음은 두 reviewer가 같은 cohort의 30개를
blind로 각각 완료하는 human 단계이며, 둘 다 30/30을 완료하기 전 Task 8을 시작하지 않는다.
