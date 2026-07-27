# Visibility ROI Baseline Reproduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 과거 visibility 관련 VLM mismatch 44건이 현재 Claude v4.0 평가 계약에서도 안정적으로 재현되는지 production write 없이 판정한다.

**Architecture:** 로컬 alias mp4에서 frozen 6-frame 입력을 만들고 Claude subscription CLI에 최대 4 clips씩 세 번 전달한다. raw 응답은 gitignored 영역에 durable 저장하며, 순수 scorer가 aggregate-only summary와 Phase 0 verdict를 만든다.

**Tech Stack:** Python 3.12, uv, OpenCV, ffmpeg/ffprobe, Claude CLI 2.1.177+, pytest.

## Global Constraints

- production DB/R2/runtime write는 0이다.
- 모델은 exact `claude-sonnet-5`, prompt는 SHA-256으로 고정한 nightly v4.0이다.
- 입력은 clip당 시간순 JPEG 6장, long edge 768px no-upscale, quality 85다.
- GT·과거 VLM 예측·UUID·R2 key는 inference prompt와 tracked 결과에 넣지 않는다.
- Phase 0가 10 stable-error clips 미만이면 Phase 1을 실행하지 않는다.
- 결과를 본 뒤 gate를 바꾸지 않는다.

---

### Task 1: Frozen test contract와 순수 scorer

**Files:**
- Create: `experiments/visibility-bbox-roi-20260727/TEST-SHEET.md`
- Create: `experiments/visibility-bbox-roi-20260727/reproduce.py`
- Create: `experiments/visibility-bbox-roi-20260727/test_reproduce.py`

**Interfaces:**
- Produces: `sample_times(duration: float) -> list[float]`
- Produces: `classify_runs(labels: list[str]) -> str`
- Produces: `summarize(results: dict) -> dict`
- Produces: `decide_phase0(summary: dict) -> str`

- [x] **Step 1: Write failing tests**

```python
def test_sample_times_are_six_segment_midpoints():
    assert sample_times(60.0) == [5.0, 15.0, 25.0, 35.0, 45.0, 55.0]

def test_three_identical_non_moving_labels_are_stable_error():
    assert classify_runs(["shedding"] * 3) == "stable_error"

def test_three_moving_labels_are_stable_correct():
    assert classify_runs(["moving"] * 3) == "stable_correct"

def test_phase0_rejects_when_stable_error_clips_below_ten():
    assert decide_phase0({"stable_error_clips": 9}) == (
        "VISIBILITY_ROI_REJECT_NO_CURRENT_REPRODUCIBLE_FAILURE"
    )
```

- [x] **Step 2: Run tests and verify RED**

Run:

```bash
uv run pytest experiments/visibility-bbox-roi-20260727/test_reproduce.py -q
```

Expected: FAIL because `reproduce.py` does not exist.

- [x] **Step 3: Implement minimal pure functions and validation**

Implement:

```python
ACTIONS = {
    "eating_paste", "eating_prey", "drinking", "shedding",
    "moving", "unseen", "hand_feeding",
}

def sample_times(duration: float) -> list[float]:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("positive_duration_required")
    return [(index + 0.5) * duration / 6 for index in range(6)]

def classify_runs(labels: list[str]) -> str:
    if len(labels) != 3 or any(label not in ACTIONS for label in labels):
        raise ValueError("invalid_run_labels")
    if len(set(labels)) != 1:
        return "unstable"
    return "stable_correct" if labels[0] == "moving" else "stable_error"

def decide_phase0(summary: dict) -> str:
    if summary["stable_error_clips"] < 10:
        return "VISIBILITY_ROI_REJECT_NO_CURRENT_REPRODUCIBLE_FAILURE"
    return "VISIBILITY_ROI_HOLD_EPISODE_LINK_REQUIRED"
```

`summarize`는 stable correct/error/unstable 수, label distribution, unanimity,
token 합계만 반환하며 alias 목록과 reasoning을 반환하지 않는다.

- [x] **Step 4: Run tests and verify GREEN**

Run:

```bash
uv run pytest experiments/visibility-bbox-roi-20260727/test_reproduce.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add experiments/visibility-bbox-roi-20260727/TEST-SHEET.md \
  experiments/visibility-bbox-roi-20260727/reproduce.py \
  experiments/visibility-bbox-roi-20260727/test_reproduce.py
git commit -m "test: visibility baseline 재현 계약"
```

### Task 2: Frame extraction과 Claude CLI durable runner

**Files:**
- Modify: `experiments/visibility-bbox-roi-20260727/reproduce.py`
- Modify: `experiments/visibility-bbox-roi-20260727/test_reproduce.py`

**Interfaces:**
- Produces: `extract_six(video: Path, out_dir: Path) -> list[Path]`
- Produces: `build_command(frame_sets: dict[str, list[Path]], prompt: Path) -> list[str]`
- Produces: `parse_envelope(stdout: str, expected_aliases: set[str]) -> dict`
- Produces: `run_reproduction(...) -> dict`

- [x] **Step 1: Add failing contract tests**

