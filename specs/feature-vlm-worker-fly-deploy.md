# fly.io VLM 워커 배포

> production VLM 워커를 fly.io 에 always-on 으로 띄워 베타테스터용 자동 라벨 파이프라인을 클라우드로 분리.

**상태:** ✅ 완료
**작성:** 2026-05-07
**완료:** 2026-05-07
**연관 SOT:** `../tera-ai-product-master/docs/specs/petcam-backend-dev.md`
**연관 spec:** [`feature-vlm-worker-cloud.md`](feature-vlm-worker-cloud.md), [`cloud-migration-roadmap.md`](cloud-migration-roadmap.md)

## 1. 목적

### 사용자 가치

**베타 단계 (지금)**:
- 베타테스터 (owner 계정 공유 `bss.rol20@gmail.com`) 가 라벨링 웹에서 자동 라벨을 보고 검수/수정하는 루프 가동 → GT 누적 + 모델 신뢰도 측정.
- 라벨링 웹 (`label.tera-ai.uk`) + R2 인프라는 이미 가동 중 → 마지막 piece 가 워커.
- 워커가 사용자 맥북에 묶이면 노트북 닫는 순간 라벨링 멈춤 → 베타 운영 불가. 클라우드로 분리.

**프로덕션 단계 (장기) — 워커는 이 시점에 진짜 핵심**:
- **petcam 가치 제안의 실행 엔진** — "AI 가 펫 행동을 자동 기록" 약속을 실제로 수행하는 컴포넌트. 사용자가 모바일 앱에서 "오늘 게코가 뭐했지?" 보는 모든 데이터가 여기서 나옴.
- **하이라이트 / 알림 트리거** — `cloud-migration-roadmap.md` 결정대로 *하이라이트 = 행동 라벨*. feeding 첫 감지 → 알림, shedding → 탈피 자동 기록. **라벨 정확도 = 사용자 체감 품질**.
- **24/7 가동 보장** — 사용자 디바이스 (맥북, 자체 HW 카메라) 와 무관. 클라우드에서 들어오는 모든 모션 클립 라벨링. 카메라 사이드는 캡처만 책임지고 라벨링은 클라우드가 받음.
- **모델 개선 루프의 핵심 입력** — 자동 라벨 → 사용자 검수 → GT 누적 → 미래 fine-tuning / 평가셋 확장의 출발점. 이게 멈추면 모델 진화도 멈춤.
- **멀티테넌시 처리량** — 사용자 늘어나면 throughput 보장이 워커 책임. UNIQUE(clip_id, source) idempotency 덕에 부하 늘면 N대 가동.

### 기술 학습
- 폴링 패턴 워커를 fly.io의 always-on machine 으로 배포 (HTTP 서버 ≠ 워커 차이 학습).
- `.env` → `fly secrets` 비밀값 관리 흐름.
- `/health` HTTP endpoint 와 fly process supervision 의 관계.

## 2. 스코프

### In (이번 스펙에서 한다)
- `Dockerfile` — Python 3.12-slim + uv + `backend.vlm_worker_main` 만 (capture / API / web 제외).
- `fly.toml` — 1 region (`nrt` Tokyo), `shared-cpu-1x` 256MB, always-on (`auto_stop_machines = false`, `min_machines_running = 1`).
- `/health` HTTP endpoint — `vlm_worker_main.amain()` 안에서 worker task 와 `asyncio.gather` 로 동거 (별도 sidecar 없음).
- `fly secrets set` — 변수 6개 (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `GEMINI_API_KEY`). 선택: `VLM_POLL_INTERVAL_SEC=60`, `VLM_POLL_LIMIT`.
- spec / `next-session.md` 갱신 + commit.

### Out (이번 스펙에서 **안 한다**)
- **회귀 80.5% 진단 / 해결** — 사용자 결정으로 보류 (2026-05-07). 베타테스터한테 80% 자동 라벨 흘리면서 데이터 쌓는 게 우선. **단 production 진입 전엔 반드시 해결** — 자동 라벨이 사용자 가치의 핵심이라 80% 는 알림/하이라이트 출시 floor 미달. 별도 트랙으로 재개.
- **외부 cron 트리거** (Cloudflare Workers / GitHub Actions schedule) — fly.io native cron 은 hourly 가 최저라 베타 UX 망가짐. 비용 모니터링 후 필요시 별도 spec.
- **HA / 멀티 머신** — 베타 단계 단일 머신. UNIQUE(clip_id, source) idempotency 로 N대 가동은 향후 가능.
- **Capture worker 의 fly.io 배포** — capture 는 자체 HW 카메라로 대체 예정 (memory `project_capture_replaced_by_own_hw.md`).
- **API 서버 (`backend.main`) 의 fly.io 배포** — 현재 `api.tera-ai.uk` Cloudflare Tunnel 그대로 유지.
- **Capture / API 의 멀티 region** — petcam 사용자 한국 한정.

