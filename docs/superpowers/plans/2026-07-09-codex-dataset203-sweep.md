# Codex Dataset203 Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repeatable Codex CLI experiment harness that measures token reduction, accuracy drop, and speed on `dataset-203`.

**Architecture:** A standalone script prepares blind image assets from the existing dataset, calls `codex exec --image` with structured output, stores one JSON record per call, then summarizes paired `frames-adaptive` vs `contact-sheet` results. Tests cover deterministic sampling, usage parsing, scoring, and cascade simulation without making model calls.

**Tech Stack:** Python 3.12 standard library, ffmpeg/ffprobe, Codex CLI, pytest.

## Global Constraints

- Use `uv run`, not `pip`.
- Do not change production VLM worker behavior.
- Hide GT labels and original filenames from Codex prompts and attached image paths.
- Store experiment artifacts under `experiments/codex-dataset203-model-sweep/`.
- Resume safely: completed model calls must not be repeated unless `--force` is passed.
- Do not commit automatically.

---

### Task 1: Spec And Harness Skeleton

**Files:**
- Create: `specs/experiment-codex-dataset203-sweep.md`
- Create: `docs/superpowers/plans/2026-07-09-codex-dataset203-sweep.md`
- Create: `scripts/codex_dataset203_sweep.py`
- Test: `tests/test_codex_dataset203_sweep.py`

**Interfaces:**
- Produces: `load_manifest(path: Path) -> list[ClipRow]`
- Produces: `select_stratified(rows: Sequence[ClipRow], target_size: int, seed: int) -> list[ClipRow]`
- Produces: `extract_usage_from_text(text: str) -> TokenUsage | None`
- Produces: `summarize_records(records: Sequence[CallRecord]) -> dict[str, Any]`

- [x] **Step 1: Write spec and implementation plan**

Create the experiment spec and this plan before implementation.

- [ ] **Step 2: Write unit tests**

Run: `uv run pytest tests/test_codex_dataset203_sweep.py -q`

Expected before implementation: import/function failures.

- [ ] **Step 3: Implement script functions**

Implement dataclasses, sampling, usage parsing, result scoring, and CLI argument parsing.

- [ ] **Step 4: Run unit tests**

Run: `uv run pytest tests/test_codex_dataset203_sweep.py -q`

Expected: all tests pass.

### Task 2: Codex Smoke And Pilot

**Files:**
- Modify: `scripts/codex_dataset203_sweep.py`
- Create: `experiments/codex-dataset203-model-sweep/*`

**Interfaces:**
- Consumes: script CLI from Task 1.
- Produces: `results.jsonl`, `summary.json`, `summary.csv`, `REPORT.md`.

- [ ] **Step 1: Run smoke**

Run: `uv run python scripts/codex_dataset203_sweep.py --sample-size 1 --models gpt-5.5 --representations contact-sheet frames-adaptive --force`

Expected: 2 records, one per representation, with prediction JSON and wall-clock seconds.

- [ ] **Step 2: Run model smoke**

Run: `uv run python scripts/codex_dataset203_sweep.py --sample-size 1 --models gpt-5.5 gpt-5.3-codex gpt-5.4-mini --representations contact-sheet frames-adaptive`

Expected: 6 total records unless a model is unavailable; unavailable models are reported, not hidden.

- [ ] **Step 3: Run pilot**

Run: `uv run python scripts/codex_dataset203_sweep.py --sample-size 36 --models gpt-5.5 gpt-5.3-codex gpt-5.4-mini --representations contact-sheet frames-adaptive`

Expected: resumable JSONL records and a summary report with token reduction, accuracy drop, and speed.

- [ ] **Step 4: Verify report**

Run: `uv run python scripts/codex_dataset203_sweep.py --summarize-only`

Expected: report regenerates from saved records without new model calls.
