# Stage A — RTSP 스트리밍 + 서버 파일 저장 (MVP)

> RTSP 카메라(스마트폰 IP Webcam / Tapo C200)에서 영상을 받아 서버 로컬 파일로 저장하고, 최소 FastAPI 엔드포인트로 상태를 노출한다.

**상태:** ✅ 완료 (2026-04-20)
**작성:** 2026-04-17
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md` (Stage A 항목)

**완료 요약:** RTSP 스모크 테스트 → Tapo C200 연결 성공 → FastAPI 백그라운드 캡처 워커 + `/streams/{camera_id}/status` → 1분 단위 mp4 세그먼트 저장 + VLC 재생 확인 → pytest 2개 통과 → README 업데이트. 미해결: 재생 시간 46~47초 이슈(실수신 fps가 VideoWriter fps 미만) → Stage B에서 타임스탬프 기반 보정 시 함께 처리.

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
- [x] Tapo C200 배송 후 같은 스크립트로 Tapo URL 재확인 (2026-04-18, 1280x720)
- [x] `uv run uvicorn backend.main:app --reload` 실행 → `http://localhost:8000/health` 200 (2026-04-18)
- [x] 캡처 루프 시작 → 최소 2분 돌려서 `storage/clips/{오늘날짜}/` 아래 세그먼트 2개 이상 생성 (2026-04-20)
- [x] 저장된 `.mp4` 파일을 VLC로 열어 재생 확인 (코덱 정상) (2026-04-20, 재생 시간 46~47초 이슈는 별도 추적 — Stage B)
- [x] `GET /streams/{camera_id}/status` → 연결 상태 + 마지막 프레임 타임스탬프 반환 (2026-04-20)
- [x] 캡처 루프에 3회 재시도 로직 포함 (RTSP 일시 끊김 대응) (2026-04-18)
- [x] `pytest tests/` 최소 1개 통과 (fake numpy frame으로 세그먼트 writer 단위 테스트) (2026-04-20, 2 passed)
- [x] README.md에 로컬 실행 절차 + 스마트폰 IP Webcam 세팅 방법 추가 (2026-04-20)

## 4. 설계 메모

### 선택한 방법 (2026-04-20, Step C 구현)
- **스레드 모델**: `threading.Thread(daemon=True)` + `threading.Event` 로 종료 신호. OpenCV `read()`가 블로킹 C 호출이라 asyncio에 직접 못 넣음. 한 워커가 연결 실패 시 자체 재연결 루프.
- **세그먼트 분리**: OpenCV `VideoWriter` 1분마다 닫고 새로 열기. fourcc `mp4v` (macOS 기본 OpenCV + VLC 재생 OK, FFmpeg 의존 없음). H.264(`avc1`)는 Stage 나중에 트랜스코드 도입 시 교체.
- **카메라 식별자**: 현재는 `.env`의 `CAMERA_ID` 단일. 경로상 `{camera_id}`로 받지만 매칭 안 되면 404. 멀티 카메라는 Stage B/C에서 `{camera_id: worker}` 맵으로 확장 예정.
- **상태 공유**: `app.state.capture_worker` + `threading.Lock`으로 보호된 `CaptureState` dataclass. 재시작 시 카운터 리셋 허용. Stage D에서 DB 저장으로 대체.
- **FastAPI 라이프사이클**: `lifespan` async context manager (deprecated `on_event`는 피함).

### 주요 설계 질문 해소
- **캡처 스레드 모델**: `threading.Thread` 채택. ✅
- **세그먼트 분리 방식**: OpenCV `VideoWriter` 채택 (FFmpeg subprocess는 HLS 필요할 때). ✅
- **카메라 식별자**: 단일 `CAMERA_ID` 환경변수 → 필요 시 맵으로. ✅
- **상태 저장 위치**: 메모리(dataclass + lock). 재시작 시 소실 감수. ✅

### 여전히 미해결 (Stage B 이후)
- 세그먼트 roll-over 순간 프레임 1~2개 드롭 가능 (writer close → open 사이). Stage B 움직임 감지 단계에서 segment rotation 전략 재검토.
- fps 실측 계산 미적용 (소스 메타 또는 기본값 15 사용). 재생 속도 보정은 나중에.

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

