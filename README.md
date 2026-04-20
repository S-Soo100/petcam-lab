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
| **A** | 스트리밍 + 서버 파일 저장 (MVP) | 🚧 진행 |
| **B** | OpenCV 움직임 감지 + 클립 분리 | 대기 |
| **C** | 메타데이터 DB + 클립 조회 API | 대기 |
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

서버 시작 시 백그라운드 스레드에서 RTSP 프레임을 계속 받아 **1분 단위 mp4 세그먼트**로 저장.

저장 경로: `storage/clips/{YYYY-MM-DD}/{CAMERA_ID}/{HHMMSS}.mp4`

### 3. 엔드포인트

| 경로 | 설명 |
|------|------|
| `GET /` | 생존 확인 |
| `GET /health` | 상태 + 캡처 워커 부착 여부 |
| `GET /streams/{camera_id}/status` | 캡처 상태 스냅샷 (JSON) |
| `GET /docs` | 자동 생성 Swagger UI |

**사용 예**
```bash
curl -s http://localhost:8000/streams/cam-1/status | python -m json.tool
```

### 4. 환경변수

| 변수 | 기본값 | 역할 |
|------|-------|------|
| `RTSP_URL` | (필수) | 카메라 RTSP 주소 |
| `CAMERA_ID` | `cam-1` | status 경로에 쓰이는 식별자 |
| `SEGMENT_SECONDS` | `60` | mp4 세그먼트 길이 (초) |
| `CLIPS_DIR` | `storage/clips` | 세그먼트 루트 경로 |
| `TEST_SNAPSHOT_PATH` | `storage/test_snapshot.jpg` | 스모크 테스트 저장 경로 |

## 테스트

```bash
uv run pytest -xv
```

- 실제 RTSP 연결에 의존하지 않는 단위 테스트. fake numpy 프레임으로 세그먼트 생성·쓰기 경로만 검증.
- 통합 테스트(실 카메라 의존)는 아직 미도입.

## 참고

- 상위 제품 문서: `../tera-ai-product-master/products/petcam/`
- FastAPI 공식: https://fastapi.tiangolo.com/
- OpenCV-Python: https://docs.opencv.org/
