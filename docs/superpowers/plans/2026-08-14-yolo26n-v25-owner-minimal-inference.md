# YOLO26n v2.5 Owner minimal inference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** immutable accepted Owner 280-frame bundle을 frozen v2.4로 추론해 deterministic hard-case를 고르고,
prediction이 보이지 않는 CVAT queue를 독립 검수까지 완료한다.

**Architecture:** 기존 hardened all-in-one 실행기는 live path에서 제외하고, content pins와 과학적 선택 정책만
가진 새 focused runner를 만든다. runtime drift는 version ledger와 import/model-load smoke로 관찰하되 전체
site-packages equality로 실행을 막지 않는다. private ledger와 public blind bundle을 분리하고 기존 validator를
최종 acceptance authority로 유지한다.

**Tech Stack:** Python 3.12, uv, Pillow, Ultralytics, PyTorch, pytest, 기존 v2.5 blind validator

## Global Constraints

- 기준 addendum:
  `docs/superpowers/specs/2026-08-14-yolo26n-v25-owner-minimal-inference-addendum.md`
- Gate input 인자 0, Gate downstream records 0
- validation153/internal151/external60 input 인자·접근·추론 0
- DB/R2/service/production model/GME/labeling web write·deploy 0
- existing 280 bundle은 read-only; decode/mining 반복 0
- 기존 failed/hardened attempts, locks, ledgers는 삭제·덮어쓰기·재사용 0. model-load 가능한 READY isolated
  runtime은 read-only 재사용할 수 있다.
- fresh output 0700/0600, no-overwrite
- 사람 bbox 전 dataset/train/eval 0
- pre-review 1회, post-output review 1회만 수행하고 fixed hard stop 밖 요구는 기록만 한다.
- 변경 파일이 10개 미만이므로 아래 파일만 순서대로 다룬다. unrelated dirty/untracked는 stage하지 않는다.

---

## Task 1: 과학 정책을 focused pure module로 고정

**Files:**
- Create: `scripts/yolo26n_v25_hardcase_science.py`
- Create: `tests/test_yolo26n_v25_hardcase_science.py`

### Step 1: 기존 정책 parity RED 작성

고정 fixture로 다음을 검증한다.

- duplicate IoU 경계 `0.70`
- empty prediction → `suspected_miss`
- single confidence `<0.50`, same-source `<=2.0s` detection support 유무
- box edge `2%/98%` partial-occlusion
- 우선순위 duplicate → miss → false-positive → occlusion → diversity
- source round-robin, source당 cap 6, total cap 210
- 정책 id와 seed literal

Run:

```bash
uv run pytest -q tests/test_yolo26n_v25_hardcase_science.py
```

Expected: module import 또는 API 부재로 RED.

### Step 2: 순수 최소 구현

I/O, runtime, artifact publication을 import하지 않는 typed functions로 classifier와 selector를 구현한다. 기존
builder 함수와 같은 fixture output을 내는 parity test를 추가하되 기존 builder를 수정하지 않는다.

### Step 3: GREEN과 정적 검증

```bash
uv run pytest -q tests/test_yolo26n_v25_hardcase_science.py
uv run python -m py_compile scripts/yolo26n_v25_hardcase_science.py
git diff --check
```

---

## Task 2: minimal runner 계약을 TDD로 구현

**Files:**
- Create: `scripts/run_yolo26n_v25_owner_inference_minimal.py`
- Create: `tests/test_run_yolo26n_v25_owner_inference_minimal.py`

### Step 1: CLI/API hard-stop RED 작성

테스트가 다음 계약을 먼저 실패하게 만든다.

- required inputs: absolute bundle directory, expected bundle directory SHA, expected count exact 280, checkpoint와
  expected raw SHA, freeze와 expected raw SHA, fresh output directory
- CLI에는 Gate/validation/internal/external/source-video 경로 인자가 없음; 전달하면 argparse unknown argument
- bundle manifest/member set/image SHA/count mismatch는 model factory 호출 전 fail
- checkpoint SHA mismatch와 freeze selected `{confidence:.25,nms_iou:.40,duplicate:4}` 또는
  `imgsz=960,max_det=50` mismatch는 model factory 호출 전 fail
