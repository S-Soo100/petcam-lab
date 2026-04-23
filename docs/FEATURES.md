# FEATURES — 이 백엔드가 해주는 일들

> "엔드포인트가 아니라 기능 단위" 로 본 petcam-lab. 각 기능마다 무엇/왜/어디 코드/관련 스펙.

Stage A ~ D5 를 거치면서 9개 기능 레이어가 쌓였다. 아래 순서는 데이터 흐름 순 (캡처 → 저장 → 조회 → 인증 → 배포 → QA).

---

## 1. 실시간 RTSP 캡처 (다중 카메라)

**무엇**
- 사용자가 등록한 N 대의 카메라 각각에 전용 스레드 워커를 띄워 RTSP 스트림을 상시 수신.
- 연결 끊겨도 3회 재시도 → 실패 시 2초마다 재연결 시도 (무한 반복).
- 워커별 상태(연결 여부, 누적 프레임 수, 현재 세그먼트, 에러 등) 는 `GET /streams/{camera_id}/status` 로 조회 가능.

**왜**
- OpenCV `cv2.VideoCapture.read()` 가 C 레벨 블로킹이라 asyncio 이벤트 루프와 격리 필요.
- 초기엔 env 로 카메라 1대 하드코딩 (Stage A~D2) → D3 에서 `cameras` 테이블 기반 다중 워커로 전환.

**어디**
- [backend/capture.py](../backend/capture.py) — `CaptureWorker` 클래스 + FPS 측정·재연결·세그먼트 저장 루프
- [backend/main.py](../backend/main.py) — `lifespan` 에서 `cameras` 테이블 SELECT → 워커 N 개 bootstrap

**튜닝 포인트**
- 재시도 상수: `CONNECT_MAX_RETRIES=3`, `FRAME_READ_MAX_FAILS=30`
- FPS 측정 구간: `FPS_MEASURE_SEC=10`초 (첫 세그먼트만 짧아지지만 이후 모든 세그먼트 재생 시간 정확)

**관련 스펙:** [stage-a-streaming.md](../specs/stage-a-streaming.md), [stage-d3-multi-capture.md](../specs/stage-d3-multi-capture.md)

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
- `camera_clips.thumbnail_path` 컬럼에 상대 경로 저장 → `GET /clips/{id}/thumbnail` 로 반환.

**왜**
- Flutter 앱 클립 피드에서 "영상 다운로드 없이 미리보기".
- mp4 디코딩 없이 jpg 한 장이 훨씬 빠름 (네트워크·파싱 둘 다).

**어디**
- [backend/capture.py](../backend/capture.py) — `_save_thumbnail` + 세그먼트 roll-over 시 프레임 캐싱
- [backend/routers/clips.py](../backend/routers/clips.py) — `GET /clips/{id}/thumbnail` (FileResponse)

**엣지케이스**
- `thumbnail_path` NULL 인 기존 클립 (D4 이전) → 404 "thumbnail not generated"
- DB 엔 있는데 디스크에서 사라짐 → 404 "thumbnail file missing on disk"

**관련 스펙:** [stage-d4-thumbnail.md](../specs/stage-d4-thumbnail.md)

---

## 5. 클립 메타 DB + 조회 API + Range 스트리밍

**무엇**
- 세그먼트 종료 시 Supabase `camera_clips` 테이블에 INSERT (user_id, camera_id, pet_id, started_at, duration_sec, has_motion, motion_frames, file_path, file_size, codec, width, height, fps, thumbnail_path).
- `GET /clips` — 필터(camera_id, has_motion, from, to) + **seek pagination** (`cursor = started_at`).
- `GET /clips/{id}` — 단건 메타.
- `GET /clips/{id}/file` — mp4 스트리밍, **HTTP Range 지원** (Flutter `video_player` 시크).
- `GET /clips/{id}/thumbnail` — jpg 반환.

**왜**
- `offset` 페이지네이션은 깊어질수록 느림 → `started_at < cursor` 인덱스 range scan.
- Range 헤더 없이 `StreamingResponse(open(path))` 만 쓰면 브라우저 시크 불가.
- **장애 내성**: Supabase 네트워크 장애 시 `storage/pending_inserts.jsonl` JSONL 큐에 append → 30초마다 flush 재시도. 큐 최대 1000 라인, 초과 시 오래된 것 drop.

**어디**
- [backend/routers/clips.py](../backend/routers/clips.py) — 목록/단건/파일/썸네일 4 엔드포인트
- [backend/clip_recorder.py](../backend/clip_recorder.py) — `make_clip_recorder` (user_id/pet_id 주입 + 미러 훅) + `make_flush_insert_fn`
- [backend/pending_inserts.py](../backend/pending_inserts.py) — `PendingInsertQueue` (thread-safe JSONL)

