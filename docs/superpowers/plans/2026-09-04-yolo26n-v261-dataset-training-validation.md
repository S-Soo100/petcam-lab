# YOLO26n v2.6.1 dataset·training·validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사람 bbox가 끝난 4,096장의 v2.6.1 hard-case를 누수 없는 학습/validation 데이터로 만들고, v2.6 baseline과 matched 6-run 비교를 거쳐 development-only 후보와 detector threshold를 동결한다.

**Architecture:** CVAT export 3개를 익명 review index와 다시 결합해 사람 GT 원장을 만든다. v2.6의 기존 train만 replay하고, v2.6에서 선택에 쓴 recent validation 505장과 old validation153/test151은 학습에서 계속 제외한다. 신규 GT는 source clip과 60초 이내 인접 episode를 하나의 group으로 묶어 train/validation 80:20으로 나눈다. 같은 dataset에서 v2.6 warm-start와 clean-reference를 seed 26/27/28로 각각 학습한 뒤, v2.6 baseline을 포함한 7개 후보를 신규 validation에 동일 protocol로 한 번씩 실행한다. 선택·threshold 동결 뒤에만 과거 regression suite를 실행한다.

**Tech Stack:** Python 3.12, `uv`, Ultralytics YOLO26n, PyTorch MPS, Pillow/OpenCV, pytest, CVAT for images 1.1 XML

**Spec:** `docs/superpowers/specs/2026-09-04-yolo26n-v261-expanded-hardcase-design.md`

## Global Constraints

- 실행 호스트는 MacBook이며 private attempt는 `/Users/baek/private-rba/yolo26n-v261-gme-hardcases/attempt-20260904-owner-v1`이다.
- 동결된 CVAT export는 `cvat-export-v1`의 Task 4/5/6 ZIP 세 개다. 기존 파일을 삭제·수정·덮어쓰지 않는다.
- export 실측 계약은 4,096 images, 2,699 positive images, 1,397 human-confirmed empty images, 2,732 gecko boxes, uncertain 0, media_error 0이다.
- 실제 게코만 positive다. 유리 반사상, 식물, 코르크, 선반과 기타 배경은 GT box가 아니다.
- sealed future holdout 300 clips는 frame·GT·prediction 접근 0을 유지한다.
- v2.6 train image replay는 허용하지만 v2.6 recent validation 505, old validation153, old internal test151은 학습 입력으로 금지한다.
- frozen v2.6 baseline/warm initializer는 `/Users/baek/private-rba/yolo26n-v26-recent-dense/attempt-20260826-owner-v1/runs-v26-comparison-v2/warm-start-s28/weights/best.pt`다.
- clean-reference initializer는 `/Users/baek/private-rba/yolo26n-v26-recent-dense/attempt-20260826-owner-v1/inputs/yolo26n-clean-reference.pt`다.
- frame random split을 금지한다. source clip과 60초 이내 인접 clip의 episode connected component가 최소 분리 단위다.
- 새 artifact는 private attempt 아래 새 경로에 O_EXCL/no-overwrite로만 생성하고 directory/file mode는 `0700/0600`으로 고정한다.
- DB/R2/service/GME/labeling web/production model write·deploy는 0이다.
- 구현, commit·push, dataset build, training, validation 실행은 각각 현재 계획 승인과 별개의 실행 단계다. 이 문서 작성만으로 실제 학습을 시작하지 않는다.

---

## Task 1: CVAT export를 재현 가능한 사람 GT 원장으로 동결

**Files:**
- Create: `scripts/normalize_yolo26n_v261_cvat_exports.py`
- Create: `tests/test_normalize_yolo26n_v261_cvat_exports.py`
- Modify: `experiments/yolo26n-v261-expanded-hardcase/TEST-SHEET.md`
- Modify: `experiments/yolo26n-v261-expanded-hardcase/REPORT.md`

- [x] **Step 1: 실패 테스트 작성**

다음을 각각 거부하는 테스트를 먼저 작성한다.

