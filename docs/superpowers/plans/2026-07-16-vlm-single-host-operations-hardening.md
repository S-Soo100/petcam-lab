# VLM Single-Host Operations Hardening — Cross-Repo Handoff

> Bootstrap 상태: nightly의 plan/design이 아직 untracked라 새 validator 기준 `artifact_untracked`가 정상이다. 이 문서는 이미 시작된 사고 복구 handoff이며 `HANDOFF_OK`로 소급 가장하지 않는다. nightly plan/design commit/push 승인 후 manifest를 만들고 `HANDOFF_OK`를 확인해야 다음 cross-session handoff가 가능하다.

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
