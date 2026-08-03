# Gecko Motion Engine Production Shadow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Every behavior change follows RED → GREEN → REFACTOR.

**Goal:** 신규 재생 가능 `motion_clips` 전부와 KST 2026-07-15 이후 eligible 기존 영상을 Mac mini에서 Gecko Motion Engine(GME)으로 분석해, 사용자 값과 GT를 건드리지 않는 `candidate` 활동시간·추적 품질·파생 산출물을 저장한다.

**Architecture:** `gecko-vision-gate`가 detector-agnostic GME 코어와 순차 디코더를 소유하고, `petcam-lab`이 독립 durable queue·append-only run 원장·전환 SQL을 소유하며, `petcam-nightly-reporter`가 Mac mini host guard·R2 입출력·live 우선 claim·backfill pause·LaunchAgent를 소유한다. 기존 Python Evidence의 테이블·run·코드·원본 R2는 그대로 보존한다. 10개 실제 영상 operational smoke를 통과한 뒤에만 신규 enqueue를 GME로 원자 전환하고 기존 LaunchAgent를 내린다.

**Tech Stack:** Python 3.12, OpenCV, NumPy, RF-DETR detector adapter, FastAPI/Supabase PostgreSQL RPC, boto3/Cloudflare R2, launchd, pytest, uv.

## Global Constraints

- GME 출력은 `candidate` shadow다. Flutter/API, `activity-v1`, GT, 행동명, 하이라이트, VLM route를 변경하지 않는다.
- GME 결과로 영상 skip·원본 삭제·게코 부재 확정·행동 정답 확정을 하지 않는다.
- 한 영상은 한 번 순차 디코딩하고 전체 프레임 배열을 메모리에 쌓지 않는다.
- 원본 30fps 이하는 전 분석, 초과 원본은 분석 시계를 최대 30fps로 제한한다.
- detector anchor는 기본 0.5초이며 tracker 신뢰도 하락 시 즉시 재검출한다.
- 위치 provenance는 `observed/tracked/interpolated/unknown`을 분리한다. 1.0초 초과 gap은 보정하지 않는다.
- `moving/static/not_visible/unknown/camera_motion`을 구분한다. 검출 실패를 자동으로 `not_visible`로 바꾸지 않는다.
- 여러 마리는 track을 분리하고 identity를 억지로 연결하지 않는다.
- DB에는 clip/run 요약과 bounded 상태구간만 둔다. 영구 trajectory와 상태전환은 R2 GME 전용 prefix, 상세 debug는 별도 14일 prefix에 둔다.
- 원본 영상·과거 Python Evidence 원장·기존 사용자 데이터는 수정하거나 삭제하지 않는다.
- live job이 항상 backfill보다 먼저다. live lag p95가 15분을 넘으면 backfill claim만 멈춘다.
- 비밀값·이메일·전체 UUID·원문 GT를 코드, 테스트 fixture, 로그, 보고서에 넣지 않는다.
- 기존 dirty 파일을 revert, stash, reset하지 않는다. 각 저장소는 격리 worktree/branch에서 작업한다.

## Public Contracts

### Gate core Python API

```python
@dataclass(frozen=True, slots=True)
class Detection:
    timestamp_sec: float
    bbox_xywh: tuple[float, float, float, float]
    confidence: float
    class_name: str

class Detector(Protocol):
    model_name: str
    model_version: str
    checkpoint_sha256: str
    schema_version: str
    threshold: float
    def detect(self, frame_bgr: np.ndarray, timestamp_sec: float) -> tuple[Detection, ...]: ...

def analyze_clip(
    video_path: str | Path,
    *,
    detector: Detector,
    config: GMEConfig = GMEConfig(),
) -> GMEAnalysis: ...
```

`GMEAnalysis`는 최소한 clip metadata, state intervals, any-gecko candidate moving seconds,
moving gecko-seconds, visibility/unknown/camera-motion seconds, maximum simultaneous gecko count,
tracking quality, detector/tracker/engine provenance, compressed trajectory payload, debug payload를 반환한다.

