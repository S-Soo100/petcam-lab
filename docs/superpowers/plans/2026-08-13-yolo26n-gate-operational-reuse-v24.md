# YOLO26n Gate 운영 GT 재사용 v2.4 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 과거 Gecko Vision Gate의 운영 사람 GT만 누수 없이 v2.4 train에 보강하고, 동결된 v2.3 validation/test와 Owner 외부 진단 60장으로 재현율 개선 여부를 판정한다.

**Architecture:** MacBook의 Gate COCO 원본을 read-only로 검증하고 source clip cap·dHash·lineage 규칙으로 후보를 만든다. Owner가 결정론적 60장 bbox 정책 감사를 통과시킨 뒤 Mac mini private 영역에서 v2.3 dataset을 byte-for-byte 부모로 복사하고 Gate 후보만 train에 추가한다. v2.3 warm checkpoint에서 단일 v2.4 학습을 실행하고 validation threshold를 먼저 동결한 뒤 internal fixed test와 Owner 외부 60장을 각각 한 번만 평가한다.

**Tech Stack:** Python 3.12, uv, Pillow, imagehash-compatible dHash, YOLO26n/Ultralytics CLI, pytest, Mac mini MPS, private JSON provenance.

## Global Constraints

- 허용 입력은 Gate COCO의 `operational` 사람 GT 1,951장뿐이다. Roboflow 1,430장은 제외한다.
- strict bbox 위반 16장은 자동 clamp하지 않고 `invalid_bbox_quarantine`으로 남긴다.
- selector seed는 `yolo26n-gate-operational-reuse-v24-v1`, source clip cap은 2, source-local dHash 허용 거리는 `>2`다.
- v2.3 validation/test의 bytes·순서·label은 변경하지 않는다. Gate 후보는 v2.4 train에만 추가한다.
- v2.3 val/test와 exact SHA, source clip, camera-night, 동일 원본 파생 관계가 겹치거나 lineage가 불명확한 Gate 후보는 제외한다.
- 최종 후보 최소 조건은 total 300, positive 150, negative 100, source clip 200이다.
- 학습 전 Owner bbox 정책 감사는 서로 다른 clip의 positive 40장 + negative 20장이다.
- 학습은 v2.3 selected warm checkpoint에서 시작하고 v2.3의 seed/imgsz/optimizer/epoch/patience/augmentation/MPS 계약을 유지한다.
- threshold는 validation precision floor `0.60`을 만족하는 grid에서만 동결한다. 동결 전 test/external inference는 금지한다.
- 채택 후보 기준은 internal fixed test recall `>=0.6389`, precision `>=0.60`, external recall `>=0.4211`, external FP `<=20`, duplicate `<=4`다.
- DB/R2/service/GME/labeling web/active model write는 0이다. 원본·v2.3·외부 진단 artifact는 불변이다.
- production 적용과 commit/push는 별도 Owner 승인 전에는 실행하지 않는다.

## 파일 구조

- Create: `scripts/build_yolo26n_gate_operational_candidates_v24.py` — COCO 검증, dedup, lineage 제외, 후보·감사 bundle 생성.
- Create: `tests/test_build_yolo26n_gate_operational_candidates_v24.py` — selector와 fail-closed provenance 계약.
- Create: `scripts/build_yolo26n_owner_dataset_v24.py` — Owner 감사 결과 검증 후 v2.3 부모에 train-only materialization.
- Create: `tests/test_build_yolo26n_owner_dataset_v24.py` — 부모 불변·원자적 publish·집계 검증.
- Create: `scripts/run_yolo26n_v24_gate_reuse.py` — warm-only 학습 manifest와 one-shot lock 관리.
- Create: `tests/test_run_yolo26n_v24_gate_reuse.py` — exact training contract·no-overwrite·provenance 검증.
- Create: `scripts/evaluate_yolo26n_v24_gate_reuse.py` — validation threshold freeze, fixed test, external60 비교 report.
- Create: `tests/test_evaluate_yolo26n_v24_gate_reuse.py` — 평가 순서·기준·lineage·one-shot 검증.
- Create: `reports/yolo26n-gate-operational-reuse-v24/README.md` — 비민감 집계와 최종 판정만 기록.

---

### Task 1: Gate 운영 GT 후보 selector와 lineage preflight

