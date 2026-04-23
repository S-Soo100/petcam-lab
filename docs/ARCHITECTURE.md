# ARCHITECTURE — petcam-lab

> 이 레포의 백엔드가 외부 시스템과 어떻게 맞물리고, 내부 모듈이 어떻게 구성됐는지. 코드 읽기 전에 이거부터.

---

## 1. 한 줄 요약

**TP-Link Tapo C200 (또는 스마트폰 IP캠) 이 RTSP 로 영상을 쏘면, 이 Python FastAPI 백엔드가 받아서 1분 단위 mp4 로 잘라 저장하고, 움직임 감지 태깅 + 썸네일 생성 후 Supabase 에 메타데이터를 기록한다. Flutter 앱이 Supabase JWT 로 인증하고 `api.tera-ai.uk` (Cloudflare Tunnel) 를 통해 클립을 목록 조회·재생한다.**

---

## 2. 시스템 맵

```
┌──────────────┐        RTSP(554)        ┌─────────────────────────────────┐
│  Tapo C200   │ ──────────────────────► │                                 │
│  (또는 IP캠) │ ◄── 등록/삭제는 API로 ── │                                 │
└──────────────┘                         │      petcam-lab (FastAPI)       │
                                         │      ── 로컬 맥북에서 수동 가동 ──│
┌──────────────┐   GET /clips/{id}/file  │                                 │
│ Flutter app  │ ◄──────── Range ──────► │  ┌──────────────────────────┐  │
│ (LTE/Wi-Fi)  │                         │  │ capture worker × N (스레드) │  │
│              │     Supabase JWT        │  │   RTSP → mp4 + thumb     │  │
└──────┬───────┘                         │  └────────┬─────────────────┘  │
       │                                 │           │                      │
       │ HTTPS (api.tera-ai.uk)          │           ▼                      │
       ▼                                 │  ┌──────────────────────────┐  │
┌──────────────────┐                     │  │ routers: /clips /cameras │  │
│ Cloudflare       │                     │  │        /health /streams  │  │
│ Tunnel (Named)   │ ──── 127.0.0.1:8000 │  └────────┬─────────────────┘  │
└──────────────────┘                     └───────────┼──────────────────────┘
                                                     │
                                                     │ service_role (RLS bypass)
                                                     ▼
                                         ┌─────────────────────────────────┐
                                         │           Supabase              │
                                         │  ┌──────────────────────────┐  │
                                         │  │ auth.users (JWT issuer)  │  │
                                         │  │ cameras / camera_clips   │  │
                                         │  │ pets / clip_mirrors      │  │
                                         │  └──────────────────────────┘  │
                                         └─────────────────────────────────┘

                    storage/
                     └─ clips/{YYYY-MM-DD}/{camera_uuid}/
                         ├─ 163423_motion.mp4   (CFR-보정 60초 ±0.1)
                         ├─ 163423_motion.jpg   (대표 프레임 썸네일)
                         └─ pending_inserts.jsonl  (DB INSERT 재시도 큐)
```

**역할 분담**
| 컴포넌트 | 책임 | 이 레포 관리? |
|----------|------|--------------|
| Tapo C200 / IP캠 | RTSP 영상 송출 | X (외부 하드웨어) |
| Cloudflare Tunnel | 공개 도메인 + HTTPS + outbound 터널 | X (cloudflared CLI) |
| petcam-lab | 수신·저장·분석·API | **이 레포** |
| Supabase | Auth + Postgres + RLS | X (BaaS, 대시보드 관리) |
| Flutter 앱 | 사용자 UI | `tera-ai-flutter` 레포 |
| 기획 SOT | "무엇/왜" | `tera-ai-product-master` 레포 |

---

## 3. backend/ 내부 구조

