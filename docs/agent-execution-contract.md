# Agent execution contract

AI 에이전트가 구현은 끝냈지만 검수·통합·Preview 앞에서 반복해서 멈추는 일을 줄이기 위한 공통 계약이야.
`AGENTS.md`와 `CLAUDE.md`에는 요약만 두고, 상세 규칙은 이 문서를 정본으로 삼아.

## 1. 기본 실행 단위

사용자가 구현부터 반영까지 승인했다면 아래를 **한 작업**으로 본다.

1. 시작 상태와 handoff 검증
2. 구현과 테스트
3. 독립 리뷰와 발견 결함 수정
4. 전체 회귀·빌드·DB probe
5. 안전한 branch 통합
6. migration과 Preview 적용
7. 역할별 canary
8. 증거 기록과 최종 보고

중간 단계가 성공했다는 이유만으로 임의의 Stop Point를 만들지 않아. 새 권한이 필요하거나 아래 하드
중단 조건에 해당할 때만 멈춰.

## 2. 상태 이름

| 상태 | 뜻 |
|---|---|
| `IMPLEMENTED_UNVERIFIED` | 코드 작성만 끝남. 전체 테스트·빌드·runtime 증거 없음 |
| `REVIEWED_READY_FOR_INTEGRATION` | 독립 리뷰와 전체 회귀 통과. 아직 main·DB·Preview 미반영 |
| `PREVIEW_READY` | Preview build·migration probe·역할 canary가 통과. production 공개는 아직 아님 |
| `DEPLOYED_VERIFIED` | production SHA·deployment·DB 상태·실제 canary까지 확인 |
| `BLOCKED_<원인>` | 안전하게 우회할 방법이 없는 하드 중단. 원인과 재개 조건을 함께 기록 |

`tsc` 통과를 build 성공이라 부르거나, kickstart만 보고 자연 주기까지 검증했다고 부르는 식의 상태
상향은 금지해.

## 3. 하드 중단 조건

다음 중 하나일 때만 `BLOCKED_*`로 멈춰.

- 사용자에게서 받지 않은 새 권한이 필요함: production write, destructive git, 외부 공개 등
- 인증·호스트·비밀값이 없고 안전한 대체 경로도 없음
- 테스트·DB invariant·보안 계약이 깨짐
- 다른 세션의 dirty 파일과 충돌해 보존하면서 진행할 수 없음
- rollback 또는 fail-closed 경로가 증명되지 않음

로컬 Docker 부재, 세션 내 build hook 차단, 특정 CLI 실패는 그 자체로 blocker가 아니야. disposable
PostgreSQL, Vercel Preview build, 다른 read-only 검증처럼 **동등한 증거**가 있으면 계속 진행하고,
대체 증거의 한계는 보고서에 정확히 써.

## 4. 단계별 최소 증거

| 단계 | 필요한 증거 |
|---|---|
| 코드 | 관련 테스트 + 전체 회귀 + 타입/정적 검사 + `git diff --check` |
| DB | disposable/local DB 실실행 + rollback + residue 0 + 권한/RLS 검사 |
| build | 실제 `npm run build` 또는 동일 commit의 Vercel build 성공 |
| Preview | deployment READY + API probe + 역할별 화면/권한 canary |
| production | main SHA + deployment ID + migration 이력 + 실제 사용자 흐름 canary |
| runtime worker | 목표 host의 hostname + service 상태 + repo HEAD + 실제 run |

증거가 없는 단계는 미검증으로 남겨. 다른 단계의 성공으로 대신하지 않아.

## 5. Git·멀티세션

- 시작할 때 branch, HEAD, upstream, tracked/untracked 상태를 그대로 기록해.
- untracked 파일이 있으면 `clean`이라고 보고하지 않아.
- 사용자 변경이 있는 checkout에서는 merge하지 말고 clean worktree를 사용해.
- merge 뒤 전체 검증이 성공하기 전에는 worktree나 feature branch를 삭제하지 않아.
- branch 정리는 merge된 branch만 `git branch -d`로 하고, 원격 삭제는 사용자 요청 범위에 포함될 때만 해.
- 다른 세션 파일은 add·commit·delete·stash·reset하지 않아.

## 6. 보고 형식

완료 보고는 아래 순서로 짧게 써.

1. 최종 상태 이름
2. 실제 반영 범위와 현재 사용자 경험
3. 테스트·build·DB·canary 증거
4. main/production SHA와 배포 ID
5. 미검증 또는 남은 위험
6. 다음 자동 작업 또는 사용자에게 필요한 한 가지 행동

“코드는 끝났고 다음 승인을 기다린다”는 문구는 실제로 새 권한이 필요한 경우에만 사용해.
