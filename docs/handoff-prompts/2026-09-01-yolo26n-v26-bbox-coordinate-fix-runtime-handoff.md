---
handoff_version: 1
task_id: yolo26n-v26-bbox-coordinate-fix
execution_repo: /Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab
plan_path: /Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/docs/superpowers/plans/2026-09-01-yolo26n-v26-bbox-coordinate-fix.md
design_path: /Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/docs/superpowers/specs/2026-09-01-yolo26n-v26-bbox-coordinate-fix-design.md
commit_sha: 756106fae5e4a911212352d66abfa1177de8abca
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.gme-worker
---

# YOLO26n v2.6 bbox 좌표 계약 수정 Runtime Handoff

## 고정 입력

- petcam-lab commit: `756106fae5e4a911212352d66abfa1177de8abca`
- gecko-vision-gate commit: `634b9b6e574eab47961724e27a0498f4ab1f6430`
- petcam-nightly-reporter commit: `1a301ff58f7e7d8703d5cea3c5c865b7d89d4e9b`
- checkpoint SHA-256: `a00e5a7a1e1f9197accb036339a38a7c821f03c8ab79611ebce89e5cde59b513`
- 이전 detector identity: `89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7`
- 새 detector identity: `deccfc8315d3c00edb5bf59db3c573dca568e9d6d7a5da8d7dc93d2082bdb899`
- bbox coordinate contract: `xywh-top-left-v1`
- runtime service: `com.petcam.gme-worker`

## 현재 불변 상태

- 이전 identity worker는 의도적으로 정지되어 있다.
- 이전 identity의 queued, processing, succeeded, failed job과 모든 run/artifact는 감사 이력으로 보존한다.
- 새 identity migration, live trigger 전환, web active identity 전환은 아직 적용하지 않았다.

## 고정 실행 순서

1. Mac mini hostname과 세 runtime worktree 실제 경로·HEAD·upstream·clean 상태를 읽기 전용으로 확인한다.
2. 각 worktree를 위 commit으로 fast-forward하고 다시 clean인지 확인한다. 다른 변경이 있으면 중단한다.
3. checkpoint SHA와 local detector execution identity가 고정값과 일치하는지 DB/R2 접근 전에 확인한다.
4. Gate 전체 123개, Nightly 전체 511개 테스트를 실행한다. lab migration 테스트와 web 테스트·typecheck도 확인한다.
5. live trigger와 web identity를 이전 값으로 유지한 채 새 identity smoke만 생성한다. 문제 재현 영상과 주간·야간·반사 사례를 포함한다.
6. 새 worker는 identity-isolated claim RPC로 새 identity smoke만 처리한다.
7. job/run/artifact 연결, bbox coordinate provenance, checkpoint, failure 0을 확인하고 문제 영상의 박스를 실제 프레임과 수치·화면으로 대조한다.
8. canary 성공 시에만 migration을 적용해 신규 live enqueue를 새 identity로 바꾼다.
9. 신규 live 처리 성공 뒤 web active identity를 전환하고 라벨링 화면을 검증한다.
10. 그 뒤에만 저장 영상 전체를 새 identity로 append-only enqueue하고 live 우선 worker와 완료 감시를 재개한다.

## 금지 동작

- 기존 job/run/artifact 삭제·수정·재queue·덮어쓰기
- canary 성공 전 live trigger 또는 web active identity 전환
- 원본 영상/R2 object, 사람 GT, 라벨링 판정 변경
- 반사 박스 제거 또는 threshold/NMS/checkpoint 변경
- 비밀값, 원문 영상·이미지·GT, clip/source ID, R2 key 출력

실패 시 새 worker를 중지하고 신규 write를 멈춘다. 기존 결과를 고치거나 삭제하지 않고 집계와 원인만 보고한다.
