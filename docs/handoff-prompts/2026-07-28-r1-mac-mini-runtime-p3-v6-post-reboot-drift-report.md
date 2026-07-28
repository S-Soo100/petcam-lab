# R1 Mac mini runtime P3 v6 post-reboot drift 보고

## 판정

`R1_RUNTIME_P3_V6_POST_REBOOT_OFF_TARGET_DRIFT_BLOCKED`

v6는 pre-reboot code/canary gate를 모두 통과했지만 첫 restart 요청이 iTerm2 quit timeout으로
중단됐어. boot sec가 바뀌지 않은 것을 확인한 뒤 exact research service만 rollback했다.
그 뒤 실제 reboot가 발생했지만 target plist는 이미 제거된 상태였으므로 v6 reboot recovery
통과로 소급 판정하지 않는다.

reboot 후 production baseline에서 off-target plist 소실 1건이 확인돼 v7 재설치와 24시간
검증을 시작하지 않는다.

## 첫 restart 요청과 rollback

첫 restart 요청 직후:

```text
pre boot sec=1785233472
45초 후 boot sec=1785233472
```

unified log에는 restart가 앱 종료를 진행하다 iTerm2가 45초 안에 종료되지 않아
loginwindow에서 중단된 증거가 있어.

```text
2026-07-28 21:05:52 logoutSuccess=0
bundleID=com.googlecode.iterm2
interruptReason=Application failed to quit
```

command exit 0만으로 reboot 성공을 주장하지 않고:

- `com.petcam.research-runtime` bootout
- target plist 제거
- target process 0 확인
- marker와 ledger 증거 보존

을 수행했다.

## 실제 reboot

사용자 확인 뒤 관측한 실제 post-reboot 값:

```text
boot sec=1785240518
boot time=2026-07-28T21:08:38+09:00
target service=absent
target plist=absent
runtime HEAD=7267b642dd9e25a0e199e57c5d41d1e2c04ee419
runtime checkout=clean
control checkout=clean
```

target absent는 reboot 전 rollback 결과와 일치한다.

## production baseline drift

pre-reboot immutable baseline:

```text
/Users/baek-end/Library/Application Support/petcam/research-runtime/audit/r1-p3-production-immutable-baseline-v6.json
SHA-256=17514aba088d9751023476ea2b17ab839c58f760685d5a76ec86c90a13cea7a4
services=8
```

post-reboot 비교:

- plist missing: `com.petcam.vlm-backfill-finalizer`
- finalizer launchd service: absent
- 다른 production plist 7개 SHA-256/WorkingDirectory: pre와 동일
- production repo HEAD/status fingerprint mismatch: 0

관련 unified log:

```text
2026-07-28 21:08:22 service inactive: com.petcam.vlm-backfill-finalizer
2026-07-28 21:08:22 removing service: com.petcam.vlm-backfill-finalizer
2026-07-28 21:09:48 background task registration removing
```

이 로그만으로 plist 삭제 actor나 의도를 단정하지 않는다. research controller는 target 외
LaunchAgent를 bootout/bootstrap/remove/signal하지 않았다.

## zero-cost와 종료 상태

- research target service/plist/process: absent
- local ledger jobs: 7
- provider calls 합계: 0
- cost 합계: 0
- legacy root: absent
- production DB/R2/media/dataset/model/Claude/VLM/local LLM 접근: 0
- research media/model residue: 0
- v6 marker: 증거로 보존
- `R1_RUNTIME_P3_PENDING_24H`: 시작하지 않음
- `DEPLOYED_VERIFIED`: 주장하지 않음

production baseline을 복구하거나 새 baseline으로 승인하는 작업은 이 research target
handoff 범위를 벗어나므로 자동 수행하지 않는다.
