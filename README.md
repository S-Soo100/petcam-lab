# petcam-lab

> 도마뱀 특화 펫캠 (게코 캠) 영상 백엔드. 학습 겸 실 프로덕트.

**한 줄**: Tapo C200 RTSP → 1분 mp4 + 움직임 태깅 → Cloudflare R2 + Supabase 메타. Flutter 앱·라벨링 웹이 R2 signed URL 로 영상 직결, VLM 워커가 자동 라벨링.

**아키텍처 4-component** (2026-05-08 기준):
1. **API 서버** (`backend.main:app`) — fly.io `petcam-api` always-on, `https://api.tera-ai.uk`
2. **캡처 워커** (`backend.capture_main`) — LAN/자체 HW 호스팅 (RTSP 평문 비번 + 사설 IP 의존)
3. **VLM 워커** (`backend.vlm_worker_main`) — fly.io `petcam-vlm-worker` always-on
4. **라벨링 웹** — Vercel `label.tera-ai.uk`

같은 코드베이스 (`backend/`), 3 entrypoint. 도메인 로직 공유 + 프로세스만 분리. 상세: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## 빠른 시작

### 1. 셋업 (최초 1회)

```bash
brew install uv
cd /Users/baek/petcam-lab
uv sync

cp .env.example .env
# → .env 열어서 Supabase 키 / DEV_USER_ID / CAMERA_SECRET_KEY 채우기
# CAMERA_SECRET_KEY 생성:
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

환경변수 전체: [`docs/ENV.md`](docs/ENV.md)

### 2. 로컬 실행

```bash
# RTSP 스모크 테스트 (카메라 연결 확인)
uv run python scripts/test_rtsp.py

# API 서버 (조회·라벨·CRUD)
uv run uvicorn backend.main:app --reload

# 캡처 워커 (RTSP → mp4 → R2 PUT, 별도 터미널)
uv run python -m backend.capture_main

# VLM 워커 (자동 라벨링, 선택)
uv run python -m backend.vlm_worker_main

# Swagger UI
open http://localhost:8000/docs
```

카메라 등록: `POST /cameras` — 상세는 [`docs/API.md`](docs/API.md).

### 3. 외부 공개 (배포)

```bash
# fly.io 배포 (코드 푸시 후)
fly deploy --app petcam-api

# 헬스체크
curl https://api.tera-ai.uk/health
# → {"status":"ok","startup_error":null}
```

API 서버는 fly.io always-on (`petcam-api`, Tokyo `nrt`, 256MB). VLM 워커는 별도 app (`petcam-vlm-worker`). 캡처 워커는 LAN/자체 HW. 상세: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

### 4. 테스트

```bash
uv run pytest -xv
```

247 tests collected (Stage A ~ D5 + 클라우드 마이그레이션 + QA 미러).

---

## 기술 스택

| 분류 | 선택 | 이유 |
|------|------|------|
| 언어 | Python 3.12 | OpenCV/영상 생태계 성숙 + 학습 목표 |
| 패키지 매니저 | `uv` | Rust 기반 빠른 설치, 단일 `pyproject.toml` |
| 웹 프레임워크 | FastAPI | 타입 힌트 DX, TS 와 유사 |
| 영상 I/O | OpenCV + FFmpeg | RTSP + 움직임 감지 + avc1 인코딩 |
| BaaS | Supabase | Auth (ES256 JWT) + Postgres + service_role |
| 외부 스토리지 | Cloudflare R2 (S3 호환) | egress 무료, signed URL 1h TTL |
| API 서버 배포 | fly.io always-on | 256MB nrt, DNS A/AAAA 직결 |
| VLM | Gemini 2.0 Flash | 9 ActionType, temperature=0.1 |
| 라벨링 웹 | Next.js (Vercel) | App Router, server-side route 가 R2/Supabase 직결 |

상세: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §7~§8.

---

## 로드맵

| Stage | 내용 | 상태 |
|-------|------|------|
| **A** | RTSP 스트리밍 + 서버 파일 저장 MVP | ✅ 완료 |
| **B** | OpenCV 움직임 감지 + 클립 분리 (CFR 보정) | ✅ 완료 |
| **C** | 메타데이터 DB + 클립 조회 API (`/clips`) | ✅ 완료 |
| **D1** | Supabase JWT 검증 + Fernet 비번 암호화 | ✅ 완료 |
| **D2** | `/cameras` CRUD + RTSP 자동 probe | ✅ 완료 |
| **D3** | 다중 캡처 워커 + `camera_id` UUID FK | ✅ 완료 |
| **D4** | 클립 썸네일 생성 + 조회 | ✅ 완료 |
| **D5** | 외부 공개 (Cloudflare Tunnel → fly.io always-on, AUTH_MODE=prod) | ✅ 완료 (2026-05-08 fly.io cutover) |
| **클라우드 마이그레이션** | R2 외부 스토리지 + VLM 자동 라벨링 + 라벨링 웹 + 4-component 분리 | ✅ 완료 |
| **E** | 온디바이스 필터링 (ESP32-CAM / 자체 HW) | 🆕 스코프 미확정 |

Stage 별 스펙: [`specs/README.md`](specs/README.md). 클라우드 마이그레이션 결정 락인: [`specs/cloud-migration-roadmap.md`](specs/cloud-migration-roadmap.md).

---

## 카메라 소스

- **실제 기기**: TP-Link Tapo C200 × 2대
  - RTSP: `rtsp://<user>:<pass>@<IP>:554/stream1` (1080p) 또는 `stream2` (720p, 권장)
  - 설정: Tapo 앱 → Advanced → Camera Account 활성화
  - **macOS Local Network Permission** 필수: 시스템 설정 → 개인정보 보호 → 로컬 네트워크 → VSCode/Terminal 토글 ON
