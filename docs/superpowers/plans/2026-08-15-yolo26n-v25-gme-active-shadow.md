# YOLO26n v2.5 GME Active Shadow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 동결된 YOLO26n v2.5 warm-start detector를 GME의 새 append-only detector identity로 연결하고, 10개 실영상 smoke 뒤 신규 production 영상과 저장된 eligible 영상을 안전하게 재분석한다.

**Architecture:** `gecko-vision-gate`는 검증된 checkpoint bytes를 Ultralytics YOLO detector protocol로 변환한다. `petcam-nightly-reporter`는 exact inference contract와 model provenance를 고정하고 live 우선 worker·smoke·backfill을 실행한다. `petcam-lab`은 기존 `gme_jobs`/`gme_runs` schema를 그대로 사용하면서 신규 live enqueue identity만 v2.5 checkpoint SHA로 전환한다.

**Tech Stack:** Python 3.12, Ultralytics YOLO26n, OpenCV, Supabase PostgreSQL RPC, Cloudflare R2, launchd, pytest, uv.

## Global Constraints

- v2.5 checkpoint SHA-256은 `2b128f105e898bc472ed66861583ab80007dae6e94b291db497d7a2f8081f84a`다.
- evaluation freeze SHA-256은 `3d1f65f8d5034010add7210ada7cbad9f48ca329646ab021e5a428470f6949f9`다.
- raw inference는 `conf=0.001`, `imgsz=960`, `iou=0.70`, `max_det=50`; GME observation은 score `>=0.20`만 사용한다.
- job identity는 `(clip_id, gme-shadow-v1, gme-motion-v0, checkpoint_sha256)`다.
- 기존 detector identity의 job/run/artifact는 수정·삭제하지 않는다.
- 신규 live가 backfill보다 우선이며 live lag p95가 900초를 넘으면 historical claim을 중단한다.
- Flutter/API `activity-v1`, 사람 GT, 행동명, 하이라이트, 자동 skip·격리·삭제·부재 확정은 변경하지 않는다.
- 원본 R2 object는 read-only다. write는 기존 GME permanent/debug allowlist와 `gme_jobs`/`gme_runs` RPC에만 허용한다.
- 10-clip smoke 독립 검수 전에는 신규 live trigger 전환과 저장 영상 backfill을 실행하지 않는다.
- future holdout candidate selection과 사람 blind GT에는 v2.5 prediction을 노출하지 않는다.

---

### Task 1: YOLO26n GME detector adapter

**Repo:** `/Users/baek-end/myPythonProjects/gecko-vision-gate`

**Files:**
- Create: `src/gecko_vision_gate/gme_yolo_detector.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `tests/test_gme_yolo_detector.py`

**Interfaces:**
- Consumes: `gme_contracts.Detection`, pinned checkpoint path/SHA, raw/score/NMS/image/max-det settings.
- Produces: `YoloGMEAdapter.detect(frame_bgr, timestamp_sec) -> tuple[Detection, ...]`와 `build_yolo_detector(...)`.

- [ ] **Step 1: checkpoint와 inference contract의 RED 테스트를 작성한다.**

```python
def test_yolo_adapter_rejects_checkpoint_sha_mismatch(tmp_path):
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"model")
    with pytest.raises(ValueError, match="checkpoint SHA"):
        build_yolo_detector(checkpoint=checkpoint, expected_sha256="0" * 64, model_factory=lambda _: FakeModel())

def test_yolo_adapter_filters_at_score_threshold_and_preserves_xywh():
    detector = build_adapter_with_predictions(confidences=[0.19, 0.20, 0.91])
    detections = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8), 1.5)
    assert [d.confidence for d in detections] == [0.91, 0.20]
    assert all(d.class_name == "gecko" for d in detections)
