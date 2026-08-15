# YOLO26n v2.5 Future Holdout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** v2.5 선택 이후 새 production 영상으로 prediction-blind 200장 holdout을 만들고 v2.4/v2.5를 one-shot 비교한다.

**Architecture:** readiness/inventory, blind reserve/finalization, CVAT normalization, one-shot evaluation을 독립 CLI로 분리한다. 모든 단계는 immutable private artifact와 SHA lineage로 연결하고, 모델 출력은 사람 GT가 동결된 뒤에만 사용한다.

**Tech Stack:** Python 3.12, uv, Pillow, OpenCV, Ultralytics, Supabase read-only, R2 exact GET, pytest.

## Global Constraints

- final 목표는 양성 100 + 음성 100이며 자동으로 60/60으로 축소하지 않는다.
- v2.5 selection freeze 뒤 `clip_purpose=production`만 후보가 된다.
- source 2장, camera-night 24장, 최소 3 camera/6 nights다.
- inference는 `threshold=.20`, `imgsz=960`, `conf=.001`, `nms_iou=.70`, `max_det=50`, match IoU `.50`이다.
- DB/R2/service/git/production model/GME/labeling web write·deploy는 0이다.
- 기존 v2.5 development artifact와 Owner external60은 읽기 전용으로 보존한다.

---

### Task 1: Freeze와 readiness inventory

**Files:**
- Create: `scripts/build_yolo26n_v25_future_holdout.py`
- Create: `tests/test_build_yolo26n_v25_future_holdout.py`
- Modify: `docs/superpowers/plans/2026-08-15-yolo26n-v25-future-holdout.md`

**Interfaces:**
- Produces: `FreezeContract`, `FutureSource`, `build_readiness(...) -> dict[str, object]`
- Artifact: `readiness.private.json` with status `WAITING_FOR_FUTURE_MEDIA` or `V25_FUTURE_MEDIA_READY`

- [x] **Step 1: cutoff·purpose·pagination RED 작성**

```python
def test_readiness_uses_only_post_freeze_production_sources():
    result = build_readiness(freeze=freeze_fixture(), rows=mixed_rows())
    assert result["eligible_source_count"] == 1
    assert result["db_write_count"] == result["r2_get_count"] == 0

def test_zero_rows_is_waiting_not_an_error():
    assert build_readiness(freeze=freeze_fixture(), rows=[])["status"] == "WAITING_FOR_FUTURE_MEDIA"
```

- [x] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_build_yolo26n_v25_future_holdout.py -k readiness`
Expected: import 또는 함수 부재로 FAIL.

- [x] **Step 3: strict freeze/readiness 구현**

`FreezeContract`는 v2.5 freeze raw SHA, selected checkpoint SHA, cutoff UTC, threshold `.20`, inference 계약을 검증한다. `build_readiness`는 post-cutoff production row만 정렬하고 camera/night/source capacity aggregate만 반환한다.

- [x] **Step 4: pagination drift·bool count·write audit 테스트 추가**

```python
def test_readiness_rejects_count_drift_before_r2_get():
    with pytest.raises(ValueError, match="snapshot count"):
        collect_metadata(FakePagedClient(changing_count=True), freeze_fixture())
```

- [x] **Step 5: 검증·커밋**

Run: `uv run pytest -q tests/test_build_yolo26n_v25_future_holdout.py`
Expected: PASS.

```bash
git add scripts/build_yolo26n_v25_future_holdout.py tests/test_build_yolo26n_v25_future_holdout.py docs/superpowers/plans/2026-08-15-yolo26n-v25-future-holdout.md
git commit -m "feat: YOLO v2.5 future readiness 계약"
```

### Task 2: Historical fingerprint와 blind reserve

**Files:**
- Modify: `scripts/build_yolo26n_v25_future_holdout.py`
- Modify: `tests/test_build_yolo26n_v25_future_holdout.py`

**Interfaces:**
- Produces: `build_exposure_fingerprints(...)`, `select_reserve(...)`, `materialize_reserve(...)`
- Artifact: `historical-exclusions.private.json`, `reserve-manifest.private.json`, `presence-screen.csv`, `cvat-presence.zip`

- [x] **Step 1: overlap·cap·blind RED 작성**

```python
def test_reserve_excludes_all_exposed_sha_and_near_duplicate():
    chosen = select_reserve(rows(), exposed_sha={SHA_A}, exposed_dhash={DHASH_A})
    assert all(row.image_sha256 != SHA_A for row in chosen)
    assert all(hamming(row.dhash64, DHASH_A) > 2 for row in chosen)

