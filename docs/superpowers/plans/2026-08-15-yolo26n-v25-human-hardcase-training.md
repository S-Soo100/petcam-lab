# YOLO26n v2.5 Human Hard-case Training Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CVAT Task 167 / Job 164의 blind bbox 201장을 v2.4 train에 append-only로 결합하고, warm-start와 clean-reference를 동일 개발 평가 계약으로 비교해 v2.5 development 후보를 고른다.

**Architecture:** strict normalizer가 CVAT 원장을 queue bytes에 묶고, dataset builder가 v2.4 parent를 보존한 새 immutable dataset을 만든다. training runner는 두 후보를 독립 one-shot으로 학습하며, evaluator는 frozen v2.4 baseline과 두 후보를 같은 validation 프로토콜로 다시 측정한 뒤 선택 후보와 baseline만 fixed-test에서 비교한다.

**Tech Stack:** Python 3.12, uv, Pillow, Ultralytics YOLO26n, PyTorch MPS, pytest.

---

## Task 1: CVAT Job 164 원장 정규화

**Files:**
- Create: `scripts/normalize_yolo26n_v25_cvat_export.py`
- Create: `tests/test_normalize_yolo26n_v25_cvat_export.py`

- [x] strict fixture로 정상 201 frame / 219 bbox / 198 positive / 3 negative 계약 테스트를 먼저 작성한다.
- [x] wrong task/job/state/label, bool-as-int, track/tag/non-manual/non-rectangle, missing/extra frame, invalid bbox, queue SHA·dimension drift, partial publish 적대 테스트를 작성하고 RED를 확인한다.
- [x] `normalize_export(...) -> dict` 순수 함수와 no-clobber 0600 snapshot/summary publisher를 구현한다.
- [x] sequence `V250001..V250201`, raw label id 11, `gecko`, frame 0..200을 queue manifest와 exact bijection으로 묶는다.
- [x] raw annotations/queue manifest/JPEG bytes SHA와 dimensions, aggregate를 manifest에 기록한다.
- [x] `uv run pytest -q tests/test_normalize_yolo26n_v25_cvat_export.py`와 `py_compile`을 통과시킨다.

## Task 2: Dataset v2.5 빌더

**Files:**
- Create: `scripts/build_yolo26n_owner_dataset_v25.py`
- Create: `tests/test_build_yolo26n_owner_dataset_v25.py`
- Reference: `scripts/build_yolo26n_owner_dataset_v24.py`

- [x] parent1458 + hard-case201 = train1659, val153, test151, total1963 테스트를 RED로 만든다.
- [x] parent val/test record order와 모든 image/label bytes가 보존되고 새 201장은 train-only임을 검증한다.
- [x] positive198/negative3/box219, class0, finite normalized bbox, empty3의 explicit zero-byte label 파일을 검증한다.
- [x] parent exact SHA overlap을 재검사하고 frozen queue의 dHash<=2 보증은 queue manifest SHA로 상속한다.
- [x] staging 전체 file set/hash/decode/label/aggregate를 재검증하고 exclusive rename으로 fresh destination에만 publish한다.
- [x] manifest에 parent/snapshot/queue provenance와 DB/R2/service/deploy write count 0을 기록한다.
- [x] 단위·적대 테스트, 관련 v2.4 builder 회귀, `py_compile`을 통과시킨다.

## Task 3: 두 후보 one-shot 학습 실행기

**Files:**
- Create: `scripts/run_yolo26n_v25_training.py`
- Create: `tests/test_run_yolo26n_v25_training.py`
- Reference: `scripts/run_yolo26n_v24_gate_reuse.py`
- Reference: `scripts/run_yolo26n_v22_training.py`

