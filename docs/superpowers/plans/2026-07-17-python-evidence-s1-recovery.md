# Python Evidence S1 Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Confirmed FFmpeg PATH propagation failure를 고치고, frozen S1 workload를 production worker 중단 없이 여러 안전창에서 완주해 `S1R_*` verdict를 낸다.

**Architecture:** `petcam-lab` benchmark harness에 executable dependency preflight와 invalid-key retry semantics를 추가한다. 기존 S1 artifacts는 보존하고 recovery 전용 output에서 동일 manifest·threshold·warmup·repeat를 처음부터 재측정한다. Mac mini에서는 production LaunchAgent와 같은 PATH로 manual foreground run만 실행하고 append-safe resume로 MPS cold/warm과 CPU reduced cells를 완성한다.

**Tech Stack:** Python 3.12, pytest, OpenCV, FFmpeg, RF-DETR/MPS, R2 read-only, Supabase read-only, uv, macOS launchctl read-only probes

## Global Constraints

- 설계 정본: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/docs/superpowers/specs/2026-07-17-python-evidence-s1-recovery-design.md`
- 실행 레포: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1`
- implementation host: `BaekBook-Pro-14-M5.local`
- runtime host: `baeg-endeuui-Macmini.local`
- runtime: read-only manual foreground benchmark. LaunchAgent를 생성·수정·중단하지 않는다.
- original S1 verdict `S1_HOLD_RUNTIME_BUDGET`과 original raw/summary/report를 삭제·재작성하지 않는다.
- sample 32/reduced 16, manifest SHA, influx SHA, conditions, threshold `0.10`, warmup `1`, repeats `3`을 바꾸지 않는다.
- recovery는 새 output directory에서 전체 workload를 처음부터 측정한다. original partial 성능 records를 recovery raw에 복사하지 않는다.
- DB SELECT와 R2 GET만 허용한다. Supabase mutation/RPC/migration, R2 write/delete, Claude/VLM 호출은 금지한다.
- production Gate/nightly HEAD, selector, settings, plist, env, LaunchAgent state를 변경하지 않는다.
- 관련 lock이 free이고 다음 production job까지 최소 25분일 때만 시작한다. 각 foreground run의 hard budget은 20분이다.
- 다른 세션의 untracked/staged 파일을 add·수정·삭제하지 않는다.

---

### Task 1: A6 root-cause correction and executable dependency preflight

**Files:**
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/scripts/benchmark_python_evidence_s1.py`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/tests/test_benchmark_python_evidence_s1.py`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/experiments/python-evidence-s1-throughput/REPORT.md`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/docs/handoff-prompts/2026-07-17-python-evidence-s1-throughput-benchmark-report.md`

**Interfaces:**
- Produces: `verify_executable_dependency(name: str, *, which_fn, run_fn) -> str`
- Produces: preflight error codes `ffmpeg_missing`, `ffmpeg_unusable`
- Consumes: existing `_verify_deps(args) -> int`

- [ ] **Step 1: Write RED tests for missing and unusable FFmpeg**

Add tests that inject `which_fn=lambda _: None` and assert `ffmpeg_missing`; inject an executable-looking path whose `run_fn` returns nonzero/raises timeout and assert `ffmpeg_unusable`. Assert detector loader, R2 resolver, and temp factory are not called.

- [ ] **Step 2: Run the focused tests and confirm RED**

```bash
cd /Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1
uv run pytest -q tests/test_benchmark_python_evidence_s1.py -k 'ffmpeg or verify_deps'
```

Expected: new cases fail because the dependency guard does not exist.

- [ ] **Step 3: Implement the minimal dependency guard**

Resolve `ffmpeg` with `shutil.which`, require an executable path, then run `[resolved, "-version"]` with capture enabled and a five-second timeout. Return the resolved absolute path without printing PATH. Convert missing to `SafetyAbort("ffmpeg_missing", ...)` and unusable/timeout to `SafetyAbort("ffmpeg_unusable", ...)`. Call the guard in dependency verification and normal preflight before detector build, Supabase, R2, or temp creation.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run the Step 2 command. Expected: all focused tests pass.

- [ ] **Step 5: Correct the historical report additively**

Replace only the unverified A6 cause paragraph with the confirmed evidence:

