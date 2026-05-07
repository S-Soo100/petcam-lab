# Cloud Migration Roadmap — 모놀리식 FastAPI → 분산 워커 + BaaS

> 현재 단일 FastAPI 프로세스에 묶인 capture / encode_upload / API / (예정) VLM 추론을 BaaS(Supabase) + 분산 워커 아키텍처로 전환하는 전체 로드맵 + 결정 락인.

**상태:** 🚧 진행 중
**작성:** 2026-05-07
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-backend-dev.md`
**선행 학습 자료:** [`../docs/learning/cloud-architecture-overview-learning.md`](../docs/learning/cloud-architecture-overview-learning.md)

## 1. 목적

**왜 지금 이걸 하나?**
1. **자체 HW 웹캠 도입 대비** — 캡처가 LAN 안 (맥북) 에 묶여있던 임시 제약을 영구 해소 (memory: `project_capture_replaced_by_own_hw.md`).
2. **VLM PoC → production 화** — Round 3 (`feature-poc-vlm-web.md`) 종료. v3.5 prompt 락인 + 라벨링 웹까지 만들어둔 상태에서, **자동 라벨이 모든 모션 클립에 자동으로 붙는** 흐름이 빠짐. 분산 워커로 채움.
3. **상용화 전제 조건 충족** — SOT (`petcam-backend-dev.md` L212) "카메라가 우리 클라우드로 직접 push → 같은 WiFi 제약 해제" 가 본 트랙의 종착점.

**학습 목표 (이 레포는 학습 + 실 프로덕트):** BaaS vs self-hosted, DB-as-message-bus 패턴, contract 모듈화, polling vs webhook vs cron 트리거, idempotency. 자세한 비유·대안 비교는 학습 자료 (`cloud-architecture-overview-learning.md`) 참조.

## 2. 스코프

### In (이번 트랙에서 한다)
1. **capture worker 분리** — 현재 `backend.main` lifespan 안의 `CaptureWorker` + `EncodeUploadWorker` 를 별도 프로세스로 분리. 자체 HW 등장 시 contract 만 맞추면 교체 가능한 구조.
2. **VLM worker 신규** — `camera_clips` 의 `r2_key IS NOT NULL AND has_motion = true` 행을 폴링해 추론 → `behavior_logs` (source='vlm') INSERT.
3. **Flutter 앱 라벨 통합** — 라벨 chip 표시 + 하이라이트 탭. 라벨 수정은 **여전히 라벨링 웹** 에서만.
4. **권한 모델 확정** — `labelers` 테이블 = admin/staff. 별도 `profiles.role` 안 만듦.
5. **이전·정리 — `next-session.md` 갱신, donts-audit 누적, SOT 동기화**.

### Out (이번 트랙에서 안 한다)
- Self-hosted 백엔드로 대체 (Supabase 유지 — 결정 메모 §4-1)
- HITL UI 를 Flutter 앱에 추가 (라벨링 웹이 이미 admin 도구로 존재 — 결정 메모 §4-6)
- VLM 모델 변경 (Gemini Flash 2.5 + v3.5 prompt 락인 — `next-session.md` "락인된 결정")
- Self-hosted Postgres / Auth (lock-in 분석 후 Supabase 유지)
- pg_cron / Edge Function 도입 (단순 polling 부터. 트래픽 늘면 그때 바꿈)
- 자체 HW 펌웨어 / 보드 작업 (별도 트랙)

> **스코프 변경은 합의 후에만.** Out 항목 손대고 싶으면 본 spec 수정 + 사유 기록.

## 3. 완료 조건

체크리스트가 진행 상태. 하위 spec 별로 분리 추적.

- [~] [`feature-capture-worker-extraction.md`](feature-capture-worker-extraction.md) — 코드 완료 (2026-05-07), 사용자 실기 검증 대기
- [~] [`feature-vlm-worker-cloud.md`](feature-vlm-worker-cloud.md) — 코드 완료 + 마이그레이션 적용 + 1건 inference 검증 (2026-05-07). 159건 회귀 80.5% (floor 85.5% 미달, 베타 후 별도 트랙) + 100건 비용 추적 미해결.
- [x] [`feature-vlm-worker-fly-deploy.md`](feature-vlm-worker-fly-deploy.md) — VLM 워커 fly.io 배포 + E2E 검증 완료 (2026-05-07). `petcam-vlm-worker` (nrt, shared-cpu-1x 256MB, always-on, /health). clip 70093109 → moving 0.9 INSERT 75초.
- [x] [`feature-labeling-web-cloud.md`](feature-labeling-web-cloud.md) — 라벨링 웹 백엔드 분리 (2026-05-07). `label.tera-ai.uk` 의 영상/라벨/추론/메타 4 endpoint 를 Vercel→Supabase/R2 직결로 이식. owner PoC 흐름이 맥북 의존 0. clip 3b0d9995 실기 검증 통과 (영상 재생 + VLM 추론 표시).
- [ ] [`flutter-cloud-handoff.md`](flutter-cloud-handoff.md) — Flutter 측 PR merge (백엔드 contract freeze 완료, VLM 워커 가동 시작 → Flutter 작업 시작 가능)
- [ ] SOT (`tera-ai-product-master/docs/specs/petcam-backend-dev.md`) 동기화 — "캡처 분리 / VLM worker fly.io / 라벨링 웹 Vercel 직결 / labelers 화이트리스트=admin role" 반영
- [x] `docs/ARCHITECTURE.md` 업데이트 — 분산 워커 다이어그램 (B1 트랙 코드 완료 시 갱신, 2026-05-07) + 라벨링 웹 Vercel 직결 흐름 (2026-05-07)
- [x] `docs/DEPLOYMENT.md` 업데이트 — fly.io VLM 워커 배포 섹션 (2026-05-07) + 라벨링 웹 백엔드 의존 표 (2026-05-07)
- [ ] 본 spec 상태 ✅ + `specs/README.md` 표 갱신 (Flutter 트랙 완료 후)

## 4. 설계 메모 — 락인된 결정

순서대로 락인. 새 세션에서 재논의 금지 (override 시 사용자 명시 필요).

### §4-1. Supabase 유지 (2026-05-07)

**결정:** 비용·성장 우려에도 Supabase 를 central management hub 로 유지.

**검토:** 사용자 질문 "비용 들 거면 자체 서버가 낫지 않아?" → Auth/Postgres/RLS/대시보드 한 묶음 self-hosted 면 운영 부담 폭증. 1만 유저 도달 시점에야 비용 변곡점이라 그때 다시 검토.

**How to apply:** Auth + DB 메타 + RLS 는 Supabase. 영상 바이트는 R2 (Supabase Storage 안 씀 — egress 비쌈). VLM/캡처 처럼 무거운 처리는 별도 워커.

### §4-2. R2 직접 접근 (2026-05-07)

**결정:** VLM worker / Flutter 앱이 R2 에 직접 GET (signed URL). Supabase 우회.

**검토:** Supabase Storage 거치면 (a) 추가 hop = latency (b) Supabase egress 과금 = 비용 (c) lock-in 심화. R2 는 Cloudflare egress free.

**How to apply:** Flutter 영상 재생 = Edge Function `get_signed_clip_url` → R2 presigned URL. 백엔드 `/clips/{id}/file` redirect 도 같은 패턴 (이미 구현, `feature-r2-storage-encoding-labeling.md`).

### §4-3. capture worker 모듈식 분리 (2026-05-07)

**결정:** capture + encode_upload 를 별도 service 로 분리. **자체 HW 등장 시 capture 부분만 교체** 가능한 contract.

**검토:** 자체 HW = "카메라가 클라우드에 직접 push" (SOT L212). 즉 RTSP pull → push 모델 전환. 그 시점 encode_upload 도 카메라가 함. 그러나 **DB INSERT (camera_clips row + r2_key)** 는 클라우드 백엔드 책임. 따라서 contract 경계는 **R2 업로드 직후 → DB INSERT 호출 직전** 이 자연스러움.

**How to apply:**
- 현재 코드 `clip_recorder.make_clip_recorder` 시그니처 = contract 의 자연 경계.
- 자체 HW 가 와도 같은 payload 를 HTTP POST /internal/clips 같은 식으로 호출.
- capture.py 자체엔 큰 추상화 투자 X (어차피 대체될 코드 — memory `project_capture_replaced_by_own_hw.md`).

### §4-4. DB-as-message-bus (camera_clips status) (2026-05-07)

**결정:** 워커 간 통신은 별도 message broker (Redis/SQS) 안 씀. `camera_clips` 의 컬럼 자체가 큐.

**검토:** 도입 비용 0, 새 인프라 0. 폴링 비용 < broker 운영 비용 (현재 트래픽 기준). 트래픽 변곡점 (>10 req/s) 도달 시 webhook + Edge Function 으로 전환 검토.

**How to apply:**
- VLM worker = `WHERE has_motion = true AND r2_key IS NOT NULL AND NOT EXISTS (behavior_logs WHERE clip_id=... AND source='vlm')` 폴링.
- 폴링 주기 30초 (라벨러 큐 페이지의 SLA 기준).
- 결과 INSERT 는 idempotent — UNIQUE (clip_id, source) on behavior_logs (마이그레이션 필요, §VLM spec 참조).

### §4-5. labelers = admin/staff role (2026-05-07)

**결정:** `labelers` 테이블 (화이트리스트) 가 사실상 admin/staff role. 별도 `profiles.role` enum 안 만듦.

**검토:** 이미 존재. 사용자 의도 "라벨 수정은 관리자/스태프만" 과 정확히 일치 — labelers 멤버 = (clip 소유 무관) 모든 클립 라벨 가능. 비-멤버 = 본인 클립만 (RLS).

**How to apply:**
- Flutter `currentUserIsLabeler` provider — Supabase RPC `is_labeler(uid)` 또는 Edge Function `/me/role` 호출.
- 라벨 수정 UI 는 Flutter 에 안 만듦 (라벨링 웹이 담당, §4-6).
- "관리자 전용 진입점" 으로 라벨링 웹 deep link 만 Flutter 에 둠 (선택).

### §4-6. 라벨링 = 두 클라이언트 분리 (2026-05-07)

**결정:** Flutter 앱은 **라벨 표시 + 하이라이트 필터** 만. 라벨 수정/생성 UI 는 라벨링 웹 (`label.tera-ai.uk`) 만.

**검토:** 라벨링 웹은 이미 모바일/PC 동작 + admin 워크플로우. Flutter 에 같은 UI 또 만드는 건 중복. 일반 유저는 라벨 수정 권한 없으므로 Flutter UI 자체가 불필요.

**How to apply:**
- Flutter clip 상세 = chip 표시 only (수정 버튼 X).
- 사용자 본인이 labeler 라도 Flutter 안에선 수정 못 함. 라벨링 웹으로 가야 함.
- 일반 유저용 HITL ping 은 별도 (`feature-vlm-hitl-ping.md`, 미착수). 이번 트랙 Out.

### §4-7. 하이라이트 정의 (2026-05-07)

**결정:** "하이라이트" = `behavior_labels.action ∉ ('moving', 'unknown')` 인 클립.

**검토:** 사용자 표현 "지금 녹화하는 '움직임 감지' 자체가 모두 다 하이라이트야! 그중에서 무빙 말고 음식먹거나 똥싸거나 이상행동이나 이것들을 하이라이트라고 부를거임" → "녹화 = 모션 = 후보, 행동 라벨 붙은 것 = 진짜 하이라이트".

**How to apply:**
- Flutter "하이라이트" 탭 쿼리 = `clips JOIN behavior_logs ON clip_id WHERE source='vlm' AND action NOT IN ('moving', 'unknown')`.
- 검증된 (human override 된) 라벨이 있으면 그게 우선 — 우선순위 스코어링 별도 결정 필요 (§db-and-contracts spec).
- 카운트는 일/주/월 단위로 집계 (KPI 지표).

### §4-8. VLM 결과 저장 = behavior_logs (source='vlm') (2026-05-07)

**결정:** VLM 추론 결과는 `behavior_logs` 테이블 (이미 존재). human 라벨은 별도 `behavior_labels` 테이블 유지.

**검토:** 두 테이블 분리 = 출처 명확 + 학습셋 추출 쉬움. 같은 테이블 + `model` 컬럼 패턴도 가능했지만, 이미 `behavior_logs` 가 라벨링 웹의 검수 화면 (`/clips/{id}/inference`) 에서 source='vlm' 로 사용 중 — 깨면 회귀.

**How to apply:**
- VLM worker = `behavior_logs` INSERT (clip_id, source='vlm', action, confidence, vlm_model, reasoning, created_at).
- Flutter 라벨 표시 = behavior_logs 최신 source='vlm' + behavior_labels 우선순위 머지 (UI 레이어).
- UNIQUE (clip_id, source) 추가 검토 — 같은 source 중복 INSERT 시 마지막 값 유지 (UPSERT).

## 5. 학습 노트

새 패턴 / 라이브러리 / 개념 — 사용자가 처음 접하는 것들.

- **DB-as-message-bus** — 별도 큐 없이 컬럼 (`status`, `r2_key IS NULL`, etc.) 자체가 작업 상태. JS 비유: Postgres 가 곧 BullMQ. 단점: 폴링 비용. 장점: 트랜잭션 / RLS / 운영성 한 번에. → 학습 자료 §3.
- **idempotency** — 같은 input 으로 여러 번 호출돼도 결과 동일. UNIQUE 제약 + UPSERT 패턴이 보호막. 분산 워커는 항상 idempotent 가정. → 학습 자료 §4.
- **contract 모듈화** — 폴더 분리 (code modularity) 가 아니라 **interface (입력/출력 시그니처)** 가 안정적이면 모듈식. capture worker 의 contract = `clip_recorder(payload)` 호출 경계. → 학습 자료 §6.
- **signed URL** — 클라이언트가 객체 스토리지 (R2/S3) 에 직접 접근하되 서버가 발급한 시간제한 URL 만 유효. 영상은 백엔드 거치지 않고 직접 GET. JS 비유: AWS SDK `getSignedUrl`. → `r2_uploader.generate_signed_url`.
- **lifespan vs startup event** — FastAPI 0.93+ 권장. 컨텍스트 매니저 (`@asynccontextmanager`) 라 정확한 cleanup 보장. Node 비유: `server.listen` + `process.on('SIGTERM')` 통합. → `backend/main.py:139`.

## 6. 참고

- SOT: [`../../tera-ai-product-master/docs/specs/petcam-backend-dev.md`](../../tera-ai-product-master/docs/specs/petcam-backend-dev.md) §165, §212 (자체 HW 트랙)
- 학습 자료: [`../docs/learning/cloud-architecture-overview-learning.md`](../docs/learning/cloud-architecture-overview-learning.md) — 7개 토픽 + TS/JS 비유
- 하위 spec: [`feature-capture-worker-extraction.md`](feature-capture-worker-extraction.md), [`feature-vlm-worker-cloud.md`](feature-vlm-worker-cloud.md), [`feature-vlm-worker-fly-deploy.md`](feature-vlm-worker-fly-deploy.md), [`feature-labeling-web-cloud.md`](feature-labeling-web-cloud.md), [`flutter-cloud-handoff.md`](flutter-cloud-handoff.md)
- 관련 메모리: `project_capture_replaced_by_own_hw.md`, `project_owner_account.md`
- 락인 (재논의 금지): VLM v3.5 floor 85.5% (`next-session.md` "락인된 결정")