- protected role record는 model factory 호출 전 fail
- output이 이미 있으면 model factory 호출 전 `FileExistsError`
- producer code SHA와 inference code SHA가 달라도 두 필드로 기록하며 성공
- runtime version 차이는 warning/count ledger만 바꾸고 성공
- frame 하나의 decode/model-result 실패는 reason count에 추가하고 나머지를 계속 처리
- 모든 frame이 제외되거나 selection 0이면 output READY를 만들지 않고 `V25_HARDCASE_QUEUE_SHORTAGE`
- inference는 `conf=.25,iou=.40,imgsz=960,max_det=50`, save false, stream false

Run:

```bash
uv run pytest -q tests/test_run_yolo26n_v25_owner_inference_minimal.py
```

Expected: module/API 부재로 RED.

### Step 2: bundle과 freeze 검증

runner 안에 focused readers를 구현한다.

- bundle directory contract SHA와 exact member set을 계산한다.
- manifest record 280개와 `F######.jpg` bytes SHA/dimensions/role을 검증한다.
- source identity는 private in-memory row에서만 유지한다.
- checkpoint/freeze raw SHA와 frozen params를 검증한다.
- historical/Gate/mtime/ctime/inode/runtime tree fingerprint를 요구하지 않는다.

### Step 3: runtime smoke와 per-frame inference

- 현재 Python, Ultralytics, Torch, TorchVision, NumPy, OpenCV, Pillow version을 문자열로 수집한다.
- import 및 verified checkpoint model-load smoke를 수행한다.
- 가능한 frame을 batch 또는 bounded chunk로 frozen params inference한다.
- result count/order/shape/finite boxes를 확인한다. 개별 실패는 `decode_failed`, `inference_failed`,
  `result_invalid` 중 하나로 제외하고 안전 count만 남긴다.
- surviving record에 Task 1 signal을 붙이고 cap 6/210 selector를 적용한다.

### Step 4: private provenance ledger와 no-write gate

한 개의 `provenance-ledger.private.json`을 canonical JSON으로 만들고 다음을 exact 기록한다.

- schema/status/role/policy/seed
- bundle directory SHA, bundle manifest SHA, checkpoint SHA, freeze SHA
- `producer_code_sha256`, `inference_code_sha256` 별도 필드
- frozen params, runtime versions
- input/surviving/excluded/selected count와 exclusion reason counts
- `gate_policy=quarantine_all`, `gate_candidate_count=0`, `gate_inputs_consumed=false`
- protected access count 0
- DB/R2/service/production model/GME/labeling web write/deploy count 0

public blind bundle에는 이 ledger를 넣지 않는다.

### Step 5: focused GREEN

```bash
uv run pytest -q \
  tests/test_yolo26n_v25_hardcase_science.py \
  tests/test_run_yolo26n_v25_owner_inference_minimal.py
uv run python -m py_compile \
  scripts/yolo26n_v25_hardcase_science.py \
  scripts/run_yolo26n_v25_owner_inference_minimal.py
git diff --check
```

---

## Task 3: blind CVAT bundle과 기존 validator 결속

**Files:**
- Modify: `scripts/run_yolo26n_v25_owner_inference_minimal.py`
- Modify: `tests/test_run_yolo26n_v25_owner_inference_minimal.py`
- Test only: `scripts/validate_yolo26n_v25_blind_queue.py`
- Test only: `tests/test_validate_yolo26n_v25_blind_queue.py`

### Step 1: blind leak RED 작성

다음을 공격 fixture로 고정한다.

- public filenames/manifest/COCO/ZIP에 source, prediction, confidence, bucket/signal 문자열 0
- COCO annotations empty, empty-frame allowed
- JPEG를 metadata-free deterministic JPEG로 재인코드하고 actual JPEG/EXIF empty/허용 info 재확인
- max210, source cap6, deterministic sequence `V25####`
- queue member exact bijection과 ZIP member bytes exact
- fresh output만 허용; existing output no-overwrite
- selected 0이면 queue/zip/READY 0

Expected: blind publisher 부재로 RED.

### Step 2: 최소 publisher 구현

fresh sibling staging에서 CVAT files, ZIP, private review index, provenance ledger를 완성한 뒤 final output이
미존재할 때 한 번 publish한다. public artifact에는 blind 필드만 두고 predictions/signals/source는 private review
index에만 둔다. 기존 validator가 기대하는 queue schema와 `BBOX_RULES_BYTES`를 그대로 사용한다.

### Step 3: 독립 validator acceptance GREEN

테스트가 runner output directory SHA를 계산해 기존 validator API/CLI에 넘기고
`V25_BLIND_QUEUE_ACCEPTED`를 확인한다. runner의 최종 status는 acceptance까지 성공한 경우에만
`V25_BLIND_CVAT_QUEUE_READY`다.

