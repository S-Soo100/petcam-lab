# Mac mini Local VLM Evidence Analyst Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task with review checkpoints.

**Goal:** Mac mini M1 16GB에서 SmolVLM2 2.2B MLX가 Universal Python Evidence와 deterministic 6프레임을 읽어 사람 evidence GT와 일치하는 보조 관찰을 안정적으로 생성하는지, production에 연결하지 않고 재현 가능한 240-key benchmark로 검증한다.

**Architecture:** `petcam-lab`은 시험지·manifest·GT validator·scorer·보고서 SOT를 소유한다. `petcam-rba-worker`는 입력 materializer·MLX adapter·strict parser·one-shot runner를 소유한다. `gecko-vision-gate`는 동결 checkpoint의 read-only 프레임 검출 의존성으로만 사용하고 수정하지 않는다. Gate 입력 생성과 MLX 추론은 메모리에서 순차 실행한다.

**Tech Stack:** Python 3.12, uv, pytest, OpenCV/Pillow, existing Universal Python Evidence, gecko-vision-gate, MLX-VLM 0.6.5, SmolVLM2 2.2B MLX, JSONL, stdlib statistics/bootstrap.

## Global constraints

- production DB는 SELECT only, R2는 GET only다.
- 행동 GT·selector·VLM job·app activity·Python Evidence 원장에 쓰지 않는다.
- LaunchAgent·plist·상주 model server를 만들지 않는다.
- measured key당 generation은 정확히 1회다. schema/content 실패를 재호출하지 않는다.
- Qwen 모델은 상용 허가 전 다운로드·실행하지 않는다.
- model·runtime 설치와 benchmark 실행은 owner의 별도 승인 대상이다.
- raw media·frame·model text는 `storage/local-vlm-evidence-analyst/` 밖에 두지 않는다.
- 구현 중 각 task는 RED→GREEN 테스트 후 commit한다. cross-repo handoff 전 세 branch를 push한다.

---

### Task 1: 실험 계약과 artifact validator 고정

**Files:**
- Modify: `/Users/baek/petcam-lab/experiments/local-vlm-evidence-analyst/TEST-SHEET.md`
- Modify: `/Users/baek/petcam-lab/experiments/local-vlm-evidence-analyst/REPORT-TEMPLATE.md`
- Create: `/Users/baek/petcam-lab/scripts/validate_local_vlm_evidence_manifest.py`
- Test: `/Users/baek/petcam-lab/tests/test_validate_local_vlm_evidence_manifest.py`

**Step 1: Write failing contract tests**

Test these cases:

- valid 180 unique clips / 6 strata×30 / dev120·holdout60
- duplicate clip, episode leakage, dev↔holdout leakage
- camera<2, date<3, missing evidence GT
- repeat set 30 clips with strata×5 and exactly two extra keys
- manifest/GT hash mismatch

**Step 2: Run RED**

```bash
cd /Users/baek/petcam-lab
uv run pytest tests/test_validate_local_vlm_evidence_manifest.py -q
```

Expected: import or assertion failure because validator does not exist.

**Step 3: Implement minimum validator**

Expose pure functions:

```python
def validate_manifest(manifest: dict, gt_rows: list[dict]) -> list[str]: ...
def build_measured_keys(manifest: dict, repeat_seed: int = 20260721) -> list[dict]: ...
```

CLI returns nonzero and stable error codes; it must not query Supabase.

**Step 4: Run GREEN and regression**

```bash
uv run pytest tests/test_validate_local_vlm_evidence_manifest.py -q
uv run pytest -q
git diff --check
```

**Step 5: Commit**

```bash
git add experiments/local-vlm-evidence-analyst scripts/validate_local_vlm_evidence_manifest.py tests/test_validate_local_vlm_evidence_manifest.py
git commit -m "test: local VLM evidence 벤치마크 계약 고정"
```

---

### Task 2: strict output schema·prompt·parser 구현