### DB identity

- job identity: `(clip_id, engine_schema_version, algorithm_version, detector_identity)`
- run identity: 동일 네 필드 + immutable artifact digest
- live priority `100`, smoke `90`, historical `10`
- run row는 append-only, job row만 lease/status가 변경된다.

### R2 prefixes

- permanent: `terra-derived/gme/v1/permanent/<clip-id>/<run-identity>.json.gz`
- 14-day debug: `terra-derived/gme/v1/debug-14d/<clip-id>/<run-identity>.json.gz`
- worker는 이 두 prefix 외 PUT을 로컬 검증 단계에서 거부한다.
- lifecycle은 `debug-14d/` prefix에만 적용하며 원본 `terra-clips/clips/`와 절대 겹치지 않는다.

---

### Task 1: 격리 작업공간과 기준선 확정

**Files:**
- No production file changes.
- Create isolated branches/worktrees:
  - `petcam-lab`: current linked worktree를 유지하되 GME 파일만 명시 stage
  - `gecko-vision-gate`: `codex/gme-shadow-v0`
  - `petcam-nightly-reporter`: `codex/gme-shadow-v0`, 반드시 `origin/main`의 Mac mini HEAD `0eaa7ea77964c77511b7a1ba9f998bd27b0864af` 포함 여부를 먼저 확인

- [ ] **Step 1:** 세 저장소에서 `git status --short --branch`, `git rev-parse HEAD`, upstream을 저장한다.
- [ ] **Step 2:** Gate와 nightly의 기존 checkout에 있는 untracked 파일을 그대로 두고 격리 worktree를 만든다.
- [ ] **Step 3:** `uv sync` 후 기준 테스트를 실행한다.
  - Gate: `uv run pytest -q`
  - nightly: `uv run pytest -q`
  - lab: `uv run pytest -q`
- [ ] **Step 4:** 기준 실패가 있으면 새 변경과 분리해 기록하고 같은 영역의 실패는 해결 전 구현을 시작하지 않는다.

### Task 2: GME 코어 계약과 결과 스키마

**Repo:** `gecko-vision-gate`

**Files:**
- Create: `src/gecko_vision_gate/gme_contracts.py`
- Create: `src/gecko_vision_gate/gme_serialization.py`
- Create: `tests/test_gme_contracts.py`
- Create: `tests/test_gme_serialization.py`

- [ ] **Step 1 (RED):** frozen dataclass, allowlisted state/provenance, finite non-negative timestamps, normalized bbox 범위, interval 비중첩, artifact schema/version 검증 테스트를 작성한다.
- [ ] **Step 2:** `uv run pytest -q tests/test_gme_contracts.py tests/test_gme_serialization.py`가 누락 API로 실패하는지 확인한다.
- [ ] **Step 3 (GREEN):** `Detection`, `TrackPoint`, `StateInterval`, `TrackingQuality`, `ArtifactIdentity`, `GMEAnalysis`, `GMEConfig`, `Detector` protocol을 최소 구현한다.
- [ ] **Step 4:** permanent/debug payload를 canonical JSON으로 만들고 gzip round-trip과 SHA-256 digest를 구현한다.
- [ ] **Step 5:** 대상 테스트와 Gate 전체 테스트를 통과시킨다.

### Task 3: 다중 게코 연결과 provenance 보존

**Repo:** `gecko-vision-gate`

**Files:**
- Create: `src/gecko_vision_gate/gme_tracker.py`
- Create: `tests/test_gme_tracker.py`