**Files:**
- Create: `scripts/build_yolo26n_gate_operational_candidates_v24.py`
- Create: `tests/test_build_yolo26n_gate_operational_candidates_v24.py`

**Interfaces:**
- Consumes: Gate `train.json`, `val.json`, `test.json`, Gate image root, v2.3 manifest, v2.1/v2.2/v2.3 private provenance ledgers.
- Produces: `candidate-manifest.private.json`, `audit-index.csv`, `audit-frames/`, `exclusions.private.json`.
- Pure API: `build_gate_candidate_plan(coco_documents, image_metadata, protected_records, lineage_rows, seed) -> dict[str, object]`.
- Pure API: `select_policy_audit(records, positive_count=40, negative_count=20) -> list[dict[str, object]]`.

- [x] **Step 1: COCO·bbox·lineage fail-closed 테스트 작성**

```python
def test_selector_rejects_non_operational_and_quarantines_oob_bbox():
    plan = build_gate_candidate_plan(
        coco_documents=[fixture_operational_and_roboflow()],
        image_metadata=fixture_image_metadata(),
        protected_records=[],
        lineage_rows=[],
        seed="yolo26n-gate-operational-reuse-v24-v1",
    )
    assert plan["source_counts"] == {"operational": 2}
    assert plan["exclusion_counts"]["invalid_bbox_quarantine"] == 1
    assert plan["selected_count"] == 1


def test_selector_excludes_sha_source_night_and_unresolved_lineage():
    plan = build_gate_candidate_plan(
        coco_documents=[fixture_four_operational_images()],
        image_metadata=fixture_image_metadata(),
        protected_records=fixture_protected_val_test(),
        lineage_rows=fixture_lineage_rows_with_one_unresolved(),
        seed="yolo26n-gate-operational-reuse-v24-v1",
    )
    assert plan["exclusion_counts"] == {
        "exact_sha_overlap": 1,
        "source_clip_overlap": 1,
        "camera_night_overlap": 1,
        "unresolved_lineage": 1,
    }
```

- [x] **Step 2: selector 테스트가 구현 부재로 실패하는지 확인**

Run: `uv run pytest -q tests/test_build_yolo26n_gate_operational_candidates_v24.py`

Expected: import 또는 함수 부재로 FAIL.

- [x] **Step 3: strict COCO parser·SHA/dHash·clip cap selector 구현**

구현은 다음 값을 record마다 고정한다.

```python
{
    "source_relpath": "operational/<clip>/<frame>.jpg",
    "source_clip_ref": "<clip>",
    "camera_night_ref": "<resolved-or-null>",
    "image_sha256": "<lowercase-sha256>",
    "dhash64": "<16-lowercase-hex>",
    "positive": True,
    "box_count": 1,
    "width": 1280,
    "height": 960,
    "boxes_xywh": [[10.0, 20.0, 100.0, 80.0]],
}
```

같은 clip에 positive/negative가 함께 있으면 상태별 1장, 한 상태만 있으면 seed+SHA anchor와 dHash `>2`인 최장거리 1장을 선택한다. 보호 집합의 source/camera-night를 복원하지 못하면 후보를 채우지 않고 `unresolved_lineage`로 제외한다.

- [x] **Step 4: 결정론·역순·clip cap·shortage 테스트 추가**

```python
def test_selector_is_reversed_input_deterministic_and_caps_each_clip_at_two():
    forward = build_gate_candidate_plan(**fixture_large_plan(reverse=False))
    reverse = build_gate_candidate_plan(**fixture_large_plan(reverse=True))
    assert forward["selected_records"] == reverse["selected_records"]
    assert max(Counter(r["source_clip_ref"] for r in forward["selected_records"]).values()) <= 2


def test_selector_returns_shortage_below_exact_minimums():
    plan = build_gate_candidate_plan(**fixture_plan(total=299, positive=149, negative=99, clips=199))
    assert plan["status"] == "V24_GATE_REUSE_SHORTAGE"
```

- [x] **Step 5: private artifact writer와 60장 audit bundle 구현**

artifact는 새 output directory에만 O_EXCL/0600으로 쓰고, audit image에는 사람 GT bbox만 표시한다. 모델 예측 bbox는 포함하지 않는다. `audit-index.csv`는 generic `G0001..G0060`과 `expected_policy=review`만 노출한다.

- [x] **Step 6: Task 1 전체 검증**

