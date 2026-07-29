# R1 Mac mini runtime P3 v14 24시간 재시작 보고

## 현재 판정

`R1_RUNTIME_P3_V14_RESTART_READY`

두 번째 planned external DB migration의 commit된 attestation을 확인하고 fresh runtime gate와
v14 immutable baseline을 만들었어. 이 초판에서는 새 marker가 아직 없으므로
`R1_RUNTIME_P3_RESTARTED_PENDING_24H`를 주장하지 않는다.

## 외부 변경 attestation

- primary HEAD / origin/main:
  `99cddbe0f990bbaaa546be15b22acd6a40e8673e`
- FF-only:
  성공
- 기존 dirty paths:
  9개 보존, incoming 교집합 0
- migration:
  `migrations/2026-07-29_news_comments_admin.sql`
- migration SHA-256:
  `3fe89db99d24016000b9cb67f3ad489c1212646018b42f439681e1e49473ddeb`
- 완료 보고서:
  `/Users/baek-end/petcam-lab/docs/handoff-prompts/2026-07-29-news-comments-admin-migration-report.md`
- 완료 보고서 SHA-256:
  `3b3da07fea4c2a23d0bb3b2ce57b82aa71a29c5b6d2efc28f78c99cec9266796`
- production verdict:
  `NEWS_COMMENTS_ADMIN_MIGRATION_APPLIED_VERIFIED`
- production probes:
  `8/8`
- actual REST UA fingerprints:
  `2/2`
- production probe residue:
  `0`

R1 재시작에서는 production DB를 직접 조회하거나 쓰지 않았고 commit된 보고서만
attestation으로 사용했다.

## v13 보존

- v13 종료 판정:
  `SUPERSEDED_PLANNED_EXTERNAL_DB_CHANGE`
- v13 종료 artifact:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-24h-superseded-v13.json`
- SHA-256:
  `a6ffbecf3621401834442bc4fcc2aca859652cf8fdb8869d9ef8f8a38a39792a`
- v13 경과 재사용:
  `false`

## fresh gates

runtime exact SHA
`7267b642dd9e25a0e199e57c5d41d1e2c04ee419`에서 실행했다.

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

## v14 immutable baseline

- artifact:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-production-immutable-baseline-v14.json`
- SHA-256:
  `8766a3fc481dfab294acd10df7d0cfb58742de3eb2fb24d0c1b6dd2c74c91cb3`
- mode:
  `0600`
- 생성 시각:
  `2026-07-29T21:03:47.580206+09:00`
- immutable services:
  7
- finalizer:
  absent

## service와 ledger

- label:
  `com.petcam.research-runtime`
- loaded:
  true
- WorkingDirectory:
  `/Users/baek-end/petcam-lab-research-runtime`
- runtime root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- runtime HEAD:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- baseline runs / last exit:
  `657 / 0`
- jobs / attempts:
  `16 / 22`
- queued/running:
  `0/0`
- provider calls / cost:
  `0/0`
- residue / drift:
  `0/0`

service를 중단, 재설치, kickstart하거나 plist를 변경하지 않았다.

## 다음 단계

이 보고서를 commit/push한 exact control SHA를 새 v14 marker에 기록하고 시작 시각부터 정확히
86400초를 계산한다. 그 뒤 v14 completion automation을 정확히 하나만 ACTIVE로 등록한다.

## Additive: v14 window 시작

pre-start 보고가 control SHA
`a7af3901b5ac4645446d3c436afb72dc24a29d63`로 commit/push된 뒤 fresh marker를 원자
기록했어.

- 최종 판정:
  `R1_RUNTIME_P3_RESTARTED_PENDING_24H`
- 시작 KST:
  `2026-07-29T21:05:05.213243+09:00`
- 시작 UTC:
  `2026-07-29T12:05:05.213243+00:00`
- 완료 예정 KST:
  `2026-07-30T21:05:05.213243+09:00`
- 완료 예정 UTC:
  `2026-07-30T12:05:05.213243+00:00`
- marker:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-24h-pending-v14.json`
- marker SHA-256:
  `ca25327ad56a4fb1522b80c2eda916808989e1d5f1117c76b8622bce5de742b6`
- marker mode:
  `0600`
- 시작 runs / last exit:
  `658 / 0`
- provider calls / cost:
  `0 / 0`
- jobs / attempts:
  `16 / 22`
- queued/running:
  `0/0`
- residue / drift:
  `0/0`
- completion automation ID:
  `r1-runtime-v14-24h-completion`
- R1 automation 목표 수:
  `1`

이 시각부터 86400초를 새로 센다. v13 경과 시간은 포함하지 않고 완료 예정 전에는
`DEPLOYED_VERIFIED`를 주장하지 않는다.
