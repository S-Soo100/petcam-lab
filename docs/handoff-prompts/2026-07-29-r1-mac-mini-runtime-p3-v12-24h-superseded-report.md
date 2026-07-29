# R1 Mac mini runtime P3 v12 24시간 측정창 종료 보고

## 판정

`SUPERSEDED_PLANNED_EXTERNAL_DB_CHANGE`

이 측정창은 runtime 실패가 아니라 계획된 외부 production DB 마이그레이션 때문에 조기
종료했어. 24시간을 채우지 않았으므로 `DEPLOYED_VERIFIED`를 주장하지 않는다.

## 측정창

- 시작:
  `2026-07-29T10:17:55.289345+09:00`
- 원래 완료 예정:
  `2026-07-30T10:17:55.289345+09:00`
- 종료:
  `2026-07-29T17:57:52.806612+09:00`
- 실제 경과:
  `27597`초
- 종료 사유:
  `planned_external_production_db_migration`
- 실패 여부:
  `false`

## 종료 시점 runtime

- label:
  `com.petcam.research-runtime`
- runtime SHA:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- WorkingDirectory:
  `/Users/baek-end/petcam-lab-research-runtime`
- runtime root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- service action:
  `none`
- service:
  loaded, interval 대기 상태
- runs:
  시작 `13` → 종료 `472`
- last exit code:
  `0`
- StartInterval:
  `60`초

요청대로 service를 bootout, 재설치, kickstart하거나 plist를 변경하지 않았다.

## zero-cost 종료 snapshot

- local ledger jobs:
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
- production DB/R2/media/dataset/model/provider 접근:
  `0`
- production service mutation:
  `0`
- research service mutation:
  `0`
- legacy root:
  absent

종료 직전 tracked attempt verifier도 통과했다.

```text
R1_ATTEMPT_LEDGER_OK jobs=16 recovery_events=5
R1_ATTEMPT_PRODUCTION_BASELINE_OK services=7
R1_ATTEMPT_RESIDUE_ZERO
R1_ATTEMPT_VERIFIED
```

## 고정한 기존 증거

- 24시간 시작 marker:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-24h-pending-v12.json`
- 시작 marker SHA-256:
  `ac996815ea3cbde8c46196dbc026a8f076396537dd762ed3bfb57c170ed00a9c`
- 시작 보고서 SHA-256:
  `58d70dee30b409e4d6d8990e88dc4e2c893e3cb73e07dfd3f3b1eac09bac808d`
- 시작 보고서 control SHA:
  `64f2dd17a5e4905546d2482b9b127b40db182663`
- reboot marker SHA-256:
  `d49998c58407ce4b3df38759ae15b3658438024f3f1b6aa30f4fa58d2a034e21`
- production baseline SHA-256:
  `6cc46dd064be109060790edb7c75fb06d6b9681e2a1bf5b768ab3231473d5775`
- target plist SHA-256:
  `c5847755d5198902e0a69c83de8ffc56dfe38f0c7a9b09b73abcefe67bff0fd6`

기존 marker와 tracked 보고서는 수정하지 않았다.

## 종료 artifact

- path:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-24h-superseded-v12.json`
- SHA-256:
  `8fa359e1dedcce2f7b9bed744c747857b5f8759b4e95c2f45afc991dfe6109d9`
- mode:
  `0600`
- marker:
  `SUPERSEDED_PLANNED_EXTERNAL_DB_CHANGE`

## 완료 automation

automation `r1-runtime-v12-unattended-deployment`은 `PAUSED`로 바꿔 기존 완료 시각에 중복
최종판정이 나오지 않게 했어. delegated non-local task에서는 공식 automation control-plane
호출이 거부돼 persisted automation 상태만 fail-closed로 `PAUSED` 처리했고 service와 repo에는
영향이 없다.

## 새 baseline 재시작 절차

1. 외부 production DB 마이그레이션 owner가 완료와 안정화 시각을 확정한다.
2. 별도 승인된 재시작 세션에서 migration provenance를 기록하고 fresh versioned production
   immutable baseline을 만든다. v12 baseline이나 경과 시간을 이어 쓰지 않는다.
3. control/runtime exact SHA, clean/upstream, target plist/service/working directory/root, legacy
   root와 local residue 0을 다시 확인한다.
4. local ledger jobs/state/attempt, provider 0, cost 0을 fresh 시작 snapshot으로 고정한다.
5. 새 version의 handoff/code gate와 durable 24시간 marker를 만들고 시작/완료 예정 시각을
   새로 계산한다.
6. 새 완료 automation을 하나만 활성화하고 새 측정창이 86400초를 채우기 전에는
   `DEPLOYED_VERIFIED`를 주장하지 않는다.
