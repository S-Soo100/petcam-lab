# YOLO26n v2.4b 후처리 선택·Future Holdout 구현 계획

> **For Codex:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**목표:** v2.4 checkpoint는 다시 학습하지 않고 validation 153장에서 confidence/NMS를 고정한 뒤, 그 규칙을 확정한 이후의 새 영상으로 만든 blind future holdout 120장에 정확히 한 번 평가해 Gate/GME shadow 후보 여부를 판정한다.

**구조:** 작업을 `후처리 선택 → 새 영상 선별 → Owner bbox → export 검증 → one-shot 평가`로 분리한다. 기존 internal test 151장과 Owner 외부 진단 60장은 역사 원장으로 봉인하고 어떤 선택·재평가에도 사용하지 않는다. 새 시험지는 양성 60/음성 60을 보장하려고 prediction을 보여주지 않는 짧은 presence 선별을 먼저 거친 뒤, 최종 120장만 CVAT bbox 작업으로 보낸다.

**기술:** Python 3.12, uv, pytest, Ultralytics YOLO26n, Pillow, OpenCV, Supabase/R2 read-only inventory, CVAT export JSON/CSV, SHA-256 provenance.

**정본 설계:** `docs/superpowers/specs/2026-08-13-yolo26n-v24b-postprocess-future-holdout-design.md`

**고정 입력:**

- v2.4 code commit: `194807d0a9f50cdafac4cfe3970b8707d873c308`
- v2.4 best checkpoint SHA-256: `3c9f752b9369b30be4083f837676271640cfd1f4cbfa6027382a380efc4212c4`
- validation: 153장
- 기존 test 151장·Owner 외부 60장: 봉인, v2.4b 실행 입력 금지
- inference: `imgsz=960`, `max_det=50`, `device=mps`, 수집 confidence `0.001`
- bbox match IoU: `0.50`

---

## Task 1: 60/60 시험지 생성을 위한 blind presence 선별 계약 보강

정확히 양성 60장과 음성 60장을 만들려면 bbox 작업 전에 실제 presence를 알아야 한다. 모델 예측으로 정답을 대신하지 않고, Owner가 예측을 보지 않은 상태로 빠르게 `positive/negative/ambiguous`만 선별한다. 최종 CVAT에는 선별이 끝난 120장만 들어간다.

**Files:**

- Modify: `docs/superpowers/specs/2026-08-13-yolo26n-v24b-postprocess-future-holdout-design.md`
- Test: 문서 placeholder/계약 grep

**Step 1: 설계 문서에 선별 단계를 명시한다**

`5. 새 future holdout 120장`과 `6. 사람 검수 흐름` 사이에 다음 계약을 추가한다.

- 시스템은 final 120장이 아니라 최대 240장의 blind reserve pool을 먼저 만든다.
- 화면/CSV 이름은 `P0001..P0240`이고 모델 박스·confidence·Gate/GME 결과를 숨긴다.
- Owner 입력은 `sequence,presence`이며 값은 `positive`, `negative`, `ambiguous` 셋뿐이다.
- 결정론적 선택기가 caps를 지키면서 positive 60, negative 60을 고른다.
- 공급량이 모자라면 `V24B_FUTURE_HOLDOUT_SHORTAGE`; 예측으로 정답을 채우지 않는다.
- final CVAT에는 `H0001..H0120`만 들어가고 positive는 bbox 1개 이상, negative는 bbox 0개여야 한다.

**Step 2: 용어와 순서가 일관적인지 검사한다**

Run:

```bash
rg -n "P0001|positive|negative|ambiguous|H0001|60장|240장|SHORTAGE" \
  docs/superpowers/specs/2026-08-13-yolo26n-v24b-postprocess-future-holdout-design.md
```

Expected: blind presence 선별, exact 60/60, final CVAT 120, shortage가 모두 한 흐름으로 나온다.

---

## Task 2: 후처리 metric과 결정론적 selector 구현

**Files:**

- Create: `scripts/select_yolo26n_v24b_postprocess.py`
- Create: `tests/test_select_yolo26n_v24b_postprocess.py`

**Step 1: 실패하는 selector 테스트를 작성한다**

