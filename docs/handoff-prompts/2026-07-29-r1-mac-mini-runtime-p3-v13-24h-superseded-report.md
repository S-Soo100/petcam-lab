# R1 Mac mini runtime P3 v13 24시간 측정창 종료 보고

## 판정

`SUPERSEDED_PLANNED_EXTERNAL_DB_CHANGE`

두 번째로 승인된 외부 production DB migration 전에 v13 측정창을 정상 종료했어. runtime
실패나 rollback이 아니며 24시간을 채우지 않았으므로 `DEPLOYED_VERIFIED`를 주장하지 않는다.

## 측정창

- 시작 KST:
  `2026-07-29T18:33:02.457813+09:00`
- 시작 UTC:
  `2026-07-29T09:33:02.457813+00:00`
- 원래 완료 예정 KST:
  `2026-07-30T18:33:02.457813+09:00`
- 종료 KST:
  `2026-07-29T20:49:29.425056+09:00`
- 종료 UTC:
  `2026-07-29T11:49:29.425056+00:00`
- 실제 경과:
  `8187`초
- 종료 사유:
  `second_approved_external_production_db_migration`
- failure / rollback:
  `false / false`

## service 불변

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
- runs:
  시작 `507` → 종료 `643`
- last exit:
  `0`
- StartInterval:
  `60`초
- target plist SHA-256:
  `c5847755d5198902e0a69c83de8ffc56dfe38f0c7a9b09b73abcefe67bff0fd6`
- service action:
  `none`

service를 중단, 재설치, kickstart하거나 plist를 변경하지 않았다.

## 종료 snapshot

- local jobs:
  `16`
- states:
  `blocked=1`, `succeeded=15`
- attempt 합계:
  `22`
- queued/running:
  `0/0`
- provider calls:
  `0`
- cost:
  `0`
- production immutable services:
  `7`
- expected-absent finalizer:
  absent
- legacy root:
  absent
- residue:
  `0`
- drift:
  `0`
- production DB/R2/media/dataset/model/provider 접근:
  `0`
- production/research service mutation:
  `0/0`

## 고정한 v13 증거

- v13 marker:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-24h-pending-v13.json`
- marker SHA-256 / mode:
  `5cf9c72d6b051579fb6bd9507a5b4882d0fe6baa9358acbc005dea1e70df3fbd / 0600`
- v13 baseline:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-production-immutable-baseline-v13.json`
- baseline SHA-256 / mode:
  `8afffc5737f7f734e2cda70821d9f67a3815067b75b83a7c0a1ab685af069fa7 / 0600`

기존 marker와 baseline은 수정하지 않았다.

## 종료 artifact

- path:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-24h-superseded-v13.json`
- SHA-256:
  `a6ffbecf3621401834442bc4fcc2aca859652cf8fdb8869d9ef8f8a38a39792a`
- mode:
  `0600`
- marker:
  `SUPERSEDED_PLANNED_EXTERNAL_DB_CHANGE`

## completion automation

- 삭제 ID:
  `r1-runtime-v13-24h-completion`
- 현재 R1 automation:
  `0`

delegated task에서는 공식 automation control-plane이 local-task 제한으로 삭제를 거부했어.
사용자 승인에 따라 persisted automation 파일만 제거하고 directory 부재와 R1 automation 0을
확인했다. service와 production system에는 영향이 없다.

## 새 baseline 재시작 절차

1. 두 번째 외부 migration owner가 적용·검증 완료와 probe residue 0을 commit된 보고서로
   확정한다.
2. 별도 승인된 재시작 세션에서 그 보고서를 외부 attestation으로 읽고 production DB에는
   직접 접근하지 않는다.
3. 현재 service/checkout exact 값과 fresh runtime suite, adversarial markers,
   `R1_RESIDUE_ZERO`를 다시 검증한다.
4. v13 marker/baseline/경과 시간을 재사용하지 않고 새 versioned immutable baseline과
   시작 marker를 mode 0600으로 만든다.
5. 새 시작 시각부터 86400초를 계산하고 completion automation을 정확히 하나만 등록한다.