- export ZIP member가 `annotations.xml` 하나가 아님
- Task별 image count가 `2,000 / 2,000 / 96`과 다름
- 익명 파일명 또는 순서가 queue ZIP과 다름
- label set이 `gecko`, `uncertain`, `media_error`와 다름
- bbox가 image bounds 밖이거나 너비/높이가 0임
- 동일 image에 `uncertain`과 `media_error`가 함께 있음
- review index, queue completion, ZIP SHA가 실행 중 바뀜
- output 경로가 이미 존재하거나 private root 밖임

- [x] **Step 2: 테스트 실패 확인**

Run:

```bash
uv run pytest tests/test_normalize_yolo26n_v261_cvat_exports.py -q
```

Expected: module 미구현으로 FAIL.

- [x] **Step 3: 최소 normalizer 구현**

`normalize_yolo26n_v261_cvat_exports.py`에 다음 계약을 구현한다.

- 세 export의 XML meta와 image row를 queue part 순서대로 검증한다.
- `blind_name`으로 private `review-index.private.json`과 join한다.
- bbox는 pixel 좌표와 YOLO normalized 좌표를 모두 기록한다.
- box가 하나 이상이면 `gecko_present`, box와 tag가 모두 없으면 `gecko_absent`, tag가 있으면 각각 `uncertain`/`media_error`로 기록한다.
- 반사상 전용 class를 만들지 않는다. 사람 규칙상 반사상은 background이며 그 위 예측은 evaluation에서 FP가 된다.
- export ZIP, queue ZIP, review index, queue completion SHA를 `yolo26n-v261-export-freeze-v1` manifest에 기록한다.
- 최종 GT schema는 `yolo26n-v261-final-human-gt-v1`, status는 `V261_HUMAN_GT_READY`로 고정한다.
- output은 `human-gt-v1/export-freeze.private.json`과 `human-gt-v1/final-human-gt.private.json`에 한 번만 쓴다.

- [x] **Step 4: 테스트 통과 확인**

Run:

```bash
uv run pytest tests/test_normalize_yolo26n_v261_cvat_exports.py -q
```

Expected: PASS.

- [x] **Step 5: 실제 export normalizing과 독립 집계**

Run:

```bash
uv run python scripts/normalize_yolo26n_v261_cvat_exports.py \
  --review-index /Users/baek/private-rba/yolo26n-v261-gme-hardcases/attempt-20260904-owner-v1/blind-queue-v4/review-index.private.json \
  --queue-completion /Users/baek/private-rba/yolo26n-v261-gme-hardcases/attempt-20260904-owner-v1/blind-queue-v4/completion.private.json \
  --queue-root /Users/baek/private-rba/yolo26n-v261-gme-hardcases/attempt-20260904-owner-v1/blind-queue-v4 \
  --export-root /Users/baek/private-rba/yolo26n-v261-gme-hardcases/attempt-20260904-owner-v1/cvat-export-v1 \
  --output-root /Users/baek/private-rba/yolo26n-v261-gme-hardcases/attempt-20260904-owner-v1/human-gt-v1
```

Expected: `V261_HUMAN_GT_READY`, counts `4096 / 2699 / 1397 / 2732 / 0 / 0`.

---

## Task 2: parent v2.6와 신규 episode group을 결합한 dataset builder

**Files:**
- Create: `scripts/build_yolo26n_v261_dataset.py`
- Create: `tests/test_build_yolo26n_v261_dataset.py`
- Reference: commit `e4566db750f8e0f668d72aeadd6f8305a2361f90`, `scripts/build_yolo26n_v26_dataset.py`

- [x] **Step 1: split·누수 방지 실패 테스트 작성**

테스트 fixture에서 다음을 고정한다.

- 신규 records를 `clip_ref`와 같은 camera에서 60초 이내 인접한 source의 connected episode로 묶는다.
- seed 문자열은 `yolo26n-v261-group-split-v1`이다.
- episode group 단위로 신규 train/validation 목표 80:20을 맞추고 양 camera-night의 positive/negative가 가능한 범위에서 양 split에 존재한다.
- `uncertain`과 `media_error`는 dataset image/label에서 제외하고 exclusion ledger에 남긴다.
- `gecko_absent`는 빈 `.txt` label을 가진 negative sample로 보존한다.
- v2.6 parent train만 replay한다. parent recent val505, old val153, old test151이 train 또는 신규 validation에 들어오면 실패한다.
- same source, exact image SHA 또는 동일 episode가 train/validation 양쪽에 있으면 실패한다.
- protected fingerprint, v2.6 selected image exact overlap, future holdout source overlap은 실패한다.
- 같은 camera-night에서 5분 이내 dHash distance `<=8`이 split을 가로지르면 실패한다.
- parent image/label bytes와 manifest SHA가 바뀌면 실패한다.

