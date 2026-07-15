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
- 이 레포의 `GET /clips/highlights` — main 4 (eating_paste/drinking/moving/unknown) **제외** 행동만 모은 historical petcam 피드 (사람 검수 라벨 우선, 없으면 VLM 자동).
- `GET /clips/{id}` — 단건 메타.
- `GET /clips/{id}/file` — R2 키 있으면 302 redirect, 없으면 백엔드 직접 mp4 스트리밍 (Range 지원 fallback).
- `GET /clips/{id}/file/url` — **R2 signed URL JSON** (Flutter / 라벨링 웹 권장).
- `GET /clips/{id}/thumbnail` — R2 키 있으면 302, 없으면 jpg.
- `GET /clips/{id}/thumbnail/url` — 썸네일 R2 signed URL JSON.

**왜**
- `offset` 페이지네이션은 깊어질수록 느림 → `started_at < cursor` 인덱스 range scan.
- 하이라이트 분리 — main 4 는 일상 행동이라 양 많음, 그 외 5종 (eating_prey/defecating/shedding/basking/unseen) 만 별도 피드. 사람 라벨 (`behavior_labels`) 우선, 없으면 VLM 자동 (`behavior_logs.source='vlm'`).
- **현재 Flutter 앱은 위 petcam endpoint를 쓰지 않는다.** `EnvConfig.terraServerUrl`의 terra-server `GET /clips/highlights`를 사용한다. 2026-07-12 확인한 실제 terra-server main 기준은 `behavior_logs.source='vlm'`, confidence >= 0.5, action not in `(moving, unseen, shedding)`, 본인 `motion_clips` 존재 조건이다. motion 크기·격한 움직임·Gate gecko visibility는 현재 선정 조건이 아니다.
- 앱은 terra-server가 내려준 결과를 어젯밤 22~06시로 다시 자르고 카드·리포트에 표시할 뿐, Flutter 자체에서 움직임 크기나 게코 가시성으로 재필터하지 않는다.
- **목표 정책(2026-07-12 사용자 결정):** ① `moving/unseen/error` 외 의미 행동 하이라이트에는 shedding을 포함한다. shedding 억제는 특정 모프 IR 오탐 때문에 둔 임시 운영조치이지 제품 영구 제외가 아니다. ② 별도 enrichment 하이라이트로 게코가 보이며 밤에 크게 활동·탐색·놀이하는 장면(대표: 쳇바퀴)을 제공한다.
- VLM shedding은 사람 확인 전 `AI 탈피 의심 · 확인 필요`, 사람 GT가 shedding이면 `탈피 확인`으로 표시한다. 오답이면 고객 하이라이트에서 내리되 prediction과 verdict 이력은 보존한다.
- moving은 object와 직접·반복 상호작용 없는 일반 이동이다. 사람과 VLM은 playing 의도를 직접 단정하지 않고 wheel/장난감의 ride/push/rotate/chase/repeated-return evidence를 기록한다. 사람이 확인한 evidence에서만 고객 표시용 playing을 파생한다. `activity_intensity`는 별도 metadata다.
- **현재 feature 한계:** `storage/nightly-saved/2026-07-07_2240_e679f8ad_wheel-playing.mp4`는 canonical enrichment GT지만 motion_score 0.009, router active_motion_ratio 0.067, evidence reliability low다. 따라서 현 motion_score 단일 threshold는 제품 기준 구현으로 채택하지 않는다. `playing/enrichment` 사람 GT와 wheel/ROI interaction·temporal evidence로 후보식을 동결한 뒤 future clip에서 검증한다.
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

**다음(v2, 계획)**
- 현재 폼은 행동 top-1 라벨링에는 쓸 수 있지만 대규모 GT 생산·Gate bbox 감사에는 부족하다.
- blind mode, frame step/단축키, event 구간, uncertain/multi-action, Gate bbox 교정, hard-case·camera/animal/enclosure metadata, dataset role/provenance를 추가한다.
- 계약 SOT: [RBA Data Engine v1](../specs/feature-rba-data-engine-v1.md).

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
- 이 레포의 `web/` (Next.js project)
- 백엔드 측 인터페이스: `backend/routers/labels.py` (이 레포의 §7 endpoint 들)

**관련 스펙:** [feature-labeling-web-cloud.md](../specs/feature-labeling-web-cloud.md), [cloud-migration-roadmap.md](../specs/cloud-migration-roadmap.md)

