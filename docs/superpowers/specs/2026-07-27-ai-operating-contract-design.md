# AI 연구 운영 계약 설계

**상태:** 방향 승인 · written spec owner review
**승인:** 2026-07-27 — 승인된 작업 패키지 안에서 P0~P2 자동 진행
**상위 설계:** `docs/superpowers/specs/2026-07-27-rba-research-system-v1-design.md`

## 1. 목적

ChatGPT Desktop이 Mac mini 연구를 장기 운영할 때 매 단계마다 반복 승인받는 낭비를 줄이면서도,
production 변경·파괴적 작업·비용 확대는 Owner가 통제한다. 모델이 교체돼도 어떤 권한과 모델로
어떤 결과를 만들었는지 재현할 수 있게 한다.

## 2. 문서 구조

운영 규칙을 `AGENTS.md`에 계속 추가하지 않는다. 세 층으로 분리한다.

1. `docs/research/AI-OPERATING-CONTRACT.md`
   - 장기간 유지되는 역할, 권한, 모델 선택, 승인·중단·보고 규칙
2. `docs/research/RUN-MANIFEST.schema.json`
   - 실행별 model, reasoning, host, commit, permission, budget, stop condition의 기계 검증 계약
3. 각 연구의 `RUN-MANIFEST.json`
   - 해당 실행이 실제로 받은 권한과 사용한 runtime을 고정

`AGENTS.md`와 `CLAUDE.md`에는 계약 링크와 “작업 시작 전 manifest 검증” 한두 문단만 둔다.

## 3. 권한 등급

| 등급 | 허용 범위 | 기본 승인 |
|---|---|---|
| P0 | 코드·문서·로그·DB SELECT·외부 상태 read-only 검사 | 승인된 작업 패키지에서 자동 |
| P1 | 격리 worktree 구현, 테스트, 문서, feature branch commit·push | 승인된 작업 패키지에서 자동 |
| P2 | Preview, disposable DB, rollback probe, non-production canary | 승인된 작업 패키지에서 자동 |
| P3 | production migration·배포·Mac mini service 설치·가역적 운영 write | manifest에 exact target·rollback·검증이 있고 Owner가 작업 패키지에서 명시 승인한 경우만 |
| P4 | DB/R2 물리 삭제, force push, branch 강제삭제, 비밀값·인증 변경, 비용 한도 확대 | 항상 별도 Owner 승인 |

### 승인 범위

- Owner가 작업 패키지를 승인하면 P0~P2는 중간 Stop Point 없이 검수·commit·push·Preview까지
  이어서 수행한다.
- P3는 “배포도 해” 같은 일반 문구만으로 확장하지 않는다. manifest에 production project,
  migration 또는 service label, rollback, canary가 구체적으로 있어야 한다.
- P4는 상위 계획에 들어 있어도 실행 직전에 별도 승인이 필요하다.
- 하위 에이전트와 외부 CLI는 호출한 부모가 가진 permission보다 높은 작업을 할 수 없다.
- 권한 밖 작업을 laptop, 다른 계정, 직접 API 같은 우회 경로로 실행하지 않는다.

## 4. 모델·추론 프로필

모델명은 영구 규칙이 아니라 **현재 mapping**으로 버전 관리한다. 모델이 교체되면 같은 역할의
후속 모델로 mapping을 갱신하되 과거 manifest는 수정하지 않는다.

| profile | 현재 기본 mapping | 용도 |
|---|---|---|
| `frontier_planning` | `gpt-5.6-sol`, `ultra` | 전체 연구 설계, 데이터 계약, 아키텍처, 최종 채택 판정 |
| `critical_engineering` | `gpt-5.6-sol`, `high` 또는 `xhigh` | DB 무결성, 보안, 동시성, production 배포 검수 |
| `standard_execution` | `gpt-5.6-terra`, `medium` 또는 `high` | 일반 구현, 테스트, 문서, 반복 조사 |
| `independent_review` | 작성자와 다른 모델 family 또는 독립 세션 | diff·실험 해석·위험 경계 교차검수 |
| `local_assistant` | manifest에서 고정한 local model | evidence 요약·후보 정리. 최종 행동·GT 판정 금지 |

Ultra는 모든 구현에 기본 사용하지 않는다. 다음 중 하나일 때 사용한다.

- 장기 연구 방향이나 dataset 계약을 결정할 때
- 되돌리기 어려운 아키텍처 선택
- 상충하는 증거의 최종 해석
- Critical/P3 작업의 마지막 독립 검수