다음을 고정한다.

- threshold grid: `0.05..0.80`, step `0.05`
- NMS grid: `.40,.45,.50,.55,.60,.65,.70`
- one-to-one IoU match `.50`
- TP/FP/FN, precision, recall, positive-image recall, duplicate prediction 계산
- 후보 gate: precision `>=.60`, recall `>=.65`, duplicate `<=` baseline `(conf=.20,nms=.70)`
- tie-break: duplicate 최소 → recall 최대 → FP 최소 → confidence 최대 → NMS 최소
- 후보가 없으면 `V24B_POSTPROCESS_SHORTAGE`
- bool/NaN/inf/count mismatch/duplicate sequence/잘못된 SHA는 모두 reject

예시 테스트:

```python
def test_selector_uses_exact_tie_break_order():
    metrics = [
        metric(nms=.60, conf=.25, fp=8, recall=.70, duplicate=2),
        metric(nms=.50, conf=.30, fp=8, recall=.70, duplicate=2),
    ]
    selected = select_postprocess_candidate(metrics, baseline_duplicate=3)
    assert (selected.confidence, selected.nms_iou) == (.30, .50)


def test_selector_fails_closed_when_no_candidate_meets_floor():
    result = build_postprocess_freeze(...)
    assert result["status"] == "V24B_POSTPROCESS_SHORTAGE"
    assert "selected" not in result
```

**Step 2: 테스트가 RED인지 확인한다**

Run:

```bash
uv run pytest -q tests/test_select_yolo26n_v24b_postprocess.py
```

Expected: import/file 없음으로 FAIL.

**Step 3: 순수 함수만 최소 구현한다**

주요 인터페이스:

```python
@dataclass(frozen=True)
class PostprocessMetric:
    nms_iou: float
    confidence: float
    tp: int
    fp: int
    fn: int
    duplicate: int
    precision: float
    recall: float
    positive_image_recall: float


def score_prediction_ledger(
    ledger: Mapping[str, object], *, confidence: float, match_iou: float = 0.50
) -> PostprocessMetric: ...


def select_postprocess_candidate(
    metrics: Sequence[PostprocessMetric], *, baseline_duplicate: int
) -> PostprocessMetric | None: ...


def build_postprocess_freeze(...) -> dict[str, object]: ...
```

기존 `scripts/evaluate_yolo26n_v22.py`의 deterministic greedy one-to-one IoU 의미를 재사용하되 기존 v2.2 파일과 역사 결과는 수정하지 않는다.

**Step 4: GREEN 확인**

Run:

```bash
uv run pytest -q tests/test_select_yolo26n_v24b_postprocess.py
uv run python -m py_compile scripts/select_yolo26n_v24b_postprocess.py
```

Expected: PASS.

---

## Task 3: validation NMS grid one-shot runner와 freeze 구현

**Files:**

- Create: `scripts/run_yolo26n_v24b_postprocess.py`
- Create: `tests/test_run_yolo26n_v24b_postprocess.py`
- Modify: `scripts/select_yolo26n_v24b_postprocess.py`

**Step 1: one-shot·provenance RED 테스트를 작성한다**

테스트할 계약:

- exact v2.4 checkpoint SHA와 dataset manifest SHA를 실행 전에 검사
- validation 153장만 허용; path가 test/external이면 inference 전에 reject
- NMS별 exact output path와 `.locks/predict-nms-XX.started.private.json`
- final output/lock을 inference 전에 O_EXCL로 선점해 재호출·동시 호출 차단
- checkpoint는 검증한 bytes에서 0600 private pinned copy를 만들고 model을 먼저 load
- 이미지는 bytes 1회 읽기 → SHA·decode·dimension 검증 → 같은 PIL 객체를 inference에 전달
- result order를 입력 index와 exact bind
- 입력 checkpoint/images/manifest/code는 pre/post SHA가 같아야 함
- NMS별 ledger 7개가 모두 검증된 뒤에만 freeze 생성
- private artifact/lock exact 0600, no-overwrite, partial publish 없음
- DB/R2/service/git write 호출 0

**Step 2: RED 확인**

```bash
uv run pytest -q tests/test_run_yolo26n_v24b_postprocess.py
```