**v2 production 완료(2026-07-12):** 한 화면에서 prediction을 숨긴 사람 GT를 먼저 잠그고, exact VLM snapshot을 공개해 verdict와 오류 유형을 저장한다. 큐 응답도 VLM 값을 포함하지 않으며 same-origin R2 썸네일, frame step/속도/단축키, moving과 wheel/object interaction 분리, VLM 없는 clip의 GT-only 완료를 구현했다. 운영 E2E로 30개 썸네일·blind GT·interaction validation·snapshot 공개·verdict 저장·다음 이동을 확인했다. 필수 GT는 visibility·대표/복수 관찰 행동·구간·target·확신도·품질/환경 tag이며 camera metadata는 시스템 상속한다. bbox/ROI·animal/enclosure 관리·audit metric은 후속 범위다. 상세 [라벨링 웹 v2 설계](superpowers/specs/2026-07-12-labeling-web-v2-design.md) · [RBA Data Engine v1](../specs/feature-rba-data-engine-v1.md).

상세 화면 상단에는 `camera_clips.started_at`의 KST 촬영 일시와 영상 길이를 표시한다.
`영상 다운로드`는 기존 clip 권한을 확인한 뒤 attachment disposition이 포함된 R2 signed
URL을 발급하며, Vercel을 거치지 않고 원본 MP4를 직접 내려받는다.

**가입·승인·간편 날짜(2026-07-13, 구현 완료·preview 검증 완료):** 팀원이 웹에서 직접 가입 신청하고
owner 가 같은 웹에서 승인·거절·권한 해제한다(Supabase Studio 수동 등록 폐기).
- **인증 ≠ 라벨링 권한** 분리. 접근 상태 = `owner / labeler / pending / rejected / unregistered`
  (`GET /api/labeling-access`, 판정 순서 owner→labelers→application→unregistered).
  **영상 접근 SOT 는 `labelers`** — `application.status='approved'` 단독으로 허용하지 않는다.
- 화면: `/labeling/signup`(가입+신청), `/labeling/apply`(기존 로그인 사용자 신청),
  `/labeling/pending`(대기·거절 안내), `/labeling/team`(owner 관리). 레이아웃이 access 확인
  전까지 중립 화면을 그려 pending 이 메뉴를 흘깃 보지 못하게 한다.
- 승인/거절/권한 해제는 원자 RPC `fn_review_labeler_application`(§DATABASE)로 `labelers`와
  신청 상태를 함께 갱신. owner 는 `DEV_USER_ID` 로 판정하고 관리 API 는 `requireOwner` 로 이중 검증.
- **접근 게이트 강화**: 큐·단건·영상 URL·라벨·GT·VLM 검수에 `requireLabelingAccess`(owner 또는
  실제 labelers 멤버)를 적용해 pending 사용자가 자기 소유 clip 으로 우회하지 못하게 했다.
- 단건 clip metadata GET도 공통 `loadClipWithPerms`를 사용한다. 가입·팀 관리·access·큐의
  DB 장애 응답은 내부 Supabase 메시지를 숨기고 서버 로그에만 남긴다.
- **KST 날짜 컨트롤**: 큐에서 오늘/어제/최근 3·7일 프리셋 + 이전·다음 날 이동 + 전체 기간.
  범위는 `+09:00` ISO 로 URL 에 남아 새로고침·공유가 된다(`web/src/lib/labelingDateRange.ts`).
- **GT 잠금 후 이어하기**: 큐 제외 기준을 본인 `clip_labeling_sessions.stage='completed'`로 바꿔,
  GT 만 잠그고 VLM 검수를 안 끝낸 영상이 `VLM 검수 이어하기` 배지로 큐에 남는다. 큐 응답엔
  stage 만 노출(prediction/VLM action 미포함)해 blind 를 유지한다.
- 완료 clip UUID 전체를 PostgREST `NOT IN` URL에 넣지 않는다. 최대 100개 후보 batch별로
  본인 session stage만 조회하고 페이지가 찰 때까지 이어서 읽어 검수 누적 시 URL 한계를 피한다.
- 초기 검증은 Python 334·Web 60·TypeScript와 Vercel preview
  `dpl_D45VbxNBBFBzsXYoLL7DeD939PDX`에서 수행했다. production 승격 뒤 실제 가입·owner 승인으로
  활동 중 라벨러가 2명이 됐고 승인 대기 0명을 운영 `/labeling/team`에서 확인했다. 최종 누적 회귀는
  Web 245·TypeScript·Python 334, Vercel production `dpl_5nsq7hqnKHcwKrZefqk7YozsrhmE` Ready다.
  미완료 라벨러는 tutorial gate로 본 큐가 막히며, 지정 pilot 1명의 5/5 뒤 본 큐 진입을 확인한다.

