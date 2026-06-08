# hand_feeding OOD 라벨 도입 + Track A v3.6 후보 실험

> petcam-rba-worker HITL 검수 핸드오버(2026-06-06) 반영 — 사람/도구 개입(OOD) 영상을 `hand_feeding` 라벨로 분리해서 P0 학습 오염을 막고, 라벨 체계·라벨링 UI·VLM 워커에 전파한다.

**상태:** 🚧 진행 중 🔄 (C-1/C-2/GT정정 완료, C-3 회귀평가만 Gemini key 차단으로 대기 — 2026-06-08 Claude 정성 트랙으로 우회 진전 + v3.6.1 OOD 초안 신설)
**작성:** 2026-06-06 · **최종 갱신:** 2026-06-08
**연관 SOT:** `../petcam-rba-worker` 핸드오버 3종 (아래 §6) — 원본 SOT는 rba-worker, 이 스펙은 petcam-lab 측 반영 작업 추적
**연관 RBA 용어:** [`experiment-event-segment-vlm.md`](experiment-event-segment-vlm.md) (Track A/B 정의)

## 1. 목적

**사용자 가치:** petcam 운영 환경은 "사람 부재 자율 모니터링"인데, 학습 후보 영상 일부가 사람이 스푼/시린지/핀셋으로 급여하는 OOD 영상이었음. 이걸 P0 학습에 그대로 넣으면 모델이 "사람 손 = 섭취" 같은 spurious feature를 학습 → 운영(손 없음)에서 recall 하락. rba-worker HITL 검수 결과 **`eating_paste` GT 13건 중 5건(38%)이 사실 OOD**. 라벨링 단계에서 OOD 구분 옵션이 없던 게 근본 원인.

**기술 학습:** 라벨 클래스 1개 추가가 types/prompts/labeling-UI/DB/평가 **5개 레이어에 어떻게 전파되는지**. 그리고 production 락인된 v3.5 프롬프트를 회귀평가로 안전하게 확장하는 절차.

## 2. 스코프

### In (이번 스펙에서 한다)

- **C-1 라벨 추가** — `hand_feeding` (OOD 마커, color `#e67e22`)을 5곳에 전파:
  - `web/src/types.ts` — BEHAVIOR_CLASSES + PRIORITY_ORDER(최상위) + UI_BEHAVIOR_CLASSES
  - `backend/vlm/prompts.py` — BEHAVIOR_CLASSES
  - `web/src/lib/labelingApi.ts` — `ActionType` union *(보고서 누락분)*
  - `web/src/app/labeling/[clipId]/page.tsx` — `RAW_ACTIONS` + `MIRRORABLE_ACTIONS` + 한글 라벨 *(보고서 누락분)*
- **C-2 라벨링 UI OOD 입력** — 우리 실제 구조(`action` state + `lick_target` + `createLabel` API)에 맞게 재설계. "사람/도구 보임" 인지를 라벨러에게 주는 UX.
- **C-3 v3.6 후보 프롬프트** — `hand_feeding` OOD 판정 룰 **하나만** 추가. v3.5 백업 불변 보존 + 회귀평가로 floor 안 깨지는지 측정 후 채택/롤백 결정.
- **GT 정정 6건 sync 검토** — 6개 clip이 우리 Supabase `behavior_logs`에 있는지 확인 → 있으면 sync SQL + audit.

### Out (이번 스펙에서 **안 한다**)

- **C-4 event_logs 멀티이벤트 스키마** — `gemini_client.py` 응답 스키마(`{action,confidence,reasoning}` 단일) + worker INSERT(clip당 1 row) + 새 테이블 전면 변경. 위험 🔴 매우 높음. **Phase B 별도 PR.**
- **C-3 정의 정밀화 4개** (drinking/shedding/eating_prey/eating_paste) — **이미 v3.5 프롬프트에 구현돼 있음** (§4 근거). 중복이라 제외.
- **C-3 confidence<0.7 → needs_review** — [`feature-vlm-hitl-ping.md`](feature-vlm-hitl-ping.md)가 이미 동일 트리거 보유 + "confidence-abstain 단독 분기 무용" 판정 (메모리). 제외.
- **C-5 capture 가변 길이** — 자체 HW 캡처가 RTSP capture.py 대체 예정이라 투자 보류 (메모리 `project_capture_replaced_by_own_hw`).
- **multi-track 한 clip phase 분할 라벨링** — 현재 단건-단일라벨 구조와 충돌. event-level은 C-4와 함께 Phase B.

