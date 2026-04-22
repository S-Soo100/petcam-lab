# petcam-lab

> 도마뱀 특화 펫캠 (게코 캠) 영상 백엔드 서비스. 학습 겸 실제 제품 코드.

## 상위 기획

이 레포는 `tera-ai-product-master` 레포의 아래 기획 문서를 구현한다:

- [제품 기획 (B2C 게코 캠)](../tera-ai-product-master/docs/specs/petcam-b2c.md)
- [백엔드 개발 기획 스펙](../tera-ai-product-master/docs/specs/petcam-backend-dev.md)
- [제품 포지션 요약](../tera-ai-product-master/products/petcam/README.md)

## 기술 스택

- **Python 3.12+** (예정)
- **FastAPI** — 웹 프레임워크
- **uvicorn** — ASGI 서버
- **OpenCV** (`opencv-python`) — 영상 I/O 및 움직임 감지
- **FFmpeg** — 영상 인코딩/디코딩 (나중 도입)
- **uv** — 패키지/환경 매니저

## 아키텍처 요약

메인 앱 백엔드는 **Supabase**. 영상 서비스는 **별도 Python FastAPI 서버**로 분리.

- **로컬 개발 초기**: FastAPI 독립 운영 (자체 DB/파일 저장)
- **중기**: Supabase Auth JWT 검증 + Supabase Postgres 연동
- **후기**: Supabase Storage 또는 독립 스토리지로 영상 저장

상세: [`petcam-backend-dev.md`](../tera-ai-product-master/docs/specs/petcam-backend-dev.md)

## 폴더 구조

```
petcam-lab/
├── backend/          # FastAPI 서버 코드
├── scripts/          # 실험 스크립트 (RTSP 테스트 등)
├── storage/          # 영상·클립 저장 (gitignore)
├── tests/            # 테스트 코드
├── .gitignore
├── README.md
└── pyproject.toml    # uv 설정 (uv init 후 생성)
```

## 카메라 소스

- **실제 기기**: TP-Link Tapo C200 × 2대 (주문 완료, 배송 대기 중)
  - RTSP URL: `rtsp://<user>:<pass>@<IP>:554/stream1`
- **대기 중 대체**: 스마트폰 IP 캠 앱
  - Android: `IP Webcam`
  - iOS: `iVCam` 또는 `EpocCam`

## 개발 로드맵

| Stage | 내용 | 상태 |
|-------|------|------|
| **A** | 스트리밍 + 서버 파일 저장 (MVP) | ✅ 완료 |
| **B** | OpenCV 움직임 감지 + 클립 분리 | ✅ 완료 |
| **C** | 메타데이터 DB + 클립 조회 API | ✅ 완료 |
| **D** | Supabase Auth 연동 + 카메라 등록 + 외부 접속 + 앱 연결 | 🚧 D1·D2·D4 완료 |
| **E** | 온디바이스 필터링 (ESP32-CAM) | 나중 |

## 셋업 (최초 1회)

```bash
# uv 설치
brew install uv

# 의존성 설치 (pyproject.toml 기준 자동 싱크)
cd /Users/baek/petcam-lab
uv sync

# .env 생성
cp .env.example .env
# → .env 파일을 열어 RTSP_URL 을 실제 카메라 주소로 교체
```

### RTSP 소스 세팅

**Tapo C200 (실제 기기)**
1. Tapo 앱에서 카메라 설정 → Advanced → Camera Account 활성화 후 계정 생성
2. `.env` 의 `RTSP_URL` 을 `rtsp://<user>:<pass>@<카메라IP>:554/stream2` 로 설정
   - stream1 = 1080p, stream2 = 720p (기본 권장)
3. **macOS Local Network Permission** 필수: 시스템 설정 → 개인정보 보호 및 보안 → 로컬 네트워크 → VSCode(또는 Terminal) 토글 ON 후 재시작
   - 미허용 시 `No route to host` 오류 발생. 자세한 진단 절차는 [`specs/stage-a-streaming.md`](specs/stage-a-streaming.md) "macOS Local Network Permission" 학습 노트 참조

