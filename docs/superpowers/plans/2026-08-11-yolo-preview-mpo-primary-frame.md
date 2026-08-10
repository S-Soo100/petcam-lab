# YOLO Preview MPO 첫 프레임 호환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 정상 MPO/JPEG의 첫 프레임을 YOLO Preview에서 추론하되 animated WebP/PNG 차단을 유지한다.

**Architecture:** `backend.yolo_preview_worker._decode_image`의 다중 프레임 판단을 요청 MIME과 Pillow
판독 형식에 결합한다. JPEG/MPO만 첫 프레임을 허용하고 다른 다중 프레임 형식은 기존처럼 거부한다.

**Tech Stack:** Python 3.12, Pillow, NumPy, OpenCV, FastAPI, pytest

## Global Constraints

- production active model, DB, R2, production Vercel 배포를 변경하지 않는다.
- 10 MiB, 20 MP, signature/type, animated WebP/PNG, temp cleanup 방어를 유지한다.
- 모델 출력은 GT·skip·삭제·행동명 근거가 아니다.

---

### Task 1: MPO 회귀 테스트와 최소 디코더 수정

**Files:**
- Modify: `tests/test_yolo_preview_worker.py`
- Modify: `backend/yolo_preview_worker.py`

**Interfaces:**
- Consumes: `_decode_image(path: Path, *, content_type: str) -> np.ndarray`
- Produces: `image/jpeg` MPO의 첫 프레임 BGR 배열과 기존 `/v1/infer` 200 schema

- [ ] **Step 1: synthetic MPO helper와 성공 테스트 작성**

  Pillow `format="MPO"`, `save_all=True`로 크기 10×8의 서로 다른 두 프레임을 만들고
  `/v1/infer`에 `image/jpeg`로 제출한다. 응답 200, runner 호출 1회, temp cleanup을 검증한다.

- [ ] **Step 2: RED 확인**

  Run: `uv run pytest -q tests/test_yolo_preview_worker.py::test_mpo_jpeg_uses_primary_frame`
  Expected: 현재 `n_frames != 1` 분기 때문에 응답 422로 FAIL.

- [ ] **Step 3: 최소 구현**

  `_decode_image`에서 `image/jpeg`이면서 Pillow `format in {"JPEG", "MPO"}`인 경우에만 다중
  프레임을 허용한다. 첫 프레임에 `seek(0)`을 적용하고 기존 verify·20 MP·RGB→BGR 흐름을 유지한다.

- [ ] **Step 4: GREEN과 방어 회귀 확인**

  Run: `uv run pytest -q tests/test_yolo_preview_worker.py`
  Expected: MPO 성공 테스트와 animated WebP 422를 포함해 전부 PASS.

- [ ] **Step 5: 전체 검증**

  Run: `uv run pytest -q`
  Run: `cd web && npm test -- --run && npm run build`
  Expected: 기존 baseline 이상, 실패 0, Next.js build exit 0.

### Task 2: 보호 Preview 배포와 실제 사진 검증

**Files:**
- Modify: `docs/superpowers/plans/2026-08-11-yolo-preview-mpo-primary-frame.md` 체크박스만

**Interfaces:**
- Consumes: 검증된 branch HEAD와 고정 checkpoint identity
- Produces: Mac mini localhost worker와 기존 보호 Preview의 실제 bbox 결과

- [ ] **Step 1: 구현 커밋과 Mac mini runtime HEAD 동기화**

  clean HEAD를 Mac mini runtime repo에 fast-forward하고 기존 관리 스크립트로
  `com.petcam.yolo-preview-worker`를 재등록한다.

- [ ] **Step 2: runtime 검증**

  hostname, LaunchAgent running, working directory, runtime HEAD, authenticated `/v1/health`,
  localhost 8093 listener를 확인한다.

- [ ] **Step 3: 보호 Preview 브라우저 검증**

  rate-limit window를 고려해 Owner 사진 4장을 각각 제출하고 파일명, bbox overlay, model version,
  confidence, processed_at, 오류 유무를 기록한다.

- [ ] **Step 4: production 불변 확인**

  production detector가 계속 preview worker를 사용하지 않는지 확인하고 DB/R2 write 0을 보고한다.