- [ ] **Step 1 (RED):** 두 detection의 IoU/정규화 중심거리 deterministic association, 새 track 생성, 사라진 track 종료, 여러 마리 분리, tie 안정정렬 테스트를 작성한다.
- [ ] **Step 2 (RED):** anchor 사이 optical-flow/bbox tracking 결과는 `tracked`, detector anchor는 `observed`, 양쪽 anchor가 있는 1.0초 이하 gap만 `interpolated`, 긴 gap은 `unknown`인 테스트를 작성한다.
- [ ] **Step 3:** 테스트가 API 부재 또는 기대값 불일치로 실패하는지 확인한다.
- [ ] **Step 4 (GREEN):** Hungarian 추가 의존성 없이 작은 N에 맞는 confidence→IoU→distance 안정 greedy association을 구현한다.
- [ ] **Step 5 (GREEN):** OpenCV sparse LK optical flow로 bbox 내부 특징점을 따라가고, feature 수/forward-backward error/bbox jump로 tracker confidence를 계산한다.
- [ ] **Step 6:** fragmentation, possible ID switch, gap, jump, provenance 시간 비율, multi-gecko separation을 누적한다.
- [ ] **Step 7:** 대상 테스트와 전체 Gate 테스트를 통과시킨다.

### Task 4: 카메라 변화 분리와 실제 움직인 시간 후보 계산

**Repo:** `gecko-vision-gate`

**Files:**
- Create: `src/gecko_vision_gate/gme_motion.py`
- Create: `tests/test_gme_motion.py`

- [ ] **Step 1 (RED):** 정지 게코+전체 프레임 이동은 `camera_motion`, 화면은 고정+게코 bbox/몸영역 이동은 `moving`, 검출은 있으나 변화가 작으면 `static`인 합성 프레임 테스트를 작성한다.
- [ ] **Step 2 (RED):** IR/exposure 급변, timestamp overlay 제외영역, 반복 프레임, decode gap을 `unknown`/품질 flag로 보존하는 테스트를 작성한다.
- [ ] **Step 3 (RED):** 두 마리 동시 10초 이동이 any-gecko 10초, gecko-seconds 20초가 되는 interval union 테스트를 작성한다.
- [ ] **Step 4 (GREEN):** background feature 기반 global affine/translation 추정, 프레임 밝기 histogram 변화, freeze hash, overlay mask를 계산한다.
- [ ] **Step 5 (GREEN):** track displacement를 bbox 대각선(몸길이 proxy)과 normalized coordinates로 환산해 shadow-v0 moving/static 후보를 만든다. threshold는 `GMEConfig`와 provenance에 저장하고 검증 전 제품값으로 해석하지 않는다.
- [ ] **Step 6:** five-state interval을 결정론적으로 압축하고 any-gecko/ gecko-seconds/unknown/관찰 가능 시간을 계산한다.
- [ ] **Step 7:** 대상 테스트와 전체 Gate 테스트를 통과시킨다.

### Task 5: 한 번 순차 디코딩하는 GME 엔진

**Repo:** `gecko-vision-gate`

**Files:**
- Create: `src/gecko_vision_gate/gme_engine.py`
- Create: `src/gecko_vision_gate/gme_cli.py`
- Modify: `pyproject.toml`
- Create: `tests/test_gme_engine.py`
- Create: `tests/test_gme_cli.py`

- [ ] **Step 1 (RED):** fake `VideoCapture`로 모든 원본 프레임 decode, 최대 30fps analysis, detector 0.5초 anchor, confidence 하락 즉시 재검출, `release()` 보장 테스트를 작성한다.
- [ ] **Step 2 (RED):** 0프레임/잘못된 FPS/중간 decode 오류가 정상 부재가 아닌 typed terminal/unknown으로 반환되는 테스트를 작성한다.
- [ ] **Step 3:** 테스트 실패를 확인한다.
- [ ] **Step 4 (GREEN):** shared frame stream에서 tracker, motion, media QA를 호출하는 `analyze_clip()`을 구현한다. 전체 프레임 배열을 금지하고 직전 프레임·bounded track state만 유지한다.
- [ ] **Step 5 (GREEN):** 기존 `GeckoDetector`를 public `Detector` contract로 감싸는 adapter와 `gecko-gme` CLI를 추가한다.
- [ ] **Step 6:** CLI가 원본 경로·credential을 stdout에 노출하지 않고 redacted summary만 출력하는지 테스트한다.
- [ ] **Step 7:** `uv run pytest -q`와 작은 합성 mp4 CLI smoke를 통과시킨다.