**스마트폰 IP Webcam (대체 소스)**
- Android: Play 스토어 `IP Webcam` 앱 → 서버 시작 → 화면에 표시된 `http://IP:8080` 참고
- `.env` 의 `RTSP_URL` 을 `rtsp://<IP>:8080/h264_ulaw.sdp` (앱 설정에 따라 경로 다름)
- 인증 없음 기본 설정

## 로컬 실행

### 1. RTSP 스모크 테스트 (한 프레임만 찍어 저장)

```bash
uv run python scripts/test_rtsp.py
# 성공 시 storage/test_snapshot.jpg 생성
```

### 2. FastAPI 서버 기동 (백그라운드 캡처 포함)

```bash
uv run uvicorn backend.main:app --reload
```

서버 시작 시 백그라운드 스레드에서 RTSP 프레임을 계속 받아 **1분 단위 mp4 세그먼트**로 저장. 각 세그먼트는 **움직임 있었는지** 판정되어 파일명 접미사로 구분.

저장 경로: `storage/clips/{YYYY-MM-DD}/{CAMERA_ID}/{HHMMSS}_{motion|idle}.mp4`

예시:
```
storage/clips/2026-04-20/cam-1/
├── 211147_motion.mp4   ← 이 1분에 도마뱀이 움직였음
├── 211247_idle.mp4     ← 가만히 있었음
└── 211347_motion.mp4
```

**세그먼트 품질 보장 (Stage B)**
- **CFR 보정**: 네트워크 jitter 로 수신 FPS 가 요동쳐도 재생 시간은 항상 60초 ±0.1. 부족하면 직전 프레임 복제 패딩, 넘치면 드롭.
- **코덱 avc1(H.264)**: mp4v 대비 ~70% 용량 감소 (1분당 2~5MB). OpenCV 빌드별 `avc1 → H264 → X264 → mp4v` 폴백.
- **깨진 세그먼트 자동 삭제**: 경과 <5초 또는 <50KB 는 unlink. 0초 영상 방지.

### 3. 엔드포인트

| 경로 | 설명 |
|------|------|
| `GET /` | 생존 확인 |
| `GET /health` | 상태 + 캡처 워커 부착 여부 |
| `GET /streams/{camera_id}/status` | 캡처 상태 스냅샷 (JSON) |
| `GET /clips` | 클립 목록 (필터·페이지네이션, Stage C) |
| `GET /clips/{id}` | 단건 메타 (Stage C) |
| `GET /clips/{id}/file` | mp4 스트리밍 + HTTP Range (Stage C) |
| `GET /clips/{id}/thumbnail` | 클립 대표 프레임 jpg (Stage D4) |
| `GET /docs` | 자동 생성 Swagger UI |

**사용 예**
```bash
curl -s http://localhost:8000/streams/cam-1/status | python -m json.tool
```

**응답 주요 필드**
```
{
  "camera_id": "cam-1",
  "is_connected": true,
  "frames_read": 14321,          // 누적 프레임 수
  "segments_written": 12,         // 저장 완료된 세그먼트 개수
  "current_segment": "211147.mp4",
  "frame_size": [1280, 720],
  "fps": 12.3,                    // VideoWriter 에 실제 쓰이는 fps
  "measured_fps": 12.3,           // 워커 시작 시 10초 실측 (Stage B)
  "last_motion_ts": 1745000000.5, // 가장 최근 움직임 감지 epoch 초 (Stage B)
  "motion_segments_today": 3,     // 오늘 _motion.mp4 저장된 개수 (Stage B)
  "codec": "avc1",                // 실제로 열린 VideoWriter fourcc
  "last_changed_ratio": 0.85,     // 최근 프레임 픽셀 변화 % (튜닝용)
  "segment_motion_frames": 142    // 현재 세그먼트 누적 유효 motion 프레임 수
}
```

### 4. 환경변수

**캡처 기본**