```text
2026-07-17 10:50 KST 재검증: SSH 비로그인 PATH에는 /opt/homebrew/bin이 없었고,
FFmpeg는 /opt/homebrew/bin/ffmpeg에 존재했으며 같은 Python에서 shutil.which("ffmpeg")는 None이었다.
따라서 A6 실패 원인은 PYTHONPATH/temp가 아니라 benchmark 실행 환경의 PATH 전파 누락이다.
```

Do not alter original measured values or `S1_HOLD_RUNTIME_BUDGET`.

- [ ] **Step 6: Commit the isolated correction**

```bash
git add scripts/benchmark_python_evidence_s1.py tests/test_benchmark_python_evidence_s1.py \
  experiments/python-evidence-s1-throughput/REPORT.md \
  docs/handoff-prompts/2026-07-17-python-evidence-s1-throughput-benchmark-report.md
git commit -m "fix: S1 A6 FFmpeg 실행환경 사전검사"
```

### Task 2: Recovery preregistration and completeness contract

**Files:**
- Create: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/experiments/python-evidence-s1-recovery/TEST-SHEET.md`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/scripts/benchmark_python_evidence_s1.py`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/tests/test_benchmark_python_evidence_s1.py`

**Interfaces:**
- Produces: `expected_measured_keys(clips, *, device: str) -> set[tuple]`
- Produces: `successful_completed_keys(path) -> set[tuple]`
- Produces: `completeness_report(expected, actual) -> dict[str, object]`
- Consumes: existing `BenchRecord`, `clips_from_manifest`, `load_completed_keys`

- [ ] **Step 1: Write RED tests for error retry and completeness**

Cover all of these cases:

- a successful measured key is skipped on resume;
- an `error_code=FileNotFoundError` key is not skipped and is retried;
- a warmup record never satisfies a measured key;
- duplicate successful measured keys are rejected;
- MPS expects 32 A6/B12/CROI clips plus reduced 16 DALL clips for both cache modes and repeats 1..3;
- CPU expects reduced 16 for all four conditions, both cache modes, repeats 1..3;
- missing and unexpected keys are returned separately.

- [ ] **Step 2: Run the targeted tests and confirm RED**

```bash
uv run pytest -q tests/test_benchmark_python_evidence_s1.py -k 'resume or completed or completeness or expected_measured'
```

- [ ] **Step 3: Implement success-only resume**

Change resume completion so only records with `error_code is None`, `is_warmup is False`, finite positive `e2e_s`, and a valid measured repeat satisfy a key. Preserve error records for audit, but allow a later successful record for the same key. Treat two successful records for one key as a contract error.

- [ ] **Step 4: Freeze the recovery TEST-SHEET**

The new sheet must copy the original sample/influx hashes, 32/16 manifests, four conditions, threshold `0.10`, warmup `1`, repeats `3`, resource gates, and `160 clips/h` capacity gate verbatim. It must explicitly preregister only this operational change:

```text
execution = multiple independent <=20m foreground runs with append-safe resume;
each run starts only with >=25m safe window and free activity/VLM locks;
original S1 partial records are not imported.
```

Include the four `S1R_*` verdicts from the design. Mark `PRE_REGISTERED` before any recovery canary.

- [ ] **Step 5: Run targeted tests and confirm GREEN**

Run the Step 2 command and verify all selected tests pass.

- [ ] **Step 6: Commit preregistration before runtime execution**

```bash
git add experiments/python-evidence-s1-recovery/TEST-SHEET.md \
  scripts/benchmark_python_evidence_s1.py tests/test_benchmark_python_evidence_s1.py
