# S0.1 Frame Sampling Self-Healing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 0프레임 evidence가 완료 상태로 굳는 결함을 복구하고, 기존 불완전 assessment를 자동 재처리한 뒤 S0 coverage 감사를 다시 통과시킨다.

**Architecture:** Gate는 metadata/seek 실패에 bounded-memory sequential fallback을 제공한다. Nightly는 최소 프레임 미달을 저장 성공으로 인정하지 않고, 현재 assessment가 불완전 prelabel을 가리키면 다시 선택한다. 기존 0프레임 prelabel은 immutable audit history로 남기고 current assessment만 정상 evidence로 relink한다.

**Tech Stack:** Python 3.12, OpenCV, pytest, Supabase, launchd, uv

## Global Constraints

- 설계: `/Users/baek/petcam-lab/docs/superpowers/specs/2026-07-16-s0-frame-sampling-self-healing-design.md`
- 기준 SHA: gate `9e39596bdb907a86496948f4bf3a13fe760d8222`, nightly production main `cbd2e09ed00857bdbd8a27c3f0483881c9abdbd6`, lab는 handoff manifest SHA.
- 현재 `/Users/baek/petcam-nightly-reporter` primary working tree는 다른 세션의 feature branch와 미커밋 파일이 있다. branch 전환·수정·stash·cleanup 금지. 반드시 별도 worktree를 사용한다.
- Gate도 별도 feature worktree에서 작업하고 primary main은 구현 중 건드리지 않는다.
- DB migration과 직접 UPDATE/DELETE/보정 RPC 금지. 기존 0프레임 prelabel 보존.
- VLM/Claude/selector/backfill/GT/behavior label/app activity 설정 변경 금지.
- production runtime 변경은 Mac mini `com.petcam.activity-worker`만 허용한다.
- 배포 전 모든 코드가 main에 fast-forward push되고 Mac mini에서 정확한 SHA를 확인해야 한다.
- S0 재감사 전에는 S1을 시작하지 않는다.

---

### Task 1: Live 0-frame 원인 진단과 재현 fixture 고정

**Files:**
- Create: `/Users/baek/petcam-lab/docs/handoff-prompts/2026-07-16-s0-frame-sampling-self-healing-report.md` (진행 기록 후 최종 보고서로 완성)

**Interfaces:**
- Consumes: production `clip_prelabels`, `clip_activity_assessments`, `motion_clips`, R2 read-only
- Produces: 문제 clip별 metadata count, sequential decode count, indexed read count

- [ ] **Step 1: Verify handoff and all three repository heads**

Run the manifest validator first. Fetch all repos without changing working trees. If gate/nightly origin main differs from the pinned SHA, stop and report drift before implementing.

- [ ] **Step 2: Query current incomplete evidence read-only**

Select `frames_sampled < 6`, producer provenance, assessment reason, clip start time and R2 key internally. Report only clip short IDs and counts. Freeze a diagnostic timestamp.

- [ ] **Step 3: Diagnose every incomplete clip on Mac mini**

For each clip, download into one `TemporaryDirectory` and record:

```text
CAP_PROP_FRAME_COUNT
CAP_PROP_FPS
indexed target count / successful indexed reads
sequential decodable frame count
ffprobe duration/frame metadata when available
```

Do not run detector or VLM. Do not preserve video/frame artifacts.

- [ ] **Step 4: Classify root cause**

Use exactly one of: `metadata_count_zero`, `indexed_seek_failure`, `truncated_or_undecodable`, `mixed`. If sequential decode also yields fewer than 6, mark the clip `permanent_candidate` rather than pretending fallback will repair it.

- [ ] **Step 5: Confirm temp media 0 and document the diagnostic**

Stop if any source video cannot be accounted for or cleanup fails.

### Task 2: Gate bounded-memory sequential fallback

**Files:**
- Modify: `/Users/baek/myPythonProjects/gecko-vision-gate/src/gecko_vision_gate/frame_sampling.py`
- Modify: `/Users/baek/myPythonProjects/gecko-vision-gate/tests/test_frame_sampling.py`
- Create: `/Users/baek/myPythonProjects/gecko-vision-gate/reports/R0003-frame-sampling-fallback.md`

**Interfaces:**
- Preserves: `sample_frames(video_path, num_frames=12) -> list[tuple[float, np.ndarray]]`
- Produces internal helpers: `_count_sequential_frames(path)`, `_sample_sequential(path, total, num_frames, fps)`

- [ ] **Step 1: Create an isolated Gate worktree**

Create `feat/s0-frame-sampling-self-healing` from the pinned clean `origin/main`. Do not switch the primary repo branch.