### 결정 필요 (착수 전 사용자 확인)

- **UI_BEHAVIOR_CLASSES 노출 방식** — hand_feeding을 (A) 그대로 노출 / (B) feeding merge / (C) utility 그룹. 보고서 권장은 A. 단 `results` 대시보드 막대그래프가 8개 가정이면 layout 영향 → 확인 필요.

> **스코프 변경은 합의 후에만.** In/Out 경계 흔들리면 이 섹션 수정 + 사유 기록.

## 3. 완료 조건

### C-1 라벨 추가 — ✅ 완료
- [x] `web/src/types.ts` BEHAVIOR_CLASSES / PRIORITY_ORDER / UI_BEHAVIOR_CLASSES에 hand_feeding 추가
- [x] `backend/vlm/prompts.py` BEHAVIOR_CLASSES 동기화 (SPECIES_CLASSES 자동 흡수)
- [x] `web/src/lib/labelingApi.ts` `ActionType` union에 추가
- [x] `labeling/[clipId]/page.tsx` RAW_ACTIONS + MIRRORABLE_ACTIONS + 한글 라벨("사람 급여")
- [x] **`backend/routers/labels.py` ActionType Literal에 추가** (보고서·초안 누락분 — 백엔드 검증)
- [x] `behavior_logs.action` CHECK 제약 **없음 확정** (GT sync UPDATE 시 hand_feeding 정상 반영 — migration 불필요)
- [x] `pnpm exec tsc --noEmit` 0 errors + `pytest tests/` 64 passed

### C-2 라벨링 UI — ✅ 코드 완료 (브라우저 검증 대기)
- [x] hand_feeding을 RAW_ACTIONS(더보기 최상위) + MIRRORABLE_ACTIONS 포함 → 선택·저장·mirror 경로 확보
- [x] hand_feeding 선택 시 OOD 안내 박스 + 더보기 버튼 "사람 급여" 힌트 (라벨러 OOD 인지)
- [ ] 실기: 라벨링 화면에서 hand_feeding 저장 → behavior_logs mirror 브라우저 확인 (사용자)

### C-3 v3.6 후보 프롬프트 — 🚧 Gemini 회귀평가 대기 (Claude 정성 트랙으로 우회 검증)
- [x] v3.6 후보 작성 (`web/prompts/backups/system_base.v3.6.md` — v3.5 백업 불변, OOD 룰만 추가)
- [x] 격리: `build_system_prompt(species, *, prompt_version)` — v3.5=9class / v3.6=10class
- [x] **v3.6.1 OOD 룰 초안 신설** (`web/prompts/backups/system_base.v3.6.1.md` + `prompt_version="v3.6.1"` + `_VERSION_EXCLUDED_CLASSES["v3.6.1"]=set()` — v3.6 무손상). v3.6 "손/도구 보이면 hf" 과발동 → **"음식 전달 행위(feeding act)"로 좁힘**.
- [x] **Claude 정성 검증** (Gemini key 차단 우회, 2026-06-08): v3.6 11건 과발동 진단 → v3.6.1 로 과발동 5/5 수정 + recall 6/6 유지 (v3.6 6/11 → v3.6.1 11/11). hand_feeding OOD recall blind 12/13(44건)·23/26=88%(153건).
- [ ] **(차단) `scripts/eval_vlm_v36_handfeeding.py` Gemini 159/203건 회귀** → P0 floor 근사 + hand_feeding recall 측정 — **AQ. prefix key 계정 플래그로 Gemini 차단**(메모리 `feedback_gemini_aq_key_account_flag`). key 교체 후 재개.
- [ ] hand_feeding 탐지 확인 + recovered > broken (Gemini 회귀로 정량 측정)
- [x] **채택 보류 결정 기록** — v3.6.1 은 정성 검증만 통과, **회귀 없이 `DEFAULT_PROMPT_VERSION` 승격 금지** (donts/vlm.md: 회복만 보고 채택 금지, 의심되면 롤백 우선). DEFAULT 는 여전히 `v3.5` 유지.
- [ ] **(신규) Gemini 회귀 통과 후 `DEFAULT_PROMPT_VERSION` → v3.6+ 승격** — 사용자 v3.5 영구폐기 결정(2026-06-08). 승격은 회귀 게이트 통과가 전제.