Run: `uv run pytest -q tests/test_build_yolo26n_gate_operational_candidates_v24.py`

Expected: PASS.

- [ ] **Step 7: commit checkpoint**

Owner가 별도로 commit을 승인한 경우에만:

```bash
git add scripts/build_yolo26n_gate_operational_candidates_v24.py tests/test_build_yolo26n_gate_operational_candidates_v24.py
git commit -m "feat: Gate 운영 GT v2.4 후보 selector"
```

---

### Task 2: Owner 60장 bbox 정책 감사 gate

**Files:**
- Modify: `scripts/build_yolo26n_gate_operational_candidates_v24.py`
- Modify: `tests/test_build_yolo26n_gate_operational_candidates_v24.py`

**Interfaces:**
- Consumes: Task 1 `audit-index.csv`, Owner 작성 `sequence,verdict` CSV.
- Produces: `owner-audit-summary.private.json` with `V24_GATE_AUDIT_ACCEPTED`, `V24_GATE_POSITIVE_FULL_REVIEW_REQUIRED`, or `V24_GATE_NEGATIVE_FULL_REVIEW_REQUIRED`.
- Pure API: `validate_owner_policy_audit(index_rows, verdict_rows) -> dict[str, object]`.

- [x] **Step 1: exact 60·순서·verdict 테스트 작성**

```python
def test_owner_audit_accepts_exact_40_positive_and_20_negative():
    summary = validate_owner_policy_audit(fixture_audit_index(), fixture_all_accept())
    assert summary["status"] == "V24_GATE_AUDIT_ACCEPTED"
    assert summary["positive_count"] == 40
    assert summary["negative_count"] == 20


@pytest.mark.parametrize("bad", ["", "yes", True, 1, "fix_box", "wrong_negative"])
def test_owner_audit_rejects_unknown_verdict(bad):
    with pytest.raises(ValueError):
        validate_owner_policy_audit(fixture_audit_index(), fixture_with_verdict(bad))
```

- [x] **Step 2: RED 확인 후 exact CSV validator 구현**

허용 verdict는 `accept`, `positive_needs_fix`, `negative_mislabeled` 세 개뿐이다. positive 수정 1건 이상이면 전체 positive 후보 재검수, negative 오라벨 1건 이상이면 전체 negative 후보 재검수 상태를 반환한다.

- [x] **Step 3: fail-closed 상태 검증**

Run: `uv run pytest -q tests/test_build_yolo26n_gate_operational_candidates_v24.py`

Expected: PASS. 감사 승인 전 dataset materialization 호출은 `PermissionError`로 실패.

- [ ] **Step 4: commit checkpoint**

별도 승인 시에만 selector 파일과 테스트를 stage/commit한다.

---

### Task 3: v2.3 부모 불변 v2.4 dataset materialization

**Files:**
- Create: `scripts/build_yolo26n_owner_dataset_v24.py`
- Create: `tests/test_build_yolo26n_owner_dataset_v24.py`

**Interfaces:**
- Consumes: pinned v2.3 manifest/root, accepted candidate manifest, accepted Owner audit summary, Gate images.
- Produces: `yolo26n-owner-dataset-v24` manifest, YOLO train/val/test tree, `data.yaml`, cache directory.
- Pure API: `build_v24_plan(base_manifest, candidate_manifest, audit_summary) -> dict[str, object]`.

- [x] **Step 1: 부모 split 불변과 train-only 추가 테스트 작성**

```python
def test_v24_preserves_parent_val_test_and_adds_gate_only_to_train():
    plan = build_v24_plan(fixture_v23_manifest(), fixture_gate_candidates(320), fixture_accepted_audit())
    assert plan["parent_split_counts"] == {"train": 889, "val": 153, "test": 151}
    assert plan["v24_split_counts"] == {"train": 1209, "val": 153, "test": 151}
    assert {row["split"] for row in plan["gate_records"]} == {"train"}
```

- [x] **Step 2: RED 확인 후 manifest·YOLO label 변환 구현**

COCO `[x,y,w,h]`를 YOLO normalized `[cx,cy,w,h]`로 9자리 고정 변환하고, class id는 `0`만 허용한다. 부모 record와 파일은 staging에서 SHA/label/decode를 다시 검증한다.

- [x] **Step 3: TOCTOU·no-clobber·원자 publish 테스트 작성**

