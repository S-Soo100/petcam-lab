# FEATURES — 이 백엔드가 해주는 일들

> "엔드포인트가 아니라 기능 단위" 로 본 petcam-lab. 각 기능마다 무엇/왜/어디 코드/관련 스펙.

Stage A ~ D5 + 클라우드 마이그레이션 (`cloud-migration-roadmap.md`) 까지 거치면서 13개 기능 레이어가 쌓였다. 아래 순서는 데이터 흐름 순 (캡처 → 저장 → R2 → 조회 → 라벨링 → 인증 → RBA/VLM → 라벨링 웹 → 배포 → QA).

**RBA (Reptile Behavior Analysis)** 는 이 제품의 핵심 AI 분석 기술명이다. 밤사이 파충류 펫캠 영상을 행동 타임라인과 케어 시그널로 바꾼다. Track A는 저비용 의미 분석 역할(현재 production 모델 미확정), Track B는 SegmentVLM 정밀 분석/품질 연구다. 사업·관계도 설명은 [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](AI-VIDEO-ANALYSIS-STRATEGY.md).

**4-component 아키텍처** (2026-05-08 기준):
1. **API 서버** (`backend.main:app`) — fly.io `petcam-api` always-on. §6, §7, §8, §9, §12.
2. **캡처 워커** (`backend.capture_main`) — LAN/자체 HW. §1~§5 (제작·R2 PUT·DB INSERT), §13.
3. **VLM 워커** (`backend.vlm_worker_main`) — Gemini fly 배포는 historical/셧다운 대상. 새 baseline 확정 전 production 재가동 안 함. §10.
4. **라벨링 웹** — Vercel `label.tera-ai.uk`. §11.

같은 코드베이스 (`backend/`) 의 3 entrypoint — `backend.main:app`, `backend.capture_main`, `backend.vlm_worker_main`. 도메인 로직 공유 + 프로세스만 분리.

---

## 1. 실시간 RTSP 캡처 (다중 카메라, 별도 프로세스)

**무엇**
- 사용자가 등록한 N 대의 카메라 각각에 전용 스레드 워커를 띄워 RTSP 스트림을 상시 수신.
- 연결 끊겨도 3회 재시도 → 실패 시 2초마다 재연결 시도 (무한 반복).
- **API 서버와 별도 프로세스** — `backend.capture_main` 으로 단독 기동. LAN 의존 (RTSP 는 사설 IP 와 평문 비번 필요).

**왜**
- OpenCV `cv2.VideoCapture.read()` 가 C 레벨 블로킹이라 asyncio 이벤트 루프와 격리 필요.
- 초기엔 env 로 카메라 1대 하드코딩 (Stage A~D2) → D3 에서 `cameras` 테이블 기반 다중 워커로 전환 → 클라우드 마이그레이션에서 API 서버로부터 분리 (워커 메모리 256MB fly.io 머신에 OpenCV+FFmpeg 못 싣고, RTSP 는 LAN 안에서만 닿음).
- API 서버는 더 이상 워커 메모리 상태 모름 → `/streams/{camera_id}/status` 같은 진단 endpoint 폐기. 운영 모니터링은 워커 호스트의 OS 레벨로 (자체 HW 운영체제 / fly.io machine / 맥북 launchd).

**어디**
- [backend/capture.py](../backend/capture.py) — `CaptureWorker` 클래스 + FPS 측정·재연결·세그먼트 저장 루프
- [backend/capture_main.py](../backend/capture_main.py) — 캡처 워커 entry point (`uv run python -m backend.capture_main`)

**튜닝 포인트**
- 재시도 상수: `CONNECT_MAX_RETRIES=3`, `FRAME_READ_MAX_FAILS=30`
- FPS 측정 구간: `FPS_MEASURE_SEC=10`초 (첫 세그먼트만 짧아지지만 이후 모든 세그먼트 재생 시간 정확)

**관련 스펙:** [stage-a-streaming.md](../specs/stage-a-streaming.md), [stage-d3-multi-capture.md](../specs/stage-d3-multi-capture.md), [feature-capture-worker-extraction.md](../specs/feature-capture-worker-extraction.md)

