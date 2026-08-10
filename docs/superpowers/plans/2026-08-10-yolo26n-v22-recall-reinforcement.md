# YOLO26n v2.2 Recall Reinforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사람 검수한 hard positive·hard negative를 Dataset v2.1에 추가하고, 재현율 우선 YOLO26n v2.2 후보 두 개를 학습해 새 future holdout 전까지 development-only checkpoint로 보존한다.

**Architecture:** 기존 v2.1 채굴 코드는 역사 기준선으로 먼저 고정하고, v2.2 후보 선택·실행·CVAT 검증·dataset 빌드·학습·threshold 선택을 각각 독립 CLI로 만든다. 모델과 GME는 후보를 찾을 뿐 정답을 만들지 않으며, Mac mini에서는 versioned private artifact만 쓰고 repo·DB·R2·service는 변경하지 않는다.

**Tech Stack:** Python 3.12, uv, pytest, OpenCV, Ultralytics YOLO26n, Supabase read-only, Cloudflare R2 read-only, CVAT, macOS MPS.

## Global Constraints

- Dataset v2.1 기준선은 698장·양성 398장·bbox 426개이며 source·camera-night·이미지 해시 누출 0 상태를 보존한다.
- 후보 목표는 hard-positive signal 220장, hard-negative signal 100장, source당 최대 2장, camera-night당 최대 12장이다.
- `clip_purpose='production'`만 허용하고 `test/`, active system exclusion, quarantine, source missing, media deleted는 제외한다.
- CVAT에는 예측 bbox를 넣지 않으며 Owner가 원본만 보고 bbox 또는 빈 이미지를 확정한다.
- 현재 development holdout 34장·23 bbox는 결과를 동결한 뒤 최종 평가 자격을 영구 상실한다.
- warm-start 60 epoch/patience 15와 clean-start 100 epoch/patience 20을 960px·동일 seed·동일 split로 비교한다.
- threshold는 development set에서 precision 0.60 이상인 지점 중 recall 최대값으로 고정한다.
- future holdout은 이후 production-purpose 120장 이상, 양성·음성 각 60장 이상, 최소 3카메라·6 camera-night다.
- YOLO 결과로 행동·하이라이트·GT·부재·자동 skip/route/삭제를 확정하지 않는다.
- production DB·R2·service·active model·Vercel은 이 계획에서 변경하지 않는다.

---

## File Structure

- `scripts/build_yolo26n_v21_candidate_queue.py`: 이미 검증한 v2.1 source 분류·선택 기준선.
- `scripts/run_yolo26n_v21_candidate_mining.py`: 이미 검증한 v2.1 read-only 채굴 기준선.
- `scripts/build_yolo26n_cvat_dataset.py`: CVAT rectangle을 YOLO dataset으로 바꾸는 공용 기준선.
- `scripts/build_yolo26n_v22_candidate_queue.py`: v2.2 strict positive/negative quota와 source/night cap만 담당.
- `scripts/run_yolo26n_v22_candidate_mining.py`: production eligibility 조회, probe inference, review frame materialization 담당.
- `scripts/validate_yolo26n_v22_cvat_export.py`: 사람 CVAT export의 geometry·sequence·ambiguous 계약 검증 담당.
- `scripts/build_yolo26n_v22_dataset.py`: v2.1과 승인된 v2.2 사람 라벨 병합, group split, leakage audit 담당.
- `scripts/run_yolo26n_v22_training.py`: warm/clean 학습 명령 생성과 run manifest 담당.
- `scripts/select_yolo26n_v22_threshold.py`: prediction ledger에서 precision floor를 지키는 threshold 선택 담당.
- 같은 이름의 `tests/test_*.py`: 각 순수 계약의 RED/GREEN 테스트.

---

### Task 1: v2.1 재사용 도구 기준선 고정

**Files:**
- Add: `scripts/build_yolo26n_v21_candidate_queue.py`
- Add: `scripts/run_yolo26n_v21_candidate_mining.py`
- Add: `scripts/build_yolo26n_cvat_dataset.py`
- Add: `tests/test_build_yolo26n_v21_candidate_queue.py`
- Add: `tests/test_run_yolo26n_v21_candidate_mining.py`
- Add: `tests/test_build_yolo26n_cvat_dataset.py`
- Add: `docs/superpowers/plans/2026-08-10-yolo26n-v21-targeted-reinforcement.md`

