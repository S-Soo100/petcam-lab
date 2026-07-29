# R1 Mac mini runtime P3 v12 24시간 시작 보고

## 판정

`R1_RUNTIME_P3_PENDING_24H`

reboot recovery 보고 commit/push 뒤 durable 시작 snapshot을 mode 0600으로 원자 기록했어.
완료 예정 시각 전에는 `DEPLOYED_VERIFIED`를 주장하지 않는다.

## 시간과 provenance

- 시작 시각: `2026-07-29T10:17:55.289345+09:00`
- 완료 예정 시각: `2026-07-30T10:17:55.289345+09:00`
- 최소 경과 시간: 86400초
- reboot recovery report control SHA:
  `ecf7c687c251bacbd5793634ea007ef44951e369`
- runtime SHA:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- post-reboot boot sec: `1785287088`

## durable 시작 snapshot

- artifact:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-24h-pending-v12.json`
- SHA-256:
  `ac996815ea3cbde8c46196dbc026a8f076396537dd762ed3bfb57c170ed00a9c`
- owner: current runtime user
- mode: `0600`
- marker: `R1_RUNTIME_P3_PENDING_24H`

artifact는 다음 immutable hash를 포함한다.

- reboot marker:
  `d49998c58407ce4b3df38759ae15b3658438024f3f1b6aa30f4fa58d2a034e21`
- production baseline:
  `6cc46dd064be109060790edb7c75fb06d6b9681e2a1bf5b768ab3231473d5775`
- reboot authorization:
  `ea9b7e502f71ef536f1e23014ebb2f8e653f0a64ef2f27afdd3aaac444d0a5f1`
- target plist:
  `c5847755d5198902e0a69c83de8ffc56dfe38f0c7a9b09b73abcefe67bff0fd6`

## 시작 상태

- target label: `com.petcam.research-runtime`
- WorkingDirectory:
  `/Users/baek-end/petcam-lab-research-runtime`
- runtime root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- service runs: 13
- last exit code: 0
- StartInterval: 60초
- active research process: 0
- jobs: 16
- ledger state 분포: `blocked=1`, `succeeded=15`
- attempt 합계: 22
- queued/running: 0/0
- provider calls 합계: 0
- cost 합계: 0
- production immutable services: 7
- expected-absent finalizer: absent
- legacy root: absent
- media/model/secret-like residue: 0
- production DB/R2/media/dataset/model/Claude/VLM/local LLM/provider 접근: 0
- production service mutation: 0

`blocked=1`은 기존 `r1-p3-synthetic-canary-005`의 `attempt=0`, `lease_epoch=0`,
provider/cost 0 기록이야. v12 실행 중 새 실패나 drift가 아니고 시작 snapshot에 그대로
고정했다.

## preflight 정정 기록

첫 JSON preflight는 ledger의 16개 job이 모두 `succeeded`일 것이라는 추가 가정을
fail-closed로 거부했고 파일을 쓰지 않았다. 실제 분포를 query-only로 확인한 뒤 기존
blocked canary를 포함한 정확한 시작 상태로 다시 생성했다.

복사된 attempt verifier는 실행 비트와 import root가 없어서 직접 호출 방식이 각각 exit
126과 `ModuleNotFoundError`를 냈다. verifier 자체 판정 실패는 아니며, control checkout을
`PYTHONPATH`로 둔 원래 invocation으로 재실행해 아래 결과를 다시 확보했다.

```text
R1_ATTEMPT_LEDGER_OK jobs=16 recovery_events=5
R1_ATTEMPT_PRODUCTION_BASELINE_OK services=7
R1_ATTEMPT_RESIDUE_ZERO
R1_ATTEMPT_VERIFIED
```

full reboot verifier도 시작 직전에 다시 통과했다.

```text
R1_REBOOT_BOOT_ID_CHANGED new=1785287088
R1_REBOOT_RUNTIME_HEAD_OK
R1_REBOOT_SERVICE_LOADED
R1_REBOOT_PRODUCTION_IMMUTABLE_BASELINE_OK services=7
R1_REBOOT_RUNTIME_STATUS_OK jobs=16
R1_REBOOT_RESIDUE_ZERO
R1_RUNTIME_P3_REBOOT_RECOVERY_OK
```

24시간 뒤에는 최소 경과 시간, exact service/root/HEAD, 자연 run 증가, ledger jobs/state/
attempt 불변, duplicate 0, provider/cost 0, production baseline services 7, finalizer/legacy
root/residue 0을 재검증한다. 그 전에는 service를 유지하고
`R1_RUNTIME_P3_PENDING_24H`로만 보고한다.