```python
def test_materializer_rejects_source_mutation_and_never_replaces_destination(tmp_path):
    with pytest.raises(ValueError, match="changed"):
        run_materialization(**fixture_mutating_source(tmp_path))
    assert not fixture_output(tmp_path).exists()
```

- [x] **Step 4: staging 재검증과 exclusive rename 구현**

publish 직전 exact file set, 모든 image SHA, label count/geometry, val/test parent order·bytes를 다시 검증하고 no-replace rename으로 final directory를 만든다.

- [x] **Step 5: Task 3 검증**

Run: `uv run pytest -q tests/test_build_yolo26n_owner_dataset_v24.py`

Expected: PASS.

- [ ] **Step 6: commit checkpoint**

별도 승인 시에만 v2.4 builder와 테스트를 stage/commit한다.

---

### Task 4: v2.4 warm-only one-shot 학습

**Files:**
- Create: `scripts/run_yolo26n_v24_gate_reuse.py`
- Create: `tests/test_run_yolo26n_v24_gate_reuse.py`

**Interfaces:**
- Consumes: v2.4 dataset manifest/data.yaml, v2.3 selected warm `best.pt`, exact source commit/archive.
- Produces: `runs/warm-start/`, `run-manifests/warm-start.private.json`, one-shot started lock.
- API: `build_v24_training_spec(data_yaml, initializer, runs_dir) -> TrainingSpec`.

- [x] **Step 1: exact training command 테스트 작성**

```python
def test_v24_training_matches_v23_warm_contract():
    spec = build_v24_training_spec(Path("data.yaml"), Path("v23-best.pt"), Path("runs"))
    command = build_training_command(spec, yolo_executable=Path("yolo"))
    assert "imgsz=960" in command
    assert "device=mps" in command
    assert "optimizer=AdamW" in command
    assert "lr0=0.001" in command
    assert "seed=26" in command
    assert "name=warm-start" in command
```

- [x] **Step 2: 학습 전 lock·pin·schema 검증 테스트 작성**

재호출·동시호출은 YOLO 실행 전에 거부하고, dataset/checkpoint/source code SHA가 바뀌면 학습을 시작하지 않는다.

- [x] **Step 3: RED 확인 후 warm-only runner 구현**

clean-reference spec은 만들지 않는다. output manifest는 dataset SHA, checkpoint SHA, command, 시작/종료, return code, best.pt SHA, results.csv SHA를 기록한다.

- [x] **Step 4: Task 4 검증**

Run: `uv run pytest -q tests/test_run_yolo26n_v24_gate_reuse.py`

Expected: PASS.

- [ ] **Step 5: commit checkpoint**

별도 승인 시에만 runner와 테스트를 stage/commit한다.

---

### Task 5: validation threshold freeze와 동결 평가

**Files:**
- Create: `scripts/evaluate_yolo26n_v24_gate_reuse.py`
- Create: `tests/test_evaluate_yolo26n_v24_gate_reuse.py`

**Interfaces:**
- Consumes: v2.4 dataset, v2.4 best.pt, v2.3 fixed metrics, Owner external diagnostic60 snapshot.
- Produces: validation ledger, threshold freeze, internal test ledger, external60 ledger, comparison report.
- API: `select_v24_threshold(records, precision_floor=0.60) -> dict[str, object]`.
- API: `classify_v24_result(internal_metrics, external_metrics) -> str`.

- [x] **Step 1: threshold와 평가 순서 테스트 작성**

```python
def test_threshold_uses_validation_only_and_fixed_precision_floor():
    freeze = select_v24_threshold(fixture_validation_predictions(), precision_floor=0.60)
    assert freeze["precision"] >= 0.60
    assert freeze["status"] == "V24_THRESHOLD_FROZEN"


def test_test_and_external_are_blocked_before_freeze():
    with pytest.raises(PermissionError):
        build_fixed_evaluation_plan(freeze=None)
```

- [x] **Step 2: 채택·실패 판정 테스트 작성**

```python
def test_adoption_requires_all_internal_and_external_gates():
    assert classify_v24_result(
        {"recall": 0.64, "precision": 0.61},
        {"recall": 0.43, "false_positive": 20, "duplicate": 4},
    ) == "V24_TRAINED_DEVELOPMENT_ONLY"
    assert classify_v24_result(
        {"recall": 0.63, "precision": 0.61},
        {"recall": 0.43, "false_positive": 20, "duplicate": 4},
    ) == "V24_GATE_REUSE_REJECTED"
```

