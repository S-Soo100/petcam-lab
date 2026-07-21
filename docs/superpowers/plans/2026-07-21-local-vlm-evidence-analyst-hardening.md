# Local VLM Evidence Analyst Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 local VLM benchmark 골격을 실제 Universal Python Evidence 입력, fail-closed runtime identity, 필수 자원 계측, 올바른 품질 scorer를 가진 dry-verified 구현으로 하드닝한다.

**Architecture:** `petcam-rba-worker`가 versioned evidence JSONL을 strict하게 읽어 canonical payload와 SHA-256을 만들고, 이를 6프레임과 함께 prompt·raw ledger에 연결한다. `petcam-lab` scorer는 필수 runtime artifact와 사람 GT를 입력받아 지표·CI·coverage·resource gate를 재계산하며, 별도 recompute가 공유 helper 없이 canonical 결과를 검산한다. 이번 계획은 Work Package A만 수행하고 production SELECT 후보 생성과 사람 GT는 후속 Work Package B로 남긴다.

**Tech Stack:** Python 3.12, uv, pytest, Supabase artifact schema(읽기 계약만), Pillow, MLX-VLM 0.6.5 package API, JSONL, psutil 또는 macOS 표준 명령 기반 계측

## Global Constraints

- 기준 설계: `/Users/baek/petcam-lab/docs/superpowers/specs/2026-07-21-local-vlm-evidence-analyst-hardening-design.md`
- 시작 브랜치: 양쪽 모두 `feat/local-vlm-evidence-analyst`; lab base는 설계 commit을 포함한 HEAD, rba base는 `72898c64519b806162e25cd1d77a27f53dcb5e7f`.
- Work Package A만 구현한다. Work Package B 후보 selector, 사람 GT, manifest 180개 구성은 시작하지 않는다.
- production DB/R2 write, migration, Slack, LaunchAgent, selector, cloud VLM, app activity, 행동 GT 변경은 금지한다.
- SmolVLM2 snapshot 다운로드와 실제 inference는 금지한다. `mlx-vlm==0.6.5` package metadata lock·package import·signature inspection은 허용한다.
- raw media와 inference artifact는 commit하지 않는다.
- 필수 identity·runtime metric·평가 표본이 하나라도 없으면 PASS가 아니라 stable failure code여야 한다.
- `Gate threshold`는 CLI 필수값이며 기존 코드의 `0.5` 기본값 사용을 금지한다. threshold를 새로 채택하거나 튜닝하지 않는다.
- 각 task는 RED 확인 → 최소 구현 → 해당 test GREEN → 전체 관련 test → 커밋 순서로 끝낸다.
- 두 레포 feature branch만 push한다. main merge·Mac mini 실행은 금지한다.

---

## File Structure

### `petcam-rba-worker`

- Create `backend/local_evidence_analyst/evidence.py` — evidence row 검증·deterministic selection·canonical JSON·hash.
- Create `backend/local_evidence_analyst/runtime_identity.py` — repo/snapshot/checkpoint/runtime pin fail-closed 검증.
- Create `backend/local_evidence_analyst/runtime_metrics.py` — latency/RSS/swap/temp/deadline 계측과 runtime artifact.
- Modify `backend/local_evidence_analyst/prompt.py` — canonical evidence payload와 frame context만 받는 bounded prompt.
- Modify `backend/local_evidence_analyst/runner.py` — evidence 선택, ledger integrity, timing, resource provenance 연결.
- Modify `backend/local_evidence_analyst/mlx_adapter.py` — 실제 0.6.5 API 계약과 load/generate timing 결과.
- Modify `scripts/run_local_evidence_benchmark.py` — required CLI pins, evidence JSONL loader, fail-closed self-check, runtime artifact 출력.
- Create `tests/test_local_evidence_evidence.py`.
- Create `tests/test_local_evidence_runtime_identity.py`.
- Create `tests/test_local_evidence_runtime_metrics.py`.
- Modify `tests/test_local_evidence_runner.py`.
- Modify `tests/test_local_evidence_mlx_adapter.py`.
- Create `tests/test_local_evidence_runbook.py`.
- Modify `pyproject.toml`, `uv.lock` — `mlx-vlm==0.6.5` optional/dependency group lock.

### `petcam-lab`

