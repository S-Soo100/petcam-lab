# R1 Mac mini runtime P3 v9 event-schema rollback 보고

## 판정

`R1_RUNTIME_P3_V9_POSTCHECK_EVENT_SCHEMA_ERROR_ROLLED_BACK`

v9 runtime 검증 자체는 다음까지 통과했어.

- RunAtLoad 2회: exit 0
- manual `009`: `succeeded`, attempt 1
- 자연 cycle: `runs=3 -> 4`, exit 0
- SIGKILL target PGID:
  parent `7134`, child `7140`
- recovery `009`: `succeeded`, attempt 2, lease epoch 3, exit 0

post-check에서 success event를 `.event == "job_succeeded"`로 가정했지만 실제 event schema는
일반 lifecycle을 `state`로 기록하고 recovery 전이만 `event`로 기록해 assertion이
실패했다.

실제 recovery sequence:

```text
state=queued
state=running attempt=1 lease_epoch=1
event=recovery_queued previous_lease_epoch=1
state=running attempt=2 lease_epoch=3
state=succeeded lease_epoch=3
```

검증 command 실패 직후 exact target service/plist를 rollback했다.

## rollback 후 증거

- target service/plist/process: absent
- manual `009`: succeeded/1/epoch 1/exit 0
- recovery `009`: succeeded/2/epoch 3/exit 0
- local ledger jobs: 10
- provider calls/cost: `0/0`
- production baseline: 7 exact
- finalizer/legacy root: absent
- reboot/24시간: 시작하지 않음

tracked `verify_research_runtime_attempt.py`가 actual v9 ledger/events/results/baseline을
`R1_ATTEMPT_VERIFIED`로 검증했다. fresh v10부터 post-check는 이 helper만 사용한다.