- [x] **Step 2: 테스트 실패 확인**

Run:

```bash
uv run pytest tests/test_build_yolo26n_v261_dataset.py -q
```

Expected: module 미구현으로 FAIL.

- [x] **Step 3: builder 구현**

`build_yolo26n_v261_dataset.py`는 v2.6 builder의 path confinement, SHA 검증, group split과 no-overwrite 방식을 계승하되 schema를 다음처럼 분리한다.

- group plan: `yolo26n-v261-group-split-plan-v1`, `V261_GROUP_SPLIT_READY`
- dataset manifest: `yolo26n-owner-dataset-v261`, `V261_DATASET_READY`
- lineage에는 parent dataset/labels, final human GT, review index, export freeze, source plan, protected fingerprint와 builder source SHA를 기록한다.
- `train = frozen v2.6 train + 신규 train groups`, `val = 신규 validation groups`로 구성한다.
- 기존 v2.6 recent val505와 old val153/test151은 materialize하지 않고 immutable regression reference로만 manifest에 연결한다.
- class는 single `gecko=0`, images/labels/data.yaml은 상대경로와 전수 SHA를 manifest에 기록한다.

- [x] **Step 4: 테스트 통과 확인**

Run:

```bash
uv run pytest tests/test_build_yolo26n_v261_dataset.py -q
```

Expected: PASS.

- [x] **Step 5: dry-run split을 먼저 생성**

Run:

```bash
uv run python scripts/build_yolo26n_v261_dataset.py \
  --final-human-gt /Users/baek/private-rba/yolo26n-v261-gme-hardcases/attempt-20260904-owner-v1/human-gt-v1/final-human-gt.private.json \
  --review-index /Users/baek/private-rba/yolo26n-v261-gme-hardcases/attempt-20260904-owner-v1/blind-queue-v4/review-index.private.json \
  --source-plan-root /Users/baek/private-rba/yolo26n-v261-gme-hardcases/attempt-20260904-owner-v1/source-plan-v1 \
  --parent-dataset /Users/baek/private-rba/yolo26n-v26-recent-dense/attempt-20260826-owner-v1/dataset-v26-v1 \
  --protected-dataset-manifest /Users/baek/private-rba/yolo26n-v26-recent-dense/attempt-20260826-owner-v1/dataset-v26-v1/manifest.private.json \
  --protected-selection-manifest /Users/baek/private-rba/yolo26n-v26-recent-dense/attempt-20260826-owner-v1/blind-queue/selection.private.json \
  --split-output /Users/baek/private-rba/yolo26n-v261-gme-hardcases/attempt-20260904-owner-v1/dataset-v261-build-v1/group-split.private.json
```

Expected: `V261_GROUP_SPLIT_READY`. 실제 image 수, episode 수, camera-night와 positive/negative 분포를 승인 전 보고한다.

- [ ] **Step 6: 승인 뒤 dataset materialize**

Step 5에서 사람이 확인한 split 파일을 새로 계산하지 않고 SHA로 다시 읽는다. Step 5 명령의
`--split-output` 대신 아래 인자를 사용한다. `V261_APPROVED_SPLIT_SHA256`은 사람이 확인한 직후
`shasum -a 256`으로 기록한 값이어야 하며 materialize 시점에 다시 계산한 값으로 대체하지 않는다.

```bash
  --split-input /Users/baek/private-rba/yolo26n-v261-gme-hardcases/attempt-20260904-owner-v1/dataset-v261-build-v1/group-split.private.json \
  --approved-split-sha256 "$V261_APPROVED_SPLIT_SHA256" \
  --dataset-output /Users/baek/private-rba/yolo26n-v261-gme-hardcases/attempt-20260904-owner-v1/dataset-v261-v1 \
  --source-commit "$(git rev-parse HEAD)" \
  --materialize
```

