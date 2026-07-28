# R1 Mac mini runtime P3 v5 guard defer rollback 보고

## 판정

`R1_RUNTIME_P3_V5_GUARD_DEFER_ROLLED_BACK`

v5 RunAtLoad 2회는 exit 0이었지만 manual canary `r1-p3-synthetic-canary-005`가 production
guard에서 `deferred`됐어. 성공 조건인 attempt 1 `succeeded`가 아니므로 뒤 단계로 가지 않고
`com.petcam.research-runtime`만 rollback했다.

## 증거

```text
job_id=r1-p3-synthetic-canary-005
state=deferred
attempt=0
yield reason=activity_lock_busy
```

rollback 직후 read-only guard probe는 `quiet_window_insufficient`였어. production lock,
service 또는 schedule은 수정하지 않았다. deferred job에는 cancel intent를 기록해 다음
runtime 설치가 claim하지 않게 했고 상태/attempt 감사 이력은 보존했다.

- target service/plist/process: absent
- legacy root: absent
- provider calls/cost: 0/0
- media/model residue: 0
- production immutable baseline: 8 services unchanged
- production DB/R2/media/dataset/model/Claude/VLM/local LLM 접근: 0
- production service mutation: 0

v6는 fresh `006` IDs를 사용하고 read-only guard가 자연스럽게 `allowed`가 된 뒤에만 설치한다.
