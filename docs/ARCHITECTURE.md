# ARCHITECTURE — petcam-lab

> 이 레포의 백엔드가 외부 시스템과 어떻게 맞물리고, 내부 모듈이 어떻게 구성됐는지. 코드 읽기 전에 이거부터.

---

## 1. 한 줄 요약

**TP-Link Tapo C200 (또는 스마트폰 IP캠) 이 RTSP 로 영상을 쏘면, 이 Python FastAPI 백엔드가 받아서 1분 단위 mp4 로 잘라 저장하고, 움직임 감지 태깅 + 썸네일 생성 후 Supabase 에 메타데이터를 기록한다. Flutter 앱이 Supabase JWT 로 인증하고 `api.tera-ai.uk` (Cloudflare Tunnel) 를 통해 클립을 목록 조회·재생한다.**

---

## 2. 시스템 맵

```
┌──────────────┐        RTSP(554)        ┌─────────────────────────────────────┐
│  Tapo C200   │ ──────────────────────► │ 프로세스 #2 — backend.capture_main  │
│  (또는 IP캠) │                         │ (asyncio standalone, 맥북/HW 로컬)   │
└──────────────┘                         │                                       │
       ▲                                 │  ┌──────────────────────────────┐    │
       │  등록/삭제는 API로              │  │ CaptureWorker × N (스레드)    │    │
       │                                 │  │   RTSP → mp4 (60s 세그먼트)   │    │
                                         │  └────────┬─────────────────────┘    │
┌──────────────┐                         │           ▼                           │
│ Flutter app  │                         │  ┌──────────────────────────────┐    │
│ (LTE/Wi-Fi)  │                         │  │ EncodeUploadWorker (asyncio) │    │
└──────┬───────┘                         │  │   FFmpeg → mp4 + thumb       │    │
       │                                 │  │   boto3 PUT → R2             │    │
       │ Supabase JWT                    │  │   Supabase camera_clips INSERT│   │
       │ HTTPS (api.tera-ai.uk)          │  └──────────────────────────────┘    │
       ▼                                 └─────────────────────────────────────┘
┌──────────────────┐                                       │
│ Cloudflare       │                                       │ service_role
│ Tunnel (Named)   │                                       ▼
└────────┬─────────┘                     ┌─────────────────────────────────┐
         │ 127.0.0.1:8000                │           Supabase              │
         ▼                               │  ┌──────────────────────────┐  │
┌─────────────────────────────────────┐  │  │ auth.users (JWT issuer)  │  │
│ 프로세스 #1 — backend.main:app       │  │  │ cameras / camera_clips   │  │
│ (uvicorn FastAPI, 127.0.0.1)         │  │  │ labels / labelers        │  │
│  ┌────────────────────────────────┐  │  │  │ pets / clip_mirrors      │  │
│  │ routers: /clips /cameras /labels│ │  │  └──────────────────────────┘  │
│  │ /health                         │ │  │                                  │
│  └─────────┬──────────────────────┘ │  └─────────────────────────────────┘
└────────────┼─────────────────────────┘                  ▲
             │ R2 signed URL 발급                         │
             ▼                                            │
       ┌─────────────────┐                                │
       │ Cloudflare R2   │ ◄── PUT (mp4/jpg) ─────────────┘
       │ (mp4/jpg)       │      (프로세스 #2 가 직접 업로드)
       └────────┬────────┘
                │ GET (mp4 bytes)
                ▼
┌─────────────────────────────────────┐
│ 프로세스 #3 — backend.vlm_worker_main│
│ (asyncio standalone, 어디서나 가동) │
│  ┌────────────────────────────────┐ │
│  │ camera_clips polling (30s)      │ │       service_role
│  │   has_motion=true               │ │      INSERT behavior_logs
│  │   r2_key NOT NULL               │ │ ────────────────────────►
│  │   NOT EXISTS(behavior_logs vlm) │ │       (action / confidence /
│  └────────┬───────────────────────┘ │        reasoning, source='vlm')
│           ▼                         │
│  ┌────────────────────────────────┐ │
│  │ Gemini 2.5 Flash 호출           │ │
│  │   v3.5 prompt (락인)            │ │
│  │   temperature=0.1 + JSON schema │ │
│  └────────────────────────────────┘ │
└─────────────────────────────────────┘

                    storage/
                     └─ clips/{YYYY-MM-DD}/{camera_uuid}/
                         ├─ 163423_motion.mp4   (원본, R2 업로드 후 보존)
                         ├─ 163423_motion.jpg   (대표 프레임 썸네일)
                         └─ pending_inserts.jsonl  (DB INSERT 재시도 큐)
```

