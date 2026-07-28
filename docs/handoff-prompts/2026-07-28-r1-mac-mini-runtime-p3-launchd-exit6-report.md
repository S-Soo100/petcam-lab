# R1 Mac mini runtime P3 LaunchAgent exit 6 진단·수정 보고

## 판정

`EXIT6_ROOT_CAUSE_FIXED_READY_FOR_V2_HANDOFF`

v1 runtime code `8a7ea47041d02180f2fe03ada54f39f45ccf7c26`의 LaunchAgent RunAtLoad
`SAFETY_VIOLATION(6)` 원인을 확인했고, fix branch
`codex/r1-runtime-launchd-exit6-fix`에서 최소 수정 후 새 runtime code
`a47bea6202b708dd0066155d41904dcb19fccbe5`를 만들었어.

## root cause

launchd 환경 PATH에는 `/usr/sbin`이 없었다.

```text
launchd path_has_usr_sbin=False
manual  path_has_usr_sbin=True
```

runtime `current_boot_id()`는 `sysctl -n kern.boottime`를 bare command로 호출했다. Mac mini에서
`sysctl` 실제 위치는 `/usr/sbin/sysctl`이라 launchd RunAtLoad에서 다음 예외가 동일하게 2회
재현됐다.

```text
FileNotFoundError: [Errno 2] No such file or directory: 'sysctl'
backend/research_runtime/runner.py:62 current_boot_id
backend/research_runtime/runner.py:147 run_once
```

manual command와 launchd의 uid/user/cwd/HOME/TMPDIR/umask/quiet-window/ledger/event 입력은
동일하거나 원인과 무관했고, jobs 0→0, events 0→0이었다.

## 재현과 최소 실험

- launchd diagnostic 1: exit 6, `FileNotFoundError('sysctl')`
- launchd diagnostic 2: exit 6, `FileNotFoundError('sysctl')`
- manual normal PATH: exit 0
- manual launchd-like PATH without `/usr/sbin`: exit 6
- manual launchd-like PATH plus `/usr/sbin:/sbin`: exit 0

provider/DB/R2/media/model/Claude/VLM/local LLM 접근은 0이었고, production service mutation도 0이었다.

## RED → GREEN

RED:

```text
uv run pytest -q tests/research_runtime/test_runner.py::test_current_boot_id_does_not_depend_on_launchd_path
1 failed
```

GREEN:

```text
uv run pytest -q tests/research_runtime/test_runner.py::test_current_boot_id_does_not_depend_on_launchd_path
1 passed
```

수정은 `backend/research_runtime/runner.py`의 `current_boot_id()`에서 `sysctl`을
`/usr/sbin/sysctl` 절대경로로 고정한 한 줄이야.

## fix 검증

```text
uv run pytest -q tests/research_runtime
40 passed in 0.63s
```

```text
R1_SIGKILL_RECOVERY_OK
R1_REBOOT_FENCING_OK
R1_STALE_EPOCH_OK
R1_SINGLETON_OK
R1_MONOTONIC_CLOCK_OK
R1_PRODUCTION_DEFER_OK
R1_STARVATION_BLOCK_OK
R1_DEADLINE_OK
R1_DISK_FAILURE_OK
R1_REDACTION_OK
R1_BOUNDED_TAIL_OK
R1_LEDGER_FAIL_CLOSED_OK
R1_CANCEL_CLEANUP_OK
R1_RESIDUE_ZERO
```

`bash -n scripts/researchctl scripts/install_research_runtime_launchd.sh`도 통과했다.

## v2 설치 입력

- handoff v2:
  `docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-p3-install-handoff-v2.md`
- canary v2:
  `docs/research/run-manifests/jobs/2026-07-28-r1-p3-synthetic-canary-v2.json`
- runtime code v2:
  `a47bea6202b708dd0066155d41904dcb19fccbe5`

v2 `HANDOFF_OK` 전에는 설치하지 않는다.
