# YOLO26n v2.7 C500G Prospective Dataset Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** C500G 30분 원본을 불변 보존하면서 camera-night 누수 없는 역할 원장, ROI 기반 blind 사람 GT 약 3,000건, v2.6 train-only hard-case와 YOLO v2.7 `DATASET_READY` manifest를 만든다.

**Architecture:** production 원천은 read-only inventory로만 읽고 모든 파생물은 0700 private attempt 아래에 새 파일로 기록한다. metadata-only role freeze를 pixel 접근보다 먼저 수행하고, train-only 600 ROI 파일럿이 full-frame 또는 3-tile publication을 한 번 결정한다. CVAT에는 예측 없는 익명 image queue만 전달하며, 사람 status/bbox를 strict normalize한 뒤 replay와 prospective GT를 lineage·SHA·camera-night gate로 결합한다.

**Tech Stack:** Python 3.12, `uv`, OpenCV, Pillow, JSON/ZIP, CVAT annotation JSON, pytest, 기존 C500G manifest/Supabase/R2 read adapters

**Spec:** `docs/superpowers/specs/2026-08-28-yolo26n-v27-c500g-prospective-dataset-design.md`

## Global Constraints

- Python은 3.12 이상이고 패키지 관리는 `uv`만 쓴다. 새 dependency는 추가하지 않는다.
- 원본 `/Volumes/RAP-C500G/recordings`와 R2 `c500g`, `rap_c500g_recordings`는 read-only다.
- source video, manifest, DB row, R2 object, service, active model, 라벨링 웹을 수정·삭제·격리하지 않는다.
- 모든 파생 artifact는 `storage/yolo26n-v27-c500g/attempts/{attempt_id}/` 아래에만 만들고 directory는 0700, file은 0600으로 쓴다.
- private artifact만 raw `camera_key`, `bundle_id`, source key를 가질 수 있다. 콘솔·공개 report·handoff에는 익명 digest와 aggregate만 쓴다.
- metadata-only inventory·role freeze가 끝나기 전에는 thumbnail/video pixel을 열지 않는다.
- ROI calibration과 600건 파일럿은 `v27_train` 또는 study 이전 calibration frame만 사용한다.
- v2.6 teacher는 6 run, candidate, preprocessing/NMS/threshold/10fps rule, fixed-test가 모두 freeze된 immutable manifest 없이는 0건이다.
- CVAT 첫 pass와 double review에는 prediction bbox·confidence·source identity를 넣지 않는다.
- `uncertain`과 `media_error`는 negative가 아니며 sibling ROI에 둘 중 하나가 있으면 full-frame을 발행하지 않는다.
- split 원자는 `camera-night`이고 가능하면 같은 날짜의 세 camera-night을 date block으로 묶는다.
- v2.6 sealed holdout, v2.7 validation, v2.7 future holdout은 teacher mining에서 제외한다.
- commit은 Owner가 해당 commit을 명시 승인한 뒤에만 한다. push는 별도 승인 없이는 하지 않는다.
- 다른 host·task에 실행을 넘길 때 tracked clean commit과 `HANDOFF_OK`가 먼저다.
- 구현 시작 HEAD에는 이 spec/plan, 최신 v2.6 design/plan, `backend/rap_c500g_manifest.py`와 관련 schema가 함께 tracked 상태여야 한다.
- 이 계획은 v2.6 holdout source/window ledger를 예약하지만 model 평가·성능 판정은 기존 v2.6 Task 10이 소유한다.

## File Map

- `docs/superpowers/specs/2026-08-29-yolo26n-v26-c500g-holdout-clip-unit-addendum.md`: v2.6의 `300 clip`을 C500G 60초 파생 evaluation window로 해석하는 정본.
- `experiments/yolo26n-v27-c500g/TEST-SHEET.md`: role, quota, representation threshold, stop rule 사전등록.
- `scripts/yolo26n_v27_c500g/contracts.py`: enum, immutable record, schema/status 상수와 strict validators.
- `scripts/yolo26n_v27_c500g/private_io.py`: O_EXCL 0600 JSON/JSONL/ZIP write와 SHA helper.
- `scripts/yolo26n_v27_c500g/inventory.py`: 로컬/R2/DB read-only snapshot과 3계층 무결성 대조.
- `scripts/yolo26n_v27_c500g/roles.py`: v2.6 holdout, v2.7 train/validation, date guard 원장.
- `scripts/yolo26n_v27_c500g/roi.py`: ROI profile 검증, crop, 원본 좌표 round-trip.
- `scripts/yolo26n_v27_c500g/sampling.py`: prediction-independent pilot/base selection, exact/dHash/time dedup.
- `scripts/yolo26n_v27_c500g/cvat.py`: 익명 review bundle과 CVAT human export strict normalizer.
- `scripts/yolo26n_v27_c500g/representation.py`: 16px/95%/2% gate와 full-frame/3-tile freeze.
- `scripts/yolo26n_v27_c500g/teacher.py`: frozen v2.6 ledger 검증과 train-only hard-case rank.
- `scripts/yolo26n_v27_c500g/dataset.py`: replay+prospective YOLO dataset build와 누수 감사.
- `scripts/yolo26n_v27_c500g/cli.py`: 각 pure step을 연결하는 subcommand CLI.
- `tests/yolo26n_v27_c500g/`: 위 모듈과 end-to-end fake-video 검증.
- `docs/runbooks/yolo26n-v27-c500g-dataset.md`: 실제 사람 순서, 승인 gate, 복구 절차.

## Artifact Flow

```text
local manifest/video + R2 HEAD snapshot + DB SELECT snapshot
  → source-inventory-v1
  → role-freeze-v1
  → train-only roi-profile-v1
  → pilot-review-queue-v1 (600 + double 60, prediction_visible=false)
  → human-gt-v1
  → representation-decision-v1 (full_frame | roi_3tile)
  → base review/GT + optional frozen-teacher review/GT
  → dataset-v27-manifest-v1 + leakage-report-v1
```

---

### Task 0: v2.6 C500G holdout clip-unit addendum와 TEST-SHEET 고정

