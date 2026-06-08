# 다음 세션 시작 지점

> 매 세션 마지막에 갱신. 다음 세션 초입에 먼저 읽는다.
> **최종 갱신:** 2026-06-08 (Opus 4.8) — **Claude 트랙 203 평가 + v3.6.1 OOD 초안 + dataset-203.** eval-0608 44건 등록 + 평가셋 159 동결→**203 통합** + Claude 153건 blind(v3.6 71.2%→**v3.6.1 72.5%**, contact sheet 적합도맵) + **GT 오류 9건 정정(blind=라벨QA)** + dataset-203 구축. 커밋 `8fca779`·`1af0eff`·`de2de48`·`6b7d1c4` push. **⚠️ Gemini key 여전히 차단 — v3.6.1 정량 + production 승격의 블로커.** 사용자: **v3.5 영구폐기 결정**(앞으로 v3.6+) + **YOLO 이벤트단서 검출 계획**. **다음 = key 확보→v3.6.1 정량 / YOLO 스펙화 / `5936`·`5cfe1d48` GT 재검토.** (이전 2026-06-07: hand_feeding OOD 라벨; 2026-05-08: API fly.io cutover)

## 🆕 2026-06-08 — Claude 트랙 203 평가 + v3.6.1 OOD 초안 + dataset-203 + YOLO 계획

**완료 (커밋 `8fca779`·`1af0eff`·`de2de48`·`6b7d1c4`, push):**
- **eval-0608 44건 신규 evidence셋** R2(`clips/eval-0608/`)+DB 등록 + **평가셋 159 동결 → 203 통합** (사용자 결정). `load_eval_set`=203 / `load_eval_set_0608`=44, 159=203−44 복원가능. (메모리 `project_eval0608_evidence_set`)
- **Claude 구독 트랙 203 적합 153건 blind 평가** (contact sheet, GT 미공개 서브에이전트). 미세행동 50건은 contact sheet 불가로 제외:
  - **적합도 맵**: moving 91%·hand_feeding 88% 가능 / drinking 35%·eating_prey 40%·eating_paste 61% 미세접촉 한계 / shedding(6x6 3회로도 20%)·defecating(0%)·hiding·unseen 완전불가 → **Gemini 영상 필요 영역 확정**.
  - raw v3.6 71.2% → **v3.6.1 72.5%** (과발동 수정 −6 / recall 손실 +4 상쇄). (메모리 `project_contact_sheet_adequacy_v361`)
- **GT 오류 9건 정정 (blind=라벨 QA)**: `2961`(hf→paste) + 159건 8건(eating_prey/paste→hf, 사람이 핀셋/시린지/스푼 급여하는 영상인데 v3.5 시절 라벨). 8장 육안 교차검증 후 정정.
- **v3.6.1 OOD 룰 초안** (`web/prompts/backups/system_base.v3.6.1.md`, `prompt_version="v3.6.1"` 격리, v3.6 무손상): OOD "손/도구 보이면 hf" → **"음식 전달 행위"로 좁힘**. 정성 11건 과발동 5/5 수정 + recall 6/6 유지. **⚠️ 채택 절대 보류 — 회귀(Gemini) 없이 `DEFAULT_PROMPT_VERSION` 승격 X.**
- **dataset-203** `storage/dataset-203/` (gitignore, 로컬 2.2GB): 203건을 `{GT}__{Claude v3.6.1}__{clip8}.{ext}` + `manifest.csv`. 파일명만으로 GT vs Claude 일치/불일치 검수. 중복 영상 142개 휴지통.

**⚠️ 여전히 차단 — Gemini key:** v3.6.1 정량 + production 승격의 **단일 블로커**. AQ. prefix 계정 플래그(`feedback_gemini_aq_key_account_flag`). 표준 AIza key 확보 후: `eval_vlm_v36_handfeeding`에 `prompt_version` 분기 추가 → 203으로 **v3.5/v3.6/v3.6.1 정량 비교** (P0 floor + OOD recall + 과발동 감소).

