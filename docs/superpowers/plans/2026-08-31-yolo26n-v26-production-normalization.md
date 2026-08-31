# YOLO26n v2.6 Production Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** YOLO26n v2.6을 신규·저장 production 영상의 GME detector와 라벨링 웹의 기본 overlay·업로드 추론 worker로 연결해 v2.5 장애를 정상화한다.

**Architecture:** Gecko Vision Gate가 v2.6 checkpoint·후처리·10fps 시간축 계약과 실행 identity를 재현하고, petcam-nightly-reporter가 Mac mini의 durable GME worker와 인증 HTTP inference worker를 제공한다. petcam-lab은 append-only v2.6 job enqueue와 exact-identity web overlay를 제공하며, 10건 smoke 뒤 신규 live를 직접 전환하고 과거 영상은 50개씩 backfill한다.

**Tech Stack:** Python 3.12, Ultralytics YOLO26n, OpenCV, FastAPI/uvicorn, Supabase PostgreSQL RPC, Cloudflare R2, Next.js 14, TypeScript, launchd, Cloudflare Tunnel, pytest, Vitest, uv.

**Spec:** `docs/superpowers/specs/2026-08-31-yolo26n-v26-production-normalization-design.md`

**Execution status (2026-09-01 KST):** Tasks 1~6 구현·테스트·commit·push 완료. Gate `ecddd485`,
Nightly `d1985c8`, petcam-lab `d266863`. Gate 121, Nightly 496, web 1,274 tests와 TypeScript PASS.
로컬 web build는 repository resource hook 때문에 실행하지 않았고 Task 8 clean runtime 검증으로 이관한다.
production DB/R2/service/Vercel 변경은 아직 0이다.

## Global Constraints

- petcam-lab reviewed base commit은 `4ce6270def59298ce6a789b6165a1e4801f15b96`다.
- training source commit은 `e4566db750f8e0f668d72aeadd6f8305a2361f90`다.
- checkpoint SHA-256은 `a00e5a7a1e1f9197accb036339a38a7c821f03c8ab79611ebce89e5cde59b513`다.
- detector freeze SHA-256은 `8f8e02beb452ec2ddfdce344dff507294f56136c69224990c50552d22bb343a0`다.
- detector execution identity는 `89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7`다.
- inference는 `conf=0.001`, `imgsz=960`, model NMS `0.70`, post NMS `0.55`, `max_det=50`, score `>=0.15`다.
- 분석은 최대 10fps, presence candidate는 연속 5 frame 중 3 frame 이상 accepted detection이다.
- 신규 live priority는 100이고 historical batch는 최대 50이다. live lag p95가 900초를 넘으면 historical claim만 중단한다.
- v2.5 job/run/artifact, 사람 GT, 원본 R2 object는 수정·삭제·덮어쓰기하지 않는다.
- `yolo_active_model`의 future-holdout gate를 우회하지 않고 Flutter/API 고객 활동량 정본을 바꾸지 않는다.
- production fake inference, secret 출력, browser의 detector identity/run UUID/R2 key 노출을 금지한다.
- 구현은 세 repository의 격리 worktree에서 진행하고 각 repository 변경은 별도 commit으로 고정한다.

---

### Task 1: Gecko Vision Gate v2.6 실행 계약과 10fps 시간축

**Repo:** `/Users/baek/myPythonProjects/gecko-vision-gate`

**Files:**
- Create: `src/gecko_vision_gate/gme_temporal.py`
- Modify: `src/gecko_vision_gate/gme_contracts.py`
- Modify: `src/gecko_vision_gate/gme_engine.py`
- Modify: `src/gecko_vision_gate/gme_yolo_detector.py`
- Create: `tests/test_gme_temporal.py`
- Modify: `tests/test_gme_engine.py`
- Modify: `tests/test_gme_yolo_detector.py`

**Interfaces:**
- Consumes: frozen checkpoint bytes와 Global Constraints의 exact inference/temporal values.
- Produces: `AnalysisClock.accept(frame_index, source_fps) -> bool`, `TemporalDetectionGate.push(detections) -> tuple[Detection, ...]`, `YoloGMEAdapter.execution_contract`, v2.6 `detector_identity()`.

- [x] **Step 1: exact 10fps clock와 3-of-5 gate RED 테스트를 작성한다.**

```python
def test_25fps_uses_absolute_10fps_deadline_grid():
    clock = AnalysisClock(max_analysis_fps=10.0)
    selected = [index for index in range(26) if clock.accept(index, 25.0)]
    assert selected == [0, 3, 5, 8, 10, 13, 15, 18, 20, 23, 25]

def test_two_of_five_is_suppressed_and_third_positive_is_accepted():
    gate = TemporalDetectionGate(window_frames=5, min_positive_frames=3)
    assert gate.push((_detection(0.0),)) == ()
    assert gate.push(()) == ()
    assert gate.push((_detection(0.2),)) == ()
    assert gate.push((_detection(0.3),)) == (_detection(0.3),)
```

- [x] **Step 2: RED를 확인한다.**

Run: `uv run pytest -q tests/test_gme_temporal.py`

Expected: FAIL because `gme_temporal` does not exist.

- [x] **Step 3: streaming deadline clock와 bounded detection window를 구현한다.**