```

- [ ] **Step 2: 실패를 확인한다.**

Run: `uv run pytest -q tests/test_gme_yolo_detector.py`
Expected: FAIL because `gme_yolo_detector` does not exist.

- [ ] **Step 3: 검증된 checkpoint와 exact predict 설정을 구현한다.**

```python
class YoloGMEAdapter:
    def detect(self, frame_bgr: np.ndarray, timestamp_sec: float) -> tuple[Detection, ...]:
        result = self._model.predict(
            source=frame_bgr, conf=self.raw_confidence, imgsz=self.image_size,
            iou=self.nms_iou, max_det=self.max_detections, verbose=False,
        )[0]
        rows = zip(result.boxes.xywh.tolist(), result.boxes.conf.tolist(), strict=True)
        accepted = [
            Detection(timestamp_sec, tuple(float(v) for v in xywh), float(score), "gecko")
            for xywh, score in rows if float(score) >= self.threshold
        ]
        return tuple(sorted(accepted, key=lambda item: (-item.confidence, item.bbox_xywh)))
```

`build_yolo_detector()`는 모델 load 전에 actual checkpoint SHA를 expected SHA와 비교하고, model identity를 checkpoint SHA로 고정한다. Ultralytics는 runtime dependency로 `uv add ultralytics`를 사용한다.

- [ ] **Step 4: adapter와 Gate 전체 테스트를 실행한다.**

Run: `uv run pytest -q tests/test_gme_yolo_detector.py tests/test_gme_engine.py tests/test_gme_contracts.py`
Expected: PASS.

- [ ] **Step 5: Gate 변경만 커밋한다.**

```bash
git add pyproject.toml uv.lock src/gecko_vision_gate/gme_yolo_detector.py tests/test_gme_yolo_detector.py
git commit -m "feat: GME YOLO26n detector adapter"
```

### Task 2: Nightly worker v2.5 configuration과 provenance

**Repo:** `/Users/baek-end/petcam-nightly-reporter`

**Files:**
- Modify: `reporter/config.py`
- Modify: `reporter/gme_worker.py`
- Modify: `.env.example`
- Modify: `install-launchd-gme.sh`
- Modify: `tests/test_gme_worker.py`
- Modify: `tests/test_install_launchd_gme.py`

**Interfaces:**
- Consumes: Task 1 `build_yolo_detector()`와 exact v2.5 configuration.
- Produces: model/checkpoint/inference settings가 DB run provenance에 남는 one-shot GME worker.

- [ ] **Step 1: RED 테스트로 backend 선택, mismatch 선차단, provenance를 고정한다.**

```python
def test_worker_rejects_job_detector_identity_before_download():
    mismatched = FakeJob(detector_identity="0" * 64)
    with pytest.raises(_JobFailure, match="invalid_metadata"):
        _validate_job_detector_identity(mismatched, local_detector_identity=V25_IDENTITY)

def test_run_payload_contains_exact_yolo_inference_contract():
    payload = _run_payload(
        FakeJob(detector_identity=V25_IDENTITY), fake_analysis(V25_IDENTITY), fake_uploaded(),
        Producer("test-host", "run-1", "test-code"), detector_provenance=V25_PROVENANCE,
    )
    assert payload["detector_provenance"]["raw_confidence"] == 0.001
    assert payload["detector_provenance"]["threshold"] == 0.20
    assert payload["detector_provenance"]["image_size"] == 960