- **대체 소스**: 스마트폰 IP 캠 앱 (Android: `IP Webcam`, iOS: `iVCam` / `EpocCam`)
- **중기**: 자체 HW (카메라+캡처 통합) → 클라우드 직접 push (RTSP 단계 폐기 가능)

---

## 문서 지도

**독자별 진입점**
| 너는 누구? | 먼저 읽어 |
|-----------|-----------|
| 새로 온 개발자 | 이 README + [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| AI 에이전트 | [`AGENTS.md`](AGENTS.md) (Claude는 [`CLAUDE.md`](CLAUDE.md)) |
| 기능 훑고 싶음 | [`docs/FEATURES.md`](docs/FEATURES.md) |
| API 호출할 거야 | [`docs/API.md`](docs/API.md) |
| DB 스키마 궁금 | [`docs/DATABASE.md`](docs/DATABASE.md) |
| 배포하려고 | [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) |
| 환경변수 뭔지 | [`docs/ENV.md`](docs/ENV.md) |
| 기여할래 | [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) |
| 용어 모르겠어 | [`docs/GLOSSARY.md`](docs/GLOSSARY.md) |
| Flutter 작업 | [`docs/handoff-prompts/flutter-cloud-migration.md`](docs/handoff-prompts/flutter-cloud-migration.md) |

**의사결정 이력 / 진행 상태**
- [`specs/README.md`](specs/README.md) — Stage 별 스펙 목록 + 체크리스트
- [`specs/cloud-migration-roadmap.md`](specs/cloud-migration-roadmap.md) — 클라우드 마이그레이션 결정 락인
- [`specs/next-session.md`](specs/next-session.md) — 다음 세션 시작 지점
- [`docs/learning/`](docs/learning/) — Stage 진행 당시 학습 노트 (과정 기록)

**상위 기획 (다른 레포)**
- [`../tera-ai-product-master/products/petcam/README.md`](../tera-ai-product-master/products/petcam/README.md) — 제품 포지션
- [`../tera-ai-product-master/docs/specs/petcam-b2c.md`](../tera-ai-product-master/docs/specs/petcam-b2c.md) — B2C 기능 스펙
- [`../tera-ai-product-master/docs/specs/petcam-backend-dev.md`](../tera-ai-product-master/docs/specs/petcam-backend-dev.md) — 백엔드 기획

---

## 폴더 구조

```
petcam-lab/
├── backend/          API 서버 + 캡처 워커 + VLM 워커 (3 entrypoint, 같은 코드베이스)
│   ├── main.py             API 서버 entry (FastAPI)
│   ├── capture_main.py     캡처 워커 entry (RTSP → mp4 + R2 PUT)
│   ├── vlm_worker_main.py  VLM 워커 entry (자동 라벨링)
│   ├── routers/            clips, cameras, labels, me
│   ├── capture.py          CaptureWorker, CFR 보정, 코덱 폴백
│   ├── motion.py           픽셀 차분 움직임 감지
│   ├── clip_recorder.py    Supabase INSERT + pending_inserts 큐
│   ├── encode_upload_worker.py  DB-as-message-bus (R2 PUT 큐)
│   ├── r2_uploader.py      Cloudflare R2 (boto3 S3 호환, signed URL 발급)
│   ├── auth.py             Supabase JWT (ES256, JWKS 10분 TTL)
│   ├── crypto.py           Fernet 비번 암호화
│   └── ...
├── web/              Next.js — /upload /queue /inference /results (Round 1) + /labeling (Round 4 GT)
├── scripts/          단발 실험 (test_rtsp, measure_fps)
├── storage/          로컬 캐시: clips/ (원본) + encoded/ (R2 업로드본). 정본은 R2.
├── tests/            pytest (247 tests)
├── specs/            Stage별 스펙 + 클라우드 마이그레이션 + 진행 상태
├── docs/             아키텍처/기능/API/DB/배포 공식 문서
│   ├── handoff-prompts/    옆 레포 (Flutter 등) 새 세션 진입용
│   └── learning/           Stage 진행 당시 학습 노트
├── .claude/          Claude Code 규칙 + donts + audit 로그
├── fly.toml          fly.io API 서버 머신 설정
├── Dockerfile        uv 기반 슬림 이미지
├── AGENTS.md         AI 에이전트 공용 진입점
├── CLAUDE.md         Claude 전용 페르소나 + 규칙
├── .env.example      환경변수 템플릿 (더미값)
├── pyproject.toml    uv 설정
└── README.md         이 파일
```

---

## 레포 성격

**학습 + 실 프로덕트 둘 다.** 사용자는 Node.js 가벼운 경험 + Python 웹크롤링 정도. FastAPI·OpenCV·비동기는 처음이지만 이 코드는 상용 백엔드의 시작점. 그래서:

- 새 개념/라이브러리 쓸 때 WHY 짧게 주석 — "그냥 이렇게 써" 금지.
- TS/Node 비유 활용 (예: `Depends()` ≈ NestJS DI, `StreamingResponse` ≈ Node `res.write`).
- 구조·네이밍·테스트·보안은 상용 수준.

상세 원칙: [`CLAUDE.md`](CLAUDE.md).

---

## 참고

- FastAPI: https://fastapi.tiangolo.com/
- OpenCV-Python: https://docs.opencv.org/
- Supabase: https://supabase.com/docs
- Cloudflare R2: https://developers.cloudflare.com/r2/
- fly.io: https://fly.io/docs/