상세 [가입·승인·날짜 설계](superpowers/specs/2026-07-13-labeler-signup-date-controls-design.md).

**대화형 튜토리얼(2026-07-14, production 활성화·실사용 pilot 전):** 승인된 신규 라벨러는 owner가
확정한 동일한 5개 영상에서 `Blind GT → 고정 VLM 검수 → 기준 답·차이·해설`을 순서대로
학습하고, 5개 피드백을 모두 확인한 뒤 일반 큐에 들어간다. 점수 합격선은 두지 않으며
결과는 관리자 진단용이다.
- **provenance 분리**: 튜토리얼 attempt 는 `labeling_tutorial_attempts` 에만 저장하고
  production `behavior_labels`·`clip_labeling_sessions` 에 **0건 기록**한다.
- **정답 보호**: `reference_gt`·`feedback` 은 VLM 검수 제출 전 API 응답에 key 자체를 넣지 않고,
  4 테이블 모두 RLS+service_role 전용(정책 0건)이라 브라우저가 정답을 직접 조회할 수 없다.
- **서버 게이트**: 미완료 labeler 는 `loadClipWithPerms`·큐(`requireProductionLabelingAccess`)에서
  403 `tutorial_required` → 클라이언트가 `/labeling/tutorial` 로 이동. owner 전면 bypass.
  `GET /api/labeling-access` 가 `tutorial{required,status,completed_lessons}` 를 별도 축으로 반환.
- **owner 운영**: `/labeling/team` 에서 팀원별 진행·lesson별 mismatch 확인, `다시 시작`(run+1,
  기록 보존)·`완료 면제`(사유 1~200자). 5개 확정·활성화는 `fn_seed_tutorial_lesson_from_owner`
  + `fn_activate_tutorial_set` RPC(실 clip UUID 는 owner 가 별도 실행, 커밋엔 없음).
- **공유 UI**: 상세 페이지의 GT/VLM 폼·플레이어를 `_labeling-forms.tsx` 로 추출해
  production/tutorial 이 공유하되 저장 API 는 분리.
- **하드닝(후속 마이그레이션 `_hardening.sql` + `_hardening_2.sql`)**: active/archived lesson
  의 10필드(set/position/clip/title/objective/tip/reference/prediction/reference_vlm_review/
  feedback) 변경·삭제를 DB trigger 로 차단하되 판단은 **OLD.tutorial_set_id 기준**(active
  lesson 을 draft set 으로 옮기는 우회 차단). seed 는 draft set 전용 + owner session 의 VLM
  verdict/`completion_reason=vlm_reviewed`·비어있지 않은 feedback 검사. activation 은 draft
  전용 + 5 lesson verdict/feedback 완전성. Router Review API 도 production 게이트 적용,
  미완료 labeler 에게 work 메뉴 숨김, labelers 조회 오류는 일반 502(내부 메시지 은닉).
  reset/waive 는 대상이 실제 labeler 인지 검증(404), team-progress 는 네 쿼리 오류 모두 일반
  502. 레거시 무인증 `/api/label` 은 owner-only 로 잠금.
- **production 상태**: owner 보정 GT를 기준으로 `tutorial-v1` 5개 lesson을 seed하고 2026-07-14
  활성화했다. active set 1·lesson 5·position/clip 중복 0·reference/prediction/review/feedback 5/5를
  확인했고, 운영 `/labeling/tutorial`에서 `본작업 전 5개 연습 · 0/5`, `/labeling/team`에서
  승인 대기 0명·활동 중 라벨러 2명·두 명 모두 `tutorial-v1 0/5`를 확인했다. activation 직후
  attempts/progress는 0/0이었다.
- 검증: web 245 tests·tsc·Python 334 통과. 커밋 `0702e66`을 `main`에 푸시했고 Vercel production
  `dpl_5nsq7hqnKHcwKrZefqk7YozsrhmE`가 Ready인 상태에서 실제 첫 lesson 렌더와 console error 0을 확인했다.
  active lesson 불변은 DB 롤백 검증
  (move/position/title/reference/delete 5차단 ALL_PASS_ROLLBACK).
  **남음**: 두 라벨러 중 지정한 1명 5개 E2E pilot → 본 큐 진입·첫 본작업 5개 확인 → 나머지 팀원 개방.