**Step 3: runner를 구현한다**

CLI:

```bash
uv run python scripts/run_yolo26n_v24b_postprocess.py predict-grid \
  --dataset-manifest /absolute/dataset-manifest.private.json \
  --expected-dataset-manifest-sha256 218f32d745e407470c661d97cfe0035e27614cc8f7921ae61835050a0dcd827f \
  --checkpoint /absolute/best.pt \
  --expected-checkpoint-sha256 3c9f752b9369b30be4083f837676271640cfd1f4cbfa6027382a380efc4212c4 \
  --output /absolute/private/v24b-postprocess-attempt-v1

uv run python scripts/run_yolo26n_v24b_postprocess.py freeze \
  --output /absolute/private/v24b-postprocess-attempt-v1
```

`predict-grid`는 7개 NMS 원장을 만들고, 각 원장에는 checkpoint/dataset/code/inference contract/input frame hashes를 기록한다. `freeze`는 원장을 다시 검증하고 Task 2 selector로 단 하나의 조합만 고정한다.

**Step 4: 공격·회귀 테스트를 통과시킨다**

```bash
uv run pytest -q \
  tests/test_select_yolo26n_v24b_postprocess.py \
  tests/test_run_yolo26n_v24b_postprocess.py
uv run python -m py_compile \
  scripts/select_yolo26n_v24b_postprocess.py \
  scripts/run_yolo26n_v24b_postprocess.py
```

Expected: PASS. 테스트에는 ABA checkpoint/image 변조, reversed result order, second-call-before-inference, output publish failure cleanup이 포함돼야 한다.

---

## Task 4: future 영상 read-only inventory와 blind presence reserve pool 구현

**Files:**

- Create: `scripts/build_yolo26n_v24b_future_holdout.py`
- Create: `tests/test_build_yolo26n_v24b_future_holdout.py`
- Modify: `docs/superpowers/plans/2026-08-13-yolo26n-v24b-postprocess-future-holdout.md`
- Modify: `docs/superpowers/specs/2026-08-13-yolo26n-v24b-postprocess-future-holdout-design.md`

**Step 1: 순수 선택기 RED 테스트를 작성한다**

주요 구조:

```python
@dataclass(frozen=True)
class FutureFrame:
    source_ref: str
    camera_id: str
    camera_night: str
    recorded_at: str
    image_sha256: str
    dhash: int
    local_name: str


def choose_blind_reserve_pool(
    frames: Sequence[FutureFrame], *, seed: str, limit: int = 240
) -> tuple[FutureFrame, ...]: ...


def choose_exact_holdout(
    pool: Sequence[FutureFrame],
    presence_rows: Sequence[Mapping[str, str]],
    *,
    positive_count: int = 60,
    negative_count: int = 60,
) -> tuple[FutureFrame, ...]: ...
```

테스트 계약:

- freeze timestamp 이후 영상만
- `clip_purpose=production`만; test/firmware-dev 제외
- 기존 dataset, v2.4 test, external60와 source/image/night/derivation overlap 0
- 실제 pinned dataset/test/external artifact와 별도 protected-lineage SOT를 exact bijection으로 join
- prepare input independent SHA, 0600/non-symlink/single-read/pre-post identity, duplicate JSON key 거부
- protected lineage가 없거나 불완전하면 `V24B_PROTECTED_LINEAGE_SHORTAGE`, normalized output 0
- pool 최대 240, source당 2, night당 20, camera>=3, night>=6, same-source dHash `>2`
- input reverse 순서에서도 selection 동일
- `presence` exact string 셋과 1행/sequence
- exact positive60/negative60을 caps와 함께 만족
- ambiguous는 final에서 제외
- 가능한데 greedy가 실패하는 overlapping-night 반례를 max-flow/feasibility-preserving selection으로 해결
- 부족하면 artifact ZIP/CVAT 0, status `V24B_FUTURE_HOLDOUT_SHORTAGE`

**Step 2: RED 확인**

```bash
uv run pytest -q tests/test_build_yolo26n_v24b_future_holdout.py
```

**Step 3: phase별 CLI를 구현한다**