- Modify `scripts/score_local_vlm_evidence.py` — 올바른 bootstrap CI, coverage breakdown, 필수 runtime gate.
- Modify `scripts/recompute_local_vlm_evidence.py` — scorer helper를 공유하지 않는 독립 검산 확장.
- Modify `tests/test_score_local_vlm_evidence.py`.
- Create `tests/fixtures/local_vlm_evidence_hardened/` — media 없는 합성 manifest/GT/results/runtime fixture.
- Create `docs/handoff-prompts/2026-07-21-local-vlm-evidence-hardening-report.md` — Claude 완료 보고서.
- Modify `docs/handoff-prompts/2026-07-21-mac-mini-local-vlm-evidence-analyst-implementation-report.md` — 기존 판정이 이 하드닝 결과로 superseded됨을 additive하게 표시.

---

### Task 1: Universal Python Evidence strict contract

**Files:**
- Create: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/evidence.py`
- Create: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_evidence.py`

**Interfaces:**
- Consumes: `clip_python_evidence_runs`에서 export한 JSON object 목록.
- Produces:
  - `EvidenceContractError(code: str)`
  - `EvidenceSelection(source_run_id: str, payload: dict, canonical_json: str, sha256: str)`
  - `select_evidence(rows: list[dict], *, clip_id: str, schema_version: str, algorithm_version: str) -> EvidenceSelection`
  - `MAX_EVIDENCE_BYTES = 32768`

- [ ] **Step 1: Write failing contract tests**

```python
def test_selects_one_exact_version_and_hashes_canonical_json():
    row = _row(clip_id="c1", run_id="r1")
    selected = select_evidence(
        [row], clip_id="c1",
        schema_version="python-evidence-raw-v1",
        algorithm_version="croi-temporal-v1",
    )
    assert selected.source_run_id == "r1"
    assert selected.payload["motion_summary"] == row["motion_summary"]
    assert len(selected.sha256) == 64
    assert selected.sha256 == hashlib.sha256(selected.canonical_json.encode()).hexdigest()

@pytest.mark.parametrize("rows,code", [([], "INPUT_EVIDENCE_MISSING"), ([_row(), _row(run_id="r2")], "INPUT_EVIDENCE_AMBIGUOUS")])
def test_missing_or_ambiguous_fails(rows, code):
    with pytest.raises(EvidenceContractError) as exc:
        select_evidence(rows, clip_id="c1", schema_version="python-evidence-raw-v1", algorithm_version="croi-temporal-v1")
    assert exc.value.code == code

def test_rejects_over_cap_series_and_nonfinite_numbers():
    row = _row(global_motion_series=[{"t": i, "v": 1.0} for i in range(257)])
    with pytest.raises(EvidenceContractError, match="INPUT_EVIDENCE_INVALID"):
        select_evidence([row], clip_id="c1", schema_version="python-evidence-raw-v1", algorithm_version="croi-temporal-v1")
```

필수 추가 case: cross-clip, wrong version, missing run id, non-object summary, non-array series, payload >32KiB, canonical key order/hash 안정성.

- [ ] **Step 2: Run RED test**

Run:

```bash
cd /Users/baek/petcam-rba-worker
uv run pytest tests/test_local_evidence_evidence.py -q
```

Expected: FAIL because `backend.local_evidence_analyst.evidence` does not exist.

- [ ] **Step 3: Implement the strict allowlist**

Canonical payload는 다음 키만 포함한다.

```python
EVIDENCE_KEYS = (
    "evidence_schema_version", "algorithm_version", "model_name", "model_version",
    "checkpoint_sha256", "threshold", "sampler_version", "schema_version",
    "frames_sampled", "level0_status", "level1_status", "decoded_frame_count",
    "point_stride", "metadata", "motion_summary", "global_motion_series",
    "roi_motion_series", "spatial_dwell", "periodicity_summary",
    "motion_excursions", "source_prelabel_identity",
)

@dataclass(frozen=True, slots=True)
class EvidenceSelection:
    source_run_id: str
    payload: dict[str, Any]
    canonical_json: str
    sha256: str
```

JSON은 `sort_keys=True, separators=(",", ":"), allow_nan=False`로 직렬화한다. 배열 point cap은 256, object/array 타입과 numeric finite를 재귀 검증한다.

- [ ] **Step 4: Run GREEN test and the existing schema tests**

```bash
cd /Users/baek/petcam-rba-worker
uv run pytest tests/test_local_evidence_evidence.py tests/test_local_evidence_schema.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/local_evidence_analyst/evidence.py tests/test_local_evidence_evidence.py
git commit -m "feat: local VLM Python Evidence 입력 계약 추가"
```