Test that:

- each clip must contain exactly six frames;
- batch size must be 1..4;
- exact model is present in `modelUsage`;
- `is_error`, schema mismatch, alias-set mismatch, and model mismatch fail closed;
- resume skips completed `(run, batch)` keys;
- raw results are written atomically after every successful batch.

- [x] **Step 2: Run focused tests and verify RED**

Run:

```bash
uv run pytest experiments/visibility-bbox-roi-20260727/test_reproduce.py -q
```

Expected: new tests FAIL.

- [x] **Step 3: Implement extraction and runner**

Frame extraction uses:

```bash
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 INPUT
ffmpeg -y -ss TIMESTAMP -i INPUT -frames:v 1 -q:v 3 OUTPUT
```

Then OpenCV downsizes only when the long edge exceeds 768 and writes JPEG quality 85.

Claude command uses:

```text
claude -p <blind prompt>
  --safe-mode
  --tools Read
  --allowed-tools Read
  --add-dir <frame root>
  --model claude-sonnet-5
  --effort low
  --no-session-persistence
  --system-prompt-file <frozen v4.0>
  --output-format json
  --json-schema <7-class batch schema>
```

The runner performs three deterministic passes over sorted `review-*.mp4`, batches at most
four aliases, retries only transient process/envelope errors once, aborts on auth/quota/model/
alias mismatch, and persists `raw/results.json` after each batch.

- [x] **Step 4: Run tests and verify GREEN**

Run:

```bash
uv run pytest experiments/visibility-bbox-roi-20260727/test_reproduce.py -q
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add experiments/visibility-bbox-roi-20260727/reproduce.py \
  experiments/visibility-bbox-roi-20260727/test_reproduce.py
git commit -m "feat: Claude visibility baseline 재현 runner"
```

### Task 3: Preflight, frozen artifacts, and Phase 0 execution

**Files:**
- Create ignored: `experiments/visibility-bbox-roi-20260727/raw/prompt.v4.0.md`
- Create ignored: `experiments/visibility-bbox-roi-20260727/raw/frames/`
- Create ignored: `experiments/visibility-bbox-roi-20260727/raw/results.json`
- Create: `experiments/visibility-bbox-roi-20260727/baseline-summary.json`

**Interfaces:**
- Consumes: 44 local alias mp4s and frozen prompt
- Produces: aggregate-only `baseline-summary.json`

- [x] **Step 1: Verify preflight**

Run:

```bash
claude auth status
claude --version
ffmpeg -version
ffprobe -version
test "$(find experiments/unified-gt-failure-audit-20260727/raw/blind-review-44 \
  -maxdepth 1 -name 'review-*.mp4' | wc -l | tr -d ' ')" = "44"
```

Expected: authenticated, required tools present, 44 videos.

- [x] **Step 2: Freeze prompt by copy and hash**

Copy the read-only nightly v4.0 prompt to ignored raw storage and record only its SHA-256
in `TEST-SHEET.md` before inference.

- [x] **Step 3: Run Phase 0**

Run:

```bash
uv run python experiments/visibility-bbox-roi-20260727/reproduce.py run \
  --video-dir experiments/unified-gt-failure-audit-20260727/raw/blind-review-44 \
  --prompt experiments/visibility-bbox-roi-20260727/raw/prompt.v4.0.md \
  --raw-out experiments/visibility-bbox-roi-20260727/raw/results.json \
  --summary-out experiments/visibility-bbox-roi-20260727/baseline-summary.json
```

Actual: 44 clips × 2 runs completed. Monotonic upper bound 7 < 10으로 pass 3 early-stop.

- [x] **Step 4: Independently rescore**

Run a second process:

```bash
uv run python experiments/visibility-bbox-roi-20260727/reproduce.py score \
  --raw-out experiments/visibility-bbox-roi-20260727/raw/results.json \
  --summary-out /tmp/visibility-baseline-summary.json
cmp experiments/visibility-bbox-roi-20260727/baseline-summary.json \
  /tmp/visibility-baseline-summary.json
```

Expected: byte-identical aggregate summary.

### Task 4: Report, verification, and branch publication

**Files:**
- Create: `experiments/visibility-bbox-roi-20260727/REPORT.md`
- Modify: `experiments/visibility-bbox-roi-20260727/IMPLEMENTATION-PLAN.md`

- [x] **Step 1: Write the report**

Include exact completed clips/runs, stable-error/correct/unstable counts, action distribution,
unanimity, prompt/model/input provenance, gate result, prior ROI comparison, selection-bias
warning, production mutation 0, unexecuted Phase 1, and final verdict.

- [x] **Step 2: Run verification**

```bash
uv run pytest experiments/visibility-bbox-roi-20260727 -q
uv run pytest -q
git diff --check
git status --short
```

Expected: focused and full suite PASS, diff clean, changes only in the experiment directory.

- [ ] **Step 3: Commit and push**

```bash
git add experiments/visibility-bbox-roi-20260727
git commit -m "docs: visibility baseline 재현 판정"
git push -u origin codex/visibility-bbox-roi-20260727
```