### Task 6: GME 연구 라운드 기록

**Repo:** `gecko-vision-gate`

**Files:**
- Create: `reports/R0004-gme-shadow-v0.md`
- Modify: `reports/README.md`
- Modify: `README.md`
- Modify: `specs/architecture.md`

- [ ] **Step 1:** GME가 Gate v3 adoption을 우회하지 않는다는 점, algorithm threshold가 candidate라는 점, synthetic/unit 결과와 남은 정확도 위험을 기록한다.
- [ ] **Step 2:** detector adapter 계약과 `gecko-gme` 사용법을 문서화한다.
- [ ] **Step 3:** `rg`로 auto skip/behavior GT/user metric 오해 문구가 없는지 확인한다.

### Task 7: GME durable queue·append-only 원장 migration

**Repo:** `petcam-lab`

**Files:**
- Create: `migrations/2026-08-03_gecko_motion_engine_shadow.sql`
- Create: `tests/test_gecko_motion_engine_migration.py`
- Modify: `docs/DATABASE.md`

- [ ] **Step 1 (RED):** 정적 migration 테스트에 다음을 고정한다: `gme_jobs`, `gme_runs`, RLS policy 0, service-role-only RPC, append-only blocker, lease reclaim, live 우선, allowlisted 실패 코드, payload 크기/타입 검증, job/run identity, source `smoke/live/historical`.
- [ ] **Step 2 (RED):** 신규 live trigger가 아직 생성되지 않고, smoke enqueue RPC만 존재하며, Python Evidence trigger/table을 건드리지 않는 테스트를 작성한다.
- [ ] **Step 3:** 테스트 실패를 확인한다.
- [ ] **Step 4 (GREEN):** migration과 RPC를 구현한다:
  - `fn_enqueue_gme_jobs`
  - `fn_claim_gme_jobs`
  - `fn_complete_gme_job`
  - `fn_fail_gme_job`
  - `fn_insert_gme_run`
  - operational stats RPC
- [ ] **Step 5:** `gme_runs`에는 candidate seconds, state intervals, gecko count, tracking quality, detector/tracker/engine provenance, permanent/debug artifact key+digest만 저장한다.
- [ ] **Step 6:** disposable PostgreSQL transaction rollback probe에서 apply, 권한, append-only, concurrent claim, cross-job completion 차단, residue 0을 검증한다.
- [ ] **Step 7:** migration 테스트와 lab 전체 테스트를 통과시킨다.

### Task 8: GME worker 저장 경계와 R2 artifact writer

**Repo:** `petcam-nightly-reporter`

**Files:**
- Create: `reporter/gme_store.py`
- Create: `reporter/gme_artifacts.py`
- Modify: `reporter/r2.py`
- Modify: `reporter/config.py`
- Modify: `.env.example`
- Create: `tests/test_gme_store.py`
- Create: `tests/test_gme_artifacts.py`

- [ ] **Step 1 (RED):** RPC allowlist, frozen job model, stale lease, canonical run payload, malformed state/quality 거부 테스트를 작성한다.
- [ ] **Step 2 (RED):** 정확한 두 GME prefix만 PUT 가능, traversal/원본 prefix/blank key 거부, gzip digest 검증, permanent/debug upload failure 분리 테스트를 작성한다.
- [ ] **Step 3:** 실패를 확인한다.
- [ ] **Step 4 (GREEN):** 기존 Python Evidence store를 수정하지 않고 별도 GME repository를 구현한다.
- [ ] **Step 5 (GREEN):** boto3 `put_object`에 content type/encoding, artifact SHA-256 metadata를 넣고 key 원문을 로그하지 않는 writer를 구현한다.
- [ ] **Step 6:** `GME_ENABLED`, expected host, batch limit, lease/runtime, checkpoint, threshold, anchor, analysis fps, permanent/debug prefix 설정을 fail-closed로 추가한다.
- [ ] **Step 7:** 대상 테스트와 nightly 전체 테스트를 통과시킨다.