**Interfaces:**
- Consumes: 현재 worktree에 이미 존재하는 v2.1 untracked 파일 7개.
- Produces: `CandidatePolicy`, `select_candidate_sources`, `choose_probe_indices`, `choose_review_probe_indices`, `build_dataset`의 tracked 기준선.

- [ ] **Step 1: 기준선 파일만 범위에 있는지 확인**

Run:

```bash
git status --short -- \
  scripts/build_yolo26n_v21_candidate_queue.py \
  scripts/run_yolo26n_v21_candidate_mining.py \
  scripts/build_yolo26n_cvat_dataset.py \
  tests/test_build_yolo26n_v21_candidate_queue.py \
  tests/test_run_yolo26n_v21_candidate_mining.py \
  tests/test_build_yolo26n_cvat_dataset.py \
  docs/superpowers/plans/2026-08-10-yolo26n-v21-targeted-reinforcement.md
```

Expected: 위 7개만 `??`로 표시되고 다른 dirty 파일은 이 Task의 stage 대상이 아니다.

- [ ] **Step 2: 기존 기준선 테스트를 실행**

Run:

```bash
uv run pytest -q \
  tests/test_build_yolo26n_v21_candidate_queue.py \
  tests/test_run_yolo26n_v21_candidate_mining.py \
  tests/test_build_yolo26n_cvat_dataset.py
```

Expected: 15 tests PASS.

- [ ] **Step 3: 안전 계약을 정적으로 확인**

Run:

```bash
rg -n 'insert\(|update\(|upsert\(|delete\(|put_object|copy_object|remove\(' \
  scripts/build_yolo26n_v21_candidate_queue.py \
  scripts/run_yolo26n_v21_candidate_mining.py \
  scripts/build_yolo26n_cvat_dataset.py
```

Expected: DB/R2 write 호출 0건. 로컬 파일 생성용 `write_text`, `copy2`는 허용한다.

- [ ] **Step 4: 기준선만 커밋**

```bash
git add \
  scripts/build_yolo26n_v21_candidate_queue.py \
  scripts/run_yolo26n_v21_candidate_mining.py \
  scripts/build_yolo26n_cvat_dataset.py \
  tests/test_build_yolo26n_v21_candidate_queue.py \
  tests/test_run_yolo26n_v21_candidate_mining.py \
  tests/test_build_yolo26n_cvat_dataset.py \
  docs/superpowers/plans/2026-08-10-yolo26n-v21-targeted-reinforcement.md
git commit -m "test: YOLO26n v2.1 데이터 도구 기준선 고정"
```

---

### Task 2: v2.2 strict candidate policy

**Files:**
- Create: `scripts/build_yolo26n_v22_candidate_queue.py`
- Create: `tests/test_build_yolo26n_v22_candidate_queue.py`

**Interfaces:**
- Consumes: `CandidateRow = Mapping[str, object]` with `source_ref`, `camera_night`, `camera_id`, `yolo_max_conf`, `yolo_detection_count`, `gme_visible_ratio`, `gme_unknown_ratio`, `gme_max_geckos`.
- Produces: `V22CandidatePolicy`, `classify_v22_candidate(row) -> str`, `select_v22_candidate_sources(rows, policy, excluded_source_refs) -> list[dict[str, object]]`.

- [ ] **Step 1: strict quota와 cap의 실패 테스트 작성**

```python
def test_v22_selection_never_backfills_negative_quota_with_positive_sources():
    policy = V22CandidatePolicy(
        frame_quotas={"hard_positive": 4, "hard_negative": 2},
        frames_per_source=2,
        max_frames_per_camera_night=4,
        seed="owner-v2.2",
    )
    rows = [
        _row("p1", "n1", "c1", gme_max_geckos=1, yolo_detection_count=0),
        _row("p2", "n2", "c2", gme_max_geckos=1, yolo_detection_count=0),
    ]

    selected = select_v22_candidate_sources(rows, policy=policy)

    assert [row["candidate_bucket"] for row in selected] == [
        "hard_positive", "hard_positive"
    ]
    assert sum(row["planned_frame_count"] for row in selected) == 4
```