### 2026-04-18 — Tapo C200 (실 제품)
- **기기 IP**: `192.168.0.149` / 포트 `554` (RTSP 표준)
- **RTSP URL**: `rtsp://geckocam1:****@192.168.0.149:554/stream2`
- **캡처 해상도**: 1280×720 (stream2 — 예상했던 360p 아니라 **720p**. 최신 Tapo 펌웨어는 stream2도 720p 제공)
- **연결 시간**: 첫 프레임까지 ~3초 (인증 + 스트림 협상 포함)
- **관찰**:
  - 첫 시도에 연결 성공, 재시도 로직 불발동 = 건강한 시스템
  - Tapo 자체 **타임스탬프 오버레이** (`2026-04-18 17:48:50`) + `tapo` 워터마크 박혀있음. 워터마크는 앱에서 끌 수 있음. 타임스탬프는 법적 증거 차원에서 유용할 수도.
  - `/stream2` 로 시작해서 실제 해상도 확인하는 전략이 주효 — 스펙 문서의 "360p" 가정은 펌웨어 버전에 따라 틀림.
- **Mac 쪽 이슈 — macOS Local Network Permission**:
  - 기본 바이너리(ping, nc)는 되지만 brew/uv 설치 바이너리(ffmpeg, python)는 **"No route to host"** 로 차단됨.
  - 시스템 설정 → 개인정보 보호 및 보안 → 로컬 네트워크 → Visual Studio Code ON.
  - VSCode 재시작 or 묵시적 거부 캐시 해소 후 동작.
  - **흔한 함정이라 향후 Tapo 프로비저닝 문서에 꼭 명시할 것.**
- **상태**: ✅ 완료

## 5. 학습 노트

- **OpenCV `VideoCapture(rtsp_url)` 초기 동작**: RTSP 연결은 `isOpened()` 성공 후에도 실제 디코딩 가능한 I-frame이 올 때까지 짧은 버퍼링 시간 필요. 첫 `read()` 호출이 키프레임 받기 전이면 부분 복원 프레임이나 검은 프레임 반환. **실 운영 패턴**: 연결 직후 N프레임(5~10) 버리거나, `read()` 실패 시 재시도. JS로 치면 WebRTC `RTCPeerConnection` 의 ICE gathering 지연 + first packet 버퍼링과 유사.
- **RTSP URL 경로는 서버 구현에 따라 다름**: Tapo는 `/stream1`, IP Webcam은 `/h264_ulaw.sdp`. RFC로 표준화된 게 아니라 각 서버가 SDP를 expose하는 경로가 다름. 첫 연결 시 공식 문서/앱 내 안내 확인 필수.
- **`python-dotenv` + `Path(__file__).resolve().parent.parent`**: 스크립트 위치 기준 절대경로. CWD에 의존 안 함 → `cd` 어디서 실행해도 같은 동작. Node의 `path.resolve(__dirname, '..')` 과 동일 패턴.
- **macOS Local Network Permission (Sonoma/Sequoia 이후)**: brew/uv로 설치한 CLI(ffmpeg, python)는 `192.168.x.x` 대역 접근 시 OS 권한 필요. 시스템 기본(ping, nc)은 면제. **증상**: `Connection ... failed: No route to host` (실제로는 "host 못 찾음"이 아니라 "앱이 차단됨"인데 메시지가 오해 유발). **진단 절차**: ping + nc는 성공 → ffprobe/opencv만 실패 → 권한 문제 확정. **해결**: `시스템 설정 → 개인정보 보호 및 보안 → 로컬 네트워크 → VSCode (or Terminal, iTerm) 토글 ON` + VSCode 재시작. 첫 시도에 다이얼로그 무시되면 수동 설정 필요.