```python
@dataclass(slots=True)
class AnalysisClock:
    max_analysis_fps: float
    _next_deadline_number: int = 0

    def accept(self, frame_index: int, source_fps: float) -> bool:
        timestamp = frame_index / source_fps
        deadline = self._next_deadline_number / self.max_analysis_fps
        if timestamp + 1e-12 < deadline:
            return False
        self._next_deadline_number += 1
        return True


class TemporalDetectionGate:
    def __init__(self, *, window_frames: int, min_positive_frames: int) -> None:
        self._window = deque(maxlen=window_frames)
        self._minimum = min_positive_frames

    def push(self, detections: tuple[Detection, ...]) -> tuple[Detection, ...]:
        self._window.append(bool(detections))
        return detections if sum(self._window) >= self._minimum else ()
```

Constructor는 finite positive fps, positive window, `1 <= minimum <= window`를 검증한다.

- [x] **Step 4: GMEConfig와 engine RED 테스트를 추가한다.**

```python
def test_v26_engine_decodes_all_frames_and_analyzes_at_exact_10fps(monkeypatch):
    cap = FakeCapture(_frames(26), 25.0)
    detector = SequenceDetector([True] * 11)
    monkeypatch.setattr("gecko_vision_gate.gme_engine.cv2.VideoCapture", lambda _: cap)
    result = analyze_clip("clip.mp4", detector=detector, config=GMEConfig.v26())
    assert result.decoded_frame_count == 26
    assert result.analyzed_frame_count == 11
    assert detector.calls == pytest.approx([0.0, .12, .2, .32, .4, .52, .6, .72, .8, .92, 1.0])
```

- [x] **Step 5: v2.6 config에서 모든 analysis frame을 detector에 보내고 temporal gate 뒤 tracker에 전달한다.**

`GMEConfig.v26()`는 다음 exact 값을 반환한다.

```python
return cls(
    analysis_fps=10.0,
    anchor_interval_sec=0.1,
    detection_window_frames=5,
    detection_min_positive_frames=3,
    detector_every_analysis_frame=True,
)
```

legacy config는 기존 0.5초 anchor 경로를 유지한다. v2.6 경로는 `AnalysisClock`으로 frame을 선택하고
매 analysis frame의 raw detection을 `TemporalDetectionGate`에 넣은 결과만 `update_anchor()`에 전달한다.
exposure transition은 tracker와 temporal window를 함께 reset한다.

- [x] **Step 6: v2.6 adapter identity와 post NMS RED 테스트를 작성한다.**

```python
def test_v26_execution_identity_is_frozen(tmp_path):
    detector = build_yolo_detector(
        checkpoint=_checkpoint(tmp_path), expected_sha256=V26_SHA,
        model_version="v2.6-warm-start-s28", score_threshold=0.15,
        post_nms_iou=0.55, analysis_fps=10.0,
        temporal_window_frames=5, temporal_min_positive_frames=3,
        model_factory=lambda _: _Model(_empty_result()),
    )
    assert detector.execution_identity == V26_IDENTITY

def test_post_nms_suppresses_overlapping_lower_score_box(tmp_path):
    detector = _v26_detector(tmp_path, boxes=_overlapping_boxes())
    assert [row.confidence for row in detector.detect(_frame(), 0.0)] == [0.91]
```

- [x] **Step 7: canonical execution contract를 구현한다.**

```python
contract = {
    "schema": "gme-yolo-execution-v2",
    "model_name": "yolo26n",
    "model_version": model_version,
    "checkpoint_sha256": actual_sha256,
    "detector_schema_version": SCHEMA_VERSION,
    "raw_confidence": raw_confidence,
    "score_threshold": score_threshold,
    "image_size": image_size,
    "model_nms_iou": nms_iou,
    "post_nms_iou": post_nms_iou,
    "max_detections": max_detections,
    "analysis_fps": analysis_fps,
    "temporal_window_frames": temporal_window_frames,
    "temporal_min_positive_frames": temporal_min_positive_frames,
}
identity = sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
```

`detector_identity()`는 `execution_identity`가 있는 detector에서 그 값을 사용하고, 기존 RF-DETR/v2.5
detector는 이전 pipe-delimited identity 계산을 유지한다. bbox는 score filter 뒤 confidence/geometry
stable sort로 post NMS `0.55`를 적용한다.

- [x] **Step 8: Gate 전체 검증을 실행한다.**

Run: `uv run pytest -q`

Expected: PASS, v2.5 legacy identity regression 포함.

- [x] **Step 9: Gate 변경을 commit한다.**

```bash
git add src/gecko_vision_gate/gme_temporal.py src/gecko_vision_gate/gme_contracts.py \
  src/gecko_vision_gate/gme_engine.py src/gecko_vision_gate/gme_yolo_detector.py \
  tests/test_gme_temporal.py tests/test_gme_engine.py tests/test_gme_yolo_detector.py
git commit -m "feat: GME YOLO v2.6 시간축 계약"
```

### Task 2: Nightly GME worker를 v2.6 identity로 일반화

**Repo:** `/Users/baek/petcam-nightly-reporter`

