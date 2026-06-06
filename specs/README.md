# specs/ — Lightweight Spec-Driven Development

> "내일의 나/사용자가 '왜 이렇게 했지?' 물을 확률이 높으면 스펙을 쓴다. 아니면 그냥 한다."

## 이 폴더의 역할

개발 작업의 **의사결정 기록**과 **진행 상태**를 한 파일에 모아둔다. 체크리스트가 status, 설계 메모가 ADR, 학습 노트가 개인 위키 역할.

**연관:**
- 상위 **기획 스펙**(무엇/왜)은 `tera-ai-product-master/docs/specs/`
- 여기 **개발 스펙**(어떻게)은 그걸 받아서 구현 관점으로 구체화

## 스펙 쓸지 말지 판단

### ✅ 쓴다
- 스테이지 단위 작업 (Stage A~E)
- 3일 이상 걸릴 기능
- 설계 결정이 필요한 작업 (라이브러리 선택, 아키텍처 선택 등)
- 여러 스크립트·모듈이 묶이는 실험
- 버그가 아키텍처 이슈로 번진 대형 수정

### ❌ 안 쓴다
- 단발 버그 수정 (1~2시간 이내)
- 순수 리팩토링 (동작 동일)
- 의존성 업데이트
- 오타/문서 수정
- 스크립트 한두 줄 추가

### 애매하면?
**판단 기준 한 줄**: "내일의 나/사용자가 '왜 이렇게 했지?' 물을 확률이 높으면 쓴다."

## 작업 흐름

1. **작업 시작 전** — 관련 스펙 있는지 확인 → 있으면 읽고 완료 조건 체크.
2. **스펙 없는데 필요** — `_template.md` 복사 → `specs/{주제}.md`로 저장 → **스코프/완료 조건만 먼저 채우고** 사용자 확인.
3. **작업 중** — 설계 결정 생기면 "설계 메모" 섹션에 추가. 새 개념 쓰면 "학습 노트"에.
4. **작업 완료** — 모든 체크박스 ✅ → 상태 `✅ 완료`로 변경 → 스펙에 마지막 요약 한 줄.
5. **중단/폐기** — `⏸️ 보류` 또는 `🗑️ 폐기` + 사유 한 줄.

## 네이밍

- 형식: `{stage/feature}-{kebab-case}.md`
- 스테이지: `stage-a-streaming.md`, `stage-b-motion-detect.md`
- 기능: `feature-clip-retention.md`, `feature-supabase-auth.md`
- 실험: `experiment-rtsp-codec-compare.md`

## 상태 표기

| 기호 | 의미 |
|------|------|
| 🚧 | 진행 중 |
| ✅ | 완료 (완료 조건 전부 체크) |
| ⏸️ | 보류 (재개 가능, 사유 기록) |
| 🗑️ | 폐기 (다시 안 할 것, 사유 기록) |
| 🔄 | 자매 레포 (`petcam-rba-worker`) 에 미러됨, 양쪽 sync 필요 |

## 원칙

1. **체크리스트가 진행 상태** — 별도 칸반/status 파일 만들지 말 것.
2. **완료 조건은 검증 가능하게** — "잘 작동한다"가 아니라 "`pytest tests/test_foo.py` 통과" 같은 구체 기준.
3. **Out 섹션이 핵심** — 뭘 안 할지 명시하지 않으면 스코프가 뭉개진다.
4. **학습 노트는 나중의 나를 위한 것** — 작성 시점엔 귀찮지만 3개월 뒤 효자.
5. **폐기도 기록** — 실패·보류한 스펙도 남긴다. 왜 안 했는지가 미래의 의사결정에 도움.

## 🔖 다음 세션 시작 지점

**[→ next-session.md](next-session.md)** — 새 Claude 가 "뭐부터 해야해?" 질문 받으면 **이 파일부터 읽는다**. 매 세션 마지막에 갱신.

## 현재 스펙 목록

<!-- 스펙 추가 시 이 표를 업데이트 -->

