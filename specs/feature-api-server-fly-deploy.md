# fly.io API 서버 이전 + Flutter contract 채우기

> `api.tera-ai.uk` 를 사용자 맥북 (Cloudflare Tunnel) 에서 fly.io always-on 으로 옮기고, 동시에 Flutter 가 요구한 누락 endpoint 2개 (`/me/is_labeler`, `/clips/highlights`) 추가.

**상태:** 🚧 진행 중
**작성:** 2026-05-07
**연관 SOT:** `../tera-ai-product-master/docs/specs/petcam-backend-dev.md`
**연관 spec:** [`flutter-cloud-handoff.md`](flutter-cloud-handoff.md), [`feature-vlm-worker-fly-deploy.md`](feature-vlm-worker-fly-deploy.md), [`cloud-migration-roadmap.md`](cloud-migration-roadmap.md), [`feature-labeling-web-cloud.md`](feature-labeling-web-cloud.md)

## 1. 목적

### 사용자 가치

**베타 단계 (지금)**:
- API 서버가 사용자 맥북 (`localhost:8000` + Cloudflare Tunnel) 에 묶여 있음 → 노트북 닫으면 Flutter 앱 모든 호출 즉시 503. 클라우드로 분리해야 베타테스터가 24/7 사용 가능.
- 2026-05-05 부터 사용자 명시 신호로 일시 중지 상태. 이번 작업으로 종료.

**Flutter 통합 블로커 해결**:
- `flutter-cloud-handoff.md` §4 에서 Flutter 앱이 요청한 6 endpoint 중 4개 (`/clips/{id}/file/url`, `/thumbnail/url`, `/labels`, `/inference`) 는 이미 존재 — 다만 API 서버가 살아있어야 호출 가능. fly.io 이전이 그 잠금 해제.
- 남은 2개 `/me/is_labeler`, `/clips/highlights` 는 백엔드에 없음 — Flutter Phase C (라벨 chip) / Phase D (하이라이트 탭) 진행 불가. 이번에 같이 추가.

**프로덕션 단계 (장기)**:
- VLM 워커 (`feature-vlm-worker-fly-deploy.md`) 가 이미 fly.io 가동 중. 라벨링 웹 (Vercel) 도 always-on. **API 서버만 사용자 디바이스에 남으면 single point of failure.**
- 4 컴포넌트 (API / VLM / R2 / 라벨링 웹) 모두 클라우드로 옮겨야 자체 HW 카메라 트랙 (`project_capture_replaced_by_own_hw.md`) 도착 시 깔끔하게 직결 가능 (캡처 → R2 → DB → VLM → API → Flutter).