**프로세스 분리 (cloud-migration 2026-05-07)**
- **프로세스 #1 = `backend.main:app` (uvicorn)** — HTTP API only. cloud 배포 가능 (Cloudflare Tunnel 너머). 캡처 워커 / VLM 워커 in-memory 상태는 모름. 현재: 맥북 + Cloudflare Tunnel `api.tera-ai.uk`.
- **프로세스 #2 = `backend.capture_main` (asyncio)** — RTSP 캡처 + 인코딩 + R2 업로드 + Supabase INSERT. RTSP 가 LAN 의존이라 카메라와 같은 네트워크 (지금: 맥북 / 추후: 자체 HW) 에 가동.
- **프로세스 #3 = `backend.vlm_worker_main` (asyncio)** — 미라벨 클립 폴링 → Gemini 2.5 Flash → behavior_logs INSERT. RTSP 무관 → 클라우드 머신에 배포 가능. UNIQUE(clip_id, source) 가 동시 워커 race 방어. **현재: fly.io `petcam-vlm-worker` (nrt, shared-cpu-1x 256MB, always-on)** — 2026-05-07 배포.
- **외부 #4 = 라벨링 웹 (`label.tera-ai.uk`, Vercel Next.js)** — `web/` 디렉토리. owner 검수 흐름 (영상 재생/라벨/추론/메타) 은 Vercel API route 가 **Supabase + R2 직결** 로 처리 → 프로세스 #1 (API 서버) 의존 없음. 라벨러 큐 (`/labeling`, `/labeling/me`) 만 여전히 `BACKEND_URL` 경유 (owner PoC 범위 밖). 2026-05-07 배포.
- 세 프로세스 + 라벨링 웹이 공유: `.env` 또는 fly secrets / Vercel env (Supabase / R2 / Fernet / DEV_USER_ID / GEMINI_API_KEY), DB 스키마, R2 버킷, contract = `clip_recorder` payload, prompts SOT (`web/prompts/backups/`).
- 결정 락인: [`specs/cloud-migration-roadmap.md`](../specs/cloud-migration-roadmap.md) §4-3 + [`specs/feature-capture-worker-extraction.md`](../specs/feature-capture-worker-extraction.md) + [`specs/feature-vlm-worker-cloud.md`](../specs/feature-vlm-worker-cloud.md) + [`specs/feature-vlm-worker-fly-deploy.md`](../specs/feature-vlm-worker-fly-deploy.md) + [`specs/feature-labeling-web-cloud.md`](../specs/feature-labeling-web-cloud.md).

**역할 분담**
| 컴포넌트 | 책임 | 이 레포 관리? |
|----------|------|--------------|
| Tapo C200 / IP캠 | RTSP 영상 송출 | X (외부 하드웨어) |
| Cloudflare Tunnel | 공개 도메인 + HTTPS + outbound 터널 | X (cloudflared CLI) |
| **petcam-lab #1 (API)** | HTTP API + JWT + R2 signed URL | **이 레포** |
| **petcam-lab #2 (capture_main)** | 캡처·인코딩·R2 업로드·DB INSERT | **이 레포** |
| **petcam-lab #3 (vlm_worker_main)** | 미라벨 클립 자동 라벨링 (Gemini) | **이 레포** |
| Supabase | Auth + Postgres + RLS | X (BaaS, 대시보드 관리) |
| Cloudflare R2 | mp4/jpg 객체 저장 | X (R2 버킷) |
| Flutter 앱 | 사용자 UI | `tera-ai-flutter` 레포 |
| 기획 SOT | "무엇/왜" | `tera-ai-product-master` 레포 |

