# R1 Mac mini runtime P3 v10 pre-reboot 보고

## 판정

`R1_RUNTIME_P3_REBOOT_READY_V10`

v10은 tracked attempt verifier를 포함한 code gate, RunAtLoad 2회, manual canary, 자연 60초
cycle 2회와 SIGKILL recovery를 모두 통과했어. 아직 reboot recovery와 24시간 지속 검증
전이므로 `DEPLOYED_VERIFIED`는 주장하지 않는다.

## provenance와 code gate

- runtime SHA:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- pre-report control SHA:
  `ba8f88d807974403e8e5411c055490160558eed6`
- handoff SHA-256:
  `604d74612647b668be38ddb534c540e679689ef585c25d581625f71a34a8cc71`
- reboot verifier SHA-256:
  `8982bafadb5dd8e9fd7baa3a1f6adc6d84d73c0a9450f090c28babeaa132c389`
- attempt verifier SHA-256:
  `765db047d3aeea74f97a6b213e5788a1f6dcca25b237d20b111a4b7589e6a844`
- `HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=7267b642 runtime=launchagent@baeg-endeuui-Macmini.local`
- control verifier tests: `11 passed`
- runtime suite: `41 passed`
- adversarial markers: 14줄, `R1_RESIDUE_ZERO`
- system Python compile와 bash syntax: exit 0

## production guard와 LaunchAgent

충분한 연속 구간:

```text
2026-07-29T00:55:07+09:00 allowed=True reason=allowed
```

production lock/service/schedule은 변경하지 않았다.

- RunAtLoad 1: `runs=1`, last exit 0
- RunAtLoad 2: `runs=1`, last exit 0
- WorkingDirectory:
  `/Users/baek-end/petcam-lab-research-runtime`
- runtime root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- StartInterval: 60 seconds
- target plist SHA-256:
  `c5847755d5198902e0a69c83de8ffc56dfe38f0c7a9b09b73abcefe67bff0fd6`

## manual과 자연 cycle

- manual `r1-p3-synthetic-canary-010`: attempt 1 `succeeded`
- root option/env 생략으로 canonical default root 검증

```text
2026-07-29T00:57:11+09:00 runs=3 last exit=0
2026-07-29T00:58:12+09:00 runs=4 last exit=0
```

두 자연 cycle에서 manual tuple은 `succeeded|1`로 불변이었다.

## SIGKILL recovery

```text
ledger PID=10402 attempt=1 lease_epoch=1
parent PGID=10400
child PID/PGID=10406
```

사용자, checkout, command와 parent/child process group을 assert한 뒤 exact research child,
parent PGID 순서로 SIGKILL했다.

```text
2026-07-29T01:00:33+09:00 PID=10582 attempt=2 lease_epoch=3
2026-07-29T01:02:32+09:00 succeeded exit_code=0
```

tracked attempt verifier 결과:

```text
R1_ATTEMPT_LEDGER_OK jobs=12 recovery_events=5
R1_ATTEMPT_PRODUCTION_BASELINE_OK services=7
R1_ATTEMPT_RESIDUE_ZERO
R1_ATTEMPT_VERIFIED
```

## zero-cost와 immutable baseline

- local ledger jobs: 12
- provider calls 합계: 0
- cost 합계: 0
- media/model/secret-like residue: 0
- legacy root: absent
- runtime process: 0
- production DB/R2/media/dataset/model/Claude/VLM/local LLM 접근: 0
- production service mutation: 0
- production immutable services: 7
- expected-absent finalizer: absent
- baseline SHA-256:
  `cf62c22904e60e9ad67bf180fac7a78428b340a2b6b2df2480e6f72daa7c08b2`

## reboot 준비

- pre-reboot boot sec: `1785240518`
- current service: `runs=6`, last exit 0

이 보고를 commit/push한 final clean control SHA와 upstream equality를 marker에 직접 기록한다.