- [ ] **Step 2: Write RED tests**

Tests must cover:

```python
def test_zero_metadata_count_falls_back_to_sequential_decode(): ...
def test_indexed_read_shortfall_falls_back_to_sequential_decode(): ...
def test_normal_metadata_path_does_not_open_fallback_passes(): ...
def test_fallback_keeps_at_most_requested_frames(): ...
def test_every_video_capture_is_released_on_success_and_failure(): ...
```

Use a fake `VideoCapture`; do not add binary fixtures to git.

- [ ] **Step 3: Run tests and confirm RED**

Run: `uv run pytest -q tests/test_frame_sampling.py`

Expected: fallback tests fail against current implementation.

- [ ] **Step 4: Implement two-pass sequential fallback**

Keep the normal indexed path byte-for-byte equivalent. The fallback first counts decodable frames without retaining arrays, reopens the video, then stores only `evenly_spaced_indices(total, num_frames)`. Never append all decoded frames.

- [ ] **Step 5: Run Gate verification**

```bash
uv run pytest -q tests/test_frame_sampling.py
uv run pytest -q
git diff --check
```

Expected: all Gate tests pass and the report explains why this is infrastructure recovery, not Gate v3 behavior work.

- [ ] **Step 6: Commit and push Gate branch**

Commit only the sampler, tests, and R0003 report. Push the feature branch; do not merge yet.

### Task 3: Nightly minimum-frame write barrier

**Files:**
- Modify in isolated worktree: `reporter/gate_runner.py`
- Modify: `tests/test_gate_runner.py`
- Modify: `tests/test_activity_worker.py`

**Interfaces:**
- Produces: `InsufficientSampleFrames(found: int, required: int)`
- Preserves: `assess_clip(...) -> GateAssessment` for valid clips

- [ ] **Step 1: Create an isolated nightly worktree**

Create `feat/s0-evidence-self-healing` from pinned `origin/main@cbd2e09...`. The existing primary feature branch and its untracked files are out of scope.

- [ ] **Step 2: Write RED tests for 0–5 and 6 frames**

```python
def test_assess_clip_rejects_zero_frames_before_detector(): ...
def test_assess_clip_rejects_five_frames_before_storeable_result(): ...
def test_assess_clip_accepts_six_frames(): ...
```

Assert the detector is not called for insufficient frames and the exception exposes counts but no file path.

- [ ] **Step 3: Implement the minimum-frame barrier**

Immediately after `sample_fn`, raise `InsufficientSampleFrames` when `len(frames) < policy.min_frames`. Do not modify `ActivityPolicy.min_frames` or the four-state decision function.

- [ ] **Step 4: Verify process isolation and exit semantics**

