# 배포 가이드

> petcam-lab 백엔드를 **외부망 공개**하는 방법. Cloudflare Named Tunnel (`api.tera-ai.uk`) + `AUTH_MODE=prod` 이 현재 운영 스탠스.

## 목차

- [배포 아키텍처](#배포-아키텍처)
- [사전 준비](#사전-준비)
- [Cloudflare Named Tunnel 설정](#cloudflare-named-tunnel-설정)
- [평상시 실행 체크리스트](#평상시-실행-체크리스트)
- [AUTH_MODE prod 전환](#auth_mode-prod-전환)
- [운영 팁](#운영-팁)
- [트러블슈팅](#트러블슈팅)
- [롤백 / 긴급 대응](#롤백--긴급-대응)

---

## 배포 아키텍처

```
[Flutter 앱 (LTE)]
       │ HTTPS
       ▼
[Cloudflare Edge]   ← 공인 DNS `api.tera-ai.uk`
       │
       │ 역방향 터널 (HTTP/2 멀티플렉싱, outbound-only)
       ▼
[맥북 cloudflared 프로세스]
       │ http://localhost:8000
       ▼
[uvicorn (backend.main:app, 127.0.0.1 바인딩)]   ← 프로세스 #1: HTTP API only
       │
       └── Supabase (camera_clips, cameras, labels) + R2 signed URL 발급

[backend.capture_main (asyncio standalone)]      ← 프로세스 #2: 캡처+인코딩+R2 업로드
       │
       ├── RTSP → CaptureWorker N개 → Tapo C200 × 2
       └── EncodeUploadWorker → R2 PUT + Supabase camera_clips INSERT

[backend.vlm_worker_main (asyncio standalone)]   ← 프로세스 #3: VLM 자동 라벨링
       │ ▸ production: fly.io `petcam-vlm-worker` (nrt, always-on)
       │ ▸ 로컬 검증: `uv run python -m backend.vlm_worker_main`
       │ camera_clips 폴링 (60s prod / 30s 로컬 기본) — has_motion + r2_key + NOT EXISTS
       ├── R2 GET (영상 bytes)
       ├── Gemini 2.5 Flash 호출 (v3.5 prompt 락인)
       └── behavior_logs INSERT (source='vlm', UNIQUE 제약 idempotent)
```

**핵심 설계 (cloud-migration 분리, 2026-05-07)**
- **세 프로세스 분리** — API 서버 / 캡처 워커 / VLM 워커. 같은 코드베이스 + 같은 `.env` (또는 fly secrets). RTSP 가 LAN 의존이라 캡처만 LAN (맥북 / 추후 자체 HW) 에 남고, API 와 VLM 은 클라우드로 옮길 수 있음. **VLM 워커는 이미 fly.io 로 옮겨짐** (2026-05-07). 결정 락인: [`specs/cloud-migration-roadmap.md`](../specs/cloud-migration-roadmap.md) §4-3, [`specs/feature-vlm-worker-fly-deploy.md`](../specs/feature-vlm-worker-fly-deploy.md).
- **uvicorn 은 `127.0.0.1` 에만 바인딩** — 외부에서 맥북 IP 로 직접 접근 불가. 오직 cloudflared 프로세스만 경유.
- **NAT 뚫기** — `cloudflared` 가 outbound 로 Cloudflare 엣지에 파이프를 만들어 둠. 공유기 포트포워딩 불필요.
- **HTTPS 자동** — Cloudflare 가 엣지에서 TLS 종료. 인증서 별도 관리 불필요. iOS ATS 문제 없음.
- **인증은 JWT** — `AUTH_MODE=prod` 에서 Supabase 에서 발급한 JWT 를 JWKS 로 검증.
- **세 프로세스 공유** — `.env` (Supabase service_role / Fernet / R2 / DEV_USER_ID / GEMINI_API_KEY), DB 스키마, R2 버킷.
- **DB-as-message-bus (VLM)** — VLM 워커가 polling SELECT 으로 미라벨 클립 가져옴. 별도 큐 인프라 (Redis / SQS) 도입 안 함. UNIQUE(clip_id, source) 제약이 동시 워커 race 방어.

---

## 사전 준비

### 한 번만

1. **Cloudflare 계정** — `terraaidev@gmail.com` 으로 로그인
2. **도메인 등록** — `tera-ai.uk` (Cloudflare Registrar 또는 외부에서 구입 후 Nameserver 이전)
3. **Homebrew** — 맥북 OS 표준

### 매번 (맥북 재부팅 후)

- Tapo 카메라 2대 켜기 + Wi-Fi 연결 확인 (Tapo 앱에서 녹색 표시)
- 맥북 잠자기 방지 확인 (아래 [운영 팁](#운영-팁))

---

## Cloudflare Named Tunnel 설정

### 최초 1회 설정

```bash
# 1. cloudflared 설치
brew install cloudflared
cloudflared --version   # 2026.3.0 이상

# 2. Cloudflare 계정 로그인 (브라우저 OAuth)
cloudflared tunnel login
# → ~/.cloudflared/cert.pem 생성됨

# 3. 터널 생성
cloudflared tunnel create petcam-lab
# → UUID 출력 (예: 3c199df0-f2c2-40e3-86a5-a53923a17374)
# → ~/.cloudflared/<UUID>.json (credentials) 생성됨

# 4. DNS 라우팅 (Cloudflare 대시보드의 tera-ai.uk zone 에 CNAME 자동 추가)
cloudflared tunnel route dns petcam-lab api.tera-ai.uk
```

### `~/.cloudflared/config.yml` 작성

```yaml
tunnel: 3c199df0-f2c2-40e3-86a5-a53923a17374
credentials-file: /Users/baek/.cloudflared/3c199df0-f2c2-40e3-86a5-a53923a17374.json

ingress:
  - hostname: api.tera-ai.uk
    service: http://localhost:8000
  - service: http_status:404
```

**ingress 규칙**
- 첫 줄: `api.tera-ai.uk` 로 들어온 요청을 `localhost:8000` (uvicorn) 으로 프록시.
- 끝 줄: 다른 호스트명은 404 (catch-all). 필수 — 없으면 cloudflared 가 에러.

---

## 평상시 실행 체크리스트

```
[  ] 1. Tapo 카메라 2대 켜져 있음 (녹색 LED)
[  ] 2. 맥북 잠자기 방지 (caffeinate -d &)
[  ] 3. 터미널 A — uvicorn (API 서버) 기동
[  ] 4. 터미널 B — capture_main (캡처+인코딩+R2 업로드 워커) 기동
[  ] 5. 터미널 C — cloudflared 기동
[  ] 6. (선택) 터미널 D — vlm_worker_main 로컬 검증용 — 평소엔 fly.io 워커가 처리
[  ] 7. 외부에서 https://api.tera-ai.uk/health 확인 (API)
[  ] 8. 외부에서 https://petcam-vlm-worker.fly.dev/health 확인 (VLM 워커)
[  ] 9. Flutter 앱에서 로그인 → 클립 피드 로드
```

> ⚠️ 터미널 A/B 는 **둘 다 떠 있어야** 정상 동작. A 만 띄우면 API 는 응답하지만
> 새 클립이 안 만들어짐. B 만 띄우면 클립은 쌓이지만 외부에서 조회 불가.
> **VLM 워커는 fly.io 가 default** — 클라우드 always-on 으로 모션 클립 자동 라벨.
> 터미널 D 는 회귀 / 디버깅 / 새 prompt 검증할 때만 (로컬에서 수동 가동).
> ⚠️ 로컬 D 와 fly.io 워커가 동시에 도는 상황은 race 안전 (UNIQUE(clip_id, source)
> 가 idempotency 보장) 이지만 동일 클립을 두 번 inference 하므로 불필요. 검증 끝나면 로컬 종료.

### 기동 순서

**터미널 A** — API 서버 (`127.0.0.1` 바인딩 필수)

```bash
cd /Users/baek/petcam-lab
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

기동 로그에 다음이 보여야 정상.
```
AUTH_MODE=prod
INFO:     Uvicorn running on http://127.0.0.1:8000
```

**터미널 B** — 캡처 워커 (standalone asyncio)

```bash
cd /Users/baek/petcam-lab
uv run python -m backend.capture_main
# 또는 entrypoint 등록 후:
# uv run petcam-capture
```

기동 로그에 다음이 보여야 정상.
```
AUTH_MODE=prod
capture worker started: camera=<uuid> (거실)
capture worker started: camera=<uuid> (작업실)
capture_main running: 2 worker(s), 0 skipped — Ctrl+C / SIGTERM 으로 정지
```

**터미널 D** (선택) — VLM 자동 라벨링 워커

```bash
cd /Users/baek/petcam-lab
uv run python -m backend.vlm_worker_main
# 또는 entrypoint 등록 후:
# uv run petcam-vlm
```

기동 로그에 다음이 보여야 정상.
```
AUTH_MODE=prod
vlm worker started — poll_interval=30s limit=10
```

처리 사이클마다 (`polled` > 0 인 경우) 통계 로그가 찍힘. 아무 클립도 미라벨 상태가 아니면 조용함 (정상).

**환경변수 (이 워커 전용)**
- `GEMINI_API_KEY` — [AI Studio](https://aistudio.google.com/app/apikey) 발급. 누락 시 `Gemini 미설정` 으로 부팅 실패.
- `VLM_POLL_INTERVAL_SEC` (선택, 기본 30) / `VLM_POLL_LIMIT` (선택, 기본 10).

**선행 마이그레이션** — Supabase SQL Editor 에서 [`migrations/2026-05-07_behavior_logs_unique_clip_source.sql`](../migrations/2026-05-07_behavior_logs_unique_clip_source.sql) 실행. UNIQUE(clip_id, source) 제약이 idempotency 보장.

**터미널 C** — Cloudflare Tunnel

```bash
cloudflared tunnel run petcam-lab
```

기동 로그에 `4 connection` 이 뜨면 정상. (Cloudflare 엣지에 4개 병렬 연결.)

**외부 검증**

```bash
curl https://api.tera-ai.uk/health
# → {"status": "ok", "startup_error": null}
# (워커 상태는 capture_main 프로세스 영역이라 별도. 후속 spec 에서 모니터링 엔드포인트 추가 예정)

curl https://api.tera-ai.uk/clips
# → {"detail": "Authorization 헤더가 없음."}  ← 401, prod 정상
```

### 종료 순서

- **터미널 C** — Ctrl+C (Tunnel 먼저 끊어서 외부 요청 차단)
- **터미널 A** — Ctrl+C (API 서버 종료)
- **터미널 B** — Ctrl+C (캡처 stop 후 EncodeUploadWorker drain → 종료. SIGINT/SIGTERM 둘 다 graceful)
- **터미널 D** — Ctrl+C (VLM 워커는 진행 중 사이클 완료 후 정지. 다음 부팅 시 미라벨 클립부터 자동 재처리.)

---

## AUTH_MODE prod 전환

`.env` 수정.

```bash
AUTH_MODE=prod
SUPABASE_JWT_ISSUER=https://<project>.supabase.co/auth/v1
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

### 맥북 잠자기 방지

`cloudflared` 프로세스가 죽으면 터널 끊김 → 외부 접속 불가. 잠자기 상태에선 네트워크 I/O 도 얼어붙음.

**옵션 1 — caffeinate (가볍게)**

```bash
caffeinate -d &        # 디스플레이 포함 슬립 방지. 터미널 종료하면 해제
# or
caffeinate -i -s &     # idle 슬립만 방지 (-i), AC 전원 연결 시 (-s)
```

**옵션 2 — pmset (시스템 설정, 영구)**

```bash
sudo pmset -a sleep 0          # 절대 잠들지 않음 (사용자 권장 X, 배터리 과소모)
sudo pmset -c sleep 0          # AC 전원일 때만 잠들지 않음 (권장)
sudo pmset -a networkoversleep 1   # 잠들어도 네트워크 유지 시도
```

**옵션 3 — launchd plist (자동 기동)**

현재 스펙은 수동 기동 전제 (테스터 5명 이하). 24시간 보장 원하면 `~/Library/LaunchAgents/com.petcam.cloudflared.plist` 작성 후 `launchctl load`. Stage D5 에서 스펙상 Out.

### 로그 관찰

- **uvicorn** 로그: 캡처 워커 상태, INSERT 실패, lifespan 이벤트
- **cloudflared** 로그: 연결 끊김/재연결, 트래픽 분기
- **Supabase 로그**: 대시보드 `Logs > API` — 성공/실패 쿼리 통계

### 서버 상태 원격 확인

```bash
curl https://api.tera-ai.uk/health
```

Flutter 앱 쪽에서 주기 ping 으로 "서버 대기 중" UX 를 띄우는 기능은 Stage D5 Out (차기 과제).

---

## 트러블슈팅

### `/health` 가 외부에서 안 뜸

**체크 순서**
1. **uvicorn 이 돌고 있나?** `curl http://localhost:8000/health` — 로컬에서도 안 뜨면 FastAPI 문제.
2. **cloudflared 가 돌고 있나?** `cloudflared tunnel list` 로 `petcam-lab` 상태 확인.
3. **DNS 가 cloudflared 로 연결됐나?** `dig api.tera-ai.uk` — Cloudflare IP (`104.x.x.x`, `172.67.x.x` 대역) 반환 확인.
4. **config.yml 이 맞나?** `~/.cloudflared/config.yml` 의 tunnel UUID 와 `cloudflared tunnel list` 출력 대조.

### `curl localhost:8000` 은 되는데 `api.tera-ai.uk` 만 안 됨

- `config.yml` 의 `service: http://localhost:8000` 포트가 uvicorn 포트와 일치하는지.
- uvicorn 이 `0.0.0.0` 이 아니라 `127.0.0.1` 에만 바인딩돼도 cloudflared 는 localhost 로 접근하니 OK.

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

터미널 B 에서 `cloudflared` Ctrl+C — 즉시 `api.tera-ai.uk` 요청 전부 실패 (Cloudflare 엣지가 백엔드 응답 없음 ⇒ 522). 백엔드/데이터는 무손상.

### 특정 카메라 비활성

```sql
UPDATE cameras SET is_active = false WHERE id = '<camera_uuid>';
```

다음 서버 기동부터 해당 워커 skip. `DELETE` 는 clip 행이 CASCADE 로 같이 사라지므로 신중.

### `AUTH_MODE=dev` 로 응급 회귀

prod 에서 JWT 검증 버그가 터지면 일시적으로 `AUTH_MODE=dev` 로 돌릴 수 있음. **단 외부 공개된 상태면 cloudflared 를 먼저 끄고** 시도. dev + 공개는 전 데이터 유출.

### 디스크 풀

`storage/clips/` 가 꽉 차면 새 세그먼트 저장 실패 → 워커가 `state=error` 로 내려감.
**터미널 B (capture_main) 로그**에서 last_error 확인. 오래된 날짜 디렉토리 `rm -rf`
로 정리 (DB 행은 남음 — `GET /clips/{id}/file` 이 410 반환).

### 공개 URL 변경 필요

현재는 `api.tera-ai.uk` 1개. 바꾸려면:
1. Cloudflare DNS 에서 새 호스트명 CNAME 추가 (`cloudflared tunnel route dns`)
2. `~/.cloudflared/config.yml` 의 `ingress.hostname` 수정
3. Flutter 앱 `BACKEND_URL` 교체 후 재배포
4. 구 URL 은 DNS CNAME 제거하면 즉시 차단

---

관련 스펙: [`specs/stage-d5-deploy-tunnel.md`](../specs/stage-d5-deploy-tunnel.md). 학습 맥락: [`docs/learning/stage-d5-tunnel-learning.md`](learning/stage-d5-tunnel-learning.md).