---

## 2. 움직임 감지 + 세그먼트 태깅

**무엇**
- 프레임마다 `MotionDetector.update()` 호출 → 이전 프레임과 픽셀 차분 → `is_motion_frame: bool`.
- 세그먼트(60초) 종료 시 누적 유효 motion 초가 임계(3초) 이상이면 파일명에 `_motion` 접미사, 미만이면 `_idle`.
- 튜닝용 실시간 픽셀 변화율(`last_changed_ratio`) 도 상태에 노출.

**왜**
- 저전력 앱/ESP32 이식 고려해 가벼운 알고리즘 선택 (MOG2/KNN 대신 `cv2.absdiff` + Gaussian 블러 + threshold).
- 사육장은 조명 고정 → 배경 모델링 오버킬. 장점: 설명 가능 + CPU 저렴.
- UVB on/off 같은 급격한 밝기 변화는 일시적 false positive. 고도화는 Stage C+ 이후.

**어디**
- [backend/motion.py](../backend/motion.py) — `MotionDetector` 클래스 (ratio% 반환)
- [backend/capture.py](../backend/capture.py) — run-length 집계 (`MOTION_MIN_DURATION_FRAMES` 이상 연속이어야 유효 run)

**튜닝 포인트**
- `MOTION_PIXEL_THRESHOLD` (0~255, 기본 25) — 픽셀별 밝기 차이 임계. 올리면 노이즈 덜 잡음.
- `MOTION_PIXEL_RATIO` (%, 기본 1.0) — 프레임의 변한 픽셀 비율. 올리면 오탐 ↓, 놓침 ↑.
- `MOTION_MIN_DURATION_FRAMES` (기본 12 ≈ 1초) — N 프레임 연속이어야 유효 run.
- `MOTION_SEGMENT_THRESHOLD_SEC` (기본 3.0초) — 세그먼트 `_motion` 판정 최소 누적.

**관련 스펙:** [stage-b-motion-detect.md](../specs/stage-b-motion-detect.md)

---

## 3. 세그먼트 저장 (CFR 보정 + 코덱 폴백 + 깨진 파일 자동 삭제)

**무엇**
- 1분 단위 mp4 저장. 파일명 `{HHMMSS}_{motion|idle}.mp4`.
- **CFR (Constant Frame Rate) 보정** — 네트워크 jitter 로 수신 FPS 가 요동쳐도 재생 시간은 항상 60초 ±0.1.
  - 부족분: 직전 프레임 복제 패딩
  - 초과분: 드롭 (motion 판정은 항상 실행)
- **코덱 폴백 체인**: `avc1` → `H264` → `X264` → `mp4v`. OpenCV 빌드에 따라 이름 다름. 첫 성공한 것 세션 내 재사용.
- **깨진 세그먼트 자동 삭제**: 경과 <5초 또는 파일 <50KB → unlink (0바이트 영상 방지).

**왜**
- Stage A 에선 mp4v + 수신 FPS 그대로 → 60초 녹화가 21초 재생 버그 발생.
- avc1 교체로 용량 ~70% 절감 (1분당 2~5MB). 품질 동등.
- macOS 사파리에서 mp4v는 재생 안 됨. avc1 은 모든 플랫폼 OK.

**어디**
- [backend/capture.py](../backend/capture.py) — `compute_padding_count` / `should_drop_frame` pure function + `_open_new_segment` 코덱 폴백 + `_close_and_tag_segment` 정합성 검증

**튜닝 포인트**
- `SEGMENT_SECONDS=60` — 1 세그먼트 길이. 길게 하면 썸네일 대표성↑, 짧게 하면 플레이어 시크 반응성↑.
- `VIDEO_FOURCC_CANDIDATES` 순서 — OpenCV 빌드가 특정 코덱만 지원하는 경우 순서 조정.
- `MIN_SEGMENT_SEC=5`, `MIN_SEGMENT_BYTES=50_000` — 자동 삭제 임계.

**관련 스펙:** [stage-b-motion-detect.md](../specs/stage-b-motion-detect.md)

