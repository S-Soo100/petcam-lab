# Python Evidence S1R2 CROI Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CROI MPS cold 32 clips × measured 3회를 새 raw run으로 완주해 `160 clips/h` 처리량과 production 운영 안전을 PASS 또는 REJECT한다.

**Architecture:** 기존 benchmark full profile을 보존하고, `croi-mps-cold` 고정 profile을 추가한다. 이 profile은 CROI/cold/MPS만 허용하고 96 measured keys를 완전성 정본으로 사용한다. Mac mini의 자연 안전창에서 read-only foreground run을 실행하며, 결과는 기존 S1/S1R artifacts와 분리한다.

**Tech Stack:** Python 3.12, pytest, OpenCV, RF-DETR/MPS, R2 read-only, Supabase read-only, uv, macOS read-only launchctl/log probes

## Global Constraints

- design: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/docs/superpowers/specs/2026-07-17-python-evidence-s1r2-croi-design.md`
- execution repo: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1`
- implementation host: `BaekBook-Pro-14-M5.local`
- runtime host: `baeg-endeuui-Macmini.local`
- feature branch: `feat/python-evidence-s1-benchmark`; main merge 금지
- frozen manifest 32 clips, influx, threshold `0.10`, warmup `1`, repeats `3`, capacity gate `160 clips/h` 유지
- S1R2는 CROI/MPS/cold만 실행한다. expected measured success는 정확히 96이다.
- 기존 S1/S1R raw·summary·report를 수정하거나 새 raw에 복사하지 않는다.
- DB SELECT와 R2 GET만 허용한다. mutation/RPC/migration, R2 write/delete, Claude/VLM 호출 금지.
- production Gate/nightly HEAD, selector/settings, LaunchAgent/plist/env 변경 금지.
- safe window `>=25분`, activity/VLM locks free일 때만 시작; hard budget `1200초`.
- 다른 세션 및 unrelated 파일을 add·수정·삭제하지 않는다.

---

### Task 1: Fixed CROI execution profile

**Files:**
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/scripts/benchmark_python_evidence_s1.py`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/tests/test_benchmark_python_evidence_s1.py`

**Interfaces:**
- Produces: `ExecutionProfile(name: str, device: str, conditions: tuple[str, ...], cache_modes: tuple[str, ...])`
- Produces: `resolve_execution_profile(name: str, requested_device: str) -> ExecutionProfile`
- Produces profile name: `croi-mps-cold`
- Consumes: `run_benchmark`, `build_adapters`, `expected_measured_keys`, `write_summary`

- [ ] **Step 1: Write RED profile tests**

Test that:

- `full` preserves existing conditions and both cache modes;
- `croi-mps-cold` resolves to device `mps`, conditions `("CROI",)`, cache modes `("cold_independent",)`;
- `croi-mps-cold` with requested device `cpu` fails with `profile_device_mismatch`;
- unknown profile is rejected by argparse;
- profile resolution occurs before detector/R2/temp.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
cd /Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1
uv run pytest -q tests/test_benchmark_python_evidence_s1.py -k 'profile or croi_mps_cold'
```

Expected: tests fail because fixed profiles do not exist.

- [ ] **Step 3: Implement the minimal profile**

Add `--profile` with choices `full` and `croi-mps-cold`, default `full`. Keep `--device` for backward compatibility. Resolve one immutable profile before dependency/adapters/data work. Pass `profile.conditions` and `profile.cache_modes` to `run_benchmark`. Store profile name and selected conditions/cache modes in summary metadata.

- [ ] **Step 4: Make FFmpeg dependency conditional**

Only call `verify_ffmpeg_available` when `"A6" in profile.conditions`. For `croi-mps-cold`, dependency status is `not_required` and FFmpeg absence must not block. Preserve full profile behavior exactly.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 6: Commit profile support**

```bash
git add scripts/benchmark_python_evidence_s1.py tests/test_benchmark_python_evidence_s1.py
git commit -m "feat: S1R2 CROI MPS cold 고정 실행 profile"
```

### Task 2: Profile-specific completeness and gate

**Files:**
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/scripts/benchmark_python_evidence_s1.py`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/tests/test_benchmark_python_evidence_s1.py`

**Interfaces:**
- Modify: `expected_measured_keys(clips, *, device, repeats=3, conditions=CONDITIONS, cache_modes=CACHE_MODES) -> set`
- Produces: `evaluate_s1r2_croi_gates(records, *, expected_keys, projected_4cam_p95) -> dict`

- [ ] **Step 1: Write RED completeness tests**

For 32 frozen-equivalent clips assert:

- expected keys are exactly 96 for `CROI/mps/cold/repeat 1..3`;
- A6/B12/DALL/warm/CPU keys are unexpected;
- warmup records do not fill measured keys;
- error records do not fill measured keys;
- duplicate successful key raises contract error;
- 95/96 produces incomplete, 96/96 produces complete.

- [ ] **Step 2: Write RED verdict gate tests**

Cover exactly:

- 96/96 + capacity 160 + resource/safety pass → `S1R2_PASS_CROI_THROUGHPUT`;
- 96/96 + capacity below 160 → `S1R2_REJECT_CROI_THROUGHPUT`;
- 최대 세 번의 안전창 뒤 missing key 존재 → `S1R2_REJECT_CROI_RELIABILITY`;
- independent mismatch 또는 unexpected/duplicate success → `S1R2_REJECT_MEASUREMENT_INTEGRITY`;
- any operational safety violation → `S1R2_REJECT_OPERATIONAL_RISK` and overrides performance.

- [ ] **Step 3: Run tests and confirm RED**

```bash
uv run pytest -q tests/test_benchmark_python_evidence_s1.py -k 'expected_measured or s1r2 or completeness'
```

- [ ] **Step 4: Implement profile-specific expected keys and gate**

Default arguments must preserve full-profile callers. The S1R2 gate consumes only successful measured CROI/mps/cold records, requires exact expected/actual equality, calculates p95 and `3600/p95`, and applies RSS `<=4GiB`, temp peak `<=2GiB`. Service/temp-after/write/VLM safety is supplied explicitly from runtime audit, not inferred from timing records.

- [ ] **Step 5: Run tests and confirm GREEN**

Run the Step 3 command. Expected: all selected tests pass.

- [ ] **Step 6: Commit completeness and gate**

```bash
git add scripts/benchmark_python_evidence_s1.py tests/test_benchmark_python_evidence_s1.py
git commit -m "test: S1R2 CROI 96-key 합격 계약"
```

### Task 3: Preregister S1R2 before runtime

**Files:**
- Create: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/experiments/python-evidence-s1r2-croi/TEST-SHEET.md`