### Task 9: Mac mini GME worker와 live 우선 정책

**Repo:** `petcam-nightly-reporter`

**Files:**
- Create: `reporter/gme_worker.py`
- Create: `reporter/gme_runtime_policy.py`
- Create: `tests/test_gme_worker.py`
- Create: `tests/test_gme_runtime_policy.py`

- [ ] **Step 1 (RED):** disabled/host mismatch/common Gate lock busy/no jobs가 DB/R2/model/temp write 전에 끝나는 테스트를 작성한다.
- [ ] **Step 2 (RED):** job당 download 1회, GME analyze 1회, permanent/debug PUT, run insert, complete 순서를 테스트한다.
- [ ] **Step 3 (RED):** 실패 격리, retry/terminal allowlist, temp 0, idempotent existing run, stale lease no-op을 테스트한다.
- [ ] **Step 4 (RED):** live lag p95 >15m이면 historical claim 0이고 live claim은 계속되는 테스트를 작성한다.
- [ ] **Step 5 (GREEN):** `python -m reporter.gme_worker` one-shot worker를 구현한다. 기존 common Gate lock을 재사용하고 원본·GT·VLM·activity store import를 금지한다.
- [ ] **Step 6 (GREEN):** batch에는 live를 먼저 처리하고 남은 capacity에서만 historical을 claim한다.
- [ ] **Step 7:** 대상 테스트와 nightly 전체 테스트를 통과시킨다.

### Task 10: Smoke/backfill/LaunchAgent 운영 도구

**Repo:** `petcam-nightly-reporter`

**Files:**
- Create: `scripts/enqueue_gme_smoke.py`
- Create: `scripts/enqueue_gme_backfill.py`
- Create: `scripts/audit_gme_shadow.py`
- Create: `install-launchd-gme.sh`
- Create: `tests/test_enqueue_gme_smoke.py`
- Create: `tests/test_enqueue_gme_backfill.py`
- Create: `tests/test_audit_gme_shadow.py`
- Create: `tests/test_install_launchd_gme.py`

- [ ] **Step 1 (RED):** smoke selector가 eligible, playable, 서로 다른 카메라/밤을 가능한 범위에서 포함한 정확히 10건을 고르고 원문 식별자를 출력하지 않는 테스트를 작성한다.
- [ ] **Step 2 (RED):** backfill 시작이 `2026-07-15T00:00:00+09:00`이고 quarantine/media_deleted/source_missing/R2 preflight fail을 제외하며 keyset pagination, conflict-do-nothing을 쓰는 테스트를 작성한다.
- [ ] **Step 3 (RED):** audit가 10/10 complete, rerun identity 동일, temp 0, approved DB/R2 writes만 검사하는 테스트를 작성한다.
- [ ] **Step 4 (RED):** installer의 explicit enable, exact hostname, plist lint, 60초 one-shot, working directory, log path, secret 미포함 테스트를 작성한다.
- [ ] **Step 5 (GREEN):** 네 도구를 최소 구현하고 dry-run을 기본값으로 둔다. 실제 enqueue/install은 명시 플래그가 있어야 한다.
- [ ] **Step 6:** 대상 테스트와 nightly 전체 테스트를 통과시킨다.

### Task 11: 직접 전환 SQL과 rollback 계약

**Repo:** `petcam-lab`

**Files:**
- Create: `migrations/2026-08-03_gecko_motion_engine_direct_cutover.sql`
- Create: `scripts/verify_gme_cutover_contract.py`
- Create: `tests/test_gecko_motion_engine_cutover.py`
- Modify: `docs/DATABASE.md`