| 변수 | 기본값 | 역할 |
|------|-------|------|
| `RTSP_URL` | (필수) | 카메라 RTSP 주소 |
| `CAMERA_ID` | `cam-1` | status 경로에 쓰이는 식별자 |
| `SEGMENT_SECONDS` | `60` | mp4 세그먼트 길이 (초) |
| `CLIPS_DIR` | `storage/clips` | 세그먼트 루트 경로 |
| `TEST_SNAPSHOT_PATH` | `storage/test_snapshot.jpg` | 스모크 테스트 저장 경로 |

**움직임 감지 (Stage B)**

| 변수 | 기본값 | 역할 |
|------|-------|------|
| `MOTION_PIXEL_THRESHOLD` | `25` | 두 프레임 간 픽셀 밝기 차이 임계(0~255). 노이즈 필터링 |
| `MOTION_PIXEL_RATIO` | `1.0` | 변한 픽셀 비율(%) 임계. 초과하면 해당 프레임을 motion 으로 판정 |
| `MOTION_MIN_DURATION_FRAMES` | `12` | N프레임 연속이어야 유효 motion run (≈ 1초) |
| `MOTION_SEGMENT_THRESHOLD_SEC` | `3.0` | 세그먼트 내 motion 누적 이 초 이상이면 `_motion.mp4` |

**튜닝 가이드**
- `_motion` 태그 너무 자주 붙음 (오탐) → `MOTION_PIXEL_RATIO` 를 `1.5` 로 올림
- 진짜 움직였는데 `_idle` 로 태그됨 (놓침) → `MOTION_PIXEL_RATIO` 를 `0.7` 로 낮춤
- 센서 노이즈로 파닥거림 → `MOTION_PIXEL_THRESHOLD` 를 `30~35` 로 올림
- UVB 램프 on/off 순간 false positive 는 Stage C 이후 해결 예정

## Stage C — 클립 메타 DB + 조회 API

세그먼트 close 마다 Supabase `camera_clips` 테이블에 INSERT. 앱(또는 curl) 이 `/clips` 로 목록·단건·파일 스트리밍 조회.

### 환경변수 (Supabase)

| 변수 | 기본값 | 역할 |
|------|-------|------|
| `SUPABASE_URL` | (필수) | 프로젝트 URL (`https://<ref>.supabase.co`) |
| `SUPABASE_SERVICE_ROLE_KEY` | (필수) | service_role 키 — RLS 바이패스. **클라이언트 배포 금지** |
| `DEV_USER_ID` | (필수) | Stage C 하드코딩 user_id. Stage D 에서 JWT 로 교체 |
| `DEV_PET_ID` | `""` | 선택. 빈 값이면 `camera_clips.pet_id = NULL` |

미설정 시 캡처는 동작, DB INSERT 만 생략 (`/health` 의 `startup_error` 로 확인).

### 장애 내성

- INSERT 실패 (네트워크·Supabase 장애) 시 `storage/pending_inserts.jsonl` 에 append
- 서버 기동 1회 + 30초 주기 flush → 복구되면 자동 전송
- 큐 최대 1000 라인, 초과 시 오래된 것부터 drop

### 엔드포인트 사용 예

**목록 (필터·페이지네이션)**
```bash
# 전체
curl -s http://localhost:8000/clips | python -m json.tool

# motion 있는 것만, 최근 10개
curl -s "http://localhost:8000/clips?has_motion=true&limit=10" | python -m json.tool

# 특정 카메라 + 기간
curl -s "http://localhost:8000/clips?camera_id=cam-1&from=2026-04-21T00:00:00Z&to=2026-04-22T00:00:00Z"

# 다음 페이지 (seek pagination)
curl -s "http://localhost:8000/clips?limit=10&cursor=2026-04-21T05:22:23%2B00:00"
```

응답 형식:
```
{
  "items": [ ...camera_clips 행... ],
  "count": 10,
  "next_cursor": "2026-04-21T05:22:23+00:00",   // 마지막 행의 started_at
  "has_more": true
}
```