**Files:**
- Modify: `reporter/config.py`
- Modify: `reporter/gme_worker.py`
- Modify: `.env.example`
- Modify: `install-launchd-gme.sh`
- Modify: `tests/test_gme_worker.py`
- Modify: `tests/test_install_launchd_gme.py`

**Interfaces:**
- Consumes: Task 1 `build_yolo_detector()`와 `GMEConfig.v26()`.
- Produces: exact v2.6 config/provenance를 가진 `com.petcam.gme-worker` one-shot runtime.

- [x] **Step 1: strict v2.6 config RED 테스트를 작성한다.**

```python
def test_v26_runtime_provenance_contains_full_execution_contract(monkeypatch):
    detector, provenance = _build_runtime_detector()
    assert provenance == {
        "model_name": "yolo26n", "model_version": "v2.6-warm-start-s28",
        "checkpoint_sha256": V26_SHA, "detector_identity": V26_IDENTITY,
        "raw_confidence": 0.001, "threshold": 0.15, "image_size": 960,
        "model_nms_iou": 0.70, "post_nms_iou": 0.55,
        "max_detections": 50, "analysis_fps": 10.0,
        "temporal_window_frames": 5, "temporal_min_positive_frames": 3,
    }
```

- [x] **Step 2: RED를 확인한다.**

Run: `uv run pytest -q tests/test_gme_worker.py tests/test_install_launchd_gme.py`

Expected: FAIL on missing v2.6 configuration.

- [x] **Step 3: exact 환경변수와 detector builder를 구현한다.**

추가·변경할 non-secret 변수는 다음과 같다.

```text
GME_MODEL_VERSION=v2.6-warm-start-s28
GME_CHECKPOINT_SHA256=a00e5a7a1e1f9197accb036339a38a7c821f03c8ab79611ebce89e5cde59b513
GME_DETECTOR_IDENTITY=89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7
GME_RAW_CONFIDENCE=0.001
GME_SCORE_THRESHOLD=0.15
GME_IMAGE_SIZE=960
GME_NMS_IOU=0.70
GME_POST_NMS_IOU=0.55
GME_MAX_DETECTIONS=50
GME_ANALYSIS_FPS=10
GME_TEMPORAL_WINDOW_FRAMES=5
GME_TEMPORAL_MIN_POSITIVE_FRAMES=3
```

worker는 media download 전에 job identity와 local execution identity를 비교한다. `_run_payload()`의
`detector_provenance`에는 위 계약 전체와 freeze SHA를 저장한다. engine은 `GMEConfig.v26()`을 사용하고
환경값과 config 값이 다르면 DB/R2 access 전에 exit 2로 끝난다.

- [x] **Step 4: LaunchAgent installer의 exact contract 검증을 갱신한다.**

installer는 checkpoint 절대경로와 위 literal 값을 모두 plist에 전달한다. secret은 기존 repo `.env`에서만
읽고 plist·stdout에 넣지 않는다. `WorkingDirectory`, expected hostname, interval 60초, batch `1..50`을
검증한다.

- [x] **Step 5: worker 관련 회귀를 실행한다.**

Run: `uv run pytest -q tests/test_gme_worker.py tests/test_gme_runtime_policy.py tests/test_install_launchd_gme.py tests/test_enqueue_gme_smoke.py tests/test_enqueue_gme_backfill.py tests/test_audit_gme_shadow.py`

Expected: PASS.

- [x] **Step 6: Nightly GME 변경을 commit한다.**

```bash
git add reporter/config.py reporter/gme_worker.py .env.example install-launchd-gme.sh \
  tests/test_gme_worker.py tests/test_install_launchd_gme.py
git commit -m "feat: GME worker를 YOLO v2.6으로 전환"
```

### Task 3: 인증된 v2.6 HTTP inference worker

**Repo:** `/Users/baek/petcam-nightly-reporter`

**Files:**
- Create: `reporter/yolo_http_worker.py`
- Create: `install-launchd-yolo-http-worker.sh`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.env.example`
- Create: `tests/test_yolo_http_worker.py`
- Create: `tests/test_install_launchd_yolo_http_worker.py`

**Interfaces:**
- Consumes: Task 2의 exact detector factory와 v2.6 config.
- Produces: `GET /health`, token-authenticated `POST /v1/infer`, localhost `127.0.0.1:8765`, service `com.petcam.yolo-http-worker`.

- [x] **Step 1: auth·size·decode·response RED 테스트를 작성한다.**

```python
def test_infer_rejects_missing_worker_token(client):
    response = client.post("/v1/infer", files={"media": ("x.jpg", JPEG, "image/jpeg")})
    assert response.status_code == 401

def test_image_infer_returns_normalized_v26_boxes(client, auth):
    response = client.post(
        "/v1/infer", headers=auth,
        data={"request_id": "req-1", "training_consent": "false"},
        files={"media": ("x.jpg", JPEG, "image/jpeg")},
    )
    assert response.json()["model_version"] == "v2.6-warm-start-s28"
    assert response.json()["provider_mode"] == "worker"
    assert response.json()["frames"][0]["detections"][0]["bbox"] == {
        "x": .1, "y": .2, "width": .3, "height": .4,
    }