```bash
# 실제 역사 artifact에는 source/night/derivation이 없으므로 보호된 lineage SOT와 먼저 join한다.
uv run python scripts/build_yolo26n_v24b_future_holdout.py prepare-overlap \
  --role dataset \
  --artifact /absolute/pinned/dataset-v24-manifest.private.json \
  --expected-artifact-sha256 "$DATASET_ARTIFACT_SHA256" \
  --lineage-sot /absolute/protected/dataset-lineage.private.json \
  --expected-lineage-sha256 "$DATASET_LINEAGE_SHA256" \
  --output /absolute/pinned/normalized/dataset-overlap.private.json

uv run python scripts/build_yolo26n_v24b_future_holdout.py prepare-overlap \
  --role internal-test151 \
  --artifact /absolute/pinned/internal-test151-predictions.private.json \
  --expected-artifact-sha256 "$INTERNAL151_ARTIFACT_SHA256" \
  --lineage-sot /absolute/protected/internal-test151-lineage.private.json \
  --expected-lineage-sha256 "$INTERNAL151_LINEAGE_SHA256" \
  --output /absolute/pinned/normalized/internal-test151-overlap.private.json

uv run python scripts/build_yolo26n_v24b_future_holdout.py prepare-overlap \
  --role owner-external60 \
  --artifact /absolute/pinned/owner-external60-predictions.private.json \
  --expected-artifact-sha256 "$EXTERNAL60_ARTIFACT_SHA256" \
  --lineage-sot /absolute/protected/owner-external60-lineage.private.json \
  --expected-lineage-sha256 "$EXTERNAL60_LINEAGE_SHA256" \
  --output /absolute/pinned/normalized/owner-external60-overlap.private.json

# 세 normalized overlap ledger가 모두 준비된 뒤에만 DB metadata SELECT를 시작한다.
uv run python scripts/build_yolo26n_v24b_future_holdout.py inventory \
  --freeze /absolute/v24b-postprocess-freeze.private.json \
  --output /absolute/private/v24b-future-attempt-v1 \
  --dataset-source-json /absolute/pinned/normalized/dataset-overlap.private.json \
  --internal-test151-source-json /absolute/pinned/normalized/internal-test151-overlap.private.json \
  --owner-external60-source-json /absolute/pinned/normalized/owner-external60-overlap.private.json

# blind P#### reserve materialization
uv run python scripts/build_yolo26n_v24b_future_holdout.py materialize-pool \
  --output /absolute/private/v24b-future-attempt-v1

# Owner가 presence-screen.csv를 채운 뒤 exact H#### 120장/CVAT bundle 생성
uv run python scripts/build_yolo26n_v24b_future_holdout.py build-final \
  --output /absolute/private/v24b-future-attempt-v1 \
  --presence-screen /absolute/presence-screen.csv
```

`prepare-overlap`은 artifact와 protected lineage를 `(sequence,image_sha256)` exact bijection으로만
연결한다. source/night/derivation을 prediction이나 경로에서 추측하지 않는다. protected lineage가
missing/extra/mismatch/incomplete이면 `V24B_PROTECTED_LINEAGE_SHORTAGE`로 멈추고 normalized output을
만들지 않는다. 각 prepare 시도는 입력을 열기 전에 0600 one-shot lock을 선점한다.

`inventory`는 metadata exact quota가 불가능하면 R2 GET 전에 멈춘다. `materialize-pool`은 source MP4 bytes SHA와 추출 JPEG SHA/dimension을 private ledger로 고정한다. 또한 freeze raw bytes의 exact SHA를 inventory `freeze_sha256`에서 pool ledger `postprocess_freeze_sha256`으로 이어받는다. `build-final`은 이 값을 검증해 private manifest의 같은 필드로 보존하고, final 120장에 prediction box를 넣지 않은 generic `H0001..H0120`, `review-index.csv`, `cvat-upload.zip`, manifest를 원자적으로 만든다. Owner-facing ZIP/CSV에는 freeze SHA를 넣지 않는다.

**Step 4: GREEN 확인**

```bash
uv run pytest -q tests/test_build_yolo26n_v24b_future_holdout.py
uv run python -m py_compile scripts/build_yolo26n_v24b_future_holdout.py
```