### GT 정정 — ✅ 완료 (핸드오버 6건 + blind 평가 역검출 9건)
- [x] **핸드오버 6건**: clip 전부 우리 Supabase `camera_clips`(159건)에 존재 확인 → `behavior_logs` human row UPDATE (5→hand_feeding, 1→moving) + notes audit (`scripts/sync_handoff_gt.py --apply`). behavior_labels는 비어있어 무관
- [x] **blind 평가 역검출 9건 (2026-06-08, 라벨 QA 효과)** — Claude blind 평가가 GT 라벨 오류를 역검출:
  - eval-0608 **2961**: `hand_feeding → eating_paste` (도구 없는 dish paste 섭취였음, 핸드오버 과분류) — commit `1af0eff`
  - 159건 중 **8건**: `eating_prey/eating_paste → hand_feeding` (사람이 핀셋/시린지/스푼으로 급여하는데 v3.5 시절 hand_feeding 클래스가 없어 오라벨됨) — commit `de2de48`
  - **교훈:** blind 평가(모델이 정답을 모르는 채 판정) → 사람 GT와 불일치 케이스가 *모델 오답이 아니라 GT 오류*를 드러냄. 라벨 클래스 부재(v3.5 9-class)가 만든 체계적 오라벨을 역검출.

## 4. 설계 메모

### 보고서 가정 vs 실제 레포 차이 (핵심 — 보고서를 그대로 적용하면 안 되는 이유)

| 항목 | 보고서(home-mac) 가정 | 실제 petcam-lab | 영향 |
|---|---|---|---|
| `types.ts` BEHAVIOR_CLASSES | 9-class | **일치** (9-class) | C-1 patch 그대로 OK |
| `build_system_prompt` | 함수에 `ADDITIONAL_RULES_V2` 문자열 append | **v3.5 락인 `.md` 백업 read + placeholder 치환** 구조. 프롬프트 본문이 코드에 없음 | C-3 접근법 전면 재설계 → v3.6 후보 .md |
| drinking/shedding/eating_prey 정의 | "Gemini 오답나니 추가하라" | **이미 v3.5에 있음** (system_base.v3.5.md 룰 2/6/7/8/9) | 중복 → Out |
| 라벨링 UI | BEHAVIOR_CLASSES dropdown + PRIORITY_ORDER 자동 노출 | **MAIN_ACTIONS(4)+RAW_ACTIONS(5) 하드코딩 + lick_target(6)**. dropdown 없음 | C-2 코드 예시 못 씀, 재설계 |
| behavior_logs.action | CHECK 제약 있을 수 있음 | migration·코드 어디에도 **action CHECK 없음** (source CHECK만) | C-1 DB migration 불필요 (단 Supabase 확인) |
| output schema | clip당 multi-event 가능 가정 | `gemini_client._RESPONSE_SCHEMA` = `{action,confidence,reasoning}` 단일, worker clip당 1 row | C-4로 분리 (Phase B) |

### v3.5 정의 정밀화가 이미 있다는 근거
`web/prompts/backups/system_base.v3.5.md`:
- 룰 2: "tongue flick alone is NOT evidence" → 보고서의 "허공 짤랑→moving"
- 룰 6: "drinking vs eating_paste, meniscus 못 보면 moving" → "마른 표면→moving"
- 룰 7: "eating_prey는 prey CLEARLY VISIBLE + locked attention" → "곤충 frame 안"
- 룰 8: "shedding은 DIRECT VISIBLE skin removal, 변색만으론 moving" → "비침→moving"

→ rba-worker는 prompts를 read-only mirror만 해서 작성자가 우리 v3.5를 못 봄. **진짜 신규는 hand_feeding OOD 룰 하나뿐.**

### v3.5 락인 존중
v3.5는 사용자 명시 production floor (85.5%, 메모리 `project_vlm_v35_baseline_lock`). 프롬프트 6방향 변경 모두 퇴행/동률 ([`feature-poc-vlm-web.md`](feature-poc-vlm-web.md)). → C-3는 백업 직접 수정 금지, v3.6 후보로 만들어 회귀평가 게이트 통과해야만 채택.

### 기존 구조와의 관계
- 라벨링 UI는 이미 `lick_target='air'`로 "허공 핥기"를 분리 중 — 보고서가 모르는 기존 정교함. hand_feeding도 자연스럽게 통합 가능.
- `toFeedingMerged()`는 hand_feeding을 merge 대상에서 제외 (pass-through). `web/eval/v35/analyze-*.py` FEEDING_MERGE와 동치 유지.

