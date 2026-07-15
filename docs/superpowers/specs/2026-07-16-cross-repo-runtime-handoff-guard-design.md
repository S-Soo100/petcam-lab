# Cross-Repo·Runtime Host Handoff Guard 설계

> 상태: 구현·검증 완료, main 반영
> 작성일: 2026-07-16
> 적용 범위: petcam 관련 모든 cross-repo 작업과 background/원격 runtime 작업

검증 기록: handoff 전용 45 tests, petcam-lab 전체 381 tests, Python syntax와 whitespace 검사를 통과했다. 현재 nightly plan/design bootstrap은 의도대로 `HANDOFF_FAIL code=artifact_untracked`이며, 이를 `HANDOFF_OK`로 우회하지 않았다.

## 1. 배경

2026-07-16에 두 종류의 운영 오류를 확인했다.

1. 구현 계획서를 `petcam-nightly-reporter`에 만들고도 다른 Claude 세션에는 `petcam-lab` 상대경로만 전달했다. Claude는 올바르게 현재 레포를 검색했지만 파일을 찾을 수 없었다.
2. Mac mini에서 실행돼야 할 정규 VLM candidate worker가 MacBook에서 실행됐다. SOT에는 Mac mini 운영 중이라고 기록돼 있었지만 실제 LaunchAgent host 검증이 선행되지 않았다.

두 오류의 공통 원인은 **파일·레포·runtime host를 주장만 하고 handoff 전에 기계적으로 검증하지 않은 것**이다.

## 2. 목적

앞으로 다른 에이전트나 다른 머신에 작업을 넘길 때 다음을 자동으로 증명한다.

- 계획서와 설계서가 실제로 존재한다.
- 계획서가 의도한 실행 레포에 속한다.
- 다른 세션에서도 볼 수 있는 tracked commit 상태다.
- 전달한 commit SHA와 실제 레포 HEAD가 일치한다.
- 구현을 수행하는 host와 production service가 실행될 host가 구분돼 있다.
- worker 운영 상태는 실제 host·LaunchAgent 증거가 있을 때만 `verified`로 기록된다.

## 3. 접근안

채택안은 **규칙 + 기계 검증 + SOT 증거 계약**의 3중 방어다.

### 3.1 문서 규칙

`AGENTS.md`와 `CLAUDE.md`에 cross-repo handoff preflight를 공통 규칙으로 추가한다. 에이전트가 계획서를 읽기 전에 올바른 레포로 이동하게 만든다.

### 3.2 기계 검증

`scripts/verify_agent_handoff.py`가 handoff manifest의 파일·git·host 계약을 검사한다. 검증 실패 시 handoff 메시지를 보내거나 구현을 시작하지 않는다.

### 3.3 SOT 증거 계약

background worker 상태를 `planned`, `installed`, `enabled`, `verified`로 분리한다. 증거 없이 상위 상태를 쓰지 않는다.

## 4. Handoff manifest 계약

모든 cross-repo 구현 handoff 문서는 YAML front matter로 다음 필드를 가져야 한다.

```yaml
---
handoff_version: 1
task_id: vlm-single-host-operations-hardening
execution_repo: /Users/baek/petcam-nightly-reporter
plan_path: /Users/baek/petcam-nightly-reporter/docs/superpowers/plans/2026-07-16-vlm-single-host-operations-hardening.md
design_path: /Users/baek/petcam-nightly-reporter/specs/2026-07-16-vlm-single-host-operations-hardening-design.md
commit_sha: 0123456789abcdef0123456789abcdef01234567
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.vlm-candidate-worker
---
```

### 4.1 필수 필드

공통:

- `handoff_version`
- `task_id`
- `execution_repo`
- `plan_path`
- `design_path`
- `commit_sha`
- `implementation_host`
- `runtime_kind`

`runtime_kind != none`일 때 추가 필수:

- `runtime_host`
- `runtime_label`

### 4.2 값 계약

