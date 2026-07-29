# R1 Mac mini runtime P3 v13 24시간 재시작 보고

## 현재 판정

`R1_RUNTIME_P3_V13_RESTART_READY`

계획된 외부 production DB 변경 완료 attestation을 확인하고 fresh runtime gate와 v13
immutable baseline을 만들었어. 이 초판 시점에는 새 24시간 marker와 completion automation을
아직 만들지 않았으므로 `R1_RUNTIME_P3_RESTARTED_PENDING_24H`를 주장하지 않는다.

## 외부 변경 attestation

- primary checkout:
  `/Users/baek-end/petcam-lab`
- origin/main과 primary HEAD:
  `12dcc6026885af7ed2a513ea00d540e3991f4d9f`
- FF-only:
  성공
- 기존 dirty paths:
  9개, 내용과 상태를 그대로 보존
- migration:
  `migrations/2026-07-29_news_articles.sql`
- migration SHA-256:
  `5d60520167da1723771b251048717da90fcc639698e0795840bfe86c44936939`
- 완료 보고서:
  `/Users/baek-end/petcam-lab/docs/handoff-prompts/2026-07-29-news-articles-migration-report.md`
- 완료 보고서 SHA-256:
  `934546f44a9fbef67dcb94f02504494fbe5e7db3b173952088a942090c7c1deb`
- 외부 판정:
  `NEWS_ARTICLES_MIGRATION_APPLIED_VERIFIED`
- 외부 production REST probe:
  `PROBE_RESIDUE=0`

R1 재시작 작업에서는 production DB를 직접 조회하거나 쓰지 않았고, commit된 완료 보고서만
외부 변경 attestation으로 사용했다.

## superseded window 보존

- 이전 판정:
  `SUPERSEDED_PLANNED_EXTERNAL_DB_CHANGE`
- 이전 종료 artifact:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-24h-superseded-v12.json`
- 이전 종료 artifact SHA-256:
  `8fa359e1dedcce2f7b9bed744c747857b5f8759b4e95c2f45afc991dfe6109d9`
- 이전 경과 시간 재사용:
  `false`

v12 baseline과 window는 수정하거나 다시 열지 않는다.

## fresh code gate

runtime exact SHA
`7267b642dd9e25a0e199e57c5d41d1e2c04ee419`에서 재검증했다.

```text
41 passed in 0.62s
R1_SIGKILL_RECOVERY_OK
R1_REBOOT_FENCING_OK
R1_STALE_EPOCH_OK
R1_SINGLETON_OK
R1_MONOTONIC_CLOCK_OK
R1_PRODUCTION_DEFER_OK
R1_STARVATION_BLOCK_OK
R1_DEADLINE_OK
R1_DISK_FAILURE_OK
R1_REDACTION_OK
R1_BOUNDED_TAIL_OK
R1_LEDGER_FAIL_CLOSED_OK
R1_CANCEL_CLEANUP_OK
R1_RESIDUE_ZERO
```

실제 runtime root verifier도 통과했다.

```text
R1_ATTEMPT_LEDGER_OK jobs=16 recovery_events=5
R1_ATTEMPT_PRODUCTION_BASELINE_OK services=7
R1_ATTEMPT_RESIDUE_ZERO
R1_ATTEMPT_VERIFIED
```

## v13 immutable baseline

- artifact:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-production-immutable-baseline-v13.json`
- SHA-256:
  `8afffc5737f7f734e2cda70821d9f67a3815067b75b83a7c0a1ab685af069fa7`
- mode:
  `0600`
- 생성 시각:
  `2026-07-29T18:31:13.384647+09:00`
- production immutable services:
  7
- expected-absent finalizer:
  absent
- production DB access by restart:
  0

## service와 local ledger

- label:
  `com.petcam.research-runtime`
- loaded:
  true
- state:
  interval 대기
- WorkingDirectory:
  `/Users/baek-end/petcam-lab-research-runtime`
- runtime root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- runtime HEAD:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- baseline snapshot runs:
  505
- last exit:
  0
- StartInterval:
  60초
- local jobs:
  16
- states:
  `blocked=1`, `succeeded=15`
- attempt 합계:
  22
- queued/running:
  `0/0`
- provider calls:
  0
- cost:
  0
- legacy root:
  absent

service를 중단, 재설치, kickstart하거나 plist를 변경하지 않았다.

## 다음 원자 단계

이 보고서를 commit/push한 exact control SHA를 fresh v13 24시간 marker에 기록한다. marker는
새 시작 시각과 정확히 24시간 뒤 완료 예정 시각을 mode 0600으로 원자 기록하고, 그 뒤 새
window 전용 completion automation을 정확히 하나만 만든다.

## Additive: v13 window 시작

pre-start 보고가 control SHA
`17423da81530114f2ca7ead3d0e09284d265513b`로 commit/push된 뒤 fresh marker를
원자 기록했어.

- 최종 시작 판정:
  `R1_RUNTIME_P3_RESTARTED_PENDING_24H`
- 시작 시각 KST:
  `2026-07-29T18:33:02.457813+09:00`
- 시작 시각 UTC:
  `2026-07-29T09:33:02.457813+00:00`
- 완료 예정 KST:
  `2026-07-30T18:33:02.457813+09:00`
- 완료 예정 UTC:
  `2026-07-30T09:33:02.457813+00:00`
- marker:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-24h-pending-v13.json`
- marker SHA-256:
  `5cf9c72d6b051579fb6bd9507a5b4882d0fe6baa9358acbc005dea1e70df3fbd`
- marker mode:
  `0600`
- 시작 runs:
  507
- last exit:
  0
- provider calls:
  0
- cost:
  0
- jobs/states/attempts:
  `16 / blocked=1+succeeded=15 / 22`
- queued/running:
  `0/0`
- residue:
  `R1_RESIDUE_ZERO`

이 시각부터 86400초를 새로 센다. superseded v12 window의 경과 시간은 포함하지 않는다.
completion automation ID는 `r1-runtime-v13-24h-completion` 하나만 사용한다.
