# R1 Mac mini runtime P3 v12 pre-reboot 보고

## 판정

`R1_RUNTIME_P3_REBOOT_READY_V12`

v12는 exact NOPASSWD shutdown authorization, fresh handoff와 code gate, RunAtLoad 2회,
manual canary, 자연 60초 cycle 2회와 SIGKILL recovery를 모두 통과했어. 아직 reboot
recovery와 24시간 지속 검증 전이므로 `DEPLOYED_VERIFIED`는 주장하지 않는다.

## provenance와 code gate

- runtime SHA:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- pre-report control SHA:
  `2afd2f43f819e1afc49d2506765e1095ec1ac6c5`
- handoff SHA-256:
  `e1c2834ea1ac0c21a39a34ce93a2d1be4694c09ad0cf0eb09f1087a8ad137451`
- reboot verifier SHA-256:
  `8982bafadb5dd8e9fd7baa3a1f6adc6d84d73c0a9450f090c28babeaa132c389`
- attempt verifier SHA-256:
  `65691b35ecd0570017b8928bdc64798729ed49bd149eaf64def4f07ec3f6c29d`
- manual v12 SHA-256:
  `c03896f543ef5a56c91151633bb7419fe4d0ef8ddfeb7099d88d98f2e29cd709`
- recovery v12 SHA-256:
  `6e50c56ba07fd16284a66e5ceae47f4b9135477a3652e1648aadf54d3d37fac5`
- `HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=7267b642 runtime=launchagent@baeg-endeuui-Macmini.local`
- control verifier tests: `12 passed`
- runtime suite: `41 passed`
- adversarial markers: 14줄, `R1_RESIDUE_ZERO`
- system Python compile와 installer/CLI bash syntax: exit 0

## unattended reboot authorization

- sudoers path:
  `/private/etc/sudoers.d/petcam-research-runtime-reboot`
- owner: `root:wheel`
- mode: `0440`
- exact NOPASSWD command:
  `/sbin/shutdown -r now`
- authorization attestation SHA-256:
  `ea9b7e502f71ef536f1e23014ebb2f8e653f0a64ef2f27afdd3aaac444d0a5f1`

다른 sudo command에는 NOPASSWD를 부여하지 않았다.

## production guard와 LaunchAgent

충분한 연속 구간:

```text
2026-07-29T09:55:25+09:00 allowed=True reason=allowed
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

- manual `r1-p3-synthetic-canary-012`:
  `succeeded|attempt=1|lease_epoch=1|provider_calls=0|cost=0|exit=0`
- root option/env 생략으로 canonical default root 검증
- legacy root: absent

```text
2026-07-29T09:57:09+09:00 runs=3 last exit=0
2026-07-29T09:58:09+09:00 runs=4 last exit=0
```

두 자연 cycle에서 manual tuple은 불변이었다.

## SIGKILL recovery

```text
ledger PID=24121 attempt=1 lease_epoch=1
parent PGID=24116
child PID/PGID=24125
```

사용자, checkout, command와 parent/child process group을 assert한 뒤 exact research child,
parent PGID 순서로 SIGKILL했다.

```text
2026-07-29T09:59:38+09:00 PID=24309 attempt=2 lease_epoch=3
2026-07-29T10:01:39+09:00 succeeded exit_code=0
```

tracked attempt verifier 결과:

```text
R1_ATTEMPT_LEDGER_OK jobs=16 recovery_events=5
R1_ATTEMPT_PRODUCTION_BASELINE_OK services=7
R1_ATTEMPT_RESIDUE_ZERO
R1_ATTEMPT_VERIFIED
```

## zero-cost와 immutable baseline

- local ledger jobs: 16
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
  `6cc46dd064be109060790edb7c75fb06d6b9681e2a1bf5b768ab3231473d5775`

## reboot 준비

- pre-reboot boot sec snapshot: `1785240518`
- current service: `runs=6`, last exit 0

이 보고를 commit/push한 final clean control SHA와 upstream equality를 schema 2 marker에
기록한다. marker를 쓰기 전에 fixed attempt verifier를 다시 실행하고, marker 작성 뒤
boot sec만 다른 임시 marker로 full reboot verifier preflight를 통과시킨다.
