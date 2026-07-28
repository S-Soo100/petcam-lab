# R1 Mac mini runtime P3 v3 pre-reboot 보고

## 판정

`R1_RUNTIME_P3_REBOOT_READY`

runtime `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`의 root drift 수정과 pre-reboot
canary가 모두 통과했어. 아직 reboot recovery와 24시간 지속 검증 전이므로
`DEPLOYED_VERIFIED`는 주장하지 않는다.

## provenance와 code gate

- runtime branch: `codex/r1-runtime-launchd-exit6-fix`
- runtime SHA: `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- control branch: `codex/r1-mac-mini-runtime-p3-preinstall`
- v3 handoff SHA-256:
  `071336b5a37f750c5247e52641ba1209cd828e98e2ac91a419d6935dfc9b81b4`
- `HANDOFF_OK task=r1-mac-mini-runtime-p3-install repo=petcam-lab-research-runtime commit=7267b642 runtime=launchagent@baeg-endeuui-Macmini.local`
- runtime checkout: detached clean exact SHA
- runtime suite: `41 passed`
- adversarial marker: 14줄, `R1_RESIDUE_ZERO` 포함
- bash syntax: exit 0

## LaunchAgent와 manual canary

- target service: `com.petcam.research-runtime`
- RunAtLoad 1: `runs=1`, last exit 0
- RunAtLoad 2: `runs=1`, last exit 0
- expected HEAD, WorkingDirectory, canonical root, StartInterval 60 확인
- manual canary submit은 root env/option을 생략했고 canonical target ledger에만 생성
- legacy `/Users/baek-end/.petcam-research-runtime`: absent
- quiet window 중 자동 cycle 4회는 `quiet_window_insufficient`로 defer
- starvation block 전에 target service만 일시 bootout하고 plist/ledger 보존
- guard `allowed` 뒤 preserved plist를 수동 bootstrap
- manual canary `r1-p3-synthetic-canary-003`: attempt 1, lease epoch 1, `succeeded`
- provider calls 0, cost 0, media 0

## 자연 cycle

manual canary 뒤 kickstart 없이 service `runs`가 `1 -> 2 -> 3`으로 증가했어. 두 cycle 모두
last exit 0이고 canary attempt는 1로 유지됐다.

## SIGKILL recovery

bounded job `r1-p3-sigkill-recovery-003`의 process topology를 ledger와 `ps`로 대조했다.

```text
ledger PID=86460, attempt=1, lease_epoch=1
parent PGID=86458: uv/caffeinate/run-once only
child PGID=86464: synthetic_noop_v1 only
```

두 target process group만 SIGKILL했고 네 process가 모두 0인지 확인했다. 다음 자연 cycle이
dead PID를 한 번 reclaim한 뒤 attempt 2, lease epoch 3으로 실행했고 `succeeded`로 끝났어.

event 순서:

```text
queued
running attempt=1 lease_epoch=1
recovery_queued previous_lease_epoch=1
running attempt=2 lease_epoch=3
succeeded lease_epoch=3
```

attempt 1 성공 commit과 orphan process는 0이야. service는 `runs=5`, last exit 0으로
복구됐다.

## reboot gate

pre-reboot boot sec는 `1784164918`이야. durable artifact:

- `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-reboot-pending-v3.json`
- `/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-post-reboot-verify-v3.sh`
- verifier SHA-256:
  `291e57f9ec1fd14eaf6630c6666e10df08e6d14ac04a3a8567ba716cbac5ca7b`

reboot 전 production plist 8개 hash는 기존 baseline과 동일했고 production checkout은 새 경계에
따라 읽지 않았다. runtime ledger 2 jobs의 provider/cost 합계는 0/0, secret-like match 0,
media/model residue 0이야.