**Files:**
- Create: `docs/superpowers/specs/2026-08-29-yolo26n-v26-c500g-holdout-clip-unit-addendum.md`
- Create: `experiments/yolo26n-v27-c500g/TEST-SHEET.md`
- Modify: `docs/decision-gate.md` — append-only addendum link 1개

**Interfaces:**
- Produces: holdout policy `c500g-v26-holdout-window-v1`.
- Produces: 모든 후속 CLI가 pin하는 TEST-SHEET SHA-256.

- [ ] **Step 0: tracked SOT preflight**

  Run:
  ```bash
  git cat-file -e HEAD:docs/superpowers/specs/2026-08-28-yolo26n-v27-c500g-prospective-dataset-design.md
  git cat-file -e HEAD:docs/superpowers/plans/2026-08-29-yolo26n-v27-c500g-prospective-dataset-preparation.md
  git cat-file -e HEAD:backend/rap_c500g_manifest.py
  git diff --quiet && test -z "$(git ls-files --others --exclude-standard)"
  ```
  Expected: exit 0. 하나라도 실패하면 구현·handoff를 시작하지 않는다.

- [ ] **Step 1: addendum에 evaluation unit을 literal로 기록**

  다음 계약을 그대로 쓴다.

  ```yaml
  schema: c500g-v26-holdout-window-v1
  source_role: first_3_post_freeze_complete_camera_nights
  window_duration_sec: 60
  window_alignment: non_overlapping_from_30min_slot_start
  selection: sha256_rank_prediction_independent
  windows_per_camera_night: 100
  total_windows: 300
  bbox_frame_offsets_sec: [12, 24, 36, 48]
  total_bbox_frames: 1200
  clip_presence_review: full_60sec_blind_human
  model_input: frozen_v26_full_frame_10fps
  group_boundary: camera_night_and_30min_source_sha
  reuse_after_open: forbidden
  ```

  30분 원본은 자르거나 다시 쓰지 않고 60초 window는 `(source_sha, start_ms, end_ms)` 파생 좌표로만 정의한다.

- [ ] **Step 2: TEST-SHEET에 역할·quota·중단 규칙 기록**

  `role freeze before pixels`, pilot `600`, warmup `27`, pilot double `60`, total unique judgment target `3000`, total double target `300`, ROI negative `30–40%`, `uncertain+media_error <=10%`, short side `>=16px` fraction `>=0.95`, edge issue `<=0.02`, re-stratification/ROI recalibration maximum `3`을 literal로 고정한다.

- [ ] **Step 3: 문서 계약 검사**

  Run:
  ```bash
  rg -n 'window_duration_sec: 60|total_windows: 300|total_bbox_frames: 1200|role freeze before pixels|pilot.*600|short side' docs/superpowers/specs/2026-08-29-yolo26n-v26-c500g-holdout-clip-unit-addendum.md experiments/yolo26n-v27-c500g/TEST-SHEET.md
  git diff --check
  ```
  Expected: 모든 literal이 한 번 이상 나오고 `git diff --check` exit 0.

- [ ] **Step 4: Owner 승인 gate**

  addendum과 TEST-SHEET을 보여주고 승인 전에는 Task 1로 넘어가지 않는다. 승인 시 두 파일 SHA를 이후 runtime manifest에 기록한다.

- [ ] **Step 5: 승인된 경우에만 commit**

  ```bash
  git add docs/superpowers/specs/2026-08-29-yolo26n-v26-c500g-holdout-clip-unit-addendum.md experiments/yolo26n-v27-c500g/TEST-SHEET.md docs/decision-gate.md
  git commit -m "docs: v2.7 C500G 데이터 준비 계약 고정"
  ```

### Task 1: Strict contract와 private artifact I/O

**Files:**
- Create: `scripts/yolo26n_v27_c500g/__init__.py`
- Create: `scripts/yolo26n_v27_c500g/contracts.py`
- Create: `scripts/yolo26n_v27_c500g/private_io.py`
- Create: `tests/yolo26n_v27_c500g/factories.py`
- Create: `tests/yolo26n_v27_c500g/conftest.py`
- Create: `tests/yolo26n_v27_c500g/test_contracts.py`
- Create: `tests/yolo26n_v27_c500g/test_private_io.py`

**Interfaces:**
- Produces: `Role`, `ReviewStatus`, `Box`, `SourceRecord`, `RoiRect`, `RoiProfile`, `FrameRequest`, `ReviewItem`, `HumanBox`, `TeacherFreeze`, `PredictionRow`, `DatasetRecord`.
- Produces: `strict_object(value, required, optional)`, `sha256_file(path)`, `write_private_json_new(path, value)`, `write_private_zip_new(path, entries)`.
- Produces test builders: `valid_source`, `inventory_7days`, `valid_v26_freeze`, `roles`, `roi_profile`, `request`, `pilot_gt`, `contract`, `queue`, `lineage`, `human_gt`, `protected_ledgers`, `prediction_rows`, `inputs_with_uncertain_sibling`, `dataset_with_cross_role_night`, `inputs_with_mutated_replay`.
- Produces pytest fixtures: `fake_bundle`, `fake_r2`, `fake_db`, `cli_runner`, `fake_c500g_tree`.