같은 파일에 다음 assertion을 추가한다.

- excluded source는 절대 재선택하지 않는다.
- 한 source의 `planned_frame_count <= 2`다.
- 같은 camera-night의 frame 합은 12 이하다.
- 입력 순서를 뒤집어도 결과가 동일하다.
- `gme_max_geckos>=2`는 `hard_positive` 안에서 `multi_gecko` stratum tag를 가진다.
- GME가 0이어도 YOLO high-confidence면 `hard_negative` 후보일 뿐 사람 음성 정답으로 저장하지 않는다.

- [ ] **Step 2: 실패 확인**

Run:

```bash
uv run pytest -q tests/test_build_yolo26n_v22_candidate_queue.py
```

Expected: module import failure.

- [ ] **Step 3: 최소 policy 구현**

```python
@dataclass(frozen=True)
class V22CandidatePolicy:
    frame_quotas: Mapping[str, int]
    frames_per_source: int
    max_frames_per_camera_night: int
    seed: str

    def source_quota(self, bucket: str) -> int:
        frames = int(self.frame_quotas[bucket])
        return math.ceil(frames / self.frames_per_source)
```

`select_v22_candidate_sources`는 bucket별 source quota를 따로 채우고 다른 bucket으로 부족분을
backfill하지 않는다. 출력에는 `candidate_bucket`, `strata_tags`, `planned_frame_count`,
`review_required=True`만 추가하고 label·bbox·presence 정답은 넣지 않는다.

- [ ] **Step 4: 테스트 통과 확인**

Run:

```bash
uv run pytest -q \
  tests/test_build_yolo26n_v22_candidate_queue.py \
  tests/test_build_yolo26n_v21_candidate_queue.py
```

Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add scripts/build_yolo26n_v22_candidate_queue.py tests/test_build_yolo26n_v22_candidate_queue.py
git commit -m "feat: YOLO26n v2.2 후보 quota 계약 추가"
```

---

### Task 3: read-only v2.2 candidate mining runner

**Files:**
- Create: `scripts/run_yolo26n_v22_candidate_mining.py`
- Create: `tests/test_run_yolo26n_v22_candidate_mining.py`

**Interfaces:**
- Consumes: `V22CandidatePolicy`, v2.1 source refs·image hashes, Supabase `motion_clips`/`gme_runs`/`motion_clip_system_exclusions`, R2 GET, v2.1 `best.pt`.
- Produces: `probe-sources.private.json`, `analyzed-sources.private.json`, `candidate-manifest.private.json`, `review-index.csv`, `review-frames/`, `cvat-upload.zip`.

- [ ] **Step 1: eligibility와 review frame 테스트 작성**

```python
def test_eligible_clips_excludes_nonproduction_and_active_system_exclusions():
    clips = [
        {"id": "a", "clip_purpose": "production", "r2_key": "terra-clips/clips/a.mp4"},
        {"id": "b", "clip_purpose": "test", "r2_key": "test/b.mp4"},
        {"id": "c", "clip_purpose": "production", "r2_key": "terra-clips/clips/c.mp4"},
    ]
    exclusions = {"c": "quarantined"}

    assert [row["id"] for row in eligible_clips(clips, exclusions)] == ["a"]
```

같은 파일에 다음 테스트를 추가한다.

- `candidate`, `quarantined`, `media_deleted`, `deletion_blocked`는 제외하고 `restored`는 허용한다.
- probe 24개는 endpoint를 피하고 영상 전체에 결정론적으로 분포한다.
- hard positive는 미검출·저신뢰 frame, hard negative는 고신뢰 frame을 먼저 고른다.
- source당 2장, camera-night당 12장 cap을 materialization 뒤에도 다시 검사한다.
- 기존 이미지 exact SHA-256과 source 내부 dHash 근접 중복을 제외한다.
- inventory night cap은 frame 수가 아니라 source 수로 적용하며 `28 sources/night`를 넘기지 않는다.
- inventory는 HP 560/HN 530, 합계 1,090 source의 metadata-only 선택 summary가 exact일 때만
  R2 GET을 시작한다.
- 최종 frame이 중복·unreadable이면 같은 source의 다음 ranked probe, 이후 같은 bucket reserve source로 backfill한다. bucket 간 backfill은 금지한다.
- private manifest는 inventory pool/selection/downloaded/missing과 bucket별 planned/accepted,
  candidate/source exhaustion, night-cap block, decode/imwrite failure, deduplicated/unreadable/shortfall
  집계를 남긴다. source별 probe extraction count는 private analyzed ledger에만 남긴다.
- manifest에 `prediction_boxes_exposed_to_reviewer=False`, `db_write_count=0`, `r2_write_count=0`가 기록된다.

- [ ] **Step 2: 실패 확인**

Run:

```bash
uv run pytest -q tests/test_run_yolo26n_v22_candidate_mining.py
```

Expected: module import failure.

- [ ] **Step 3: pure helper와 CLI 구현**

```python
ACTIVE_EXCLUSION_STATES = {
    "candidate", "quarantined", "media_deleted", "deletion_blocked"
}

