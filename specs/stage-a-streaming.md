# Stage A — RTSP 스트리밍 + 서버 파일 저장 (MVP)

> RTSP 카메라(스마트폰 IP Webcam / Tapo C200)에서 영상을 받아 서버 로컬 파일로 저장하고, 최소 FastAPI 엔드포인트로 상태를 노출한다.

**상태:** 🚧 진행 중
**작성:** 2026-04-17
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` (Stage A 항목)

## 1. 목적

- **사용자 가치**: 카메라 → 서버 경로가 end-to-end로 돌아가는 최소 회로 확보. 후속 스테이지(움직임 감지, DB 저장)의 기반.
- **학습 목표**: FastAPI 기본 구조, OpenCV `VideoCapture` 라이프사이클, async vs sync 핸들러, `.env` 기반 설정, uvicorn 실행.

## 2. 스코프

### In (이번 스펙에서 한다)
- `scripts/test_rtsp.py` — RTSP 연결 스모크 테스트 (이미 뼈대 있음)
- `backend/main.py` — FastAPI 앱 엔트리 + `GET /health` 엔드포인트
- `backend/capture.py` — RTSP 캡처 루프 (백그라운드 스레드 또는 asyncio task)
- 영상을 **1분 단위 세그먼트**로 `storage/clips/{YYYY-MM-DD}/{HHMMSS}.mp4` 저장
- `GET /streams/{camera_id}/status` — 연결 상태, 최근 프레임 타임스탬프, 세그먼트 개수
- 로컬 개발 실행 문서화 (`README.md` 업데이트)

### Out (이번 스펙에서 안 한다)
- 움직임 감지 / 클립 분리 → **Stage B**
- DB 저장 (SQLite/Supabase) → **Stage C**
- 인증 / JWT 검증 → **Stage D**
- 실시간 스트리밍 뷰어 (웹/앱) — 일단 파일 저장만, 재생은 VLC 등으로 수동 확인
- 멀티 카메라 동시 캡처 — 1대만 동작 검증 후 나중에
- 온디바이스 필터링 → **Stage E**

### 경계 사유
- MVP는 "녹화가 된다"까지만. 감지·뷰어·인증을 한 번에 넣으면 디버깅 포인트가 너무 많음.

## 3. 완료 조건

- [x] `uv run python scripts/test_rtsp.py` → IP Webcam으로 `storage/test_snapshot.jpg` 저장 성공 (2026-04-17)
- [ ] Tapo C200 배송 후 같은 스크립트로 Tapo URL 재확인
- [ ] `uv run uvicorn backend.main:app --reload` 실행 → `http://localhost:8000/health` 200
- [ ] 캡처 루프 시작 → 최소 2분 돌려서 `storage/clips/{오늘날짜}/` 아래 세그먼트 2개 이상 생성
- [ ] 저장된 `.mp4` 파일을 VLC로 열어 재생 확인 (코덱 정상)
- [ ] `GET /streams/{camera_id}/status` → 연결 상태 + 마지막 프레임 타임스탬프 반환
- [ ] 캡처 루프에 3회 재시도 로직 포함 (RTSP 일시 끊김 대응)
- [ ] `pytest tests/` 최소 1개 통과 (fake numpy frame으로 세그먼트 writer 단위 테스트)
- [ ] README.md에 로컬 실행 절차 + 스마트폰 IP Webcam 세팅 방법 추가

## 4. 설계 메모

### 선택한 방법
- _작업 진행하면서 채움_

### 주요 설계 질문 (작업 중 답 채울 것)
- **캡처 스레드 모델**: `threading.Thread` vs `asyncio.to_thread` vs `multiprocessing`? → OpenCV 블로킹 I/O라 asyncio에 직접 못 넣음.
- **세그먼트 분리 방식**: OpenCV `VideoWriter` 1분마다 닫고 새로 열기 vs FFmpeg subprocess로 HLS 세그먼트 생성? → MVP는 OpenCV가 단순.
- **카메라 식별자**: 현재는 `.env`에 URL 1개만. 다중 카메라 확장 시 `{camera_id: url}` 맵으로 바꿔야 함.
- **상태 저장 위치**: 메모리(dict) vs 파일? → MVP는 메모리. 재시작하면 날아감 감수.

### 리스크 / 미해결 질문
- Tapo C200 RTSP 인증이 실제로 `/stream1` 경로로 되는지 확인 필요 (Tapo 앱에서 RTSP 계정 별도 생성 필요할 수 있음).
- OpenCV `VideoWriter`의 H.264 인코딩이 macOS에서 추가 패키지 필요할 수 있음 (FFmpeg 설치 여부 확인).

## 4.5. 실험 기록

작업 진행 중 환경별 세팅값·관찰 기록. 개인 개발 환경 기준이라 비밀값 아닌 것만.

### 2026-04-17 — IP Webcam (Android 공기계)
- **기기 IP**: `192.168.0.123` / 포트 `8080`
- **RTSP URL**: `rtsp://192.168.0.123:8080/h264_ulaw.sdp` (인증 없이 연결 성공)
- **캡처 해상도**: 1920×1080
- **연결 시간**: 첫 프레임까지 ~2초
- **관찰**:
  - 첫 실행에서 렌즈가 바닥 → 완전 검은 프레임. 카메라 물리 상태 체크가 코드 디버깅보다 먼저.
  - 최초 시도 때는 H.264 `no frame!`/`Missing reference picture` 경고 다수. 두 번째 시도는 경고 없음 → 스트림이 안정화된 후 read 호출하면 키프레임 받기 쉬움. 실 운영에서는 "유효 프레임 올 때까지 N회 재시도" 로직 필요.
- **상태**: ✅ 완료

## 5. 학습 노트

- **OpenCV `VideoCapture(rtsp_url)` 초기 동작**: RTSP 연결은 `isOpened()` 성공 후에도 실제 디코딩 가능한 I-frame이 올 때까지 짧은 버퍼링 시간 필요. 첫 `read()` 호출이 키프레임 받기 전이면 부분 복원 프레임이나 검은 프레임 반환. **실 운영 패턴**: 연결 직후 N프레임(5~10) 버리거나, `read()` 실패 시 재시도. JS로 치면 WebRTC `RTCPeerConnection` 의 ICE gathering 지연 + first packet 버퍼링과 유사.
- **RTSP URL 경로는 서버 구현에 따라 다름**: Tapo는 `/stream1`, IP Webcam은 `/h264_ulaw.sdp`. RFC로 표준화된 게 아니라 각 서버가 SDP를 expose하는 경로가 다름. 첫 연결 시 공식 문서/앱 내 안내 확인 필수.
- **`python-dotenv` + `Path(__file__).resolve().parent.parent`**: 스크립트 위치 기준 절대경로. CWD에 의존 안 함 → `cd` 어디서 실행해도 같은 동작. Node의 `path.resolve(__dirname, '..')` 과 동일 패턴.

- **FastAPI 앱 구조**: (Stage A 이번 마일스톤에서 다룰 예정)
- **async vs sync 핸들러 판단**:
- **uvicorn --reload 동작 원리**:

## 6. 참고

- SOT 스펙: [`petcam-backend-dev.md`](../../tera-ai-product-master/docs/specs/petcam-backend-dev.md)
- FastAPI 공식: https://fastapi.tiangolo.com/tutorial/first-steps/
- OpenCV VideoCapture: https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html
- IP Webcam (Android): https://play.google.com/store/apps/details?id=com.pas.webcam
- Tapo C200 RTSP: 공식 지원, Tapo 앱 → 카메라 설정 → Advanced → Camera Account
