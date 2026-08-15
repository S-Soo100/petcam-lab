---
handoff_version: 1
task_id: yolo26n-v25-gme-active-shadow
execution_repo: /Users/baek/.codex/worktrees/d1a4/petcam-lab
plan_path: /Users/baek/.codex/worktrees/d1a4/petcam-lab/docs/superpowers/plans/2026-08-15-yolo26n-v25-gme-active-shadow.md
design_path: /Users/baek/.codex/worktrees/d1a4/petcam-lab/docs/superpowers/specs/2026-08-15-yolo26n-v25-gme-active-shadow-design.md
commit_sha: 0597b7d510b20bfdfd085e86feb6cf5efff05222
implementation_host: baek-macbook
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.gme-worker
---

# YOLO26n v2.5 GME Active Shadow Runtime Handoff

## Tracked implementation inputs

- petcam-lab implementation commit: `0597b7d510b20bfdfd085e86feb6cf5efff05222`
- gecko-vision-gate commit: `1ce7648c16156b840ce753e251a2801b9ff0d9da`
- petcam-nightly-reporter commit: `24cc5b26d6d9d5a8897669325e22643741150c88`
- model checkpoint SHA-256: `2b128f105e898bc472ed66861583ab80007dae6e94b291db497d7a2f8081f84a`
- detector execution identity: `d4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6`
- threshold freeze SHA-256: `3d1f65f8d5034010add7210ada7cbad9f48ca329646ab021e5a428470f6949f9`

각 dependency SHA는 runtime host에서 exact checkout하고 local `git show` bytes와 대조한다. model/freeze는
기존 private v2.5 attempt에서 read-only로 가져오며 Slack·Git·로그에 파일 자체를 첨부하지 않는다.

## Runtime contract

- execution repo: `/Users/baek-end/petcam-nightly-reporter`
- Gate repo: `/Users/baek-end/myPythonProjects/gecko-vision-gate`
- lab repo: `/Users/baek-end/petcam-lab`
- model source: `/Users/baek-end/private-rba/yolo26n-owner-dataset-v25/attempt-20260815-owner-v1/runs/warm-start/weights/best.pt`
- inference: raw confidence `0.001`, image size `960`, NMS IoU `0.70`, max detections `50`
- observation threshold: `0.20`
- job identity: model/version/checkpoint/schema/threshold execution SHA-256 (`d4654168...`)

## Ordered execution

1. 세 repository와 model/freeze SHA를 read-only 검증한다.
2. Gate/Nightly 전체 테스트와 local one-frame model smoke를 통과시킨다.
3. production-purpose 실제 영상 10개만 v2.5 smoke identity로 enqueue한다.
4. bounded one-shot worker로 10건을 처리하고 `10/10`, artifact `20/20`, temp `0`, forbidden write `0`을 독립 검수한다.
5. smoke acceptance 뒤에만 lab migration으로 신규 production live trigger identity를 v2.5로 바꾼다.
6. 신규 live lag p95가 900초 이내인지 확인한 뒤 저장 영상 backfill dry-run inventory를 만든다.
7. historical first batch 50건을 처리·검수하고, 정상일 때만 나머지 eligible 저장 영상을 bounded batch로 enqueue한다.

## Forbidden changes

- Flutter/API `activity-v1` 또는 사용자 노출 값 변경
- 사람 GT·행동명·하이라이트 수정
- 원본 R2 object 이동·삭제·덮어쓰기
- 영상 자동 skip·격리·삭제·부재 확정
- future holdout prediction 공개
- 기존 detector identity의 job/run/artifact 수정·삭제

실패하면 v2.5 신규 enqueue/worker만 중단하고 live trigger function을 이전 detector identity로 복원한다.
이미 생성된 v2.5 shadow 원장은 삭제하지 않는다.
