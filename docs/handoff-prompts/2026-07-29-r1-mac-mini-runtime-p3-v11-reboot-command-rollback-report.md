# R1 Mac mini runtime P3 v11 reboot command rollback 보고

## 판정

`R1_RUNTIME_P3_V11_REBOOT_COMMAND_BLOCKED_ROLLED_BACK`

v11은 pre-reboot code/canary gate와 durable marker dry-run까지 통과했지만,
non-interactive administrator authorization을 얻지 못해 reboot 요청 전에 멈췄어.
지침대로 exact research target과 pending marker만 즉시 rollback했고 reboot/24시간
뒤 단계는 시작하지 않았다.

## pre-reboot 통과 범위

- runtime SHA:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- final pre-reboot control SHA:
  `3f4ffb259fe25368e83773e83a7c590f3e94e83c`
- pre-reboot report SHA-256:
  `2c488b3288756c2947fa24b1dbd14cd6288389aeb85dfbe5237a1cef2a054b6d`
- RunAtLoad 2회: exit 0
- manual `011`: `succeeded|attempt=1|lease_epoch=1`
- natural cycle: `runs 2 -> 3 -> 4`, exit 0
- SIGKILL recovery `011`: `succeeded|attempt=2|lease_epoch=3`
- tracked attempt verifier:
  `jobs=14`, `recovery_events=5`, `R1_ATTEMPT_VERIFIED`

durable marker는 다음 값으로 원자 작성했어.

```text
marker SHA-256=2c302d3e2a786c31d6272ee098a57ac44f15835276148e1713f0962251ce3946
pre_reboot_boot_sec=1785240519
control_sha=3f4ffb259fe25368e83773e83a7c590f3e94e83c
service_runs=8
```

boot sec만 다른 임시 marker로 full verifier를 실행한 결과는
`R1_RUNTIME_P3_REBOOT_RECOVERY_OK`까지 통과했다.

## reboot 실패 경계

실행 순서는 password prompt가 발생한 뒤 reboot command가 일부 실행되는 상태를 막기 위해
다음 preflight부터 시작했어.

```text
/usr/bin/sudo -n /usr/bin/true
sudo: a password is required
exit=1
```

preflight가 실패했으므로 `/usr/bin/sudo -n /sbin/shutdown -r now`는 실행되지 않았다.

- 실패 후 boot sec: `1785240519`
- pre-reboot boot sec와 동일
- 실제 reboot: 없음
- reboot recovery: 미검증

## exact rollback과 post-check

ERR trap과 후속 검증 결과야.

```text
target service=absent
target plist=absent
target runtime process=0
v11 pending marker=absent
legacy root=absent
finalizer plist=absent
runtime HEAD=7267b642dd9e25a0e199e57c5d41d1e2c04ee419 clean
control HEAD/upstream=3f4ffb259fe25368e83773e83a7c590f3e94e83c clean
```

보존된 v11 evidence에 fixed verifier를 재실행한 결과:

```text
R1_ATTEMPT_LEDGER_OK jobs=14 recovery_events=5
R1_ATTEMPT_PRODUCTION_BASELINE_OK services=7
R1_ATTEMPT_RESIDUE_ZERO
R1_ATTEMPT_VERIFIED
```

- production baseline SHA-256:
  `77f1d511bc38d964dea7f6bcba7e4909400d8f021b087f0d683e5ccbd6a793ee`
- provider calls 합계: 0
- cost 합계: 0
- production DB/R2/media/dataset/model/Claude/VLM/local LLM 접근: 0
- production service mutation: 0
- `R1_RUNTIME_P3_PENDING_24H`: 시작하지 않음
- `DEPLOYED_VERIFIED`: 주장하지 않음

다음 attempt는 interactive administrator authorization이 확보된 fresh handoff/marker
흐름으로 다시 시작해야 해. v11을 reboot 성공으로 소급하지 않는다.
