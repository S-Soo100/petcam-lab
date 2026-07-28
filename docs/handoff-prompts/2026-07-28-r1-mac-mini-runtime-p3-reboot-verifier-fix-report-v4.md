# R1 Mac mini runtime P3 reboot verifier v4 수정 보고

## 판정

`REBOOT_VERIFIER_ROOT_CAUSE_FIXED_READY_FOR_V4_HANDOFF`

v3 reboot에서 runtime 자체는 exact SHA와 canonical root로 자동 복구했지만 audit verifier가
잘못된 boot ID와 reboot 비호환 production baseline을 사용해 fail-closed rollback했어.
runtime 코드는 수정하지 않았고 control-owned verifier만 TDD로 교체했다.

## root cause

첫째, untracked v3 shell verifier의 greedy 표현식
`s/.*sec = ([0-9]+).*/\1/`은 다음 실제 출력에서 `sec`가 아니라 마지막 `usec`를 선택했다.

```text
{ sec = 1785233472, usec = 925537 } Tue Jul 28 19:11:12 2026
```

둘째, production baseline이 plist/code mutation뿐 아니라 launchd
`loaded/runs/last-exit`까지 동일하다고 요구했다. 이 값들은 reboot로 정상 변화하므로 strict
`pre == post`는 reboot recovery와 양립하지 않는다. 실제 v3 post-reboot에서 production
plist 8개의 SHA-256과 WorkingDirectory는 모두 pre-reboot와 같았다.

단일 수정 가설은 "audit verifier가 stable identifier와 immutable configuration만
판정해야 한다"야. runtime 실행 경로는 v3에서 reboot RunAtLoad exit 0까지 이미 통과했으므로
runtime SHA를 바꾸지 않는다.

## RED → GREEN

RED 1:

```text
tests/research_runtime/test_reboot_verifier.py
ImportError: scripts.verify_research_runtime_reboot 없음
```

GREEN 1:

```text
boot sec/usec parser와 immutable 비교 4 passed
```

RED 2:

```text
ImportError: verify_production_baseline 없음
```

GREEN 2:

```text
실제 plist SHA-256/WorkingDirectory read-only 검증 6 passed
```

RED 3:

```text
ImportError: verify_reboot_marker 없음
```

GREEN 3:

```text
schema 2 marker 전체 read-only 검증 7 passed
```

test는 `sec=1785233472, usec=925537`에서 boot sec를 결정론적으로 선택하고,
loaded/runs/last-exit 변화는 허용하면서 plist hash 또는 WorkingDirectory drift는
거부한다.

## 최소 수정

- tracked verifier:
  `scripts/verify_research_runtime_reboot.py`
- regression test:
  `tests/research_runtime/test_reboot_verifier.py`
- runtime SHA:
  `7267b642dd9e25a0e199e57c5d41d1e2c04ee419` 유지
- production verifier 입력:
  label, plist SHA-256, plist non-null WorkingDirectory
- launchd volatile state:
  관찰용이며 pass/fail 입력에서 제외
- DB/R2/provider/media/model/Claude/VLM/local LLM 접근:
  0
- production service mutation:
  0

실제 재배포 결과와 control SHA는 v4 pre-reboot/reboot 보고에 additive로 기록한다.
