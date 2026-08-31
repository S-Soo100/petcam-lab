---
handoff_version: 1
task_id: yolo26n-v26-production-normalization
execution_repo: /Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab
plan_path: /Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/docs/superpowers/plans/2026-08-31-yolo26n-v26-production-normalization.md
design_path: /Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/docs/superpowers/specs/2026-08-31-yolo26n-v26-production-normalization-design.md
commit_sha: 811b0ae4cb40707a4c90a4a01d198266eda2ad21
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.gme-worker
---

# YOLO26n v2.6 Production Normalization Runtime Handoff

## 고정 구현 입력

- petcam-lab 기준 commit: `811b0ae4cb40707a4c90a4a01d198266eda2ad21`
- gecko-vision-gate 구현 위치: `/Users/baek/.codex/worktrees/yolo-v26-production-normalization/myPythonProjects/gecko-vision-gate`
- gecko-vision-gate commit: `ecddd4857c22005694197b7df4797b6053b920e2`
- petcam-nightly-reporter 구현 위치: `/Users/baek/.codex/worktrees/yolo-v26-production-normalization/petcam-nightly-reporter`
- petcam-nightly-reporter commit: `d1985c8af9d7191bef3b3bf1707696ce03ebdb38`
- model version: `v2.6-warm-start-s28`
- checkpoint SHA-256: `a00e5a7a1e1f9197accb036339a38a7c821f03c8ab79611ebce89e5cde59b513`
- threshold freeze SHA-256: `8f8e02beb452ec2ddfdce344dff507294f56136c69224990c50552d22bb343a0`
- old regression report SHA-256: `3c99e7a2f6633c5c741ee3ed79bda1a52ab575a1cfa9318ca0bdb4583d9be8cb`
- detector execution identity: `89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7`
- GME service: `com.petcam.gme-worker`
- authenticated HTTP inference service: `com.petcam.yolo-http-worker`
- public worker hostname: `yolo-worker.tera-ai.uk`

구현 host는 `BaekBook-Pro-14-M5.local`, 실제 runtime host는
`baeg-endeuui-Macmini.local`이다. Mac mini의 checkout 경로는 미리 추측하지 않는다. 수신자는
read-only preflight에서 세 repository의 실제 경로·HEAD·upstream·dirty 상태를 확인하고, 위 commit과
일치하는 clean runtime worktree를 새로 준비하거나 기존 clean worktree를 사용한다. 경로·host·commit이
다르면 운영 write 없이 멈춘다.

## 순서가 고정된 실행 계약

1. Mac mini hostname, 디스크 여유, 현재 LaunchAgent, 기존 GME identity, repository 상태, migration 상태,
   v2.6 job 존재 여부를 read-only로 점검한다.
2. 정확한 세 commit으로 clean runtime worktree를 만들고 Gate·Nightly 테스트, lab web 테스트·typecheck·
   clean build를 수행한다. 구현 중 hook 때문에 생략된 web production build는 이 단계에서 사용자 터미널 또는
   동등한 clean runtime 환경으로 수행한다.
3. private model을 runtime 전용 immutable 위치로 복사하고 checkpoint SHA를 재계산한다. model load와
   one-frame local inference를 통과하기 전에는 production-purpose job을 만들지 않는다.
4. live trigger는 아직 바꾸지 않은 채 production-purpose smoke를 정확히 10건만 신규 v2.6 identity로 실행한다.
   기존 job·run·artifact를 수정, 삭제, 덮어쓰기, 재사용하지 않는다.
5. 별도 read-only 집계로 smoke `10/10 succeeded`, run 연결 `10/10`, 필수 artifact key/SHA 누락 `0`,
   retry/terminal failure `0`, identity·checkpoint·schema·threshold provenance 일치를 확인한다.
6. 위 acceptance 뒤에만 append-only DB migration, 두 LaunchAgent, tunnel, Vercel Preview를 적용한다.
   Preview canary를 통과한 뒤 production에 반영하고 신규 live job의 exact v2.6 identity와 사용자 화면을 확인한다.
7. live 우선순위를 유지한 채 historical first batch `50`을 처리·검수한다. 정상일 때만 나머지 저장 영상
   backfill을 bounded batch로 이어간다.
8. acceptance 실패 시 신규 v2.6 enqueue/worker를 중단하고 live trigger·service·tunnel·web을 직전 정상
   상태로 되돌린다. append-only smoke 원장과 실패 증거는 삭제하지 않는다.

## 운영 금지와 정보 보호

- smoke acceptance 전 production trigger cutover 금지
- 기존 v2.5/v2.6 job, run, artifact의 삭제·수정·덮어쓰기 금지
- 원본 R2 object, 사람 GT, 행동명, 하이라이트, 라벨링 판정 변경 금지
- automatic skip, 영상 부재 확정, 영상 삭제 근거로 사용 금지
- 비밀값, 원문 영상·이미지·GT, clip/source ID, R2 key, raw inference payload 출력 금지
- Git에 checkpoint, token, service-role key, tunnel credential 커밋 금지

모든 운영 단계는 design·plan의 acceptance와 rollback 계약을 그대로 따른다. 동등한 검증 없이 경고를
무시하거나 다음 단계로 넘어가지 않는다.