정확한 모델을 runtime이 제공하지 못하면 대체 모델을 조용히 사용하지 않는다. `requested_model`,
`actual_model`, `requested_reasoning`, `actual_reasoning`, fallback 이유를 manifest와 보고서에 기록한다.
모델 identity를 확인할 API나 runtime 증거가 없으면 추측하지 않고 `unverified`로 쓴다.

## 5. Run manifest 계약

모든 Standard 이상 연구·구현 작업은 시작 전 다음을 고정한다.

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

## 6. 비밀값·인증

- 비밀번호, API key, webhook, session cookie, signed URL은 계약·manifest·로그에 기록하지 않는다.
- 문서에는 `capability_available`, credential source 이름, 만료 여부만 기록한다.
- 사용자에게 받은 비밀번호를 다른 세션이나 모델에 전달하지 않는다.
- 인증이 필요하면 기존 OS keychain, environment, approved connector를 사용한다.
- 인증 실패를 해결하려고 권한·host guard·RLS를 약화하지 않는다.

## 7. 장기·원격 실행

- Desktop 앱은 연구 지휘자이며 daemon이 아니다. 반복 실행은 LaunchAgent 또는 durable job runner가
  담당한다.
- Mac mini의 job은 앱·MacBook 연결이 끊겨도 진행 상태를 ledger와 파일에 기록한다.
- heartbeat는 상태가 바뀌지 않으면 알림하지 않는다.
- 승인 요청, BLOCKED, rollback, integrity failure, 완료 상태만 즉시 보고한다.
- 재부팅 뒤 manifest·ledger·repo HEAD로 안전하게 resume하거나 fail-closed한다.
- 동일 branch/worktree를 두 머신·두 agent가 동시에 수정하지 않는다.

## 8. 검증·보고

최종 보고에는 최소한 다음을 포함한다.

- requested/actual model과 reasoning
- 시작·최종 commit, upstream, tracked/untracked 상태
- 사용한 permission 등급과 실제 mutation
- 실행한 검증 명령과 결과
- dataset split과 표본 범위
- 비용·token·wall time 또는 `not-measured`
- 미검증 항목과 다음 허용 행동

`IMPLEMENTED_UNVERIFIED`, `PREVIEW_VERIFIED`, `DEPLOYED_VERIFIED`, `RESEARCH_ADOPTED`를 구분한다.
도구가 없다는 이유만으로 BLOCKED를 남발하지 않되, 동등한 검증 없이 VERIFIED를 주장하지 않는다.

## 9. 실패·중단 규칙

다음은 자동 중단하고 Owner에게 보고한다.

- manifest HEAD·repo·host mismatch
- dataset split leakage 또는 media hash mismatch
- 허용되지 않은 production/GT/behavior/app/R2 mutation
- secret 또는 개인식별정보 출력
- model identity·prompt·sampler drift
- budget·deadline 초과
- rollback·cleanup·residue 검증 실패

일반 테스트 실패와 구현 결함은 P0~P2 범위에서 최대 세 번 진단·수정한다. 같은 blocker가 반복돼
안전한 진전이 없을 때만 BLOCKED로 보고한다.

## 10. 구현 범위

이 설계 승인 후 한 구현계획에서 다음만 수행한다.

1. `docs/research/AI-OPERATING-CONTRACT.md` 작성
2. `docs/research/RUN-MANIFEST.schema.json` 작성
3. `docs/research/RUN-MANIFEST.example.json` 작성
4. schema validator와 최소 계약 테스트 추가
5. `AGENTS.md`, `CLAUDE.md`, RBA 연구 시스템 v1 문서에 짧은 링크 추가
6. 중앙 카탈로그에 운영 계약 등록

Mac mini 이전, model benchmark, dataset inventory, production 배포는 이 구현 범위가 아니다. 계약
구현·검증이 끝난 뒤 R1 Mac mini research runtime foundation으로 넘어간다.

## 11. 완료 조건

- P0~P4와 preauthorization 경계가 모순 없이 정의됨
- 현재 모델 profile과 fallback 기록 계약이 있음
- manifest가 repo/model/permission/data/budget/stop 조건을 기계 검증함
- 실제 secret·credential 필드가 schema에 없음
- AGENTS/CLAUDE 진입점 증가가 짧은 링크 수준임
- 기존 agent execution contract와 destructive-action 규칙을 약화하지 않음