def test_public_reserve_has_no_model_or_source_fields(tmp_path):
    publish_presence_bundle(reserve_fixture(), tmp_path)
    assert forbidden_tokens(tmp_path / "cvat-presence.zip") == set()
```

- [x] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_build_yolo26n_v25_future_holdout.py -k 'reserve or exposure'`
Expected: FAIL.

- [x] **Step 3: exact SHA + source-local dHash dedup 구현**

v2.5 dataset 1,963장과 protected ledgers의 SHA/source/night/derivation을 private exclusion ledger로 만든다. reserve는 seeded rank로 source 2, night 24 cap을 적용하며 reverse-input 결과가 같아야 한다.

- [x] **Step 4: JPEG normalization과 blind ZIP 구현**

R2 exact GET 뒤 EXIF 없는 JPEG를 만들고 `P0001..P0400`과 `sequence,presence`만 공개한다. private manifest에 원본 lineage와 공개 JPEG SHA를 묶는다.

- [x] **Step 5: 검증·커밋**

Run: `uv run pytest -q tests/test_build_yolo26n_v25_future_holdout.py`
Expected: PASS.

```bash
git add scripts/build_yolo26n_v25_future_holdout.py tests/test_build_yolo26n_v25_future_holdout.py
git commit -m "feat: YOLO v2.5 blind future reserve"
```

### Task 3: Presence screen과 exact final holdout

**Files:**
- Modify: `scripts/build_yolo26n_v25_future_holdout.py`
- Modify: `tests/test_build_yolo26n_v25_future_holdout.py`

**Interfaces:**
- Produces: `build_final_holdout(reserve, presence_csv, positive_count=100, negative_count=100)`
- Artifact: `future-holdout-manifest.private.json`, `review-index.csv`, `cvat-upload.zip`

- [x] **Step 1: exact 100/100·ambiguous RED 작성**

```python
def test_final_requires_exact_100_positive_and_100_negative():
    with pytest.raises(ValueError, match="balanced holdout shortage"):
        build_final_holdout(reserve_199(), presence_99_100())

def test_ambiguous_is_never_negative():
    final = build_final_holdout(reserve_220(), presence_with_ambiguous())
    assert all(row.presence != "ambiguous" for row in final)
```

- [x] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_build_yolo26n_v25_future_holdout.py -k final`
Expected: FAIL.

- [x] **Step 3: deterministic 200장 finalization 구현**

final은 `H0001..H0200` 순서, 3 camera/6 nights, source/night cap을 다시 검사한다. bbox prediction은 포함하지 않는다.

- [x] **Step 4: no-overwrite·partial cleanup 테스트**

두 output 중 하나라도 publish 실패하면 READY manifest가 없어야 하고 기존 output은 덮어쓰지 않는다.

- [x] **Step 5: 검증·커밋**

Run: `uv run pytest -q tests/test_build_yolo26n_v25_future_holdout.py`
Expected: PASS.

```bash
git add scripts/build_yolo26n_v25_future_holdout.py tests/test_build_yolo26n_v25_future_holdout.py
git commit -m "feat: YOLO v2.5 balanced future holdout"
```

### Task 4: CVAT export validator

**Files:**
- Create: `scripts/validate_yolo26n_v25_future_holdout_export.py`
- Create: `tests/test_validate_yolo26n_v25_future_holdout_export.py`

**Interfaces:**
- Produces: `normalize_future_export(...) -> dict[str, object]`
- Artifact: `future-holdout-gt.private.json`, `future-holdout-acceptance.private.json`

- [ ] **Step 1: wrong job/label/shape/SHA RED 작성**

```python
@pytest.mark.parametrize("mutation", ["wrong_label", "rotation", "track", "sha", "dimension", "partial"])
def test_export_rejects_contract_mutation(mutation):
    with pytest.raises(ValueError):
        normalize_future_export(**fixture(mutation))
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_validate_yolo26n_v25_future_holdout_export.py`
Expected: FAIL.

- [ ] **Step 3: single-read SHA·static bbox normalizer 구현**

단일 gecko class, axis-aligned static rectangle, 보이는 개체별 0..N bbox만 허용한다. negative는 0 bbox, ambiguous는 입력에 존재할 수 없다.

- [ ] **Step 4: TOCTOU·0600·atomic publish 테스트**

manifest/JPEG/CVAT bytes는 같은 read bytes로 hash+parse/decode하며 scan 전후 file state drift를 거부한다.

- [ ] **Step 5: 검증·커밋**

Run: `uv run pytest -q tests/test_validate_yolo26n_v25_future_holdout_export.py`
Expected: PASS.

```bash
git add scripts/validate_yolo26n_v25_future_holdout_export.py tests/test_validate_yolo26n_v25_future_holdout_export.py
git commit -m "feat: YOLO v2.5 future GT 검증기"
```

### Task 5: v2.4/v2.5 one-shot evaluator

**Files:**
- Create: `scripts/evaluate_yolo26n_v25_future_holdout.py`
- Create: `tests/test_evaluate_yolo26n_v25_future_holdout.py`

**Interfaces:**
- Produces: `run_candidate_once(...)`, `build_future_report(...)`
- Artifact: 두 prediction ledger, `future-comparison-report.private.json`

- [ ] **Step 1: freeze-before-test·one-shot·metric RED 작성**

```python
def test_future_evaluation_uses_frozen_point_two_for_both_candidates():
    report = build_future_report(v24_ledger(), v25_ledger(), freeze_fixture())
    assert report["metrics"]["v2.4"]["threshold"] == 0.20
    assert report["metrics"]["v2.5"]["threshold"] == 0.20