def eligible_clips(clips: Iterable[Mapping[str, object]], exclusions: Mapping[str, str]):
    return [
        row for row in clips
        if row.get("clip_purpose") == "production"
        and not str(row.get("r2_key", "")).startswith("test/")
        and exclusions.get(str(row["id"])) not in ACTIVE_EXCLUSION_STATES
    ]
```

CLI는 `inventory`와 `analyze` 두 subcommand로 나눈다. `inventory`는 SELECT와 R2 GET만 수행하고,
`analyze`는 로컬 mp4를 OpenCV로 24-frame probe한 뒤 YOLO prediction ledger만 private JSON에 쓴다.
`VideoCapture.release()`는 `finally`에서 실행한다.

- [ ] **Step 4: 테스트와 write 감사**

Run:

```bash
uv run pytest -q \
  tests/test_run_yolo26n_v22_candidate_mining.py \
  tests/test_build_yolo26n_v22_candidate_queue.py
rg -n 'insert\(|update\(|upsert\(|delete\(|put_object|copy_object' \
  scripts/run_yolo26n_v22_candidate_mining.py
```

Expected: tests PASS, DB/R2 write call 0건.

- [ ] **Step 5: 커밋**

```bash
git add scripts/run_yolo26n_v22_candidate_mining.py tests/test_run_yolo26n_v22_candidate_mining.py
git commit -m "feat: YOLO26n v2.2 read-only 후보 채굴기 추가"
```

---

### Task 4: Mac mini 후보 320장 준비

**Files:**
- Create on Mac mini private artifact: `/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3/`
- No repository file changes.

`attempt-20260810-owner-v1/`은 인공 shortage를 기록한 실패 provenance로 동결한다. 파일을
덮어쓰거나 그 review ZIP을 CVAT에 올리지 않는다.
`attempt-20260810-owner-v2/`는 실행 계약을 모두 통과했지만 final HP 103/HN 27의 genuine
shortage로 끝난 provenance다. 이 artifact도 수정하거나 CVAT에 올리지 않는다.

v3 inventory HP 560/HN 530과 `28 sources/night`는 v2 accepted yield의 one-sided 95% LCB로
final HP 220/HN 100을 보수적으로 계획한 bounded scale-up이며, metadata preflight에서 해당
선택이 가능함을 확인한 값이다. classifier, 24 probe/source, final quota, dedup과 review cap은
바꾸지 않는다.

runner는 `--output`을 위 v3 절대경로 하나로만 허용한다. inventory 시작 시 `code/` 외 artifact가
있으면 외부 read 전에 거부한다. analyze는 정상 inventory 산출물인 `code/`,
`inventory-selection.private.json`, `probe-sources.private.json`, `source-clips/`만 허용하며
`probe-frames/`, `review-frames/`, analyzed ledger, review index, candidate manifest, CVAT ZIP 등
부분 실행 산출물이 하나라도 있으면 덮어쓰지 않고 중단한다.
shortage 집계의 `candidate_exhausted`는 후보 풀이 끝났을 때 남은 frame quota 수이고,
`source_exhausted`는 probe를 다 소비하고도 source cap을 못 채운 source 수다.

**Interfaces:**
- Consumes: Task 3 exact source commit, v2.1 dataset artifact, v2.1 checkpoint, Mac mini reporter read credentials.
- Produces: `V22_CANDIDATE_QUEUE_READY` or exact quota shortage report.

- [ ] **Step 1: exact code snapshot을 private artifact로 복사**

Run from MacBook worktree:

```bash
SOURCE_SHA=$(git rev-parse HEAD)
git archive --format=tar --add-virtual-file="source-commit.txt:$SOURCE_SHA" "$SOURCE_SHA" \
  scripts/build_yolo26n_v22_candidate_queue.py \
  scripts/run_yolo26n_v22_candidate_mining.py | \