- [ ] **Step 1: RED — enum·unknown-key·0600/O_EXCL 테스트 작성**

  ```python
  def test_private_json_is_new_0600_and_not_overwritten(tmp_path):
      path = tmp_path / "artifact.private.json"
      write_private_json_new(path, {"schema": "x", "status": "ok"})
      assert stat.S_IMODE(path.stat().st_mode) == 0o600
      with pytest.raises(FileExistsError):
          write_private_json_new(path, {"schema": "changed"})

  def test_source_record_rejects_unknown_role():
      with pytest.raises(ValueError, match="role"):
          SourceRecord.from_json({**valid_source(), "role": "test"})
  ```

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_contracts.py tests/yolo26n_v27_c500g/test_private_io.py -q`
  Expected: 새 package import 실패.

- [ ] **Step 3: GREEN — 타입과 strict writer 구현**

  ```python
  class Role(StrEnum):
      V26_HOLDOUT = "v26_holdout"
      V26_HOLDOUT_DATE_GUARD = "v26_holdout_date_guard"
      V27_TRAIN = "v27_train"
      V27_VAL = "v27_val"

  class ReviewStatus(StrEnum):
      PRESENT = "present"
      ABSENT = "absent"
      UNCERTAIN = "uncertain"
      MEDIA_ERROR = "media_error"

  def write_private_json_new(path: Path, value: Mapping[str, object]) -> None:
      path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
      payload = canonical_json_bytes(value)
      fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
      try:
          os.fchmod(fd, 0o600)
          os.write(fd, payload)
          os.fsync(fd)
      finally:
          os.close(fd)
  ```

  모든 schema root는 `db_write_count`, `r2_write_count`, `service_write_count`, `git_write_count`를 literal `0`으로 가진다.

- [ ] **Step 4: GREEN 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_contracts.py tests/yolo26n_v27_c500g/test_private_io.py -q`
  Expected: PASS.

- [ ] **Step 5: 승인된 경우에만 commit**

  ```bash
  git add scripts/yolo26n_v27_c500g/__init__.py scripts/yolo26n_v27_c500g/contracts.py scripts/yolo26n_v27_c500g/private_io.py tests/yolo26n_v27_c500g/factories.py tests/yolo26n_v27_c500g/conftest.py tests/yolo26n_v27_c500g/test_contracts.py tests/yolo26n_v27_c500g/test_private_io.py
  git commit -m "feat: v2.7 C500G private artifact 계약"
  ```

### Task 2: USB/R2/DB read-only source inventory

**Files:**
- Create: `scripts/yolo26n_v27_c500g/inventory.py`
- Create: `tests/yolo26n_v27_c500g/test_inventory.py`

**Interfaces:**
- Consumes: C500G `rap-c500g-bundle/v1` local manifest, R2 list/head result, DB SELECT rows.
- Produces: `collect_inventory(local_root, r2_reader, db_reader, *, test_sheet_sha256) -> dict[str, object]` with schema `yolo26n-v27-c500g-source-inventory-v1`.
- Produces: `inventory_public_summary(inventory) -> dict[str, object]` with aggregate only.

- [ ] **Step 1: RED — 3계층 일치와 write 0 spy 테스트 작성**

  ```python
  def test_inventory_requires_local_r2_db_identity(fake_bundle, fake_r2, fake_db):
      result = collect_inventory(fake_bundle.root, fake_r2, fake_db, test_sheet_sha256="a" * 64)
      assert result["status"] == "V27_SOURCE_INVENTORY_READY"
      assert result["storage_match_count"] == 1
      assert fake_r2.write_calls == []
      assert fake_db.write_calls == []

  def test_inventory_reports_sha_mismatch_without_skipping(fake_bundle, fake_r2, fake_db):
      fake_r2.video_sha256 = "b" * 64
      result = collect_inventory(fake_bundle.root, fake_r2, fake_db, test_sheet_sha256="a" * 64)
      assert result["status"] == "V27_SOURCE_INVENTORY_MISMATCH"
      assert result["mismatch_count"] == 1
  ```

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_inventory.py -q`
  Expected: `inventory` module import 실패.

- [ ] **Step 3: GREEN — read-only adapters와 completion 검사 구현**

  local은 `recordings/**/manifest.json`만 scan하고 `video.mp4` size/SHA를 manifest와 재계산한다. R2는 `list_objects_v2`와 `head_object`, DB는 `.select("bundle_id,mode,camera_key,night_date,scheduled_start_utc,partial,duration_sec,codec,width,height,fps,video_size_bytes,video_sha256,video_r2_key,manifest_r2_key,relative_bundle_path,capture_status,upload_status")`만 허용하는 Protocol을 쓴다. production, `partial=false`, duration 허용오차 ±2초, 2880×1620, HEVC/H264, capture/upload 완료, local/R2/DB size·SHA 일치를 record별로 판정한다.

  public summary에는 다음 필드만 둔다.

  ```python
  {
      "schema": "yolo26n-v27-c500g-inventory-summary-v1",
      "expected_slot_count": int,
      "actual_bundle_count": int,
      "complete_camera_night_count": int,
      "missing_slot_count": int,
      "mismatch_count": int,
      "decode_probe_failure_count": int,
  }
  ```

- [ ] **Step 4: GREEN 확인과 write verb scan**

  Run:
  ```bash
  uv run pytest tests/yolo26n_v27_c500g/test_inventory.py -q
  rg -n 'upload_file|put_object|delete_object|upsert|insert|update|delete\(' scripts/yolo26n_v27_c500g/inventory.py
  ```
  Expected: tests PASS, second command has no match.

- [ ] **Step 5: 승인된 경우에만 commit**

  ```bash
  git add scripts/yolo26n_v27_c500g/inventory.py tests/yolo26n_v27_c500g/test_inventory.py
  git commit -m "feat: C500G read-only 원본 inventory"
  ```

### Task 3: Metadata-only role freeze와 v2.6 holdout reservation

**Files:**
- Create: `scripts/yolo26n_v27_c500g/roles.py`
- Create: `tests/yolo26n_v27_c500g/test_roles.py`

**Interfaces:**
- Consumes: `source-inventory-v1`, frozen v2.6 manifest, TEST-SHEET SHA.
- Produces: `freeze_roles(inventory, v26_freeze, *, seed) -> role-freeze-v1`.
- Produces: `assert_pixel_access_allowed(role_manifest, source_ref, allowed_roles) -> None`.

- [ ] **Step 1: RED — first-3, date guard, validation block, pre-freeze 거부 테스트 작성**

  ```python
  def test_role_freeze_reserves_first_three_post_freeze_complete_camera_nights():
      result = freeze_roles(inventory_7days(), valid_v26_freeze(), seed="v27-role-freeze-v1")
      assert count_role(result, "v26_holdout") == 3
      assert all(row["starts_after_v26_freeze"] for row in rows(result, "v26_holdout"))
      assert cross_role_camera_nights(result) == set()

  def test_role_freeze_never_promotes_pre_freeze_night_when_short():
      result = freeze_roles(inventory_with_two_eligible_nights(), valid_v26_freeze(), seed="v27-role-freeze-v1")
      assert result["status"] == "V26_HOLDOUT_SHORTAGE"
      assert count_role(result, "v26_holdout") == 2

  def test_role_freeze_stops_when_fewer_than_three_dev_date_blocks_remain():
      result = freeze_roles(inventory_with_two_dev_date_blocks(), valid_v26_freeze(), seed="v27-role-freeze-v1")
      assert result["status"] == "V27_VAL_SHORTAGE"
  ```

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_roles.py -q`
  Expected: `roles` module import 실패.

