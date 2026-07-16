# Python Evidence S1 Throughput Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Python evidence 후보 구성 중 `sparse Gate 12-frame + bbox ROI dense OpenCV`가 Mac mini에서 projected 4-camera p95 유입량의 2배를 지속 처리할 수 있는지, production 데이터 변경 없이 재현 가능한 벤치마크로 판정한다.

**Architecture:** `petcam-lab`이 benchmark harness·사전등록·결과 artifact의 소유자다. Mac mini에서는 별도 worktree의 harness를 `petcam-nightly-reporter`의 `uv` 환경으로 수동 실행해 현재 production의 R2·Gate·6-frame 의존성을 그대로 재사용한다. 조건 A/B/C/D를 동일 clip manifest에 paired-run하고, 다운로드 포함·제외 비용과 run 내 재사용을 분리한다. cross-process persistent cache는 설계 전이므로 구현하지 않는다.

**Tech Stack:** Python 3.12, pytest, OpenCV, RF-DETR, boto3/R2, Supabase read-only, `resource`, macOS/MPS, uv

## Global Constraints

- 설계 정본: `/Users/baek/petcam-lab/docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`
- 실행 레포: `/Users/baek/petcam-lab`
- 구현 host: 현재 MacBook의 Claude 세션
- 실측 host: Mac mini `baeg-endeuui-Macmini.local`
- runtime kind: read-only manual benchmark. LaunchAgent·daemon·cron을 만들거나 수정하지 않는다.
- S1 대상은 S0 재감사에서 `policy_ready >= 80%`인 covered subset camera `5b3ea7aa`, `f6599924`뿐이다. camera `90119209` 결과로 일반화하지 않는다.
- DB는 SELECT만 허용한다. migration/RPC/INSERT/UPDATE/DELETE/UPSERT 금지.
- R2는 read-only GET만 허용한다. 영상·frame은 `TemporaryDirectory` 안에서만 만들고 정상·예외·중단 모두 cleanup한다.
- Claude/VLM 호출, selector 실행·변경, GT/behavior label/app activity write, production worker code·plist·환경변수 변경 금지.
- 운영 서비스가 실행 중이면 양보한다. activity lock과 VLM lock을 비차단 확인하고, 다음 예약 작업 전 hard deadline을 만족하지 못하면 benchmark를 시작하지 않는다.
- S1 성공은 production 배포 승인이 아니다. 성공해도 `S2 raw evidence shadow 계획 작성 가능`까지만 의미한다.
- 기존 unrelated untracked 파일과 다른 세션 파일은 add/수정/삭제하지 않는다.

## Frozen Experiment Contract

### Processing conditions

| ID | 조건 | 목적 | production 후보 여부 |
|---|---|---|---|
| `A6` | 현재 `vlm_frames.extract_six` 6-frame 추출 | 현행 입력 비용 기준선 | 기준선 |
| `B12` | 현재 Gate `sample_frames(..., 12)` + detector | sparse presence/bbox 비용 | 구성요소 |
| `CROI` | `B12` + bbox 내부 dense OpenCV flow | Python evidence 후보 비용 | 후보 |
| `DALL` | 모든 decodable frame에 detector | 위험 상한 대조군 | 절대 아님 |

- `CROI`에서 bbox가 없으면 `roi_status=no_bbox`로 기록하고 dense ROI 비용은 0으로 둔다. full frame을 ROI라고 바꾸지 않는다.
- `DALL`은 처리량 위험 대조만 한다. 결과와 무관하게 production 채택 대상이 아니다.
- detector device는 `mps`와 `cpu`를 분리 측정한다. 전체 paired workload는 MPS가 정본이고 CPU는 고정된 축소 manifest에서 장치 비교만 한다.

### Cache/download modes

- `cold_independent`: 조건별 R2 다운로드·decode를 독립 실행해 현재 cross-process 중복 상한을 잰다.
- `warm_same_run`: 한 번 받은 원본 mp4를 같은 process/run에서 재사용해 다운로드 제외 처리비를 잰다.
- `cross_process_cache`: **NOT RUN / NOT IMPLEMENTED**. cache key·lock·TTL·partial recovery·용량·보존·crash cleanup 계약이 없으므로 결과표에 `not_run_design_required`로 남긴다.

### Frozen workload