## 3. 완료 조건

- [x] `Dockerfile` build 통과 — `docker build -t vlm-worker .` (로컬, 이미지 178 MB).
- [x] `docker run --env-file .env vlm-worker` — 컨테이너 안에서 polling 사이클 1회 + clip 1건 inference 통과 (clip 70093109 → moving 0.9, 12:01:42 INSERT).
- [x] `vlm_worker_main` 안에 `/health` endpoint 추가 — `GET /health` → `{"ok": true, "service": "vlm-worker"}` 200. `tests/test_health.py` 4개 통과.
- [x] `fly.toml` 작성 — region `nrt`, VM `shared-cpu-1x` 256MB, `auto_stop_machines = false`, `min_machines_running = 1`, `[[http_service.checks]]` `/health` 30s.
- [x] `fly secrets set` 7개 적용 (`scripts/fly-set-secrets.sh` 일괄). `fly secrets list` 마스킹 확인.
- [x] `flyctl deploy` 통과. `fly status` healthy. 외부 `https://petcam-vlm-worker.fly.dev/health` 200.
- [x] `fly logs` 에 `vlm worker started` + 폴링 사이클 로그 60s 간격 확인.
- [x] 새 클립 1건 → 자동 라벨 INSERT — `id=809, action=moving, confidence=0.9, vlm_model=gemini-2.5-flash`. cycle `polled=1 ok=1 failed=0`.
- [x] `specs/README.md` 표 갱신 + commit.

## 4. 설계 메모

### Always-on 결정 근거
- **fly.io native cron** = scheduled machines, 최저 단위 hourly. 5분/1분 cron 불가 → 베타테스터가 "라벨 업로드 후 최대 1시간 자동 추론 안 보임" 패턴이 됨.
- **외부 cron** (GitHub Actions / Cloudflare Workers) = 가능하지만 멀티 시스템 운영 = 학습 단계 과한 복잡도.
- **비용 비교**: shared-cpu-1x 256MB always-on 약 $1.94/월 vs cron+scale-to-zero 약 $0.05/월 → 절약 폭 $2/월, 베타에 무의미.
- **결론**: always-on + 폴링 60s, 가장 작은 VM. 트래픽 늘어나면 외부 cron 트랙 별도 검토.

### `/health` 구현 위치
- **선택**: `vlm_worker_main.amain()` 안에서 worker task + FastAPI `uvicorn.Server` 두 개를 `asyncio.gather` 로 동시 가동. 같은 프로세스, 같은 이벤트 루프.
- **고려한 대안**: sidecar container (별도 프로세스) — fly.toml `[processes]` 로 가능. 단일 워커에 과한 분리.
- **이유**: 워커가 죽으면 health task 도 같이 죽어서 fly 가 재시작. 정확한 신호.

### 동시성 / Idempotency
- `UNIQUE(clip_id, source)` 제약 + RPC `fn_vlm_pending_clips` 의 `NOT EXISTS` 1차 방어 — 워커 N개 동시 가동 안전.
- 베타 단계는 1 머신만. 향후 부하 늘어 HA 필요시 `min_machines_running` 만 올리면 됨.

### Region 선택
- `nrt` (Tokyo) — 한국 사용자 대상, 가장 가까움 (~30ms RTT).
- Supabase region 도 점검 필요 (asia-northeast 같은 권역이면 OK).
- R2 는 글로벌 — 영향 없음.