- [ ] **Step 3: GREEN — role algorithm 구현**

  v2.6 holdout은 `(scheduled_start_utc, anonymous_camera_digest)` 정렬의 첫 3 complete camera-night이다. 그 날짜의 나머지 camera-night은 `v26_holdout_date_guard`로 두어 v2.7 dev에서 제외한다. 남은 complete date block 수 `n < 3`이면 즉시 `V27_VAL_SHORTAGE`를 반환한다. `n >= 3`일 때만 validation block 수를 `min(max(1, n // 5), n - 2)`로 계산하고 SHA-256 seed rank로 고른다. 나머지 유효 source는 train이며 한 camera-night은 정확히 한 role만 가진다.

- [ ] **Step 4: GREEN 확인과 metadata-only 감사**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_roles.py -q`
  Expected: PASS; fake video의 `open_count == 0`.

- [ ] **Step 5: 승인된 경우에만 commit**

  ```bash
  git add scripts/yolo26n_v27_c500g/roles.py tests/yolo26n_v27_c500g/test_roles.py
  git commit -m "feat: v2.7 camera-night 역할 동결"
  ```

### Task 4: Train-only ROI profile과 좌표 round-trip

**Files:**
- Create: `scripts/yolo26n_v27_c500g/roi.py`
- Create: `tests/yolo26n_v27_c500g/test_roi.py`

**Interfaces:**
- Consumes: `role-freeze-v1`, Owner-authored normalized ROI profile.
- Produces: `validate_roi_profile(profile, roles) -> RoiProfile`.
- Produces: `crop_frame(frame, rect, padding_px)`, `roi_box_to_full(box, rect, padding_px)`, `full_box_to_roi(box, rect, padding_px)`.

- [ ] **Step 1: RED — exactly-3, bounds, holdout lineage와 round-trip 테스트 작성**

  ```python
  def test_roi_profile_requires_three_nonempty_rects_per_camera():
      with pytest.raises(ValueError, match="exactly 3"):
          validate_roi_profile(profile_with_two_rects(), roles())

  def test_roi_box_round_trip_is_within_one_pixel():
      original = Box(41.0, 52.0, 131.0, 202.0)
      full = roi_box_to_full(original, rect(), padding_px=12)
      restored = full_box_to_roi(full, rect(), padding_px=12)
      assert max_abs_delta(original, restored) <= 1.0
  ```

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_roi.py -q`
  Expected: `roi` module import 실패.

- [ ] **Step 3: GREEN — normalized rect와 provenance gate 구현**

  profile은 camera별 `left/middle/right` 3 rect, `padding_px`, calibration source role, day/IR verification flag, profile SHA를 가진다. calibration source role은 `v27_train|pre_study_calibration`만 허용한다. rect는 `[0,1]` bounds, 양수 면적, target interior 비중첩을 검증한다. OpenCV crop은 numpy slice copy이며 full/ROI 좌표는 float를 유지하고 YOLO serialize 직전에만 정규화한다.

- [ ] **Step 4: GREEN 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_roi.py -q`
  Expected: PASS.

- [ ] **Step 5: 승인된 경우에만 commit**

  ```bash
  git add scripts/yolo26n_v27_c500g/roi.py tests/yolo26n_v27_c500g/test_roi.py
  git commit -m "feat: C500G ROI 좌표 계약"
  ```

### Task 5: Prediction-independent 600 ROI pilot queue

**Files:**
- Create: `scripts/yolo26n_v27_c500g/sampling.py`
- Create: `tests/yolo26n_v27_c500g/test_sampling.py`

**Interfaces:**
- Consumes: inventory, role freeze, ROI profile.
- Produces: `select_pilot_requests(inventory: Mapping[str, object], roles: Mapping[str, object], profile: RoiProfile, *, target: int, seed: str) -> Sequence[FrameRequest]`.
- Produces: `extract_review_items(requests: Sequence[FrameRequest], source_root: Path, profile: RoiProfile, output_dir: Path) -> Mapping[str, object]` and anonymous ZIP.
- Produces: `extract_one(request: FrameRequest, source_path: Path) -> ReviewItem`, always releasing `VideoCapture`.

- [ ] **Step 1: RED — 66/67, train-only, time-band, dedup, release 테스트 작성**

  ```python
  def test_pilot_is_600_train_only_and_balanced():
      rows = select_pilot_requests(inventory(), roles(), roi_profile(), target=600)
      assert len(rows) == 600
      assert set(Counter(row.enclosure_digest for row in rows).values()) == {66, 67}
      assert {row.role for row in rows} == {Role.V27_TRAIN}

  def test_video_capture_is_released_on_decode_error(monkeypatch):
      cap = FailingCapture()
      monkeypatch.setattr(cv2, "VideoCapture", lambda _: cap)
      with pytest.raises(DecodeError):
          extract_one(request(), source_path())
      assert cap.released is True
  ```

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_sampling.py -q`
  Expected: `sampling` module import 실패.