def test_second_inference_claim_is_rejected_before_model_load(tmp_path):
    run_candidate_once(**valid_args(tmp_path))
    with pytest.raises(FileExistsError):
        run_candidate_once(**valid_args(tmp_path))
```

- [ ] **Step 2: RED 확인**

Run: `uv run pytest -q tests/test_evaluate_yolo26n_v25_future_holdout.py`
Expected: FAIL.

- [ ] **Step 3: pinned bytes inference와 independent report 구현**

검증한 checkpoint bytes로 model을 만들고 검증한 JPEG bytes의 PIL 객체만 inference에 전달한다. TP/FP/FN/duplicate와 낮/밤 subgroup을 저장한다.

- [ ] **Step 4: 채택 gate 구현**

precision `.60`, recall `.70`, v2.4 대비 recall `+3%p`, subgroup recall 후퇴 `<=5%p`, lineage 위반 0을 모두 만족할 때만 `V25_FUTURE_HOLDOUT_SHADOW_CANDIDATE`다.

- [ ] **Step 5: 검증·커밋**

Run: `uv run pytest -q tests/test_evaluate_yolo26n_v25_future_holdout.py`
Expected: PASS.

```bash
git add scripts/evaluate_yolo26n_v25_future_holdout.py tests/test_evaluate_yolo26n_v25_future_holdout.py
git commit -m "feat: YOLO v2.5 future one-shot 평가"
```

### Task 6: 전체 회귀와 Mac mini readiness

**Files:**
- Modify: `docs/superpowers/plans/2026-08-15-yolo26n-v25-future-holdout.md`

**Interfaces:**
- Consumes: Task 1~5 CLI와 frozen v2.5 private artifact
- Produces: first immutable `WAITING_FOR_FUTURE_MEDIA` 또는 blind presence queue

- [ ] **Step 1: 관련 테스트와 전체 회귀 실행**

Run:

```bash
uv run pytest -q \
  tests/test_build_yolo26n_v25_future_holdout.py \
  tests/test_validate_yolo26n_v25_future_holdout_export.py \
  tests/test_evaluate_yolo26n_v25_future_holdout.py
uv run pytest -q
```

Expected: scoped와 전체 PASS.

- [ ] **Step 2: mutation audit**

Run: `rg -n "insert|update|upsert|delete|put_object|copy_object|service" scripts/*v25_future_holdout.py`
Expected: DB/R2/service mutation call 0.

- [ ] **Step 3: Mac mini clean archive preflight**

reviewed commit archive, selection freeze, v2.4/v2.5 checkpoint, dataset/protected artifact SHA를 검증하고 fresh private attempt만 만든다.

- [ ] **Step 4: readiness 실행**

현재 예상 결과는 production clip `0`, status `WAITING_FOR_FUTURE_MEDIA`, R2 GET/write `0`이다. 이후 새 production metadata가 들어왔을 때만 reserve 단계로 이동한다.

- [ ] **Step 5: 최종 검수·보고**

presence queue READY면 이미지 수와 예상 사람 시간을 보고한다. 부족하면 aggregate만 보고하고 예전 영상을 섞지 않는다.