**단건 메타**
```bash
curl -s http://localhost:8000/clips/<uuid>
```

**mp4 스트리밍 (HTTP Range 지원)**
```bash
# 전체 다운로드
curl -s http://localhost:8000/clips/<uuid>/file -o clip.mp4

# 처음 1KB 만 (브라우저 `<video>` 시크 시뮬레이션)
curl -s -H "Range: bytes=0-1023" http://localhost:8000/clips/<uuid>/file -o head.bin

# 끝 부분만
curl -s -H "Range: bytes=4000000-" http://localhost:8000/clips/<uuid>/file -o tail.bin
```

상태 코드:
- `200` — Range 없음, 전체 전송
- `206` — Range 유효, Partial Content
- `410` — DB 행은 있으나 파일이 디스크에 없음
- `416` — malformed / out-of-bounds Range
- `404` — 클립 id 자체가 없음

## Stage D1 — Auth 인프라 + 카메라 암호화

Stage C 까지는 `DEV_USER_ID` 하드코딩. D1 에서 **Supabase JWT 검증** 을 붙여 앱에서 실제 로그인 유저로 API 호출 가능하게 함. 동시에 카메라 등록(D2 예정) 에서 쓸 **Fernet 대칭 암호화 유틸** 을 선반영.

### Dev / Prod 모드 분기

`AUTH_MODE` 하나로 전환:

| 모드 | 동작 | 쓰는 곳 |
|------|------|--------|
| `dev` (기본) | `Authorization` 헤더 무시 → `DEV_USER_ID` 반환 | 로컬 개발, 기존 Stage C 테스트 호환 |
| `prod` | `Bearer <jwt>` 검증 → `sub` claim 반환 | 앱 연결, 외부 배포 |

서버 코드는 동일하게 `Depends(get_current_user_id)` 하나만 쓰면 됨 — 내부에서 `AUTH_MODE` 보고 자동 분기.

### 환경변수 (D1 신규)

| 변수 | 기본값 | 역할 |
|------|-------|------|
| `AUTH_MODE` | `dev` | `dev` 면 `DEV_USER_ID` 반환, `prod` 면 JWT 검증 |
| `SUPABASE_JWT_ISSUER` | — | `prod` 필수. 예: `https://<ref>.supabase.co/auth/v1` |
| `SUPABASE_JWKS_URL` | — | `prod` 필수. 예: `<issuer>/.well-known/jwks.json` |
| `CAMERA_SECRET_KEY` | (placeholder) | Fernet 32바이트 키. 카메라 비밀번호 암호화에 사용 |

### CAMERA_SECRET_KEY 생성

`.env` 의 `CAMERA_SECRET_KEY` 는 기본 placeholder → 반드시 실 키로 교체:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

출력값을 `.env` 의 `CAMERA_SECRET_KEY=` 뒤에 붙여넣기. **커밋 금지** (이미 `.gitignore` 대상).

키 분실 시 기존 암호문 복호 불가 → 카메라 재등록 필요. 운영 키는 별도 볼트(1Password 등) 에 백업.

### JWT 검증 흐름 (prod)

1. 클라이언트가 `Authorization: Bearer <supabase_jwt>` 헤더로 호출
2. FastAPI `Depends(get_current_user_id)` 가 헤더 파싱
3. `get_jwks()` 가 `SUPABASE_JWKS_URL` 에서 공개키 목록 fetch (**10분 TTL 캐시**)
4. 토큰 header 의 `kid` 로 JWKS 에서 매칭되는 키 찾기
5. RS256 서명 검증 + `iss` (`SUPABASE_JWT_ISSUER` 와 일치) + `exp` 체크
6. `sub` claim → `user_id` 로 라우트에 주입

실패는 모두 **401 AuthError** 로 통일 (구체 원인은 `detail` 에).

### 내부 유틸