### 기술 학습
- HTTP 서버 (FastAPI) 를 fly.io 에 배포 (워커와 다른 점: 외부 도메인 + Let's Encrypt + DNS 전환).
- `flyctl certs create` + Let's Encrypt 자동 발급 흐름.
- Cloudflare DNS CNAME 전환 (Tunnel CNAME 제거 → fly.io custom domain).
- secrets 회전 (Fernet key, JWKS URL, R2 credentials 등 11개).

## 2. 스코프

### In (이번 스펙에서 한다)

**Phase 1 — 새 endpoint 2개 추가 (한 PR, 회귀 가드 포함)**
- `GET /me/is_labeler` — `clip_perms.is_labeler(user_id, sb)` 헬퍼 wrap. 응답 `{"is_labeler": bool}`.
  - 위치: `backend/routers/me.py` 신규 (라벨/클립/카메라 어디에도 안 맞아 별도 라우터).
- `GET /clips/highlights` — VLM 또는 owner 검수가 main 4 클래스 (eating_paste/drinking/moving/unknown 제외 행동) 라벨링한 클립 목록.
  - 위치: `backend/routers/clips.py` 안에 추가 (clips 도메인).
  - 정의 (cloud-migration-roadmap §4-7): `behavior_logs` 또는 `behavior_labels` 가 있는 clip → DISTINCT ON (clip_id) 로 1건만 (human 우선, 없으면 vlm).
  - cursor pagination (started_at 기준, 기존 ClipPage 패턴 재사용).
- pytest — 기존 224 통과 + 새 케이스 6~8개 (is_labeler 멤버/비멤버, highlights 빈/단일/페이지/owner-only).
- 로컬 검증만 (`uv run pytest`, `curl localhost:8000/me/is_labeler` JWT 통과 확인).

**Phase 2 — fly.io 셋업 (staging)**
- `Dockerfile.api` — VLM 워커 Dockerfile 패턴 재사용. `uv sync` 후 `uvicorn backend.main:app` 으로 entrypoint 만 변경.
- `fly.api.toml` — 앱 이름 `petcam-api`, region `nrt`, `shared-cpu-1x` 256MB, `auto_stop_machines = false`, `min_machines_running = 1`, `[[http_service.checks]]` `/health` 30s.
- `scripts/fly-set-secrets-api.sh` — secrets 11개 일괄 (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWKS_URL`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `RTSP_CRED_FERNET_KEY`, `LABELING_WEB_ORIGINS`, `AUTH_MODE=prod`, `LOG_LEVEL=INFO`).
- `flyctl deploy --config fly.api.toml` → `petcam-api.fly.dev` staging URL 검증 (Flutter 호출 patch 한 번 + 라벨링 웹 큐 호출 patch 한 번).

**Phase 3 — DNS 전환 (production cutover)**
- `flyctl certs create api.tera-ai.uk` (Let's Encrypt 자동).
- Cloudflare DNS: `api.tera-ai.uk` Tunnel CNAME 제거 → fly.io custom domain (검증된 CNAME 으로).
- DNS propagation 확인 후 `curl https://api.tera-ai.uk/health` 200.
- Flutter / 라벨러 큐 양쪽 production 200 검증.
- 사용자 맥북 Cloudflare Tunnel 종료 (`cloudflared` 프로세스) + `uvicorn backend.main:app` 종료. 캡처 워커는 맥북에 남음 (자체 HW 등장 전까지).

**Phase 4 — 문서화 + commit**
- 이 spec ✅ 완료 표시.
- `docs/DEPLOYMENT.md` — fly.io API 서버 섹션 추가 + Cloudflare Tunnel 섹션 deprecated 표시.
- `docs/ARCHITECTURE.md` 다이어그램 갱신 (Tunnel → fly.io).
- `specs/next-session.md` 가동 상태 + 트랙 표 갱신.
- `specs/flutter-cloud-handoff.md` "백엔드 가동 상태" — API 서버 fly.io 명시.
- `docs/handoff-prompts/flutter-cloud-migration.md` 동일.
- `.claude/donts-audit.md` Standard+ 1줄 entry.

### Out (이번 스펙에서 **안 한다**)
- **Capture 워커 fly.io 배포** — capture 는 RTSP 의존이라 LAN 안에서만 가능. 자체 HW 카메라가 클라우드로 직접 push 하면 워커 자체가 사라짐 (`project_capture_replaced_by_own_hw.md`). 그 전까지 사용자 맥북 유지.
- **API 서버 멀티 region** — petcam 사용자 한국 한정. `nrt` 단일.
- **HA / 멀티 머신** — 베타 단계 단일 머신. UNIQUE 제약 + idempotent 호출 덕분에 향후 `min_machines_running` 만 올리면 됨.
- **`/clips/highlights` 의 알림/푸시 통합** — 정의만 만들고 Flutter 가 polling 으로 표시. 푸시는 별도 spec.
- **Flutter 측 코드 변경** — 옆 레포 (tera-ai-flutter) 작업. 이 spec 끝나면 Flutter 세션에 "endpoint ready" 신호.
- **VLM 워커 / 라벨링 웹 secrets 회전** — 별개 컴포넌트. API secrets 만 신규.
- **Custom domain 전환 시 zero-downtime** — 베타 단계 사용자 1명 (owner). DNS propagation 동안 5~10분 503 발생할 수 있음 — 사용자 명시 양해 후 전환 시간 합의.

> **스코프 변경은 합의 후에만.** 작업 중 In/Out 경계가 흔들리면 이 섹션 수정 + 사유 기록.

## 3. 완료 조건

체크리스트가 곧 진행 상태.

### Phase 1 — endpoint 2개 (한 PR)
- [ ] `backend/routers/me.py` 신규 — `GET /me/is_labeler` 200 `{"is_labeler": bool}`.
- [ ] `backend/main.py` 에 `me_router` include.
- [ ] `backend/routers/clips.py` 에 `GET /clips/highlights` 추가 — cursor pagination, DISTINCT ON (clip_id) human 우선, 응답 `{items: [...], next_cursor: str|null}`.
- [ ] `tests/test_me.py` 신규 — labeler/non-labeler 2 케이스.
- [ ] `tests/test_clips_highlights.py` 신규 — 빈/단일/페이지/non-owner 차단 4 케이스.
- [ ] 기존 `uv run pytest` 224 케이스 회귀 0.
- [ ] 로컬 `curl http://localhost:8000/me/is_labeler` (JWT) 200 + `curl /clips/highlights` 200.
- [ ] commit `feat(api): /me/is_labeler + /clips/highlights endpoint`.

### Phase 2 — fly.io 셋업 (staging)
- [ ] `Dockerfile.api` build 통과 — `docker build -f Dockerfile.api -t petcam-api .` 로컬.
- [ ] `docker run --env-file .env -p 8000:8000 petcam-api` — `/health` 200 + `/me/is_labeler` JWT 검증.
- [ ] `fly.api.toml` 작성.
- [ ] `flyctl apps create petcam-api` (region `nrt`).
- [ ] `scripts/fly-set-secrets-api.sh` 11개 secrets 적용 + `flyctl secrets list -a petcam-api` 마스킹 확인.
- [ ] `flyctl deploy --config fly.api.toml` 통과. `flyctl status -a petcam-api` healthy.
- [ ] `curl https://petcam-api.fly.dev/health` 200.
- [ ] Flutter 한 endpoint patch (BACKEND_URL 임시 `https://petcam-api.fly.dev`) → file/url 200 + thumbnail 200 + labels 200.
- [ ] 라벨링 웹 큐 호출도 staging URL 로 한 번 — owner 큐 200 검증.

### Phase 3 — DNS 전환 (production)
- [ ] `flyctl certs create api.tera-ai.uk -a petcam-api` 발급 진행 시작.
- [ ] Cloudflare DNS: `api.tera-ai.uk` Tunnel CNAME 제거 + fly.io custom domain 추가 (검증 CNAME `<acme>.<app>.fly.dev`).
- [ ] `flyctl certs show api.tera-ai.uk -a petcam-api` 상태 `Has Certificate`.
- [ ] `curl https://api.tera-ai.uk/health` 200.
- [ ] Flutter `BACKEND_URL` 원복 (production 도메인) — 시뮬레이터 1회 라운드트립 검증.
- [ ] 라벨링 웹 큐 production 200.
- [ ] 사용자 맥북 `cloudflared` 종료 + `uvicorn backend.main:app` 종료.

### Phase 4 — 문서화
- [ ] 이 spec 상태 ✅ 완료.
- [ ] `docs/DEPLOYMENT.md` API 서버 fly.io 섹션 추가 + Tunnel 섹션 deprecated.
- [ ] `docs/ARCHITECTURE.md` 다이어그램 갱신.
- [ ] `specs/next-session.md` 가동 상태 표 갱신 + Cloud Migration 트랙 표에 이 spec 행 추가.
- [ ] `specs/flutter-cloud-handoff.md` + `docs/handoff-prompts/flutter-cloud-migration.md` 가동 상태 단락 갱신.
- [ ] `.claude/donts-audit.md` Standard+ entry.
- [ ] `specs/README.md` 표 갱신.
- [ ] commit `feat(api): fly.io 이전 완료 + Flutter contract 채움 (is_labeler + highlights)`.

## 4. 설계 메모

### 왜 한 spec 묶음? (사용자 결정 2026-05-07)
- 두 spec (endpoint 추가 + fly.io 이전) 으로 쪼개면 spec 관리 비용 ↑, 진행 추적 흐려짐.
- endpoint 2개는 fly.io 이전 없이도 의미 있지만 (로컬 검증 가능), production 가치는 fly.io 가 살아야 발현 → 묶는 게 자연스러움.
- 4 phase 명확히 분리 + 체크리스트 phase 별 그룹핑 → 한 spec 안에서도 진행 상태 가독성 유지.

### 왜 Phase 1 endpoint 2개를 한 PR? (사용자 결정 2026-05-07)
- 두 endpoint 모두 회귀 위험 ≤ 1 라우터, 테스트 8 케이스 추가, 변경 범위 좁음.
- 분리하면 PR 2회 review 부담 + Flutter 측 보고 2회. 묶는 비용 < 분리 비용.
- 단 fly.io PR (Phase 2~3) 은 별도 commit — DNS 전환 롤백 시 endpoint 코드는 살리고 인프라만 되돌리기 위해.

### 왜 `petcam-api` 앱 이름? (사용자 결정 2026-05-07)
- VLM 워커 = `petcam-vlm-worker` 패턴 따름. `petcam-` prefix 로 같은 제품군 묶이고 fly.io dashboard 에서 한눈에 보임.
- `petcam-backend` 는 모호 (VLM 워커도 backend). `petcam-api` 가 역할 정확.

### 왜 256MB 부터? (사용자 결정 2026-05-07)
- VLM 워커도 256MB 가동 중 — supabase-py + boto3 (R2) + Fernet 정도로는 부족 안 할 것 (Gemini SDK 가 빠지므로 워커보다 가벼움).
- fly metrics 보고 부족하면 `flyctl scale memory 512` 한 줄로 즉시 올림. 비용 차이 $1.94/월 → $3.88/월, 베타에 무의미.
- 학습 가치도 — 처음부터 512MB 박으면 메모리 모니터링 동기 약함.

### `/clips/highlights` 정의 (cloud-migration-roadmap §4-7 락인)
- 입력: `behavior_logs` (vlm 자동 라벨) + `behavior_labels` (owner 검수) 두 테이블.
- 정책: clip 당 1건 — human 라벨 있으면 그것, 없으면 vlm 라벨.
- 필터: main 4 (eating_paste / drinking / moving / unknown) **제외** = "특별한 행동" 이라는 spec 정의.
  - 후보: eating_prey, defecating, shedding, basking, unseen → 이 5개가 highlight 대상.
- 정렬: clip.started_at DESC.
- pagination: cursor = ISO8601 timestamp (started_at), 기존 `/clips` 패턴 재사용.

### 왜 `Dockerfile.api` 별도? (워커 Dockerfile 과 분리)
- 같은 베이스 (`python:3.12-slim` + uv) 지만 entrypoint 와 COPY 범위가 다름.
- 워커 = `backend.vlm_worker_main` + `web/prompts/`.
- API = `backend.main` + uvicorn. `web/prompts/` 불필요.
- 한 Dockerfile multi-target 도 가능하지만 (build args) 학습 단계 과한 복잡도. 두 파일이 더 명확.

### DNS 전환 — Cloudflare Tunnel 제거 vs 유지
- **선택**: 제거. fly.io custom domain 으로 완전 이전.
- **고려한 대안**: Tunnel 유지 (fallback) — 두 origin 동시 운영. fly.io 장애 시 자동 fallback.
- **이유**: fly.io fly-proxy 는 own SLA 99.95% 존재. Tunnel 유지 = 사용자 맥북 + cloudflared 의존 = 분리 목적 무효. 장애 대응은 fly.io status 모니터링 + 알림으로 별개 트랙.

### secrets 11개 정리
| 변수 | 출처 | 비고 |
|------|------|------|
| `SUPABASE_URL` | Supabase project | VLM 워커와 동일 |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase project | VLM 워커와 동일 |
| `SUPABASE_JWKS_URL` | Supabase project | API 만 (JWT 검증) |
| `R2_ENDPOINT` | Cloudflare R2 | 워커와 동일 |
| `R2_ACCESS_KEY_ID` | Cloudflare R2 | 워커와 동일 |
| `R2_SECRET_ACCESS_KEY` | Cloudflare R2 | 워커와 동일 |
| `R2_BUCKET` | Cloudflare R2 | 워커와 동일 |
| `RTSP_CRED_FERNET_KEY` | 로컬 .env | 카메라 password 암호화 키. **회전 시 기존 카메라 복호화 불가** — `.env` 값 그대로 옮김. |
| `LABELING_WEB_ORIGINS` | 결정값 | `https://label.tera-ai.uk` (CORS) |
| `AUTH_MODE` | 결정값 | `prod` 강제 — `dev` 우회 사고 방지 |
| `LOG_LEVEL` | 결정값 | `INFO` (운영 표준) |

### 리스크 / 미해결 질문
- **DNS propagation 5~10분 503** — 베타 사용자 1명에게 명시 양해. 새벽 시간대 전환 권장.
- **Fernet key 분실 위험** — `.env` 의 `RTSP_CRED_FERNET_KEY` 가 fly secrets 와 일치해야 기존 카메라 복호화. 미리 backup.
- **Flutter `BACKEND_URL` 환경 변수 위치** — Flutter 세션에 staging URL → production 도메인 두 번 patch 요청 부담. dart-define 패턴이면 hot reload 로 가능.
- **VM 256MB OOM** — clips list/highlights query 가 500+ row 반환 시 메모리 spike 가능. `fly metrics` 모니터링 + 부족 시 `scale memory 512`.
- **Cloudflare Tunnel 연결 종료 타이밍** — production 200 검증 끝나기 전까지 Tunnel 유지. 검증 후에만 `cloudflared` 종료.

## 5. 학습 노트

- **fly.io custom domain + certs**: `flyctl certs create <domain>` → fly.io 가 ACME challenge CNAME 발급 → 그 CNAME 을 Cloudflare DNS 에 추가 → Let's Encrypt 자동 발급 (5~10분). 이후 그 도메인 으로 들어오는 트래픽이 fly-proxy 로 라우팅. (TS 비유: Vercel 의 custom domain 추가와 동일 흐름, ACME challenge 가 자동.)
- **`flyctl deploy` vs `flyctl deploy --config <toml>`**: `--config` 미지정 시 `fly.toml` 자동 감지. 한 레포에 여러 fly 앱 (워커 + API) 이면 toml 파일 별도로 두고 `--config` 명시.
- **DNS CNAME 전환 시 zero-downtime 전략**: TTL 짧게 (300s) → 새 CNAME 추가 → 검증 → 옛 CNAME 제거 → TTL 정상 복원. 사용자 1명이라 굳이 안 함.
- **`uvicorn backend.main:app --host 0.0.0.0 --port 8080`**: fly.io 컨테이너 안에서는 `0.0.0.0` 바인딩 필수. `127.0.0.1` 이면 fly-proxy 가 못 닿음. 로컬 dev 의 `127.0.0.1` 과 다른 점.
- **`AUTH_MODE=prod` 강제 이유**: backend/auth.py 에 `dev` 모드 (JWT 우회) 가 있음 → fly secrets 에 반드시 `prod` 로 박아 운영 사고 차단.
- **DISTINCT ON (PostgreSQL)**: 한 컬럼 기준 그룹별 첫 row 반환. `SELECT DISTINCT ON (clip_id) * FROM ... ORDER BY clip_id, source = 'human' DESC, created_at DESC`. (TS/Node 비유: GROUP BY + window function 대신 짧은 한 줄.)
- **Cursor pagination**: offset 대신 마지막 row 의 정렬 키 (started_at) 를 다음 호출에 전달. row 추가/삭제에도 안정. 기존 `/clips` 가 이미 사용 — 동일 패턴.

## 6. 참고

- fly.io launch: https://fly.io/docs/launch/
- fly.io custom domain: https://fly.io/docs/networking/custom-domain/
- fly.io certificates: https://fly.io/docs/networking/custom-domains-with-fly/
- 연관 spec: [`feature-vlm-worker-fly-deploy.md`](feature-vlm-worker-fly-deploy.md), [`flutter-cloud-handoff.md`](flutter-cloud-handoff.md), [`cloud-migration-roadmap.md`](cloud-migration-roadmap.md)
- 연관 memory: `project_macbook_migration_pending.md`, `project_capture_replaced_by_own_hw.md`, `project_owner_account.md`
