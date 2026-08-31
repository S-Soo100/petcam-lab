---
handoff_version: 1
task_id: yolo26n-v26-claim-isolation-recovery
execution_repo: /Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab
plan_path: /Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/docs/superpowers/plans/2026-08-31-yolo26n-v26-production-normalization.md
design_path: /Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/docs/superpowers/specs/2026-08-31-yolo26n-v26-production-normalization-design.md
commit_sha: 795bd10630d008d86d90fd8b7b4d1d25b2558f3c
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.gme-worker
---

# YOLO26n v2.6 Claim Isolation Recovery Runtime Handoff

## 고정 구현 입력

- petcam-lab commit: `795bd10630d008d86d90fd8b7b4d1d25b2558f3c`
- petcam-nightly-reporter commit: `66827f226a31e30a144342eddfe2a3a7ba4ba86f`
- gecko-vision-gate commit: `ecddd4857c22005694197b7df4797b6053b920e2`
- pre-smoke migration: `migrations/2026-09-01_gme_detector_identity_claim_isolation.sql`
- production normalization migration: `migrations/2026-08-31_yolo26n_v26_gme_production_normalization.sql`
- detector identity: `89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7`
- checkpoint SHA-256: `a00e5a7a1e1f9197accb036339a38a7c821f03c8ab79611ebce89e5cde59b513`
- v2.5 service: `com.petcam.gme-worker`
- Mac mini lab runtime worktree: `/Users/baek-end/.codex/worktrees/yolo-v26-production-normalization/petcam-lab`
- Mac mini Nightly runtime worktree: `/Users/baek-end/.codex/worktrees/yolo-v26-production-normalization/petcam-nightly-reporter`
- Mac mini Gate runtime worktree: `/Users/baek-end/.codex/worktrees/yolo-v26-production-normalization/myPythonProjects/gecko-vision-gate`

구현 host와 runtime host는 다르다. 수신자는 Mac mini의 hostname, 세 runtime worktree의 clean HEAD,
model bytes와 checkpoint SHA, 현재 v2.5 LaunchAgent의 plist bytes·working directory·detector identity를
다시 확인한다. 하나라도 다르면 DB/service/R2 write 없이 멈춘다.

## 불변 incident 계약

최초 v2.6 smoke는 enqueue 10건과 idempotency까지 통과했지만 legacy claim RPC가 identity를 필터링하지
않아 v2.5 worker가 먼저 claim했다. 현재 v2.6 smoke 원장은 다음 aggregate와 정확히 일치해야 한다.

- total: 10
- `failed_terminal/invalid_metadata`: 10
- result run link: 0
- v2.6 run: 0
- queued/processing/retry/succeeded: 0

이 10건은 삭제·수정·requeue·덮어쓰기하지 않는다. 개별 job/clip/source/R2 key는 출력하지 않는다.

## 순서가 고정된 복구 계약

1. Mac mini runtime worktree를 위 세 commit으로 fast-forward하고 clean 상태를 확인한다.
2. Gate 전체, Nightly 전체, lab migration 관련 테스트를 실행한다. Nightly 기준은 `504 passed`, lab
   전체 기준은 `2552 passed, 5 skipped`이며 환경 차이는 실제 실패 원인과 함께 보고한다.
3. production DB에는 pre-smoke claim isolation migration만 먼저 적용한다. production normalization
   migration, live trigger, rate-limit table, web default는 아직 적용하지 않는다.
4. SELECT-only로 새 `fn_claim_gme_jobs_for_detector` body가 lease normalization, candidate selection, final
   claim 모두 `p_detector_identity`를 필터링하고 service-role only인지 확인한다. legacy
   `fn_claim_gme_jobs` body는 변경되지 않아야 한다.
5. 불변 incident aggregate를 다시 확인하고 v2.5 processing이 0일 때만 기존 service를 일시 bootout한다.
   bootout 뒤에도 processing이 생겼으면 recovery enqueue를 하지 않는다.
6. `enqueue_gme_smoke.py --recovery-after-claim-incident` dry-run은 기존 v2.6 job이 있는 clip을 제외한 다른
   eligible production 영상 정확히 10건을 선택해야 한다. aggregate 외 식별자는 출력하지 않는다.
7. `--apply`는 정확히 한 번만 실행하며 inserted가 10이 아니면 fail closed한다. 적용 뒤 같은 명령을
   다시 실행하지 않는다. total 20 상태는 selector가 새 enqueue를 거부해야 한다.
8. 새 Nightly code의 bounded v2.6 worker를 실행한다. 새 claim RPC는 v2.6 identity job만 가져가므로
   v2.5 live/historical job을 claim하지 않아야 한다.
9. `audit_gme_shadow.py`로 total 20, unique clip 20, incident terminal 10, recovery succeeded 10, run identity
   10, artifact key/SHA/bytes/HEAD 20, queued/processing/retry/other 0을 독립 확인한다.
10. 감사 성공·실패와 무관하게 기존 plist bytes·working directory·v2.5 identity로
    `com.petcam.gme-worker`를 즉시 bootstrap한다. loaded 상태와 v2.5 신규 live 처리 가능성을 read-only로
    확인한다.
11. recovery가 10/10일 때만 production normalization cutover를 다음 단계로 승인한다. 실패하면 세 번째
    smoke를 추가하거나 기존 20건을 고치지 않고, live trigger·web·HTTP worker를 그대로 둔다.

## 금지 동작

- incident 10건 또는 recovery job/run/artifact 삭제·수정·requeue·덮어쓰기
- recovery acceptance 전 production normalization migration 적용
- 원본 media/R2 object, 사람 GT, 라벨링 판정 수정
- v2.5 service plist 내용을 임의 변경하거나 다른 worktree로 교체
- 비밀값, raw result, clip/source ID, R2 key 출력
- 실패 후 임의의 세 번째 smoke cohort 생성