- [x] warm-start(60/patience15/lr0 .001)와 clean-reference(100/patience20/lr0 .01)의 exact spec 테스트를 작성한다.
- [x] 공통 imgsz960/batch2/device mps/workers0/seed26/AdamW와 기존 augmentation 계약을 고정한다.
- [x] dataset SHA, initializer SHA, code SHA만 hard-stop identity로 검사한다.
- [x] Python/Ultralytics/Torch/TorchVision/NumPy/OpenCV/Pillow 버전은 warning ledger로만 기록하고 mismatch로 중단하지 않는다.
- [x] candidate별 0600 STARTED lock을 inference 전에 선점하고 results.csv/best.pt/completion manifest를 no-overwrite로 검증한다.
- [x] 한 후보 실패가 다른 후보 자동 채택으로 이어지지 않도록 독립 상태를 기록한다.
- [x] 단위·회귀 테스트와 `py_compile`을 통과시킨다.

## Task 4: 동일 프로토콜 비교 평가기

**Files:**
- Create: `scripts/evaluate_yolo26n_v25.py`
- Create: `tests/test_evaluate_yolo26n_v25.py`
- Reference: `scripts/evaluate_yolo26n_v24_gate_reuse.py`

- [x] frozen v2.4 baseline + warm + clean validation ledger를 각각 1회만 생성하는 계약을 테스트한다.
- [x] 공통 inference `conf=.001/imgsz=960/nms_iou=.70/max_det=50/device=mps`, match IoU .50을 고정한다.
- [x] threshold .05..80/.05, precision floor .60, 후보별·global tie-break를 결정론 테스트로 고정한다.
- [x] 둘 다 floor 미달이면 test 접근 전에 `V25_VALIDATION_SHORTAGE`로 중단한다.
- [x] freeze 뒤 baseline과 선택 후보만 internal test151에 exact same protocol로 1회 실행한다.
- [x] Owner external60 재실행을 금지하고 역사 참고값만 보고서에 허용한다.
- [x] report에 v2.4 same-protocol 행, 선택 lineage, warm/clean recipe 차이, development-only와 future-holdout 필요를 기록한다.
- [x] 단위·회귀 테스트와 `py_compile`을 통과시킨다.

## Task 5: 통합 검증과 리뷰

- [x] 새 네 테스트 파일과 관련 v2.4/v2.2 회귀를 실행한다.
- [x] `uv run pytest -q` 전체 회귀를 실행하고 실패가 있으면 원인을 분리해 최대 3회 안에서 수정한다.
- [x] `git diff --check`, `py_compile`, DB/R2/service/production mutation audit를 실행한다.
- [x] Claude 독립 코드 리뷰에서 Critical/Important 0을 확인한다.
- [ ] 설계·계획·코드 범위만 커밋하고 branch를 push한다.

## Task 6: Mac mini private 실행

- [ ] reviewed commit의 clean detached archive와 private fresh attempt root를 준비한다.
- [ ] Job164 export 정규화 → dataset materialize를 순서대로 수행하고 각 manifest SHA를 독립 검증한다.
- [ ] warm-start와 clean-reference를 one-shot 실행하며 정상 진행은 완료까지 자동 감시한다.
- [ ] 두 학습 completion manifest와 best.pt를 검증한 뒤 validation 3-way evaluation과 freeze를 수행한다.
- [ ] freeze 성공 시 baseline+selected fixed-test를 실행하고 development comparison report를 만든다.
- [ ] raw SHA와 독립 metric 재계산으로 최종 acceptance를 수행한다.
- [ ] production/GME/labeling web 배포 없이 `V25_TRAINED_DEVELOPMENT_ONLY` 또는 명확한 fail-closed 사유를 보고한다.

## Task 7: Future holdout 사람 작업 handoff

- [ ] v2.5 학습·개발평가가 성공한 뒤에만 새 촬영분으로 prediction-blind holdout queue를 설계한다.
- [ ] 사람에게 bbox 규칙, 수량, 예상시간을 전달하고 별도 승인 전에는 모델 채택·배포를 하지 않는다.