---

## Task 5: final 120장 CVAT export validator 구현

**Files:**

- Create: `scripts/validate_yolo26n_v24b_future_holdout_export.py`
- Create: `tests/test_validate_yolo26n_v24b_future_holdout_export.py`

**Step 1: strict export validator RED 테스트를 작성한다**

기존 `scripts/validate_yolo26n_v22_cvat_export.py`의 single-read·ctime·static rectangle 방어를 재사용한다. 다음은 v2.4b 전용으로 추가한다.

- manifest exact schema/status, raw manifest SHA independent pin
- exact `H0001..H0120`, image set/hash/dimension/order
- exact label `{id:1,name:"gecko"}`
- static axis-aligned rectangle만, score/source/track/attributes/rotation 등 금지 필드 fail-closed
- positive 선별 60장은 bbox `>=1`, negative 60장은 bbox `==0`
- multiple gecko는 여러 bbox 허용
- ambiguous 0; 발견 시 final accept 금지하고 reserve 보충 요구
- camera>=3, night>=6, source<=2, night<=20, same-source dHash `>2`
- input directory scan 전후 name/dev/inode/size/mtime/ctime 및 same bytes hash/decode
- normalized snapshot과 acceptance summary를 둘 다 0600/no-overwrite/atomic publish

**Step 2: RED 확인**

```bash
uv run pytest -q tests/test_validate_yolo26n_v24b_future_holdout_export.py
```

**Step 3: validator와 CLI를 구현한다**

```bash
uv run python scripts/validate_yolo26n_v24b_future_holdout_export.py \
  --candidate-manifest /absolute/future-holdout-manifest.private.json \
  --expected-manifest-sha256 "$INDEPENDENT_MANIFEST_SHA256" \
  --review-index /absolute/private/review-index.csv \
  --expected-review-index-sha256 "$INDEPENDENT_REVIEW_INDEX_SHA256" \
  --snapshot /absolute/cvat-normalized-snapshot.json \
  --owner-ambiguous /absolute/ambiguous.csv \
  --review-frames-dir /absolute/review-frames \
  --normalized-output /absolute/private/future-holdout-gt.private.json \
  --summary-output /absolute/private/future-holdout-acceptance.private.json
```

성공 status는 `V24B_FUTURE_HOLDOUT_ACCEPTED`다.

**Step 4: GREEN·회귀 확인**

```bash
uv run pytest -q \
  tests/test_validate_yolo26n_v24b_future_holdout_export.py \
  tests/test_validate_yolo26n_v22_cvat_export.py
uv run python -m py_compile scripts/validate_yolo26n_v24b_future_holdout_export.py
```

---

## Task 6: future holdout one-shot evaluator와 shadow 판정 구현

**Files:**

- Create: `scripts/evaluate_yolo26n_v24b_future_holdout.py`
- Create: `tests/test_evaluate_yolo26n_v24b_future_holdout.py`

**Step 1: 평가 gate RED 테스트를 작성한다**

고정 판정:

- box precision `>=.60`
- box recall `>=.60`
- positive-image recall `>=.60`
- false-positive negative images `<=6/60`
- duplicate prediction `<=4`
- integrity/overlap/one-shot/write 위반 0

통과 status는 `V24B_SHADOW_CANDIDATE`, 실패 status는 `V24B_FUTURE_HOLDOUT_REJECTED`다. 실패 후 같은 holdout으로 threshold/NMS를 바꾸는 CLI는 만들지 않는다.

다음 공격 테스트를 포함한다.

- freeze/GT/checkpoint/code SHA 위조
- 다른 checkpoint 또는 다른 NMS/conf 주입
- bool/NaN/inf/malformed prediction/box OOB/negative area
- result 순서 교환
- checkpoint/image ABA
- test output 재호출·동시 호출 시 predictor 호출 0
- report publish 실패 시 ledger-only partial 0
- DB/R2/service/GME/labeling web write 호출 0

**Step 2: RED 확인**

```bash
uv run pytest -q tests/test_evaluate_yolo26n_v24b_future_holdout.py
```

**Step 3: one-shot evaluator를 구현한다**

