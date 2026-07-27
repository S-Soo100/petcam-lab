# AI 연구 운영 계약

AI 연구·구현을 장기 운영할 때 P0~P2의 반복 승인을 줄이면서도 production 변경, 파괴적 작업,
비용 확대는 Owner가 통제하도록 하는 정본이야. 실행별 실제 권한·모델·runtime은
`RUN-MANIFEST`에 고정한다.

## 권한 등급

| 등급 | 자동 실행 범위 |
|---|---|
| P0 | read-only 코드·문서·로그·DB SELECT |
| P1 | 격리 worktree 구현·테스트·문서·feature commit/push |
| P2 | Preview·disposable DB·rollback probe·non-production canary |
| P3 | exact target·rollback·canary가 승인된 production 변경 |
| P4 | 삭제·destructive git·credential 변경·비용 확대 |

승인된 작업 패키지에서 P0~P2는 중간 승인 없이 완료한다.
P4는 항상 별도 Owner 승인이다.

### 승인 범위

- Owner가 작업 패키지를 승인하면 P0~P2는 중간 Stop Point 없이 검수·commit·push·Preview까지
  이어서 수행한다.
- P3는 “배포도 해” 같은 일반 문구만으로 확장하지 않는다. manifest에 production project,
  migration 또는 service label, rollback, canary가 구체적으로 있고 Owner가 작업 패키지에서
  명시 승인한 경우만 허용한다.
- P4는 상위 계획에 들어 있어도 실행 직전에 별도 승인이 필요하다.
- 하위 에이전트와 외부 CLI는 호출한 부모가 가진 permission보다 높은 작업을 할 수 없다.
- 권한 밖 작업을 laptop, 다른 계정, 직접 API 같은 우회 경로로 실행하지 않는다.

## Model profile

| profile | 현재 mapping | 역할 |
|---|---|---|
| frontier_planning | gpt-5.6-sol / ultra | 연구 설계·최종 판정 |
| critical_engineering | gpt-5.6-sol / high~xhigh | DB·보안·동시성·배포 검수 |
| standard_execution | gpt-5.6-terra / medium~high | 구현·테스트·문서 |
| independent_review | 작성자와 다른 model family 또는 독립 세션 | 교차검수 |

모델 provenance는 requested_model, actual_model, requested_reasoning,
actual_reasoning, fallback_reason으로 기록한다.

모델명은 영구 규칙이 아니라 현재 mapping으로 버전 관리한다. 모델이 교체되면 같은 역할의
후속 모델로 mapping을 갱신하되 과거 manifest는 수정하지 않는다.

| profile | 현재 기본 mapping | 용도 |
|---|---|---|
| `frontier_planning` | `gpt-5.6-sol`, `ultra` | 전체 연구 설계, 데이터 계약, 아키텍처, 최종 채택 판정 |
| `critical_engineering` | `gpt-5.6-sol`, `high` 또는 `xhigh` | DB 무결성, 보안, 동시성, production 배포 검수 |
| `standard_execution` | `gpt-5.6-terra`, `medium` 또는 `high` | 일반 구현, 테스트, 문서, 반복 조사 |
| `independent_review` | 작성자와 다른 모델 family 또는 독립 세션 | diff·실험 해석·위험 경계 교차검수 |
| `local_assistant` | manifest에서 고정한 local model | evidence 요약·후보 정리. 최종 행동·GT 판정 금지 |

Ultra는 모든 구현에 기본 사용하지 않는다. 장기 연구 방향이나 dataset 계약을 결정할 때,
되돌리기 어려운 아키텍처를 선택할 때, 상충하는 증거를 최종 해석할 때, Critical/P3 작업의
마지막 독립 검수에만 사용한다.

정확한 모델을 runtime이 제공하지 못하면 대체 모델을 조용히 사용하지 않는다.
`requested_model`, `actual_model`, `requested_reasoning`, `actual_reasoning`, fallback 이유를
manifest와 보고서에 기록한다. 모델 identity를 확인할 API나 runtime 증거가 없으면 추측하지
않고 `unverified`로 쓴다.

## Run manifest 계약

모든 Standard 이상 연구·구현 작업은 시작 전 `RUN-MANIFEST`에 다음을 고정한다.

- identity: task id, 목적, 설계·계획 절대경로
- source: execution repo, branch, 40자리 commit, clean 상태
- runtime: implementation host, runtime host, runtime kind, service label
- model: requested/actual model, reasoning effort, app/CLI/API/local 구분
- permission: 최고 허용 P등급, 허용 write, 금지 write
- data: dataset version, split, media availability contract, privacy class
- budget: 최대 호출, token 또는 비용, wall time, deadline
- safety: lock, host guard, rollback, residue, temp-media 조건
- stop conditions: integrity drift, secret exposure, off-target mutation, budget 초과, runtime drift
- deliverables: REPORT, summary, commit, deployment evidence

계획을 보고 권한·model·dataset을 사후 변경하지 않는다. 변경이 필요하면 새 manifest revision과
변경 사유를 먼저 기록한다.

## 비밀값

비밀번호·API key·webhook·cookie·signed URL을 기록하지 않는다.
capability_available, credential_source_name, 만료 여부만 기록한다.

- 사용자에게 받은 비밀번호를 다른 세션이나 모델에 전달하지 않는다.
- 인증이 필요하면 기존 OS keychain, environment, approved connector를 사용한다.
- 인증 실패를 해결하려고 권한·host guard·RLS를 약화하지 않는다.

## 장기·원격 실행

- Desktop 앱은 연구 지휘자이며 daemon이 아니다. 반복 실행은 LaunchAgent 또는 durable job runner가
  담당한다.
- Mac mini의 job은 앱·MacBook 연결이 끊겨도 진행 상태를 ledger와 파일에 기록한다.
- heartbeat는 상태가 바뀌지 않으면 알림하지 않는다.
- 승인 요청, BLOCKED, rollback, integrity failure, 완료 상태만 즉시 보고한다.
- 재부팅 뒤 manifest·ledger·repo HEAD로 안전하게 resume하거나 fail-closed한다.
- 동일 branch/worktree를 두 머신·두 agent가 동시에 수정하지 않는다.

## 검증·보고

최종 보고에는 최소한 다음을 포함한다.

- requested/actual model과 reasoning
- 시작·최종 commit, upstream, tracked/untracked 상태
- 사용한 permission 등급과 실제 mutation
- 실행한 검증 명령과 결과
- dataset split과 표본 범위
- 비용·token·wall time 또는 `not-measured`
- 미검증 항목과 다음 허용 행동

`IMPLEMENTED_UNVERIFIED`, `PREVIEW_VERIFIED`, `DEPLOYED_VERIFIED`, `RESEARCH_ADOPTED`를
구분한다. 도구가 없다는 이유만으로 BLOCKED를 남발하지 않되, 동등한 검증 없이 VERIFIED를
주장하지 않는다.

## 실패·중단 규칙

다음은 자동 중단하고 Owner에게 보고한다.

- manifest HEAD·repo·host mismatch
- dataset split leakage 또는 media hash mismatch
- 허용되지 않은 production/GT/behavior/app/R2 mutation
- secret 또는 개인식별정보 출력
- model identity·prompt·sampler drift
- budget·deadline 초과
- rollback·cleanup·residue 검증 실패

일반 테스트 실패와 구현 결함은 P0~P2 범위에서 최대 세 번 진단·수정한다. 같은 blocker가
반복돼 안전한 진전이 없을 때만 BLOCKED로 보고한다.