---

## 4. 썸네일 (대표 프레임 jpg)

**무엇**
- 세그먼트 종료 시 대표 프레임 jpg 1장을 mp4 옆에 저장.
- `_motion.mp4` → **움직임이 처음 감지된 프레임** (가장 유익한 순간)
- `_idle.mp4` → **세그먼트 중간 ~30초 지점** (평균적 장면)
- 둘 다 실패 시 마지막 유효 프레임 fallback (빈 썸네일 방지).
- `camera_clips.thumbnail_path` (로컬) + `thumbnail_r2_key` (R2) 컬럼에 경로 저장 → `GET /clips/{id}/thumbnail` 또는 `/thumbnail/url` 로 반환.

**왜**
- Flutter 앱 클립 피드에서 "영상 다운로드 없이 미리보기".
- mp4 디코딩 없이 jpg 한 장이 훨씬 빠름 (네트워크·파싱 둘 다).

**어디**
- [backend/capture.py](../backend/capture.py) — `_save_thumbnail` + 세그먼트 roll-over 시 프레임 캐싱
- [backend/routers/clips.py](../backend/routers/clips.py) — `GET /clips/{id}/thumbnail` (R2 redirect or FileResponse)

**엣지케이스**
- `thumbnail_path` + `thumbnail_r2_key` 둘 다 NULL 인 기존 클립 (D4 이전) → 404 "thumbnail not generated"
- DB 엔 있는데 디스크에서 사라짐 → 404 "thumbnail file missing on disk"

**관련 스펙:** [stage-d4-thumbnail.md](../specs/stage-d4-thumbnail.md)

---

## 5. R2 외부 스토리지 (Cloudflare R2 PUT/GET)

**무엇**
- mp4 + jpg 를 캡처 워커가 Cloudflare R2 버킷에 PUT (S3 호환 API). 키 형식 `clips/YYYY-MM-DD/<camera-id>/HHMMSS_motion.mp4`.
- **EncodeUploadWorker** — 별도 큐 워커가 디스크 mp4 → R2 PUT 후 `camera_clips.r2_key` UPDATE. 디스크 파일은 보존 (재처리 fallback) 또는 retention 정책으로 정리.
- API 서버는 R2 키를 보고 **signed URL** (1h TTL, GET) 발급 — `boto3.client('s3').generate_presigned_url('get_object', ...)`.
- 클라이언트 (Flutter / 라벨링 웹) 는 signed URL 로 R2 edge 에 **직접 GET** → API 서버는 byte stream 통과 안 시킴.

**왜**
- **256MB 메모리 제약** — fly.io shared-cpu-1x 머신에서 4K 클립 byte stream 통과시키면 OOM. R2 직접 GET 으로 메모리 상수화.
- **R2 키 opaque** — 클라이언트는 signed URL 의 query param 만 보고 키 자체는 모름 (옆 사용자 키 추측 차단).
- **Authorization 헤더 한계** — HTML5 `<video src>` 는 cross-origin 요청에 Authorization 헤더 못 보냄. signed URL 자체가 토큰이라 헤더 불필요 → `<video>` / `VideoPlayerController` 어디든 박을 수 있음.
- **R2 egress 무료** — Cloudflare 정책. AWS S3 대비 트래픽 비용 0.

**어디**
- [backend/r2_uploader.py](../backend/r2_uploader.py) — `presign_get_url(key, ttl=3600)` + `put_object` 헬퍼
- [backend/encode_upload_worker.py](../backend/encode_upload_worker.py) — DB-as-message-bus 패턴 (NEXT 폴링 + UNIQUE 잠금)
- [backend/routers/clips.py](../backend/routers/clips.py) — `/file/url`, `/thumbnail/url` 발급