ssh baek-end@baeg-endeuui-Macmini.local \
  'mkdir -p /Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3/code && tar -x -C /Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3/code'
```

Expected: remote `code/source-commit.txt`가 local `git rev-parse HEAD`와 일치한다. 이 과정은
`/Users/baek-end/petcam-lab`을 수정하지 않는다.

- [ ] **Step 2: inventory 실행**

Run on Mac mini using the reporter venv that provides `supabase`:

```bash
RUN=/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3
PYTHON=/Users/baek-end/petcam-nightly-reporter/.venv/bin/python
PYTHONPATH="$RUN/code" "$PYTHON" \
  "$RUN/code/scripts/run_yolo26n_v22_candidate_mining.py" inventory \
  --output "$RUN" \
  --reporter-repo /Users/baek-end/petcam-nightly-reporter \
  --cutoff 2026-07-15T00:00:00Z \
  --existing-selection /Users/baek-end/private-rba/yolo26n-v21-targeted/attempt-20260810-owner-v2/candidate-manifest.private.json \
  --existing-review-csv /Users/baek-end/private-rba/yolo26n-owner-dataset-v21/attempt-20260810-owner-final-v1/combined-review.private.csv \
  --inventory-max-sources 1090 \
  --probe-hard-positive-sources 560 \
  --probe-hard-negative-sources 530 \
  --probe-max-sources-per-night 28 \
  --seed owner-v2.2
```

Expected: R2 GET 전에 `inventory-selection.private.json`과 stdout에 source ID 없는 pool/selection
집계가 기록되고 HP 560/HN 530 exact가 아니면 `V22_INVENTORY_SELECTION_SHORTAGE`로 멈춘다.
exact일 때만 download가 시작되며 DB/R2 write는 0이다.

- [ ] **Step 3: v2.1 model로 24-frame probe와 review queue 생성**

```bash
RUN=/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3
VENV='/Users/baek-end/Library/Application Support/petcam/yolo26n-day-night-gecko-detection/private/mps-smoke-20260809T191651+0900/venv'
PYTHONPATH="$RUN/code" "$VENV/bin/python" \
  "$RUN/code/scripts/run_yolo26n_v22_candidate_mining.py" analyze \
  --output "$RUN" \
  --model /Users/baek-end/private-rba/yolo26n-owner-dataset-v21/attempt-20260810-owner-final-v1/runs/baseline-960-v21/weights/best.pt \
  --existing-images /Users/baek-end/private-rba/yolo26n-owner-dataset-v21/attempt-20260810-owner-final-v1/input-images \
  --probe-frames-per-source 24 \
  --review-frames-per-source 2 \
  --hard-positive-frames 220 \
  --hard-negative-frames 100 \
  --max-frames-per-night 12 \
  --imgsz 960 \
  --inference-conf 0.05 \
  --seed owner-v2.2