- **Step C 전체 구조 — 메인 스레드 + 캡처 스레드**: FastAPI는 요청/응답 싱글 루프인데, 우리가 하고 싶은 건 "요청 없이도 계속 도는 영상 수신 루프". 해법은 **백그라운드 스레드를 하나 더 띄우는 것**. 서버가 켜지면 두 스레드가 동시에 도는 구조:
  - 메인 스레드: FastAPI가 HTTP 요청 기다리며 응답 (8000 포트)
  - 캡처 스레드: RTSP에서 계속 프레임 받아 mp4 파일로 적재
  - 두 스레드가 `CaptureState` dataclass를 공유 → 엔드포인트가 캡처 상태 조회 가능
  - 공유 시 반드시 `threading.Lock`으로 보호 (Python GIL은 단일 바이트코드만 atomic)
  - JS로 치면 Express 메인 루프 + `worker_threads`에 영상 처리 붙인 형태.

- **왜 `asyncio`가 아니라 `threading`?**: OpenCV `cv2.VideoCapture.read()`는 C 레벨 블로킹 I/O라 async 핸들러에 직접 넣으면 이벤트 루프 전체가 멈춤. `asyncio.to_thread`로 매 프레임을 wrap하는 방법도 있지만, 캡처는 "계속 도는 루프"라 전용 스레드가 직관적. 실제로 이 레포의 `donts/python.md` 4번 규칙과 같은 결정.

- **`threading` 3총사 — Thread, Event, Lock**:
  - `threading.Thread(target=fn, daemon=True)` — 별도 스레드에서 `fn` 실행. `daemon=True`는 메인 프로세스 끝나면 같이 죽음 (Node의 `unref()` 유사).
  - `threading.Event` — 스레드간 불린 신호. `set()` / `is_set()` / `wait(timeout)`. 여기선 "종료 신호"로 사용. `stop_event.wait(2.0)`은 "2초 대기하되 중간에 set되면 즉시 깸" — `time.sleep(2.0)`보다 **종료 반응성 좋음**. JS의 `AbortController.signal`과 비슷.
  - `threading.Lock` — 공유 자원 보호. `with self._lock:` 블록 안에서만 임계구역. JS엔 이 개념 자체 없음 (싱글 스레드라 불필요).

- **`@dataclass` — "그냥 데이터 담는 그릇"**: Python 기본 class는 `__init__` 직접 써야 하지만 `@dataclass` 데코레이터 붙이면 자동 생성. TypeScript의 `interface` + 기본값 조합. 동등성 비교(`__eq__`)도 자동. `dataclasses.asdict(state)`로 dict 변환 쉬움 → JSON 응답으로 바로.

- **FastAPI 앱 구조 — `lifespan` 패턴**: 구버전의 `@app.on_event("startup")` / `@app.on_event("shutdown")`은 deprecated. 현재 표준은 `@asynccontextmanager`로 정의한 async 함수:
  ```python
  @asynccontextmanager
  async def lifespan(app):
      # startup
      worker.start()
      yield       # ← 서버 돌아가는 시간
      # shutdown
      worker.stop()
  app = FastAPI(lifespan=lifespan)
  ```
  Express로 치면 `app.listen()` 시점 초기화 + `process.on('SIGTERM')` 정리를 **한 함수로** 묶은 것. `yield` 위는 startup, 아래는 shutdown, `yield` 자체는 "서버가 요청 받는 동안".

- **`app.state` — 앱 수명 동안 살아있는 보관함**: FastAPI의 `app.state`는 그냥 빈 Namespace 객체. 어디든 `app.state.xxx`로 붙이면 모든 엔드포인트에서 접근 가능. **전역 변수보다 권장되는 이유**는 테스트에서 app 인스턴스 격리 가능하기 때문. `Depends()`는 요청 스코프 주입이라 "앱 전체 하나만 있는 싱글톤"엔 맞지 않음 — 그때 쓰는 게 `app.state`.

- **`Optional[X]` vs `X | None`**: TypeScript의 `T | null`에 해당. Python 3.10+는 `float | None`도 지원하지만 `Optional[float]`도 여전히 주류.