**환경변수**
- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`

**관련 스펙:** [feature-r2-storage-encoding-labeling.md](../specs/feature-r2-storage-encoding-labeling.md), [cloud-migration-roadmap.md](../specs/cloud-migration-roadmap.md)

---

## 6. 클립 메타 DB + 조회 API

**무엇**
- 세그먼트 종료 시 Supabase `camera_clips` 테이블에 INSERT (user_id, camera_id, pet_id, started_at, duration_sec, has_motion, motion_frames, file_path, file_size, codec, width, height, fps, thumbnail_path, **r2_key**, **thumbnail_r2_key**).
- `GET /clips` — 필터(camera_id, has_motion, from, to) + **seek pagination** (`cursor = started_at`).
- `GET /clips/highlights` — main 4 (eating_paste/drinking/moving/unknown) **제외** 행동만 모은 하이라이트 피드 (사람 검수 라벨 우선, 없으면 VLM 자동).
- `GET /clips/{id}` — 단건 메타.
- `GET /clips/{id}/file` — R2 키 있으면 302 redirect, 없으면 백엔드 직접 mp4 스트리밍 (Range 지원 fallback).
- `GET /clips/{id}/file/url` — **R2 signed URL JSON** (Flutter / 라벨링 웹 권장).
- `GET /clips/{id}/thumbnail` — R2 키 있으면 302, 없으면 jpg.
- `GET /clips/{id}/thumbnail/url` — 썸네일 R2 signed URL JSON.

**왜**
- `offset` 페이지네이션은 깊어질수록 느림 → `started_at < cursor` 인덱스 range scan.
- 하이라이트 분리 — main 4 는 일상 행동이라 양 많음, 그 외 5종 (eating_prey/defecating/shedding/basking/unseen) 만 별도 피드. 사람 라벨 (`behavior_labels`) 우선, 없으면 VLM 자동 (`behavior_logs.source='vlm'`).
- **장애 내성**: Supabase 네트워크 장애 시 `storage/pending_inserts.jsonl` JSONL 큐에 append → 30초마다 flush 재시도. 큐 최대 1000 라인, 초과 시 오래된 것 drop.

**어디**
- [backend/routers/clips.py](../backend/routers/clips.py) — 목록/하이라이트/단건/파일/썸네일/url 7 엔드포인트
- [backend/clip_recorder.py](../backend/clip_recorder.py) — `make_clip_recorder` (user_id/pet_id 주입 + 미러 훅) + `make_flush_insert_fn`
- [backend/pending_inserts.py](../backend/pending_inserts.py) — `PendingInsertQueue` (thread-safe JSONL)

**상태 코드**
- `/clips/{id}/file`: 302 (R2 redirect) / 200 (Range 없음, 로컬 fallback) / 206 (Partial Content) / 410 (R2 키도 디스크 파일도 없음) / 416 / 404
- `/clips/{id}/file/url`: 200 + `{url, ttl_sec, type}` / 410 / 404
- `/clips/{id}/thumbnail`: 200 / 302 / 404 3분기 (row 없음 / NULL / 파일 사라짐)

**관련 스펙:** [stage-c-db-api.md](../specs/stage-c-db-api.md), [stage-d4-thumbnail.md](../specs/stage-d4-thumbnail.md), [cloud-migration-roadmap.md](../specs/cloud-migration-roadmap.md)

---

## 7. 라벨링 API + 라벨러 큐

**무엇**
- 7 엔드포인트 (`backend/routers/labels.py` + `me.py`):
  - `POST /clips/{id}/labels` — 라벨 1건 UPSERT (UNIQUE `clip_id+labeled_by`)
  - `GET /clips/{id}/labels` — owner=전체 / labeler=본인만 / 외부=404
  - `GET /clips/{id}/inference` — owner-only VLM 추론 조회 (라벨러 anchoring 차단)
  - `GET /labels/queue` — 라벨러 큐 (`has_motion=true AND r2_key NOT NULL`, 본인 라벨한 거 제외)
  - `GET /labels/mine` — 본인 라벨한 클립 회고 (필터 없음)
  - `GET /me/is_labeler` — Flutter 가 deep link 노출 여부 결정용
- **9 raw ActionType** + **6 LickTargetType** — DB 는 TEXT, Pydantic enum 검증 (VLM 진화 따라 바꾸기 쉽게).

**3-tier 권한 모델**
| 역할 | 라벨 작성 | 다른 사람 라벨 보기 | VLM 추론 | 큐 스코프 |
|------|----------|-------------------|----------|----------|
| owner | ✅ (force `labeled_by` override 가능) | ✅ | ✅ | 본인 user_id |
| labeler (`labelers` 멤버) | ✅ (본인만) | ❌ | ❌ | 모든 user_id |
| 외부인 | ❌ | ❌ (404) | ❌ (404) | n/a |

**왜**
- VLM 자동 라벨 (`behavior_logs.source='vlm'`) 만으로는 신뢰도 부족 (일상 행동 85% / 저빈도 행동 더 낮음). 사람 검수 라벨 (`behavior_labels`) 이 GT.
- 라벨러는 VLM 결과 못 봐야 anchoring bias 회피 (자기 라벨이 VLM 으로 쏠림). owner 만 검수 화면에서 VLM 비교.
- 큐 필터 `has_motion+r2_key` — idle 세그먼트 (재생할 모션 없음) / R2 미업로드 (재생 불가) 둘 다 라벨링 대상 아님.

**어디**
- [backend/routers/labels.py](../backend/routers/labels.py) — 5 엔드포인트
- [backend/routers/me.py](../backend/routers/me.py) — `is_labeler`
- [backend/clip_perms.py](../backend/clip_perms.py) — `is_labeler(user_id, sb)`, `load_clip_with_perms(...)`

**관련 스펙:** [feature-labeling-web-cloud.md](../specs/feature-labeling-web-cloud.md), [cloud-migration-roadmap.md](../specs/cloud-migration-roadmap.md)

---

## 8. 카메라 CRUD + RTSP 자동 probe + 비번 암호화

**무엇**
- 6 엔드포인트: `POST /cameras/test-connection`, `POST /cameras`, `GET /cameras`, `GET /cameras/{id}`, `PATCH /cameras/{id}`, `DELETE /cameras/{id}`.
- 등록 시 **자동 RTSP probe** (3초 타임아웃, 첫 프레임 수신) → 실패면 400 + 등록 거부.
- 비번은 **Fernet 대칭 암호화** (AES-128-CBC + HMAC) 로 `cameras.password_encrypted` 에 저장. 응답에는 절대 노출 X.
- `(user_id, host, port, path)` 유니크 제약 → 중복 등록 시 409.
- PATCH `password` 들어오면 재암호화.

**왜**
- RTSP 는 접속 시 평문 비번 필요 → bcrypt/argon2 같은 일방향 해시 사용 불가 → 양방향 Fernet.
- `cameras` 테이블 RLS 에 INSERT 정책 없음 → anon/authenticated 직접 insert 불가 → 백엔드가 probe → encrypt → insert 순서 강제.
- test-connection 실패도 200 + `success=false` (사용자 입력 오타 vs 서버 크래시 구분).

**어디**
- [backend/routers/cameras.py](../backend/routers/cameras.py) — 6 엔드포인트 + Pydantic 모델
- [backend/rtsp_probe.py](../backend/rtsp_probe.py) — `probe_rtsp` + `build_rtsp_url` + `mask_rtsp_url` (로깅용)
- [backend/crypto.py](../backend/crypto.py) — Fernet 싱글톤 (`CAMERA_SECRET_KEY`) + placeholder 가드

**주의**
- `CAMERA_SECRET_KEY` 는 최초 1회 생성 후 **변경 금지** — 바꾸면 기존 DB 암호문 전부 복호화 불가.
- 생성: `uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