```

Expected: 중복·unreadable frame은 같은 source의 다음 probe와 같은 bucket reserve source로
backfill한다. exact 320장 또는 bucket별 planned/accepted, candidate/source exhaustion,
night-cap block, requested/readable/decode/imwrite failure, deduplicated/unreadable/shortfall이
fail-closed로 보고되며 shortage를 다른 bucket으로 채우지 않는다.

- [ ] **Step 4: 독립 queue preflight**

Run:

```bash
RUN=/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3
python3 -c 'import json,pathlib; p=pathlib.Path("/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260811-owner-v3/candidate-manifest.private.json"); d=json.loads(p.read_text()); assert d["prediction_boxes_exposed_to_reviewer"] is False; assert d["db_write_count"] == 0; assert d["r2_write_count"] == 0; assert d["inventory_selection_counts"] == {"hard_positive": 560, "hard_negative": 530}; assert d["bucket_counts"] == {"hard_positive": 220, "hard_negative": 100}; print(d["status"], d["review_frame_count"], d["bucket_counts"], d["materialization_counts"])'
```

Expected: `V22_CANDIDATE_QUEUE_READY`, review count 320, hard-positive 220, hard-negative 100,
source/night cap 위반 0. 조건을 못 채우면 `V22_CANDIDATE_QUEUE_SHORTAGE`로 멈춘다.

---

### Task 5: CVAT export fail-closed validator

**Files:**
- Create: `scripts/validate_yolo26n_v22_cvat_export.py`
- Create: `tests/test_validate_yolo26n_v22_cvat_export.py`

**Interfaces:**
- Consumes: `candidate-manifest.private.json`, CVAT annotation snapshot JSON, `owner-review.private.csv` with optional `ambiguous=true`.
- Produces: `V22_HUMAN_REVIEW_ACCEPTED` summary and accepted sequence set; ambiguous rows are excluded, not converted to negatives.

- [ ] **Step 1: validator failure tests 작성**

```python
def test_ambiguous_frame_is_excluded_instead_of_becoming_negative(tmp_path: Path):
    result = validate_export(
        candidate_manifest=_manifest(["H0001", "H0002"]),
        snapshot=_snapshot({"H0001": [], "H0002": []}),
        review_rows=[
            {"sequence": "H0001", "ambiguous": "false"},
            {"sequence": "H0002", "ambiguous": "true"},
        ],
    )

    assert result.accepted_sequences == ("H0001",)
    assert result.ambiguous_sequences == ("H0002",)
```

같은 파일에 sequence 누락·중복, label 2개 이상, rectangle 이외 shape, 음수·역전·화면 밖 bbox,
manifest 밖 frame, image hash mismatch를 모두 rejection으로 테스트한다.

- [ ] **Step 2: 실패 확인**

Run:

```bash
uv run pytest -q tests/test_validate_yolo26n_v22_cvat_export.py
```

Expected: module import failure.

- [ ] **Step 3: immutable result type과 validator 구현**

```python
@dataclass(frozen=True)
class CvatValidationResult:
    accepted_sequences: tuple[str, ...]
    ambiguous_sequences: tuple[str, ...]
    positive_image_count: int
    negative_image_count: int
    box_count: int
```

`validate_export`는 모든 frame을 먼저 검사한 뒤 결과를 반환한다. 한 frame이라도 계약을 어기면
부분 결과를 쓰지 않고 `ValueError`로 종료한다.

- [ ] **Step 4: 테스트 통과와 커밋**

```bash
uv run pytest -q tests/test_validate_yolo26n_v22_cvat_export.py
git add scripts/validate_yolo26n_v22_cvat_export.py tests/test_validate_yolo26n_v22_cvat_export.py
git commit -m "feat: YOLO26n v2.2 CVAT export 검증 추가"
```

**Human gate:** Task 4 queue가 준비되면 Owner가 CVAT에서 320장 이하를 검수한다. 이 단계에서만
`V22_HUMAN_REVIEW_REQUIRED`를 보고하고 자동 학습을 시작하지 않는다.

---

### Task 6: Dataset v2.2 builder와 leakage audit

**Files:**
- Create: `scripts/build_yolo26n_v22_dataset.py`
- Create: `tests/test_build_yolo26n_v22_dataset.py`

**Interfaces:**
- Consumes: v2.1 `combined-owner-snapshot.private.json`/`combined-review.private.csv`/`input-images`, Task 5 accepted CVAT export.
- Produces: versioned YOLO dataset, `manifest.private.json`, `development-exclusions.private.json`, `data.yaml`.

- [ ] **Step 1: merge·split·leakage RED tests 작성**

```python
def test_v22_builder_never_places_one_camera_night_in_multiple_splits(tmp_path: Path):
    manifest = build_v22_dataset(
        base_records=_base_records(),
        reinforcement_records=_reinforcement_records(),
        output_dir=tmp_path / "dataset",
        seed=26,
    )

    split_by_night = {}
    for row in manifest["records"]:
        split_by_night.setdefault(row["camera_night_group"], set()).add(row["split"])
    assert all(len(splits) == 1 for splits in split_by_night.values())