### 리스크 / 미해결 질문
- UI_BEHAVIOR_CLASSES 추가 시 results 대시보드 layout 영향 (§2 결정 필요).
- C-3 v3.6/v3.6.1에 OOD 룰 추가가 기존 클래스 판정을 흔들 위험 → 회귀평가로 broken 측정 필수. **현재 차단:** Gemini 회귀 불가(AQ. prefix key 계정 플래그) → 정량 broken 미측정. **Claude 정성 트랙은 회귀 대체가 아님**(broken 카운트 불가), key 교체 후 정량 게이트 필수.
- GT 정정 6건 clip이 우리 DB에 실제 있는지 미확인 (rba-worker로 마이그레이션된 데이터라 잔류 여부 불명). → **해소: 6건 전부 존재, sync 완료.** (+ 2026-06-08 blind 평가가 GT 라벨 오류 9건 추가 역검출 → §C-3 GT 정정 참고.)

### 159건 오답 진단 (2026-06-07, GT sync 후, 비용 0)

`scripts/diagnose_vlm_errors.py` — `behavior_logs` 의 GT(human) vs Gemini v3.5(vlm) 비교. 영상/비용 추가 없이 "어디서·왜 틀리나" 측정 (이미 저장된 추론 재사용).

- **정확도**: raw 78.0% (124/159), feeding-merged 81.8% (130/159).
  - ⚠️ 85.5% floor 대비 낮아 보이는 건 **GT sync 효과** — hand_feeding 5건 + moving 1건이 정답→오답 재분류됨 (v3.5 는 OOD 모름). **v3.5 성능 저하 아님.** v3.6 가 hand_feeding 잡으면 회복 예상.
- **클래스별**: shedding 97% / feeding 91% / eating_prey 84% / moving 80% / **defecating 69%** / hand_feeding 0%(구조적).
- **최대 혼동**: `moving ↔ feeding` 13건. Gemini 가 "그릇 근처 머리 움직임"을 conf **0.9~0.95** 로 "반복 핥기"라 과탐지.

**결론 4가지**:
1. **그릇↔먹기 = 시각 한계 확정**. v3.5 에 "그릇 근처 ≠ 먹기" 룰이 *이미 있는데도* conf 0.9+ 로 못 막음 → 프롬프트로 못 풂 ([`feature-poc-vlm-web.md`](feature-poc-vlm-web.md) 6번 검증과 일치). **영상 추가로도 안 풀림** → ROI(그릇 위치)/UX/시간 시그널 필요.
2. **defecating 69% 약함**: 배변을 moving 으로 놓침 (자세 미묘 + 16건 부족) → **영상 추가 가치 있는 클래스.**
3. **hand_feeding 5건 → v3.6 풀 가능성 높음**: Gemini reasoning 에 이미 `spoon/syringe/stick held by...` 도구 인지. 클래스 부재로 eating_paste 분류했을 뿐 → v3.6 OOD 룰로 잡힐 것 (충전 후 회귀평가로 확인).
4. **VideoMAEv2 검증 과녁 확정**: 그릇↔먹기는 "혀 실제 접촉/반복 횟수" 같은 *시간적 동작 디테일* = frame 샘플링(Gemini) 약점 = 비디오 네이티브(VideoMAEv2) 가설적 강점. 소규모 검증을 **"이 13건 혼동 감소 여부"** 로 타깃팅.

**다음 방향**: 영상 추가는 defecating 등 "데이터 부족 + 미묘" 클래스에 한해 가치. 그릇↔먹기는 영상 양 문제 아님(시각 한계) → ROI/UX/VideoMAEv2. hand_feeding 은 v3.6.

### v3.6 → v3.6.1 OOD 룰 좁히기 (2026-06-08, Claude 정성 트랙)

Gemini 회귀가 AQ. prefix key 계정 플래그로 막혀(메모리 `feedback_gemini_aq_key_account_flag`), **Claude 정성 트랙**으로 OOD 룰을 검증·개선. (방법론 검증 트랙 — 모델 일반화 아님. contact sheet 입력으로 Claude 가 직접 판정.)

