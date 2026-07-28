# R1 Mac mini runtime P3 v8 status-envelope rollback 보고

## 판정

`R1_RUNTIME_P3_V8_STATUS_ENVELOPE_ERROR_ROLLED_BACK`

v8 RunAtLoad 2회와 중간 production baseline은 통과했고 manual `008`도 target canonical
root에서 attempt 1 `succeeded`였어. orchestration poll이 `researchctl show --json` 응답의
state를 잘못 읽어 timeout 처리했다.

실제 envelope:

```json
{"job":{"attempt":1,"job_id":"r1-p3-synthetic-canary-008","state":"succeeded"},"schema_version":1}
```

잘못된 jq path는 `.state`와 `.attempt`였고 correct path는 `.job.state`와
`.job.attempt`다. timeout의 ERR trap이 exact target service/plist를 제거했다.

rollback 확인:

- target service/plist/process: absent
- manual `008`: attempt 1 `succeeded`
- provider calls/cost: `0/0`
- production baseline: 7 exact
- finalizer/legacy root: absent
- 자연/SIGKILL/reboot/24시간: 시작하지 않음

fresh v9은 `researchctl show`를 사람이 읽는 display가 아니라 ledger의 structured SQL로
판정하고 `009` job IDs를 사용한다.