- [ ] **Step 3: GREEN — deterministic selection과 anonymous bundle 구현**

  source SHA와 TEST-SHEET seed로 timestamp rank를 만들고 enclosure 66–67개, 네 시간대, central/edge location을 균형화한다. pixel decode 뒤 RGB channel spread 평균 `<=4`를 IR, 그 외를 color로 기록하되 이 값은 sampling stratum이고 GT가 아니다. exact JPEG SHA를 전역 제거하고 dHash distance `<=2`와 같은 source 5분 이내 후보를 near-duplicate로 제거한다. `cv2.VideoCapture.release()`는 `finally`에서 호출한다.

  queue filename은 `V27P0001.jpg` 형식이고 review manifest에는 source ref가 없다. 별도 0600 lineage에만 `(anonymous_sequence, source_sha, timestamp_ms, roi_profile_sha, full_xy)`를 둔다. warmup은 `V27W0001..V27W0027`, pilot double-review는 SHA rank 60개로 만든다.

- [ ] **Step 4: GREEN 확인과 prediction leak scan**

  Run:
  ```bash
  uv run pytest tests/yolo26n_v27_c500g/test_sampling.py -q
  rg -n 'confidence|prediction|checkpoint|model_version' tests/yolo26n_v27_c500g/fixtures/pilot-review-queue.public.json
  ```
  Expected: tests PASS, fixture scan no match.

- [ ] **Step 5: 승인된 경우에만 commit**

  ```bash
  git add scripts/yolo26n_v27_c500g/sampling.py tests/yolo26n_v27_c500g/test_sampling.py
  git commit -m "feat: v2.7 train-only ROI 파일럿 queue"
  ```

### Task 6: CVAT status/bbox strict normalizer와 adjudication

**Files:**
- Create: `scripts/yolo26n_v27_c500g/cvat.py`
- Create: `tests/yolo26n_v27_c500g/test_cvat.py`

**Interfaces:**
- Consumes: review queue manifest, private lineage, CVAT raw annotations JSON.
- Produces: `build_cvat_contract(queue) -> cvat-task-contract-v1`.
- Produces: `normalize_cvat_export(contract, queue, lineage, annotations) -> human-gt-v1`.
- Produces: `build_conflict_queue(primary, secondary) -> adjudication-queue-v1`.

- [ ] **Step 1: RED — status/bbox, manual source, sibling uncertainty 테스트 작성**

  ```python
  @pytest.mark.parametrize("status,box_count", [("present", 0), ("absent", 1)])
  def test_status_box_mismatch_is_rejected(status, box_count):
      with pytest.raises(ValueError, match="status/bbox"):
          normalize_cvat_export(contract(), queue(), lineage(), export(status, box_count))

  def test_sibling_uncertain_blocks_full_frame_publish():
      gt = normalize_cvat_export(contract(), queue(), lineage(), export_with_uncertain_sibling())
      assert gt["source_groups"][0]["full_frame_eligible"] is False
  ```

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_cvat.py -q`
  Expected: `cvat` module import 실패.

- [ ] **Step 3: GREEN — CVAT image tag와 rectangle 계약 구현**

  contract label은 image tag `present|absent|uncertain|media_error`와 rectangle `gecko`다. 각 image에 status tag 정확히 1개를 요구한다. `present`는 manual rectangle 1개 이상, `absent`는 0개다. bbox는 rotation 0, 양수 면적, image bounds 안이어야 한다. status tag attribute는 다음 allowlist만 허용한다.

  ```text
  edge_issue = none | clipped | miss_suspected
  lighting_state = ir | color | transition
  occlusion_state = none | partial | heavy
  hardcase_structure = none | shed_skin | feeder_insect | human_hand | reflection | droplet | mesh | branch | leaf | camera_body | separator | stationary_sleep
  cross_enclosure_reflection = true | false
  ```

  `human_hand`는 급여·관리 중 사람 손, `shed_skin`은 탈피 중 개체와 남은 허물을 뜻한다. 이 attribute는 sampling coverage용 사람 관찰이며 YOLO class나 행동 GT가 아니다.

  primary export는 overwrite하지 않고 SHA와 raw payload를 보존한다. secondary disagreement는 presence 상태 또는 bbox IoU `<0.70`이며 전부 adjudication으로 보낸다. adjudication 전 `HUMAN_GT_READY`를 발행하지 않는다.

- [ ] **Step 4: GREEN 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_cvat.py -q`
  Expected: PASS.

- [ ] **Step 5: 승인된 경우에만 commit**

  ```bash
  git add scripts/yolo26n_v27_c500g/cvat.py tests/yolo26n_v27_c500g/test_cvat.py
  git commit -m "feat: v2.7 CVAT 사람 GT 정규화"
  ```

### Task 7: Representation freeze와 prediction-independent main queue

**Files:**
- Create: `scripts/yolo26n_v27_c500g/representation.py`
- Create: `tests/yolo26n_v27_c500g/test_representation.py`
- Modify: `scripts/yolo26n_v27_c500g/sampling.py`
- Modify: `tests/yolo26n_v27_c500g/test_sampling.py`

**Interfaces:**
- Produces: `decide_representation(pilot_gt, *, imgsz=960) -> representation-decision-v1`.
- Produces: `select_base_queue(inventory: Mapping[str, object], roles: Mapping[str, object], profile: RoiProfile, human_gt: Mapping[str, object], *, train_target: int, val_target: int, reserve_target: int, seed: str) -> Mapping[str, object]`.

