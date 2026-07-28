# R1 Mac mini runtime P3 v7 orchestration rollback 보고

## 판정

`R1_RUNTIME_P3_V7_ORCHESTRATION_CWD_ERROR_ROLLED_BACK`

v7 첫 RunAtLoad는 `runs=1`, last exit 0과 exact WD/root/HEAD/60초를 통과했어.
handoff대로 target을 bootout하고 target plist를 제거한 뒤 production baseline을 다시
검증하는 단계에서 orchestration command가 실패했다.

## exact error

baseline verifier는 control branch의 tracked module인데 command cwd를 runtime checkout으로
둔 채 다음 import를 실행했다.

```python
from scripts.verify_research_runtime_reboot import verify_production_baseline
```

runtime exact SHA에는 이 control-only module이 없으므로:

```text
ModuleNotFoundError: No module named 'scripts.verify_research_runtime_reboot'
```

가 발생했다. runtime code 결함이나 production drift가 아니다.

## rollback 상태

오류 시점에 target은 첫 RunAtLoad 뒤 이미 제거된 상태였고 두 번째 설치는 실행되지 않았다.

- target service/plist/process: absent
- production baseline services: 7 exact
- `com.petcam.vlm-backfill-finalizer`: absent
- local ledger jobs: 7
- v7 `007` jobs: 0
- provider calls/cost: `0/0`
- legacy root: absent
- 뒤 manual/natural/SIGKILL/reboot/24시간 단계: 시작하지 않음

fresh v8은 baseline verifier command의 cwd를
`/Users/baek-end/petcam-lab-r1-runtime-p3-control`로 고정하거나 mode 0600 audit copy를
절대경로 import한다. 같은 v7 attempt는 재개하지 않는다.