---

### Task 2: Evidence artifact loader and prompt/runner wiring

**Files:**
- Modify: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/prompt.py`
- Modify: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/runner.py`
- Modify: `/Users/baek/petcam-rba-worker/scripts/run_local_evidence_benchmark.py`
- Modify: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_runner.py`
- Create: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_runbook.py`

**Interfaces:**
- Consumes: Task 1 `EvidenceSelection`.
- Produces:
  - `load_evidence_rows(path: Path) -> dict[str, list[dict]]`
  - `RunnerDeps.evidence_for: Callable[[str], EvidenceSelection]`
  - `prompt_for(clip, materialized, evidence: EvidenceSelection) -> str`
  - raw record fields `evidence_source_run_id`, `evidence_sha256`, `evidence_schema_version`, `evidence_algorithm_version`.

- [ ] **Step 1: Add failing runner and loader tests**

```python
def test_runner_passes_canonical_evidence_to_prompt_and_ledger(tmp_path):
    deps = _deps(tmp_path, evidence_for=lambda _: _selection(sha256="a" * 64))
    keys = _keys(("c1", 0))
    _fill_lookup(deps, keys)
    run_benchmark(keys, deps)
    rec = json.loads(deps.jsonl_path.read_text().splitlines()[0])
    assert rec["evidence_source_run_id"] == "run-c1"
    assert rec["evidence_sha256"] == "a" * 64
    assert deps.adapter.last_prompt_evidence_sha == "a" * 64

def test_missing_evidence_is_terminal_input_failure_without_generation(tmp_path):
    def missing(_):
        raise EvidenceContractError("INPUT_EVIDENCE_MISSING")
    deps = _deps(tmp_path, evidence_for=missing)
    # run and assert status/input failure code; adapter.generate_calls == []
```

Loader tests must reject malformed JSONL, missing `clip_id`, and more than one raw object with the same `id`.

- [ ] **Step 2: Run RED tests**

```bash
cd /Users/baek/petcam-rba-worker
uv run pytest tests/test_local_evidence_runner.py tests/test_local_evidence_runbook.py -q
```

Expected: new tests fail because evidence is not a runner dependency and the CLI has no evidence artifact.

- [ ] **Step 3: Wire evidence into prompt and provenance**

Change the prompt boundary to:

```python
def build_prompt(evidence_json: dict, *, frame_context: dict) -> str:
    canonical = json.dumps(evidence_json, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    context = json.dumps(frame_context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # Existing rules/schema remain; include both canonical evidence and frame context.
```

Runner sequence per key:

```python
selection = deps.evidence_for(key["clip_id"])
prompt = deps.prompt_for(deps.clip_lookup[dk], mat, selection)
rec["evidence_source_run_id"] = selection.source_run_id
rec["evidence_sha256"] = selection.sha256
```

`--evidence-jsonl` is required for normal run and self-check. The file contains exported `clip_python_evidence_runs` rows; the CLI groups rows by `clip_id` and Task 1 selects the exact frozen version.

- [ ] **Step 4: Close PIL images deterministically**

Replace the current open-image list with detached copies:

```python
def _load_images(mat):
    from PIL import Image
    images = []
    for path in mat.image_paths:
        with Image.open(path) as src:
            images.append(src.convert("RGB").copy())
    return images
```

Runner must call `close()` on each image in `finally` after generation.

- [ ] **Step 5: Run GREEN tests**

```bash
cd /Users/baek/petcam-rba-worker
uv run pytest tests/test_local_evidence_evidence.py tests/test_local_evidence_runner.py tests/test_local_evidence_runbook.py tests/test_local_evidence_schema.py -q
```

Expected: all pass; prompt contains motion series/dwell/periodicity fixture values and raw ledger has evidence SHA.

- [ ] **Step 6: Commit**

```bash
git add backend/local_evidence_analyst/prompt.py backend/local_evidence_analyst/runner.py scripts/run_local_evidence_benchmark.py tests/test_local_evidence_runner.py tests/test_local_evidence_runbook.py
git commit -m "feat: local VLM에 Universal Python Evidence 연결"
```

---

### Task 3: Required runtime identity and snapshot verification