```

- [ ] **Step 2: 대상 테스트 실패를 확인한다.**

Run: `uv run pytest -q tests/test_gme_worker.py tests/test_install_launchd_gme.py`
Expected: FAIL on missing YOLO config/provenance.

- [ ] **Step 3: exact configuration과 adapter factory를 구현한다.**

`reporter/config.py`에 다음 환경변수를 strict parse한다.

```text
GME_DETECTOR_BACKEND=yolo26n
GME_CHECKPOINT_SHA256=2b128f105e898bc472ed66861583ab80007dae6e94b291db497d7a2f8081f84a
GME_DETECTOR_IDENTITY=d4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6
GME_RAW_CONFIDENCE=0.001
GME_SCORE_THRESHOLD=0.20
GME_IMAGE_SIZE=960
GME_NMS_IOU=0.70
GME_MAX_DETECTIONS=50
```

worker는 claim한 job identity가 local detector execution identity와 다르면 media download 전에 terminal `invalid_metadata`로 종료한다. `_run_payload()`에는 execution identity, model name/version, checkpoint SHA, raw confidence, score threshold, image size, NMS IoU, max detections를 저장한다.

- [ ] **Step 4: launchd가 exact configuration을 전달하도록 구현한다.**

installer는 위 값, checkpoint 절대경로, expected host를 비밀값 없이 plist에 넣고 `plutil -lint`를 통과시킨다.

- [ ] **Step 5: worker 관련 회귀를 실행한다.**

Run: `uv run pytest -q tests/test_gme_worker.py tests/test_gme_runtime_policy.py tests/test_install_launchd_gme.py`
Expected: PASS.

- [ ] **Step 6: Nightly 변경만 커밋한다.**

```bash
git add reporter/config.py reporter/gme_worker.py .env.example install-launchd-gme.sh tests/test_gme_worker.py tests/test_install_launchd_gme.py
git commit -m "feat: GME worker에 YOLO v2.5 연결"
```

### Task 3: Smoke와 backfill identity를 runtime contract로 전환

**Repo:** `/Users/baek-end/petcam-nightly-reporter`

**Files:**
- Modify: `scripts/enqueue_gme_smoke.py`
- Modify: `scripts/enqueue_gme_backfill.py`
- Modify: `scripts/audit_gme_shadow.py`
- Modify: `tests/test_enqueue_gme_smoke.py`
- Modify: `tests/test_enqueue_gme_backfill.py`
- Modify: `tests/test_audit_gme_shadow.py`

**Interfaces:**
- Consumes: strict `GME_CHECKPOINT_SHA256`와 `GME_DETECTOR_IDENTITY` configuration.
- Produces: v2.5 identity로만 enqueue/audit하는 dry-run-first operational tools.

- [ ] **Step 1: RED 테스트로 old hardcoded identity와 test clip 누수를 막는다.**

```python
def test_enqueue_uses_configured_v25_identity():
    enqueue(fake_sb, ["clip"], source="smoke", priority=90, apply=True, detector_identity=V25_IDENTITY)
    assert fake_sb.rpc_payload["p_detector_identity"] == V25_IDENTITY

def test_eligible_requires_production_purpose():
    assert not is_eligible_metadata(row(clip_purpose="test"), exclusion_state=None, cleanup_state=None)
```

- [ ] **Step 2: 실패를 확인한다.**

Run: `uv run pytest -q tests/test_enqueue_gme_smoke.py tests/test_enqueue_gme_backfill.py tests/test_audit_gme_shadow.py`
Expected: FAIL because the old RF-DETR identity is constant and purpose is not loaded.

- [ ] **Step 3: selection과 enqueue를 v2.5 contract로 구현한다.**

`motion_clips` select에 `clip_purpose`를 포함하고 exact `production`만 허용한다. enqueue와 audit는 caller가 전달한 64자리 lowercase detector identity를 요구하며 기본값으로 숨기지 않는다. dry-run output에는 식별자 원문 대신 수량과 identity 앞 8자리만 표시한다.

- [ ] **Step 4: 관련 전체 테스트를 통과시킨다.**

Run: `uv run pytest -q tests/test_enqueue_gme_smoke.py tests/test_enqueue_gme_backfill.py tests/test_audit_gme_shadow.py`
Expected: PASS.

- [ ] **Step 5: Nightly 변경만 커밋한다.**

```bash
git add scripts/enqueue_gme_smoke.py scripts/enqueue_gme_backfill.py scripts/audit_gme_shadow.py tests/test_enqueue_gme_smoke.py tests/test_enqueue_gme_backfill.py tests/test_audit_gme_shadow.py
git commit -m "fix: GME smoke와 backfill detector identity 고정"
```

### Task 4: 신규 live enqueue를 v2.5 identity로 전환

**Repo:** `/Users/baek/.codex/worktrees/d1a4/petcam-lab`

**Files:**
- Create: `migrations/2026-08-15_yolo26n_v25_gme_active_shadow.sql`
- Create: `tests/test_yolo26n_v25_gme_active_shadow_migration.py`
- Modify: `docs/DATABASE.md`

**Interfaces:**
- Consumes: v2.5 checkpoint SHA and existing `trg_enqueue_gme_live_job`.
- Produces: smoke 승인 뒤 신규 clip을 v2.5 detector identity로 enqueue하는 reversible trigger function.

- [ ] **Step 1: migration RED 테스트를 작성한다.**

```python
def test_migration_pins_v25_identity_and_preserves_history():
    assert V25_IDENTITY in SQL
    assert "create or replace function public.fn_enqueue_gme_live_job" in SQL.lower()
    assert "delete from public.gme_jobs" not in SQL.lower()
    assert "delete from public.gme_runs" not in SQL.lower()