**사용자 방향 (2026-06-08):**
- **v3.5 영구 폐기 결정** — hand_feeding 필요하니 앞으로 **v3.6+**(hand_feeding 포함). 단 DEFAULT 승격은 Gemini 회귀 통과 후. v3.5가 세운 floor(P0 85.5%)는 **품질 바닥선으로 유효**(프롬프트는 버리되 기준은 유지).
- **YOLO 계획 (재정의)**: "moving 거르기"가 아니라 **YOLO = 이벤트 단서 객체 검출(그릇/손/도구/prey/허물) → VLM 라우팅 + evidence**. 효과 = 비용절감(moving 31% 스킵, 확실) + 정확도(evidence-aug, 간접). 미세행동 병목은 YOLO 밖(영상 시간축/Gemini full/HITL). **dataset-203이 게코 fine-tune YOLO 학습 데이터로 적합**(OWLv2 47.5% 검출실패 교훈). → `project_yolo_evidence_layer_status` 메모리 + `docs/AI-VIDEO-ANALYSIS-STRATEGY.md`.

**팔로업:** `5936`·`5cfe1d48` GT 재검토(성급한 hf 정정 의심 — manifest도 갱신) / Gemini key 확보 → v3.6.1 정량 / YOLO 트랙 스펙화.

**상세:** `experiment-claude-subscription-rba.md` · `experiments/eval-159-claude/REPORT.md`

---

## 🆕 hand_feeding OOD 트랙 + YOLO 다음 트랙 (2026-06-07)

**완료 (커밋 `676dfd4` + `0e1f7bc`, push):**
- C-1 hand_feeding 라벨 5곳 (types.ts / labelingApi.ts / labeling page / prompts.py / labels.py) — tsc 0, pytest 64
- C-2 라벨링 OOD 안내 UX (코드 완료, **브라우저 검증 대기**)
- C-3 v3.6 후보 프롬프트 + `build_system_prompt(species, *, prompt_version)` 버전 격리 (v3.5 production 9-class 보존, v3.6=10-class)
- GT 정정 6건 Supabase `behavior_logs(human)` sync (5→hand_feeding, 1→moving) + audit
- 159건 오답 진단 (`scripts/diagnose_vlm_errors.py`): feeding-merged 81.8% (GT sync로 6건 오답 재분류된 효과 — **v3.5 저하 아님**), 최대 혼동 moving↔feeding 13건

**⚠️ 차단됨 — key 확보 후 즉시:**
- v3.6 회귀평가: Gemini **AQ. prefix key 계정 플래그**로 막힘 (크레딧 소진 아님). 다른 Google 계정 AIza key or Google manual review. 재개: `rm /tmp/vlm-regression-v36.jsonl && PYTHONPATH=. uv run python scripts/eval_vlm_v36_handfeeding.py`. **fly worker key도 점검** (같은 플래그 계정이면 production VLM도 멈춤).

**진단이 준 다음 전략:**
- defecating(69%) / eating_paste(5건) / drinking = **영상 추가 가치** / 그릇↔먹기 혼동 = **시각 한계**(영상 무의미, ROI/UX/YOLO로) / hand_feeding = **v3.6가 풀 듯**(Gemini reasoning에 도구 이미 인지)

**YOLO evidence layer = 다음 트랙 (사용자 트리거 대기):**
- 사용자가 ①운영환경 게코 영상 ②게코 frame ③YOLO 공부 진행 후 **"YOLO 하자"로 트리거**. 그때 `specs/experiment-yolo-evidence-layer.md` 스펙 → **Phase 3(pretrained 검출 한계 확인) 먼저**, custom(Phase 4-5)은 나중. 실행은 rba-worker 영역 검토. 로드맵: `docs/learning/yolo-video-analysis-study-plan.md`. **YOLO = 좌표·시간 evidence 생성**(행동 판단 X). OWLv2 47.5% 검출 실패 교훈(`experiment-tracking-vlm-input.md` 폐기).

**팔로업:** C-2 브라우저 검증 / rba-worker `BEHAVIOR_CLASSES` cherry-pick(10-class sync) / `feature-vlm-worker-cloud` 회귀 재측정(아래 80.5%는 GT sync 전 수치) / 스펙: `feature-hand-feeding-ood-label.md`

---

## 🆕 Cloud Migration 트랙 시작 (2026-05-07)

사용자 명시 — 기존 모놀리식 FastAPI 를 분산 워커 + BaaS 패턴으로 전환. spec 4개 작성 완료, 코드 작업 시작 대기.