Expected: `V261_DATASET_READY`, protected overlap 0, group leakage 0.

---

## Task 3: matched warm-start / clean-reference 3-seed training runner

**Files:**
- Create: `scripts/run_yolo26n_v261_training.py`
- Create: `tests/test_run_yolo26n_v261_training.py`
- Reference: commit `e4566db750f8e0f668d72aeadd6f8305a2361f90`, `scripts/run_yolo26n_v26_training.py`

- [x] **Step 1: runner 계약 테스트 작성**

- candidate는 `warm-start`, `clean-reference`만 허용한다.
- seed는 `26`, `27`, `28`만 허용한다.
- 공통 recipe는 `epochs=100`, `patience=20`, `optimizer=AdamW`, `lr0=0.001`, `imgsz=960`, `batch=2`, `workers=0`, `device=mps`, `deterministic=True`, `exist_ok=False`다.
- initializer 외 모든 학습 인자는 두 candidate에서 동일해야 한다.
- dataset manifest/status/SHA, initializer SHA, runner SHA, clean source commit과 YOLO executable SHA가 다르면 시작 전 거부한다.
- started lock, run directory, manifest가 이미 있으면 재실행·덮어쓰기를 거부한다.
- `results.csv`, `weights/best.pt`, 정상 return code가 모두 있어야 completion manifest를 만든다.

- [x] **Step 2: 실패 확인 후 최소 구현**

Run:

```bash
uv run pytest tests/test_run_yolo26n_v261_training.py -q
```

Expected before implementation: FAIL. 구현 후: PASS.

- [ ] **Step 3: 1-epoch smoke를 별도 임시 dataset/run root에서 실행**

두 initializer 경로를 각각 한 번 검증하되 production dataset과 정식 run lock을 소비하지 않는다. smoke도 private attempt 아래 `smoke-v261-v1`에 no-overwrite로 기록한다.

- [ ] **Step 4: full training source commit 고정**

Run:

```bash
V261_SOURCE_COMMIT="$(git rev-parse HEAD)"
test "$(git status --porcelain)" = ""
printf '%s\n' "$V261_SOURCE_COMMIT"
```

Expected: 40자리 commit과 빈 status. dirty이면 정식 training 금지.

- [ ] **Step 5: 정식 6-run 실행**

아래 순서로 각 run을 한 번만 실행한다.

```text
warm-start-s26 → warm-start-s27 → warm-start-s28
clean-reference-s26 → clean-reference-s27 → clean-reference-s28
```

warm-start initializer는 frozen v2.6 selected `best.pt`, clean-reference initializer는 v2.6에서 사용한 동일 approved YOLO26n base checkpoint다. 각 run에 `started.private.json`, Ultralytics run directory, `run-manifests-v261-v1/<candidate>-s<seed>.private.json`을 분리한다.

- [ ] **Step 6: 6-run 독립 completion 검사**

각 run의 final epoch, best epoch, precision, recall, mAP50, mAP50-95와 early-stop 여부를 `experiments/yolo26n-v261-expanded-hardcase/TRAINING-REPORT.md`에 집계한다. 학습 내부 validation은 후보 참고값이며 최종 선택값으로 쓰지 않는다.

---

## Task 4: v2.6 baseline 포함 same-protocol validation 7회와 freeze

**Files:**
- Create: `scripts/evaluate_yolo26n_v261.py`
- Create: `tests/test_evaluate_yolo26n_v261.py`
- Reference: commit `1463e537af2d5464b64b494dc712d743c35316fc`, `scripts/evaluate_yolo26n_v26.py`

- [x] **Step 1: evaluator 실패 테스트 작성**