- **문제:** v3.6 OOD 룰 "손/도구가 보이면 hand_feeding" 이 **과발동**. 단순 핸들링(개체를 들거나 만지는 손)까지 hand_feeding 으로 잘못 분류 (정성 11건 중 6/11 만 정답).
- **수정:** v3.6.1 에서 트리거를 **"음식 전달 행위(feeding act)"로 좁힘** — 손/도구 *존재*가 아니라 *음식을 입으로 전달하는 동작*이 보일 때만 hand_feeding. (`web/prompts/backups/system_base.v3.6.1.md`, v3.6 파일은 무손상.)
- **정성 결과:** 과발동 5/5 전부 수정 + recall 6/6 유지 → v3.6 6/11 → **v3.6.1 11/11**. blind recall 12/13(44건)·23/26=88%(153건).
- **채택 보류:** 정성 검증만 통과. **Gemini 회귀 게이트 없이 `DEFAULT_PROMPT_VERSION` 승격 금지** (donts/vlm.md 룰 5: 회복만 보고 채택 금지). 현재 DEFAULT=`v3.5` 유지.
- **왜 Claude 정성 트랙이 유효한가:** 회귀 정량평가(broken/recovered 카운트)는 못 하지만, *룰 문구가 과발동/과소발동 하는지*는 소수 케이스 blind 판정으로 진단 가능 → 룰 초안 품질을 Gemini 복구 전에 미리 끌어올림. (정량 게이트는 여전히 Gemini 회귀가 SOT.)

### v3.5 영구폐기 결정 (2026-06-08, 사용자)

사용자가 **v3.5 영구폐기 + v3.6+ 전환**을 결정. 단 **승격 절차는 그대로** — Gemini 회귀 게이트 통과 후에만 `DEFAULT_PROMPT_VERSION` 을 v3.6+ 로 올린다 (폐기 결정이 게이트를 건너뛰는 게 아님). 그때까지 production 워커는 v3.5 로 계속 돈다.
- 영향: 메모리 `project_vlm_v35_baseline_lock` 의 "v3.5 production floor" 는 **승격 기준선**으로는 유효(회귀가 이 floor 를 깨지 않아야 함), 단 최종 production 프롬프트는 v3.6+ 가 될 예정.
- v3.5 백업 `.md` 는 **삭제하지 않는다** (회귀 baseline·롤백 안전망). "폐기"=DEFAULT 에서 내림이지 파일 제거 아님.

## 5. 학습 노트

- **OOD (out-of-distribution)**: 학습 데이터에는 있지만 운영 환경엔 없는 분포. 여기선 "사람 손/도구". 모델이 OOD 신호를 정답 단서로 학습하면 운영에서 무너짐.
- **spurious feature**: 정답과 우연히 상관된 가짜 단서 (사람 손 등장 ↔ 섭취). 인과가 아니라 데이터 편향.
- **회귀평가 게이트**: 프롬프트 변경을 production에 넣기 전 고정 평가셋으로 baseline 대비 broken/recovered 측정. `scripts/eval_vlm_worker_regression.py`. (2026-06-08: 평가셋 159 → **203건 통합**(eval-0608 44건 추가, 메모리 `project_eval0608_evidence_set`). v3.6.1 회귀는 이 203건으로 측정 예정 — Gemini key 복구 대기.)
- **blind 평가 (라벨 QA 효과)**: 모델이 사람 GT 를 *모르는 채* 판정 → GT 불일치 케이스가 모델 오답뿐 아니라 *GT 라벨 오류*도 드러냄. 2026-06-08 Claude blind 평가가 클래스 부재로 생긴 체계적 오라벨 9건을 역검출 (§C-3 GT 정정).

## 6. 참고

- 핸드오버 원본 (Desktop, rba-worker 작성):
  - `HANDOVER_TO_PETCAM_LAB_2026-06-06.md` — HITL 검수 결과 요약
  - `PETCAM_LAB_MIGRATION_PLAN_2026-06-06.md` — C-1~C-5 patch + sync 체크리스트
  - `REPORT_PETCAM_LAB_CHANGES_2026-06-06.md` — 변경 요청서 + GT 정정 audit trail
- 연관 스펙: [`feature-poc-vlm-web.md`](feature-poc-vlm-web.md) (v3.5 락인), [`feature-vlm-feeding-merge-ux.md`](feature-vlm-feeding-merge-ux.md) (UI 매핑), [`feature-vlm-hitl-ping.md`](feature-vlm-hitl-ping.md) (confidence 트리거), [`experiment-event-segment-vlm.md`](experiment-event-segment-vlm.md) (RBA Track / event-level)
- sync 룰: CLAUDE.md §"자매 레포 분리" — `BEHAVIOR_CLASSES` SOT는 petcam-lab, rba-worker는 read-only mirror. C-1 적용 후 rba-worker에 cherry-pick.