- 총 32 clip, deterministic seed `20260717`.
- camera `5b3ea7aa`: bbox-present 8 + bbox-absent 8.
- camera `f6599924`: bbox-present 16. 이 camera에는 현재 bbox-absent 가용 clip이 없다는 제약을 manifest에 기록한다.
- 각 stratum 안에서 `duration_sec` quartile을 균등하게 뽑는다. clip은 `activity-v1`, current assessment, `frames_sampled >= 6`, R2 key 존재 조건을 만족해야 한다.
- `DALL`과 CPU 장치 비교의 축소 manifest는 위 32개 중 각 stratum·duration quartile을 유지한 deterministic 16개다. 결과를 보고 표본을 바꾸지 않는다.
- accuracy GT는 보지 않는다. 이 표본은 처리량용이며 label 품질 판정에 사용하지 않는다.

### Repetitions and thresholds

- 각 measured path는 warmup 1회 후 measured repeat 3회. warmup은 p50/p95에서 제외한다.
- 유입량은 실행 직전 최근 7일 production read-only로 camera별 clips/hour 및 전체 p50/p95/max를 계산한다.
- `projected_4_camera_p95 = observed_total_p95 * 4 / observed_camera_count`를 기본 선형 가정으로 쓰고, observed camera count와 한계를 보고한다.
- 처리 능력은 `3600 / clip_e2e_p95_seconds`; 성공에는 `CROI_MPS_capacity >= projected_4_camera_p95 * 2`가 필요하다.
- peak RSS 상한: benchmark process `<= 4 GiB`.
- peak local temp disk 상한: `<= 2 GiB`.
- next scheduled production job까지 최소 25분이 남아야 시작할 수 있고, benchmark hard runtime budget은 20분이다. 20분 안에 끝나지 않으면 fail-closed 중단·cleanup 후 `HOLD_RUNTIME_BUDGET`이다.
- 실행 전후 관련 LaunchAgent의 run count/last exit/log error를 비교한다. 예약 지연·exit/error 증가가 1건이라도 있으면 성능 수치와 무관하게 HOLD다.

---

### Task 1: Baseline·유입량·표본 사전등록

**Files:**
- Create: `/Users/baek/petcam-lab/experiments/python-evidence-s1-throughput/TEST-SHEET.md`
- Create: `/Users/baek/petcam-lab/experiments/python-evidence-s1-throughput/sample_manifest.json`
- Create: `/Users/baek/petcam-lab/experiments/python-evidence-s1-throughput/influx_snapshot.json`
- Create: `/Users/baek/petcam-lab/scripts/prepare_python_evidence_s1.py`
- Create: `/Users/baek/petcam-lab/tests/test_prepare_python_evidence_s1.py`

- [ ] **Step 1: Verify handoff and repository heads**

Run the handoff validator first. Confirm lab HEAD equals the manifest SHA. Fetch without changing unrelated working trees. Record Gate/nightly production HEADs but do not require remembered SHAs.

- [ ] **Step 2: Write RED selection tests**

Cover camera allowlist, current `activity-v1`, `frames_sampled >= 6`, R2 key, deterministic quartile selection, insufficient stratum fail-closed, duplicate clip rejection, and stable JSON output.

- [ ] **Step 3: Implement read-only preparation**

The script may use Supabase SELECT only. Inject the row loader in tests. Static source must contain no mutation method or RPC call. The tracked manifest stores clip UUID·expected duration·expected bbox stratum only; R2 key는 실행 시 read-only 재조회하고 artifact·stdout에 남기지 않는다. Reports expose only short IDs and aggregate counts.

- [ ] **Step 4: Generate influx snapshot and manifest**

Run once against production read-only. Confirm exactly 32 unique clips and the frozen strata. If a stratum is insufficient, stop and update neither sample rule nor threshold without user review.

- [ ] **Step 5: Freeze TEST-SHEET before benchmark execution**

TEST-SHEET must include question, hypotheses, conditions, cache modes, sample contract, repeat count, metrics, thresholds, stop rules, non-goals, and hashes of manifest/influx snapshot. Mark the sheet `PRE_REGISTERED` with timestamp. Do not write results into it later except a link to the report.

### Task 2: Benchmark metric core and safety guard

**Files:**
- Create: `/Users/baek/petcam-lab/scripts/benchmark_python_evidence_s1.py`
- Create: `/Users/baek/petcam-lab/tests/test_benchmark_python_evidence_s1.py`

- [ ] **Step 1: Write RED tests for timing and percentiles**

Test warmup exclusion, repeat aggregation, p50/p95, throughput formula, projected four-camera formula, nonfinite/negative duration rejection, and empty sample failure.

