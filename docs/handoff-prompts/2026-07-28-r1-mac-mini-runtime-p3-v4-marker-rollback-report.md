# R1 Mac mini runtime P3 v4 marker 작성 rollback 보고

## 판정

`R1_RUNTIME_P3_V4_MARKER_ASSERTION_ROLLED_BACK`

v4는 RunAtLoad 2회, manual canary, 자연 cycle 2회, SIGKILL recovery까지 통과했지만
pre-reboot marker 생성 명령에서 controller가 control SHA를 잘못 하드코딩해 assertion이
실패했어. marker는 쓰기 전이었고 reboot는 실행되지 않았다. fail-closed 계약에 따라
`com.petcam.research-runtime`만 즉시 rollback했다.

## exact 원인

```text
actual control SHA:
905fd65b4295c89f01c6e935e49c55ee5b78be1a

mistyped expected SHA:
905fd65357770fab584c07d1f4d7bfbdde9f49fe
```

runtime, verifier, production baseline 결함이 아니라 운영 명령의 수동 전사 오류야. v5 marker는
control SHA를 `git rev-parse HEAD`에서 직접 읽고 branch clean/upstream 일치만 검증한다.
별도 hardcoded SHA assertion은 두지 않는다.

## rollback 증거

- target service: absent
- target plist: absent
- research `run-once`/`execute-handler` process: 0
- marker v4: absent
- runtime checkout: detached clean exact
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419`
- ledger jobs: 4
- provider calls 합계: 0
- cost 합계: 0
- production immutable baseline: 8 services unchanged
- production DB/R2/media/dataset/model/Claude/VLM/local LLM 접근: 0
- production service mutation: 0

v4 canary IDs는 재사용하지 않는다. v5는 fresh `005` IDs와 새 handoff/HANDOFF_OK로 전체
RunAtLoad 이후 순서를 다시 시작한다.