**관련 스펙:** [stage-d1-auth-crypto.md](../specs/stage-d1-auth-crypto.md), [stage-d2-cameras-api.md](../specs/stage-d2-cameras-api.md)

---

## 9. Supabase JWT 인증 (dev/prod 분기)

**무엇**
- 모든 라우트가 `Depends(get_current_user_id)` 하나로 user_id 를 받음. 내부에서 `AUTH_MODE` 보고 자동 분기.
- `AUTH_MODE=dev` (기본) — `Authorization` 헤더 무시, `DEV_USER_ID` 반환. 로컬 개발·pytest 용.
- `AUTH_MODE=prod` — `Bearer <JWT>` 필수. Supabase JWKS 에서 공개키 fetch (10분 TTL 캐시) → 서명/`exp`/`iss` 검증 → `sub` claim 반환.
- 알고리즘 런타임 결정 — 현재 Supabase 는 `ES256` (P-256), 과거 프로젝트는 `RS256`. `jwt.PyJWK` 가 `kty` 보고 공개키 객체 자동 생성.

**왜**
- 로컬 개발 중에 JWT 발급 번거로움 → dev 모드로 우회.
- prod 전환은 `.env` 한 줄만 수정. 코드는 동일.
- JWKS TTL 캐시 — 매 요청마다 Supabase 호출하면 지연·비용. `@lru_cache` 는 TTL 없어서 키 회전 시 영구 캐시 위험 → 모듈 전역 dict + `time.monotonic` 10분.
- service_role + 라우터 user_id 필터 = single gate (RLS 우회를 의도적 설계).