```bash
uv run python scripts/evaluate_yolo26n_v24b_future_holdout.py \
  --freeze /absolute/v24b-postprocess-freeze.private.json \
  --expected-freeze-sha256 "$INDEPENDENT_FREEZE_SHA256" \
  --holdout-manifest /absolute/future-holdout-manifest.private.json \
  --expected-holdout-manifest-sha256 "$INDEPENDENT_HOLDOUT_MANIFEST_SHA256" \
  --holdout-gt /absolute/future-holdout-gt.private.json \
  --checkpoint /absolute/best.pt \
  --output /absolute/private/v24b-future-attempt-v1/evaluation-v1
```

검증한 checkpoint bytes에서 model을 load하고 검증한 JPEG bytes에서 만든 PIL 객체만 inference에 쓴다. ledger와 report에는 checkpoint/freeze/holdout/GT/code SHA, inference contract, 원시 count, TP/FP/FN, duplicate, positive/negative image metric, gate 결과를 기록한다.

**Step 4: GREEN 확인**

```bash
uv run pytest -q tests/test_evaluate_yolo26n_v24b_future_holdout.py
uv run python -m py_compile scripts/evaluate_yolo26n_v24b_future_holdout.py
```

---

## Task 7: 전체 회귀·보안 감사·실행 handoff 고정

**Files:**

- Create: `docs/superpowers/plans/2026-08-13-yolo26n-v24b-postprocess-future-holdout-handoff.md`
- Modify: `docs/superpowers/specs/2026-08-13-yolo26n-v24b-postprocess-future-holdout-design.md`
- Modify: `docs/superpowers/plans/2026-08-13-yolo26n-v24b-postprocess-future-holdout.md`

**Step 1: 전체 관련 테스트를 실행한다**

```bash
uv run pytest -q \
  tests/test_select_yolo26n_v24b_postprocess.py \
  tests/test_run_yolo26n_v24b_postprocess.py \
  tests/test_build_yolo26n_v24b_future_holdout.py \
  tests/test_validate_yolo26n_v24b_future_holdout_export.py \
  tests/test_evaluate_yolo26n_v24b_future_holdout.py \
  tests/test_validate_yolo26n_v22_cvat_export.py \
  tests/test_evaluate_yolo26n_v22.py

uv run pytest -q
```

Expected: 모든 신규·전체 회귀 PASS. 기존 skip은 이유가 유지돼야 한다.

**Step 2: 정적 안전 감사를 한다**

```bash
uv run python -m py_compile \
  scripts/select_yolo26n_v24b_postprocess.py \
  scripts/run_yolo26n_v24b_postprocess.py \
  scripts/build_yolo26n_v24b_future_holdout.py \
  scripts/validate_yolo26n_v24b_future_holdout_export.py \
  scripts/evaluate_yolo26n_v24b_future_holdout.py

git diff --check
rg -n "insert\(|update\(|upsert\(|delete\(|put_object|copy_object|os\.remove|shutil\.move" \
  scripts/*v24b*.py
```

Expected: syntax/diff PASS. 외부 DB/R2/service mutation API 0. 로컬 private artifact의 원자적 생성·cleanup만 허용한다.

**Step 3: bootstrap/final handoff를 두 단계로 분리한다**

freeze는 Task 8 Step 1이 만들어야 하므로 이 시점에는 exact freeze SHA를 쓸 수 없다. `PENDING`이나
`<sha>`를 유효 pin 또는 실행 승인으로 표현하지 않는다. tracked handoff 문서는 전달 이력과 절차만
기록하며 validator manifest 자체가 아니다. validator는 manifest의 `commit_sha`가 execution repo의
현재 HEAD와 같고 plan/design이 그 commit에 있어야 하므로, self-referential tracked manifest commit을
`HANDOFF_OK`로 만들 수 없다.

1. 승인 범위의 구현·plan/design을 **implementation commit I**로 먼저 commit한다. 이 commit은 아직
   freeze artifact를 주장하지 않는다.
2. 그 다음 tracked handoff 기록 문서를 **tracking commit H**로 별도 commit한다. H는 I의 exact 40자리
   SHA와 아래 절차를 기록하지만 validator 대상 manifest가 아니다. Mac mini runtime은 H가 아니라 I를
   checkout해야 한다.