**Files:**
- Create: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/runtime_identity.py`
- Create: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_runtime_identity.py`
- Modify: `/Users/baek/petcam-rba-worker/scripts/run_local_evidence_benchmark.py`
- Modify: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_runbook.py`

**Interfaces:**
- Produces:
  - `RuntimeIdentityError(code: str)`
  - `RepoIdentity(head: str, clean: bool)`
  - `SnapshotIdentity(repo: str, revision: str, path: str, required_files_sha256: str)`
  - `verify_repo(path: Path, expected_head: str) -> RepoIdentity`
  - `verify_snapshot(path: Path, *, expected_repo: str, expected_revision: str) -> SnapshotIdentity`
  - `sha256_file(path: Path) -> str`

- [ ] **Step 1: Write fail-closed RED tests**

```python
@pytest.mark.parametrize("flag", ["--lab-head", "--rba-head", "--gate-head", "--snapshot-dir", "--gate-checkpoint", "--gate-threshold"])
def test_required_runtime_flag_cannot_be_omitted(flag):
    argv = _complete_self_check_argv()
    value_index = argv.index(flag) + 1
    del argv[value_index]
    del argv[argv.index(flag)]
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)

def test_git_command_failure_is_not_clean_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: CompletedProcess(a, 128, "", "fatal"))
    with pytest.raises(RuntimeIdentityError, match="REPO_QUERY_FAILED"):
        verify_repo(tmp_path, "a" * 40)

def test_snapshot_directory_name_alone_is_not_proof(tmp_path):
    snap = tmp_path / ("a" * 40)
    snap.mkdir()
    with pytest.raises(RuntimeIdentityError, match="SNAPSHOT_INCOMPLETE"):
        verify_snapshot(snap, expected_repo=MODEL_REPO, expected_revision="a" * 40)
```

Additional RED cases: non-40-hex head, dirty repo, missing checkpoint, checkpoint hash mismatch, threshold absent/out of `(0,1]`, missing model config/weight index, revision mismatch, evidence artifact missing.

- [ ] **Step 2: Run RED tests**

```bash
cd /Users/baek/petcam-rba-worker
uv run pytest tests/test_local_evidence_runtime_identity.py tests/test_local_evidence_runbook.py -q
```

- [ ] **Step 3: Implement identity verification**

Required CLI additions:

```python
p.add_argument("--snapshot-dir", type=Path, required=True)
p.add_argument("--lab-head", required=True, type=_sha40)
p.add_argument("--rba-head", required=True, type=_sha40)
p.add_argument("--gate-head", required=True, type=_sha40)
p.add_argument("--model-repo", required=True)
p.add_argument("--model-revision", required=True, type=_sha40)
p.add_argument("--mlx-vlm-version", required=True)
p.add_argument("--gate-checkpoint", type=Path, required=True)
p.add_argument("--gate-checkpoint-sha256", required=True, type=_sha256)
p.add_argument("--gate-threshold", required=True, type=_threshold)
p.add_argument("--evidence-schema-version", required=True)
p.add_argument("--evidence-algorithm-version", required=True)
```

`--self-check`도 같은 required identity를 검사하며 model import·R2·Gate inference는 하지 않는다. expected value를 actual value로 자동 대체하는 `or repo_states[...]`와 snapshot 상수 fallback을 삭제한다.

- [ ] **Step 4: Run GREEN tests**

```bash
cd /Users/baek/petcam-rba-worker
uv run pytest tests/test_local_evidence_runtime_identity.py tests/test_local_evidence_runbook.py tests/test_local_evidence_runner.py -q
```

- [ ] **Step 5: Commit**

```bash
git add backend/local_evidence_analyst/runtime_identity.py scripts/run_local_evidence_benchmark.py tests/test_local_evidence_runtime_identity.py tests/test_local_evidence_runbook.py
git commit -m "fix: local VLM runtime identity를 fail-closed로 검증"
```

---

### Task 4: Raw ledger integrity and mandatory runtime metrics

**Files:**
- Create: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/runtime_metrics.py`
- Create: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_runtime_metrics.py`
- Modify: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/runner.py`
- Modify: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/mlx_adapter.py`
- Modify: `/Users/baek/petcam-rba-worker/scripts/run_local_evidence_benchmark.py`
- Modify: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_runner.py`
- Modify: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_mlx_adapter.py`

**Interfaces:**
- Produces:
  - `LedgerIntegrityError(code: str)`
  - `RuntimeMeasurementError(code: str)`
  - `RuntimeMetricsMonitor.start_run()/start_phase()/end_phase()/finish_run()`
  - runtime JSON fields: `model_load_ms`, `materialize_ms`, `generation_ms`, `e2e_ms`, `peak_rss_bytes`, `mlx_peak_bytes`, `swap_start_bytes`, `swap_end_bytes`, `swap_delta_bytes`, `temp_peak_bytes`, `temp_residual_count`, `worker_exit_delta`, `deadline_delay_sec`, `sustained_clips_per_hour`, `projected_four_camera_p95`.

- [ ] **Step 1: Write RED tests for corrupted ledger**

```python
def test_malformed_jsonl_aborts_instead_of_skipping(tmp_path):
    path = tmp_path / "raw.jsonl"
    path.write_text('{"measured_key":"a"}\n{broken\n')
    with pytest.raises(LedgerIntegrityError, match="RAW_LEDGER_MALFORMED"):
        load_completed_records(path)