**상태 코드**
- `/clips/{id}/file`: 200 (Range 없음) / 206 (Partial Content) / 410 (DB 엔 있으나 파일 사라짐) / 416 (Range out-of-bounds) / 404 (id 없음)
- `/clips/{id}/thumbnail`: 200 / 404 3분기 (row 없음 / NULL / 파일 사라짐)

**관련 스펙:** [stage-c-db-api.md](../specs/stage-c-db-api.md), [stage-d4-thumbnail.md](../specs/stage-d4-thumbnail.md)

---

## 6. 카메라 CRUD + RTSP 자동 probe + 비번 암호화

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

## 7. Supabase JWT 인증 (dev/prod 분기)

**무엇**
- 모든 라우트가 `Depends(get_current_user_id)` 하나로 user_id 를 받음. 내부에서 `AUTH_MODE` 보고 자동 분기.
- `AUTH_MODE=dev` (기본) — `Authorization` 헤더 무시, `DEV_USER_ID` 반환. 로컬 개발·pytest 용.
- `AUTH_MODE=prod` — `Bearer <JWT>` 필수. Supabase JWKS 에서 공개키 fetch (10분 TTL 캐시) → 서명/`exp`/`iss` 검증 → `sub` claim 반환.
- 알고리즘 런타임 결정 — 현재 Supabase 는 `ES256` (P-256), 과거 프로젝트는 `RS256`. `jwt.PyJWK` 가 `kty` 보고 공개키 객체 자동 생성.

**왜**
- 로컬 개발 중에 JWT 발급 번거로움 → dev 모드로 우회.
- prod 전환은 `.env` 한 줄만 수정. 코드는 동일.
- JWKS TTL 캐시 — 매 요청마다 Supabase 호출하면 지연·비용. `@lru_cache` 는 TTL 없어서 키 회전 시 영구 캐시 위험 → 모듈 전역 dict + `time.monotonic` 10분.

**어디**
- [backend/auth.py](../backend/auth.py) — `get_current_user_id`, `verify_jwt`, `get_jwks`, `reset_jwks_cache`
- 모든 `backend/routers/*.py` — `Depends(get_current_user_id)` 로 주입

**에러 모델**
- 모든 인증 실패 → 401 `AuthError` (detail 로 원인 구분)
- 실패 원인: 헤더 없음 / Bearer 포맷 아님 / kid 매칭 실패 / 서명 불일치 / exp 만료 / iss 불일치 / sub 없음

**관련 스펙:** [stage-d1-auth-crypto.md](../specs/stage-d1-auth-crypto.md)

---

## 8. 외부 공개 (Cloudflare Named Tunnel + AUTH_MODE=prod)

**무엇**
- 로컬 맥북에서 돌던 백엔드를 `https://api.tera-ai.uk` 로 공개. Flutter 앱이 LTE/외부 Wi-Fi 에서도 접근.
- 백엔드는 `127.0.0.1:8000` 로만 바인딩 (외부 직결 차단) → `cloudflared tunnel run petcam-lab` 이 outbound 로 Cloudflare 에 연결 → Cloudflare 가 공개 HTTPS 종단 제공.
- 공유기 포트포워딩 불필요. 인증서 자동.

**왜**
- 맥북 IP 가 DHCP + 테더링/이동 → 고정 IP 없음. Tunnel 은 outbound 라 위치 무관.
- ngrok 은 무료 플랜 URL 이 매번 바뀜 → Cloudflare Named Tunnel 은 DNS CNAME 자동 고정 (`api.tera-ai.uk`).
- 24시간 상시 가동은 스코프 밖 — 사용자가 수동으로 서버 띄울 때만 접근 가능.

**어디**
- [backend/main.py](../backend/main.py) — `lifespan` 시작 시 `AUTH_MODE` 값을 warning 으로 로그 (실수 감지)
- 외부: `~/.cloudflared/config.yml` + `cloudflared tunnel run petcam-lab`

**운영 절차**
```bash
# 터미널 1 — 백엔드 (127.0.0.1 바인딩)
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000

# 터미널 2 — Cloudflare Tunnel
cloudflared tunnel run petcam-lab
```

두 프로세스 모두 살아있어야 외부 접근 가능. 상세: [DEPLOYMENT.md](DEPLOYMENT.md).

**관련 스펙:** [stage-d5-deploy-tunnel.md](../specs/stage-d5-deploy-tunnel.md)

---

## 9. QA 테스터 미러 (임시 인프라)

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

## 10. 다음 읽을 문서

- **코드 구조** → [ARCHITECTURE.md](ARCHITECTURE.md)
- **API 스펙** → [API.md](API.md)
- **DB 스키마** → [DATABASE.md](DATABASE.md)
- **용어** → [GLOSSARY.md](GLOSSARY.md)