- [ ] **Step 2: Write RED tests for safety**

Test wrong host, dirty/pinned SHA mismatch, activity/VLM lock busy, less than 25-minute safe window, 20-minute hard deadline, temp cleanup on success/exception/interrupt, and forbidden write/VLM adapter injection.

- [ ] **Step 3: Implement pure metric types and fail-closed preflight**

Use `time.perf_counter`, `resource.getrusage`, local directory byte counts, and explicit clock injection. Do not add `psutil`. The guard must run before R2 GET, detector load, or temp creation.

- [ ] **Step 4: Implement append-safe local results**

Write each measured record to local JSONL using atomic rename/checkpoint semantics. It must be safe to resume a partially completed benchmark without rerunning completed `(clip, condition, device, cache_mode, repeat)` keys. No DB persistence.

### Task 3: Exact condition adapters

**Files:**
- Modify: `/Users/baek/petcam-lab/scripts/benchmark_python_evidence_s1.py`
- Modify: `/Users/baek/petcam-lab/tests/test_benchmark_python_evidence_s1.py`

- [ ] **Step 1: Add `A6` adapter tests**

Use the exact nightly `reporter.vlm_frames.extract_six` adapter. Assert six outputs when decodable, duration/timing capture, and cleanup. It must not call Claude.

- [ ] **Step 2: Add `B12` adapter tests**

Use Gate `sample_frames(..., num_frames=12)` and `GeckoDetector`. Record sampling/decode and detector separately. Preserve bounded-memory sampling.

- [ ] **Step 3: Add `CROI` adapter tests**

Derive a union/robust bbox only from `B12` detector outputs. Decode sequentially and calculate raw, meaning-neutral ROI flow time series; do not classify basking/drinking, infer head position, or introduce thresholds. Assert `no_bbox` behavior.

- [ ] **Step 4: Add `DALL` adapter tests**

Sequentially decode one frame at a time and immediately infer/release; never hold all frames. Enforce reduced manifest and hard deadline. Mark every result `risk_control_only=true`.

- [ ] **Step 5: Add CPU/MPS device separation**

Pass explicit detector device to RF-DETR. If MPS is unavailable on Mac mini, stop rather than silently report CPU as MPS.

### Task 4: Download reuse and end-to-end runner

**Files:**
- Modify: `/Users/baek/petcam-lab/scripts/benchmark_python_evidence_s1.py`
- Modify: `/Users/baek/petcam-lab/tests/test_benchmark_python_evidence_s1.py`

- [ ] **Step 1: Write RED cold/warm tests**

Assert `cold_independent` downloads once per condition run, `warm_same_run` downloads once per clip/run and reuses the original, duplicate count is exact, and cross-process cache is never created.

- [ ] **Step 2: Implement injected R2 downloader**

Use the current nightly R2 read adapter. Record download wall time and bytes. Redact keys and secrets from stdout/result. Retry only bounded read errors; no infinite retries.

- [ ] **Step 3: Implement paired run scheduler**

Run warmup then three repeats with deterministic order rotation to reduce condition-order bias. Check hard deadline between every clip/condition. On a single clip failure, record sanitized error code and continue only if cleanup and deadline remain safe; systemic detector/R2 failure stops the run.

- [ ] **Step 4: Verify temp media zero**

Before and after every repeat, scan only the benchmark temp root. Final acceptance additionally scans known project temp roots on Mac mini. Source videos and frames must be 0 after exit.

### Task 5: Local verification and feature branch publication

- [ ] **Step 1: Run focused RED→GREEN evidence**

```bash
uv run pytest -q tests/test_prepare_python_evidence_s1.py tests/test_benchmark_python_evidence_s1.py
```

- [ ] **Step 2: Run full lab regression**

```bash
uv run pytest -q
uv run python -m compileall -q scripts
git diff --check
```

- [ ] **Step 3: Run forbidden-behavior audit**

Prove benchmark runtime source has no Supabase mutation/RPC, Claude/VLM call, LaunchAgent manipulation, production selector/settings write, or persistent cache creation.

- [ ] **Step 4: Commit and push an isolated feature branch**

Use `feat/python-evidence-s1-benchmark`. Commit TEST-SHEET, input artifacts, scripts, and tests only. Do not merge main before Mac mini dry preflight. Preserve unrelated files.

### Task 6: Mac mini read-only benchmark execution