| 상태 | 파일 | 한 줄 |
|------|------|------|
| ✅ | [stage-a-streaming.md](stage-a-streaming.md) | RTSP 스트리밍 + 서버 파일 저장 MVP (완료 2026-04-20) |
| ✅ | [stage-b-motion-detect.md](stage-b-motion-detect.md) | 움직임 감지 + 세그먼트 `_motion`/`_idle` 태그 (완료 2026-04-20) |
| ✅ | [stage-c-db-api.md](stage-c-db-api.md) | Supabase `camera_clips` + 조회 API 3종 (완료 2026-04-21) |
| ✅ | [stage-d-roadmap.md](stage-d-roadmap.md) | Stage D 전체 로드맵 + 결정 기록 (완료 2026-04-22). ⚠️ 결정 1 (Cloudflare Tunnel) 은 2026-05-08 fly.io edge 이전으로 무효화 — feature-api-server-fly-deploy 참조 |
| ✅ | [stage-d1-auth-crypto.md](stage-d1-auth-crypto.md) | JWT 검증 `Depends` + Fernet 비번 암호화 인프라 (완료 2026-04-22) |
| ✅ | [stage-d2-cameras-api.md](stage-d2-cameras-api.md) | `cameras` 테이블 + CRUD API 6종 + RTSP 테스트 연결 (완료 2026-04-22) |
| ✅ | [stage-d3-multi-capture.md](stage-d3-multi-capture.md) | 다중 캡처 워커 + `camera_clips.camera_id` UUID FK 마이그레이션 (완료 2026-04-22) |
| ✅ | [stage-d4-thumbnail.md](stage-d4-thumbnail.md) | 썸네일 파이프라인 — `thumbnail_path` 컬럼 + 캡처 워커 jpg 저장 + `GET /clips/{id}/thumbnail` (완료 2026-04-22) |
| ✅ | [stage-d5-deploy-tunnel.md](stage-d5-deploy-tunnel.md) | Cloudflare Tunnel (Named) `api.tera-ai.uk` + AUTH_MODE=prod + Flutter E2E (완료 2026-04-22) |
| ✅ | [feature-clip-mirrors-for-qa.md](feature-clip-mirrors-for-qa.md) | QA 테스터 계정용 `clip_mirrors` 미러링 인프라 — live + flush 양쪽 훅 (완료 2026-04-22) |
| ✅ | [feature-docs-refresh.md](feature-docs-refresh.md) | 문서 리프레시 — README 슬림 + `docs/` 공식 문서 10개 + `AGENTS.md` + `docs/learning/` 분리 (완료 2026-04-22) |
| ✅ | [feature-poc-vlm-web.md](feature-poc-vlm-web.md) | **v3.5 85.5% production 확정** (Round 3, 2026-04-30). baseline 깨기 시도 6회 모두 퇴행/동률 (v3.6/v3.7-B/v4 + Track B/C/D/E + dish-postfilter). 잔존 오답은 시각 한계로 결론 — 다음은 UX 통합·HITL 정공법 |
| ✅ | [feature-vlm-feeding-merge-ux.md](feature-vlm-feeding-merge-ux.md) | **완료 2026-05-02** — UI 매핑 통합 (drinking+paste→feeding 표시 레이어). types.ts toFeedingMerged() + UI_BEHAVIOR_CLASSES, F3 결과 매핑, 평가 매핑 동치 9/9, tsc 통과 |
| 🚧 | [feature-vlm-hitl-ping.md](feature-vlm-hitl-ping.md) | **신규 2026-05-02** — HITL ping 큐 (defecating/shedding/eating_prey 모호 케이스 사용자 검수). 일일 5건 + opt-in. confidence<0.7 또는 confusion-prone 클래스 트리거 |
| 🚧 | [feature-rba-evidence-based-feeding-drinking.md](feature-rba-evidence-based-feeding-drinking.md) | **신규 2026-06-02** — eating/drinking 직접 단정 대신 ROI 체류 + before/after 상태 변화 + 표면 핥기 증거를 `visit/candidate/inferred/confirmed` event 로 저장하는 RBA 증거 기반 섭식/음수 판단 레이어 구현 계획 |
| 🚧 | [experiment-claude-subscription-rba.md](experiment-claude-subscription-rba.md) | **신규 2026-06-02** — evidence 스펙 검증용 **저비용 트랙**. Gemini API 대신 Max 구독(Claude Code/Cowork)을 analyzer 로 써서 증거 기반 판단법을 증분비용 $0 로 sample 검증. 진짜 새로움은 'analyzer 과금 모델' 하나 — 전처리는 SegmentVLM 재사용. 검증 대상=방법론(모델 일반화 X), 재현성 함정 측정 포함. 실행은 petcam-rba-worker 영역(sync 검토) |
| 🗑️ | [feature-vlm-feeding-postfilter.md](feature-vlm-feeding-postfilter.md) | **폐기 2026-05-02** — dish-presence binary 라우터 154건 84.42% FAIL (floor 85.7%). broken=0/recovered=2/still-wrong=24. 평가셋 A환경에서 dish_present 시그널 무효화 + binary 라우터도 같은 시각 한계 |
| ✅ | [feature-r2-storage-encoding-labeling.md](feature-r2-storage-encoding-labeling.md) | **완료 2026-05-15** — R2 인프라/인코딩/업로드/Label API/라벨링 웹 (`label.tera-ai.uk`) Vercel 배포 + Cloudflare DNS + 라벨러 부트스트랩 SQL + 가동 검증. NULL camera_id 88건 PoC 클립 backfill 결정만 별도로 이관 |
| 🚧 | [feature-labeling-management.md](feature-labeling-management.md) | **2026-05-04 코드 완료, 사용자 검증 대기** — 백엔드: queue has_motion/r2 필터 + `/labels/mine` + `/clips/{id}/inference` (33 tests). 프론트: `/labeling/me` 회고 페이지 + 헤더 탭 + 단건 페이지에 owner 검수 섹션 (VLM 추론 + 다른 라벨러 + override 모달) + r2 없음 안내 + 폼 disable. 남은 작업: 백엔드 재시작 + 사용자 브라우저 검증 |
| 🚧 | [cloud-migration-roadmap.md](cloud-migration-roadmap.md) | **신규 2026-05-07** — 모놀리식 FastAPI → 분산 워커 + BaaS 트랙 상위 spec. 결정 락인 8개 (Supabase 유지, R2 직접, capture 분리, DB-as-message-bus, labelers=admin, 하이라이트=행동 라벨, behavior_logs source='vlm') |
| 🚧 | [feature-capture-worker-extraction.md](feature-capture-worker-extraction.md) | **2026-05-07 코드 완료, 실기 검증 대기** — capture/encode 를 `backend.capture_main` standalone 으로 분리. main.py 슬림화 + /streams 엔드포인트 삭제 + 224 tests 통과 + DEPLOYMENT/ARCHITECTURE 갱신 |
| 🚧 | [feature-vlm-worker-cloud.md](feature-vlm-worker-cloud.md) | **2026-05-07 1건 검증 완료, 회귀/배포 대기** — UNIQUE + RPC `fn_vlm_pending_clips` 마이그레이션 적용 (Supabase MCP) + worker.py RPC 전환 + 235/235 통과. 폴링 버그 (2-step client diff cutoff) → RPC NOT EXISTS 로 수정. 1건 inference: clip 70093109 → action=moving 0.90 (GT 일치). 남은 작업: 159건 회귀 + 100건 비용 + fly.io |
| 🚧 | [flutter-cloud-handoff.md](flutter-cloud-handoff.md) | **신규 2026-05-07** — Flutter 측 작업서 (cross-repo). 라벨 chip + 하이라이트 탭 + R2 signed URL. 라벨 수정 UI 는 라벨링 웹이 담당, Flutter 안 만듦 |
| ✅ | [feature-vlm-worker-fly-deploy.md](feature-vlm-worker-fly-deploy.md) | **완료 2026-05-07** — VLM 워커 fly.io 배포 (`petcam-vlm-worker`, nrt, shared-cpu-1x 256MB, always-on, /health). E2E 검증: clip 70093109 → action=moving 0.9 INSERT (75초). `.dockerignore` web/* + !web/prompts/ negation 으로 prompts SOT 공유 |
| ✅ | [feature-labeling-web-cloud.md](feature-labeling-web-cloud.md) | **완료 2026-05-07** — `label.tera-ai.uk` 영상/라벨/추론/메타 4 endpoint 를 Vercel→Supabase/R2 직결로 이식. owner PoC 흐름 맥북 의존 0. 신규: `web/src/lib/{r2.ts:presignGet, clipPerms.ts}` + `/api/clips/[id]/{file/url, labels, inference}` route. 실기 검증: clip 3b0d9995 영상 + VLM shedding conf 1.00 표시 |
| ✅ | [feature-api-server-fly-deploy.md](feature-api-server-fly-deploy.md) | **완료 2026-05-08** — `api.tera-ai.uk` 가 사용자 맥북 Cloudflare Tunnel → fly.io `petcam-api` (nrt, shared-cpu-1x 256MB, always-on) 직결로 이전. Let's Encrypt cert (E8, 2026-08-06) 자동 발급. Phase 1 endpoint 2개 (`/me/is_labeler`, `/clips/highlights`) 추가 (commit `b458bb0`, pytest 247). Phase 2 staging `ba01060`. Phase 3 DNS cutover (Tunnel CNAME 삭제 → A/AAAA DNS only, 30s 안에 cert Issued, HTTP 200 from 66.241.124.67). 사용자 맥북 의존 0. |
| 🗑️ | [experiment-tracking-vlm-input.md](experiment-tracking-vlm-input.md) | **폐기 2026-05-14** — Step 1.5 게이트 FAIL. 검출 47.5% 실패 + 트래킹 drift 28.6% 양쪽 보틀넥. 4분기 매트릭스 (α) 분기. 시각 한계 가설 (A) 6번째 강화 (v3.5 lock-in + dish-postfilter + 6방향 prompt 변경 + 본 PoC). Step 2/3 미실행. 다음 전략 별도 탐색 |
| 🚧 🔄 | [experiment-event-segment-vlm.md](experiment-event-segment-vlm.md) | **RBA Track B / 신규 2026-05-16** — 1~4분 영상을 motion/ROI 기반 5~15초 event로 쪼개고 event별 VLM 분석 후 clip-level timeline으로 병합하는 사이드 플랜. production 변경 없이 RBA Track A baseline(60초 top-1) 대비 P0 recall, false highlight, HITL review 효율, 비용/latency 비교. **🔄 2026-05-27 [`../petcam-rba-worker`](../../petcam-rba-worker/specs/experiment-event-segment-vlm.md) 로 미러됨 — Mac mini worker 작업 진행은 그쪽 갱신** |
| 🚧 🔄 | [experiment-mac-mini-segmentvlm-worker.md](experiment-mac-mini-segmentvlm-worker.md) | **신규 2026-05-16** — 맥미니를 outbound polling 기반 SegmentVLM 로컬 worker 로 써서 Claude CLI / Codex CLI / local VLM fallback 분석을 수행하는 사이드 플랜. fly.io `petcam-vlm-worker` 는 Gemini baseline 으로 유지. **🔄 2026-05-27 [`../petcam-rba-worker`](../../petcam-rba-worker/specs/experiment-mac-mini-segmentvlm-worker.md) 로 미러됨 — Mac mini worker 작업 진행은 그쪽 갱신** |
| 🚧 🔄 | [feature-mac-mini-local-track-a-worker.md](feature-mac-mini-local-track-a-worker.md) | **신규 2026-05-26** — Mac mini M1 16GB/256GB 를 Gemini Track A 대체 후보인 local RBA worker 로 세팅. 60초 motion clip → contact sheet → local VLM label JSON → Gemini/GT 비교 후 fallback 정책 결정. **🔄 2026-05-27 [`../petcam-rba-worker`](../../petcam-rba-worker/specs/feature-mac-mini-local-track-a-worker.md) 로 미러됨 — Mac mini worker 작업 진행은 그쪽 갱신** |
| 🚧 🔄 | [feature-hand-feeding-ood-label.md](feature-hand-feeding-ood-label.md) | **신규 2026-06-06** — rba-worker HITL 핸드오버 반영. `hand_feeding` OOD 라벨(사람/도구 개입) 추가로 P0 학습 오염 차단 — types/prompts/labelingApi/labeling-UI 5곳 전파(C-1) + 라벨링 OOD UX(C-2) + v3.6 후보 프롬프트(OOD 룰만, v3.5 락인 보존+회귀평가, C-3) + GT 정정 6건 sync 검토. 보고서 가정 vs 실제 차이 6건 기록(정의 정밀화 4개는 이미 v3.5에 있어 제외, event-level은 Phase B Out) |