- **캡처 루프 타이밍 — 어떻게 1분짜리 mp4가 만들어지나**: 스레드가 "1분간만 기록"하는 게 아니라 **서버 켜진 내내 계속 돌며 1분마다 파일 교체**하는 구조. 루프 한 바퀴 = 프레임 1장 처리:
  ```
  while not stop_event.is_set():
      ok, frame = cap.read()            # ① 프레임 1장 받기 (~60ms 블로킹)
      if writer is None:
          writer = open_new_segment()   # ② 첫 프레임이면 새 .mp4 열기
          segment_started = now
      writer.write(frame)               # ③ 파일 끝에 프레임 추가
      if now - segment_started >= 60:   # ④ 60초 경과 체크
          writer.release()              #    현재 파일 닫기 (저장 확정)
          writer = open_new_segment()   #    새 파일 열기
          segment_started = now
  ```
  Tapo C200 stream2는 초당 ~15 프레임 → 1분 파일 = 약 900 프레임 = 10~15 MB. 정각에 자르는 게 아니라 "60초 경과" 기준이라 첫 파일은 18:30:42 처럼 자투리 시작 가능.

- **왜 세그먼트 분할?**: (1) 용량 관리 — 한 파일 24시간이면 수십 GB, 오래된 것 삭제 단위가 됨. (2) 손상 복원력 — 파일 하나 깨져도 나머지 살아남음. (3) 특정 시각 빠르게 찾기. (4) Stage B의 "움직임 있는 세그먼트만 보관" 설계로 연결.

- **세그먼트 코덱 `mp4v`를 고른 이유**: macOS OpenCV 기본 빌드에 포함 → FFmpeg 별도 설치 없이 바로 `.mp4` 저장 가능. VLC/QuickTime/브라우저 모두 재생. 단점은 용량 — H.264(`avc1`)가 2~3배 작지만 FFmpeg 의존 있음. **Stage A는 호환성 우선**, 나중에 트랜스코딩 단계 들어가면 교체.

- **`async def` vs `def` 핸들러 — FastAPI 판단법**: FastAPI는 두 형태 모두 지원. **규칙**: 핸들러 안에서 블로킹 호출(`time.sleep`, `requests.get`, `cv2.imread`, 동기 DB 드라이버)을 쓰면 `def`(동기)로. 비동기 라이브러리(`httpx.AsyncClient`, `asyncpg`)만 쓰면 `async def`로. `def` 핸들러는 FastAPI가 자동으로 스레드풀에서 실행해서 이벤트 루프 안 막음. **잘못된 조합**: `async def` 안에서 동기 블로킹 함수 호출 → 루프 정지 → 전체 서버 먹통. 이번 `stream_status`는 락 걸고 메모리 복사만 하는 짧은 작업이라 `def`로 충분 (정확히는 어느 쪽이든 상관없지만 동기가 더 명료).

- **`uvicorn --reload` 동작 원리**: uvicorn이 파일시스템 watcher(watchfiles 패키지) 붙여서 `.py` 변경 감지 → **워커 프로세스 자체를 재시작**. 코드 수정 즉시 반영되지만 **인메모리 상태(캡처 상태 카운터, 누적 프레임 수)는 모두 리셋**. 실 운영은 `--reload` 없이 돌림. Node의 `nodemon`과 동일 컨셉.

- **Stage A의 네트워크 제약 — Pull 방식 한계**: 현재 구조는 서버가 카메라에 RTSP로 끌어오는 **Pull 방식**. 서버와 카메라가 **같은 사설 네트워크(WiFi)** 에 있어야 동작하고, 외부 네트워크에서 접근 불가. 실 B2C 제품은 **Push 방식(카메라가 클라우드로 outbound 연결)** 이 필수이며, Tapo 같은 상용 카메라는 제3자 서버 푸시 API를 열지 않기 때문에 **Stage E 자체 HW(ESP32-CAM)에서만 실현 가능**. 즉 Stage E는 "선택적 최적화"가 아니라 **상용화 크리티컬 패스**. 상세: SOT 스펙 [`petcam-backend-dev.md`](../../tera-ai-product-master/docs/specs/petcam-backend-dev.md) "네트워크 아키텍처 — Pull vs Push" 섹션.

## 6. 참고

- SOT 스펙: [`petcam-backend-dev.md`](../../tera-ai-product-master/docs/specs/petcam-backend-dev.md)
- FastAPI 공식: https://fastapi.tiangolo.com/tutorial/first-steps/
- OpenCV VideoCapture: https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html
- IP Webcam (Android): https://play.google.com/store/apps/details?id=com.pas.webcam
- Tapo C200 RTSP: 공식 지원, Tapo 앱 → 카메라 설정 → Advanced → Camera Account