**어디**
- [backend/auth.py](../backend/auth.py) — `get_current_user_id`, `verify_jwt`, `get_jwks`, `reset_jwks_cache`
- 모든 `backend/routers/*.py` — `Depends(get_current_user_id)` 로 주입

**에러 모델**
- 모든 인증 실패 → 401 `AuthError` (detail 로 원인 구분)
- 실패 원인: 헤더 없음 / Bearer 포맷 아님 / kid 매칭 실패 / 서명 불일치 / exp 만료 / iss 불일치 / sub 없음

**관련 스펙:** [stage-d1-auth-crypto.md](../specs/stage-d1-auth-crypto.md)

---

## 10. RBA Track A — VLM 자동 라벨링 (별도 워커, fly.io always-on)

**무엇**
- 이 레이어는 **RBA Track A** 다. 60초 motion clip 전체를 Gemini 2.5 Flash + v3.5 prompt 로 한 번 분석해 기본 행동 라벨을 만든다.
- **VLM 워커** (`backend.vlm_worker_main`) 가 fly.io `petcam-vlm-worker` 머신에서 24/7 가동. `https://petcam-vlm-worker.fly.dev/health`.
- **DB-as-message-bus** — Redis 같은 외부 큐 없이 `behavior_logs` 테이블 자체를 큐로 사용:
  - 캡처 워커가 R2 PUT 끝낼 때 `behavior_logs(clip_id, source='vlm', status='pending')` INSERT.
  - historical Gemini 워커는 `status='pending'` 행을 폴링 → R2 signed URL로 mp4 다운로드 → Gemini 2.5 Flash 호출 → `action`/`confidence`/`reasoning` UPDATE + `status='done'` 구조였다.
  - 동시 처리 보호 — `UNIQUE (clip_id) WHERE status='pending'` 부분 인덱스로 중복 처리 차단.
- 결과는 `GET /clips/{id}/inference` (owner-only) 와 `GET /clips/highlights` (사람 라벨 없을 때 fallback) 에 노출.

**왜**
- 라벨링 웹/Flutter 가 R2 영상 받아서 클라이언트 추론 = 메모리·CPU 무리 (브라우저 / 모바일).
- API 서버가 추론 = 256MB 머신에 큰 모델 못 실음. 추론 시간 (수초) 동안 다른 요청 막음.
- 별도 워커 = scale 독립 (라벨링 트래픽 ≠ VLM 처리량) + always-on 으로 새 클립 즉시 처리.
- DB-as-message-bus 선택 이유 — 베타 트래픽 (사용자 1, 클립당 ~10초 처리) 에선 Postgres LISTEN/NOTIFY 또는 폴링이 Redis 추가 운영 비용보다 저렴.

**어디**
- [backend/vlm_worker_main.py](../backend/vlm_worker_main.py) — entry point
- [backend/vlm/](../backend/vlm/) — 모델별 어댑터 (Gemini, Sonnet 등) + 프롬프트 + cost tracker
- [backend/health.py](../backend/health.py) — `/health` endpoint (별도 FastAPI app)