git commit -m "test: S1 recovery 분할 실행 계약 동결"
git push origin feat/python-evidence-s1-benchmark
```

### Task 3: Local regression and forbidden-behavior audit

**Files:**
- Test only; no new production files.

- [ ] **Step 1: Run focused and full tests**

```bash
cd /Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1
uv run pytest -q tests/test_benchmark_python_evidence_s1.py
uv run pytest -q
uv run python -m compileall -q scripts
git diff --check
```

Expected: all tests pass, compileall and whitespace checks exit 0.

- [ ] **Step 2: Audit forbidden behavior**

Inspect the recovery runtime path and prove it contains no Supabase mutation method, RPC call, R2 write/delete, Claude/VLM invocation, launchctl mutation, plist write, or selector/settings write. Report matches from unrelated legacy code separately; do not modify them.

- [ ] **Step 3: Verify Git state**

Require feature branch local HEAD equals `origin/feat/python-evidence-s1-benchmark` and the owned files are clean. Do not merge main.

### Task 4: Mac mini dependency canary

**Runtime:** manual foreground on `baeg-endeuui-Macmini.local` only.

- [ ] **Step 1: Update the isolated Mac mini worktree**

Fetch and fast-forward `/Users/baek-end/pe-s1-benchmark` to the pushed feature branch. Do not switch or modify production lab/nightly/gate worktrees.

- [ ] **Step 2: Capture read-only baseline**

Record hostname, feature HEAD, production nightly/gate HEADs, LaunchAgent labels/last exit, current locks, next schedules, and temp-media count. Require all expected runtime repos clean and services healthy.

- [ ] **Step 3: Verify the exact PATH contract**

Use only this environment for benchmark commands:

```bash
env PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin \
  PYTHONPATH=/Users/baek-end/pe-s1-benchmark:/Users/baek-end/petcam-nightly-reporter \
  /Users/baek-end/petcam-nightly-reporter/.venv/bin/python \
  /Users/baek-end/pe-s1-benchmark/scripts/benchmark_python_evidence_s1.py --verify-deps \
  --manifest /Users/baek-end/pe-s1-benchmark/experiments/python-evidence-s1-throughput/sample_manifest.json \
  --influx /Users/baek-end/pe-s1-benchmark/experiments/python-evidence-s1-throughput/influx_snapshot.json \
  --pinned-sha "$(git -C /Users/baek-end/pe-s1-benchmark rev-parse HEAD)" \
  --out-dir /Users/baek-end/pe-s1-benchmark/experiments/python-evidence-s1-recovery \
  --device mps --checkpoint /Users/baek-end/gecko-vision-gate/runs/gecko_v2/checkpoint_best_ema.pth