3. read-only preflight에서 checkpoint artifact 1개의 SHA-256은
   `3c9f752b9369b30be4083f837676271640cfd1f4cbfa6027382a380efc4212c4`, dataset manifest의 SHA-256은
   `218f32d745e407470c661d97cfe0035e27614cc8f7921ae61835050a0dcd827f`이고 mode는 `0600`이며 v1/v2 attempt
   bytes가 동일함을 확인했다.
   하지만 현재 Mac mini checkout은 unrelated dirty이고 implementation commit은 remote에 없으므로 바꾸거나
   sync하지 않는다. clean isolated `/Users/baek-end/petcam-lab` checkout이 I에 존재하기 전 bootstrap 상태는
   `PENDING_CLEAN_IMPLEMENTATION_CHECKOUT`다. 이는 Step 1 실행 승인이 아니다.
4. 그 조건이 충족됐을 때만 I checkout의 root/HEAD/clean 상태를 shell precheck로 확인한 뒤 I checkout 밖의
   private 경로에 untracked bootstrap manifest를 만들고 `verify_agent_handoff.py`를 실행한다. bootstrap은
   **Task 8 Step 1의 validation grid/freeze 생성만**
   허용하며, Task 8 Step 2 이후를 허용하지 않는다.
5. Step 1이 shortage 없이 single freeze를 publish하면 raw bytes SHA-256을 독립 계산한다. final도 같은
   root/HEAD/clean-I shell precheck를 다시 통과해야 한다. 그 뒤 actual lowercase 64-hex dataset/freeze SHA와
   raw bytes를 shell에서 strict 검증하고, 그 값이 본문과 exact 일치하는 untracked final manifest/addendum을
   새로 만든 뒤 validator를 실행한다. 이 두 pin이 정확히 일치한 final handoff만 Task 8 Step 2 이후
   read-only 흐름을 허용한다.

runtime contract는 private approved attempt root의 환경만 쓴다. shared uv environment, production
checkout, git, service, DB/R2에는 쓰지 않는다. Mac mini에 repository/shared environment의 Ultralytics가
없으므로 다음 exact command로만 일회성 isolated dependency를 쓴다. `ATTEMPT_ROOT`는 사전에 승인된
private absolute attempt root여야 하며, 아직 경로가 없다면 상태는 `PENDING_APPROVED_ATTEMPT_ROOT`다.

```bash
ATTEMPT_ROOT=/absolute/approved-private/v24b-postprocess-attempt-v1
EXECUTION_REPO=/Users/baek-end/petcam-lab
EXPECTED_I=e822f289b38b61d2d29bbd26370be20874e1eb82
set -eu
test "$(git -C "$EXECUTION_REPO" rev-parse --show-toplevel)" = "$EXECUTION_REPO"
test "$(git -C "$EXECUTION_REPO" rev-parse HEAD)" = "$EXPECTED_I"
test -z "$(git -C "$EXECUTION_REPO" status --porcelain)"
cd "$EXECUTION_REPO"
env YOLO_CONFIG_DIR="$ATTEMPT_ROOT/yolo-config" \
  uv run --isolated --with 'ultralytics==8.4.118' python \
  scripts/run_yolo26n_v24b_postprocess.py predict-grid \
  --dataset-manifest /absolute/private/dataset-manifest.private.json \
  --expected-dataset-manifest-sha256 218f32d745e407470c661d97cfe0035e27614cc8f7921ae61835050a0dcd827f \
  --checkpoint /absolute/private/best.pt \
  --expected-checkpoint-sha256 3c9f752b9369b30be4083f837676271640cfd1f4cbfa6027382a380efc4212c4 \
  --output "$ATTEMPT_ROOT"
env YOLO_CONFIG_DIR="$ATTEMPT_ROOT/yolo-config" \
  uv run --isolated --with 'ultralytics==8.4.118' python \
  scripts/run_yolo26n_v24b_postprocess.py freeze --output "$ATTEMPT_ROOT"
```

