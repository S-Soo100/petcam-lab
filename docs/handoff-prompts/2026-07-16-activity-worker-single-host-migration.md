# Activity Worker Single-Host Migration — Claude 실행 지시서

> 이 문서는 휴대용 MacBook에서 잘못 실행 중인 `activity-worker`를 상시 가동 Mac mini로 안전하게 단일 이전하기 위한 실행 정본이야.

## 1. 실행 지시

이 문서 전체를 읽고 순서대로 바로 수행해. 사용자는 아래 범위의 코드 변경, 테스트, commit/push, MacBook LaunchAgent 중단, Mac mini 설치 및 첫 실사이클을 승인했어.

중간 승인을 다시 묻지 말고, 실제 외부 상태가 문서와 다르거나 안전 조건을 충족하지 못할 때만 fail-closed로 멈춰.

완료 또는 중단 결과는 반드시 다음 파일에 작성해:

`/Users/baek/petcam-lab/docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration-report.md`

채팅 응답에는 보고서 절대경로와 최종 판정만 짧게 남겨.

## 2. 목표와 완료 조건

`activity-worker`의 유일한 production runtime을 Mac mini로 이전해.

완료 조건은 모두 충족해야 해:

- MacBook: `com.petcam.activity-worker` absent
- Mac mini: `com.petcam.activity-worker` loaded
- 알려진 두 호스트 전체 loaded 수 정확히 1
- Mac mini에서 `activity-v1` 실사이클 최소 1회 완료
- 실제 처리 cycle은 `queried = ok`, `fail = 0`, exit code 0
- 잘못된 호스트나 expected host 미설정 상태에서는 DB/R2/detector 이전에 nonzero로 fail-closed
- 현재 DB exclusion 설정과 앱 effective activity 정책 불변

코드와 테스트만 통과하고 runtime 이전을 검증하지 못했다면 완료가 아니야.

## 3. 현재 실측 사실

### MacBook

- hostname: `BaekBook-Pro-14-M5.local`
- `com.petcam.activity-worker` loaded
- working directory: `/Users/baek/petcam-nightly-reporter`
- `ACTIVITY_POLICY_VERSION=activity-v1`
- `StartInterval=3600`, `RunAtLoad=true`
- 실행 이력: `runs=38`, 마지막 exit code 0
- 현재 checkout: `feat/vlm-basking-classification`
- 다른 세션의 미커밋 문서가 있으므로 기존 checkout을 수정·삭제·커밋하면 안 돼.

### Mac mini

- SSH alias: `home-mac`
- hostname: `baeg-endeuui-Macmini.local`
- repo: `/Users/baek-end/petcam-nightly-reporter`
- 시작 시 main HEAD와 origin 동기화를 다시 확인해.
- `com.petcam.activity-worker`는 현재 absent
- 기존 VLM, rolling backfill, finalizer, nightly reporter, router-features LaunchAgent는 변경 금지

### 실제 장애

MacBook 네트워크 불안 시 한 cycle에서 `queried 55 / ok 43 / fail 12`가 발생했어. `RemoteProtocolError`, `ConnectError`, DNS 오류가 있었지만 process가 exit 0이라 부분 실패가 정상처럼 기록됐어.

## 4. 작업 방식

다음 skill을 순서대로 사용해:

1. `superpowers:systematic-debugging`
2. `superpowers:using-git-worktrees`
3. `superpowers:writing-plans`
4. `superpowers:test-driven-development`
5. `superpowers:verification-before-completion`

운영 상태를 바꾸는 단계는 병렬로 실행하지 마.

기존 dirty checkout 대신 `origin/main` 기반 clean isolated worktree와 `fix/activity-worker-single-host` 브랜치를 사용해. 시작 당시 origin/main과 Mac mini main SHA를 40자리로 기록해.

다음 두 정본 문서를 실제 코드 확인 후 작성하고, 사용자가 Inline Execution을 이미 선택했으므로 계획 작성 후 바로 실행해:

- `specs/2026-07-16-activity-worker-single-host-design.md`
- `docs/superpowers/plans/2026-07-16-activity-worker-single-host-migration.md`

