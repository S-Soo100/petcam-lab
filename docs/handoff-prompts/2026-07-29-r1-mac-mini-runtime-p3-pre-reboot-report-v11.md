# R1 Mac mini runtime P3 v11 pre-reboot 보고

## 판정

`R1_RUNTIME_P3_REBOOT_READY_V11`

v11은 query-only WAL verifier fix, fresh handoff와 code gate, RunAtLoad 2회, manual canary,
자연 60초 cycle 2회와 SIGKILL recovery를 모두 통과했어. 아직 reboot recovery와 24시간
지속 검증 전이므로 `DEPLOYED_VERIFIED`는 주장하지 않는다.

## provenance와 code gate

- runtime SHA:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- pre-report control SHA:
  `9b316d4845559006881cf56ab1bf56fe2341f99f`
- verifier fix control SHA:
  `61b3caafb3ea3b4b9d65a67a3460bdbe6ef5da87`
- handoff SHA-256:
  `cf015d3d92046537e35821eeb384edb7c4858ae183ed5df686d0aca63c48fcf3`
- reboot verifier SHA-256:
  `8982bafadb5dd8e9fd7baa3a1f6adc6d84d73c0a9450f090c28babeaa132c389`
- attempt verifier SHA-256:
  `65691b35ecd0570017b8928bdc64798729ed49bd149eaf64def4f07ec3f6c29d`
- manual v11 SHA-256:
  `103f5b884add6483764c380854478dd654f38931aefd79e43a095061bbe5493e`
- recovery v11 SHA-256:
  `37c707b818b9eaa42191efb127ae1c200dd4f19306ebc01cdb8b1bfad8ef7b40`
- `HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=7267b642 runtime=launchagent@baeg-endeuui-Macmini.local`
- control verifier tests: `12 passed`
- runtime suite: `41 passed`
- adversarial markers: 14줄, `R1_RESIDUE_ZERO`
- system Python compile와 installer/CLI bash syntax: exit 0

## production guard와 LaunchAgent

충분한 연속 구간:

```text
2026-07-29T02:55:24+09:00 allowed=True reason=allowed
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

- manual `r1-p3-synthetic-canary-011`:
  `succeeded|attempt=1|lease_epoch=1|provider_calls=0|cost=0|exit=0`
- root option/env 생략으로 canonical default root 검증
- legacy root: absent

```text
2026-07-29T02:57:21+09:00 runs=3 last exit=0
2026-07-29T02:58:21+09:00 runs=4 last exit=0
```

두 자연 cycle에서 manual tuple은 불변이었다.

## SIGKILL recovery

```text
ledger PID=15842 attempt=1 lease_epoch=1
parent PGID=15837
child PID/PGID=15846
```

사용자, checkout, command와 parent/child process group을 assert한 뒤 exact research child,
parent PGID 순서로 SIGKILL했다.

```text
2026-07-29T03:00:13+09:00 PID=16020 attempt=2 lease_epoch=3
2026-07-29T03:02:14+09:00 succeeded exit_code=0
```

tracked attempt verifier 결과:

```text
R1_ATTEMPT_LEDGER_OK jobs=14 recovery_events=5
R1_ATTEMPT_PRODUCTION_BASELINE_OK services=7
R1_ATTEMPT_RESIDUE_ZERO
R1_ATTEMPT_VERIFIED
```

## zero-cost와 immutable baseline

- local ledger jobs: 14
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
  `77f1d511bc38d964dea7f6bcba7e4909400d8f021b087f0d683e5ccbd6a793ee`

## reboot 준비

- pre-reboot boot sec: `1785240519`
- current service: `runs=6`, last exit 0

이 보고를 commit/push한 final clean control SHA와 upstream equality를 schema 2 marker에 직접
기록한다. marker를 쓰기 전에 fixed tracked attempt verifier를 다시 실행하고, marker
작성 뒤에는 boot sec만 다른 임시 marker로 full reboot verifier preflight를 통과시킨다.
