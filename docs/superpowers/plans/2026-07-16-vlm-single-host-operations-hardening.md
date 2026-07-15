---
handoff_version: 1
task_id: vlm-single-host-operations-hardening
execution_repo: /Users/baek/petcam-nightly-reporter
plan_path: /Users/baek/petcam-nightly-reporter/docs/superpowers/plans/2026-07-16-vlm-single-host-operations-hardening.md
design_path: /Users/baek/petcam-nightly-reporter/specs/2026-07-16-vlm-single-host-operations-hardening-design.md
commit_sha: 95fa7e79be84f44c4d185fe4f0d1b34228aa8933
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.vlm-candidate-worker
---

# VLM Single-Host Operations Hardening — Cross-Repo Handoff

> Bootstrap 복구 완료: nightly plan/design과 Task 1~10 구현이 commit `95fa7e7`에 포함됐고, 이 manifest로 `HANDOFF_OK`를 검증한다. 이 성공은 전달 무결성만 뜻하며 Mac mini 배포·실행 완료를 뜻하지 않는다.

## 작업 레포

이 기능의 worker·launchd·Slack 구현 위치는 `petcam-lab`이 아니라 다음 레포다.

```text
/Users/baek/petcam-nightly-reporter
```

## 정본

반드시 아래 두 파일을 절대경로로 열어 전부 읽는다.

```text
/Users/baek/petcam-nightly-reporter/docs/superpowers/plans/2026-07-16-vlm-single-host-operations-hardening.md
/Users/baek/petcam-nightly-reporter/specs/2026-07-16-vlm-single-host-operations-hardening-design.md
```

두 파일이 실제로 존재하는지 먼저 확인한다. 하나라도 없으면 구현하지 말고 누락 경로를 보고한다.

## 실행 지시

```bash
cd /Users/baek/petcam-nightly-reporter
```

그 다음 `superpowers:executing-plans`를 사용해 정본 계획의 Task 1~10만 TDD로 실행한다.

다음은 사용자 추가 승인 전 금지한다.

- Task 11 production 전환 runbook 실행
- migration apply
- commit/push
- LaunchAgent bootout/bootstrap
- production Claude 호출
- DB settings 변경

기존 untracked reliability 초안, `.env.bak-*`, `storage/`, 영상 파일은 수정·삭제·커밋하지 않는다.

## cross-repo 예외

정본 Task 4가 요구하는 forward migration 파일만 `petcam-lab`에 작성할 수 있다. 그 외 구현은 `petcam-nightly-reporter`에서 수행한다.

```text
/Users/baek/petcam-lab/migrations/2026-07-16_clip_vlm_failure_diagnostic.sql
```

구현·전체 검증·코드 리뷰가 끝나면 정본 Task 10의 형식으로 보고하고 멈춘다.