계획에는 실제 파일, 테스트, 명령, 예상 결과를 넣고 `TBD`, `TODO`, 추측 경로를 남기지 마.

## 5. 구현 계약

### 5.1 Activity host guard

- config에 `ACTIVITY_EXPECTED_HOST`를 추가해.
- 기존 `require_expected_host`를 검토하고 최소 변경으로 재사용해.
- `activity_worker`는 DB, R2, detector, Slack, policy-version guard보다 먼저 실제 hostname과 expected host를 비교해야 해.
- expected host가 비었거나 불일치하면 DB/R2/detector/Slack 호출 0회, 비밀값 없는 오류, nonzero exit로 종료해.

필수 RED→GREEN 테스트:

- hostname 일치 시 정상 진행
- expected host 공백 시 side effect 전 실패
- hostname 불일치 시 side effect 전 실패
- guard 실패 시 detector/load/download/store 호출 모두 0회

### 5.2 Installer hardening

`install-launchd-activity.sh`를 다음 계약으로 보완해:

- `ACTIVITY_EXPECTED_HOST` 누락 시 설치 중단
- 실제 hostname과 불일치 시 설치 중단
- 실제 hostname을 expected host로 자동 복사해 승인하는 코드 금지
- plist에 `ACTIVITY_EXPECTED_HOST=baeg-endeuui-Macmini.local`과 `ACTIVITY_POLICY_VERSION=activity-v1` 포함
- `plutil -lint` 실패 시 bootstrap 금지
- VLM/backfill installer는 수정 금지

필수 테스트:

- expected host 누락 실패
- hostname 불일치 실패
- 일치 시 정상 plist 생성
- plist host/policy/working directory 검증
- 자동 hostname 승인 코드가 없다는 정적 검사

### 5.3 Partial failure 관측성

- 성공한 clip 결과는 유지하되 clip 실패가 하나라도 있으면 cycle을 정상으로 숨기지 마.
- 최종 summary에 `queried/ok/fail`을 남기고 process는 nonzero로 끝내.
- 모든 clip이 성공했을 때만 exit 0이야.
- URL, secret, raw DB/HTTP exception 전문은 로그에 남기지 마.

필수 테스트:

- `ok=N, fail=0` → exit 0
- `ok>0, fail>0` → 성공 결과 유지 + nonzero
- 전부 실패 → nonzero
- 로그에 secret, 전체 URL, DB 원문 없음

## 6. 코드 검증과 Git

다음을 모두 실행해:

- 관련 targeted test의 RED 확인 후 GREEN
- nightly 전체 pytest
- `compileall`
- `bash -n install-launchd-activity.sh`
- 임시 HOME/stub launchctl을 사용한 plist fixture 검증
- `git diff --check`

모두 통과한 뒤 conventional commit으로 커밋해. `origin/main`이 작업 시작 이후 예상치 않게 변경됐으면 push하지 말고 중단해. fast-forward 가능한 경우에만 origin/main에 push하고 force push는 금지해.

## 7. Runtime handoff gate

최종 코드 commit 후 handoff manifest를 작성해:

- `task_id: activity-worker-single-host`
- `execution_repo`: clean worktree 절대경로
- `plan_path`, `design_path`: 위 두 문서 절대경로
- `commit_sha`: 최종 HEAD 40자리
- `implementation_host: BaekBook-Pro-14-M5.local`
- `runtime_kind: launchagent`
- `runtime_host: baeg-endeuui-Macmini.local`
- `runtime_label: com.petcam.activity-worker`

다음 명령에서 `HANDOFF_OK`를 확보하기 전에는 runtime 이전을 시작하지 마:

```bash
cd /Users/baek/petcam-lab
uv run python scripts/verify_agent_handoff.py --manifest <manifest-absolute-path>
```

## 8. 운영 이전 순서

### 8.1 Mac mini preflight