| 영역 | 상태 | 위치 |
|---|---|---|
| 상위 로드맵 + 결정 락인 8개 | ✅ spec 작성 | [`cloud-migration-roadmap.md`](cloud-migration-roadmap.md) |
| capture worker 분리 (`backend.main` lifespan → 별도 entrypoint) | 🚧 **코드 완료, 실기 검증 대기** (2026-05-07) | [`feature-capture-worker-extraction.md`](feature-capture-worker-extraction.md) |
| VLM worker production (PoC → 자동 폴링) | 🚧 **1건 검증 완료, 회귀 미해결** (2026-05-07) — UNIQUE+RPC 마이그레이션 + 1건 inference (moving 0.90, GT 일치). 159건 회귀 80.5% (floor 85.5% 미달) — production 진입 전 해결 필수. | [`feature-vlm-worker-cloud.md`](feature-vlm-worker-cloud.md) |
| VLM worker fly.io 배포 (always-on 클라우드) | ✅ **완료 2026-05-07 (후속)** — `petcam-vlm-worker` nrt, shared-cpu-1x 256MB. E2E 검증 완료. `.dockerignore` web prompts SOT 충돌 회고 기록. | [`feature-vlm-worker-fly-deploy.md`](feature-vlm-worker-fly-deploy.md) |
| 라벨링 웹 백엔드 분리 (Vercel→Supabase/R2 직결) | ✅ **완료 2026-05-07 (후속2)** — owner 검수 4 endpoint Vercel 직결. `label.tera-ai.uk` 맥북 의존 0. clip 3b0d9995 실기 검증. | [`feature-labeling-web-cloud.md`](feature-labeling-web-cloud.md) |
| API 서버 fly.io 이전 + Flutter contract endpoint 2개 | ✅ **완료 2026-05-08 — Phase 1+2+3+4 모두 종료.** `api.tera-ai.uk` 가 fly.io edge (66.241.124.67) 직결 + Let's Encrypt E8 cert (2026-08-06). 사용자 맥북 의존 0 (capture_main 제외). DEPLOYMENT.md / ARCHITECTURE.md 갱신 완료. | [`feature-api-server-fly-deploy.md`](feature-api-server-fly-deploy.md) |
| Flutter 라벨 chip + 하이라이트 탭 + R2 signed URL | 🚧 **백엔드 측 endpoint 채움 완료 2026-05-08** — Flutter 측 작업 대기. Flutter 측 새 세션에 `docs/handoff-prompts/flutter-cloud-migration.md` 던지면 됨. | [`flutter-cloud-handoff.md`](flutter-cloud-handoff.md) |
| Flutter 레포에 던질 handoff prompt | ✅ 작성 | [`../docs/handoff-prompts/flutter-cloud-migration.md`](../docs/handoff-prompts/flutter-cloud-migration.md) |
| 학습 자료 (사용자가 다른 에이전트와 공부용) | ✅ 작성 (이전 세션) | [`../docs/learning/cloud-architecture-overview-learning.md`](../docs/learning/cloud-architecture-overview-learning.md) |

**시나리오 매트릭스 (Flutter 측):**
- A. 자동 라벨 보기 = 모든 유저
- B. 라벨 수정 (HITL) = **labelers 멤버 (admin/staff) 만**, **라벨링 웹** 에서 (Flutter 안 만듦)
- C. 하이라이트 = `behavior_logs.action ∉ {moving, unknown}` 클립 (모든 유저 본인 거)

**핵심 결정 (재논의 금지):** §4-1 Supabase 유지, §4-2 R2 직접, §4-3 capture 모듈 분리, §4-4 DB-as-message-bus, §4-5 labelers=admin, §4-6 라벨 수정 UI 분리, §4-7 하이라이트 정의, §4-8 behavior_logs source='vlm'.



## 🛑 백엔드 캡처 일시 중지 중 (2026-05-05) — 캡처 워커 한정

**상태:**
- `backend.main:app` (uvicorn) — **fly.io `petcam-api` production 가동 중 (2026-05-08 cutover 완료).** `api.tera-ai.uk` 직결, always-on. 사용자 맥북 의존 0.
- `backend.capture_main` — **여전히 일시 중지.** 사용자 맥북 로컬에서만 가동 가능 (RTSP LAN 의존). 사용자 명시 신호 받기 전 자동 재개 X.

