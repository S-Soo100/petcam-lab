# Python Evidence S2 Raw Shadow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` and `superpowers:test-driven-development` task-by-task. Do not infer missing contracts.

**Goal:** Mac mini activity-worker가 기존 Gate 결과와 다운로드를 재사용해 의미 없는 dense ROI/global 시간축 evidence를 append-only shadow row로 만들 수 있게 구현한다.

**Architecture:** raw temporal 계산은 gecko-vision-gate의 순수 모듈이 소유한다. petcam-nightly-reporter는 기존 activity-worker의 index/process/store 경로를 확장하되 feature flag false에서 현재 동작을 그대로 보존한다. petcam-lab은 service-role-only append-only DB 계약과 SOT를 소유한다.

**Tech Stack:** Python 3.12, OpenCV, NumPy, pytest, Supabase/PostgreSQL, uv, three-repo feature branches

## Global constraints

- design: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1/docs/superpowers/specs/2026-07-17-python-evidence-s2-raw-shadow-design.md`
- orchestration repo: `/Users/baek/petcam-lab/.claude/worktrees/python-evidence-s1`
- implementation host: `BaekBook-Pro-14-M5.local`
- runtime kind: none (이번 handoff에서 Mac mini 실행 금지)
- 시작점:
  - lab feature: `feat/python-evidence-s1-benchmark` @ manifest SHA
  - nightly base: `origin/main` @ `19a1fe56792cf43497da8884b9c42ac8db51b5ba`
  - gate base: `origin/main` @ `f182ea4b59c11bd9b7cf4dbb90dc2b2bc9ef022e`
- 각 레포에 `feat/python-evidence-s2-shadow` branch/worktree를 만들되 다른 세션 dirty tree를 건드리지 않는다.
- production DB apply, main merge, LaunchAgent, Mac mini pull/run, selector/VLM/app/GT 변경 금지.
- raw motion/event 숫자만. 행동 candidate enum과 head ROI 추측 금지.
- commit은 task 단위로 의도적으로 나누고 세 feature branch만 push한다.

---

### Task 1: Establish isolated three-repo branches and contract fixtures

**Files:**
- Create isolated worktrees for lab, nightly, gate.
- Create Gate tests: `tests/test_temporal_evidence.py`

- [ ] **Step 1:** Verify manifest HEAD and the three pinned base SHAs. Any mismatch or dirty owned worktree → stop with exact evidence.
- [ ] **Step 2:** Create `feat/python-evidence-s2-shadow` from the pinned base in each repo without deleting existing branches/worktrees.
- [ ] **Step 3:** Add tiny synthetic video/frame fixtures covering moving ROI, global-only lighting change, constant ROI, invalid bbox and 0/1 frame. No real user video in git.
- [ ] **Step 4:** Commit only fixtures/tests after RED is demonstrated.

### Task 2: Gate raw temporal evidence core (TDD)

**Files:**
- Create: `gecko-vision-gate/src/gecko_vision_gate/temporal_evidence.py`
- Modify: `gecko-vision-gate/src/gecko_vision_gate/__init__.py` only if public export is required
- Modify: `gecko-vision-gate/tests/test_temporal_evidence.py`

**Interfaces:**

- `TemporalMotionPoint(t_sec: float, value: float)`
- `TemporalEvidence(...)` frozen dataclass
- `robust_union_gecko_bbox(result: PrelabelResult) -> list[int] | None`
- `compute_temporal_evidence(video_path, result, *, point_cap=256, grid_size=4) -> TemporalEvidence`

- [ ] **Step 1:** Write RED tests for design §4 and VideoCapture release.
- [ ] **Step 2:** Run focused tests and capture RED.
- [ ] **Step 3:** Implement sequential decode, bounded points, ROI/global series, summaries, dwell grid, numeric periodicity and raw motion excursions.
- [ ] **Step 4:** Reject nonfinite/negative contract values; never substitute full-frame for missing bbox.
- [ ] **Step 5:** Run Gate focused + full suite and confirm GREEN.
- [ ] **Step 6:** Commit and push Gate feature branch.

### Task 3: Forward-only append-only DB migration (TDD/static probe)

**Files:**
- Create: `petcam-lab/migrations/2026-07-17_python_evidence_shadow_runs.sql`
- Modify: `petcam-lab/docs/DATABASE.md`
- Add/modify migration tests according to current repo pattern.

- [ ] **Step 1:** Write migration contract tests for table/RLS/grants/RPC/search_path/append-only trigger/identity/JSON cap.
- [ ] **Step 2:** Confirm RED before migration exists.
- [ ] **Step 3:** Implement `clip_python_evidence_runs` and `fn_insert_python_evidence_run` exactly as design §6.
- [ ] **Step 4:** Add rollback SQL as comments. Do not edit older migrations.
- [ ] **Step 5:** Run a transaction rollback probe against a disposable/local schema if available. Production apply is forbidden. If no safe DB target exists, run static tests and report the missing runtime probe honestly.
- [ ] **Step 6:** Commit migration/docs but do not push until Task 7 cross-repo audit.

### Task 4: Nightly store and indexer self-healing (TDD)

**Files:**
- Create: `petcam-nightly-reporter/reporter/python_evidence_store.py`
- Create: `petcam-nightly-reporter/tests/test_python_evidence_store.py`
- Modify: `reporter/activity_indexer.py`
- Modify: `tests/test_activity_indexer.py`

**Interfaces:**

- `find_python_evidence_run(...) -> dict | None`
- `store_python_evidence_run(...) -> dict`
- `list_activity_work_items(..., shadow_enabled, evidence_schema_version, algorithm_version, ...)`

- [ ] **Step 1:** RED tests: flag false has zero evidence-table query; missing assessment/evidence union selection; pagination starvation; terminal `no_bbox` counts complete; identity mismatch counts missing.
- [ ] **Step 2:** Implement service-role RPC mapper without raw DB error leakage.
- [ ] **Step 3:** Keep existing `list_unprocessed_clips` public behavior backward compatible.
- [ ] **Step 4:** Run focused/full nightly tests.
- [ ] **Step 5:** Commit store/indexer changes.

### Task 5: Extend activity-worker without duplicate detector/download (TDD)

**Files:**
- Modify: `reporter/activity_worker.py`
- Modify: `reporter/gate_runner.py` only if a typed result hook is required
- Modify: `reporter/config.py`, `.env.example`
- Modify: `tests/test_activity_worker.py`, `tests/test_gate_runner.py`

- [ ] **Step 1:** RED tests for:
  - shadow false exact legacy path/query/call counts;
  - new clip download once, detector once, temporal once;
  - existing prelabel path detector zero, download once;
  - evidence-only failure preserves Gate/assessment and returns nonzero;
  - next run self-heals only temporal evidence;
  - idempotent conflict does not alter existing row;
  - host/policy guard before DB/R2;
  - temp cleanup success/failure.
- [ ] **Step 2:** Add config:
  - `PYTHON_EVIDENCE_SHADOW_ENABLED=false`
  - `PYTHON_EVIDENCE_BATCH_LIMIT` clamped to `ACTIVITY_BATCH_LIMIT`
  - schema/algorithm versions imported from the Gate contract, not duplicated free text.
- [ ] **Step 3:** Refactor the minimum process flow needed to share the same local mp4. Do not rewrite unrelated activity policy/store logic.
- [ ] **Step 4:** Add summary counters only to internal activity log: `temporal_ok`, `temporal_terminal`, `temporal_reused`, `temporal_failed`. No Slack change.
- [ ] **Step 5:** Run focused/full nightly tests and commit.

### Task 6: Cross-repo adversarial safety tests

- [ ] **Step 1:** Test malformed DB JSON, series >256, NaN/Infinity, negative timestamps, mismatched prelabel identity.
- [ ] **Step 2:** Test UPDATE/DELETE/TRUNCATE blocker and duplicate RPC behavior via rollback probe or SQL test harness.
- [ ] **Step 3:** Static audit new runtime path for forbidden tokens/writes:
  - no `clip_vlm_jobs`, selector score, Claude/Groq/API calls;
  - no `behavior_labels`, `clip_labeling_sessions`, app activity view mutation;
  - no LaunchAgent/plist changes;
  - no raw exception/secret output.
- [ ] **Step 4:** Confirm no real mp4/jpg/jsonl evidence is tracked.

### Task 7: Full verification and SOT/report

**Files:**
- Modify additively: `petcam-lab/docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`
- Modify additively: `petcam-lab/specs/next-session.md`
- Modify additively: nightly/gate next-session or README only where current project convention requires it
- Create: `petcam-lab/docs/handoff-prompts/2026-07-17-python-evidence-s2-raw-shadow-report.md`

- [ ] **Step 1:** Run Gate full pytest, nightly full pytest, lab full pytest, compileall, `git diff --check`, migration checks.
- [ ] **Step 2:** Record exact test counts, branch SHAs, files, backward-compat proof and forbidden-action audit.
- [ ] **Step 3:** Write S2B deployment prerequisites, but do not apply them.
- [ ] **Step 4:** Commit/push the three feature branches. Require local==origin and owned worktrees clean.
- [ ] **Step 5:** Final report verdict must be exactly one:
  - `S2_IMPLEMENTATION_READY_FOR_DEPLOY_REVIEW`
  - `S2_IMPLEMENTATION_HOLD_CONTRACT`
  - `S2_IMPLEMENTATION_HOLD_TESTS`
  - `S2_IMPLEMENTATION_BLOCKED_ENVIRONMENT`

## Stop point

Stop after Task 7. Do not merge main, apply migration, touch Mac mini, enable the flag, run a production canary, or start historical evidence backfill. Codex will review the report and write a separate S2B deployment plan.