- [ ] **Step 1 (RED):** 전환 migration이 한 transaction 안에서 GME live trigger 생성 후 Python Evidence enqueue trigger만 제거하고, 어떤 기존 row/table/run도 삭제·갱신하지 않는 테스트를 작성한다.
- [ ] **Step 2 (RED):** rollback SQL이 GME 신규 enqueue를 중단하고 보존된 `fn_enqueue_python_evidence_job()` trigger를 복원하되 GME 역사 결과를 삭제하지 않는지 테스트한다.
- [ ] **Step 3 (GREEN):** cutover와 문서화된 exact rollback SQL을 구현한다. 이름 충돌과 이중 trigger 상태는 fail-closed한다.
- [ ] **Step 4:** disposable PostgreSQL에서 pre-cutover → cutover → rollback → cutover 재적용을 검증하고 각 단계 trigger 수와 residue를 출력한다.
- [ ] **Step 5:** lab 전체 테스트를 통과시킨다.

### Task 12: 정적 통합 검수와 명시 파일 커밋

**Repos:** all three

- [ ] **Step 1:** 각 저장소에서 `git diff --stat`으로 변경을 기능별로 확인하고 기존 사용자 변경과 섞이지 않았는지 검사한다.
- [ ] **Step 2:** `git diff --check`, 전체 pytest, secret/email/private-key grep을 통과시킨다.
- [ ] **Step 3:** GME 파일만 명시 stage하고 stage 목록을 다시 확인한다.
- [ ] **Step 4:** 저장소별 커밋을 만든다:
  - Gate: `feat: Gecko Motion Engine shadow 코어`
  - lab: `feat: GME shadow 원장과 직접 전환 계약`
  - nightly: `feat: Mac mini GME shadow worker`
- [ ] **Step 5:** non-force push 후 각 40자리 SHA와 upstream 일치를 확인한다.

### Task 13: cross-repo/runtime handoff 검증

**Repo:** `petcam-lab`

**Files:**
- Create: `docs/handoff-prompts/2026-08-03-gme-production-shadow-runtime-handoff.md`

- [ ] **Step 1:** manifest에 execution repo, 이 plan/design 절대경로, lab 40자리 SHA, implementation host, runtime kind/host/label과 두 dependency repo SHA를 본문에 적는다.
- [ ] **Step 2:** plan/design/manifest가 tracked commit에 있고 해당 세 파일이 clean인지 확인한다.
- [ ] **Step 3:** `uv run python scripts/verify_agent_handoff.py --manifest /Users/baek/.codex/worktrees/8faf/petcam-lab/docs/handoff-prompts/2026-08-03-gme-production-shadow-runtime-handoff.md`가 `HANDOFF_OK`를 출력해야만 Mac mini write 단계로 간다.

### Task 14: Production DB base migration과 10개 실영상 smoke

**Runtime host:** `baeg-endeuui-Macmini.local`

- [ ] **Step 1:** production migration 목록을 읽어 base GME migration 미적용을 확인하고 disposable rollback probe와 파일 SHA를 재대조한다.
- [ ] **Step 2:** base migration만 atomic apply한다. 이 단계에서는 live trigger와 Python Evidence service를 바꾸지 않는다.
- [ ] **Step 3:** Mac mini 세 repo가 승인 SHA를 가리키도록 ff-only 동기화하고 hostname, working directory, Gate checkpoint SHA, feature flag를 확인한다.
- [ ] **Step 4:** dry-run smoke selector 뒤 정확히 10건만 `source=smoke`로 enqueue한다.
- [ ] **Step 5:** GME one-shot을 실행해 10/10 complete까지 bounded retry한다. 실패를 숨기거나 다른 영상으로 사후 교체하지 않는다.
- [ ] **Step 6:** 같은 10건 재enqueue/재실행으로 새 run/중복 artifact가 생기지 않는지 확인한다.
- [ ] **Step 7:** audit로 temp 0, original/GT/activity/VLM write 0, approved GME DB/R2 prefix 외 write 0을 확인한다.
- [ ] **Step 8:** 하나라도 실패하면 cutover하지 않고 GME base schema와 smoke 결과만 보존한 채 진단한다.