**왜 (캡처 워커):** 클립 정리 작업 중 새 클립이 계속 들어오는 걸 막기 위함. 사용자 명시 지시
(2026-05-05): "캡쳐를 모두 일시중지 시켜. 내가 재개할 때 까지 일시정지 하고."

**캡처 워커 재개 방법:**
```bash
cd /Users/baek/petcam-lab && uv run python -m backend.capture_main
```

**재개 전제 조건:** 사용자가 직접 "캡처 재개해" 라고 말할 때만. AI 가 자체 판단으로
재개하지 말 것. 정리 작업 끝나도 자동 재개 X.

## ✅ 직전 세션 산출 — motion 풀 backfill 완료 + owner-override 권한

백엔드 EncodeUploadWorker + R2 업로드 + DB sync 일관 동작 확인. 두 단계 backfill 완료:
- **1차** (camera_id NOT NULL): motion 232/232, 평균 압축 44.5%, 0 fail
- **2차** (NULL 88 PoC 업로드, `clips/uploaded/...` literal): 88/88, 157s, 0 fail (사용자 결정 (b))

**최종 R2 상태**: motion total 382, in_r2 382, pending 0. 88건은 `clips/uploaded/{date}/{stem}_{id}.mp4`.

추가로 **owner-override 라벨 권한** 구현 — `POST /clips/{id}/labels` body 에 `labeled_by` 필드 (선택). owner 가 다른 라벨러 라벨을 강제 수정/생성 가능 (관리자/테스터 검수용). labeler 멤버는 본인 라벨만. 19 테스트 통과.

다음은 사용자 브라우저 E2E (로그인 → 큐 → 클립 → R2 영상 재생) + (통과 시) Vercel 배포.

| 영역 | 상태 |
|---|---|
| §3-1 R2 인프라 (`backend/r2_uploader.py`, env, RLS) | ✅ 코드 완료 |
| §3-2 인코딩 파이프라인 (`backend/encoding.py`, `encode_upload_worker.py`) | ✅ 코드 완료 |
| §3-3 업로드 워커 + DB sync (`backend/r2_uploader.py` insert) | ✅ 코드 완료 |
| §3-4 실기 검증 (motion 382/382 backfill — 232 cam + 88 PoC + 62 신규) | ✅ 2026-05-02 |
| §3-5 `/clips` API r2 redirect (302) + 라벨링 웹용 `/file/url` JSON | ✅ 코드 완료 |
| §3-6 Label API (`backend/routers/labels.py`, `behavior_labels` 테이블) | ✅ 코드 완료 |
| §3-7 라벨링 웹 (`web/src/app/labeling/`) | ✅ 코드 완료 |
| §3-7 Vercel 배포 + Cloudflare DNS (`label.tera-ai.uk`) | 🟡 사용자 작업 |
| §3-7 라벨러 부트스트랩 SQL (`auth.users + labelers INSERT`) | 🟡 사용자 작업 |
| §3-7 라벨러 모바일/PC 실기 검증 | 🟡 사용자 작업 |

상세: [feature-r2-storage-encoding-labeling.md](feature-r2-storage-encoding-labeling.md)

## 🔒 락인된 결정 — 새 세션에서 재논의 금지

### RBA / VLM (Round 3 종료, 2026-04-30 락인)