---

## 3. backend/ 내부 구조

```
backend/
├── main.py                  프로세스 #1 — FastAPI app + /health, CORS, routers 만
├── capture_main.py          프로세스 #2 — asyncio entrypoint (캡처+인코딩+R2 업로드)
├── vlm_worker_main.py       프로세스 #3 — asyncio entrypoint (Gemini 자동 라벨링)
├── routers/
│   ├── clips.py             GET /clips (목록/단건/파일/썸네일)
│   ├── cameras.py           POST·GET·PATCH·DELETE /cameras
│   └── labels.py            라벨링 관련 엔드포인트 (Stage R2)
├── vlm/
│   ├── prompts.py           v3.5 prompt 로드 + species 매핑 (web/prompts/backups read)
│   ├── gemini_client.py     Gemini SDK 래퍼 (temperature=0.1 + JSON schema)
│   └── worker.py            폴링 + idempotent INSERT + 일시/영구 에러 분기
├── capture.py               CaptureWorker 스레드 (RTSP → mp4 + motion 태그 + CFR 보정)
├── motion.py                MotionDetector (cv2.absdiff 프레임 차분)
├── clip_recorder.py         camera_clips INSERT 오케스트레이션 — contract 경계
├── encode_upload_worker.py  asyncio worker pool (FFmpeg 인코딩 + R2 업로드 + 썸네일)
├── encoding.py              FFmpeg subprocess wrapper
├── r2_uploader.py           boto3 R2 client + signed URL 발급
├── pending_inserts.py       JSONL 재시도 큐 (Supabase 장애 복구)
├── rtsp_probe.py            RTSP 테스트 연결 + URL 빌더 + 비번 마스킹
├── auth.py                  Supabase JWT 검증 + get_current_user_id Depends
├── crypto.py                Fernet 카메라 비번 암복호화
└── supabase_client.py       Supabase service_role 싱글톤
```

**의존성 방향** (화살표 = "import 함")

```
main.py (프로세스 #1)
  ├─► routers/clips.py ────► r2_uploader.py
  ├─► routers/cameras.py ──► rtsp_probe.py + crypto.py
  ├─► routers/labels.py
  └─► supabase_client.py
                              └──► auth.py (Depends 체인)

capture_main.py (프로세스 #2)
  ├─► capture.py ──► motion.py
  ├─► encode_upload_worker.py ──► encoding.py + r2_uploader.py
  ├─► clip_recorder.py ──► pending_inserts.py     ← contract 경계 (자체 HW 등장 시 보존)
  ├─► crypto.py + rtsp_probe.py
  └─► supabase_client.py

vlm_worker_main.py (프로세스 #3)
  └─► vlm/worker.py
        ├─► vlm/gemini_client.py ──► google-generativeai + r2_uploader.py
        ├─► vlm/prompts.py        ──► web/prompts/backups/*.v3.5.md  ← 라벨링 웹과 SOT 공유
        └─► supabase_client.py
```

순환 의존 없음. 하위 모듈은 상위를 import 하지 않음. **두 entrypoint (`main.py` /
`capture_main.py`) 가 같은 하위 모듈을 공유하되 책임이 분리됨** — `main.py` 는
HTTP/JWT/Read 만, `capture_main.py` 는 RTSP/Encode/Write 만.

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

cloud-migration 분리 후 동시성은 **세 OS 프로세스 + 그 안의 여러 동시성 축** 으로
계층화된다.

### 프로세스 #1 — `backend.main:app` (uvicorn FastAPI)