def test_conflicting_duplicate_identity_aborts(tmp_path):
    # same measured_key, different evidence_sha256/status must raise RAW_LEDGER_CONFLICT
```

- [ ] **Step 2: Write RED tests for missing metrics**

```python
def test_runtime_metrics_missing_command_is_fail_closed(monkeypatch):
    monitor = RuntimeMetricsMonitor(...)
    monkeypatch.setattr(monitor, "_read_swap_bytes", lambda: (_ for _ in ()).throw(OSError()))
    with pytest.raises(RuntimeMeasurementError, match="RESOURCE_EVIDENCE_MISSING"):
        monitor.start_run()

def test_generation_record_has_all_phase_latencies(tmp_path):
    # fake monotonic_ns values; assert materialize_ms/model_load_ms/generation_ms/e2e_ms are non-null
```

Also test memory-pressure/launchctl command nonzero as fail-closed, temp peak/residual, worker exit drift, capacity formula, and missing MLX peak marked missing rather than silently accepted.

- [ ] **Step 3: Run RED tests**

```bash
cd /Users/baek/petcam-rba-worker
uv run pytest tests/test_local_evidence_runtime_metrics.py tests/test_local_evidence_runner.py tests/test_local_evidence_mlx_adapter.py -q
```

- [ ] **Step 4: Implement strict ledger loading**

Replace `_load_completed` with:

```python
def load_completed_records(path: Path) -> dict[str, dict]:
    records = {}
    for line_no, raw in enumerate(path.read_text().splitlines(), 1):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LedgerIntegrityError("RAW_LEDGER_MALFORMED") from exc
        key = rec.get("measured_key")
        if not isinstance(key, str) or not key:
            raise LedgerIntegrityError("RAW_LEDGER_IDENTITY_MISSING")
        if key in records:
            raise LedgerIntegrityError("RAW_LEDGER_DUPLICATE")
        records[key] = rec
    return records
```

- [ ] **Step 5: Implement metrics artifact and runner instrumentation**

Use `time.monotonic_ns()` for phase latency, `resource.getrusage` or `psutil` for RSS, `sysctl vm.swapusage` for swap, recursive file sizes for temp peak, and the existing LaunchAgent snapshot for worker drift. All subprocess return codes must be checked.

`GenerationResult` becomes:

```python
@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    peak_memory_bytes: int | None
    output_token_count: int | None
    generation_ms: float
```

Runner writes per-record phase metrics and `--runtime-out` writes one run summary atomically using temp file + `os.replace` + fsync.

- [ ] **Step 6: Run GREEN tests**

```bash
cd /Users/baek/petcam-rba-worker
uv run pytest tests/test_local_evidence_runtime_metrics.py tests/test_local_evidence_runner.py tests/test_local_evidence_mlx_adapter.py tests/test_local_evidence_runbook.py -q
```

- [ ] **Step 7: Commit**

```bash
git add backend/local_evidence_analyst/runtime_metrics.py backend/local_evidence_analyst/runner.py backend/local_evidence_analyst/mlx_adapter.py scripts/run_local_evidence_benchmark.py tests/test_local_evidence_runtime_metrics.py tests/test_local_evidence_runner.py tests/test_local_evidence_mlx_adapter.py tests/test_local_evidence_runbook.py
git commit -m "feat: local VLM ledger 무결성과 자원 계측 강화"
```

---

### Task 5: Scorer math, coverage, and resource gate

**Files:**
- Modify: `/Users/baek/petcam-lab/scripts/score_local_vlm_evidence.py`
- Modify: `/Users/baek/petcam-lab/scripts/recompute_local_vlm_evidence.py`
- Modify: `/Users/baek/petcam-lab/tests/test_score_local_vlm_evidence.py`

**Interfaces:**
- CLI adds required `--runtime PATH`.
- `bootstrap_metric_ci(pairs, metric_fn, *, seed, n_boot=2000) -> tuple[float, float]`.
- `MIN_OBJECT_POSITIVE = 10`.
- summary adds `coverage`, `by_strata`, `by_roi_mode`, `runtime`, and CI for all primary metrics.

- [ ] **Step 1: Write RED metric tests**

```python
def test_presence_ci_bootstraps_macro_f1_not_exact_accuracy():
    pairs = [("present", "present"), ("present", "absent"), ("absent", "absent"), ("uncertain", "absent")]
    point = macro_f1(pairs)
    ci = bootstrap_metric_ci(pairs, macro_f1, seed=7, n_boot=500)
    assert ci[0] <= point <= ci[1]
    assert ci != bootstrap_metric_ci(pairs, lambda xs: sum(g == p for g, p in xs) / len(xs), seed=7, n_boot=500)