- 공식 기술명: **RBA (Reptile Behavior Analysis)** — 밤사이 파충류 펫캠 영상을 행동 타임라인과 케어 시그널로 바꾸는 AI 분석 시스템.
- RBA Track A = Zero-shot VLM 운영 기준선. RBA Track B = SegmentVLM 정밀 분석/실험 트랙.
- 사업·관계도 설명 SOT: [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../docs/AI-VIDEO-ANALYSIS-STRATEGY.md).
- **v3.5 production floor = 85.5%** (159건 feeding-merged) / 85.7% (154건 dish-postfilter ablation 기준)
- **⚠️ 2026-06-08 변경**: 평가셋 159 동결 → **203 통합**(eval-0608 44 추가). 사용자 **v3.5 프롬프트 영구폐기 결정**(hand_feeding 필요 → 앞으로 v3.6+). 단 **v3.5 floor(P0 85.5%)는 품질 바닥선으로 유효** — v3.6+가 넘어야 함. DEFAULT 승격은 Gemini 회귀 후. (메모리 `project_vlm_v35_baseline_lock` 갱신)
- 사용자 명시: "이거보다 더 나빠져서는 안 됨." → 어떤 변경이든 floor 미달이면 채택 X
- v3.5 prompt 백업: `web/prompts/backups/{system_base,crested_gecko}.v3.5.md` — 회귀 시 즉시 롤백
- **prompt 변경 시도 자체가 ROI 0** (6회 검증 실패: v3.6/v3.7-B/v4 + Track B/C/D/E + dish-postfilter)
- 잔존 오답은 prompt 한계가 아닌 **시각 한계** → UX/메타데이터/HITL 정공법
- 회귀 가드 의무: 159건 동일 평가셋으로 새 변경 측정 → 85.5% 미달이면 채택 X

### UX 통합 (2026-05-02 완료)
- `feature-vlm-feeding-merge-ux` ✅ 완료 — `types.ts toFeedingMerged()` + `UI_BEHAVIOR_CLASSES` (8 클래스 노출, raw 9 보존)
- F3 결과/평가 매핑 동치 9/9 통과, tsc 통과
- 9 raw → 8 UI: drinking + eating_paste → feeding 묶음

### HITL ping (2026-05-02 신규 spec)
- `feature-vlm-hitl-ping` 🚧 — defecating/shedding/eating_prey 모호 케이스 사용자 검수 (일일 5건 + opt-in)
- confidence<0.7 또는 confusion-prone 클래스 트리거. 코드 미착수.

## 🧭 다음 세션 즉시 착수 — 라벨링 웹 로컬 E2E → NULL 88 결정 → Vercel 배포

**A. R2 가동 검증 ✅ 2026-05-02** (motion 232/232 backfill로 갈음 — spec §3-4 [x]).

### B1. 라벨링 웹 로컬 E2E (트랙 A — 백엔드 일시 중지 상태에서는 보류)

> ⚠️ 2026-05-07 기준: 백엔드 (capture/API) 일시 중지 상태 (위 🛑 섹션). 트랙 A 재개하려면
> 사용자 명시 신호 후 `uv run uvicorn backend.main:app` + `uv run python -m backend.capture_main`
> 부팅 → 라벨링 웹 dev server `:3001` 재기동 → 아래 검증.

- 사용자 브라우저 검증:
  1. `http://localhost:3001/labeling` → `/labeling/login` 자동 redirect
  2. Supabase 계정 로그인 (owner: `bss.rol20@...` 등)
  3. `/labeling` 큐에 본인 클립 표시 (owner는 본인 user_id 클립만; 라벨러면 전체)
  4. 클립 클릭 → `/labeling/{clipId}` → 영상 재생 (R2 signed URL) + 썸네일 표시
  5. 라벨 폼 제출 → DB `behavior_labels` row 생성 확인
- 옛 PID 참조 (PID 68928, background task `b8xejq7hy`) 는 2026-05-02 세션 시점 기록. 2026-05-05 backend 중지 후 무효.

### B2. ✅ NULL camera_id 88건 결정 (b 채택) — 2026-05-02

PoC 평가셋(crested_gecko Round 1~3)을 `clips/uploaded/{date}/{stem}_{id}.mp4` literal 로 backfill.
- 사용자 명시: "싹다 업로드하고 관리자&테스터가 라벨을 확인/수정 할 수 있어야 해 b로 가."
- 88/88 succ, 157s. R2 키에 `uploaded` 박혀 카메라 캡처와 attribution 분리 가능.
- 후속: **owner-override 라벨 권한** 추가 (labels.py LabelCreate.labeled_by). owner 만 다른 라벨러 라벨 강제 수정 가능.

### B3. 라벨링 웹 Vercel 배포 (B1 통과 후)