- 경로는 `~`나 상대경로가 아니라 정규화된 절대경로다.
- `execution_repo`는 실제 Git root다.
- `execution_repo` 자체도 symlink가 아니며 입력 절대경로와 realpath가 일치해야 한다.
- plan과 design은 `execution_repo` 하위의 일반 파일이다. symlink로 repo 밖 파일을 우회하지 않는다.
- `commit_sha`는 40자리 lowercase Git object id다.
- `implementation_host`는 계획·코드 작성 host다.
- `runtime_host`는 service 설치·실행 host다. 두 값이 같아도 각각 명시한다.
- `runtime_kind` 허용값은 `none`, `launchagent`, `server`, `scheduled-job`, `mobile-build`다.
- background service가 아니면 `runtime_kind: none`을 명시하고 runtime host/label은 비운다.

## 5. Validator CLI

### 5.1 인터페이스

```bash
uv run python scripts/verify_agent_handoff.py \
  --manifest /absolute/path/to/handoff.md
```

성공 시 exit 0과 안전한 요약을 출력한다.

```text
HANDOFF_OK task=vlm-single-host-operations-hardening repo=petcam-nightly-reporter commit=01234567 runtime=launchagent@baeg-endeuui-Macmini.local
```

실패 시 nonzero와 allowlisted code만 출력한다.

```text
HANDOFF_FAIL code=plan_missing
```

### 5.2 검증 순서

1. manifest 존재·일반 파일
2. front matter parse·schema version
3. 필수 field·enum·SHA 형식
4. `execution_repo` 존재·Git root 일치
5. plan/design 존재·일반 파일·repo 내부 realpath
6. plan/design이 Git tracked인지 확인
7. plan/design이 지정 commit에 포함되는지 확인
8. repo HEAD와 `commit_sha` 일치
9. working tree에서 plan/design에 미커밋 수정이 없는지 확인
10. runtime kind별 host/label 계약

첫 실패에서 멈추되 raw subprocess stderr나 전체 local path를 일반 출력에 재노출하지 않는다. 상세 진단은 safe code와 validator 내부 test로 구분한다.

front matter는 string·integer scalar만 필요한 제한된 계약이므로 PyYAML 의존성을 추가하지 않는다. 표준 라이브러리로 `---` 경계와 `key: value`를 엄격히 파싱하고, 중복 key·중첩 구조·알 수 없는 key를 거부한다.

### 5.3 실패 코드

- `manifest_missing`
- `manifest_invalid`
- `unsupported_version`
- `required_field_missing`
- `invalid_runtime_kind`
- `invalid_commit_sha`
- `repo_missing`
- `repo_not_git_root`
- `plan_missing`
- `design_missing`
- `artifact_outside_repo`
- `artifact_symlink`
- `artifact_untracked`
- `artifact_not_in_commit`
- `head_mismatch`
- `artifact_dirty`
- `runtime_host_missing`
- `runtime_label_missing`
- `git_probe_failed`
- `unexpected_field`
- `runtime_field_forbidden`

## 6. Git visibility 정책

다른 세션에 넘길 계획서와 설계서는 반드시 tracked commit에 포함돼야 한다.

- untracked 계획서 handoff 금지
- staged-only handoff 금지
- working-tree 수정본 handoff 금지
- SHA 없는 “최신 main” 표현 금지
- `--allow-untracked`, `--force`, `--skip-git-check` 우회 옵션을 만들지 않는다.

계획서가 아직 미커밋이면 순서는 다음과 같다.

1. 사용자 설계·계획 검토
2. 사용자 commit/push 승인
3. 계획서와 설계서 commit/push
4. validator 통과
5. 다른 세션에 handoff

### 6.1 최초 도입 bootstrap

이번 오류 당시 만든 VLM plan/design은 아직 untracked이므로 validator를 구현한 직후에는 의도적으로 `artifact_untracked`가 나와야 한다. 이를 성공으로 우회하지 않는다.

