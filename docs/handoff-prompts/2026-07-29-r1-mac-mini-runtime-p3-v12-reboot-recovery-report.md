# R1 Mac mini runtime P3 v12 reboot recovery 보고

## 판정

`R1_RUNTIME_P3_REBOOT_RECOVERY_OK`

2026-07-29T10:10:43+09:00에 v12 durable marker를 기준으로 post-reboot verifier와
tracked attempt verifier를 실행했고 모두 통과했어. 이 보고 시점에는 아직 24시간 지속
검증을 시작하지 않았으므로 `DEPLOYED_VERIFIED`를 주장하지 않는다.

## reboot 증거

- pre-reboot boot sec: `1785240518`
- post-reboot boot sec: `1785287088`
- post-reboot boot time: `2026-07-29T10:04:48+09:00`
- reboot marker SHA-256:
  `d49998c58407ce4b3df38759ae15b3658438024f3f1b6aa30f4fa58d2a034e21`
- reboot marker에 기록된 control SHA:
  `75089b3c79b4b6f5a2924b417381846dacb64c21`
- runtime SHA:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`

boot sec가 marker의 pre-reboot 값과 달라졌고 marker 자체의 hash는 불변이었다.

## LaunchAgent 자동 복구

- label: `com.petcam.research-runtime`
- state snapshot: `not running`인 정상 interval 대기 상태
- WorkingDirectory:
  `/Users/baek-end/petcam-lab-research-runtime`
- runtime root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- expected HEAD:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- StartInterval: 60 seconds
- snapshot runs: `8`
- last exit code: `0`
- active research process: `0`
- target plist SHA-256:
  `c5847755d5198902e0a69c83de8ffc56dfe38f0c7a9b09b73abcefe67bff0fd6`

runtime checkout은 exact detached HEAD에서 clean이고 control checkout은 report 작성 전
HEAD/upstream `75089b3c79b4b6f5a2924b417381846dacb64c21`로 clean이었다.

## verifier 결과

```text
R1_REBOOT_BOOT_ID_CHANGED new=1785287088
R1_REBOOT_RUNTIME_HEAD_OK
R1_REBOOT_SERVICE_LOADED
R1_REBOOT_PRODUCTION_IMMUTABLE_BASELINE_OK services=7
R1_REBOOT_RUNTIME_STATUS_OK jobs=16
R1_REBOOT_RESIDUE_ZERO
R1_RUNTIME_P3_REBOOT_RECOVERY_OK
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
- legacy root `~/.petcam-research-runtime`: absent
- production DB/R2/media/dataset/model/Claude/VLM/local LLM 접근: 0
- production service mutation: 0
- production immutable services: 7
- expected-absent finalizer: absent
- production baseline SHA-256:
  `6cc46dd064be109060790edb7c75fb06d6b9681e2a1bf5b768ab3231473d5775`

## unattended reboot authorization

- sudoers path:
  `/private/etc/sudoers.d/petcam-research-runtime-reboot`
- owner/mode: `root:wheel`, `0440`
- exact NOPASSWD command: `/sbin/shutdown -r now`
- authorization attestation SHA-256:
  `ea9b7e502f71ef536f1e23014ebb2f8e653f0a64ef2f27afdd3aaac444d0a5f1`

24시간 시작 snapshot을 별도 mode 0600 durable JSON으로 기록한 뒤에는 service를 유지하고
`R1_RUNTIME_P3_PENDING_24H`로만 보고한다. 완료 예정 시각 전에는
`DEPLOYED_VERIFIED`를 주장하지 않는다.