```
backend/
├── main.py              FastAPI lifespan + 워커 부트스트랩 + /health /streams 라우트
├── routers/
│   ├── clips.py         GET /clips (목록/단건/파일/썸네일) — Stage C·D4
│   └── cameras.py       POST·GET·PATCH·DELETE /cameras — Stage D2
├── capture.py           CaptureWorker 스레드 (RTSP → mp4 + motion 태그 + CFR 보정 + 썸네일)
├── motion.py            MotionDetector (cv2.absdiff 프레임 차분)
├── clip_recorder.py     camera_clips INSERT 오케스트레이션 + clip_mirrors 훅
├── pending_inserts.py   JSONL 재시도 큐 (Supabase 장애 복구)
├── rtsp_probe.py        RTSP 테스트 연결 + URL 빌더 + 비번 마스킹
├── auth.py              Supabase JWT 검증 + get_current_user_id Depends
├── crypto.py            Fernet 카메라 비번 암복호화
└── supabase_client.py   Supabase service_role 싱글톤
```

**의존성 방향** (화살표 = "import 함")

```
main.py
  ├─► routers/clips.py ──────┐
  ├─► routers/cameras.py ────┤
  ├─► capture.py ──► motion.py
  │     └─► clip_recorder.py ──► pending_inserts.py
  ├─► crypto.py
  ├─► rtsp_probe.py
  └─► supabase_client.py
                              └──► auth.py (Depends 체인)
```

순환 의존 없음. 하위 모듈은 상위를 import 하지 않음.

---

## 4. 데이터 흐름 — "프레임 → 사용자 화면" 까지

```
 [1] Tapo C200  ──RTSP(H.264)──►  CaptureWorker._run
                                        │
 [2]  cv2.VideoCapture.read() (블로킹, 별도 스레드)
                                        │
 [3]  MotionDetector.update() — 프레임 차분 → is_motion_frame
                                        │
 [4]  CFR 보정 — compute_padding_count / should_drop_frame
                                        │
 [5]  cv2.VideoWriter.write() ──► storage/clips/YYYY-MM-DD/{uuid}/HHMMSS.mp4
                                        │
 [6]  세그먼트 60초 경과 → _close_and_tag_segment
        ├─ elapsed < 5s OR size < 50KB → unlink (깨진 세그먼트 제거)
        └─ 정상 → rename to HHMMSS_motion.mp4 또는 _idle.mp4
                                        │
 [7]  _save_thumbnail — 대표 프레임 jpg 저장 (mp4 옆)
                                        │
 [8]  _record_clip(payload) ──► clip_recorder.record
                                        │
 [9]  Supabase INSERT camera_clips (service_role)
        ├─ 성공 → _mirror_clip (clip_mirrors 매핑 있으면 복사 INSERT, best-effort)
        └─ 실패 (네트워크·키 등) → pending_inserts.jsonl 에 append
                                        │
 [10] 주기 flush (30초) → 큐 재전송 → 성공 row 제거
                                        │
 [11] Flutter 앱: GET /clips  (Authorization: Bearer <supabase JWT>)
        └─► backend/auth.get_current_user_id (JWT 검증 → sub)
        └─► routers/clips.list_clips (user_id 필터 + seek pagination)
                                        │
 [12] GET /clips/{id}/file (Range: bytes=N-)
        └─► StreamingResponse 206 Partial Content (256KB chunk)
                                        │
 [13] Flutter video_player 재생
```

**한 사이클 = 1분 세그먼트.** 캡처 워커는 하루 = 1440 세그먼트를 만들어낸다 (카메라당).

---

## 5. 동시성 모델

세 가지 동시성 축이 섞여 있다. 각자 역할 다름:

```
┌─────────────────────────────────────────────────────────────────────┐
│ FastAPI 이벤트 루프 (메인 스레드, asyncio)                           │
│                                                                      │
│   ┌─ lifespan() ────────────────────────────────────────────────┐  │
│   │  startup: cameras 테이블 SELECT → N 워커 .start()           │  │
│   │  yield (앱 동작 중)                                           │  │
│   │  shutdown: N 워커 .stop() + flush_task.cancel()              │  │
│   └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│   ┌─ HTTP 요청 핸들러 (동기 def) ───────────────────────────────┐  │
│   │  /clips, /cameras — Supabase I/O는 동기 클라이언트이므로    │  │
│   │   def 라우트. FastAPI 가 threadpool 로 실행 → 루프 안 막힘. │  │
│   └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│   ┌─ _periodic_flush (asyncio.Task) ────────────────────────────┐  │
│   │  30초 sleep → asyncio.to_thread(queue.flush, ...)           │  │
│   │  (큐 flush 는 파일 I/O + Supabase 호출 → 스레드풀)          │  │
│   └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                │ app.state.capture_workers: dict[uuid, CaptureWorker]
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│ CaptureWorker 스레드 × N (카메라 1대당 1개, daemon=True)             │
│                                                                      │
│   while not stop_event.is_set():                                    │
│     cv2.VideoCapture.read()   ← 블로킹 I/O (C 레벨)                │
│     MotionDetector.update()                                         │
│     cv2.VideoWriter.write()                                         │
│     (세그먼트 경계) → clip_recorder(payload)  ── Supabase INSERT   │
│                                                                      │
│   ▲ 상태 공유는 threading.Lock 으로 보호된 CaptureState             │
│   ▲ snapshot() 메서드가 deepcopy 해서 라우터에 전달                │
└─────────────────────────────────────────────────────────────────────┘
```

**세 줄 요약**
1. **asyncio 루프** — HTTP 핸들러 + 주기 flush 태스크. FastAPI 표준.
2. **캡처 스레드 (N개)** — OpenCV 블로킹 I/O 를 이벤트 루프와 격리. `daemon=True` 라 프로세스 종료 시 자동 정리.
3. **스레드풀 (FastAPI 내부)** — 동기 `def` 라우트가 자동으로 여기서 실행됨.

**왜 이렇게 섞여 있나?** OpenCV `cap.read()` 가 C 레벨 블로킹이라 async 만으로 못 감싼다. `asyncio.to_thread` 로 매 프레임 감싸는 것도 가능하지만, 캡처는 "계속 도는 루프" 라 전용 스레드가 훨씬 단순. 반면 HTTP 핸들러는 요청당 실행이라 스레드풀로 충분.

---

## 6. 저장소 레이아웃

```
storage/                              (.gitignore — 영상/썸네일/큐 전부 커밋 금지)
├── clips/
│   └── 2026-04-22/
│       ├── {camera_uuid_1}/
│       │   ├── 121015_motion.mp4     (60초 CFR-보정)
│       │   ├── 121015_motion.jpg     (대표 프레임, Stage D4)
│       │   ├── 121115_idle.mp4
│       │   └── 121115_idle.jpg
│       └── {camera_uuid_2}/ ...
├── pending_inserts.jsonl             (Supabase INSERT 실패 큐, max 1000 lines)
└── test_snapshot.jpg                 (scripts/test_rtsp.py 결과)
```

**파일 경로 규칙**
- 날짜 폴더: 로컬 시간 (UTC 아님) — 사용자가 "어제 영상" 을 쉽게 찾게.
- 카메라 폴더명: DB `cameras.id` UUID — `display_name` 은 바뀔 수 있지만 UUID 는 불변.
- mp4 basename: `HHMMSS` — 정렬 용이. 태그 (`_motion`/`_idle`) 는 세그먼트 종료 시점에 결정.
- 썸네일 jpg: mp4 와 동일 basename + `.jpg`.

---

## 7. 외부 의존성 지도