def test_zero_object_positive_cannot_pass_quality():
    results, gt, manifest = _dataset_without_object_positive()
    scored = score(results, gt, manifest, runtime=_valid_runtime())
    assert scored["coverage"]["object_positive"] == 0
    assert scored["gates"]["quality"] is False
    assert scored["verdict"] == "REJECT_QUALITY"

def test_runtime_is_mandatory_and_missing_field_rejects_resource():
    with pytest.raises(ValueError, match="RESOURCE_EVIDENCE_MISSING"):
        score(*_dataset(), runtime=None)
```

Add tests for visibility/motion CI, `MIN_OBJECT_POSITIVE=10`, strata and ROI counts, missing strata, missing runtime key, thresholds, temp residue, RSS/swap/capacity/deadline/worker exit.

- [ ] **Step 2: Run RED tests**

```bash
cd /Users/baek/petcam-lab
uv run pytest tests/test_score_local_vlm_evidence.py -q
```

- [ ] **Step 3: Implement metric-correct bootstrap and resource recomputation**

```python
RESOURCE_FIELDS = (
    "peak_rss_bytes", "swap_delta_bytes", "temp_residual_count",
    "worker_exit_delta", "deadline_delay_sec", "sustained_clips_per_hour",
    "projected_four_camera_p95",
)

def resource_gate(runtime: dict) -> bool:
    missing = [k for k in RESOURCE_FIELDS if runtime.get(k) is None]
    if missing:
        raise ValueError(f"RESOURCE_EVIDENCE_MISSING:{','.join(missing)}")
    return (
        runtime["peak_rss_bytes"] <= 8 * 1024**3
        and runtime["swap_delta_bytes"] <= 1 * 1024**3
        and runtime["temp_residual_count"] == 0
        and runtime["worker_exit_delta"] == 0
        and runtime["deadline_delay_sec"] == 0
        and runtime["sustained_clips_per_hour"] >= 2 * runtime["projected_four_camera_p95"]
    )
```

`object_topk is None`을 성공으로 처리하는 조건을 제거한다. confusion에 visibility를 추가한다. strata·ROI breakdown은 표본 수, 성공 수, abstain, presence/motion/visibility 점수를 포함한다.

- [ ] **Step 4: Make independent recompute genuinely independent**

`recompute_local_vlm_evidence.py`에서 `build_measured_keys` import를 제거하고 manifest 규칙을 별도로 구현한다. runtime gate와 primary metric/CI를 별도 코드로 계산해 scorer canonical과 비교한다. scorer와 상수·metric helper를 import하지 않는다.

- [ ] **Step 5: Run GREEN tests**

```bash
cd /Users/baek/petcam-lab
uv run pytest tests/test_score_local_vlm_evidence.py tests/test_validate_local_vlm_evidence_manifest.py -q
```

- [ ] **Step 6: Commit**

```bash
git add scripts/score_local_vlm_evidence.py scripts/recompute_local_vlm_evidence.py tests/test_score_local_vlm_evidence.py
git commit -m "fix: local VLM 품질·자원 게이트를 fail-closed로 계산"
```

---

### Task 6: Reproducible MLX-VLM package contract

**Files:**
- Modify: `/Users/baek/petcam-rba-worker/pyproject.toml`
- Modify: `/Users/baek/petcam-rba-worker/uv.lock`
- Modify: `/Users/baek/petcam-rba-worker/backend/local_evidence_analyst/mlx_adapter.py`
- Modify: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_mlx_adapter.py`
- Create: `/Users/baek/petcam-rba-worker/tests/test_local_evidence_mlx_runtime_contract.py`