- **`backend/auth.py`**
  - `get_current_user_id(authorization)` — 라우트에서 쓰는 dependency
  - `verify_jwt(token)` — 단위 검증 (JWKS fetch + RS256 + iss/exp)
  - `get_jwks()` — JWKS TTL 캐시 (module-global dict + `time.monotonic`)
  - `reset_jwks_cache()` — 테스트용
- **`backend/crypto.py`**
  - `encrypt_password(plaintext: str) -> str` / `decrypt_password(ciphertext: str) -> str`
  - `get_camera_fernet()` — lru_cache 싱글톤 + placeholder 가드
  - `reset_crypto_cache()` — 테스트용

## Stage D2 — `/cameras` CRUD + 테스트 연결

유저가 앱에서 카메라를 직접 등록·수정·삭제. 비번은 D1 Fernet 으로 암호화해 DB 에만 저장하고 응답에는 절대 싣지 않음.

### 테이블 `cameras`

- 컬럼: `id, user_id, pet_id, display_name, host, port(554), path('stream1'), username, password_encrypted, is_active, last_connected_at, created_at, updated_at`
- RLS: `SELECT/UPDATE/DELETE` 는 본인 행만 (`auth.uid() = user_id`). **INSERT 정책 없음** → 백엔드(service_role) 만 insert → test-connection 검증·암호화 우회 경로 차단
- 유니크 `(user_id, host, port, path)` — 같은 유저가 동일 RTSP 중복 등록 방지
- `updated_at` 자동 갱신 트리거 (`moddatetime`)

### 엔드포인트 6종

| Method | 경로 | 역할 |
|--------|------|------|
| POST | `/cameras/test-connection` | RTSP 핸드쉐이크 검증 (등록 전 호출) |
| POST | `/cameras` | 등록 — **자동 probe → 실패 시 400** |
| GET | `/cameras` | 본인 카메라 목록 (최신순) |
| GET | `/cameras/{id}` | 단건 |
| PATCH | `/cameras/{id}` | 부분 수정 (`password` 오면 재암호화) |
| DELETE | `/cameras/{id}` | 삭제 |

**응답에 `password_encrypted` 절대 포함 금지** — `CameraOut` 스키마에 해당 필드 자체를 두지 않음(Pydantic 이 자동 배제).

### 사용 예

```bash
# 테스트 연결 (등록 전)
curl -s -X POST http://localhost:8000/cameras/test-connection \
  -H 'Content-Type: application/json' \
  -d '{"host":"192.168.0.100","port":554,"path":"stream1","username":"admin","password":"pw"}'
# → {"success":true,"detail":"첫 프레임 수신 성공","frame_captured":true,"elapsed_ms":847,"frame_size":[1280,720]}

# 등록 (서버가 다시 probe → 성공 시 암호화 저장)
curl -s -X POST http://localhost:8000/cameras \
  -H 'Content-Type: application/json' \
  -d '{"display_name":"거실","host":"192.168.0.100","port":554,"path":"stream1","username":"admin","password":"pw"}'

# 목록
curl -s http://localhost:8000/cameras

# 비번만 변경 (재암호화)
curl -s -X PATCH http://localhost:8000/cameras/<uuid> \
  -H 'Content-Type: application/json' \
  -d '{"password":"new-pw"}'

# 삭제
curl -s -X DELETE http://localhost:8000/cameras/<uuid>
```

상태 코드:
- `201` — 등록 성공
- `200` — 조회/수정/삭제 성공 (test-connection 은 실패도 200 + `success=false`)
- `400` — 등록 시 probe 실패 또는 PATCH body 비어있음
- `404` — 다른 유저의 카메라 또는 미존재
- `409` — `(user_id, host, port, path)` 유니크 위반

## Stage D4 — 클립 썸네일

캡처 워커가 세그먼트 종료 시 대표 프레임 jpg 1장을 mp4 옆에 저장. 앱 클립 피드에서 썸네일로 미리 보기.

### 대표 프레임 선택 로직