`runtime_kind`은 validator가 허용하는 `oneshot`이고, `runtime_host`는
`baeg-endeuui-Macmini.local`, `runtime_label`은 `yolo26n-v24b-postprocess`로 적는다. forbidden scope는
old test151/external60, DB/R2 write, service, git, production이며 local approved private artifact 생성만
예외다. `HANDOFF_OK`는 실제 clean I checkout에서 위 validator가 출력한 경우에만 보고한다.

**Step 4: commit 순서와 검증 상태를 보존한다**

I에는 구현과 plan/design만, H에는 tracked handoff 기록 문서만 명시 stage한다. H의 존재나 PENDING
문구로 validator 통과를 주장하지 않는다. H 이후에도 Mac mini clean checkout/transport와 artifact pin이
없으면 최종 상태는 `BLOCKED_RUNTIME_HANDOFF_INPUTS`; production checkout, git, shared environment를
수정해 우회하지 않는다.

---

## Task 8: 승인된 순서로 실제 연구 실행

**Files:**

- Private artifacts only under Mac mini approved attempt roots
- No tracked source modification during execution

**Step 1: validation 후처리 조합을 고정한다**

1. Mac mini에서 implementation commit/code-file/checkpoint/dataset pin을 독립 검증한다.
2. NMS 7개 validation ledger를 각각 1회 생성한다.
3. metric table을 독립 재계산한다.
4. 후보가 있으면 freeze SHA를 별도 승인한다.
5. 후보가 없으면 `V24B_POSTPROCESS_SHORTAGE`로 멈춘다.

**Step 2: 새 영상 공급량을 read-only preflight한다**

1. freeze 이후 production clip만 조회한다.
2. 기존 모든 dataset/test/external source와 overlap을 제거한다.
3. 3 cameras/6 nights/source·night caps가 가능한지 R2 GET 전에 계산한다.
4. 부족하면 `V24B_FUTURE_HOLDOUT_SHORTAGE`로 알리고 기다린다.

**Step 3: 사람 작업 1 — blind presence 선별을 요청한다**

시스템이 `P####` frame과 `presence-screen.csv`를 준비한다. 사용자는 각 행에 다음 중 하나만 입력한다.

- `positive`: 게코가 확실히 보임
- `negative`: 게코가 확실히 없음
- `ambiguous`: 판단 불가

예측값·박스·source identity는 보여주지 않는다.

**Step 4: final 120장과 CVAT task를 만든다**

exact 60/60과 독립성 caps를 통과할 때만 `H0001..H0120` bundle을 만든다. CVAT task는 gecko 단일 class, prediction prefill 없음으로 생성한다.

**Step 5: 사람 작업 2 — bbox 검수를 요청한다**

사용자는 positive 60장에 visible gecko별 bbox를 만들고 negative 60장은 bbox 0개로 둔다. 애매한 frame은 제출 전에 제외·reserve 대체한다.

**Step 6: export를 동결하고 one-shot 평가한다**

1. export validator와 독립 리뷰를 통과시킨다.
2. TEST-SHEET manifest/GT SHA를 동결한다.
3. exact checkpoint·postprocess 조합을 1회 실행한다.
4. metric을 독립 재계산한다.
5. `V24B_SHADOW_CANDIDATE` 또는 `V24B_FUTURE_HOLDOUT_REJECTED`를 보고한다.

**Step 7: shadow 후보 이후에도 production은 건드리지 않는다**

통과 결과는 별도 Gate/GME shadow 통합 설계의 입력일 뿐이다. active model 교체, 자동 route/absence/delete/behavior 판정은 새 승인 전까지 금지한다.

---

## 완료 조건

- [ ] 기존 v2.4 checkpoint·train 1,458장 불변
- [ ] 기존 test151·external60 선택/재평가 0
- [ ] validation NMS 7개 원장과 단일 freeze가 one-shot/provenance 계약을 통과
- [ ] blind presence 선별 후 exact positive60/negative60
- [ ] final 120장의 카메라/night/source/dHash/overlap 계약 통과
- [ ] Owner CVAT export와 TEST-SHEET SHA 동결
- [ ] future holdout one-shot 평가와 독립 재계산 일치
- [ ] DB/R2/service/git/production model write 0
- [ ] 결과가 shadow 후보와 production 채택을 명확히 구분
