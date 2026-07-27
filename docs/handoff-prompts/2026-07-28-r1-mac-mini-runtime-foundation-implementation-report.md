# R1 Mac mini 연구 runtime foundation 구현 보고

## 판정

`R1_RUNTIME_IMPLEMENTED_AWAITING_FINAL_RECORD`

구현 host에서 strict synthetic no-op runtime과 적대 검증은 통과했어. Mac mini 설치·LaunchAgent
bootstrap·자연 cycle·재부팅·24시간 시험은 하지 않았으므로 `DEPLOYED`나
`RUNTIME_VERIFIED`는 주장하지 않아.

## A→M→B→C provenance

- A 설계·계획 commit:
  `fe2914a5f0623bd9311ae573d8b00cc860d04d6d`
- M start manifest 전용 commit:
  `fdb2893853559555ad3d9c012748ef51871af47f`
- 구현·독립리뷰 보정 tip:
  `42c9f656a9cea3cd0ced673e9780c743b4da9be3`
- B는 이 보고서를 추가하는 전용 구현 완료 commit이야. exact B SHA는 자기참조를 피하기 위해
  C final manifest의 `source.final_commit_sha`에만 기록해.
- C는 다섯 provenance field만 바꾸는 final-record 전용 commit으로 분리해.

M 이후 C 전까지 start manifest는 byte-identical하게 유지했어.

## 구현 범위

- strict `synthetic_noop_v1` job spec과 handler allowlist
- private runtime path, SQLite WAL/FULL ledger, fsync JSONL event 원장
- boot/PID/lease epoch fencing, stale attempt CAS 차단, attempt별 결과 격리
- production lock 비점유 probe와 KST quiet-window 양보
- monotonic wall budget, absolute deadline, process-group TERM→KILL
- child output 선-redaction과 bounded private log
- `researchctl` submit/status/show/tail/cancel
- fail-closed LaunchAgent installer artifact
- 14-scenario synthetic adversarial harness와 운영 runbook

provider call, 비용, production DB/R2/media/dataset/model/Claude/VLM 실행은 모두 0이야. 독립
코드 리뷰에 사용한 Claude CLI는 코드 읽기 전용 리뷰였고 runtime job/provider budget에는
포함되지 않아.

## fresh 검증

2026-07-28 KST, 구현 worktree에서:

- `uv run pytest -q` → `1169 passed, 3 skipped`
- `uv run python -m compileall -q backend/research_runtime scripts/run_research_runtime_adversarial.py`
  → exit 0
- `bash -n scripts/researchctl scripts/install_research_runtime_launchd.sh` → exit 0
- `git diff --check` → exit 0
- synthetic adversarial harness → 아래 14 marker와 exit 0

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

## 독립 리뷰와 보정

Claude Opus read-only 리뷰에서 Important 1건을 찾았어.

- 최초 구현은 stale running job의 epoch·attempt만 올리고 state를 running에 남겨 다음 claim
  대상에서 빠졌어.
- commit `42c9f65`에서 stale job을 fenced `deferred`로 되돌리고, recovery claim 때 attempt
  이중 증가를 막고, `max_attempts` 도달 시 `blocked`로 수렴시켰어.
- 기존 `R1_REBOOT_FENCING_OK`를 실제 recovery claim과 `succeeded` transition까지 검증하도록
  강화했어.
- 후속 Claude Sonnet read-only 리뷰 결과: `REVIEW_PASS`, Critical/Important 0.

## Git·mutation 상태

- branch: `codex/r1-mac-mini-runtime-foundation`
- start upstream: `origin/codex/r1-mac-mini-runtime-foundation` =
  `fdb2893853559555ad3d9c012748ef51871af47f`
- B commit 뒤 같은 feature branch에 FF push할 예정이야.
- primary checkout, main, production DB/R2, media, model, Mac mini, LaunchAgent는 수정하지 않았어.
- tracked secret, raw child output, media artifact는 없어.
- runtime residue는 temp root에서만 만들고 harness 종료 뒤 0이야.

## 아직 미검증

- Mac mini exact checkout·hostname·LaunchAgent loaded 상태
- manual no-op와 자연 60초 cycle
- SIGKILL 뒤 실제 LaunchAgent 복구
- 실제 reboot 복구
- 24시간 지속 운전과 production worker deadline drift

이 항목들은 별도 P3 RUN-MANIFEST, trusted approval, runtime attestation 없이는 시작하지 않아.