| 의존성 | 버전 (pyproject) | 이유 / 대안 검토 |
|--------|------------------|-------------------|
| `fastapi>=0.136` | 웹 프레임워크 | 타입 힌트 DX, TS 유사. Flask/Starlette 대비 OpenAPI 자동 생성 + Depends |
| `uvicorn>=0.44` | ASGI 서버 | FastAPI 표준 짝 |
| `opencv-python>=4.13` | RTSP + 움직임 감지 + 인코딩 | FFmpeg 직접 호출 대비 OpenCV 가 파이프라인 통합 쉬움 |
| `supabase>=2.28` | Postgres + Auth BaaS | self-hosted Postgres 대비 JWT/RLS 기성, migration dashboard |
| `pyjwt[crypto]>=2.12` | Supabase JWT 검증 (ES256) | jwcrypto 대비 API 단순 |
| `cryptography` (pyjwt 경유) | Fernet 카메라 비번 암호화 | 표준 라이브러리, Fernet = AES-128-CBC + HMAC 레시피 |
| `python-dotenv>=1.2` | `.env` 로드 | pydantic-settings 대비 학습 부담 낮음 (Stage 초기 의도) |

**런타임만 있고 빌드 타임 도구는 `uv` — 자세한 건 [CONTRIBUTING.md](CONTRIBUTING.md).**

---

## 8. 핵심 설계 결정 요약

| 결정 | 이유 | 스펙 |
|------|------|------|
| 캡처 = 전용 스레드, API = 이벤트 루프 | OpenCV 블로킹과 asyncio 격리 | [stage-a-streaming](../specs/stage-a-streaming.md) |
| CFR 보정 (패딩/드롭) | RTSP jitter 로 재생 시간 어긋남 방지 | [stage-b-motion-detect](../specs/stage-b-motion-detect.md) |
| `avc1` 코덱 기본 + 폴백 체인 | mp4v 대비 용량 ~70% 절감 | 동상 |
| pending_inserts.jsonl 파일 큐 | Redis 없이 재시도, 프로세스 재시작 생존 | [stage-c-db-api](../specs/stage-c-db-api.md) |
| service_role + RLS INSERT 정책 부재 | test-connection·암호화 우회 차단 | [stage-d2-cameras-api](../specs/stage-d2-cameras-api.md) |
| Fernet 양방향 암호화 (비번) | RTSP 접속 시 평문 필요 → 일방향 해시 불가 | [stage-d1-auth-crypto](../specs/stage-d1-auth-crypto.md) |
| 다중 워커 = `app.state.capture_workers: dict` | `Depends` 는 요청 스코프라 부적합 | [stage-d3-multi-capture](../specs/stage-d3-multi-capture.md) |
| 썸네일 = mp4 동일 basename + `.jpg` | 파일 시스템 경로 추론 가능, DB 조인 불필요 | [stage-d4-thumbnail](../specs/stage-d4-thumbnail.md) |
| `AUTH_MODE=dev/prod` 한 스위치 | 로컬 개발 / 외부 배포 모두 같은 코드 | [stage-d1-auth-crypto](../specs/stage-d1-auth-crypto.md) |
| Cloudflare Named Tunnel | 공유기 포트포워딩 불필요 + HTTPS 자동 | [stage-d5-deploy-tunnel](../specs/stage-d5-deploy-tunnel.md) |
| `clip_mirrors` 별도 테이블 (QA 용) | 정식 공유 기능 오해 방지, DROP 한 번이면 제거 | [feature-clip-mirrors-for-qa](../specs/feature-clip-mirrors-for-qa.md) |

---

## 9. 다음 읽을 문서

- **기능 관점** → [FEATURES.md](FEATURES.md)
- **API 호출** → [API.md](API.md)
- **DB 스키마** → [DATABASE.md](DATABASE.md)
- **환경변수** → [ENV.md](ENV.md)
- **배포/운영** → [DEPLOYMENT.md](DEPLOYMENT.md)
- **코드 기여** → [CONTRIBUTING.md](CONTRIBUTING.md)
- **용어 모를 때** → [GLOSSARY.md](GLOSSARY.md)
- **AI 에이전트** → [../AGENTS.md](../AGENTS.md)
