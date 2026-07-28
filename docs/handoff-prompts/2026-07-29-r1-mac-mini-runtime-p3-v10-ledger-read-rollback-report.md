# R1 Mac mini runtime P3 v10 ledger read rollback 보고

## 판정

`R1_RUNTIME_P3_V10_LEDGER_READ_ROLLBACK`

v10은 RunAtLoad 2회, manual canary, 자연 60초 cycle 2회와 SIGKILL recovery까지
통과했어. pre-reboot marker를 쓰기 직전 tracked attempt verifier가
`ledger_unreadable`로 실패해 exact target만 즉시 rollback했고, marker/reboot/24시간
단계는 시작하지 않았다.

## 실패와 rollback

- pre-reboot 보고 commit:
  `4dc80ff150298cee8136088ca3b25752c8d50857`
- 실패 시각: `2026-07-29T01:04:31+09:00` 이전
- 실패 출력:
  `R1_ATTEMPT_VERIFY_FAILED reason=ledger_unreadable`
- target launchd 제거:
  `2026-07-29T01:04:31+09:00`
- v10 reboot marker: absent
- target service/plist/process: absent
- reboot recovery: 시작하지 않음
- 24시간 검증: 시작하지 않음

service absent 상태에서 같은 verifier는 20회 연속 성공했어. 이 차이만으로 transient
오류를 추측하지 않고 target-only 진단 설치를 두 번 수행했으며, 각 진단은 EXIT trap으로
target만 제거했다.

## 결정론적 root cause

첫 진단은 loaded target의 자연 cycle을 포함한 90초 동안 production 접근 없이 같은
ledger query 세 개만 반복했어.

```text
diagnostic runs=1 -> 2
R1_SQLITE_DIAGNOSTIC iterations=3528 errors=3528
sqlite_error message=unable to open database file
target removed=2026-07-29T01:08:29+09:00
```

두 번째 대조에서 ledger와 directory ownership/mode는 정상이고 WAL sidecar가 없는 상태였어.

```text
ledger.sqlite3 mode=0600 uid=501 gid=20
ledger.sqlite3-wal absent
ledger.sqlite3-shm absent
mode=ro             -> unable to open database file
mode=ro&immutable=1 -> jobs=12 provider_calls=0 cost=0
mode=rw             -> jobs=12 provider_calls=0 cost=0
plain path          -> jobs=12 provider_calls=0 cost=0
```

runtime writer는 uv Python `3.12.13`/SQLite `3.50.4`, marker verifier는 system Python
`3.9.6`/SQLite `3.51.0`이야. uv runtime이 clean WAL ledger를 sidecar 없이 닫은 직후
system SQLite의 `mode=ro` open만 WAL sidecar를 준비하지 못해 실패하는 것을 임시
database에서도 재현했다.

`mode=rw` connection에 첫 statement로 `PRAGMA query_only=ON`을 적용하면 WAL sidecar를
준비하면서 verifier SQL mutation은 엔진에서 차단되고, 뒤의 동일 `mode=ro`도 성공했어.

## RED -> GREEN

control branch에 system Python direct-entrypoint가 clean WAL ledger를 읽는 계약을
추가했어.

```text
RED: 1 failed
     R1_ATTEMPT_VERIFY_FAILED reason=ledger_unreadable
GREEN focused: 1 passed
attempt verifier suite: 4 passed
combined verifier suite: 12 passed
system Python compile/bash syntax/diff check: exit 0
```

최소 수정은 attempt verifier의 open URI를 create 불가 `mode=rw`로 바꾸고, connection
직후 `PRAGMA query_only=ON`을 켠 것뿐이야.

- fix control SHA:
  `61b3caafb3ea3b4b9d65a67a3460bdbe6ef5da87`
- attempt verifier SHA-256:
  `65691b35ecd0570017b8928bdc64798729ed49bd149eaf64def4f07ec3f6c29d`
- runtime SHA: 변경 없음
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`

## 종료 경계

수정된 verifier를 보존된 v10 증거에 다시 실행한 결과야.

```text
R1_ATTEMPT_LEDGER_OK jobs=12 recovery_events=5
R1_ATTEMPT_PRODUCTION_BASELINE_OK services=7
R1_ATTEMPT_RESIDUE_ZERO
R1_ATTEMPT_VERIFIED
```

- provider calls 합계: 0
- cost 합계: 0
- production immutable baseline: pre == post, services 7
- expected-absent finalizer: absent
- legacy root: absent
- production DB/R2/media/dataset/model/Claude/VLM/local LLM 접근: 0
- production service mutation: 0

v10을 성공으로 소급하지 않는다. fresh v11은 새 handoff, 새 `011` jobs, 새 baseline과 새
marker로 처음부터 검증한다.
