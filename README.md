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
| **D** | Supabase Auth 연동 + 앱 연결 | 대기 |
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

## 테스트

```bash
uv run pytest -xv
```

- **capture** (`test_capture.py`) — fake numpy 프레임으로 세그먼트 생성·쓰기 + CFR 보정 pure function
- **motion** (`test_motion.py`) — MotionDetector 임계 로직
- **pending_inserts** (`test_pending_inserts.py`) — JSONL 재시도 큐 enqueue/flush/trim/손상라인
- **clips API** (`test_clips_api.py`) — FastAPI TestClient + Supabase mock. 목록 필터·seek 페이지네이션·단건 404·Range 스트리밍 (200/206/410/416)

실 RTSP/실 Supabase 에 의존하는 통합 테스트는 수동 수행 (카메라 켜고 2분 녹화 → DB 확인). CI 자동화는 Stage D 이후 검토.

## 스펙 (Lightweight Spec-Driven)

각 Stage 의 스코프·완료 조건·설계 메모는 `specs/` 에 체크리스트로 관리. 진행 상태 한눈에 보기: [`specs/README.md`](specs/README.md).

## 참고

- 상위 제품 문서: `../tera-ai-product-master/products/petcam/`
- FastAPI 공식: https://fastapi.tiangolo.com/
- OpenCV-Python: https://docs.opencv.org/
