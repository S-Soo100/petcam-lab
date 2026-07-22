# B1R Runtime Snapshot

> Task 0 산출물. Mac mini runtime을 read-only로 실측한 정본. secret 값은 담지 않는다.
> 측정 일시 기준 = 2026-07-22 (handoff local-vlm-evidence-b1r).

- runtime_verdict: B1R_RUNTIME_OK
- runtime_host: baeg-endeuui-Macmini.local
- lab_head: 7a087b746ec5cc1671ed1b500330bb70da640eaa
- nightly_head: 618f4f854254525b0ebc6f0fcf9153f8e0cd6bc1
- gate_head: 9ea55eb740e9c87dd240b9282d612772dbc798f3
- service_loaded: true
- working_directory: /Users/baek-end/petcam-nightly-reporter
- evidence_schema_version: python-evidence-raw-v1
- algorithm_version: croi-temporal-v1
- coverage_cutoff_started_at: 2026-07-22T02:45:33+00:00

## Runtime 3-repo HEAD / origin ancestry

| repo | Mac mini path | HEAD | origin/main | 상태 |
|---|---|---|---|---|
| petcam-lab | /Users/baek-end/petcam-lab | 7a087b74 | 7a087b74 | clean, HEAD==origin/main |
| petcam-nightly-reporter | /Users/baek-end/petcam-nightly-reporter | 618f4f85 | 618f4f85 | HEAD==origin/main, untracked `.env.bak-20260708-vlmoff`만 (건드리지 않음) |
| gecko-vision-gate | /Users/baek-end/myPythonProjects/gecko-vision-gate | 9ea55eb7 | 9ea55eb7 | clean, HEAD==origin/main |

- Universal Evidence 구현 commit `618f4f854254525b0ebc6f0fcf9153f8e0cd6bc1` = nightly-reporter runtime HEAD = origin/main. drift 없음.
- laptop nightly-reporter local `main` = `1d681ff8` (origin/main보다 뒤짐, checked out branch=feat/vlm-basking-classification). runtime은 laptop이 아니라 Mac mini origin/main 기준으로 판정 — laptop main을 runtime으로 가정하지 않음.

## LaunchAgent 계약 (com.petcam.python-evidence-worker)

- Label: com.petcam.python-evidence-worker
- state: not running (StartInterval 30분 주기 사이 idle), last exit code = 0
- program: /opt/homebrew/bin/uv → `uv run python -m reporter.python_evidence_worker`
- WorkingDirectory: /Users/baek-end/petcam-nightly-reporter
- StartInterval: 1800초 (30분), RunAtLoad: true
- stdout/stderr: /tmp/python-evidence-worker.log
- EnvironmentVariables (secret 제외):
  - PYTHON_EVIDENCE_ENABLED = "1"
  - PYTHON_EVIDENCE_EXPECTED_HOST = "baeg-endeuui-Macmini.local" (실제 hostname과 일치)
  - PYTHON_EVIDENCE_GATE_THRESHOLD = "0.10"

## 판정 근거

- hostname 정확히 일치, service loaded, WorkingDirectory 정확, expected-host 정확, threshold 0.10.
- nightly runtime HEAD가 pushed origin/main과 동일 → FF 통합 안전 (Task 2/6에서 disposable worktree FF-only만 사용).
- active evidence identity(schema/algorithm)를 runtime venv import로 실측 = `python-evidence-raw-v1` / `croi-temporal-v1`.
- coverage_cutoff_started_at = production `motion_clips.started_at` 최댓값 (SELECT-only). 이 시각 이하 clip만 역사 완주 분모. 이후 신규 clip은 live queue가 처리하며 B1R 분모를 움직이지 않는다.