**기준 GT·튜토리얼 UX 하드닝(2026-07-14, production 적용·활성화 완료):** owner 가 튜토리얼
기준 5개를 실제 화면에서 검수하며 발견한 문제(기본값이 정답처럼 저장됨, wheel 을 drinking 의
target 으로 오기입, 근거 없는 hand_feeding, absent 인데 활동 강도 저장)를 일반 라벨러가 반복하지
않도록 입력 경험·서버 계약·보정 감사·seed 사전검사를 함께 고쳤다.
- **중립 선택**: `visibility`/`primary_action` 은 라벨러가 직접 고르기 전까지 선택된 것처럼
  보이지 않는다(값 계약은 유지, 폼이 `explicitlySelected` 로 프리셀렉트만 제거).
- **공통 검증 issue 모델**: client(폼 인라인 오류)와 server(400 `detail`+`issues[]`)가 하나의
  순수 함수 `collectGroundTruthIssues` 를 공유한다. 규칙 9개 — 명시 선택, absent→unseen 정규화,
  관찰≥1, action당 segment 정확히 1, 범위, wheel object+type, drinking target 화이트리스트
  (water/water_bowl/glass/floor/uncertain), hand_feeding 3근거(licking·prey_capture / hand·tool /
  human), playing 금지. client 가 이슈를 먼저 계산해 없을 때만 API 호출하고 첫 오류로 scroll/focus.
- **조건부 form·문구**: absent 면 세부 동작·구간·대표 행동 대상·활동 강도·놀이 근거를 숨기고
  `해당 없음` 정규화. `행동 대상`→`대표 행동 대상`으로 명명하고 drinking/hand_feeding 은 허용
  대상만 노출. 대표 행동별 도움말 + hand_feeding 객관 근거 체크리스트 + wheel evidence 는
  대표 행동 대상과 별개임을 패널에서 명시. 튜토리얼 비교는 absent reference 의 activity_intensity
  를 subjective 로 내린다.
- **owner 현재 GT 보정**: completed 세션에서 owner 에게만 `현재 GT 보정` 버튼 노출. 최초
  `initial_gt` 는 보존하고 `current_gt`/VLM review 만 사유(10~500자)와 함께 append-only revision
  으로 보정한다(`fn_revise_clip_labeling_session`, service_role 전용, §DATABASE). API
  (`/api/labeling-v2/[clipId]/revise`)는 bearer→owner→body→GT/VLM validator→RPC 순서. 무인증
  401·비owner 403·세션 없음 404·DB 오류 일반 502. 일반 labeler 에겐 버튼·route·데이터 모두 미노출.
- **seed 의미 preflight**: seed RPC 3차 하드닝이 position 별 lesson 의미(1 absent/unseen·2 moving·
  3 wheel evidence·4 hand_feeding·5 VLM shedding 오판)를 검사해 reference GT 가 lesson 목적과
  안 맞으면 seed 전에 fail-loud.
- **기준 영상 보정·활성화**: `e679f8ad`는 owner 보정 UI로 drinking target을 실제 접촉면
  `glass`로, `d9346cbe`는 hand_feeding context를 `human`으로 보정해 append-only revision 2건을
  남겼다. position 1~5 의미 preflight 5/5 후 seed·활성화했고, position 3의 제출 전 문구는 정답을
  노출하지 않되 제출 후 feedback에서 `glass`와 wheel evidence 분리를 설명한다.
- 검증: web 245 tests(collectGroundTruthIssues 9규칙·allowedTargets·diff·튜토리얼 absent 비교·
  reference 의미 fixture·revise route 401/403/404/502·GT route issues[]), tsc·Python 334 통과.
  **DB 롤백 probe 통과**(원자 보정·initial_gt 불변·reviewer/reason 차단·seed mismatch 차단).
  Vercel production build·실화면 확인 통과. **남음**: 실제 라벨러 pilot과 완료 후 SOT 운영 결과 갱신.

상세 [기준 GT·튜토리얼 UX 하드닝 설계](superpowers/specs/2026-07-13-labeling-reference-ux-hardening-design.md).
상세 [대화형 튜토리얼 설계](superpowers/specs/2026-07-13-labeling-interactive-tutorial-design.md) ·
[구현 계획](superpowers/plans/2026-07-13-labeling-interactive-tutorial-plan.md) ·
[쉬운 말·입력 복구와 조건부 tutorial-v2 계획](superpowers/specs/2026-07-14-labeling-tutorial-plain-language-v2-design.md).
팀원 전달 문구와 관리자 운영 순서는 [라벨러 온보딩 안내](LABELER-ONBOARDING.md)를 따른다.

---

## 11.5. 라벨링 후보 격리함 (owner 전용, production 배포·Preview 검수 완료)