```
┌─────────────────────────────────────────────────────────────────────┐
│ FastAPI 이벤트 루프 (메인 스레드, asyncio)                           │
│                                                                      │
│   ┌─ lifespan() ────────────────────────────────────────────────┐  │
│   │  startup: Supabase 검증 → startup_error 기록 (워커 부트X)   │  │
│   │  yield (앱 동작 중)                                          │  │
│   │  shutdown: (할 일 없음 — 워커 없으니)                       │  │
│   └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│   ┌─ HTTP 요청 핸들러 (동기 def) ───────────────────────────────┐  │
│   │  /clips, /cameras, /labels — Supabase 동기 클라이언트이라  │  │
│   │   def 라우트. FastAPI 가 threadpool 로 실행 → 루프 안 막힘. │  │
│   └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 프로세스 #2 — `backend.capture_main` (asyncio standalone)

```
┌─────────────────────────────────────────────────────────────────────┐
│ asyncio 루프 (메인 스레드)                                            │
│                                                                      │
│   ┌─ bootstrap() ───────────────────────────────────────────────┐  │
│   │  cameras SELECT → EncodeUploadWorker.start()                │  │
│   │  → CaptureWorker × N .start()                                │  │
│   │  → _periodic_flush asyncio.Task                              │  │
│   └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│   ┌─ EncodeUploadWorker (asyncio.Task × concurrency) ───────────┐  │
│   │  큐에서 (mp4_path, base_meta) 꺼냄 → FFmpeg subprocess →    │  │
│   │   R2 PUT (boto3, asyncio.to_thread) → clip_recorder() 호출. │  │
│   └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│   await stop_event.wait()  ← SIGTERM/SIGINT graceful shutdown      │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                │ runtime.capture_workers: dict[uuid, CaptureWorker]
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│ CaptureWorker 스레드 × N (카메라 1대당 1개, daemon=True)             │
│                                                                      │
│   while not stop_event.is_set():                                    │
│     cv2.VideoCapture.read()   ← 블로킹 I/O (C 레벨)                │
│     MotionDetector.update()                                         │
│     cv2.VideoWriter.write()                                         │
│     (세그먼트 경계) → enqueue_callback(mp4, base_meta)             │
│                                                                      │
│   ▲ 상태 공유는 threading.Lock 으로 보호된 CaptureState             │
└─────────────────────────────────────────────────────────────────────┘
```

### 프로세스 #3 — `backend.vlm_worker_main` (asyncio standalone)

```
┌─────────────────────────────────────────────────────────────────────┐
│ asyncio 루프 (메인 스레드)                                            │
│                                                                      │
│   ┌─ bootstrap() ───────────────────────────────────────────────┐  │
│   │  Supabase + Gemini (env / API key) 검증 → VlmWorker 생성    │  │
│   └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│   ┌─ VlmWorker.run(stop_event) — 무한 루프 ────────────────────┐  │
│   │  while not stop_event.is_set():                             │  │
│   │    poll_clips()       ← Supabase SELECT (NOT EXISTS 필터)   │  │
│   │    for clip in clips:                                       │  │
│   │      download_clip_bytes  ← R2 GET (asyncio.to_thread)      │  │
│   │      classify_clip        ← Gemini 동기 (asyncio.to_thread) │  │
│   │      INSERT behavior_logs (idempotent UNIQUE)               │  │
│   │    await asyncio.wait_for(stop_event.wait, 30s)             │  │
│   └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│   await stop_event.wait()  ← SIGTERM/SIGINT graceful shutdown      │
└─────────────────────────────────────────────────────────────────────┘
```

**Gemini SDK / boto3 / supabase-py 모두 동기 라이브러리** → `asyncio.to_thread` 로 감싸 이벤트 루프 안 막음. donts/python.md 룰 4 동치.

**직렬 처리 (Gemini 호출당 1건)** — Flash free tier 15 RPM 제한 + 동시 N 호출 시 429 폭주 가능. 처리량은 polling cadence (30s) + LIMIT (10) 으로 평탄화.

**세 줄 요약**
1. **세 프로세스** — API 서버 (cloud 가능) / 캡처 워커 (LAN 의존) / VLM 워커 (어디서나). 같은 코드베이스 세 entrypoint.
2. **캡처 스레드 (N개, 프로세스 #2)** — OpenCV 블로킹 I/O 를 asyncio 루프와 격리. enqueue 만 하고 즉시 다음 프레임.
3. **EncodeUploadWorker (asyncio, 프로세스 #2) + VlmWorker (asyncio, 프로세스 #3)** — 둘 다 동기 SDK 를 `asyncio.to_thread` 로 감싸 루프 안 막음. 인코딩은 세그먼트 단위, VLM 은 클립 단위.

**왜 이렇게 섞여 있나?** OpenCV `cap.read()` 가 C 레벨 블로킹이라 async 만으로 못 감싼다. `asyncio.to_thread` 로 매 프레임 감싸는 것도 가능하지만, 캡처는 "계속 도는 루프" 라 전용 스레드가 훨씬 단순. 인코딩+R2 업로드는 프레임 단위가 아닌 세그먼트 단위라 asyncio worker pool 로 충분.

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
| `boto3>=1.43` | R2 S3-compat 업로드/download | aiobotocore 대비 자료 풍부, asyncio.to_thread 로 비동기화 |
| `google-generativeai>=0.8` | Gemini 2.5 Flash 클라이언트 (VLM 워커) | deprecated SDK 이지만 PoC 와 동치 보장. `google-genai` 마이그레이션 후속 |

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
| 다중 워커 = `runtime.capture_workers: dict` | `Depends` 는 요청 스코프라 부적합 | [stage-d3-multi-capture](../specs/stage-d3-multi-capture.md) |
| 썸네일 = mp4 동일 basename + `.jpg` | 파일 시스템 경로 추론 가능, DB 조인 불필요 | [stage-d4-thumbnail](../specs/stage-d4-thumbnail.md) |
| `AUTH_MODE=dev/prod` 한 스위치 | 로컬 개발 / 외부 배포 모두 같은 코드 | [stage-d1-auth-crypto](../specs/stage-d1-auth-crypto.md) |
| Cloudflare Named Tunnel | 공유기 포트포워딩 불필요 + HTTPS 자동 | [stage-d5-deploy-tunnel](../specs/stage-d5-deploy-tunnel.md) |
| `clip_mirrors` 별도 테이블 (QA 용) | 정식 공유 기능 오해 방지, DROP 한 번이면 제거 | [feature-clip-mirrors-for-qa](../specs/feature-clip-mirrors-for-qa.md) |
| **API ↔ 캡처 두 프로세스 분리 (한 코드베이스)** | RTSP LAN 의존이라 API 만 cloud 로 빼려면 entrypoint 가 둘이어야 함. 자체 HW 등장 시 capture/encode 만 교체될 contract 경계 (`clip_recorder`) 확정. | [feature-capture-worker-extraction](../specs/feature-capture-worker-extraction.md) |
| **VLM 자동 라벨링 워커 분리 (프로세스 #3)** | RTSP 무관하므로 클라우드 머신에 가동 가능. DB-as-message-bus (NOT EXISTS 폴링 + UNIQUE) 으로 동시 워커 race 방어 — Redis/SQS 같은 별도 큐 인프라 안 도입. | [feature-vlm-worker-cloud](../specs/feature-vlm-worker-cloud.md) |
| **라벨링 웹 owner 흐름 = Vercel→Supabase/R2 직결** | API 서버 (맥북) 의존 끊기. Next.js API route 가 Bearer JWT verify → service_role 로 DB/R2 접근. 권한 모델 (`owner OR labeler OR 404`) 은 백엔드 `clip_perms.py` 와 동치. 라벨러 흐름은 BACKEND_URL 유지 (별도 spec) | [feature-labeling-web-cloud](../specs/feature-labeling-web-cloud.md) |

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