def test_video_decode_uses_at_most_10fps_and_releases_capture(client, auth):
    response = _post_video(client, auth, fps=25.0, frames=26)
    assert [row["frame_index"] for row in response.json()["frames"]] == [0, 3, 5, 8, 10, 13, 15, 18, 20, 23, 25]
    assert FAKE_CAPTURE.released is True
```

- [x] **Step 2: RED를 확인한다.**

Run: `uv run pytest -q tests/test_yolo_http_worker.py tests/test_install_launchd_yolo_http_worker.py`

Expected: FAIL because the HTTP worker does not exist.

- [x] **Step 3: FastAPI worker를 구현한다.**

`uv add fastapi uvicorn python-multipart`로 dependency를 추가한다. worker는:

- `hmac.compare_digest()`로 `Authorization: Bearer` token을 검증한다.
- upload를 1MiB chunk로 읽어 image 10MiB/video 50MiB를 넘기기 전에 413으로 끝낸다.
- magic byte와 declared content type을 함께 확인한다.
- image는 최대 20MP, video는 최대 60초·1920x1080을 검증한다.
- 요청별 `TemporaryDirectory`만 사용하고 finally에서 VideoCapture를 release한다.
- 같은 process에서 detector를 한 번만 load하며 common Gate lock으로 GME worker와 동시 MPS 사용을 막는다.
- raw media, bbox, token, 원본 filename을 로그·DB·R2에 저장하지 않는다.
- response는 `request_id`, `media_kind`, model version, `provider_mode=worker`, RFC3339 time, warning,
  `frames[]`, consent에 따른 contribution status를 반환한다.

- [x] **Step 4: LaunchAgent installer를 구현한다.**

```text
label=com.petcam.yolo-http-worker
program=uv run uvicorn reporter.yolo_http_worker:app --host 127.0.0.1 --port 8765
working_directory=exact nightly repo
keep_alive=true
expected_host=baeg-endeuui-Macmini.local
```

token은 `.env`의 `YOLO_HTTP_WORKER_TOKEN`에서 읽고 plist에 쓰지 않는다. installer는 `.env` mode가
group/world-readable이면 중단하고 `plutil -lint`를 통과해야 한다.

- [x] **Step 5: HTTP worker와 Nightly 전체 검증을 실행한다.**

Run: `uv run pytest -q`

Expected: PASS, temp residue 0, DB/R2 mock call 0.

- [x] **Step 6: HTTP worker 변경을 commit한다.**

```bash
git add reporter/yolo_http_worker.py install-launchd-yolo-http-worker.sh pyproject.toml uv.lock \
  .env.example tests/test_yolo_http_worker.py tests/test_install_launchd_yolo_http_worker.py
git commit -m "feat: YOLO v2.6 인증 추론 worker"
```

### Task 4: v2.6 live enqueue와 public rate-limit 원장

**Repo:** `/Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab`

**Files:**
- Create: `migrations/2026-08-31_yolo26n_v26_gme_production_normalization.sql`
- Create: `tests/test_yolo26n_v26_gme_production_normalization_migration.py`
- Modify: `docs/DATABASE.md`

**Interfaces:**
- Consumes: v2.6 smoke 10건과 current v2.5 live trigger identity.
- Produces: v2.6 live enqueue function, `fn_consume_yolo_demo_rate_limit(text,timestamptz,integer,integer)`.

- [x] **Step 1: migration RED 테스트를 작성한다.**

```python
def test_v26_migration_requires_exact_smoke_and_current_v25_trigger():
    assert "smoke_complete < 10" in SQL
    assert V25_IDENTITY in SQL
    assert V26_IDENTITY in SQL

def test_migration_preserves_append_only_history():
    lowered = SQL.lower()
    assert "delete from public.gme_jobs" not in lowered
    assert "delete from public.gme_runs" not in lowered
    assert "update public.gme_runs" not in lowered

def test_rate_limit_rpc_is_service_role_only():
    assert "revoke all on function public.fn_consume_yolo_demo_rate_limit" in SQL.lower()
    assert "grant execute on function public.fn_consume_yolo_demo_rate_limit" in SQL.lower()
```

- [x] **Step 2: RED를 확인한다.**

Run: `uv run pytest -q tests/test_yolo26n_v26_gme_production_normalization_migration.py`

Expected: FAIL because migration does not exist.

- [x] **Step 3: fail-closed live cutover migration을 작성한다.**

한 transaction 안에서 base schema, v2.6 smoke `>=10`, v2.5 current function identity, trigger count 1을
검증한 뒤 `fn_enqueue_gme_live_job()`의 detector identity만 v2.6 literal로 교체한다. production-purpose만
enqueue하며 rollback SQL은 v2.5 identity 함수 본문을 복원한다.

- [x] **Step 4: distributed fixed-window rate-limit RPC를 작성한다.**

`yolo_demo_rate_limits(key_hash text, window_started_at timestamptz, attempts integer)`는 service-role only다.
RPC는 advisory transaction lock으로 같은 hashed requester를 직렬화하고 600초 window에서 최대 5회를
허용하며 `{allowed,retry_after_sec}`를 반환한다. raw IP는 저장하지 않고 web server가 HMAC-SHA256한
64자리 key만 받는다. 24시간보다 오래된 bucket은 요청 경계에서 최대 100개씩 삭제한다.

- [x] **Step 5: migration 회귀를 실행한다.**

Run: `uv run pytest -q tests/test_yolo26n_v26_gme_production_normalization_migration.py tests/test_yolo26n_v25_gme_active_shadow_migration.py tests/test_gecko_motion_engine_migration.py tests/test_gecko_motion_engine_cutover.py`

Expected: PASS.

- [x] **Step 6: DB 문서와 migration을 commit한다.**

```bash
git add migrations/2026-08-31_yolo26n_v26_gme_production_normalization.sql \
  tests/test_yolo26n_v26_gme_production_normalization_migration.py docs/DATABASE.md