- [ ] **Step 1: Copy immutable input hashes**

Record the existing manifest SHA `931ce37a772d921cf26017801003efebff8686a23a189eca9adcabf397b590d0` and influx SHA `885a45ba3974aa73e1e9bd19a37171829cf6b9174f926bedcf70f71cb20a5cc3`. Do not regenerate or select clips.

- [ ] **Step 2: Freeze the narrowed question**

The TEST-SHEET must explicitly state:

- CROI/MPS/cold only;
- 32 warmup records excluded + 96 measured expected;
- threshold 0.10, warmup 1, repeats 3;
- p95 <=22.5s/capacity >=160 clips/h;
- RSS/temp/service/write/VLM gates;
- previous raw results not imported;
- A6/B12 standalone/DALL/CPU/warm are non-goals and do not enter verdict;
- the five S1R2 PASS/REJECT verdicts and no HOLD verdict;
- S1R2 PASS allows only S2 plan creation.

- [ ] **Step 3: Mark PRE_REGISTERED before Mac mini execution**

Include UTC/KST timestamp and feature commit SHA. No runtime canary or benchmark may run before this commit exists remotely.

- [ ] **Step 4: Commit and push preregistration**

```bash
git add experiments/python-evidence-s1r2-croi/TEST-SHEET.md
git commit -m "test: S1R2 CROI 단독 합격시험 사전등록"
git push origin feat/python-evidence-s1-benchmark
```

### Task 4: Local verification and static safety audit

- [ ] **Step 1: Run focused and full verification**

```bash
uv run pytest -q tests/test_benchmark_python_evidence_s1.py
uv run pytest -q
uv run python -m compileall -q scripts
git diff --check
```

- [ ] **Step 2: Verify backward compatibility**

Run dry parser/profile tests proving default `full` still selects four conditions and two cache modes, and its A6 path still requires FFmpeg.

- [ ] **Step 3: Audit forbidden behavior**

Prove S1R2 runtime path contains no DB mutation/RPC, R2 write/delete, Claude/VLM call, launchctl mutation, selector/settings write, or production code modification.

- [ ] **Step 4: Verify branch publication**

Require local HEAD equals `origin/feat/python-evidence-s1-benchmark`, owned worktree clean, main unmerged.

### Task 5: Mac mini one-window CROI execution

**Runtime:** manual foreground on `baeg-endeuui-Macmini.local`.

- [ ] **Step 1: Fast-forward isolated worktree**

Update `/Users/baek-end/pe-s1-benchmark` to the pushed feature HEAD. Keep production lab/nightly/gate repos untouched.

- [ ] **Step 2: Capture runtime baseline**

Record hostname, feature SHA, production nightly/gate HEADs, loaded services/last exits, recent error counts, locks, next scheduled jobs, and known temp-media count.

- [ ] **Step 3: Require an empty S1R2 output**

Use `/Users/baek-end/pe-s1-benchmark/experiments/python-evidence-s1r2-croi`. If raw exists, inspect and report; do not delete evidence silently. Never copy S1/S1R raw.

- [ ] **Step 4: Run the frozen profile**

Use the exact environment and arguments:

```bash
env PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin \
  PYTHONPATH=/Users/baek-end/pe-s1-benchmark:/Users/baek-end/petcam-nightly-reporter \
  /Users/baek-end/petcam-nightly-reporter/.venv/bin/python \
  /Users/baek-end/pe-s1-benchmark/scripts/benchmark_python_evidence_s1.py \
  --profile croi-mps-cold --device mps \
  --manifest /Users/baek-end/pe-s1-benchmark/experiments/python-evidence-s1-throughput/sample_manifest.json \
  --influx /Users/baek-end/pe-s1-benchmark/experiments/python-evidence-s1-throughput/influx_snapshot.json \
  --pinned-sha "$(git -C /Users/baek-end/pe-s1-benchmark rev-parse HEAD)" \
  --out-dir /Users/baek-end/pe-s1-benchmark/experiments/python-evidence-s1r2-croi \
  --checkpoint /Users/baek-end/gecko-vision-gate/runs/gecko_v2/checkpoint_best_ema.pth \
  --threshold 0.10 --warmup 1 --repeats 3 --budget-s 1200 \
  --window-minutes "$SAFE_WINDOW_MINUTES" --activity-lock-free --vlm-lock-free
```

Set `SAFE_WINDOW_MINUTES` only from the immediate read-only schedule probe. Require `>=25` before command execution.

- [ ] **Step 5: Resume only if necessary**

The expected run should finish within one 20-minute window. If deadline or transient failure leaves missing keys, verify temp/service safety and use the identical command plus `--resume` in the next natural safe window. Maximum three windows; never alter workload.

- [ ] **Step 6: Verify 96-key completion and safety**

Require 96/96 measured success, unexpected 0, duplicate success 0, temp after 0, production heads unchanged, service delay/error/exit increase 0, DB/R2 writes 0, Claude/VLM calls 0.

### Task 6: Independent recomputation and final report

**Files:**
- Create: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/experiments/python-evidence-s1r2-croi/summary.json`
- Create: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/experiments/python-evidence-s1r2-croi/REPORT.md`
- Create: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/docs/handoff-prompts/2026-07-17-python-evidence-s1r2-croi-report.md`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/specs/next-session.md`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/experiments/INDEX.md`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/.claude/donts-audit.md`

- [ ] **Step 1: Recompute without harness aggregators**

Use a separate read-only Python process. From the new raw only, recompute measured key completeness, p50, p95, `3600/p95`, ratio against 80, RSS/temp peaks, and raw SHA. Do not import `aggregate`, `percentile`, `evaluate_s1_gates`, or S1R2 gate code.

- [ ] **Step 2: Compare independent and harness results**

Counts must match exactly. Percentile differences가 판정값을 바꾸거나 counts가 불일치하면 `S1R2_REJECT_MEASUREMENT_INTEGRITY`다. Confirm 128 successful total records expected when warmups are included and no error records remain.

- [ ] **Step 3: Apply one verdict**

- `S1R2_PASS_CROI_THROUGHPUT`
- `S1R2_REJECT_CROI_THROUGHPUT`
- `S1R2_REJECT_OPERATIONAL_RISK`
- `S1R2_REJECT_CROI_RELIABILITY`
- `S1R2_REJECT_MEASUREMENT_INTEGRITY`

실행 전 MPS/checkpoint/import 또는 safe window 문제로 runtime을 시작하지 못한 경우에는 과학적 verdict를 만들지 말고 `BLOCKED_ENVIRONMENT`로 보고한다. 실행을 시작한 뒤에는 HOLD를 사용하지 않는다.

- [ ] **Step 4: Write report and update SOT additively**

Preserve both previous HOLDs as history. Record exact 96-key completeness, CROI metrics, operational safety, runtime HEADs, independence from old raw, and whether S2 planning is allowed.

- [ ] **Step 5: Run final verification**

```bash
uv run pytest -q
uv run python -m compileall -q scripts
git diff --check 6478bdb..HEAD
```

- [ ] **Step 6: Commit and push owned results**

Commit code/tests/TEST-SHEET/summary/report/SOT only. Never commit raw videos, frames, R2 keys, secrets, or Mac mini ignored raw JSONL. Push feature branch; do not merge main.

- [ ] **Step 7: Stop and report**

Return the report absolute path, exact verdict, final SHA, test count, 96-key completeness, p50/p95/capacity, safety gates, runtime HEADs, and `S2 allowed|blocked`.

## Acceptance Checklist

- [ ] TEST-SHEET committed before any S1R2 runtime execution.
- [ ] New raw starts empty and imports no S1/S1R records.
- [ ] Only CROI/MPS/cold executes; expected measured keys are exactly 96.
- [ ] Default full profile remains backward compatible.
- [ ] 96/96 success, unexpected/duplicate 0 또는 명시적 REJECT.
- [ ] Capacity is compared against immutable 160 clips/h gate.
- [ ] Runtime safety, temp 0, write 0, VLM 0, production HEAD invariance are verified.
- [ ] Independent recomputation supports exactly one verdict.
- [ ] PASS alone allows S2 plan creation; no production adoption occurs.