| 세그먼트 타입 | 프레임 | 이유 |
|--------------|--------|------|
| `_motion.mp4` | 움직임이 **처음 감지된 프레임** | 뭐가 움직였는지 보려면 시작점이 가장 유용 |
| `_idle.mp4` | 세그먼트 **중간 (~30초 지점)** 프레임 | 특별한 사건 없으니 평균적 장면 |
| 둘 다 실패 | 세그먼트의 **마지막 유효 프레임** (fallback) | 빈 썸네일 대신 최소 한 장은 보장 |

### 파일명 규칙

mp4 와 **동일 basename + `.jpg` 확장자**:

```
storage/clips/2026-04-22/cam-1/
├── 163423_idle.mp4
├── 163423_idle.jpg      ← 썸네일 (30초 지점 프레임)
├── 163523_motion.mp4
└── 163523_motion.jpg    ← 썸네일 (motion 시작 프레임)
```

### DB 컬럼

`camera_clips.thumbnail_path TEXT NULL` — REPO_ROOT 기준 상대 경로 문자열. 기존 D4 이전 row 는 NULL (앱은 placeholder 표시).

### 엔드포인트 사용 예

```bash
# 썸네일 jpg 다운로드
curl -s http://localhost:8000/clips/<uuid>/thumbnail -o thumb.jpg
open thumb.jpg
```

상태 코드:
- `200` — `image/jpeg` 바이트 반환
- `404` — 세 가지 원인 (detail 로 구분):
  - `clip '<id>' not found` — DB row 없음
  - `thumbnail not generated for clip '<id>'` — `thumbnail_path` NULL (기존 클립 or 저장 실패)
  - `thumbnail file missing on disk: <path>` — DB 엔 있는데 디스크에서 사라짐

## 테스트

```bash
uv run pytest -xv
```

- **capture** (`test_capture.py`) — fake numpy 프레임으로 세그먼트 생성·쓰기 + CFR 보정 pure function
- **motion** (`test_motion.py`) — MotionDetector 임계 로직
- **pending_inserts** (`test_pending_inserts.py`) — JSONL 재시도 큐 enqueue/flush/trim/손상라인
- **clips API** (`test_clips_api.py`) — FastAPI TestClient + Supabase mock. 목록 필터·seek 페이지네이션·단건 404·Range 스트리밍 (200/206/410/416)
- **crypto** (`test_crypto.py`) — Fernet 라운드트립 + placeholder 가드 + 키 변조 검출 (Stage D1)
- **auth** (`test_auth.py`) — JWT 검증 (서명/exp/iss/kid), Dev/Prod 분기, JWKS TTL 캐시 (Stage D1)
- **rtsp_probe** (`test_rtsp_probe.py`) — URL 빌더·마스킹·probe 함수 (cv2 mock, Stage D2)
- **cameras API** (`test_cameras_api.py`) — 6 엔드포인트 CRUD + 확장 FakeSupabase (INSERT/UPDATE/DELETE) + 비번 누설 회귀 방지 (Stage D2)
- **thumbnail capture** (`test_thumbnail_capture.py`) — `_save_thumbnail` imwrite 성공/실패 + JPEG SOI 마커 검증 + `_record_clip` payload 에 `thumbnail_path` 주입 (Stage D4)
- **thumbnail API** — `test_clips_api.py` 에 `/clips/{id}/thumbnail` 404 3분기 (row 없음/NULL/디스크 없음) + 200 jpg 바이트 반환 + user_id 필터 격리 (Stage D4)

실 RTSP/실 Supabase 에 의존하는 통합 테스트는 수동 수행 (카메라 켜고 2분 녹화 → DB 확인). CI 자동화는 Stage D 이후 검토.

## 스펙 (Lightweight Spec-Driven)

각 Stage 의 스코프·완료 조건·설계 메모는 `specs/` 에 체크리스트로 관리. 진행 상태 한눈에 보기: [`specs/README.md`](specs/README.md).

## 참고

- 상위 제품 문서: `../tera-ai-product-master/products/petcam/`
- FastAPI 공식: https://fastapi.tiangolo.com/
- OpenCV-Python: https://docs.opencv.org/