### 리스크 / 미해결 질문
- **80.5% 자동 라벨 노출**: 베타테스터한테 명시 안내 필요 — "자동 라벨 신뢰도 ~80%, 검수 부탁" UI 문구 + onboarding.
- **VM 256MB OOM 우려**: Gemini SDK + supabase-py + boto3 (R2) 메모리 합 미측정. 첫 배포 후 `fly metrics` 보고 부족하면 512MB.
- **Gemini quota**: 베타 트래픽 적어 무관. AI Studio 무료 티어로 시작.
- **Cold start 시 첫 폴링 지연**: 부팅 ~10s + 의존성 import ~3s. 폴링 60s 라 무시 가능.
- **prompts SOT 위치** (follow-up): v3.5 prompts 가 `web/prompts/backups/` 에 있는데 워커도 같은 파일 read. 라벨링 웹과 SOT 공유 의도지만 docker context 에서 web/ 통째 제외하면 누락 사고 (실제 발생 — 첫 deploy 후 `PromptNotFound` 무한 루프). 중기적으로 `backend/prompts/` 같은 별도 SOT 로 이동 + 웹에서 read 하는 구조가 더 안전. 별도 spec 검토.

### `.dockerignore` SOT 충돌 (회고 — 2026-05-07)
- **사고**: `.dockerignore` 에 `web/` 통째 제외 → image 에 `web/prompts/backups/system_base.v3.5.md` 누락 → 첫 deploy 후 워커가 `PromptNotFound` 던지며 무한 실패.
- **원인**: prompts SOT 가 `web/` 안에 있는데 docker context 만 보고 제외.
- **fix**: `.dockerignore` 에 `web/*` + `!web/prompts/` (negation) + `Dockerfile` 에 `COPY web/prompts/` 추가.
- **교훈**: 디렉토리 통째 제외 전 "워커 코드가 read 하는 파일이 그 안에 없는지" grep 으로 확인. 결국 prompts SOT 분리가 더 안전 (위 follow-up).

## 5. 학습 노트

- **Dockerfile multi-stage build**: build stage 에서 `uv sync` → final stage 로 `.venv` + 코드만 복사. 이미지 크기 줄임 + build 캐시 활용. (TS 비유: `npm ci` 후 `node_modules` + `dist` 만 final 이미지에 옮기는 패턴.)
- **`uv` Docker 통합**: 공식 가이드 — `pip install uv` 한 줄. `pyproject.toml` + `uv.lock` 만 먼저 복사 → `uv sync --frozen` → 코드 복사. lock 안 바뀌면 layer 캐시 hit.
- **fly secrets vs env**: secrets 는 fly 가 암호화 저장 + 컨테이너 시작 시 ramfs 마운트 (디스크 안 남음). `fly secrets set KEY=value` 로 회전. (TS 비유: Vercel 의 Environment Variables 와 비슷, 단 회전 명령이 있음.)
- **fly.toml `[[http_service.checks]]`**: HTTP / TCP / cmd 3가지 헬스체크 중 HTTP 가 가장 정확. `interval`, `timeout`, `grace_period` (부팅 직후 첫 체크 유예) 3개 파라미터가 핵심.
- **`asyncio.gather`**: 두 coroutine (worker.run, uvicorn.Server.serve) 을 같은 loop 에 띄움. 하나 raise 하면 다른 하나 cancel — 워커 죽으면 health endpoint 도 같이 종료 → fly 재시작 트리거.
- **always-on 표현**: `auto_stop_machines = false` + `min_machines_running = 1`. fly 가 idle 자동 stop 안 하도록.
- **`.dockerignore` 와 negation pattern**: `web/` 처럼 디렉토리 통째 제외 후 `!web/prompts/` 로 일부만 살리는 패턴이 가능하지만, 디렉토리 통째 제외가 매칭되면 안의 파일 negation 이 안 먹음. 그래서 `web/*` (항목 단위) + `!web/prompts/` 가 정답. (TS 비유: `.gitignore` 와 동일 syntax.)
- **fly.io 기본 redundancy**: `[http_service]` 정의 시 처음 deploy 가 머신 2개를 띄우는 경우 있음 (regional redundancy). `flyctl scale count 1` 로 줄임. `min_machines_running = 1` 만으론 max 강제 안 됨.

## 6. 참고

- fly.io launch: https://fly.io/docs/launch/
- fly.io health checks: https://fly.io/docs/networking/health-checks/
- fly.io secrets: https://fly.io/docs/apps/secrets/
- uv + Docker: https://docs.astral.sh/uv/guides/integration/docker/
- 연관 spec: [`feature-vlm-worker-cloud.md`](feature-vlm-worker-cloud.md), [`cloud-migration-roadmap.md`](cloud-migration-roadmap.md)
- 연관 memory: `project_capture_replaced_by_own_hw.md` (capture 는 별도 트랙), `project_owner_account.md` (베타 계정 공유 패턴)
