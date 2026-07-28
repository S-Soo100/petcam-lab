# R1 Mac mini runtime P3 v3 reboot rollback 보고

## 판정

`R1_RUNTIME_P3_REBOOT_BASELINE_DRIFT_ROLLED_BACK`

reboot 후 target runtime 자동 복구는 확인됐지만 production LaunchAgent의 volatile state가
pre-reboot baseline과 달라졌어. production baseline `pre == post` 계약을 통과하지 못했으므로
`com.petcam.research-runtime`만 즉시 rollback했고 24시간 검증은 시작하지 않았다.

## reboot에서 통과한 항목

- pre-reboot boot sec: `1784164918`
- post-reboot boot sec: `1785233472`
- post-reboot target service: 자동 loaded
- target RunAtLoad: `runs=1`, last exit 0
- WorkingDirectory: `/Users/baek-end/petcam-lab-research-runtime`
- runtime root:
  `/Users/baek-end/Library/Application Support/petcam/research-runtime`
- expected/runtime HEAD:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- runtime checkout: detached clean

## 실패 원인

### 1. production baseline volatile-state drift

pre-reboot baseline에서 `com.petcam.vlm-backfill-finalizer`는 plist만 있고
`loaded=false`였어. reboot 뒤 같은 plist가 user LaunchAgent domain에 자동 등록돼
`loaded=true`, `runs=0`, `last exit code=(never exited)`가 됐다.

다른 production LaunchAgent도 reboot로 runs와 last-exit가 재초기화됐어. 예:

```text
com.petcam.activity-worker
pre:  loaded=true, last exit=1
post: loaded=true, runs=1, last exit=0

com.petcam.nightly-reporter
pre:  loaded=true, last exit=0
post: loaded=true, runs=0, last exit=(never exited)
```

production plist 8개의 SHA-256과 WorkingDirectory는 pre-reboot 값과 모두 같아. 따라서
production code/plist mutation 증거는 없지만, loaded/runs/last-exit까지 포함한 full baseline은
reboot 전후 동일하지 않다. 이 state를 맞추기 위해 production service를 bootout·kickstart하지
않았어.

### 2. durable verifier boot parser 결함

audit verifier의 정규식은 greedy `.*sec` 때문에 `sec`가 아니라 뒤의 `usec`를 추출했다.

```text
actual sysctl:
{ sec = 1785233472, usec = 925537 } Tue Jul 28 19:11:12 2026

verifier output:
R1_REBOOT_BOOT_ID_CHANGED old=1784164918 new=925537
```

boot 변경 자체는 raw `sysctl` 출력으로 별도 확인했지만 verifier는 신뢰할 수 없으므로 exit 1
시점에서 gate를 실패 처리했어.

## rollback

실행:

```text
launchctl bootout gui/501/com.petcam.research-runtime
remove /Users/baek-end/Library/LaunchAgents/com.petcam.research-runtime.plist
```

확인:

- target service absent
- target plist absent
- research runtime `run-once`/`execute-handler` process 0
- manual canary: attempt 1 `succeeded`
- SIGKILL recovery: attempt 2 `succeeded`
- legacy `/Users/baek-end/.petcam-research-runtime`: absent
- runtime checkout: detached clean exact SHA
- provider calls 합계 0
- cost 합계 0
- media/model residue 0
- runtime event/job/log secret-like match 0

ledger, events, jobs, handoff, diagnostics, audit marker는 증거로 보존했다.

## 다음 gate

재시도 전 두 항목을 먼저 해결해야 해.

1. boot ID parser를 `sec = <number>`의 첫 필드만 추출하도록 수정하고 verifier 자체 RED/GREEN
   검증을 남긴다.
2. reboot 전후 production baseline을 plist hash·WorkingDirectory 같은 immutable 항목으로
   정의할지, launchd loaded/runs/last-exit 변화까지 동일해야 하는지 명시한다. 후자를 유지하면
   reboot 자체와 양립하지 않으므로 재시도하지 않는다.

`R1_RUNTIME_P3_PENDING_24H`는 시작하지 않았고 `DEPLOYED_VERIFIED`도 주장하지 않는다.