**무엇**
- 라벨링 가치가 낮아 보이는 `camera_clips`(빈 화면·정적)을 owner 전용 격리함으로 라우팅해, 사람 라벨링 시간을 실제 행동 영상에 먼저 쓰게 하는 작업 큐. 영상·GT 삭제 없음.
- 3탭: `검토 필요`(시스템이 quarantine 제안, owner 미결정) / `라벨링 안 함`(owner skip) / `라벨링으로 보냄`(owner label). owner 결정이 시스템 제안보다 항상 우선.
- 일반 라벨링 큐(`GET /api/labeling-v2/queue`)는 후보 batch별 triage를 조회해 `검토 필요`/`라벨링 안 함`을 제외한다. `모르면 본 큐 유지`(triage 없음/unknown/오류는 남김).
- owner는 본 큐 카드의 `격리함으로` 버튼으로 수동 격리도 가능. 이미 라벨링 세션이 생긴 clip은 자동 격리·skip·수동 격리 모두 거부(`409 labeling_started`).

**왜**
- 영상이 빠르게 쌓이는데 전부 같은 우선순위로 사람에게 보이면 라벨러가 빈/정적 영상에 시간을 낭비한다. 삭제 위험 없이 되돌릴 수 있는 감사 가능한 큐 이동으로 분리.
- 자동 삭제·자동 GT 아님(§13 범위 밖). Gate는 evidence sensor일 뿐, 제품 라우팅·격리 정책은 labeling DB가 담당(연구 트랙 분리).

**어디**
- DB: `clip_labeling_triage` / `clip_labeling_triage_events` + RPC 3(`migrations/2026-07-15_labeling_triage.sql`). DATABASE.md 참조.
- 공유 상태: [web/src/lib/labelingTriage.ts](../web/src/lib/labelingTriage.ts)(유효 상태·표시 문구), [labelingTriageServer.ts](../web/src/lib/labelingTriageServer.ts)(cursor·owner-safe 매핑, evidence 비노출).
- 큐 필터: [web/src/lib/labelingQueue.ts](../web/src/lib/labelingQueue.ts) `fetchTriage` + [api/labeling-v2/queue/route.ts](../web/src/app/api/labeling-v2/queue/route.ts).
- owner API: [api/labeling-triage/](../web/src/app/api/labeling-triage/) (목록/상세/PATCH 결정/수동 격리 POST), 전부 `requireOwner`.
- UI: [labeling/quarantine/page.tsx](../web/src/app/labeling/quarantine/page.tsx)(3탭 목록), [quarantine/[clipId]/page.tsx](../web/src/app/labeling/quarantine/[clipId]/page.tsx)(영상 검토·결정·auto-next).

**2차 하드닝(migration 적용 전 보완):** ①세션↔격리 양방향 원자성 — `clip_labeling_sessions` 가드 트리거가 quarantine/skip clip의 새 세션 생성을 DB에서 차단(`PT409`), RPC+트리거 lock 순서 통일 ②GT 저장 API 격리 사전검사(`409 triage_quarantined`)+DB 원문 비노출 502 ③촬영일·카메라 필터(list/count/cursor/상세 next) + triage 대상 카메라만 주는 옵션 RPC ④상세 clip 전환 상태 초기화·영상 실패 재시도·URL/실제 상태 불일치 409 ⑤`has_motion+r2_key` fail-closed. DATABASE.md 참조.

**상태:** 코드·H7 하드닝, production migration·rollback probe, Vercel 배포와 owner E2E까지 완료했다. `petcam-nightly-reporter` worker의 read-only Preview 30을 owner가 blind 검수한 결과는 `라벨링 필요 24 / 라벨링 안 함 4 / 판단 어려움 2`였다. 시스템 quarantine 3건 중 실제 제외 가능은 1건뿐이고, `gate_static` 2건은 모두 owner가 라벨링 필요로 판정했다(격리 precision 33.3%, false exclusion 2건). 따라서 **제안 write canary·backfill·write-enabled launchd는 중단**했고 triage/event row는 계속 0이다. `gate_static → quarantine`은 폐기하고, `gate_absent`도 1/1 표본으로는 부족해 추가 독립 holdout 전까지 쓰지 않는다. 일반 라벨링 큐는 기존처럼 모두 유지된다.

**관련 스펙:** [격리함 설계](superpowers/specs/2026-07-15-labeling-triage-quarantine-design.md) · [구현 계획](superpowers/plans/2026-07-15-labeling-triage-quarantine.md).

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
