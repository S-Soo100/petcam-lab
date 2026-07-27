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
P4는 항상 별도 Owner 승인이다. P3/P4는 manifest 안의 자기 주장만으로 승인되지 않는다.

### 승인 범위

- Owner가 작업 패키지를 승인하면 P0~P2는 중간 Stop Point 없이 검수·commit·push·Preview까지
  이어서 수행한다.
- P3는 “배포도 해” 같은 일반 문구만으로 확장하지 않는다. manifest에 production project,
  migration 또는 service label, rollback, canary가 구체적으로 있고 Owner가 작업 패키지에서
  명시 승인한 경우만 허용한다. validator에 주입된 `trusted approval verifier`가 이 승인을
  확인하지 못하면 중단한다.
- P4는 상위 계획에 들어 있어도 실행 직전에 별도 승인이 필요하다. trusted verifier 확인과
  각 실행의 `approval_ref`가 모두 있어야 한다.
- 기본 CLI에는 trusted approval backend가 없다. `--parse-only`는 stdlib parser의 구조·의미
  검증만 실행하고 Git/host/runtime/approval probe를 생략한다. 호환용 `--schema-only`도 같은
  parse-only 동작과 `RUN_MANIFEST_PARSE_OK` marker를 사용한다. 일반 CLI 검증은 P3/P4를
  승인하지 않고 fail-closed한다.
- 하위 에이전트와 외부 CLI는 호출한 부모가 가진 permission보다 높은 작업을 할 수 없다.
- 권한 밖 작업을 laptop, 다른 계정, 직접 API 같은 우회 경로로 실행하지 않는다.

## Model profile

모델 provenance는 `requested_model`, `actual_model`, `requested_reasoning`,
`actual_reasoning`, `fallback_reason`으로 기록한다. requested model과 reasoning은 실행 시작
전에 반드시 비어 있지 않은 값으로 고정한다.

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

정확한 모델을 runtime이 제공하지 못하면 대체 모델을 조용히 사용하지 않는다. 모델 identity를
확인할 API나 runtime 증거가 없으면 actual model과 reasoning을 둘 다 `unverified`로 쓰고
`fallback_reason`은 `null`로 둔다. 이는 fallback이 확인됐다는 뜻이 아니라 identity가
미확인이라는 뜻이야. requested와 다른 actual model 또는 reasoning이 실제로 확인된 경우에만
비어 있지 않은 fallback 이유를 기록한다.

## Run manifest 계약

모든 Standard 이상 연구·구현 작업은 시작 전 `RUN-MANIFEST`에 다음을 고정한다.

- identity: task id, 목적, 설계·계획 절대경로
- source: execution repo, branch, base/start/implementation commit, clean 상태
- runtime: implementation host, runtime host, runtime kind, service label
- model: requested/actual model, reasoning effort, app/CLI/API/local 구분
- permission: 최고 허용 P등급, 허용 write, 금지 write
- data: dataset version, split, media availability contract, privacy class
- budget: 최대 호출, token 또는 비용, wall time, deadline
- safety: lock, host guard, rollback, residue, temp-media 조건
- stop conditions: integrity drift, secret exposure, off-target mutation, budget 초과, runtime drift
- deliverables: REPORT, summary, commit, deployment evidence

Draft 2020-12 schema는 JSON 구조를 표현하는 structural superset이고, stdlib parser가 의미
검증의 유일한 authority다. 공통 corpus는 양쪽이 표현할 수 있는 구조 규칙만 교차 검증한다.
P3/P4 action의 projected identity uniqueness와 requested/actual model fallback 관계는 schema로
완전히 표현하지 않고 parser-only semantic regression으로 고정한다. 문자열은 입력 bytes의
의미를 바꾸는 strip/canonicalize를 하지 않으며, 앞뒤 whitespace나 control character가 있으면
schema와 parser 모두 거부한다.