- [ ] **Step 1: RED — 16px/95%/2%, sibling, main quota 테스트 작성**

  ```python
  def test_full_frame_requires_95_percent_boxes_at_least_16px():
      assert decide_representation(pilot_gt(fraction_large=0.95, edge_rate=0.02))["mode"] == "full_frame"
      assert decide_representation(pilot_gt(fraction_large=0.949, edge_rate=0.02))["mode"] == "roi_3tile"

  def test_edge_rate_above_two_percent_requires_recalibration():
      assert decide_representation(pilot_gt(fraction_large=1.0, edge_rate=0.021))["status"] == "ROI_RECALIBRATION_REQUIRED"
  ```

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_representation.py tests/yolo26n_v27_c500g/test_sampling.py -q`
  Expected: representation import 실패.

- [ ] **Step 3: GREEN — letterbox pixel metric와 queue budget 구현**

  full-frame 960 전처리 scale은 `min(960 / width, 960 / height)`이며 각 full-frame bbox short side에 곱한다. eligible bbox 중 `>=16px` fraction과 `edge_issue != none` image fraction을 계산한다. decision에는 replay/C500G bbox-size histogram, profile SHA, TEST-SHEET SHA가 들어간다.

  사람 판단 총목표 3,000은 다음으로 고정한다.

  ```python
  PILOT_UNIQUE = 600
  BASE_TRAIN_ADDITIONAL = 1200
  BASE_VAL = 600
  TEACHER_OR_BASE_FALLBACK = 600
  DOUBLE_REVIEW_TOTAL = 300
  ```

  double-review는 pilot train 60, additional train 120, validation 60, teacher 또는 fallback train 60으로 고정해 각 모집단의 10%를 유지한다.

  teacher가 freeze되지 않으면 마지막 600도 prediction-independent train queue로 채운다. reserve candidate는 1,200개까지 만들되 사람에게 제시하기 전에는 judgment count에 포함하지 않는다. ROI negative가 30–40% 밖이거나 `shed_skin|feeder_insect|human_hand|reflection|droplet|mesh|branch|leaf|camera_body|separator|stationary_sleep` coverage가 한 구조에 편중되면 사람-tagged timestamp 주변의 train source에서만 reserve를 다시 층화한다. 최대 3회 추가 batch를 열고 실제 판단 총량을 report한다.

- [ ] **Step 4: GREEN 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_representation.py tests/yolo26n_v27_c500g/test_sampling.py -q`
  Expected: PASS.

- [ ] **Step 5: 승인된 경우에만 commit**

  ```bash
  git add scripts/yolo26n_v27_c500g/representation.py scripts/yolo26n_v27_c500g/sampling.py tests/yolo26n_v27_c500g/test_representation.py tests/yolo26n_v27_c500g/test_sampling.py
  git commit -m "feat: v2.7 학습 표현과 본 queue 동결"
  ```

### Task 8: Frozen v2.6 teacher ledger와 train-only hard-case queue

**Files:**
- Create: `scripts/yolo26n_v27_c500g/teacher.py`
- Create: `tests/yolo26n_v27_c500g/test_teacher.py`

**Interfaces:**
- Consumes: v2.6 freeze manifest, role manifest, optional prediction ledger, base human GT.
- Produces: `validate_teacher_freeze(manifest) -> TeacherFreeze`.
- Produces: `select_teacher_hardcases(predictions, human_gt, roles, *, limit=600) -> review-queue-v1`.

- [ ] **Step 1: RED — incomplete seed, protected role, pseudo-label leak 테스트 작성**

  ```python
  def test_teacher_requires_all_six_runs_and_fixed_test_pass():
      with pytest.raises(ValueError, match="six runs"):
          validate_teacher_freeze(freeze_with_five_runs())

  @pytest.mark.parametrize("role", ["v27_val", "v26_holdout", "v27_future_holdout"])
  def test_teacher_rejects_protected_role(role):
      with pytest.raises(ValueError, match="train-only"):
          select_teacher_hardcases(predictions_for(role), human_gt(), roles(), limit=600)
  ```

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_teacher.py -q`
  Expected: `teacher` module import 실패.

- [ ] **Step 3: GREEN — freeze pin과 selection-reason-only queue 구현**

  freeze는 run seed `{26,27,28}` × initializer `{warm-start,clean-reference}`, selected checkpoint SHA, imgsz 960, raw confidence, NMS, threshold, 10fps temporal rule, old fixed-test pass를 strict 검증한다. hard-case rank는 `human_report`, base-GT disagreement, high-confidence no-human candidate, low-confidence band, temporal instability 순이며 같은 source/camera-night cap과 dHash dedup을 적용한다.

  public review bundle에는 `selection_reason`, confidence, prediction box를 넣지 않는다. private selection ledger만 freeze SHA와 이유를 가진다. 사람 결과가 돌아오기 전 bbox/absence label은 생성하지 않는다.

- [ ] **Step 4: GREEN 확인과 leak scan**

  Run:
  ```bash
  uv run pytest tests/yolo26n_v27_c500g/test_teacher.py -q
  rg -n 'confidence|prediction|selection_reason' tests/yolo26n_v27_c500g/fixtures/teacher-review-queue.public.json
  ```
  Expected: tests PASS, second command no match.

- [ ] **Step 5: 승인된 경우에만 commit**

  ```bash
  git add scripts/yolo26n_v27_c500g/teacher.py tests/yolo26n_v27_c500g/test_teacher.py
  git commit -m "feat: v2.6 train-only hard-case queue"
  ```

### Task 9: Replay+prospective YOLO v2.7 dataset build와 leakage audit

**Files:**
- Create: `scripts/yolo26n_v27_c500g/dataset.py`
- Create: `tests/yolo26n_v27_c500g/test_dataset.py`

**Interfaces:**
- Consumes: frozen v2.6 replay manifest/bytes, role manifest, representation decision, adjudicated human GT, private lineage.
- Produces: `build_dataset_v27(replay_manifest: Mapping[str, object], replay_root: Path, prospective_gt: Mapping[str, object], roles: Mapping[str, object], decision: Mapping[str, object], output_dir: Path) -> Mapping[str, object]`.
- Produces: `audit_leakage(dataset: Mapping[str, object], protected_ledgers: Sequence[Mapping[str, object]]) -> Mapping[str, object]`.

- [ ] **Step 1: RED — representation, sibling, replay integrity, role leak 테스트 작성**

  ```python
  def test_full_frame_publish_requires_three_valid_siblings():
      with pytest.raises(ValueError, match="sibling"):
          build_dataset_v27(inputs_with_uncertain_sibling(), mode="full_frame")

  def test_same_camera_night_in_train_and_val_fails_closed():
      with pytest.raises(ValueError, match="camera-night leakage"):
          audit_leakage(dataset_with_cross_role_night(), protected_ledgers())

  def test_replay_bytes_must_match_parent_manifest():
      with pytest.raises(ValueError, match="replay integrity"):
          build_dataset_v27(inputs_with_mutated_replay(), mode="roi_3tile")
  ```

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_dataset.py -q`
  Expected: `dataset` module import 실패.