Add or retain tests proving `process_batch` increments `failed`, never calls `store_fn` for the rejected clip, continues other clips, and `run()` returns 1 when any clip failed.

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest -q tests/test_gate_runner.py tests/test_activity_worker.py`

Expected: all focused tests pass.

### Task 4: Nightly incomplete-assessment requeue

**Files:**
- Modify: `reporter/activity_indexer.py`
- Modify: `reporter/activity_worker.py`
- Modify: `tests/test_activity_indexer.py`
- Modify: `tests/test_activity_worker.py`

**Interfaces:**
- Changes: `list_unprocessed_clips(..., *, min_frames: int = 6, limit=200, page_size=500)`
- Consumer: `activity_worker.run()` passes `min_frames=policy.min_frames`

- [ ] **Step 1: Write RED requeue tests**

Cover assessment-linked prelabels with `frames_sampled` 0, 5, 6, missing referenced prelabel, and mixed pages over 1,000 clips. Assert 0/5/missing are returned and 6 is done.

- [ ] **Step 2: Implement two-stage done validation**

For each motion clip page:

1. load current-policy assessments as `(clip_id, prelabel_id)`;
2. batch-load referenced prelabels as `(id, frames_sampled)`;
3. add a clip to `done_ids` only if its linked prelabel exists and `frames_sampled >= min_frames`.

Do not change the evidence identity or delete old rows.

- [ ] **Step 3: Pass policy minimum from worker**

Update the call explicitly with `min_frames=policy.min_frames`. Add a regression assertion so a future policy minimum change is not silently ignored.

- [ ] **Step 4: Test successful relink behavior with fakes**

Seed an assessment pointing to a 0-frame prelabel. Run one worker batch whose sample succeeds with 12 frames. Assert the old prelabel remains and the same current policy assessment points to the new 12-frame prelabel.

- [ ] **Step 5: Run nightly full verification**

```bash
uv run pytest -q
python -m compileall -q reporter tests
git diff --check
```

- [ ] **Step 6: Commit and push nightly feature branch**

Commit only Task 3–4 files. Do not touch the primary dirty working tree.

### Task 5: Cross-repo review, fast-forward integration, and Mac mini canary

**Files:**
- Modify only if verified: Gate and nightly `main` histories through fast-forward commits
- No petcam-lab DB/schema files

**Interfaces:**
- Runtime: `launchagent@baeg-endeuui-Macmini.local`
- Service: `com.petcam.activity-worker`

- [ ] **Step 1: Review cross-repo contract**

Confirm nightly still loads Gate through the editable sibling path and Mac mini has both repos at the expected locations. Verify Gate branch tests and nightly branch tests using the two feature commits together.

- [ ] **Step 2: Fast-forward origin/main without force**

Only if each `origin/main` is still the pinned base, push Gate feature commit to Gate main, then nightly feature commit to nightly main. Any upstream drift requires rebase/retest and a report; do not overwrite.

- [ ] **Step 3: Pre-deploy runtime snapshot**

On Mac mini record hostname, Gate/nightly HEAD, LaunchAgent WorkingDirectory/env/last exit, incomplete current assessment count and short IDs, source table counts, and temp media count.

- [ ] **Step 4: Deploy Gate then nightly**

Bootout only `com.petcam.activity-worker`, pull both main repos, run `uv sync --frozen` in nightly, run both full test suites on Mac mini, verify editable Gate resolves to the pulled sibling repo, then bootstrap the unchanged plist.

- [ ] **Step 5: Run one canary cycle**

Use the real LaunchAgent environment. Verify hostname guard passes, incomplete clips are selected again, recoverable clips relink current assessment, unrecoverable clips create no new evidence, other clips continue, no `frames_sampled<6` row is newly created, and temp media returns to 0.

- [ ] **Step 6: Observe one natural hourly cycle**

Do not call deployment verified from kickstart alone. Confirm the next natural cycle uses the same HEAD, exits consistently with its clip outcomes, and creates no incomplete evidence.

- [ ] **Step 7: Roll back on any stop condition**

Bootout activity-worker, revert the two implementation commits in reverse order, push normal revert commits, pull Mac mini, restore service, and preserve logs. Never reset or force-push.

### Task 6: S0 rerun, SOT closure, and final report

**Files:**
- Create: `reports/python-evidence-s0-coverage-20260716-rerun/` five audit artifacts
- Modify: `docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`
- Modify: `specs/next-session.md`
- Complete: `docs/handoff-prompts/2026-07-16-s0-frame-sampling-self-healing-report.md`

**Interfaces:**
- Consumes: existing `scripts/audit_python_evidence_coverage.py`
- Produces: S0 rerun verdict; S1 remains gated by it

- [ ] **Step 1: Freeze a new as-of and rerun the existing audit**

Use the same start/policy/selector arguments as the first audit but output to `reports/python-evidence-s0-coverage-20260716-rerun/`. Do not overwrite the first report.

- [ ] **Step 2: Independently reconcile the rerun**

Reconcile eligible clips, unique prelabels, current-policy assessment linkage, regular/backfill run/job counts, and current incomplete evidence. Distinguish preserved historical 0-frame prelabels from current assessment linkage.

- [ ] **Step 3: Apply the S0 gate**

- `S0_PASS`: state that S1 may be planned next; do not start it.
- `S0_PASS_WITH_COVERAGE_GAP`: name the exact covered subset; no generalization.
- `S0_HOLD_DATA_CONTRACT`: keep S1 stopped and explain remaining root cause.

- [ ] **Step 4: Update SOT additively**

Preserve the first S0 failure history and add the self-healing result. Record Gate/nightly production SHAs and Mac mini canary/natural-cycle evidence.

- [ ] **Step 5: Final verification**

Run full tests in all changed repos, `git diff --check`, mutation/secret scans, main/origin sync checks, source table mutation attribution, and temp media 0 check.

- [ ] **Step 6: Commit and push petcam-lab artifacts**

Stage only Task 6 artifacts and SOT files. Preserve unrelated untracked files. Push main normally.

- [ ] **Step 7: Stop and report through the document**

Final report must list diagnostics, both implementation commits, tests, deployment evidence, old/new current-linkage counts, S0 rerun verdict, rollback readiness, and all forbidden actions not performed. Return only the absolute report path and `VERIFIED`, `PASS_WITH_COVERAGE_GAP`, or `NOT_VERIFIED`. Do not start S1.