- Vercel (`web/` 디렉토리) — env 3개 (`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` = `eyJ...rgtvY`, `NEXT_PUBLIC_BACKEND_URL=https://api.tera-ai.uk`)
- Cloudflare DNS — `label.tera-ai.uk` CNAME → `cname.vercel-dns.com`
- 백엔드 `.env` 에 `LABELING_WEB_ORIGINS=https://label.tera-ai.uk` 추가 + 서버 재기동
- 라벨러 1명 부트스트랩 SQL ([docs/DEPLOYMENT.md "라벨링 웹 (Vercel)"](../docs/DEPLOYMENT.md))
- 라벨러 모바일/PC 양쪽에서 클립 10건 라벨 → `behavior_labels` row 10개 확인

### 후순위 (A/B 끝난 뒤 사용자 결정)

- **HITL ping 구현** — spec [`feature-vlm-hitl-ping.md`](feature-vlm-hitl-ping.md). 라벨링 웹 인프라 재사용 (같은 `behavior_labels` 테이블) 검토
- **메타데이터 보강** — dish detection / before-after / 시간대 / 카메라 ROI prior. prompt에 박지 말 것 (룰 5 회피) — 별도 분류기/후처리 레이어로
- **Stage E 온디바이스 필터링** — 별도 트랙. SOT (`../tera-ai-product-master/docs/specs/petcam-b2c.md`) 먼저 읽고 spec 킥오프

## 🗂️ 현재 시스템 상태 스냅샷 (2026-05-08)