- validation 후보는 `baseline-v26`과 v2.6.1 6개 run, 정확히 7개다.
- raw inference는 confidence `0.001`, model NMS IoU `0.70`, max_det `50`, imgsz `960`으로 한 번만 생성한다.
- offline NMS grid는 `0.40 / 0.55 / 0.70`, confidence grid는 `0.05..0.80`의 `0.05` 간격이다.
- ledger는 같은 dataset/GT/source/evaluator/inference protocol을 가져야 한다.
- one-shot claim이 prediction 전에 생성되고 이미 존재하면 재실행을 거부한다.
- frame precision/recall/specificity, TP/FP/FN, duplicate, camera-night 최소 recall, matched box IoU와 normalized center offset을 raw ledger에서 재계산한다.
- `gecko_absent`의 모든 prediction은 FP다. 실제 개체 외 반사상에만 생긴 prediction도 동일하게 FP다.
- threshold row gate는 precision `>=0.80`, recall `>=0.90`, specificity `>=0.90`, camera-night 최소 recall `>=0.85`다.
- localization guard는 baseline 대비 matched-box recall `-0.02` 이내, median matched IoU `-0.02` 이내다.
- 합격 row는 recall, specificity, median IoU, duplicate 역순, FP 역순, 높은 threshold, warm-start 우선으로 결정론적으로 고른다.
- 합격 후보가 없으면 `V261_VALIDATION_SHORTAGE`로 끝내고 regression/future holdout에 접근하지 않는다.

- [x] **Step 2: 실패 확인 후 evaluator 구현**

Run:

```bash
uv run pytest tests/test_evaluate_yolo26n_v261.py -q
```

Expected before implementation: FAIL. 구현 후: PASS.

- [ ] **Step 3: fresh evaluation root preflight**

평가 root는 `/Users/baek/private-rba/yolo26n-v261-gme-hardcases/attempt-20260904-owner-v1/evaluation-v261-v1`로 고정한다. dataset, 7 checkpoint, 6 completion manifest, source commit과 사람이 승인한 v2.6 baseline checkpoint SHA를 검증한 뒤에만 prediction을 허용한다.
검증 결과는 no-overwrite `evaluation-bindings.private.json`으로 고정하고 각 prediction은 이 파일의
dataset/evaluator/source/checkpoint SHA를 다시 확인한다. 같은 preflight에서 blind queue의
future-holdout access count 0, sealed holdout manifest SHA, old validation153 manifest SHA와 해당 inference
artifact 부재를 `protection-evidence.private.json`으로 기록한다.

- [ ] **Step 4: validation prediction 정확히 7회**

실행 순서는 다음과 같이 고정한다.

```text
baseline-v26
warm-start-s26
warm-start-s27
warm-start-s28
clean-reference-s26
clean-reference-s27
clean-reference-s28
```

- [ ] **Step 5: validation-only freeze**

7개 ledger가 모두 존재하고 GT digest가 같을 때만 `detector-freeze.private.json`을 생성한다. freeze schema는 `yolo26n-v261-detector-freeze-v1`이며 7개 checkpoint와 ledger SHA, selected checkpoint, threshold, NMS, resize/color contract와 10fps `3-of-5` temporal rule을 묶는다. sparse frame validation이므로 `clip_level_acceptance_pending=true`를 유지한다.

---

## Task 5: 선택 뒤 regression-only 평가

**Files:**
- Modify: `scripts/evaluate_yolo26n_v261.py`
- Modify: `tests/test_evaluate_yolo26n_v261.py`
- Create: `experiments/yolo26n-v261-expanded-hardcase/EVALUATION-REPORT.md`

- [x] **Step 1: regression gate 테스트 작성**

- freeze가 없으면 어떤 regression input도 열지 않는다.
- v2.6 baseline과 selected v2.6.1 외 checkpoint를 거부한다.
- v2.6 recent validation505는 두 모델 각각 한 번만 실행하고 새 threshold 선택에는 쓰지 않는다.
- old internal test151도 두 모델 각각 한 번만 실행하고 threshold 변경에 쓰지 않는다.
- old validation153은 fingerprint/lineage 검증만 하며 이번 plan에서는 inference하지 않는다.
- precision/recall은 각 regression suite에서 v2.6 baseline 대비 `-0.02` 이내여야 한다.
- raw ledger metric 독립 재계산과 job→artifact SHA 연결이 일치해야 한다.

- [ ] **Step 2: regression 실행과 report 생성**