```

추가 테스트:

- accepted image만 병합하고 ambiguous는 없다.
- SHA-256 duplicate는 동일/다른 split 모두 fail-closed다.
- 현재 V-sequence 34개는 `final_holdout_eligible=False`다.
- 모든 empty negative에 빈 `.txt` label이 생성된다.
- bbox class는 0 하나뿐이고 geometry는 `(0,1]` 범위다.
- manifest의 image/positive/box 합계가 실제 파일과 일치한다.

- [ ] **Step 2: 실패 확인**

Run:

```bash
uv run pytest -q tests/test_build_yolo26n_v22_dataset.py
```

Expected: module import failure.

- [ ] **Step 3: builder 구현**

```python
def build_v22_dataset(
    *,
    base_records: Iterable[DatasetRecord],
    reinforcement_records: Iterable[DatasetRecord],
    output_dir: Path,
    seed: int = 26,
) -> dict[str, object]:
    records = tuple(base_records) + tuple(reinforcement_records)
    assert_unique_hashes(records)
    assignments = choose_group_splits(records, seed=seed)
    return materialize_yolo_dataset(records, assignments, output_dir)
```

manifest에는 `schema=yolo26n-owner-dataset-v22`, `evaluation_tier=development`,
`future_holdout_required=True`, base/new 수, strata 수, source/camera-night 수, 모든 입력 digest를 기록한다.

- [ ] **Step 4: 테스트 통과와 커밋**

```bash
uv run pytest -q \
  tests/test_build_yolo26n_v22_dataset.py \
  tests/test_build_yolo26n_cvat_dataset.py
git add scripts/build_yolo26n_v22_dataset.py tests/test_build_yolo26n_v22_dataset.py
git commit -m "feat: YOLO26n v2.2 데이터셋 빌더 추가"
```

---

### Task 7: 두 후보 학습과 threshold freeze

**Files:**
- Create: `scripts/run_yolo26n_v22_training.py`
- Create: `scripts/select_yolo26n_v22_threshold.py`
- Create: `tests/test_run_yolo26n_v22_training.py`
- Create: `tests/test_select_yolo26n_v22_threshold.py`

**Interfaces:**
- Consumes: v2.2 `data.yaml`, v2.1 `best.pt`, official YOLO26n pretrained checkpoint, development predictions.
- Produces: `warm-start/weights/best.pt`, `clean-reference/weights/best.pt`, run manifests, `threshold-freeze.private.json`.

- [ ] **Step 1: training command RED tests 작성**

```python
def test_training_specs_freeze_identical_data_and_different_initializers():
    specs = build_training_specs(data_yaml=Path("dataset/data.yaml"), seed=26)

    assert specs["warm-start"].epochs == 60
    assert specs["warm-start"].patience == 15
    assert specs["clean-reference"].epochs == 100
    assert specs["clean-reference"].patience == 20
    assert {spec.imgsz for spec in specs.values()} == {960}
    assert {spec.seed for spec in specs.values()} == {26}
```

명령 생성 테스트는 warm-start만 v2.1 checkpoint를 쓰고 clean-reference는 official checkpoint를
쓰며, 두 run 모두 같은 data.yaml·batch 2·device mps·workers 0을 쓰는지 확인한다.

- [ ] **Step 2: threshold RED tests 작성**

```python
def test_select_threshold_maximizes_recall_above_precision_floor():
    rows = [
        ThresholdMetric(0.10, precision=0.55, recall=0.90),
        ThresholdMetric(0.20, precision=0.61, recall=0.82),
        ThresholdMetric(0.30, precision=0.70, recall=0.75),
    ]

    assert select_threshold(rows, precision_floor=0.60).threshold == 0.20
```

precision floor를 만족하는 threshold가 없으면 성공값을 만들지 않고 `ThresholdSelectionError`로
종료하는 테스트도 추가한다.

- [ ] **Step 3: 실패 확인**

Run:

```bash
uv run pytest -q \
  tests/test_run_yolo26n_v22_training.py \
  tests/test_select_yolo26n_v22_threshold.py
```

Expected: module import failures.

- [ ] **Step 4: training runner와 threshold selector 구현**

```python
@dataclass(frozen=True)
class TrainingSpec:
    name: str
    initializer: Path
    epochs: int
    patience: int
    imgsz: int = 960
    seed: int = 26