### Task 15: 직접 production shadow cutover

**Runtime host:** `baeg-endeuui-Macmini.local`

- [ ] **Step 1:** Python Evidence processing job 수를 read-only 확인한다. 0이 아니면 신규 enqueue만 먼저 차단하고 bounded drain 후 다시 확인한다.
- [ ] **Step 2:** direct-cutover migration을 atomic apply해 GME live trigger 1, Python Evidence enqueue trigger 0을 확인한다.
- [ ] **Step 3:** 새 `motion_clips` 1건에 GME live job만 생기고 Python Evidence job은 생기지 않는지 metadata-only canary로 확인한다.
- [ ] **Step 4:** `com.petcam.gme-worker`를 60초 one-shot으로 install/bootstrap하고 service loaded, exact working directory, exact repo HEAD를 확인한다.
- [ ] **Step 5:** `com.petcam.python-evidence-worker`를 bootout하되 plist, code, env, DB tables/runs는 삭제하지 않는다.
- [ ] **Step 6:** KST 2026-07-15 이후 eligible backfill을 멱등 enqueue한다.
- [ ] **Step 7:** live lag p95, queue depth, success/retryable/terminal, temp count를 확인하고 live lag가 15분을 넘으면 backfill만 pause한다.
- [ ] **Step 8:** capture service, 원본 R2 업로드, API/Flutter, GT/VLM 값이 변경되지 않았는지 read-only 검증한다.

### Task 16: 결과 보고와 후속 정확도 연구 경계

**Repos:** lab SOT + Gate report + nightly runtime report

- [ ] **Step 1:** 세 repo HEAD/upstream/dirty 상태, DB migration 이름, Mac mini hostname/service/working directory, 실제 run 증거를 기록한다.
- [ ] **Step 2:** operational 결과를 숫자로 보고한다: smoke 10/10, 신규 coverage, backlog, live lag p95, terminal rate, artifact count/bytes, temp 0 여부.
- [ ] **Step 3:** candidate moving time 분포와 unknown/tracking fragmentation을 연구 관측치로만 요약한다. 정확도나 사용자 효용을 통과했다고 주장하지 않는다.
- [ ] **Step 4:** 다음 별도 TEST-SHEET는 사람 time-interval+bbox/mask GT, camera/animal/enclosure/video 분리, future holdout을 요구한다고 명시한다.
- [ ] **Step 5:** 심각한 operational 실패가 있으면 보존된 rollback 계약으로 Python Evidence 신규 enqueue/service를 복구하고 GME history는 삭제하지 않는다.

## Final Verification Commands

```bash
# gecko-vision-gate
uv run pytest -q
git diff --check

# petcam-nightly-reporter
uv run pytest -q
git diff --check

# petcam-lab
uv run pytest -q
uv run python scripts/verify_agent_handoff.py --manifest \
  /Users/baek/.codex/worktrees/8faf/petcam-lab/docs/handoff-prompts/2026-08-03-gme-production-shadow-runtime-handoff.md
git diff --check
```

Expected before cutover:

```text
all test suites passed
HANDOFF_OK task=gme-production-shadow repo=petcam-lab commit=[현재 lab HEAD의 앞 8자리] runtime=launchagent@baeg-endeuui-Macmini.local
smoke_complete=10/10
idempotent_rerun=true
temp_files=0
unauthorized_writes=0
```

Expected after cutover:

```text
gme_live_trigger=1
python_evidence_live_trigger=0
gme_service_loaded=true
python_evidence_service_loaded=false
live_coverage=100%
capture_impact=0
```