```bash
uv run pytest -q \
  tests/test_run_yolo26n_v25_owner_inference_minimal.py \
  tests/test_validate_yolo26n_v25_blind_queue.py
```

---

## Task 4: 구현 검증, commit, push

**Files:**
- Modify: `reports/yolo26n-v25-historical-hardcase-reinforcement/REPORT.md`
- Verify all files introduced or changed by Tasks 1-3

### Step 1: fixed-checklist self-review

아래만 확인하고 새 threat-model 요구를 추가하지 않는다.

- seven hard stops exact
- warning-only fields do not block
- protected path arguments absent
- Gate consumption 0
- producer/inference code SHA are separate
- selected cap/seed/science parity
- public leak 0 and validator acceptance
- write/deploy 0 and no training

### Step 2: full verification

```bash
uv run pytest -q \
  tests/test_yolo26n_v25_hardcase_science.py \
  tests/test_run_yolo26n_v25_owner_inference_minimal.py \
  tests/test_validate_yolo26n_v25_blind_queue.py
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider
uv run python -m py_compile \
  scripts/yolo26n_v25_hardcase_science.py \
  scripts/run_yolo26n_v25_owner_inference_minimal.py \
  scripts/validate_yolo26n_v25_blind_queue.py
git diff --check
git status --short
```

Mutation/write audit:

```bash
rg -n "supabase|r2|upload|deploy|service_role|train\(|fit\(" \
  scripts/run_yolo26n_v25_owner_inference_minimal.py \
  scripts/yolo26n_v25_hardcase_science.py
```

Expected: no external write/training path. REPORT records only safe aggregate evidence.

### Step 3: approved-scope commit and push

Stage only the addendum, plan, decision-gate append, new scripts/tests, and REPORT append. Verify staged names and diff,
commit with a Korean conventional message, then push current `codex/` branch. Do not stage unrelated files.

---

## Task 5: Mac mini minimal preflight와 one-shot live run

**Runtime host:** `baeg-endeuui-Macmini.local`
**Execution repo:** `/Users/baek-end/petcam-lab-yolo-v25-owner-only`
**Runtime kind:** development-only one-shot
**Fresh output root:** `/Users/baek-end/private-rba/yolo26n-v25-historical-hardcase-reinforcement/attempt-20260814-owner-minimal-v1`

### Step 1: minimal handoff preflight

- execution repo fetch 후 pushed implementation SHA를 detached checkout하고 clean 확인
- existing accepted bundle path를 preserved private handoff에서 resolve하고 directory SHA/count 280 확인
- checkpoint raw SHA와 freeze raw SHA/selected/imgsz/max_det 확인
- approved isolated runtime에서 imports와 model-load smoke
- fresh output root가 미존재인지 확인

과거 handoff chain이나 full runtime-tree equality를 다시 만들지 않는다. preflight output에는 path, credential,
source identifier를 출력하지 않고 SHA match/count/status만 남긴다.

### Step 2: one-shot inference와 queue build

exact implementation의 minimal runner를 approved isolated Python으로 한 번 실행한다. individual exclusions는
ledger count로 남기고, seven hard stops가 아니면 계속한다. 기존 280 bundle을 수정하거나 mining을 재실행하지
않는다.

### Step 3: independent acceptance 1회

기존 validator를 fresh queue directory/expected directory SHA/fresh acceptance path에 한 번 실행한다. 다음을
비민감 aggregate로 독립 확인한다.

- terminal status `V25_BLIND_CVAT_QUEUE_READY`
- queue image count 1..210
- source/video coverage count와 source당 max <=6
- ZIP raw SHA/member count
- provenance input/survivor/exclusion/selected counts
- protected/Gate/write/deploy counts all 0
- public forbidden tokens 0

정상 READY면 사람에게 queue image count, video coverage aggregate, CVAT ZIP 절대경로, bbox 규칙, 예상 검수
시간만 보고하고 멈춘다. 0장이면 `V25_HARDCASE_QUEUE_SHORTAGE`; 그 외에는 일곱 hard stop 중 정확한 상태와
비민감 count만 보고한다.

---

## Completion Boundary

이 plan의 완료는 새 모델 학습이 아니라 `V25_BLIND_CVAT_QUEUE_READY`다. 이후 사람은 예측을 보지 않고 gecko
bbox를 그리며 empty frame을 허용한다. 사람 acceptance 전 v2.5 dataset materialization/train/eval은 별도 승인
없이는 시작하지 않는다.