```

Expected: MPS true, checkpoint SHA present, FFmpeg dependency PASS. Do not print the full environment.

- [ ] **Step 4: Execute one A6 canary**

Use one frozen manifest clip and exact `reporter.vlm_frames.extract_six`. Download via the injected read-only R2 adapter into a scoped temp directory, require exactly six decodable JPEGs, then exit the context and prove media count 0. Detector and Claude/VLM call counts must remain 0.

- [ ] **Step 5: Stop on canary failure**

If the canary fails, save only sanitized exception type and stage name in the recovery report draft. Do not start the full recovery run.

### Task 5: Segmented MPS recovery execution

**Files produced on Mac mini ignored runtime path:**
- `experiments/python-evidence-s1-recovery/raw_results.jsonl`
- `experiments/python-evidence-s1-recovery/summary.json`

- [ ] **Step 1: Start from an empty recovery result set**

Require the recovery raw file does not exist. Never copy original S1 records. If a prior recovery attempt exists, inspect and resume it; do not delete evidence without reporting.

- [ ] **Step 2: Probe each safe window**

Before every run, use read-only launchctl/log/lock probes to calculate minutes until the earliest relevant production job. Start only when it is at least 25 minutes and both locks are free. Never bootout, disable, delay, or kickstart a production service.

- [ ] **Step 3: Run MPS with immutable parameters**

Invoke the harness with the exact PATH from Task 4, `--device mps --warmup 1 --repeats 3 --budget-s 1200 --threshold 0.10 --resume`, current feature HEAD as `--pinned-sha`, and recovery out-dir. Pass the probed `--window-minutes` and only set lock-free flags after the live probes pass.

- [ ] **Step 4: Resume across subsequent safe windows**

After every deadline exit, confirm temp media 0, production services unchanged, and partial summary readable. Wait for the next natural safe window, then run the same command. Continue until the MPS completeness report has no missing/unexpected/duplicate-success keys.

- [ ] **Step 5: Preserve operational evidence**

For every segment record start/end KST, feature HEAD, safe-window minutes, service run counters before/after, exit code, records added, temp count, and next missing cell. Never include R2 keys or secrets.

### Task 6: Segmented CPU reduced execution

- [ ] **Step 1: Verify MPS completeness first**

Do not start CPU until all required MPS measured keys are complete and MPS safety checks pass.

- [ ] **Step 2: Run CPU with frozen reduced manifest semantics**

Use the same recovery out-dir, PATH, warmup `1`, repeats `3`, budget `1200`, threshold `0.10`, and `--resume`, changing only `--device cpu`. The harness must select only the frozen reduced 16 clips for CPU.

- [ ] **Step 3: Resume until CPU completeness**

Apply the same 25-minute window, free-lock, 20-minute budget, cleanup, and service invariance checks as Task 5. Stop when CPU expected measured keys have no missing/unexpected/duplicate-success keys.

### Task 7: Independent recomputation, verdict, and SOT closure

**Files:**
- Create: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/experiments/python-evidence-s1-recovery/summary.json`
- Create: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/experiments/python-evidence-s1-recovery/REPORT.md`
- Create: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/docs/handoff-prompts/2026-07-17-python-evidence-s1-recovery-report.md`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/specs/next-session.md`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/experiments/INDEX.md`
- Modify: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/.claude/donts-audit.md`

- [ ] **Step 1: Independently recompute results**

Use a separate read-only Python process that does not import the harness aggregation functions. Recompute expected-vs-actual key completeness, p50, p95, `3600/p95`, CROI ratio against `80 clips/h`, resource peaks, temp zero, and service safety from raw JSONL plus segment logs.

- [ ] **Step 2: Compare independent values**

Require independent and harness counts to match exactly. Require p50/p95/capacity differences to be attributable only to a documented percentile interpolation method and small enough not to cross the `160 clips/h` gate. Otherwise use `S1R_HOLD_INCOMPLETE`.

- [ ] **Step 3: Apply exactly one verdict**

- `S1R_PASS_CROI_THROUGHPUT`
- `S1R_REJECT_CROI_THROUGHPUT`
- `S1R_HOLD_INCOMPLETE`
- `S1R_REJECT_OPERATIONAL_RISK`

Do not rename a recovery verdict to the original `S1_*` namespace.

- [ ] **Step 4: Write the recovery report**

Include confirmed A6 root cause, dependency canary, every execution segment, full completeness matrix, MPS cold/warm and CPU metrics, original-vs-recovery separation, service safety, temp count, mutation/VLM counts, runtime HEADs, limitations, and the single verdict.

- [ ] **Step 5: Update SOT additively**

Preserve the original HOLD as history. Add the recovery verdict and whether S2 planning is allowed. If verdict is not PASS, S2 remains blocked.

- [ ] **Step 6: Run final verification**

```bash
uv run pytest -q
uv run python -m compileall -q scripts
git diff --check
```

Also verify original S1 artifacts still exist and no production runtime repo HEAD changed.

- [ ] **Step 7: Commit and push owned artifacts only**

Do not commit raw videos, frames, R2 keys, secrets, or ignored Mac mini raw JSONL. Commit summary/report/SOT/code/tests owned by this recovery and push `feat/python-evidence-s1-benchmark`. Do not merge main.

- [ ] **Step 8: Stop and report**

Return the report absolute path, exact verdict, feature SHA, test counts, completeness counts, CROI capacity, all safety gates, Mac mini runtime HEADs, and explicit S2 allowed/blocked state.

## Acceptance Checklist

- [ ] Historical A6 cause is corrected to confirmed PATH propagation failure without altering old metrics.
- [ ] Missing/unusable FFmpeg fails before detector/R2/temp.
- [ ] A6 canary produces six frames and cleanup returns media count 0.
- [ ] Recovery uses a new empty result set and imports no original partial records.
- [ ] Frozen sample/threshold/warmup/repeats are unchanged.
- [ ] MPS cold/warm and CPU reduced expected measured keys are complete with no duplicate successes.
- [ ] Every segment respects 25-minute start window, 20-minute budget, and free locks.
- [ ] Production LaunchAgents and runtime repo HEADs are unchanged; DB/R2 writes and VLM calls are 0.
- [ ] Independent recomputation supports exactly one `S1R_*` verdict.
- [ ] Only `S1R_PASS_CROI_THROUGHPUT` allows S2 plan creation.