- [ ] **Step 3: GREEN — single publication branch와 YOLO serialization 구현**

  `full_frame`은 같은 timestamp의 세 ROI가 모두 valid일 때 원본 image 하나와 원본 좌표 bbox를 쓴다. `roi_3tile`은 각 valid ROI crop과 ROI 좌표 bbox를 쓴다. 같은 timestamp의 두 representation을 동시에 쓰지 않는다. empty label은 사람 `absent`만 허용한다. 기존 replay image/label bytes와 split은 수정하지 않고 train-only replay를 새 manifest에서 참조한다.

  누수 감사 순서는 source lineage role, camera-night role, exact image SHA, cross-role dHash `<=2`, protected v2.6 holdout/old fixed-test 순이다. 하나라도 충돌하면 dataset directory를 `DATASET_READY`로 rename하지 않는다. 성공 manifest에는 provenance별 image/bbox/negative/size histogram과 write count 0을 기록한다.

- [ ] **Step 4: GREEN 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_dataset.py -q`
  Expected: PASS.

- [ ] **Step 5: 승인된 경우에만 commit**

  ```bash
  git add scripts/yolo26n_v27_c500g/dataset.py tests/yolo26n_v27_c500g/test_dataset.py
  git commit -m "feat: YOLO v2.7 사람 GT dataset build"
  ```

### Task 10: CLI, fake-video end-to-end와 운영 runbook

**Files:**
- Create: `scripts/yolo26n_v27_c500g/cli.py`
- Create: `tests/yolo26n_v27_c500g/test_cli.py`
- Create: `tests/yolo26n_v27_c500g/test_end_to_end.py`
- Create: `docs/runbooks/yolo26n-v27-c500g-dataset.md`

**Interfaces:**
- Produces CLI subcommands: `inventory`, `freeze-roles`, `validate-roi`, `build-pilot`, `normalize-cvat`, `freeze-representation`, `build-base`, `build-teacher`, `build-dataset`, `audit`.

- [ ] **Step 1: RED — CLI overwrite·stage-order·fake-video E2E 테스트 작성**

  ```python
  def test_build_pilot_requires_role_freeze(cli_runner, attempt):
      result = cli_runner("build-pilot", "--attempt", str(attempt))
      assert result.exit_code != 0
      assert "ROLE_FREEZE_REQUIRED" in result.stdout

  def test_fake_video_pipeline_reaches_dataset_ready(fake_c500g_tree, cli_runner):
      run_all_fake_stages(fake_c500g_tree, cli_runner)
      manifest = load_private_manifest(fake_c500g_tree.attempt / "dataset/manifest.private.json")
      assert manifest["status"] == "V27_DATASET_READY"
      assert manifest["db_write_count"] == manifest["r2_write_count"] == 0
  ```

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest tests/yolo26n_v27_c500g/test_cli.py tests/yolo26n_v27_c500g/test_end_to_end.py -q`
  Expected: `cli` module import 실패.

- [ ] **Step 3: GREEN — stage marker와 명시적 input pin CLI 구현**

  각 subcommand는 이전 artifact path와 expected SHA를 필수 인자로 받고 기존 output이 있으면 `FileExistsError`로 멈춘다. `--source-root` 기본값을 두지 않고 explicit absolute path만 받는다. stdout은 status와 aggregate count만 출력하고 source ref/path를 출력하지 않는다.

  runbook의 사람 흐름은 다음 순서로 쓴다.

  ```text
  워밍업 27장 → prediction-free pilot primary → 별도 blind double 60장
  → conflict Owner adjudication → representation report 확인
  → 본 primary/double review → teacher queue는 별도 badge 없이 blind 처리
  → correction은 원본 제출을 덮지 않고 새 revision으로 저장
  ```

  CVAT task는 CLI가 자동 생성하지 않는다. Owner가 익명 ZIP의 image count, prediction leak 0, role aggregate를 확인한 뒤 CVAT UI에서 `primary`와 `double-review`를 서로 다른 image task로 만든다. label contract는 image tag 4개와 rectangle `gecko`만 등록하고 source filename 대신 anonymous sequence를 쓴다. 실제 task/job ID는 0600 runtime receipt에만 기록한다.

- [ ] **Step 4: GREEN 확인과 전체 targeted regression**

  Run:
  ```bash
  uv run pytest tests/yolo26n_v27_c500g -q
  uv run python -m scripts.yolo26n_v27_c500g.cli --help
  git diff --check
  ```
  Expected: all PASS, help에 secret/source identifier 없음, diff check exit 0.

- [ ] **Step 5: 승인된 경우에만 commit**

  ```bash
  git add scripts/yolo26n_v27_c500g/cli.py tests/yolo26n_v27_c500g/test_cli.py tests/yolo26n_v27_c500g/test_end_to_end.py docs/runbooks/yolo26n-v27-c500g-dataset.md
  git commit -m "feat: v2.7 C500G 준비 파이프라인 연결"
  ```

### Task 11: 실제 source 실행 checkpoint — 별도 승인 뒤에만

**Files:**
- Create at runtime: `storage/yolo26n-v27-c500g/attempts/{attempt_id}/runtime-provenance.private.json`
- Create if cross-host: `docs/handoff-prompts/2026-08-29-yolo26n-v27-c500g-preparation-runtime-handoff.md`
- Modify after each gate: `experiments/yolo26n-v27-c500g/TEST-SHEET.md` result appendix only

**Interfaces:**
- Consumes: tracked clean implementation commit, source root, read-only R2/DB credentials, Owner-approved ROI profile and CVAT exports.
- Produces: actual inventory → role freeze → pilot → human GT → representation → dataset artifacts.