git commit -m "feat: GME live enqueue를 YOLO v2.6으로 전환"
```

### Task 5: 라벨링 웹 overlay를 v2.6 identity에 고정

**Repo:** `/Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab`

**Files:**
- Modify: `web/.env.example`
- Modify: `web/src/lib/gmeOverlay.ts`
- Modify: `web/src/lib/gmeOverlayServer.ts`
- Modify: `web/src/lib/gmeOverlayServer.test.ts`
- Modify: `web/src/app/api/labeling-v3/[clipId]/gme-overlay/route.ts`
- Modify: `web/src/app/api/labeling-v3/blind/[clipId]/gme-overlay/route.ts`
- Modify: `web/src/app/labeling/_gme-overlay.tsx`
- Modify: `web/src/app/labeling/_gme-overlay.test.tsx`

**Interfaces:**
- Consumes: server-only `GME_ACTIVE_DETECTOR_IDENTITY`.
- Produces: `GmeOverlayState = 'ready' | 'pending' | 'unavailable'`, exact v2.6 source selection, safe `model_version='v2.6'` response.

- [x] **Step 1: old-latest fallback를 거부하는 RED 테스트를 작성한다.**

```typescript
it('selects only the active v2.6 identity and never falls back to v2.5', async () => {
  process.env.GME_ACTIVE_DETECTOR_IDENTITY = V26_IDENTITY;
  await loadCurrentGmeOverlayStatus(CLIP_ID);
  expect(jobQuery.eq).toHaveBeenCalledWith('detector_identity', V26_IDENTITY);
});

it('returns pending without exposing detector identity', async () => {
  jobQuery.result = [{ status: 'processing', result_run_id: null }];
  expect(await loadCurrentGmeOverlayStatus(CLIP_ID)).toEqual({ state: 'pending' });
});
```

- [x] **Step 2: RED를 확인한다.**

Run: `cd web && npm test -- src/lib/gmeOverlayServer.test.ts src/app/api/labeling-v3/[clipId]/gme-overlay/route.test.ts`

Expected: FAIL because active identity/state filtering is missing.

- [x] **Step 3: exact identity status loader를 구현한다.**

`loadCurrentGmeOverlayStatus(clipId)`는 64자리 env가 없거나 invalid면 throw한다. job query는 clip과
detector identity가 모두 일치하는 최신 row 하나만 읽는다. succeeded일 때 run도 같은 clip·identity·ok
상태인지 확인한다. browser response는 다음 safe shape만 사용한다.

```typescript
type GmeOverlayResponse = {
  state: 'ready' | 'pending' | 'unavailable';
  available: boolean;
  model_version: 'v2.6';
  overlay_revision: string | null;
  duration_sec: number;
  points: GmeOverlayPoint[];
};
```

- [x] **Step 4: Owner와 blind route/UI를 상태별로 갱신한다.**

- pending: `YOLO v2.6 분석 대기 중`
- unavailable: `YOLO v2.6 결과를 확인할 수 없어. 사람 판정은 계속할 수 있어.`
- ready/no points: `영상 전체에서 YOLO v2.6 탐지 없음`
- ready/points: 기존 box와 피드백 버튼 표시

어느 상태에서도 v2.5 run을 fallback하지 않고 사람 라벨링·GT 저장을 막지 않는다.

- [x] **Step 5: overlay web 검증을 실행한다.**

Run: `cd web && npm test -- src/lib/gmeOverlay.test.ts src/lib/gmeOverlayServer.test.ts src/app/labeling/_gme-overlay.test.tsx src/app/api/labeling-v3/[clipId]/gme-overlay/route.test.ts src/app/api/labeling-v3/blind/[clipId]/gme-overlay/route.test.ts`

Expected: PASS, detector identity/run UUID/R2 key response 0.

- [x] **Step 6: overlay 변경을 commit한다.**

```bash
git add web/.env.example web/src/lib/gmeOverlay.ts web/src/lib/gmeOverlayServer.ts \
  web/src/lib/gmeOverlayServer.test.ts web/src/app/api/labeling-v3/[clipId]/gme-overlay/route.ts \
  web/src/app/api/labeling-v3/blind/[clipId]/gme-overlay/route.ts \
  web/src/app/labeling/_gme-overlay.tsx web/src/app/labeling/_gme-overlay.test.tsx