**Runtime:** manual foreground command only on `baeg-endeuui-Macmini.local`.

- [ ] **Step 1: Create isolated Mac mini worktree**

Fetch the feature branch into a separate worktree. Do not switch the production lab main or any runtime repo branch. Verify Gate/nightly main heads and their test suites/dependencies.

- [ ] **Step 2: Verify runtime dependencies**

Run the lab benchmark through `/Users/baek-end/petcam-nightly-reporter`'s `uv run` so exact production Gate/RF-DETR/R2 packages are used. Confirm checkpoint SHA and detector device. Never install packages during the benchmark window.

- [ ] **Step 3: Capture service baseline**

Record relevant LaunchAgent loaded state, run count, last exit, recent error count, current locks, and next schedules. Require a safe 25-minute window. If unavailable, wait for the next safe window; do not bootout services.

- [ ] **Step 4: Execute benchmark with hard deadline**

Run the frozen manifest only. Keep foreground logs secret-free. If the 20-minute budget expires, stop, cleanup, record `HOLD_RUNTIME_BUDGET`, and do not shrink the sample post hoc.

- [ ] **Step 5: Post-run safety audit**

Confirm DB mutation count 0 by code path and read-only snapshots, VLM/Claude call 0, service deadline delay 0, exit/error increase 0, R2 temp 0, no persistent cache, and production repo heads unchanged.

### Task 7: Report, decision, and SOT closure

**Files:**
- Create: `/Users/baek/petcam-lab/experiments/python-evidence-s1-throughput/raw_results.jsonl`
- Create: `/Users/baek/petcam-lab/experiments/python-evidence-s1-throughput/summary.json`
- Create: `/Users/baek/petcam-lab/experiments/python-evidence-s1-throughput/REPORT.md`
- Create: `/Users/baek/petcam-lab/docs/handoff-prompts/2026-07-17-python-evidence-s1-throughput-benchmark-report.md`
- Modify: `/Users/baek/petcam-lab/docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`
- Modify: `/Users/baek/petcam-lab/specs/next-session.md`
- Modify: `/Users/baek/petcam-lab/experiments/INDEX.md`
- Modify: `/Users/baek/petcam-lab/.claude/donts-audit.md`

- [ ] **Step 1: Generate report from raw results**

The report must include influx baseline, sample limitations, per-condition/device/cache p50/p95, throughput ratio, memory/disk, duplicate downloads, service safety, failure list, and cross-process cache `not_run_design_required`.

- [ ] **Step 2: Apply exactly one verdict**

- `S1_PASS_CROI_THROUGHPUT`: all §14.3 gates pass; means only S2 raw-evidence shadow planning may begin.
- `S1_HOLD_REDUCE_CONFIG`: CROI misses throughput/resource gate without operational corruption; propose a smaller sampling configuration, do not implement it.
- `S1_HOLD_RUNTIME_BUDGET`: frozen benchmark cannot finish safely in the 20-minute window.
- `S1_REJECT_OPERATIONAL_RISK`: schedule delay, worker error/exit increase, temp leak, mutation, or other safety breach.

- [ ] **Step 3: Independent recomputation**

Use a separate read-only script/one-liner to recompute p50/p95, capacity ratio, and temp/service gates from raw JSONL. It must match `summary.json` exactly.

- [ ] **Step 4: Commit and push result artifacts**

Commit only owned experiment/report/SOT files. Push feature branch. Do not merge to main or change production based on S1 result.

- [ ] **Step 5: Stop and report**

Return exact verdict, feature branch SHA, Mac mini host/runtime heads, test counts, measured capacity ratio, safety gates, artifact paths, and remaining limitations. Wait for Codex/user independent verification before any S2 plan.

## Acceptance Checklist

- [ ] TEST-SHEET and deterministic manifests were frozen before detector benchmark.
- [ ] 32-clip covered-subset workload and 16-clip D/CPU subset match the contract.
- [ ] A6/B12/CROI/DALL ran with warmup excluded and 3 measured repeats, or a pre-registered HOLD stop rule fired.
- [ ] CROI contains raw ROI motion only; no semantic classification or threshold.
- [ ] Cross-process cache was not implemented.
- [ ] DB writes 0, VLM calls 0, selector/runtime changes 0.
- [ ] temp media 0 and production LaunchAgent delay/error/exit increase 0.
- [ ] Raw results independently recompute to the published verdict.
- [ ] S1 result is not represented as production adoption.