**Files:**
- Create: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/schema.py`
- Create: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/prompt.py`
- Create: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/parser.py`
- Create: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/__init__.py`
- Test: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_schema.py`

**Step 1: Write failing parser tests**

Cover valid JSON, markdown fence, leading prose, missing/extra key, wrong enum, wrong list item, observation>240 chars, banned behavior token, non-boolean abstain, text>4KB.

**Step 2: Run RED**

```bash
cd /Users/baek/petcam-rba-worker
uv run pytest tests/test_local_evidence_schema.py -q
```

**Step 3: Implement strict dataclass boundary**

Use enums/typed dataclass and return stable `ParseFailure(code, redacted_length, fingerprint)`. Do not repair JSON, strip fences, infer missing fields, or preserve raw reasoning in normal logs.

Prompt must:

- describe frames as time-ordered observations
- include Python Evidence as untrusted evidence, not truth
- prohibit behavior labels and health conclusions
- explicitly allow `uncertain` and `abstain=true`
- request one JSON object only

**Step 4: Run GREEN**

```bash
uv run pytest tests/test_local_evidence_schema.py -q
uv run pytest -q
git diff --check
```

**Step 5: Commit**

```bash
git add backend/local_evidence_analyst tests/test_local_evidence_schema.py
git commit -m "feat: local evidence 출력 계약과 strict parser 추가"
```

---

### Task 3: MLX-VLM adapter와 의존성 격리

**Files:**
- Modify: `/Users/baek/petcam-rba-worker/pyproject.toml`
- Modify: `/Users/baek/petcam-rba-worker/uv.lock`
- Create: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/mlx_adapter.py`
- Test: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_mlx_adapter.py`

**Step 1: Add failing fake-runtime tests**

Test lazy import, pinned model/revision validation, six-image call, temperature 0, max_tokens 256, one generation per key, `GenerationResult.text`, peak memory capture, load/generate error taxonomy, unload cleanup.

**Step 2: Run RED**

```bash
uv run pytest tests/test_local_evidence_mlx_adapter.py -q
```

**Step 3: Add optional benchmark group**

```bash
uv add --group local-evidence-benchmark "mlx-vlm==0.6.5"
```

Verify resolved wheel hash matches TEST-SHEET. Keep import inside adapter methods so default project/test import does not require MLX.

**Step 4: Implement adapter**

Constants:

```python
MODEL_REPO = "mlx-community/SmolVLM2-2.2B-Instruct-mlx"
MODEL_REVISION = "844516024a1c4400d34489b89ee067d794e432ed"
MAX_TOKENS = 256
TEMPERATURE = 0.0
```

Use MLX-VLM `load(..., revision=...)`, processor chat template for six images, and `generate`. Validate local snapshot revision before measured run.

**Step 5: Run GREEN without model download**

```bash
uv run pytest tests/test_local_evidence_mlx_adapter.py -q
uv run pytest -q
git diff --check
```

All unit tests inject fake MLX modules; no model network access.

**Step 6: Commit**

```bash
git add pyproject.toml uv.lock backend/local_evidence_analyst/mlx_adapter.py tests/test_local_evidence_mlx_adapter.py
git commit -m "feat: SmolVLM2 MLX benchmark adapter 추가"
```

---

### Task 4: deterministic 입력 materializer 구현

**Files:**
- Create: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/materializer.py`
- Test: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_materializer.py`

**Step 1: Write failing tests**

Cover:

- exactly six deterministic timestamps
- two global and four evidence images, timestamp ordered
- read-only Gate detections across six frames → bbox union
- 1.5× padding and frame clamp
- no bbox → same four timestamps as full-frame evidence, `roi_mode=full_frame_no_detection`, no fabricated center crop
- long edge≤384 with aspect ratio preserved
- frame/input hash stability
- one R2 download per clip
- partial extraction cleanup and temp 0

**Step 2: Run RED**

```bash
uv run pytest tests/test_local_evidence_materializer.py -q
```

**Step 3: Implement with injected boundaries**

```python
def materialize_clip(
    clip: ClipInput,
    *,
    downloader: Downloader,
    frame_sampler: FrameSampler,
    gate_detector: GateDetector,
    temp_root: Path,
) -> MaterializedInput: ...
```

Use the frozen Gate checkpoint read-only. Do not update `clip_prelabels`. Return only paths/hashes/provenance; ownership of cleanup remains explicit.

**Step 4: Run GREEN**

```bash
uv run pytest tests/test_local_evidence_materializer.py -q
uv run pytest -q
git diff --check
```

**Step 5: Commit**

```bash
git add backend/local_evidence_analyst/materializer.py tests/test_local_evidence_materializer.py
git commit -m "feat: Gate 기반 local VLM 입력 materializer 추가"
```

---

### Task 5: one-shot segmented benchmark runner 구현

**Files:**
- Create: `/Users/baek/petcam-rba-worker/scripts/run_local_evidence_benchmark.py`
- Create: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/runner.py`
- Test: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_runner.py`

**Step 1: Write failing orchestration tests**

Cover host mismatch, dirty/wrong HEAD, model revision mismatch, lock contention, lock order VLM→activity, deadline<10m, critical memory pressure, input failure, schema failure without retry, clip isolation, resume skips successful identity, failed identity remains terminal, fsync JSONL, signal cleanup, Gate unload before MLX load, worker exit drift abort.

**Step 2: Run RED**

```bash
uv run pytest tests/test_local_evidence_runner.py -q
```

**Step 3: Implement runner**

- exact host: `baeg-endeuui-Macmini.local`
- absolute uv path in runbook
- acquire `/tmp/petcam-vlm-candidate-worker.lock`, then `/tmp/petcam-activity-worker.lock`, both nonblocking
- materialize a bounded segment with Gate, release Gate/MLX cache, then load model once for that segment
- process one clip at a time
- store raw JSONL locally with stable durable key and `fsync`
- never call Slack or Supabase mutation endpoints
- stop before next scheduled worker safety boundary

**Step 4: Run GREEN**

```bash
uv run pytest tests/test_local_evidence_runner.py -q
uv run pytest -q
git diff --check
```

**Step 5: Commit**

```bash
git add backend/local_evidence_analyst/runner.py scripts/run_local_evidence_benchmark.py tests/test_local_evidence_runner.py
git commit -m "feat: local evidence one-shot benchmark runner 추가"
```

---

### Task 6: scorer·95% CI·독립 재계산 구현

**Files:**
- Create: `/Users/baek/petcam-lab/scripts/score_local_vlm_evidence.py`
- Create: `/Users/baek/petcam-lab/scripts/recompute_local_vlm_evidence.py`
- Test: `/Users/baek/petcam-lab/tests/test_score_local_vlm_evidence.py`

**Step 1: Write failing metric tests**

Cover confusion matrices, macro/weighted F1, present recall, object top-k recall, abstain rate, 30-clip consistency, Wilson/bootstrap seeded CI, missing/duplicate/unexpected keys, verdict priority.

**Step 2: Run RED**

```bash
cd /Users/baek/petcam-lab
uv run pytest tests/test_score_local_vlm_evidence.py -q
```

**Step 3: Implement scorer and independent recompute**

The independent script must not import scorer/runner modules. Both emit canonical JSON; hashes and every count/metric must agree. Exact verdict priority comes from TEST-SHEET §11.

**Step 4: Run GREEN**

```bash
uv run pytest tests/test_score_local_vlm_evidence.py -q
uv run pytest -q
git diff --check
```

**Step 5: Commit**

```bash
git add scripts/score_local_vlm_evidence.py scripts/recompute_local_vlm_evidence.py tests/test_score_local_vlm_evidence.py
git commit -m "feat: local evidence 품질 scorer와 독립 검산 추가"
```

---

### Task 7: data availability preflight와 PRE_REGISTERED gate

**Files:**
- Create: `/Users/baek/petcam-lab/experiments/local-vlm-evidence-analyst/manifest.json`
- Create outside Git: `/Users/baek/petcam-lab/storage/local-vlm-evidence-analyst/human-evidence-gt.json`
- Modify: `/Users/baek/petcam-lab/experiments/local-vlm-evidence-analyst/TEST-SHEET.md`

**Step 1: Build candidate manifest with SELECT-only queries**

Use camera/date/behavior metadata only for candidate construction. Apply 30-minute episode dedup before filling strata. Never use local model output.

**Step 2: Validate availability**

```bash
cd /Users/baek/petcam-lab
uv run python scripts/validate_local_vlm_evidence_manifest.py \
  --manifest experiments/local-vlm-evidence-analyst/manifest.json \
  --gt storage/local-vlm-evidence-analyst/human-evidence-gt.json
