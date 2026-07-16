# Activity Worker SOT Closure Design

## 목표

검증 완료된 `activity-worker` Mac mini 단일 호스트 이전을 petcam-lab의 현재 실행 SOT와 Python Evidence Hybrid 설계에 반영하고, 실행 지시·manifest·1차 보고·closure 보고를 Git 감사 기록으로 남긴다.

## 현재 사실

- 유일 runtime: Mac mini `baeg-endeuui-Macmini.local`
- service: `com.petcam.activity-worker`
- nightly runtime SHA: `cbd2e09ed00857bdbd8a27c3f0483881c9abdbd6`
- policy: `activity-v1`, `StartInterval=3600`, expected-host fail-closed
- MacBook: service/plist absent, decommissioned plist 백업 보존
- first cycle: `queried=88 / ok=88 / fail=0 / exit 0`
- natural second cycle: 미처리 0건, exit 0
- evidence: 7컬럼 결손 0, 중복 0, MacBook 이전 후 신규 기록 0
- exclusion settings와 `behavior_labels` 불변

## 정합화 대상

1. `specs/next-session.md`
   - 상단 현재 runtime 정본을 Mac mini single-host closure 상태로 교체한다.
   - 과거 intermediate 기록은 삭제하지 않고 `SUPERSEDED` history로 보존한다.
2. `docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`
   - activity-worker host와 current nightly runtime SHA를 교정한다.
   - 호스트 오배치 문제는 `RESOLVED`로 기록한다.
   - 전체 카메라·날짜별 evidence coverage는 아직 미측정이므로 S0 open question으로 유지한다.
   - selector 알고리즘 동결 기준 `b9dc9eb`은 runtime SHA와 다른 목적이므로 유지한다.
3. `docs/handoff-prompts/2026-07-16-activity-worker-single-host-*`
   - 검증된 네 산출물을 내용 수정 없이 tracked audit artifact로 전환한다.

## 변경 경계

- 문서만 변경한다.
- 코드, DB, migration, LaunchAgent, Slack, VLM, Gate, Flutter는 변경하지 않는다.
- 현재 worktree의 다른 세션 미추적 파일을 삭제·수정·commit하지 않는다.
- handoff 산출물 네 파일은 작업 전후 SHA-256이 같아야 한다.
- stage는 구현 계획에 명시된 6개 문서로 제한한다.

## 검증

- current SOT에서 `cbd2e09`, Mac mini activity-worker, MacBook absent, 자연 second cycle을 찾을 수 있어야 한다.
- stale current-state 표현은 0건이어야 하며 historical discovery 문맥만 허용한다.
- hybrid 설계에서 selector 기준 `b9dc9eb`은 유지돼야 한다.
- `tests/test_verify_agent_handoff.py`와 실제 manifest validator가 통과해야 한다.
- placeholder, whitespace, secret pattern 검사가 모두 통과해야 한다.

## 산출물

- SOT closure commit 1개
- Claude 실행 보고서:
  `/Users/baek/petcam-lab/docs/handoff-prompts/2026-07-16-activity-worker-sot-closure-report.md`