freeze 성공 뒤 각 고정 suite의 parent dataset manifest SHA, 정확한 record 수(505/151), record-set SHA,
baseline/selected checkpoint SHA를 각각 `regression-bindings.private.json`에 고정한다. validation용 preflight를
재사용하지 않는다. 그 뒤 다음 네 prediction만 실행한다.

```text
v2.6 recent-val505: baseline-v26, selected-v261
old internal-test151: baseline-v26, selected-v261
```

`EVALUATION-REPORT.md`에는 신규 validation 성능, 두 regression suite 비교, threshold/NMS, duplicate와 localization guard, `regression-only`, `future holdout pending`을 명시한다.

- [ ] **Step 3: sealed future holdout 미접근 확인**

future holdout manifest의 SHA와 access count 0을 확인하되 source row와 frame은 열지 않는다. v2.6.1의 production/shadow 채택, active checkpoint 교체와 300-clip holdout GT 준비는 별도 계획·승인으로 남긴다.

---

## Task 6: 전체 검증과 승인 지점

**Files:**
- Modify: `docs/superpowers/specs/2026-09-04-yolo26n-v261-expanded-hardcase-design.md`
- Modify: `experiments/yolo26n-v261-expanded-hardcase/TEST-SHEET.md`
- Modify: `experiments/yolo26n-v261-expanded-hardcase/REPORT.md`

- [x] **Step 1: 관련 unit test 실행**

```bash
uv run pytest \
  tests/test_build_yolo26n_v261_expanded_queue.py \
  tests/test_materialize_yolo26n_v261_queue.py \
  tests/test_normalize_yolo26n_v261_cvat_exports.py \
  tests/test_build_yolo26n_v261_dataset.py \
  tests/test_run_yolo26n_v261_training.py \
  tests/test_evaluate_yolo26n_v261.py -q
```

Expected: all PASS.

- [ ] **Step 2: 코드 품질 검사**

```bash
uv run ruff check \
  scripts/normalize_yolo26n_v261_cvat_exports.py \
  scripts/build_yolo26n_v261_dataset.py \
  scripts/run_yolo26n_v261_training.py \
  scripts/evaluate_yolo26n_v261.py \
  tests/test_normalize_yolo26n_v261_cvat_exports.py \
  tests/test_build_yolo26n_v261_dataset.py \
  tests/test_run_yolo26n_v261_training.py \
  tests/test_evaluate_yolo26n_v261.py
```

Expected: no errors.

- [ ] **Step 3: private artifact 독립 감사**

다음을 exact count로 보고한다.

- final GT와 dataset의 positive/negative/excluded 수
- parent replay와 신규 train/validation 수
- source/episode/camera-night 분포
- protected/future/v2.6-validation overlap와 group leakage 수
- 6개 training completion 수
- validation ledger 7개와 regression ledger 4개 수
- DB/R2/service/model/labeling web write/deploy 수

- [ ] **Step 4: 문서 상태 갱신**

`TEST-SHEET.md`, `REPORT.md`, design checklist에 실제 manifest SHA와 aggregate만 기록한다. 비밀값, 원문 image/GT, clip/source ID는 기록하지 않는다.

- [ ] **Step 5: 최종 판정**

다음 중 하나만 선언한다.

- `V261_DEVELOPMENT_CANDIDATE_READY`: validation freeze와 regression guard 통과
- `V261_VALIDATION_SHORTAGE`: 후보 없음, regression 미접근
- `V261_REGRESSION_FAILED`: validation freeze는 성공했지만 과거 분포 guard 실패
- `V261_INTEGRITY_FAILED`: GT/dataset/lineage/overlap/no-overwrite 계약 실패

어느 경우도 production 채택이나 배포 완료로 표현하지 않는다.

## 실행 승인 경계

이 문서가 승인되어도 다음 단계는 자동 승인으로 간주하지 않는다.

1. 구현·unit test
2. 코드·문서 commit/push
3. 실제 GT normalize와 dataset split/build
4. MacBook 정식 6-run 학습
5. validation 7회와 threshold freeze
6. regression 4회
7. future holdout 준비·평가와 production 반영

각 단계는 직전 산출물의 exact 상태를 보고하고 사용자의 별도 실행 승인을 받은 뒤 진행한다.