**Interfaces:**
- Produces dependency group `local-evidence-benchmark` pinned to `mlx-vlm==0.6.5`.
- `verify_mlx_runtime_contract() -> dict[str, str]` returns installed version and inspected API names without loading a model.

- [ ] **Step 1: Add dependency metadata without downloading a model snapshot**

```bash
cd /Users/baek/petcam-rba-worker
uv add --group local-evidence-benchmark "mlx-vlm==0.6.5"
```

Expected: `pyproject.toml` and `uv.lock` change; no Hugging Face snapshot path is created by this command.

- [ ] **Step 2: Write a RED real-package contract test**

```python
@pytest.mark.mlx_contract
def test_installed_mlx_vlm_065_exposes_adapter_calls():
    import importlib.metadata
    import inspect
    import mlx_vlm
    assert importlib.metadata.version("mlx-vlm") == "0.6.5"
    assert "revision" in inspect.signature(mlx_vlm.load).parameters
    assert "max_tokens" in inspect.signature(mlx_vlm.generate).parameters
```

The test must not call `load()` or `generate()` and must not access a model repository.

- [ ] **Step 3: Run the contract test and inspect the real signatures**

```bash
cd /Users/baek/petcam-rba-worker
uv run --group local-evidence-benchmark pytest tests/test_local_evidence_mlx_runtime_contract.py -q
```

Expected: RED if the current adapter assumptions do not match 0.6.5. Record actual signatures in the test failure output; do not guess.

- [ ] **Step 4: Adapt only to the verified 0.6.5 API**

Update `MlxEvidenceAdapter.load`, `_format_prompt`, and `generate` to match inspected parameter names. Keep fake tests, then add tests that bind arguments with `inspect.signature(...).bind_partial(...)` without model loading.

- [ ] **Step 5: Run GREEN tests**

```bash
cd /Users/baek/petcam-rba-worker
uv run --group local-evidence-benchmark pytest tests/test_local_evidence_mlx_adapter.py tests/test_local_evidence_mlx_runtime_contract.py -q
uv lock --check
```

Expected: all pass; no model snapshot download and no inference.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock backend/local_evidence_analyst/mlx_adapter.py tests/test_local_evidence_mlx_adapter.py tests/test_local_evidence_mlx_runtime_contract.py
git commit -m "build: MLX-VLM 0.6.5 실행 계약 고정"
```

---

### Task 7: Cross-repo dry end-to-end verification and closure report

**Files:**
- Create: `/Users/baek/petcam-lab/tests/fixtures/local_vlm_evidence_hardened/manifest.json`
- Create: `/Users/baek/petcam-lab/tests/fixtures/local_vlm_evidence_hardened/gt.json`
- Create: `/Users/baek/petcam-lab/tests/fixtures/local_vlm_evidence_hardened/results.jsonl`
- Create: `/Users/baek/petcam-lab/tests/fixtures/local_vlm_evidence_hardened/runtime.json`
- Modify: `/Users/baek/petcam-lab/tests/test_score_local_vlm_evidence.py`
- Create: `/Users/baek/petcam-lab/docs/handoff-prompts/2026-07-21-local-vlm-evidence-hardening-report.md`
- Modify: `/Users/baek/petcam-lab/docs/handoff-prompts/2026-07-21-mac-mini-local-vlm-evidence-analyst-implementation-report.md`

**Interfaces:**
- Produces one exact verdict: `HARDENED_IMPLEMENTATION_READY_FOR_DATA_REVIEW` or `HARDENING_BLOCKED_<CODE>`.

- [ ] **Step 1: Add media-free end-to-end fixtures**

Fixtures must include all six strata, both ROI modes, at least 10 object-positive rows, valid runtime metrics, repeated keys, and evidence SHA fields. They contain no real clip URL, signed URL, secret, frame, or model output from production.

- [ ] **Step 2: Write the cross-boundary dry test**

```python
def test_hardened_fixture_scores_and_recomputes_identically():
    full = score(_results(), _gt(), _manifest(), runtime=_runtime(), recompute_match=True)
    independent = recompute(_results(), _gt(), _manifest(), _runtime())
    assert canonical_summary(full) == independent
    assert full["gates"]["resource"] is True
    assert set(full["by_strata"]) == set(_manifest()["strata"])
    assert set(full["by_roi_mode"]) == {"union_roi", "full_frame_no_detection"}