- **VLM:** Gemini 2.5 Flash + v3.5 prompt = production 락인 floor 85.5%(159). **2026-06-08: 평가셋 159→203 통합 + v3.6.1 OOD 초안(`system_base.v3.6.1.md`, 채택보류). Claude contact sheet 정성 v3.6 71.2%→v3.6.1 72.5%(153 적합). GT 9건 정정. 정량은 Gemini key 복구 후.** v3.5 영구폐기 방향(v3.6+ 전환, 회귀 후 DEFAULT 승격).
- **R2:** ✅ 인프라 가동 + motion 382/382 backfill (232 cam + 88 PoC `clips/uploaded/` + 62 신규)
- **라벨 권한:** ✅ owner-override 추가
- **라벨링 웹 (#4 외부):** ✅ **`label.tera-ai.uk` Vercel always-on 가동 중**. owner 검수 4 endpoint Vercel→Supabase/R2 직결 (2026-05-07 후속2). 라벨러 큐 (`/labels/queue`, `/labels/mine`) 만 BACKEND_URL 의존
- **API 서버 (#1):** ✅ **fly.io `petcam-api` production 가동 중** (2026-05-08 cutover 완료). nrt, shared-cpu-1x 256MB, always-on, `min_machines_running = 1`. `api.tera-ai.uk` (fly.io edge 66.241.124.67) HTTPS 200, Let's Encrypt E8 cert (2026-08-06). 사용자 맥북 cloudflared / uvicorn 의존 0. Phase 1 endpoint 2개 (`/me/is_labeler`, `/clips/highlights`) 가동.
- **캡처 워커 (#2):** `backend.capture_main` — 코드 완료, 일시 중지 (2026-05-05). 사용자 명시 신호 받기 전까지 자동 재개 X. RTSP LAN 의존이라 fly.io 이전 대상 X
- **VLM 워커 (#3):** ✅ **fly.io `petcam-vlm-worker` always-on 가동 중** (2026-05-07). nrt, shared-cpu-1x 256MB. clip 70093109 1건 E2E 검증 통과 (action=moving 0.9). 159건 회귀 가드 + 100건 비용 추적 미해결.
- **Auth:** `AUTH_MODE=prod`, Supabase JWT (ES256). CORS 라벨링 웹 origins 분리
- **카메라:** cam1 (1c1aea9f) / cam2 (3a6cffbf) — 오너 bss.rol20. mirror cam1-mirror / cam2-mirror — QA dlqudan12
- **Tests:** 247 passing (이전 239 + Phase 1 신규 8 — `/me/is_labeler` 2 + `/clips/highlights` 6)
- **마이그레이션 적용:** 2026-05-07 — `behavior_logs` UNIQUE(clip_id, source) + RPC `fn_vlm_pending_clips`
- **Stage:** A~D5 ✅ / E 🆕 (스코프 미확정) / VLM PoC ✅ Round 3 종료 / R2 ✅ 가동 + 라벨링 코드 완료 / **Cloud Migration 트랙: capture 코드 완료 + VLM fly.io ✅ + 라벨링 웹 ✅ + API 서버 fly.io ✅ (cutover 완료) + Flutter 측 미착수**

## 📂 맥락 복원 — 읽을 파일 (우선순위)

새 세션이 맥락 없이 들어왔을 때 이 순서로:

1. **이 파일** — 오늘의 시작 지점 + 락인 결정
2. [feature-r2-storage-encoding-labeling.md](feature-r2-storage-encoding-labeling.md) — R2/라벨링 전체 결정 + 사용자 가동 체크리스트
3. [feature-poc-vlm-web.md](feature-poc-vlm-web.md) — VLM PoC 전체 결정 이력 (Round 1~3, §3-13까지)
4. [feature-vlm-feeding-merge-ux.md](feature-vlm-feeding-merge-ux.md) — UX 통합 완료 (raw 보존 + UI 매핑)
5. [feature-vlm-hitl-ping.md](feature-vlm-hitl-ping.md) — HITL spec (코드 미착수)
6. `~/.claude/projects/-Users-baek-petcam-lab/memory/MEMORY.md` — 자동 메모리 인덱스
7. [../README.md](../README.md) — 1분 요약 + 퀵스타트
8. [../docs/ENV.md](../docs/ENV.md) — R2 + CORS 환경변수
9. [../docs/DEPLOYMENT.md](../docs/DEPLOYMENT.md) — R2 + Vercel + 부트스트랩 SQL
10. [README.md](README.md) — spec 운영 규칙 + 전체 스펙 목록

## 💬 사용자가 "뭐부터 해야해?" 물으면

1. **첫 확인 — 락인 존중**: v3.5 baseline은 건드리지 않는다고 인지. prompt 변경/clean slate 제안 금지.
2. **즉시 액션 — Flutter 세션에 cutover 완료 신호 + 라벨 chip / 하이라이트 탭 구현**:
   - 백엔드 측 Cloud Migration 다 끝남 (2026-05-08 fly.io cutover). 옆 레포 (`/Users/baek/myProjects/tera-ai-flutter`) 에서 새 세션 띄우고 `docs/handoff-prompts/flutter-cloud-migration.md` 그대로 prompt 로 던져.
   - Flutter 5단계 PR (handoff §5): 도메인 모델 → fileUrl async → 라벨 chip → 하이라이트 탭 → labeler deep link.
3. **트랙 진행 상태** (Cloud Migration):
   - **B1. capture worker 분리** ([`feature-capture-worker-extraction.md`](feature-capture-worker-extraction.md)) — 2026-05-07 코드 완료. 자체 HW 카메라 도착 전까지는 사용자 맥북에서 `uv run python -m backend.capture_main` 으로 가동 (현재 일시 중지). **재개는 사용자 명시 신호 후.**
   - **B2. VLM production 워커** ([`feature-vlm-worker-cloud.md`](feature-vlm-worker-cloud.md)) — 코드 + fly.io 가동 완료. **남은 일:** 159건 회귀 (80.5% / floor 85.5%) + 100건 비용 추적 (별도 트랙).
   - **B2.1. VLM fly.io 배포** ([`feature-vlm-worker-fly-deploy.md`](feature-vlm-worker-fly-deploy.md)) — ✅ 2026-05-07 완료.
   - **B2.2. 라벨링 웹 백엔드 분리** ([`feature-labeling-web-cloud.md`](feature-labeling-web-cloud.md)) — ✅ 2026-05-07 완료.
   - **B2.3. API 서버 fly.io 이전 + Flutter contract endpoint** ([`feature-api-server-fly-deploy.md`](feature-api-server-fly-deploy.md)) — ✅ **완료 2026-05-08 (Phase 1+2+3+4 종료, cutover 후 production traffic 정상).**
   - **B3. Flutter 측 작업** — 별도 레포 (`/Users/baek/myProjects/tera-ai-flutter`). handoff prompt (`docs/handoff-prompts/flutter-cloud-migration.md`) 그대로 새 세션에 던지면 됨. **백엔드 측 cutover 끝남 (2026-05-08)** → production 도메인 (`api.tera-ai.uk`) 그대로 사용 가능.
4. **회귀 가드 자동 적용**: 어떤 변경이든 85.5% floor 검증 의무 (VLM 워커 변경 시).