**모델 / 비용**
- 현재 production 모델 — 미확정. 저비용 API 모델+adaptive frames+prompt+클래스+비용 계약을 동결한 뒤 future holdout으로 검증한다.
- historical — Gemini 2.5 Flash, 9 raw ActionType, 과거 planning estimate clip당 ~$0.001. 현재 비용 주장에 사용하지 않는다.
- 비용 추적: `@dataclass(frozen=True)` `CostRecord` 누적 (mutate 금지 — `donts/vlm.md` 룰 3).

**관련 스펙:** [feature-vlm-worker-cloud.md](../specs/feature-vlm-worker-cloud.md), [feature-vlm-worker-fly-deploy.md](../specs/feature-vlm-worker-fly-deploy.md)

**Track B 참고**
- **SegmentVLM** 은 RBA Track B 다. 긴 영상/모호한 클립을 5~15초 event segment 로 쪼개 event별 분석 후 timeline 으로 병합하는 정밀 분석 실험이다.
- 현재 production `behavior_logs` 에 바로 쓰지 않고, `experiments/segment-vlm/` artifact 와 비교 리포트로 검증한다.
- 관련 설명: [AI-VIDEO-ANALYSIS-STRATEGY.md](AI-VIDEO-ANALYSIS-STRATEGY.md), [experiment-event-segment-vlm.md](../specs/experiment-event-segment-vlm.md)

---

## 11. 라벨링 웹 (Vercel `label.tera-ai.uk`)

**무엇**
- Next.js (App Router) 앱. **owner 검수 + 라벨러 작업** 양쪽 같은 화면.
- Vercel 배포, `https://label.tera-ai.uk` always-on.
- 화면 구성:
  - **큐 (`/labeling`)** — `GET /labels/queue` 결과를 카드 그리드로. 클릭하면 클립 디테일.
  - **클립 디테일 (`/labeling/{clipId}`)** — R2 signed URL 로 영상 재생 + ActionType 9 + LickTargetType 6 입력.
  - **회고 (`/labeling/mine`)** — `GET /labels/mine` 본인 작업 리스트.
- Flutter 앱이 `/me/is_labeler=true` 인 owner-labeler 에게만 deep link 노출 (chip 옆 "검수" 버튼).

**왜**
- 9 ActionType + 6 LickTargetType + note 조합을 모바일 작은 화면에 맞추기 어려움 → 데스크탑 웹.
- Vercel server-side route 가 Supabase service_role / R2 액세스 키 직결 → API 서버 hop 불필요한 endpoint (영상 재생, 라벨 저장) 는 Vercel→R2/Supabase 직결로 latency 단축.
- API 서버 의존 0 — 라벨링 웹은 단순 BaaS proxy. fly.io API 서버가 죽어도 라벨링 작업은 계속 (단, Flutter 와 라벨 데이터는 Supabase 통해 sync).
- **라벨 수정 UI 는 라벨링 웹 전용** — Flutter 에 만들지 않음 (사용자 명시 결정, `cloud-migration-roadmap.md` §4-6).

**어디**
- 별도 레포 / 디렉토리 (Next.js project, 이 레포 외부)
- 백엔드 측 인터페이스: `backend/routers/labels.py` (이 레포의 §7 endpoint 들)

**관련 스펙:** [feature-labeling-web-cloud.md](../specs/feature-labeling-web-cloud.md), [cloud-migration-roadmap.md](../specs/cloud-migration-roadmap.md)

---

## 12. 외부 공개 (fly.io always-on + AUTH_MODE=prod)

**무엇**
- API 서버를 `https://api.tera-ai.uk` 로 24/7 공개. Flutter 앱이 LTE/외부 Wi-Fi 어디서든 접근 + 사용자 맥북 의존 0.
- fly.io app `petcam-api` 가 Tokyo (`nrt`) 리전에 머신 1대 (shared-cpu-1x, 256MB) 상시 가동 (`min_machines_running = 1`).
- Cloudflare DNS A/AAAA → fly.io edge **직결**. Cloudflare Tunnel/cloudflared 폐기 (2026-05-08 cutover).
- TLS — fly.io 가 발급한 Let's Encrypt E8 cert (HTTP-01 챌린지, 만료 자동 갱신).