def test_migration_requires_ten_v25_smoke_runs():
    assert "j.detector_identity" in SQL.lower()
    assert "smoke_complete < 10" in SQL.lower()
```

- [ ] **Step 2: RED를 확인한다.**

Run: `uv run pytest -q tests/test_yolo26n_v25_gme_active_shadow_migration.py`
Expected: FAIL because migration does not exist.

- [ ] **Step 3: preflight와 rollback을 포함한 forward migration을 구현한다.**

Migration은 v2.5 smoke succeeded 10건, 기존 trigger 1개, 예상 old detector identity를 검증한 뒤 `fn_enqueue_gme_live_job()` 본문만 v2.5 SHA로 교체한다. rollback SQL은 old identity 본문을 복원하며 어떤 job/run도 삭제하지 않는다.

- [ ] **Step 4: migration과 GME 회귀 테스트를 통과시킨다.**

Run: `uv run pytest -q tests/test_yolo26n_v25_gme_active_shadow_migration.py tests/test_gecko_motion_engine_migration.py tests/test_gecko_motion_engine_cutover.py`
Expected: PASS.

- [ ] **Step 5: lab 변경만 커밋한다.**

```bash
git add migrations/2026-08-15_yolo26n_v25_gme_active_shadow.sql tests/test_yolo26n_v25_gme_active_shadow_migration.py docs/DATABASE.md
git commit -m "feat: GME live enqueue를 YOLO v2.5로 전환"
```

### Task 5: Cross-repo runtime handoff와 model artifact pin

**Repo:** `/Users/baek/.codex/worktrees/d1a4/petcam-lab`

**Files:**
- Create: `docs/handoff-prompts/2026-08-15-yolo26n-v25-gme-active-shadow-runtime-handoff.md`

**Interfaces:**
- Consumes: Task 1~4의 세 tracked commit과 model/freeze SHA.
- Produces: `HANDOFF_OK`를 통과한 Mac mini runtime manifest.

- [ ] **Step 1: 세 저장소 SHA와 runtime 정보를 manifest에 literal로 기록한다.**

```text
execution_repo: /Users/baek-end/petcam-nightly-reporter
implementation_host: Mac mini
runtime_host: baeg-endeuui-Macmini.local
runtime_kind: launchd one-shot worker
service_label: com.teraai.gme-worker
checkpoint_sha256: 2b128f105e898bc472ed66861583ab80007dae6e94b291db497d7a2f8081f84a
```

design/plan 절대경로, lab 40자리 commit, Gate/Nightly dependency commit을 함께 기록한다.

- [ ] **Step 2: manifest와 plan/design이 tracked clean인지 확인한다.**

Run: `git status --short -- docs/handoff-prompts/2026-08-15-yolo26n-v25-gme-active-shadow-runtime-handoff.md docs/superpowers/specs/2026-08-15-yolo26n-v25-gme-active-shadow-design.md docs/superpowers/plans/2026-08-15-yolo26n-v25-gme-active-shadow.md`
Expected: no output after commit.

- [ ] **Step 3: handoff verifier를 실행한다.**

Run: `uv run python scripts/verify_agent_handoff.py --manifest /Users/baek/.codex/worktrees/d1a4/petcam-lab/docs/handoff-prompts/2026-08-15-yolo26n-v25-gme-active-shadow-runtime-handoff.md`
Expected: `HANDOFF_OK`.

### Task 6: Mac mini 설치 preflight와 10-clip smoke

**Runtime host:** `baeg-endeuui-Macmini.local`

**Files:**
- Create under private runtime: model handoff manifest and smoke audit artifact only.
- Do not modify original clips or historical GME artifacts.

**Interfaces:**
- Consumes: verified Task 5 manifest and exact three repo commits.
- Produces: independent v2.5 `10/10` smoke acceptance.

- [ ] **Step 1: runtime read-only preflight를 수행한다.**

세 repo HEAD, model SHA, freeze SHA, hostname, exact service working directory, GME DB migration state, existing launchd state를 확인한다. mismatch면 write 전에 중단한다.

- [ ] **Step 2: Gate/Nightly 전체 회귀와 one-frame local inference smoke를 실행한다.**

Run on Mac mini:

```bash
uv run pytest -q
```

Expected: both repositories PASS; model load succeeds without DB/R2 write.

- [ ] **Step 3: v2.5 identity로 정확히 10개 production smoke job을 enqueue한다.**

`enqueue_gme_smoke.py --apply`는 exact 10 eligible clips와 detector identity를 preflight한 뒤에만 RPC를 호출한다.

- [ ] **Step 4: worker를 bounded one-shot으로 실행하고 독립 audit한다.**

Expected: `10/10 succeeded`, rerun identity no-op, terminal failure 0, temp residue 0, original object write 0, GME allowlist 밖 write 0.

### Task 7: Live 전환과 저장 영상 backfill

**Runtime host:** `baeg-endeuui-Macmini.local`

**Interfaces:**
- Consumes: Task 6 smoke acceptance.
- Produces: 신규 v2.5 live enqueue와 bounded historical backfill.

- [ ] **Step 1: Task 4 migration을 production DB에 한 transaction으로 적용한다.**

적용 직후 trigger function identity가 v2.5 SHA인지 SELECT-only로 다시 확인한다. 다른 schema/data write는 금지한다.

- [ ] **Step 2: v2.5 launchd worker를 설치·기동한다.**

Expected: label `com.teraai.gme-worker`, correct hostname/working directory/repo HEAD, 60초 one-shot, enabled state.

- [ ] **Step 3: 신규 live coverage와 lag를 먼저 확인한다.**

새 eligible clip이 v2.5 identity job을 만들고 worker가 처리하는지 확인한다. live lag p95가 900초 이내일 때만 다음 step으로 간다.

- [ ] **Step 4: 저장 영상 dry-run inventory를 만든다.**

production purpose, media present/decode eligible, no existing v2.5 run 조건의 총 수량만 출력한다. test/quarantine/deleted/source-missing은 제외 수량으로만 기록한다.

- [ ] **Step 5: backfill을 bounded batch로 시작한다.**

첫 batch는 50건으로 제한한다. audit 통과 뒤 나머지를 keyset batch로 enqueue한다. live lag p95가 900초를 넘으면 backfill claim만 자동 중단한다.

### Task 8: 24시간 operational audit와 backend handoff 종료

**Repos:** all three

**Interfaces:**
- Consumes: live/backfill runs.
- Produces: operational shadow acceptance 또는 reversible rollback.

- [ ] **Step 1: 24시간 aggregate를 산출한다.**

신규 eligible coverage, historical selected/enqueued/succeeded, live lag p50/p95, retry/terminal failure, unknown/visible/tracking-quality 분포, temp residue를 집계한다. 개별 clip/source/GT는 보고하지 않는다.

- [ ] **Step 2: 성공 기준을 평가한다.**

`coverage=100%`, `terminal failure<1%`, `live lag p95<=900s`, provenance match `100%`, temp `0`, forbidden write `0`이면 active shadow를 유지한다.

- [ ] **Step 3: 실패 시 reversible rollback을 실행한다.**

v2.5 신규 enqueue와 worker만 중단하고 live trigger를 old identity로 복원한다. 이미 생성된 v2.5 job/run/artifact는 append-only provenance로 보존한다.

- [ ] **Step 4: Slack 후속 보고를 두 갈래로 남긴다.**

연구 업데이트에는 안전 집계·future holdout 미완료·production 미승격을, 백엔드 handoff에는 세 repo SHA·model SHA·service 상태·smoke/backfill/audit 결과·rollback 명령을 기록한다.
