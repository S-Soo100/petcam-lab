# RBA Evidence-First Cascade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a new Evidence-First Cascade experiment that shifts safe routing work from VLM calls to deterministic video evidence, then records whether it achieves token reduction without accuracy loss.

**Architecture:** A standalone script extracts low-cost OpenCV features from `dataset-203`, applies conservative non-VLM auto-label/routing rules, simulates VLM fallback using existing baseline predictions or GT oracle only for scoring, and writes reproducible JSON/Markdown reports. The first version prioritizes honest measurement over maximal automation.

**Tech Stack:** Python 3.12, uv, OpenCV, standard library, pytest.

## Global Constraints

- Use `uv run`, not `pip`.
- Do not modify production VLM worker behavior.
- Do not use GT labels, original filename labels, or prediction columns as evidence features.
- Store experiment artifacts under `experiments/rba-evidence-first-cascade/`.
- Treat existing dirty worktree files as user work; do not revert or overwrite them.
- Do not commit automatically.

---

### Task 1: Conservative Cascade Core

**Files:**
- Create: `tests/test_rba_evidence_first_cascade.py`
- Create: `scripts/rba_evidence_first_cascade.py`

**Interfaces:**
- Produces: `VideoEvidence` dataclass
- Produces: `CascadeDecision` dataclass
- Produces: `route_with_conservative_rules(evidence: VideoEvidence) -> CascadeDecision`
- Produces: `score_cascade(rows: Sequence[ScoredDecision], baseline_avg_tokens: float, fallback_avg_tokens: float) -> dict[str, Any]`

- [ ] **Step 1: Write failing unit tests**

Run: `uv run pytest tests/test_rba_evidence_first_cascade.py -q`

Expected: import failure because the script does not exist yet.

- [ ] **Step 2: Implement minimal core functions**

Implement dataclasses, conservative routing rules, and scoring helpers.

- [ ] **Step 3: Run unit tests**

Run: `uv run pytest tests/test_rba_evidence_first_cascade.py -q`

Expected: all tests pass.

### Task 2: Feature Extraction And Experiment Runner

**Files:**
- Modify: `scripts/rba_evidence_first_cascade.py`
- Create: `experiments/rba-evidence-first-cascade/*`

**Interfaces:**
- Consumes: `load_manifest`, `select_stratified`, `sample_id_for` ideas from `scripts/codex_dataset203_sweep.py`
- Produces: `features.jsonl`, `decisions.jsonl`, `results.json`, `REPORT.md`

- [ ] **Step 1: Add video feature extraction**

Extract neutral OpenCV/video metadata without reading labels from filenames.

- [ ] **Step 2: Add CLI**

Support `--sample-size`, `--seed`, `--force`, `--summarize-only`, and `--experiment-dir`.

- [ ] **Step 3: Run pilot**

Run: `uv run python scripts/rba_evidence_first_cascade.py --sample-size 36 --force`

Expected: report is generated under `experiments/rba-evidence-first-cascade/`.

### Task 3: Strategy Report And SOT Links

**Files:**
- Modify: `experiments/rba-evidence-first-cascade/REPORT.md`
- Modify: `specs/experiment-rba-evidence-first-cascade.md`

**Interfaces:**
- Consumes: `results.json`
- Produces: final strategy decision, next experiment recommendation, and explicit distinction from previous strategies.

- [ ] **Step 1: Record measured results**

Update the report with exact measured non-VLM rate, token reduction, accuracy drop, false auto-label rate, and decision.

- [ ] **Step 2: Run verification**

Run:

```bash
uv run pytest tests/test_rba_evidence_first_cascade.py -q
uv run python scripts/rba_evidence_first_cascade.py --summarize-only
```

Expected: tests pass and report regenerates from saved artifacts.