def select_threshold(
    rows: Iterable[ThresholdMetric], *, precision_floor: float = 0.60
) -> ThresholdMetric:
    eligible = [row for row in rows if row.precision >= precision_floor]
    if not eligible:
        raise ThresholdSelectionError("precision floor is unreachable")
    return max(eligible, key=lambda row: (row.recall, row.precision, row.threshold))
```

runner는 각 subprocess 종료코드, 시작/종료 시각, source commit, input manifest SHA, checkpoint SHA,
PyTorch MPS deterministic warning을 run manifest에 기록한다.

- [ ] **Step 5: 테스트 통과와 커밋**

```bash
uv run pytest -q \
  tests/test_run_yolo26n_v22_training.py \
  tests/test_select_yolo26n_v22_threshold.py
git add \
  scripts/run_yolo26n_v22_training.py \
  scripts/select_yolo26n_v22_threshold.py \
  tests/test_run_yolo26n_v22_training.py \
  tests/test_select_yolo26n_v22_threshold.py
git commit -m "feat: YOLO26n v2.2 두 후보 학습과 threshold 동결"
```

---

### Task 8: development report와 future holdout gate

**Files:**
- Create in private artifact: `REPORT.md`
- Create in private artifact: `metrics.private.json`
- Modify after evidence exists: `specs/next-session.md`

**Interfaces:**
- Consumes: v2.0/v2.1/v2.2 prediction ledgers, fixed thresholds, source/camera-night audit.
- Produces: `V22_TRAINED_DEVELOPMENT_ONLY`, `V22_FUTURE_HOLDOUT_READY`, or `V22_ADOPTION_CANDIDATE`.

- [ ] **Step 1: development 비교 실행**

두 v2.2 후보와 v2.1을 같은 development set에 실행한다. threshold-freeze는 development prediction만
읽고, future holdout 파일이나 GT에는 접근하지 않는다.

- [ ] **Step 2: development report 검증**

보고서에는 모델별 precision/recall/mAP50/mAP50-95, fixed threshold, confusion 원수,
작은 개체·가림·쳇바퀴·다개체·야간 원수, 학습시간, checkpoint SHA를 적는다. development 결과만
있으면 제목과 상태를 `V22_TRAINED_DEVELOPMENT_ONLY`로 고정한다.

- [ ] **Step 3: future pool 자격만 read-only 계산**

이후 production-purpose 영상에서 학습·후보·CVAT source와 camera-night가 겹치지 않는 표본을 센다.
120장, 양성 60, 음성 60, 최소 3카메라·6 camera-night 중 하나라도 부족하면 표본을 만들지 않고
부족한 수만 보고한다.

- [ ] **Step 4: future holdout one-shot 평가**

조건 충족 뒤 별도 TEST-SHEET와 Owner 승인을 받아 v2.1과 선택된 v2.2 후보를 한 번만 평가한다.
recall≥0.70, v2.1 대비 +10%p, precision≥0.60, leakage/decode/geometry 오류 0을 모두 만족할 때만
`V22_ADOPTION_CANDIDATE`로 기록한다.

- [ ] **Step 5: SOT 갱신과 커밋**

```bash
git add specs/next-session.md
git commit -m "docs: YOLO26n v2.2 개발 결과 기록"
```

active model, production worker, DB, R2, Vercel 변경은 이 커밋에 포함하지 않는다.

---

## Verification Matrix

| Gate | Evidence |
|---|---|
| Candidate eligibility | production only, active exclusion 0, existing source/hash overlap 0 |
| Candidate independence | source≤2 frames, camera-night≤12 frames, exact SHA duplicate 0 |
| Human truth | predicted bbox exposure false, ambiguous excluded, geometry violations 0 |
| Dataset | base/new counts exact, camera-night cross-split leakage 0, file/manifest totals exact |
| Training | two initializers, same dataset/seed/imgsz, successful exit, checkpoint SHA present |
| Threshold | development-only selection, precision floor 0.60, frozen JSON digest |
| Final adoption | new future holdout 120+, positive/negative 60+, 3 cameras, 6 nights, all metric gates pass |
| Production safety | DB/R2/service/active model/Vercel writes 0 |