**왜**
- 이전 구조 (맥북 + Cloudflare Tunnel) 는 사용자가 맥북 슬립/이동/재시작 시마다 Flutter 가 502/타임아웃. QA 안정성·24/7 라벨링 워크플로 둘 다 못 받침.
- fly.io 의 단순화 가치: 머신 + 도메인 + 헬스체크 + cert 한 통합 (cloudflared 별도 관리 불필요).
- 256MB 메모리 제약 → 캡처 워커 (OpenCV+FFmpeg) 와 VLM 워커 (큰 모델) 는 같은 fly.io 머신에 못 실음 → **프로세스 분리 강제** (이 문서 §1, §10).

**어디**
- [backend/main.py](../backend/main.py) — `lifespan` 시작 시 `AUTH_MODE` 값을 warning 으로 로그 (실수 감지)
- [fly.toml](../fly.toml) — fly.io 머신 설정 (region, memory, autostop, http_service, checks)
- [Dockerfile](../Dockerfile) — uv 기반 슬림 이미지

**운영 절차**
```bash
# 배포 — 코드 푸시 후
fly deploy --app petcam-api

# 헬스체크
curl https://api.tera-ai.uk/health
# → {"status":"ok","startup_error":null}

# 로그 tail
fly logs --app petcam-api
```

상세: [DEPLOYMENT.md](DEPLOYMENT.md).

**관련 스펙:** [stage-d5-deploy-tunnel.md](../specs/stage-d5-deploy-tunnel.md), [feature-api-server-fly-deploy.md](../specs/feature-api-server-fly-deploy.md)

---

## 13. QA 테스터 미러 (임시 인프라)

**무엇**
- 오너 계정(`bss.rol20@gmail.com`)의 `cam1 / cam2` 클립을 QA 테스터 계정(`dlqudan12@gmail.com`)이 동일하게 조회·재생할 수 있게 하는 best-effort 미러링.
- `clip_mirrors` 테이블에 `(source_camera_id, mirror_camera_id, mirror_user_id)` 매핑 저장.
- 원본 INSERT 성공 시 `_mirror_clip` 훅이 매핑 조회 → 미러 행 복사 INSERT. **Live + Flush 양쪽 훅** 필수 (재시작 타이밍 gap 방지).

**왜**
- 공개 도메인 배포 후 멀티 유저 로그인 E2E QA 필요 → QA 계정이 오너 영상을 실제로 재생·스크롤 검증.
- 정식 공유 기능이 **아님** — 사용자 방침 "앞으로 남의 개체·남의 카메라를 보는 기능은 없을거야". QA 종료 후 `DROP TABLE clip_mirrors` + 훅 제거하면 끝.
- `clip_mirrors` 는 RLS ENABLE + 정책 0건 (service_role 만 접근). 사용자 클라이언트는 이 테이블 존재 자체 모름.

**어디**
- [backend/clip_recorder.py](../backend/clip_recorder.py) — `_mirror_clip` helper + `record` (live path) 훅 + `make_flush_insert_fn` (flush path) 훅

**제거 절차** (QA 종료 시)
1. `DROP TABLE public.clip_mirrors;`
2. `backend/clip_recorder.py` 에서 `_mirror_clip` helper + 호출 2곳 삭제
3. `tests/test_clip_recorder.py` 의 미러 관련 케이스 제거
4. QA 테스터 `auth.users` / `cameras` / `pets` / `camera_clips` 삭제 (CASCADE 활용)

**관련 스펙:** [feature-clip-mirrors-for-qa.md](../specs/feature-clip-mirrors-for-qa.md)

---

## 14. 다음 읽을 문서

- **코드 구조** → [ARCHITECTURE.md](ARCHITECTURE.md)
- **API 스펙** → [API.md](API.md)
- **DB 스키마** → [DATABASE.md](DATABASE.md)
- **용어** → [GLOSSARY.md](GLOSSARY.md)