```

- [ ] **Step 3: Run both full suites**

```bash
cd /Users/baek/petcam-rba-worker
uv run --group local-evidence-benchmark pytest -q
cd /Users/baek/petcam-lab
uv run pytest -q
```

Expected: both pass. Any pre-existing failure must be reproduced on the base SHA before being classified as pre-existing.

- [ ] **Step 4: Run static safety audit**

```bash
git -C /Users/baek/petcam-rba-worker diff --check 72898c64519b806162e25cd1d77a27f53dcb5e7f..HEAD
git -C /Users/baek/petcam-lab diff --check 4feb44f9b03fb25a859fd78ec269cb2ee844661f..HEAD
rg -n "insert\(|update\(|upsert\(|delete\(|slack|launchctl bootstrap|snapshot_download|from_pretrained" \
  /Users/baek/petcam-rba-worker/backend/local_evidence_analyst \
  /Users/baek/petcam-rba-worker/scripts/run_local_evidence_benchmark.py \
  /Users/baek/petcam-lab/scripts/score_local_vlm_evidence.py \
  /Users/baek/petcam-lab/scripts/recompute_local_vlm_evidence.py
```

Review every hit. The implementation may read local artifacts and inspect packages but must contain no production mutation, model snapshot download, inference invocation in tests, Slack, or LaunchAgent change.

- [ ] **Step 5: Write the report and supersede the old verdict additively**

The report must include:

- exact branch and 40-char HEAD for both repos
- task commit list
- evidence fields actually reaching prompt and raw record fixture proof
- missing/ambiguous evidence failure proof
- required runtime flag failure proof
- resource metric completeness and missing-field rejection proof
- corrected F1/CI/object/strata/ROI results
- actual `mlx-vlm==0.6.5` package API inspection evidence
- model snapshot download/inference/DB write/Slack/LaunchAgent = 0
- full test counts and failures, if any
- exact remaining condition: Work Package B only

Do not rewrite historical content in the old implementation report. Add a top banner:

```markdown
> ⛔ SUPERSEDED on 2026-07-21: `IMPLEMENTATION_BLOCKED_DATA` was rejected by independent review.
> Current verdict is defined by `2026-07-21-local-vlm-evidence-hardening-report.md`.
```

- [ ] **Step 6: Commit report and fixtures**

```bash
cd /Users/baek/petcam-lab
git add tests/fixtures/local_vlm_evidence_hardened tests/test_score_local_vlm_evidence.py docs/handoff-prompts/2026-07-21-local-vlm-evidence-hardening-report.md docs/handoff-prompts/2026-07-21-mac-mini-local-vlm-evidence-analyst-implementation-report.md
git commit -m "docs: local VLM evidence 하드닝 검증 보고"
```

- [ ] **Step 7: Push only the two feature branches and stop**

```bash
git -C /Users/baek/petcam-rba-worker push origin feat/local-vlm-evidence-analyst
git -C /Users/baek/petcam-lab push origin feat/local-vlm-evidence-analyst
```

Confirm `local == origin`, preserve unrelated untracked files, and stop. Do not merge main, run Work Package B, install/download a model snapshot, or execute Mac mini inference.

---

## Final Review Checklist

- [ ] Every benchmark prompt contains the canonical Universal Python Evidence payload, not only durable key/ROI mode.
- [ ] Every raw result contains evidence source run id and evidence SHA-256.
- [ ] Evidence missing/ambiguous/invalid cannot call the adapter.
- [ ] Missing expected HEAD/snapshot/checkpoint/threshold cannot pass self-check.
- [ ] Git and macOS measurement command failures are fail-closed.
- [ ] Corrupt/duplicate JSONL cannot be silently skipped.
- [ ] Resource artifact is mandatory and scorer recomputes its gate.
- [ ] Presence/visibility/motion CIs bootstrap the actual metric.
- [ ] Object-positive coverage below 10 cannot pass.
- [ ] Six strata and both ROI modes appear in coverage breakdown.
- [ ] Independent recompute shares no scorer/expected-key helper.
- [ ] `mlx-vlm==0.6.5` is locked and its real API is inspected without model loading.
- [ ] Both full suites pass and no production write/model inference occurs.
- [ ] Final stop verdict is exactly `HARDENED_IMPLEMENTATION_READY_FOR_DATA_REVIEW` or a specific blocker.