`authorization.approved_at`과 `budget.deadline`의 non-null 값은 extended RFC3339
`YYYY-MM-DDTHH:MM:SS[.fraction](Z|±HH:MM)`만 허용한다. space separator, basic date/time,
ISO week date, offset seconds, 앞뒤 padding/control은 schema pattern과 parser fullmatch가
함께 거부하고, fullmatch 뒤 timezone-aware datetime으로 다시 검증한다.

`source.require_clean`은 항상 `true`다. validator는 사용자 Git 설정과 무관하게
`git status --porcelain=v1 --untracked-files=all --ignore-submodules=none`으로 tracked,
untracked, submodule 상태를 모두 확인한다.

### A → M → B → C commit lifecycle

네 commit 역할은 섞지 않는다.

| 기호 | 의미 | manifest 기록 |
|---|---|---|
| A | 설계·계획이 추적된 실행 직전 base commit | `source.commit_sha` |
| M | manifest만 추가한 전용 start-manifest commit | final에서 `source.start_manifest_commit_sha` |
| B | 구현·실험·검증 결과의 마지막 commit | final에서 `source.final_commit_sha` |
| C | final manifest만 기록한 전용 final-record commit | 현재 `HEAD`, summary의 record commit |

start phase의 현재 `HEAD`는 M이어야 하고 `M^ == A`여야 한다. manifest는
`execution_repo` 안에 있어야 하며, M에서 tracked 상태이고 현재 파일 bytes와 M의 blob bytes가
같아야 한다. M에는 manifest 외의 변경을 섞지 않는다. 이 시점의
`start_manifest_commit_sha`, `final_commit_sha`, actual model/reasoning, `fallback_reason`은 모두
`null`이다.

구현을 끝내 M보다 뒤인 B를 만든다. `git rev-list M..B`가 반환하는 모든 reachable commit에서
manifest blob은 M과 byte-identical해야 하며, implementation 중간에 manifest를 바꿨다가
B에서 복원하는 것도 허용하지 않는다. M..B endpoint tree diff에는 manifest가 아닌 tracked
path가 하나 이상 있어야 하므로 빈 implementation B도 거부한다. 그 뒤 final manifest
revision에 `start_manifest_commit_sha=M`, `final_commit_sha=B`, actual provenance를 기록하고
C를 만든다.
C는 manifest만 바꾸는 전용 record commit이며 `C^ == B`여야 한다. final phase는 현재
`HEAD == C`, `M^ == A`, `M != B`, `M`이 `B`의 ancestor인지 확인한다. 이어서 M의 원본
manifest bytes를 Git object에서 읽고, 아래 다섯 필드 외 모든 값을 비교한다.

- `source.start_manifest_commit_sha`
- `source.final_commit_sha`
- `model.actual_model`
- `model.actual_reasoning`
- `model.fallback_reason`

최종 summary와 보고서는 A(base), M(start manifest), B(implementation), C(record)를 각각
보존한다. 계획·권한·dataset 같은 immutable field를 바꾸려면 같은 실행의 final revision으로
덮지 말고 새 A→M→B→C 실행을 시작한다.

### host, runtime, safety 검증

- validator는 주입된 current-host lookup 결과와 `implementation_host`를 canonical exact match로
  비교한다. host lookup 자체가 실패해도 fail-closed한다.
- final phase에서 `runtime_kind != none`이면 주입된 `runtime attestation verifier`가 runtime
  host·service label·실행 증거를 확인해야 한다. 기본 CLI에는 이 backend가 없으므로 final
  runtime 검증을 스스로 통과시키지 않는다.
- P3 action은 rollback과 residue-zero 보호를 요구한다.
- `runtime_service_write`는 host guard와 lock도 요구한다.
- `disposable_db`는 residue-zero, `rollback_probe`는 rollback과 residue-zero 보호를 요구한다.
- `--parse-only`와 호환 alias `--schema-only`의 `RUN_MANIFEST_PARSE_OK` marker는 stdlib parser
  검증 결과일 뿐 Git lifecycle, trusted approval, host, runtime attestation을 증명하지 않는다.

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

`IMPLEMENTED_UNVERIFIED`, `PREVIEW_READY`, `DEPLOYED_VERIFIED`, `RESEARCH_ADOPTED`를
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