1. validator와 규칙 구현·전체 테스트
2. 사용자에게 현재 VLM plan/design을 포함한 정확한 commit 범위를 보고
3. 사용자 commit/push 승인
4. nightly plan/design을 먼저 commit/push
5. 그 SHA를 handoff manifest에 기록
6. validator `HANDOFF_OK` 확인

즉, validator 구현 완료와 현재 VLM handoff 검증 완료는 별도 상태로 보고한다.

## 7. 구현 host와 runtime host

### 7.1 개념 분리

- implementation host: 에이전트가 코드·문서를 수정하는 머신
- runtime host: LaunchAgent/server/job이 실제 실행되는 머신

MacBook에서 코드를 작성하는 것은 허용된다. Mac mini용 service를 MacBook LaunchAgent에 설치하는 것은 허용되지 않는다.

### 7.2 실행 전 증거

runtime 변경 전 handoff/runbook에 다음 명령과 기대값을 기록한다.

```bash
hostname
launchctl print "gui/$(id -u)/<label>"
plutil -p "$HOME/Library/LaunchAgents/<label>.plist"
```

원격 host면 SSH 명령 자체보다 결과의 다음 필드를 보고한다.

- actual hostname
- expected hostname
- service label
- loaded/not loaded
- executable working directory
- configured schedule
- repo HEAD

### 7.3 runtime code guard 관계

manifest validator는 handoff 전 정적 검증이다. 실제 worker의 `VLM_EXPECTED_HOST` fail-closed guard는 runtime 검증이다. 두 검증은 대체 관계가 아니라 둘 다 필요하다.

이번 구현은 Claude가 진행 중인 `petcam-nightly-reporter` worker 파일을 수정하지 않는다. 해당 runtime guard 구현과 충돌하지 않는다.

## 8. Worker 상태 SOT 계약

상태 정의:

| 상태 | 필요 증거 |
|---|---|
| `planned` | 승인된 설계·계획 |
| `installed` | 목표 host의 plist/service definition 존재 |
| `enabled` | 목표 host에서 scheduler/service loaded |
| `verified` | 목표 host의 실제 run 성공 + 결과 저장/관측 확인 |

금지:

- plist 파일만 보고 `enabled`라고 기록
- MacBook smoke 성공을 Mac mini `verified`로 기록
- DB 성공 row만 보고 producer host를 추측
- 과거 메모리를 live 상태처럼 현재형으로 기록

`verified` 보고 필수 항목:

- 검증 시각과 timezone
- expected/actual hostname
- service label
- run id 또는 safe identifier
- last exit/status
- 결과 count
- 다음 rollback 명령

## 9. 현재 SOT 정정

`specs/next-session.md`의 “Mac mini candidate worker 운영 중” 문구를 확인된 사실로 고친다.

정정 내용:

- 기존 기록은 잘못된 host attribution이었다.
- 정규 candidate worker는 MacBook에서 실행된 사실이 확인됐다.
- Mac mini의 historical backfill worker가 정규 failed jobs를 교차 처리한 정황이 있다.
- Mac mini 단일-host 이전과 queue ownership 하드닝은 계획/구현 중이다.
- 실제 Mac mini `verified` 상태는 host guard·handoff·한-window canary 통과 후에만 기록한다.

과거 오류를 삭제하지 않고 “정정됨”으로 남겨 원인과 재발 방지 근거를 보존한다.

## 10. 에이전트 규칙

### 10.1 AGENTS.md

Codex와 범용 agent에 다음을 강제한다.

- cross-repo handoff 전에 validator 실행
- validator 성공 전문을 handoff 메시지에 포함
- 상대경로만 전달 금지
- runtime 작업은 implementation/runtime host 분리
- 운영 완료 주장 전에 목표 host evidence 확인

### 10.2 CLAUDE.md

Claude에게 동일 계약을 추가하되 자동 로드되는 진입부에서 찾기 쉬운 위치에 둔다.