- [x] **Step 3: one-shot ledger·freeze·comparison 구현**

각 phase는 started lock을 inference 전에 O_EXCL/0600으로 만들고, input bytes/checkpoint/freeze를 pre/post 검증한다. internal test와 external60은 각각 정확히 한 번만 inference한다.

- [x] **Step 4: Task 5 검증**

Run: `uv run pytest -q tests/test_evaluate_yolo26n_v24_gate_reuse.py tests/test_evaluate_yolo26n_owner_media_external.py`

Expected: PASS.

- [ ] **Step 5: commit checkpoint**

별도 승인 시에만 evaluator와 테스트를 stage/commit한다.

---

### Task 6: Mac mini 실행, 독립 검증, 최종 보고

**Files:**
- Create: `reports/yolo26n-gate-operational-reuse-v24/README.md`
- Modify: `docs/superpowers/specs/2026-08-13-yolo26n-gate-operational-reuse-v24-design.md`
- Modify: `docs/decision-gate.md`

**Interfaces:**
- Consumes: Task 1~5 reviewed code SHA와 private pins.
- Produces: 비민감 비교 report, 채택/기각/shortage 판정, Owner에게 필요한 사람 감사 요청.

- [ ] **Step 1: reviewed source snapshot을 Mac mini에 배포하고 코드 SHA 검증**

`git archive <reviewed-sha>`로 새 private 실행 디렉터리를 만들고, source-commit과 실행 파일 SHA를 local `git show` bytes와 대조한다. 기존 repo·runtime·GME worker는 바꾸지 않는다.

- [ ] **Step 2: candidate preflight와 60장 audit bundle 생성**

Expected status는 `V24_GATE_AUDIT_REQUIRED` 또는 최소 수량 미달 시 `V24_GATE_REUSE_SHORTAGE`다. shortage면 학습을 실행하지 않는다.

- [ ] **Step 3: Owner 감사 결과 수신 후 dataset materialization**

감사에서 불일치 0일 때만 v2.4 dataset을 생성한다. 불일치가 있으면 설계대로 전체 positive/negative 재검수 gate를 열고 중단한다.

- [ ] **Step 4: warm-only 학습 실행**

예상 3~4시간. v2.3 warm-start 1,193장이 2시간 9분 걸린 실측을 기준으로, v2.4는 최대 1,831장이라 데이터량 비례 3시간 18분에 artifact 검증 여유를 더했다.

- [ ] **Step 5: validation freeze → internal test → external60 실행**

예상 30~60분. validation precision floor 미달이면 test와 external60을 열지 않는다.

- [ ] **Step 6: 독립 read-only acceptance와 비민감 보고 작성**

manifest/weights/ledger/report SHA, split bytes, counts, DB/R2/service write0을 독립 재계산한다. 개별 source/GT/비밀값은 보고하지 않는다.

- [ ] **Step 7: 전체 검증**

Run:

```bash
uv run pytest -q \
  tests/test_build_yolo26n_gate_operational_candidates_v24.py \
  tests/test_build_yolo26n_owner_dataset_v24.py \
  tests/test_run_yolo26n_v24_gate_reuse.py \
  tests/test_evaluate_yolo26n_v24_gate_reuse.py
uv run pytest -q
git diff --check
```

Expected: 모든 신규·전체 회귀 PASS, diff-check PASS, DB/R2/service mutation audit 0.

- [ ] **Step 8: commit/push checkpoint**

최종 결과를 Owner에게 보고하고 명시적 commit/push 승인을 받은 뒤에만 수행한다.

## 예상시간

| 구간 | 예상 |
|---|---:|
| 계획 고정·Task 1~5 구현·테스트 | 2.5~3.5시간 |
| 후보·lineage preflight·audit bundle | 30~60분 |
| Owner 60장 감사 | 30~60분 |
| v2.4 materialization·독립 검증 | 30~60분 |
| Mac mini warm-only 학습 | 3~4시간 |
| threshold·test·external60·최종 검증 | 30~60분 |
| **자동 구간 합계** | **6.5~9시간** |
| **Owner 감사 포함 정상 합계** | **7~10시간** |
| 정책 불일치로 전체 후보 재검수 시 추가 | **2~4시간 이상** |