- [ ] **Step 1: handoff/preflight 검증**

  cross-host면 manifest에 `execution_repo`, design/plan absolute path, 40자리 commit SHA, implementation/runtime host와 runtime kind를 기록한 뒤 실행한다.

  ```bash
  V27_REPO_ROOT="$(git rev-parse --show-toplevel)"
  V27_HANDOFF_PATH="$V27_REPO_ROOT/docs/handoff-prompts/2026-08-29-yolo26n-v27-c500g-preparation-runtime-handoff.md"
  uv run python scripts/verify_agent_handoff.py --manifest "$V27_HANDOFF_PATH"
  ```
  Expected: `HANDOFF_OK`. 실패하면 source 접근을 시작하지 않는다.

- [ ] **Step 2: read-only inventory만 실행하고 Owner에게 aggregate 보고**

  ```bash
  V27_REPO_ROOT="$(git rev-parse --show-toplevel)"
  V27_ATTEMPT="$V27_REPO_ROOT/storage/yolo26n-v27-c500g/attempts/2026-08-29-a1"
  V27_TEST_SHEET_SHA="$(shasum -a 256 "$V27_REPO_ROOT/experiments/yolo26n-v27-c500g/TEST-SHEET.md" | awk '{print $1}')"
  uv run python -m scripts.yolo26n_v27_c500g.cli inventory \
    --source-root /Volumes/RAP-C500G/recordings \
    --attempt "$V27_ATTEMPT" \
    --test-sheet-sha256 "$V27_TEST_SHEET_SHA"
  ```

  `V27_SOURCE_INVENTORY_READY`가 아니면 mismatch/shortage aggregate만 보고 중단한다.

- [ ] **Step 3: role freeze 후 pixel-access 승인 요청**

  `freeze-roles` 성공 결과에서 v2.6 holdout 3개 또는 명시적 shortage, train/validation date block, role overlap 0을 확인한다. 이 시점까지 video/thumbnail open count는 0이어야 한다. Owner 승인 전 ROI calibration으로 넘어가지 않는다.

- [ ] **Step 4: ROI profile·600 pilot 실행 후 representation 승인 요청**

  ROI profile은 train/pre-study frame으로만 만든다. 익명 ZIP aggregate를 Owner가 승인한 뒤 CVAT UI에서 primary 600장과 별도 double-review 60장 task를 만들고, task/job ID를 private receipt에 기록한다. 두 export와 adjudication이 끝난 뒤 `freeze-representation`을 실행한다. edge issue가 2% 초과면 최대 3회 ROI recalibration 후 중단한다. full-frame/3-tile decision을 Owner가 승인하기 전 본 queue를 만들지 않는다.

- [ ] **Step 5: 본 사람 GT와 optional teacher queue 실행**

  primary/double/adjudication을 순서대로 normalize한다. v2.6 freeze validator가 실패하면 teacher count 0과 prediction-independent fallback 600을 사용한다. validation에는 teacher 후보가 0인지 재검증한다.

- [ ] **Step 6: dataset build·최종 audit**

  Run:
  ```bash
  ROLE_SHA="$(shasum -a 256 "$V27_ATTEMPT/roles/role-freeze.private.json" | awk '{print $1}')"
  REPRESENTATION_SHA="$(shasum -a 256 "$V27_ATTEMPT/representation/decision.private.json" | awk '{print $1}')"
  uv run python -m scripts.yolo26n_v27_c500g.cli build-dataset --attempt "$V27_ATTEMPT" --expected-role-sha256 "$ROLE_SHA" --expected-representation-sha256 "$REPRESENTATION_SHA"
  uv run python -m scripts.yolo26n_v27_c500g.cli audit --attempt "$V27_ATTEMPT"
  ```
  Expected: `V27_DATASET_READY`, `LEAKAGE_AUDIT_PASS`, forbidden write 0. `HOLDOUT_SHORTAGE`가 있으면 그대로 보존하고 production 성능을 주장하지 않는다.

- [ ] **Step 7: 여기서 중단**

  training, inference evaluation, CVAT task 자동 생성, active model 변경은 이 preparation plan의 완료가 아니다. 별도 학습 plan과 Owner 실행 승인을 받는다.

## Final Verification Matrix

| Spec requirement | Plan task | Evidence |
|---|---|---|
| 30분 원본 불변·USB/R2/DB 대조 | 2, 11 | inventory status, three-layer SHA/size match, write 0 |
| role before pixel/sampling | 3, 10, 11 | fake open count 0, stage-order CLI failure |
| v2.6 first 3 camera-night/300 clip | 0, 3 | clip-unit addendum, holdout role count/shortage |
| ROI/full-frame decision | 4, 5, 7 | round-trip, 16px/95%/2% report |
| IR·가림·빈 화면·오탐 구조 | 5, 7 | pilot/base strata counts |
| CVAT 사람 경험·복구 | 6, 10 | status/bbox validation, append-only revision runbook |
| camera-night/date 누수 방지 | 3, 9 | role manifest, leakage report |
| 3,000 unique·300 double review | 7, 11 | human judgment aggregate |
| teacher 허용·금지 경계 | 8, 11 | freeze validator, protected-role rejection, blind bundle |
| replay 보존·단일 C500G representation | 7, 9 | representation freeze, replay integrity SHA |
| v2.7 future holdout 부족 보고 | 9, 11 | `HOLDOUT_SHORTAGE`, no production claim |

## Execution Stop Conditions

- source inventory mismatch, SHA drift, decode probe failure
- v2.6 freeze/clip-unit/TEST-SHEET pin 부재
- role overlap 또는 role freeze 전 pixel access
- post-freeze complete camera-night 3개 미만
- holdout/validation pixel을 ROI calibration에 사용
- ROI edge issue >2% after 3 recalibrations
- ROI negative outside 30–40% after 3 re-stratifications
- `uncertain+media_error` >10% without cause resolution
- unresolved primary/double conflict
- teacher input protected role 또는 freeze mismatch
- exact/near duplicate, source lineage, camera-night cross-role leak
- private output overwrite 시도 또는 forbidden write count nonzero

하나라도 발생하면 부족분을 모델 prediction으로 채우거나 source를 다른 role로 옮기지 않고 shortage artifact를 남긴다.