git commit -m "fix: 라벨링 overlay를 YOLO v2.6에 고정"
```

### Task 6: `/gecko-detector` 실제 worker와 distributed limiter 연결

**Repo:** `/Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab`

**Files:**
- Create: `web/src/lib/yoloHttpWorkerProvider.ts`
- Create: `web/src/lib/yoloRateLimitServer.ts`
- Create: `web/src/lib/yoloHttpWorkerProvider.test.ts`
- Create: `web/src/lib/yoloRateLimitServer.test.ts`
- Modify: `web/src/lib/yoloDetectionServer.ts`
- Modify: `web/src/lib/yoloDetectionServer.test.ts`
- Modify: `web/src/app/api/yolo-demo/infer/route.ts`
- Modify: `web/src/app/api/yolo-demo/infer/route.test.ts`
- Modify: `web/src/app/gecko-detector/page.tsx`
- Modify: `web/src/app/gecko-detector/_detection-overlay.tsx`
- Modify: `web/.env.example`

**Interfaces:**
- Consumes: `YOLO_WORKER_URL`, `YOLO_WORKER_TOKEN`, `YOLO_RATE_LIMIT_HMAC_SECRET`, Task 4 RPC.
- Produces: `HttpGeckoDetectionProvider.analyze(input)`, `SupabaseYoloRateLimiter.consume(key, nowMs)`.

- [x] **Step 1: HTTP adapter RED 테스트를 작성한다.**

```typescript
it('authenticates worker request and requires exact v2.6 response', async () => {
  const provider = new HttpGeckoDetectionProvider({
    url: 'https://yolo-worker.tera-ai.uk/v1/infer', token: 'worker-token',
    fetcher, timeoutMs: 180_000,
  });
  const result = await provider.analyze(INPUT);
  expect(fetcher).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({
    method: 'POST', redirect: 'error', cache: 'no-store',
    headers: { Authorization: 'Bearer worker-token' },
  }));
  expect(result.model_version).toBe('v2.6-warm-start-s28');
  expect(result.provider_mode).toBe('worker');
});

it('rejects worker redirects, timeout, wrong request id and wrong model', async () => {
  await expect(provider.analyze(INPUT)).rejects.toThrow('inference unavailable');
});
```

- [x] **Step 2: distributed limiter RED 테스트를 작성한다.**

```typescript
it('HMACs requester identity before the RPC and maps retry time', async () => {
  const result = await limiter.consume('203.0.113.7', NOW);
  expect(rpc).toHaveBeenCalledWith('fn_consume_yolo_demo_rate_limit', expect.objectContaining({
    p_key_hash: expect.stringMatching(/^[0-9a-f]{64}$/), p_limit: 5, p_window_sec: 600,
  }));
  expect(JSON.stringify(rpc.mock.calls)).not.toContain('203.0.113.7');
  expect(result).toEqual({ allowed: false, retryAfterSec: 42 });
});
```

- [x] **Step 3: RED를 확인한다.**

Run: `cd web && npm test -- src/lib/yoloHttpWorkerProvider.test.ts src/lib/yoloRateLimitServer.test.ts src/app/api/yolo-demo/infer/route.test.ts`

Expected: FAIL because real provider and limiter do not exist.

- [x] **Step 4: bounded HTTP provider와 async limiter interface를 구현한다.**

provider는 `AbortSignal.timeout(180_000)`, HTTPS only, redirect error, 2MiB response body 상한을 적용하고
기존 `validateDetectionResult()` 뒤 request id/media kind/model version/provider mode/consent status를 다시
확인한다. `RateLimiter.consume`은 `Promise<RateLimitResult>`로 바꾸고 fake test limiter도 async로 맞춘다.

- [x] **Step 5: production route dependency를 실제 provider로 바꾼다.**

development/test는 deterministic fake를 유지한다. production은 세 secret env와 64자리 active identity가
모두 있을 때만 HTTP provider+Supabase limiter를 만든다. 하나라도 없으면 503이고 fake response를 내지
않는다. `export const maxDuration = 300`을 설정하고 worker timeout은 그보다 짧게 유지한다.

- [x] **Step 6: 페이지 설명과 결과 badge를 v2.6으로 갱신한다.**

production 페이지는 fake 안내를 제거하고 `현재 분석 모델: YOLO v2.6`, `연구용 결과이며 사람 확인 필요`를
표시한다. response의 model version이 다르면 결과를 그리지 않는다.

- [ ] **Step 7: web 전체 검증을 실행한다.** — 1,274 tests·TypeScript PASS, local build는 resource hook으로 Task 8에 이관.

Run: `cd web && npm test && npx tsc --noEmit && npm run build`

Expected: PASS.

- [x] **Step 8: 실제 worker 연결을 commit한다.**

```bash
git add web/src/lib/yoloHttpWorkerProvider.ts web/src/lib/yoloRateLimitServer.ts \
  web/src/lib/yoloHttpWorkerProvider.test.ts web/src/lib/yoloRateLimitServer.test.ts \
  web/src/lib/yoloDetectionServer.ts web/src/lib/yoloDetectionServer.test.ts \
  web/src/app/api/yolo-demo/infer/route.ts web/src/app/api/yolo-demo/infer/route.test.ts \
  web/src/app/gecko-detector/page.tsx web/src/app/gecko-detector/_detection-overlay.tsx web/.env.example
