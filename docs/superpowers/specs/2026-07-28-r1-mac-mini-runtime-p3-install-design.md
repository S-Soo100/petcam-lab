# R1 Mac mini 연구 runtime P3 설치 설계

## 1. 목적

검증된 R1 synthetic no-op runtime을 Mac mini의 전용 checkout과 LaunchAgent에 설치하고,
앱·MacBook 연결과 무관하게 60초 polling, crash/reboot 복구, SSH 관측이 되는지 확인해.

이번 패키지는 설치 권한을 준비하지만 현재 세션의 실행 경계는 **Mac mini 접속·checkout 생성·
LaunchAgent bootstrap 직전**이야. 실제 runtime mutation은 다음 실행에서 P3 start marker와
Mac mini handoff가 모두 통과한 뒤에만 시작해.

## 2. 고정 provenance

| 항목 | 값 |
|---|---|
| 검증된 R1 runtime code | `8a7ea47041d02180f2fe03ada54f39f45ccf7c26` |
| runtime host | `baeg-endeuui-Macmini.local` |
| runtime user | `baek-end` |
| runtime checkout | `/Users/baek-end/petcam-lab-research-runtime` |
| runtime data root | `/Users/baek-end/Library/Application Support/petcam/research-runtime` |
| LaunchAgent label | `com.petcam.research-runtime` |
| polling | `StartInterval=60` |
| installer | `scripts/install_research_runtime_launchd.sh` |
| workload allowlist | `synthetic_noop_v1` 하나 |

runtime checkout은 detached exact code commit을 사용해. P3 승인·보고 branch와 runtime code
HEAD를 섞지 않아. 기존 production worker checkout도 공유하지 않아.

## 3. 권한과 금지 경계

P3가 허용하는 실제 mutation은 다음 하나야.

- exact target `com.petcam.research-runtime` LaunchAgent 설치·bootout·bootstrap

함께 허용하는 하위 권한은 P1 문서·feature commit/push와 P2 synthetic non-production
canary야.

다음은 모두 금지해.

- production DB migration/write와 Supabase 접근
- R2 read/write/delete
- 영상·frame·dataset·checkpoint·model 접근
- Claude/VLM/local LLM/provider 호출과 비용 발생
- 기존 production LaunchAgent 수정·bootout
- main merge, destructive Git, credential 변경
- `synthetic_noop_v1` 외 handler 등록

## 4. 설치 전 handoff

P3 controller branch는 A→M lifecycle로 설계·계획과 start manifest를 고정해. start 검증은
현재 Owner 승인 turn을 확인하는 injected trusted approval verifier를 사용해. manifest 문자열
자체는 승인 증거로 취급하지 않아.

Mac mini에는 별도 runtime handoff를 전달해. handoff validator는 다음을 exact match로 확인해.

- execution repo 경로
- runtime code commit
- installer와 R1 runbook의 tracked blob
- runtime host와 service label
- clean working tree

Mac mini execution repo가 아직 없으므로 laptop에서는 `HANDOFF_OK`를 주장하지 않아. 다음
실행에서 checkout을 만든 직후 Mac mini에서 검증해.

## 5. 설치 흐름

1. P3 start manifest의 `RUN_MANIFEST_OK`와 immutable manifest SHA를 확인해.
2. Mac mini 전용 checkout을 exact runtime code commit으로 준비해.
3. runtime handoff validator를 Mac mini에서 통과시켜.
4. Mac mini에서 research-runtime tests 39개와 adversarial marker 14개를 재실행해.
5. installer에 exact host·HEAD를 전달해 LaunchAgent를 설치해.
6. plist loaded, working directory, environment, logs mode, delete-free 상태를 확인해.

어느 단계든 mismatch면 설치하지 않고 종료해.

## 6. canary 단계

설치 뒤 canary는 순서를 바꾸지 않아.

1. manual synthetic no-op 1건
2. 자연 60초 LaunchAgent cycle 1회
3. 실행 중 SIGKILL 뒤 same-boot recovery
4. Mac mini reboot 뒤 boot fencing recovery
5. 24시간 지속 시험

각 단계의 성공 조건:

- 같은 job 동시 실행 0
- stale epoch result commit 0
- production lock·quiet-window에서 실행 시작 0
- production worker deadline/exit drift 0
- ledger·JSONL·log·CLI secret-like match 0
- provider/cost/media/temp residue 0

앞 단계가 실패하면 뒤 단계로 진행하지 않아.

## 7. rollback

즉시 rollback:

```bash
launchctl bootout gui/$(id -u)/com.petcam.research-runtime
rm "$HOME/Library/LaunchAgents/com.petcam.research-runtime.plist"
```

rollback 뒤 확인:

- `launchctl print`에서 service 없음
- research runtime process 0
- production service loaded/exit/head 불변
- runtime ledger·JSONL은 삭제하지 않고 mode 0600으로 보존
- temp media 0

## 8. runtime attestation과 완료 판정

최종 C는 Mac mini의 다음 증거를 확인하는 injected runtime attestation verifier가 있어야 해.

- hostname exact
- service loaded와 plist label exact
- WorkingDirectory와 runtime checkout HEAD exact
- manual/natural/SIGKILL/reboot canary 결과
- 24시간 결과와 production drift 0
- rollback 명령 검증과 residue 0

attestation 전 판정은 `P3_START_VALIDATED_INSTALL_NOT_STARTED`까지만 허용해.
최종 성공 판정은 `R1_RUNTIME_P3_DEPLOYED_VERIFIED`야.