- 존재하지 않는 계획을 추측 구현하지 않는 기존 행동은 올바른 fail-closed로 유지한다.
- 계획이 없으면 현재 repo만 검색하고 끝내지 말고 manifest가 명시한 execution repo를 확인한다.
- manifest validator가 실패하면 구현을 중단한다.

## 11. 테스트 전략

`tests/test_verify_agent_handoff.py`에서 실제 임시 Git repo를 생성해 subprocess behavior를 검증한다. Git 자체를 전부 mock하지 않는다.

### 11.1 성공

- tracked plan/design
- HEAD와 SHA 일치
- clean artifacts
- runtime none
- launchagent with host/label

### 11.2 경로 오류

- manifest missing
- plan missing
- design missing
- execution repo가 실제 root의 하위 디렉터리
- 상대경로
- symlink로 repo 밖 탈출
- `..` realpath 탈출

### 11.3 Git 오류

- untracked plan
- staged-only plan
- artifact dirty
- SHA format invalid
- HEAD mismatch
- artifact가 현재 tracked지만 지정 commit에는 없음

### 11.4 runtime 오류

- launchagent runtime host 누락
- launchagent label 누락
- runtime kind가 none인데 runtime host/label이 존재하면 `runtime_field_forbidden`
- 알 수 없는 field와 중복 key
- 구현 host와 runtime host가 같아도 명시돼 있으면 허용

### 11.5 출력 안전

- 실패 stdout에 전체 home path 미노출
- git stderr 미노출
- manifest의 임의 문자열/control character 미반영

## 12. 사용자 체험 흐름

`[작성]` 사용자가 다른 Claude/Codex에 넘길 plan을 승인한다.

`[검증]` agent가 validator를 실행한다.

`[성공]` `HANDOFF_OK` 한 줄과 함께 정확한 repo·commit·runtime host가 고정된다.

`[전달]` 수신 agent는 manifest를 읽고 정확한 execution repo로 이동한다.

`[운영]` runtime 작업은 목표 host에서만 실행되고 host evidence를 보고한다.

`[감정]` 사용자는 “파일이 왜 없지?”, “어느 맥에서 돌고 있지?”를 다시 추적하지 않아도 된다.

## 13. 변경 파일

Create:

- `scripts/verify_agent_handoff.py`
- `tests/test_verify_agent_handoff.py`
- `docs/handoff-prompts/_agent-task-handoff-template.md`
- `docs/superpowers/plans/2026-07-16-cross-repo-runtime-handoff-guard.md`

Modify:

- `AGENTS.md`
- `CLAUDE.md`
- `specs/next-session.md`
- `.claude/donts-audit.md`
- 현재 VLM handoff 진입 문서의 bootstrap 실패 상태 설명

Do not modify:

- `petcam-nightly-reporter/reporter/*`
- nightly launchd installer
- production DB
- 실제 LaunchAgent 상태

## 14. 완료 조건

- validator의 성공·실패 계약이 TDD로 검증된다.
- 모든 cross-repo handoff에 적용할 규칙이 AGENTS/CLAUDE 양쪽에 있다.
- handoff template에 필수 front matter가 있다.
- 현재 VLM handoff는 nightly plan/design이 commit되기 전까지 `artifact_untracked` bootstrap 상태로 명시된다. commit/push 승인 후 별도 manifest를 만들고 `HANDOFF_OK`를 확인한다.
- 잘못된 Mac mini SOT가 정정된다.
- nightly worker 구현 파일과 운영 상태는 변경하지 않는다.
- 전체 petcam-lab tests가 통과한다.
- 문서에 placeholder·모순·상대경로 기반 handoff가 없다.

## 15. 범위 밖

- 원격 SSH 자동 접속·service 변경
- LaunchAgent 설치/제거
- nightly worker host guard 구현
- GitHub Actions 도입
- 모든 과거 handoff 문서 일괄 migration
- 외부 중앙 orchestration service