git commit -m "feat: 라벨링 웹에 YOLO v2.6 worker 연결"
```

### Task 7: 문서·cross-repo runtime handoff 고정

**Repo:** `/Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab`

**Files:**
- Create: `docs/handoff-prompts/2026-08-31-yolo26n-v26-production-normalization-runtime-handoff.md`
- Modify: `docs/FEATURES.md`
- Modify: `docs/ENV.md`
- Modify: `specs/next-session.md`
- Modify: `docs/superpowers/specs/2026-08-31-yolo26n-v26-production-normalization-design.md`
- Modify: `docs/superpowers/plans/2026-08-31-yolo26n-v26-production-normalization.md`

**Interfaces:**
- Consumes: Task 1~6의 세 repository commit SHA.
- Produces: tracked/clean manifest와 `HANDOFF_OK`.

- [x] **Step 1: 운영 문서를 실제 구현과 맞춘다.**

`FEATURES`에는 v2.6 default overlay와 fake 503 종료를, `ENV`에는 네 server-only web env와 Nightly
v2.6 non-secret contract를, `next-session`에는 v2.7보다 정상화/backfill이 우선임을 기록한다.

- [x] **Step 2: design·plan·운영 문서를 먼저 commit하고 기준 SHA를 고정한다.**

handoff manifest는 아직 만들지 않는다. 다음 문서와 Task 4~6의 petcam-lab 구현이 모두 검증된 상태에서
먼저 commit한 뒤, `git rev-parse HEAD`의 40자리 값을 `BASE_SHA`로 기록한다.

```bash
git add docs/FEATURES.md docs/ENV.md specs/next-session.md docs/decision-gate.md \
  docs/superpowers/specs/2026-08-31-yolo26n-v26-production-normalization-design.md \
  docs/superpowers/plans/2026-08-31-yolo26n-v26-production-normalization.md
git commit -m "docs: YOLO v2.6 운영 정상화 설계"
git rev-parse HEAD
```

- [ ] **Step 3: manifest front matter를 방금 고정한 실제 `BASE_SHA`로 작성한다.**

```yaml
handoff_version: 1
task_id: yolo26n-v26-production-normalization
execution_repo: /Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab
plan_path: /Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/docs/superpowers/plans/2026-08-31-yolo26n-v26-production-normalization.md
design_path: /Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/docs/superpowers/specs/2026-08-31-yolo26n-v26-production-normalization-design.md
commit_sha: <Step 2에서 기록한 실제 40자리 BASE_SHA>
implementation_host: BaekBook-Pro-14-M5.local
runtime_kind: launchagent
runtime_host: baeg-endeuui-Macmini.local
runtime_label: com.petcam.gme-worker
```

본문에는 Gate/Nightly commit, model/freeze/report SHA, v2.6 identity, `com.petcam.yolo-http-worker`,
`yolo-worker.tera-ai.uk`, smoke/cutover/backfill/rollback 순서를 literal로 기록한다.

- [ ] **Step 4: manifest만 정확히 한 개의 후속 commit으로 고정한다.**

verifier는 manifest가 가리키는 `BASE_SHA`보다 현재 HEAD가 한 commit 앞인 경우, 그 한 commit이 manifest만
변경했을 때만 허용한다. 따라서 이 commit에는 다른 파일을 포함하지 않는다.

```bash
git add docs/handoff-prompts/2026-08-31-yolo26n-v26-production-normalization-runtime-handoff.md
git commit -m "docs: YOLO v2.6 runtime handoff"
```

- [ ] **Step 5: tracked clean과 handoff verifier를 확인한다.**

Run:

```bash
git status --short -- docs/handoff-prompts/2026-08-31-yolo26n-v26-production-normalization-runtime-handoff.md \
  docs/superpowers/specs/2026-08-31-yolo26n-v26-production-normalization-design.md \
  docs/superpowers/plans/2026-08-31-yolo26n-v26-production-normalization.md
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/.codex/worktrees/yolo-v26-recent-dense/petcam-lab/docs/handoff-prompts/2026-08-31-yolo26n-v26-production-normalization-runtime-handoff.md
```

Expected: status output empty, then `HANDOFF_OK`.

### Task 8: Mac mini preflight·model 설치·10건 smoke

**Runtime host:** `baeg-endeuui-Macmini.local`

**Files:**
- Create under private runtime: immutable model copy, model handoff manifest, smoke audit only.
- Modify via verified installers: two LaunchAgent plist files after smoke acceptance.

**Interfaces:**
- Consumes: Task 7 `HANDOFF_OK`, exact three repo commits, checkpoint/freeze bytes.
- Produces: v2.6 smoke `10/10`, service-ready but live trigger unchanged.

- [ ] **Step 1: runtime read-only preflight를 실행한다.**

hostname/time, three repo HEAD/dirty, current v2.5 LaunchAgent/working directory, DB migration state, GME
job source/status counts, retry/terminal failures, disk free, checkpoint source SHA를 확인한다. mismatch면 어떤
service/DB/R2도 수정하지 않고 중단한다.

- [ ] **Step 2: exact commits를 새 runtime worktree에 checkout하고 전체 테스트를 실행한다.**

Run: Gate `uv run pytest -q`; Nightly `uv run pytest -q`; lab `uv run pytest -q`; web `npm test && npx tsc --noEmit && npm run build`.

Expected: all PASS and worktrees clean.

- [ ] **Step 3: checkpoint를 private runtime에 immutable copy하고 SHA를 검증한다.**

mode 0600, parent 0700을 확인하고 actual SHA가 `a00e5a7a…59b513`와 exact 일치해야 한다. model load
one-frame smoke는 DB/R2 write 없이 실행한다.

- [ ] **Step 4: v2.6 identity로 exactly 10 production smoke jobs를 enqueue한다.**

dry-run selected 10, purpose production, media/decode eligible, existing v2.6 job 0을 먼저 확인한다. apply는
한 번만 실행하고 동일 command 재실행이 inserted 0인지 확인한다.

- [ ] **Step 5: bounded worker로 smoke를 처리하고 독립 audit한다.**

Expected: succeeded 10, retry/terminal 0, run identity 10/10, artifact key/SHA/bytes complete, temp residue 0,
original object write 0, allowlist 밖 write 0.

### Task 9: live·HTTP worker·라벨링 웹 직접 전환

**Runtime/Deploy:** Mac mini, Supabase production, Vercel production.

**Interfaces:**
- Consumes: Task 8 smoke acceptance.
- Produces: 신규 v2.6 live processing, exact v2.6 web overlay, working `/gecko-detector`.

- [ ] **Step 1: production DB migration을 한 transaction으로 적용한다.**

적용 직후 SELECT-only로 trigger count 1, function body v2.6 identity, v2.5/v2.6 historical run count 불변을
확인한다. rate-limit table/function privilege는 service-role only여야 한다.

- [ ] **Step 2: `com.petcam.gme-worker`를 v2.6 config로 설치·기동한다.**

`launchctl print`에서 loaded/running, correct working directory, 60초 interval, expected host, batch 50,
v2.6 identity를 확인한다. secret과 checkpoint full path는 사용자 보고에 출력하지 않는다.

- [ ] **Step 3: HTTP worker와 dedicated tunnel을 설치한다.**

`com.petcam.yolo-http-worker`는 localhost 8765에서 health 200이어야 한다. Cloudflare named tunnel
`petcam-yolo-worker`는 `yolo-worker.tera-ai.uk -> http://127.0.0.1:8765`만 전달한다. tunnel credential은
0600 파일에 두고 git/plist/log에 넣지 않는다. 외부 unauthenticated infer는 401, Vercel token request만
200이어야 한다.