- SSH, hostname, repo HEAD, origin 동기화 확인
- 사용자 파일과 `.env.bak-*` 보존
- 필요한 env, checkpoint, Supabase, R2 접근 확인
- activity settings, assessment/prelabel 수, effective view 상태를 read-only baseline으로 기록
- 현재 exclusion 설정은 값과 무관하게 그대로 snapshot하고 변경하지 마.
- VLM/backfill과 충돌하지 않는 시점을 선택해.

### 8.2 Mac mini 코드 준비

- 최종 origin/main을 pull해 40자리 HEAD를 검증해.
- installer를 실제 bootstrap 전에 render/lint 방식으로 검증해.
- expected host는 `baeg-endeuui-Macmini.local`을 명시적으로 전달해.

### 8.3 MacBook 중단

- 기존 plist를 timestamp가 포함된 백업 디렉터리로 비파괴 이동해.
- `launchctl bootout` 후 plist absent, service absent를 확인해.
- 백업을 삭제하지 마.

### 8.4 Mac mini 설치

- MacBook absent 확인 후에만 bootstrap해.
- plist lint, expected host, policy, working directory를 검증해.
- 두 호스트 전체 loaded 수가 정확히 1인지 확인해.

### 8.5 첫 실사이클

- RunAtLoad 또는 kickstart로 1회 실행하고 종료까지 polling해.
- `queried > 0`인 실제 cycle을 검증해.
- 처리 대상이 0이면 DB 근거를 제시하고 다음 자연 cycle 전까지 verified라고 주장하지 마.

첫 cycle acceptance:

- hostname Mac mini
- policy `activity-v1`
- exit code 0
- `queried = ok`, `fail = 0`
- detector/checkpoint 정상 로드
- assessment/prelabel 증분과 처리량 정합
- 7컬럼 evidence identity 결손 0
- 중복 evidence 0
- exclusion settings와 앱 effective policy 불변
- `behavior_labels`, GT, `clip_vlm_jobs` 변경 0
- 임시 mp4/frame 0
- 로그의 secret/원문 URL 0

## 9. 중단·rollback 계약

- Mac mini preflight 실패 전에는 MacBook을 끄지 마.
- MacBook 중단 후 Mac mini 설치나 실행이 실패하면 이중 실행 방지를 위해 MacBook을 자동 복구하지 마.
- 실패한 Mac mini 서비스를 bootout하고, MacBook plist 백업은 보존한 채 증거와 함께 중단해.
- DB setting이나 exclusion switch 변경으로 우회하지 마.
- 데이터 삭제, `reset --hard`, force push 금지.

## 10. SOT 범위

검증된 최종 상태만 `petcam-nightly-reporter/specs/next-session.md`에 반영해:

- activity-worker runtime = Mac mini
- MacBook activity-worker = absent
- hostname, service label, final HEAD, 첫 cycle 결과

`petcam-lab`의 현재 dirty 설계 및 next-session 파일은 다른 세션 소유라 수정·삭제·커밋하지 마. 최종 보고서에 petcam-lab SOT에 반영해야 할 정확한 문구를 별도 블록으로 작성해. Codex가 독립 검수 후 반영할 거야.

Python Evidence Hybrid selector, VLM batch, Gate threshold, DB schema는 이 작업에서 변경 금지야.

## 11. 보고서 필수 형식

`2026-07-16-activity-worker-single-host-migration-report.md`에 다음 순서로 작성해:

1. 최종 판정: VERIFIED / BLOCKED / FAILED
2. 원인과 기존 오배치 증거
3. 변경 파일과 구현 계약
4. RED→GREEN 및 전체 테스트 결과
5. commit SHA와 push 상태
6. `HANDOFF_OK` 전문과 manifest 절대경로
7. MacBook 최종 plist/launchctl 상태와 백업 경로
8. Mac mini hostname/HEAD/plist/launchctl 상태
9. 첫 실사이클 `queried/ok/fail/exit/runtime`
10. DB pre/post 및 금지 테이블 불변 증거
11. settings와 앱 effective policy 불변 증거
12. temp media 0 및 secret leak 0 증거
13. 아직 검증되지 않은 항목
14. rollback 절차
15. petcam-lab SOT 정정 문구

보고서에는 secret, 전체 URL, 토큰, UUID 원문을 넣지 마.
