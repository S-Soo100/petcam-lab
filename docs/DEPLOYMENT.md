# 배포 가이드

> petcam-lab 의 세 프로세스 (API / 캡처 / VLM) 와 라벨링 웹을 어디에 어떻게 가동하나. **2026-05-08 부로 API 서버 + VLM 워커 + 라벨링 웹은 클라우드 always-on, 캡처 워커만 LAN 의존.**

## 목차

- [배포 아키텍처](#배포-아키텍처)
- [사전 준비](#사전-준비)
- [API 서버 fly.io 배포](#api-서버-flyio-배포)
- [평상시 실행 체크리스트](#평상시-실행-체크리스트)
- [AUTH_MODE prod 전환](#auth_mode-prod-전환)
- [운영 팁](#운영-팁)
- [트러블슈팅](#트러블슈팅)
- [롤백 / 긴급 대응](#롤백--긴급-대응)
- [Appendix — 구 Cloudflare Named Tunnel (history)](#appendix--구-cloudflare-named-tunnel-history)

---

## 배포 아키텍처

```
[Flutter 앱 (LTE)]            [라벨링 웹 (label.tera-ai.uk, Vercel)]
       │ HTTPS                            │ owner 흐름은 Vercel→Supabase/R2 직결
       ▼                                  ▼ 라벨러 큐만 BACKEND_URL 경유
[Cloudflare DNS (api.tera-ai.uk)]
       │ A 66.241.124.67 / AAAA 2a09:8280:1::112:a9b6:0
       │ DNS only (proxy off — Let's Encrypt HTTP-01 직접)
       ▼
[fly.io edge (nrt) → petcam-api 머신]              ← 프로세스 #1: HTTP API only
       │ TLS: Let's Encrypt
       │ uvicorn backend.main:app :8000 (컨테이너 내부)
       └── Supabase (camera_clips / cameras / labels / behavior_logs) + R2 signed URL

[backend.capture_main (asyncio standalone, 맥북/자체 HW 로컬)]   ← 프로세스 #2
       │ RTSP 가 LAN 의존이라 카메라와 같은 네트워크
       ├── CaptureWorker × N → Tapo C200 × 2 (RTSP)
       └── EncodeUploadWorker → R2 PUT + Supabase camera_clips INSERT

[fly.io petcam-vlm-worker 머신 (nrt, always-on)]   ← 프로세스 #3: VLM 자동 라벨링
       │ camera_clips 폴링 60s — has_motion + r2_key + NOT EXISTS
       ├── R2 GET (영상 bytes)
       ├── Gemini 2.5 Flash 호출 (v3.5 prompt 락인)
       └── behavior_logs INSERT (source='vlm', UNIQUE 제약 idempotent)
```

**핵심 설계 (cloud-migration 완료, 2026-05-08)**
- **세 프로세스 분리** — API 서버 / 캡처 워커 / VLM 워커. 같은 코드베이스 + 같은 `.env` (로컬) 또는 fly secrets. RTSP 가 LAN 의존이라 캡처만 LAN 에 남고, API + VLM 은 fly.io 로 이전 완료. 결정 락인: [`specs/cloud-migration-roadmap.md`](../specs/cloud-migration-roadmap.md) + [`specs/feature-api-server-fly-deploy.md`](../specs/feature-api-server-fly-deploy.md).
- **API 서버 `petcam-api`** — fly.io always-on (`min_machines_running = 1`), 1대 (`flyctl scale count 1`), `nrt` Tokyo, `shared-cpu-1x` 256MB. Dockerfile 은 `Dockerfile.api`, 설정은 `fly.api.toml`. 사용자 맥북 의존 0.
- **HTTPS 자동** — fly.io 가 Let's Encrypt 인증서 자동 발급/갱신. Cloudflare DNS 는 **DNS only (gray cloud)** 로 설정 — proxy on 으로 켜면 Let's Encrypt HTTP-01 챌린지 실패함.
- **인증은 JWT** — `AUTH_MODE=prod` 에서 Supabase 가 발급한 JWT 를 JWKS 로 검증. fly secrets 에 `SUPABASE_JWKS_URL` 박아둠.
- **세 컴포넌트 공유** — Supabase service_role / Fernet / R2 자격증명 / DEV_USER_ID / GEMINI_API_KEY (라벨링 웹은 anon + service_role 별도 — Vercel env). DB 스키마, R2 버킷 단일.
- **DB-as-message-bus (VLM)** — VLM 워커가 polling SELECT 으로 미라벨 클립 가져옴. 별도 큐 인프라 도입 안 함. UNIQUE(clip_id, source) 제약이 동시 워커 race 방어.

---

## 사전 준비

### 한 번만

1. **Cloudflare 계정** — `terraaidev@gmail.com` (도메인 + R2)
2. **도메인 등록** — `tera-ai.uk` (Cloudflare Registrar)
3. **fly.io 계정 + flyctl** — `brew install flyctl` → `flyctl auth login`
4. **Homebrew** — 맥북 OS 표준 (캡처 워커 로컬 가동용)

### 매번 (맥북 재부팅 후, 캡처 가동 시)

- Tapo 카메라 2대 켜기 + Wi-Fi 연결 확인 (Tapo 앱에서 녹색 표시)
- 맥북 잠자기 방지 확인 (아래 [운영 팁](#운영-팁))

> 캡처 워커가 자체 HW 로 이전된 뒤에는 맥북 가동 불필요.

---

## API 서버 fly.io 배포

`backend.main:app` 을 `petcam-api` 앱으로 fly.io always-on 가동. Dockerfile + fly.toml 동봉. 결정 근거: [`specs/feature-api-server-fly-deploy.md`](../specs/feature-api-server-fly-deploy.md).

### 최초 1회 셋업

```bash
# 1. 앱 생성 (fly.api.toml 의 app = 'petcam-api' 와 일치)
flyctl apps create petcam-api

# 2. secrets 등록 — `.env` 의 8개 키 (Supabase / R2 / Fernet) 일괄
bash scripts/fly-set-secrets-api.sh

# 3. 배포 (Dockerfile.api + fly.api.toml)
flyctl deploy --config fly.api.toml --app petcam-api

# 4. 머신 1대로 (fly.io 첫 배포 시 2대 띄울 수 있음)
flyctl scale count 1 -a petcam-api

# 5. 커스텀 도메인 인증서 발급
flyctl certs create api.tera-ai.uk -a petcam-api
# → A / AAAA 추천값 출력 (예: 66.241.124.67 / 2a09:8280:1::112:a9b6:0)

# 6. Cloudflare DNS Records 에 A + AAAA 추가 — 둘 다 DNS only (회색 구름)
#    proxy on 으로 켜면 Let's Encrypt HTTP-01 챌린지 실패. tera-ai.uk 라벨이 'Tunnel' 인 기존
#    레코드가 있다면 (구 Cloudflare Named Tunnel 잔재) 삭제 후 추가.

# 7. 인증서 발급 확인
flyctl certs check api.tera-ai.uk -a petcam-api   # Status = Issued

# 8. 외부 검증
curl https://api.tera-ai.uk/health
# → {"status":"ok","startup_error":null}
```

### 환경변수 / Secrets

`fly.api.toml` 의 `[env]` (코드 추적, 비밀 아님):
- `AUTH_MODE=prod`
- `LOG_LEVEL=INFO`
- `LABELING_WEB_ORIGINS=https://label.tera-ai.uk` (라벨러 큐 / `/labels/mine` CORS)

`flyctl secrets set` 으로 등록 (디스크에 안 남음, ramfs):
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWKS_URL`
- `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`
- `RTSP_CRED_FERNET_KEY` (카메라 비번 복호화 — `POST /cameras/{id}/test-connection` 에 필요)

### 운영 명령어

```bash
flyctl status -a petcam-api
flyctl machines list -a petcam-api
flyctl logs -a petcam-api
flyctl machines restart <machine-id> -a petcam-api
flyctl secrets list -a petcam-api
```

### 비용

- `shared-cpu-1x` 256MB always-on ≈ $1.94/월 (VLM 워커와 동급)
- 트래픽: Flutter 앱 + 라벨러 큐 정도면 outbound 무료 한도 안

---

## 평상시 실행 체크리스트

**클라우드 (always-on, 평상시 손 안 댐)**

```
[  ] 1. fly.io petcam-api 머신 1대 가동 (https://api.tera-ai.uk/health 200)
[  ] 2. fly.io petcam-vlm-worker 머신 1대 가동 (https://petcam-vlm-worker.fly.dev/health 200)
[  ] 3. Vercel label.tera-ai.uk 가동 (라벨링 웹)
```

**로컬 (캡처 가동할 때만)**

```
[  ] 4. Tapo 카메라 2대 켜져 있음 (녹색 LED)
[  ] 5. 맥북 잠자기 방지 (caffeinate -d &)
[  ] 6. 터미널 A — capture_main (캡처+인코딩+R2 업로드 워커) 기동
[  ] 7. (선택) 터미널 B — vlm_worker_main 로컬 검증용 (회귀/디버깅 한정)
[  ] 8. Flutter 앱에서 로그인 → 클립 피드 로드
```

> 캡처 워커가 떠 있어야 새 클립이 R2 + camera_clips 에 들어가고, 그래야 fly.io VLM 워커가
> 폴링해서 자동 라벨을 채움. 캡처가 멈춰도 기존 클립 조회/재생/라벨은 정상.
> ⚠️ 로컬 B 와 fly.io VLM 워커 동시 가동은 race 안전 (UNIQUE(clip_id, source) idempotency)
> 이지만 동일 클립 중복 inference 발생. 회귀 검증 끝나면 로컬 종료.

### 기동 순서 (로컬 캡처)

**터미널 A** — 캡처 워커 (standalone asyncio)

```bash
cd /Users/baek/petcam-lab
uv run python -m backend.capture_main
```

기동 로그에 다음이 보여야 정상.
```
AUTH_MODE=prod
capture worker started: camera=<uuid> (거실)
capture worker started: camera=<uuid> (작업실)
capture_main running: 2 worker(s), 0 skipped — Ctrl+C / SIGTERM 으로 정지
```

**터미널 B** (선택) — VLM 자동 라벨링 워커 로컬 검증

```bash
cd /Users/baek/petcam-lab
uv run python -m backend.vlm_worker_main
```

기동 로그에 다음이 보여야 정상.
```
AUTH_MODE=prod
vlm worker started — poll_interval=30s limit=10
```

**환경변수 (이 워커 전용)**
- `GEMINI_API_KEY` — [AI Studio](https://aistudio.google.com/app/apikey) 발급. 누락 시 `Gemini 미설정` 으로 부팅 실패.
- `VLM_POLL_INTERVAL_SEC` (선택, 기본 30) / `VLM_POLL_LIMIT` (선택, 기본 10).

**선행 마이그레이션** — Supabase SQL Editor 에서 [`migrations/2026-05-07_behavior_logs_unique_clip_source.sql`](../migrations/2026-05-07_behavior_logs_unique_clip_source.sql) 실행. UNIQUE(clip_id, source) 제약이 idempotency 보장.

**외부 검증**

```bash
curl https://api.tera-ai.uk/health
# → {"status": "ok", "startup_error": null}

curl https://api.tera-ai.uk/clips
# → {"detail": "Authorization 헤더가 없음."}  ← 401, prod 정상

curl https://petcam-vlm-worker.fly.dev/health
# → {"ok": true, "service": "vlm-worker"}
```

### 종료 순서 (로컬 캡처)

- **터미널 A** — Ctrl+C (capture stop 후 EncodeUploadWorker drain → 종료. SIGINT/SIGTERM 둘 다 graceful)
- **터미널 B** — Ctrl+C (VLM 워커는 진행 중 사이클 완료 후 정지. 다음 부팅 시 미라벨 클립부터 자동 재처리.)

> 클라우드 컴포넌트는 평상시 종료 안 함. 긴급 차단은 [롤백 / 긴급 대응](#롤백--긴급-대응) 참조.

---

## AUTH_MODE prod 전환

**fly.io API 서버** (`petcam-api`) — `fly.api.toml` 의 `[env]` 가 `AUTH_MODE=prod` 박혀있고 `SUPABASE_JWKS_URL` 은 fly secrets 로 등록됨.

```bash
flyctl secrets list -a petcam-api
# SUPABASE_JWKS_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY 등 확인
```

**로컬 캡처 워커** (`backend.capture_main`) — `.env` 에 동일하게.

```bash
AUTH_MODE=prod
SUPABASE_JWKS_URL=https://<project>.supabase.co/auth/v1/.well-known/jwks.json
```

서버 재시작 시 lifespan 로그에 `AUTH_MODE=prod` 가 warning 레벨로 찍힘 (실수로 dev 켜져 있을 때 즉시 발견).

### 검증 (curl)

```bash
# 헤더 없음 → 401
curl https://api.tera-ai.uk/clips
# {"detail": "Authorization 헤더가 없음."}

# 위조 토큰 → 401
curl -H "Authorization: Bearer invalid" https://api.tera-ai.uk/clips
# {"detail": "JWT 헤더 파싱 실패: Not enough segments"}

# 정상 토큰 → 200 (Flutter 앱 로그인 후 토큰 복사)
curl -H "Authorization: Bearer eyJhbGci..." https://api.tera-ai.uk/clips
# {"items": [...], ...}
```

### dev 로 되돌리는 법

로컬 개발·pytest 에서만 `dev` 로 돌려 둠. `.env` 에서 `AUTH_MODE=dev` 로 바꾸고 서버 재시작. **외부망 공개 상태에서는 절대 dev 로 켜지 말 것** — `DEV_USER_ID` 로 누구나 통과됨.

---

## R2 (Cloudflare R2) 영상 저장

영상 mp4·썸네일 jpg 를 외부 라벨러가 접근할 수 있게 R2 에 업로드. 백엔드는 시간 제한 signed URL 만 발급, 객체 자체는 R2 엣지가 서빙 (egress 무료).

### 최초 1회 셋업

1. **bucket 생성** — Cloudflare 대시보드 → R2 → Create bucket. 예: `petcam-clips-prod`. 위치는 `Automatic` 또는 가까운 region.
2. **API 토큰 발급** — R2 → Manage R2 API Tokens → Create API token.
   - Permissions: `Object Read & Write`
   - 적용 bucket: 위 bucket 만 선택 (다른 bucket 침범 차단)
   - 발급된 `Access Key ID` / `Secret Access Key` 1회만 표시 → `.env` 에 즉시 저장
3. **`.env` 채우기** — `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`. 상세는 [`docs/ENV.md` #R2](ENV.md#r2-cloudflare-r2-영상-저장).
4. **수동 검증** — `uv run python scripts/test_r2_upload.py` (스크립트 없으면 작은 mp4 로 boto3 라운드트립 1회).

### 동작 흐름

```
[캡처 워커]
    │ 60s 세그먼트 → (mp4, jpg, base_meta) enqueue
    ▼
[EncodeUploadWorker N개]
    │ FFmpeg CRF 26 인코딩 → mp4 + 썸네일 추출
    │ boto3 put_object → R2
    │ camera_clips INSERT (r2_key, thumbnail_r2_key 채움)
    ▼
[clips API]
    │ GET /clips/{id}/file → 302 redirect to signed URL (Flutter 앱 + 라벨러 큐)
    │ GET /clips/{id}/file/url → 미사용 (라벨링 웹은 Vercel 직결, 2026-05-07 이전)
```

### 라벨링 웹 (Vercel) — owner 흐름은 Vercel 직결, 라벨러 큐만 BACKEND_URL 의존

별도 호스팅 — `web/` Next.js 를 Vercel 에 배포. owner 검수 흐름의 4개 endpoint
(영상 URL / 라벨 / 추론 / 클립 메타) 는 **Vercel API route 가 Supabase + R2 직결**
로 처리 → API 서버 (`api.tera-ai.uk`) 의존 끊김. 결정 락인:
[`specs/feature-labeling-web-cloud.md`](../specs/feature-labeling-web-cloud.md).

| Endpoint | 호출처 | 처리 위치 |
|---|---|---|
| `GET /api/clips/[id]` | owner 단건 페이지 | Vercel → Supabase |
| `GET /api/clips/[id]/file/url` | owner+labeler 영상 재생 | Vercel → R2 signed URL |
| `GET /api/clips/[id]/labels` | owner+labeler 라벨 prefill / 검수 | Vercel → Supabase |
| `GET /api/clips/[id]/inference` | owner 검수 (VLM 추론 표시) | Vercel → Supabase |
| `GET /labels/queue` | 라벨러 큐 페이지 | API 서버 (BACKEND_URL) |
| `GET /labels/mine` | 내 라벨 회고 | API 서버 |
| `GET /clips/{id}/thumbnail/url` | (현재 라벨링 흐름 미사용) | API 서버 |
| `POST /clips/{id}/labels` | 라벨 저장 (owner는 `/api/label`) | API 서버 |

**owner PoC 흐름은 맥북 의존 0** — `api.tera-ai.uk` 가 530 (origin down) 이어도
영상 재생 / 라벨 / 추론 / 메타 4가지가 정상 작동. 라벨러 큐만 가동 시 macbook 켜기.

1. **CORS 허용** — API 서버용. `.env` 에 `LABELING_WEB_ORIGINS=https://label.tera-ai.uk`
   (라벨러 큐 / `/labels/mine` 호출에 필요).
2. **Vercel 환경변수** — `web/.env.example` 의 `NEXT_PUBLIC_*` 3개 + service-role 4개:
   - `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` (브라우저, RLS 가 책임)
   - `NEXT_PUBLIC_BACKEND_URL=https://api.tera-ai.uk` (라벨러 큐 / `/labels/mine` 용)
   - `SUPABASE_SERVICE_ROLE_KEY` (Vercel API route 전용, 클라이언트에 노출 X)
   - `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` (signed URL 발급)
3. **Cloudflare DNS** — `label.tera-ai.uk` CNAME → `cname.vercel-dns.com` 추가.
4. **라벨러 계정 부트스트랩** — Supabase Studio:

```sql
-- (a) auth.users 에 사용자 생성: Studio → Authentication → Add user (email + temp password)
-- (b) labelers 테이블에 등록 (멤버여야 다른 user 클립 라벨 가능)
INSERT INTO labelers (user_id, added_by, note)
VALUES ('<auth.users.id>', '<관리자 user_id>', 'Round 4 GT 라벨러');
```

라벨링 웹은 회원가입 폼 노출 안 함 — 위 SQL 수동 등록만으로 가입.

### 비용 모니터링

- 무료 티어: 10GB 저장, 1M Class A (PUT/LIST), 10M Class B (GET) /월
- 카메라 2대 × 60s 세그먼트 × 24h = 약 2880 PUT/일 = 월 86k → 무료 한도 ≪
- 라벨러 1명 × 클립당 평균 5 GET × 일 100건 = 500 GET/일 = 월 15k → 무료 한도 ≪
- 임계 알림: Class A 월 800k, Class B 월 8M 도달 시 — Cloudflare 대시보드 R2 → Analytics 에서 일별 모니터링

---

## VLM 워커 fly.io 배포 (클라우드, always-on)

VLM 자동 라벨링 워커는 **fly.io 컨테이너로 배포** 되어 있음 (앱: `petcam-vlm-worker`,
region: `nrt` Tokyo, VM: `shared-cpu-1x` 256MB, always-on). 로컬 맥북이 꺼져도
모션 클립이 들어오면 60초 안에 자동 라벨이 붙음. 결정 근거: [`specs/feature-vlm-worker-fly-deploy.md`](../specs/feature-vlm-worker-fly-deploy.md).

> **언제 로컬 (`터미널 D`) 가동하나?** 새 prompt 회귀 검증 / 평가셋 재인퍼런스 / 디버깅
> 시. 평상시 라벨링은 fly.io 가 담당. 두 워커 동시 가동도 안전 (UNIQUE 제약) 이지만
> 같은 클립을 중복 inference 하므로 검증 끝나면 로컬은 종료.

### 최초 1회 셋업

```bash
# 1. flyctl 설치 + 로그인
brew install flyctl
flyctl auth login

# 2. 앱 생성 (fly.toml 의 app = 'petcam-vlm-worker' 와 일치해야 함)
flyctl apps create petcam-vlm-worker

# 3. secrets 등록 — `.env` 의 7개 키를 fly 에 회전 가능한 secret 으로 박음.
#    스크립트가 .env 읽어서 일괄 set:
bash scripts/fly-set-secrets.sh

# 4. 배포 (Dockerfile + fly.toml 자동 감지)
flyctl deploy --app petcam-vlm-worker

# 5. 검증
flyctl status --app petcam-vlm-worker
curl https://petcam-vlm-worker.fly.dev/health
# → {"ok": true, "service": "vlm-worker"}
```

> ⚠️ fly.io 가 처음 deploy 시 `[http_service]` 정의를 보고 머신 2개 (regional
> redundancy) 띄울 수 있음. `flyctl scale count 1` 로 1대로 줄임. `min_machines_running = 1`
> 만으론 max 강제 안 됨.

### 환경변수 / Secrets

`fly.toml` 의 `[env]` (비밀 아님, 코드 추적):
- `HEALTH_PORT=8080` (컨테이너 안 health endpoint 포트)
- `VLM_POLL_INTERVAL_SEC=60` (프로덕션은 60s, 로컬 기본은 30s)
- `VLM_POLL_LIMIT=10`
- `AUTH_MODE=prod` (cosmetic — 워커는 안 쓰지만 부팅 로그 가독성용)

`fly secrets set` 으로 등록 (디스크에 안 남음, ramfs 만):
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`
- `GEMINI_API_KEY`

회전: `flyctl secrets set GEMINI_API_KEY=newkey --app petcam-vlm-worker` →
머신 자동 재시작.

### 운영 명령어

```bash
# 상태
flyctl status --app petcam-vlm-worker
flyctl machines list --app petcam-vlm-worker

# 로그 (실시간 tail)
flyctl logs --app petcam-vlm-worker

# 머신 재시작 (secret 변경 후 / 디버깅)
flyctl machines restart <machine-id> --app petcam-vlm-worker

# 머신 N대로 스케일 (UNIQUE 제약 덕에 동시 워커 race 안전)
flyctl scale count 2 --app petcam-vlm-worker

# 메트릭 (메모리 / CPU)
flyctl metrics --app petcam-vlm-worker
```

### 트러블슈팅

**`PromptNotFound: v3.5 system_base 파일 없음`**
- 원인: `.dockerignore` 에서 `web/` 통째 제외 시 `web/prompts/backups/system_base.v3.5.md` 누락 (2026-05-07 사고).
- 확인: `docker run --rm -it petcam-vlm-worker ls -la /app/web/prompts/backups/`
- fix: `.dockerignore` 가 `web/*` + `!web/prompts/` (negation) 이고, `Dockerfile` 이
  builder + runtime stage 둘 다 `COPY web/prompts/ ./web/prompts/` 하는지 확인.
  prompts SOT 가 web/ 안에 있어 라벨링 웹과 공유 — 이동 검토는 별도 spec 후속.

**`Gemini 미설정` 부팅 실패**
- `flyctl secrets list --app petcam-vlm-worker` — `GEMINI_API_KEY` 항목 없으면 누락.
- `flyctl secrets set GEMINI_API_KEY=...` 후 머신 자동 재시작.

**`/health` 200 인데 `polled=0` 만 반복**
- 미라벨 클립이 정말 없을 수 있음 — 회귀 검증용으로 1건 강제하려면:
  ```sql
  DELETE FROM behavior_logs
   WHERE clip_id = '<특정 clip_id>' AND source IN ('vlm', 'vlm_failed');
  ```
  → 다음 폴링 사이클에서 RPC `fn_vlm_pending_clips` 가 잡아감.

**OOM (256MB 부족)**
- `flyctl scale memory 512 --app petcam-vlm-worker` (월 비용 약 2배). 첫 배포 후
  `flyctl metrics` 로 실 사용량 모니터링 — 측정 기준 없으면 256MB 유지.

**Cold start 직후 폴링 지연**
- 부팅 ~10s + import ~3s. 폴링 60s 라 무시 가능. 첫 사이클 즉시 처리되길 원하면
  `VLM_POLL_INTERVAL_SEC=10` 로 임시 조정 후 다시 60.

### 비용

- `shared-cpu-1x` 256MB always-on ≈ $1.94/월
- Gemini Flash free tier — 베타 트래픽 (카메라 2대 × 모션 비율) 한도 안 들어옴
- R2 / Supabase egress = 무료

---

## 운영 팁

### 맥북 잠자기 방지 (캡처 가동 시 한정)

캡처 워커가 RTSP 폴링 + R2 업로드 중일 때 맥북이 잠들면 작업 중단. fly.io 컴포넌트는 영향 없음.

**옵션 1 — caffeinate (가볍게)**

```bash
caffeinate -d &        # 디스플레이 포함 슬립 방지. 터미널 종료하면 해제
# or
caffeinate -i -s &     # idle 슬립만 방지 (-i), AC 전원 연결 시 (-s)
```

**옵션 2 — pmset (시스템 설정, 영구)**

```bash
sudo pmset -c sleep 0          # AC 전원일 때만 잠들지 않음 (권장)
sudo pmset -a networkoversleep 1   # 잠들어도 네트워크 유지 시도
```

> 자체 HW 로 캡처가 이전된 뒤에는 위 항목 모두 무관.

### 로그 관찰

- **fly.io API 서버**: `flyctl logs -a petcam-api` (실시간 tail) — HTTP 요청, JWT 검증, lifespan
- **fly.io VLM 워커**: `flyctl logs -a petcam-vlm-worker` — 폴링 사이클, Gemini 호출, INSERT
- **로컬 캡처 워커**: 터미널 A stdout — 세그먼트 닫기, 인코딩 / R2 업로드, INSERT 실패
- **Supabase 로그**: 대시보드 `Logs > API` — 성공/실패 쿼리 통계

### 서버 상태 원격 확인

```bash
curl https://api.tera-ai.uk/health
curl https://petcam-vlm-worker.fly.dev/health
```

Flutter 앱 쪽 ping 기능은 Stage D5 Out (차기 과제).

---

## 트러블슈팅

### `/health` 가 외부에서 안 뜸

**체크 순서 (fly.io API 서버)**
1. **머신이 살아 있나?** `flyctl status -a petcam-api` — `started` 상태인지. `stopped` 면 `flyctl machine start <id>`.
2. **DNS 가 fly.io edge 로 연결됐나?** `dig +short api.tera-ai.uk A` — `66.241.124.67` (또는 fly.io 가 발급한 IP) 반환 확인. Cloudflare IP (`104.x.x.x`, `172.67.x.x` 대역) 가 나오면 proxy 가 켜져 있는 것 — DNS only 로 바꿔야 함.
3. **인증서가 발급됐나?** `flyctl certs check api.tera-ai.uk -a petcam-api` — `Status = Issued` 인지.
4. **컨테이너 안 uvicorn 이 돌고 있나?** `flyctl logs -a petcam-api` — `Uvicorn running on http://0.0.0.0:8000` 라인 확인.
5. **secrets 가 다 박혀있나?** `flyctl secrets list -a petcam-api` — `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWKS_URL` 등 8개 모두 있는지.

### `flyctl deploy` 후 `/health` 200 인데 startup_error 있음

- `curl https://api.tera-ai.uk/health` 응답의 `startup_error` 필드 확인. 보통 secrets 누락 / Supabase 인증 실패.
- `flyctl logs -a petcam-api` 부팅 로그에서 lifespan 단계 에러 메시지 추적.

### 401 "JWKS 조회 실패"

- `SUPABASE_JWKS_URL` 환경변수 오타. 정확한 포맷: `https://<project>.supabase.co/auth/v1/.well-known/jwks.json`
- 네트워크 이슈 — curl 로 JWKS URL 이 200 응답하는지 확인.
- JWKS 캐시가 오래됐을 수도 — 재기동 시 10분 TTL 리셋.

### 401 "JWT 서명 불일치" 인데 토큰은 정상

- **JWKS 키 로테이션** — Supabase 가 키 바꿨을 때 최대 10분간 불일치 가능. `kid` 매칭 실패 시 1회 자동 재시도 구현됨. 10분 기다리거나 서버 재기동.
- **알고리즘 불일치** — 과거 RS256 하드코딩 버그가 있었음 (D5 에서 ES256 자동 분기로 수정). 재발하면 `backend/auth.py` 의 `jwt.PyJWK` 경로 확인.

### 캡처 워커가 안 뜸

cloud-migration 분리 후 캡처 워커는 별도 프로세스 (`backend.capture_main`) 라
`/health` 가 아니라 **터미널 B (capture_main 프로세스) 의 stdout** 을 봐야 한다.

- 터미널 B 로그에 `startup error: ...` 메시지 있는지.
- `"Supabase 미설정"` — `.env` 의 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` 채워졌는지.
- `"DEV_USER_ID 미설정"` — `.env` 에 `DEV_USER_ID` (소유자 UUID) 채워졌는지.
- `"등록된 카메라 없음"` — `cameras` 테이블이 비어있음. `POST /cameras` 또는 Supabase Studio 로 등록.
- `"CAMERA_SECRET_KEY 문제"` — Fernet 키가 placeholder 그대로면 이 에러. 생성 명령어:
  ```bash
  uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
- `"일부 카메라 skip"` — 해당 카메라의 `password_encrypted` 가 다른 Fernet 키로 암호화됨 (키 회전 사고). 해당 카메라 삭제 + 재등록.

> capture_main 이 띄운 워커 수 / 큐 사이즈를 외부에서 조회할 수 있는 모니터링
> 엔드포인트는 후속 spec 에서 추가 예정.

### Tapo RTSP 연결 실패 (`test-connection` 이 false)

- macOS 로컬 네트워크 권한: **시스템 설정 → 개인정보 보호 → 로컬 네트워크 → VSCode/Terminal 토글 ON**. 이거 안 하면 LAN 안의 Tapo 를 찾지 못함.
- Tapo 앱 → Advanced → Camera Account 활성화 확인.
- `stream2` (720p) 로 먼저 시도. `stream1` (1080p) 은 대역폭 타이트한 환경에서 실패 많음.

---

## 롤백 / 긴급 대응

### 외부 접근 즉시 차단

```bash
flyctl machine stop <machine-id> -a petcam-api
# 또는 머신 다 내림
flyctl scale count 0 -a petcam-api
```

머신이 멈추면 fly.io edge 가 즉시 502/503 응답. 백엔드/데이터는 무손상. 복구는 `flyctl scale count 1` 또는 `machine start`.

### 특정 카메라 비활성

```sql
UPDATE cameras SET is_active = false WHERE id = '<camera_uuid>';
```

다음 캡처 워커 부팅부터 해당 워커 skip. `DELETE` 는 clip 행이 CASCADE 로 같이 사라지므로 신중.

### `AUTH_MODE=dev` 로 응급 회귀 (절대 production 에서 X)

dev 모드는 `DEV_USER_ID` 로 누구나 통과 — production 에서 켜는 건 전 데이터 유출. JWT 버그 터지면 fly.io 머신 stop 으로 차단부터.

### 디스크 풀 (캡처 워커 로컬)

`storage/clips/` 가 꽉 차면 새 세그먼트 저장 실패 → 워커가 `state=error` 로 내려감.
**터미널 A (capture_main) 로그**에서 last_error 확인. 오래된 날짜 디렉토리 `rm -rf`
로 정리 (DB 행은 남음 — `GET /clips/{id}/file` 이 410 반환).

### 공개 URL 변경 필요

현재는 `api.tera-ai.uk` 1개. 바꾸려면:
1. `flyctl certs create <new-host> -a petcam-api`
2. Cloudflare DNS Records 에 새 호스트명 A/AAAA 추가 (DNS only)
3. `flyctl certs check <new-host> -a petcam-api` → `Issued`
4. Flutter 앱 `BACKEND_URL` 교체 후 재배포
5. 구 URL 은 `flyctl certs remove <old-host>` + DNS A/AAAA 제거 → 즉시 차단

---

## Appendix — 구 Cloudflare Named Tunnel (history)

> ⚠️ **2026-05-08 폐기.** API 서버는 fly.io 로 이전됐고, `api.tera-ai.uk` DNS 도 A/AAAA 직결로 바뀜. 아래 절차는 **history 보존** 용. 같은 패턴 (LAN 서비스 → outbound 터널) 이 다시 필요할 때 참고.

### 최초 1회 설정

```bash
brew install cloudflared
cloudflared tunnel login
cloudflared tunnel create petcam-lab
cloudflared tunnel route dns petcam-lab api.tera-ai.uk
```

### `~/.cloudflared/config.yml`

```yaml
tunnel: 3c199df0-f2c2-40e3-86a5-a53923a17374
credentials-file: /Users/baek/.cloudflared/3c199df0-f2c2-40e3-86a5-a53923a17374.json

ingress:
  - hostname: api.tera-ai.uk
    service: http://localhost:8000
  - service: http_status:404
```

### 운영 명령어

```bash
cloudflared tunnel run petcam-lab          # foreground 가동
cloudflared tunnel list                     # 연결 상태 / 머신 수
brew services start cloudflared             # launchd 자동 가동 (옵션)
```

### 폐기 절차 (이미 수행됨)

1. `cloudflared` 프로세스 종료 + `brew services stop cloudflared`
2. Cloudflare DNS Records 에서 Type=Tunnel api 레코드 삭제
3. fly.io 가 발급한 A/AAAA 추가 (DNS only)
4. `flyctl certs create api.tera-ai.uk` → 인증서 발급 확인
5. Flutter / 라벨링 웹 production traffic 검증

관련 스펙: [`specs/stage-d5-deploy-tunnel.md`](../specs/stage-d5-deploy-tunnel.md) (구 셋업), [`specs/feature-api-server-fly-deploy.md`](../specs/feature-api-server-fly-deploy.md) (이전). 학습 맥락: [`docs/learning/stage-d5-tunnel-learning.md`](learning/stage-d5-tunnel-learning.md).