- [ ] **Step 4: 신규 live 1건 end-to-end를 확인한다.**

새 production clip이 v2.6 live job을 만들고 succeeded run/artifact로 끝나는지 확인한다. v2.5 신규 job은
0이어야 하고 live lag는 900초 이내여야 한다.

- [ ] **Step 5: Vercel Preview를 배포하고 Owner canary를 수행한다.**

Preview env에 active identity, worker URL/token, rate-limit HMAC secret을 설정한다. Owner account로:

1. v2.6 완료 clip의 box 표시
2. v2.6 pending clip의 대기 표시
3. v2.5-only clip의 old box 미표시
4. 미탐/오탐/bad-box feedback save
5. `/gecko-detector` image 1건/video 1건 실제 v2.6 response
6. 잘못된 token 401, worker down 503, fake response 0

을 확인한다.

- [ ] **Step 6: Vercel production을 배포하고 같은 canary를 반복한다.**

deployment READY, custom domain 200, console error 0, API response model `v2.6-warm-start-s28`, secret/browser
exposure 0을 확인한다.

### Task 10: 저장 영상 backfill·운영 감사·v2.7 gate

**Runtime host:** `baeg-endeuui-Macmini.local`

**Interfaces:**
- Consumes: Task 9 live/web acceptance.
- Produces: first 50 acceptance, complete background backfill, operational completion report.

- [ ] **Step 1: historical dry-run inventory를 고정한다.**

production purpose, source media present, decode eligible, v2.6 job/run absent 조건의 selected count와
test/quarantine/deleted/source-missing/existing 제외 count만 기록한다. 개별 clip/source key는 보고하지 않는다.

- [ ] **Step 2: first batch 50을 enqueue·처리·감사한다.**

Expected: 50/50 succeeded, retry/terminal 0, provenance 50/50, artifact fields complete, live lag p95 <=900초.

- [ ] **Step 3: 나머지 historical을 keyset batch로 enqueue한다.**

worker는 live priority를 먼저 claim한다. live lag가 900초를 넘으면 historical claim을 자동 중단하고
lag가 회복되면 다음 자연 cycle에서 재개한다. failed_terminal은 자동 재queue하지 않고 즉시 보고한다.

- [ ] **Step 4: completion을 read-only 재검수한다.**

historical queued/processing/retry/terminal 0, selected=succeeded, same identity run count 일치, artifact key/SHA
missing 0, v2.5 rows unchanged, raw media/GT mutation 0을 확인한다.

- [ ] **Step 5: 운영 완료 보고와 v2.7 시작 조건을 기록한다.**

보고에는 신규 coverage, historical total/succeeded, live lag p50/p95, retry/terminal, web production deployment,
`/gecko-detector` canary, rollback 준비 상태를 포함한다. 이 시점 이후에만 v2.7 데이터 준비·학습 계획을
재개한다.