```

If any stratum, camera/date diversity, or GT completeness fails, write `BLOCKED_DATA_INSUFFICIENT` evidence and stop. Do not substitute clips.

**Step 3: Owner blind GT review**

Complete 180 evidence GT rows before any measured model output is visible. Hash manifest/GT and change TEST-SHEET state from `DRAFT_PLAN_REVIEW` to `PRE_REGISTERED` only after owner approval.

**Step 4: Commit tracked artifacts only**

```bash
git add experiments/local-vlm-evidence-analyst/TEST-SHEET.md experiments/local-vlm-evidence-analyst/manifest.json
git commit -m "test: local VLM evidence 시험지와 표본 사전등록"
```

Do not commit human GT if it contains private operational metadata; record only SHA-256 in tracked manifest.

---

### Task 8: cross-repo review·push·handoff manifest

**Files:**
- Create: `/Users/baek/petcam-lab/docs/handoff-prompts/2026-07-21-mac-mini-local-vlm-evidence-analyst-runtime-handoff.md`

**Step 1: Full verification**

```bash
cd /Users/baek/petcam-lab && uv run pytest -q && git diff --check
cd /Users/baek/petcam-rba-worker && uv run pytest -q && git diff --check
```

Run static audit for production writes, Slack, LaunchAgent changes, raw secret/media paths, and Qwen references in runtime code.

**Step 2: Request independent code review**

Review parser strictness, generation retry multiplication, lock order, Gate/MLX memory overlap, temp cleanup, resume identity, write boundaries, and metric leakage. Fix only evidenced findings and rerun tests.

**Step 3: Push clean branches**

Push petcam-lab and petcam-rba-worker feature branches. gecko-vision-gate remains unchanged but its exact 40-char HEAD and checkpoint SHA are recorded.

**Step 4: Create and validate manifest**

Manifest front matter must include execution repo, absolute plan/design path, all 40-char SHAs, `implementation_host`, `runtime_host`, `runtime_kind=oneshot`, and `runtime_label=none`.

```bash
cd /Users/baek/petcam-lab
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/petcam-lab/docs/handoff-prompts/2026-07-21-mac-mini-local-vlm-evidence-analyst-runtime-handoff.md
```

Do not proceed without literal `HANDOFF_OK` on Mac mini.

---

### Task 9: Mac mini runtime install·smoke — separate owner approval gate

**Files:**
- No tracked code changes expected.
- Gitignored runtime evidence: `/Users/baek-end/petcam-rba-worker/storage/local-vlm-evidence-analyst/`

**Step 1: Re-run read-only preflight**

Verify hostname, 3 repo HEADs, disk≥20GiB, memory pressure, swap, LaunchAgents, locks, worker exit baselines, and absolute uv path.

**Step 2: Owner approval for install/download**

Only after explicit approval:

```bash
cd /Users/baek-end/petcam-rba-worker
/Users/baek-end/.local/bin/uv sync --group local-evidence-benchmark
```

Download the pinned SmolVLM2 snapshot, verify revision and actual bytes, then set offline mode for measured runs.

**Step 3: Synthetic smoke**

Run one non-evaluation clip. Require model load, six images, strict JSON, temp 0, no DB/R2 write, worker exit drift 0. Smoke failure blocks measured run.

---

### Task 10: segmented development·holdout execution

**Step 1: Development 120**

Run bounded segments. After each segment verify raw record count/hash, temp 0, RSS/swap, locks released, scheduled worker exit/deadline unchanged.

Only schema/pipeline defects may be fixed. Any quality-driven prompt change requires deleting development results, new prompt version, and rerunning all 120.

**Step 2: Freeze execution configuration**

Commit exact model revision, prompt, schema, sampler, resize, Gate SHA/checkpoint, runtime lockfile, and development report. No holdout result has been read yet.

**Step 3: Fresh holdout 60 + repeat extra 60**

Run all 120 measured keys once under the frozen configuration. Do not retry content/schema failures.

**Step 4: Immediate safety closure**

Confirm expected 240 total keys, temp 0, worker errors/delay 0, DB/R2 write 0, raw artifact hash.

---

### Task 11: report·verdict·SOT closure

**Files:**
- Create: `/Users/baek/petcam-lab/experiments/local-vlm-evidence-analyst/REPORT.md`
- Create: `/Users/baek/petcam-lab/experiments/local-vlm-evidence-analyst/summary.json`
- Modify: `/Users/baek/petcam-lab/specs/next-session.md`
- Modify: `/Users/baek/petcam-lab/docs/decision-gate.md`

**Step 1: Score and independently recompute**

Run both scripts. Any count/hash/metric mismatch yields `REJECT_INTEGRITY` before quality interpretation.

**Step 2: Fill report template**

No blank evidence fields. Include point+95% CI, strata tables, repeat failures, resource graphs/tables, error links using short IDs and label web URLs only.

**Step 3: Select exactly one verdict**

Apply TEST-SHEET priority without post-hoc threshold changes. `PASS_LOCAL_EVIDENCE_ANALYST` still means production connection is prohibited.

**Step 4: Additive SOT update and commit**

Append result to decision-gate and next-session. Preserve failed hypotheses and raw results outside Git.

```bash
git add experiments/local-vlm-evidence-analyst/REPORT.md experiments/local-vlm-evidence-analyst/summary.json specs/next-session.md docs/decision-gate.md
git commit -m "docs: local VLM evidence 벤치마크 결과 기록"
```

## Final stop point

Stop after report push. Do not create a LaunchAgent, production consumer, selector hook, automatic exclusion, or Claude prompt integration. A PASS only unlocks a new paired control-vs-treatment TEST-SHEET through a fresh decision gate.
