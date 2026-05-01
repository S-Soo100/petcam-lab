# VLM feeding post-filter (dish-presence router)

> v3.5 86.2% baseline 잔존 오답의 핵심 덩어리 — drinking ↔ eating_paste 양방향 혼동 — 을 **2단계 분류**로 푼다. VLM raw 9-class 출력에서 `{drinking, eating_paste}` 케이스만 추출 → **별도 cheap LLM**(Gemini Flash)으로 "밥그릇이 화면에 보이냐 yes/no" 별도 호출 → 그릇 있음=eating_paste 확정, 그릇 없음=drinking 확정. v3.5 prompt/모델 락인 무관(raw 출력은 안 건드림). 평가셋 feeding-merged 정확도 93.1% (drinking + eating_paste GT 29건 → feeding 예측 27건)와 raw 86.2% 사이 ~7%p 갭이 곧 "feeding 묶음 안의 분리 비용" — 이걸 dish 시그널로 흡수.

**상태:** 🗑️ 폐기 (2026-05-02) — **post-filter 메커니즘은 안전(broken=0)이지만 신호 품질이 부족해 채택 불가**.
- 154건 final 정확도 **84.42%** (130/154) — floor 85.7%(132/154) 미달 (-2건).
- router self-accuracy: dish 79.4% / lick 73.5% / both 67.6% — 90% 목표 미달.
- 오답셋 26건 한정 multi-track ablation(Track A baseline + B/C/D/E 4종 prompt 변형) 결과 **누구도 baseline 못 이김** — A=D=8/26, E=7, B=4, C=3. → prompt 보정으로 router 신호 품질 끌어올리기 불가능 검증.
- 결론: **시각 한계 — Pro와 Flash가 같은 환각 학습("approaches dish→eats from dish")**. UX/HITL 정공법으로 pivot. 후속 spec [`feature-vlm-feeding-merge-ux.md`](feature-vlm-feeding-merge-ux.md) (재개) + [`feature-vlm-hitl-ping.md`](feature-vlm-hitl-ping.md) (신규).
- 재활용 가능 자산: `dish-presence-gt.jsonl` 34건(human 12 + oracle 22), `oracle-dish-presence.py` / `infer-dish-presence.py` / `analyze-multi-track.py` 인프라, 12건 사용자 메모(confusion set 진단 데이터).

**작성:** 2026-05-01 / **폐기:** 2026-05-02
**연관 SOT:** `../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md` (라운드 진화 + 결정 16건)

## 1. 목적

- **사용자 가치**: 사육 환경 컨텍스트(밥그릇 = 슈퍼푸드 급여 윈도우 자체)를 활용해 VLM 시각 한계 회피. v3.5 raw 정확도 86.2% → feeding-merged 93.1% 갭 ~7%p의 대부분 흡수 목표 (raw 정확도 90%+ 기대). drinking 시각 한계 4건 + eating_paste over-trigger 양방향 보정.
- **기술 학습**:
  - 다단계 LLM 분류 패턴 (행동 차원 → 환경 차원 분리)
  - Cheap binary classifier (Gemini Flash, JSON yes/no)로 단일 결정만 하는 호출
  - Post-filter 룰을 prompt에 박지 않고 코드에 두는 이유 (donts/vlm.md 룰 5 회피)
  - 양방향 보정의 회귀 측정 — 모델 자체 정확도가 raw 분리 정확도 미달이면 backfire
- **결정 근거**:
  - `project_vlm_v35_baseline_lock.md` — prompt 변경 ROI 0 검증
  - `feedback_vlm_visual_information_limit.md` — "사람도 헷갈리는 케이스"는 메타 시그널로
  - `feedback_vlm_ux_merge_validation.md` — 평가 매핑 93.1% (feeding 묶음) 검증값이 갭 분석 근거
  - 환경 prior로 "밥그릇 화면 존재" 사용자 발의 (2026-05-01) — 오너 입력 UX 불필요, 시각 시그널 직접

## 2. 스코프

### In (이번 스펙에서 한다)

#### 2.1 dish-presence GT 라벨링
- **합집합 39건** (`web/eval/v35/dish-candidates.jsonl`, 2026-05-01 추출):
  - GT∈feed & raw∈feed: 27건
  - GT∈feed & raw∉feed: 2건 (false negative)
  - GT∉feed & raw∈feed: 10건 (false positive, moving GT 9건 + defecating 1건)
- **두 시그널** 라벨링 — `dish_present` (화면에 사료 그릇 존재) + `licking_behavior` (게코가 핥는 동작).
  - **2-feature 결정 사유** (2026-05-01): binary(dish only)는 GT=moving raw=eating_paste 9건 회복 불가능 — 룰이 dish=false → drinking으로만 보내서 moving으로 못 옴. licking 시그널 추가 시 `dish=false + licking=false → moving` 룰로 회복 가능 (39건 분포 분석 결과).
- 1차: Gemini Pro로 oracle 호출 → `{dish_present, licking_behavior, reasoning}` JSON.
- 2차: 사람 spot check — oracle 결과 검수, 불일치/모호 케이스만 사람 확정.
- 산출물: `web/eval/v35/dish-presence-gt.jsonl` (clip_id, dish_present, licking_behavior, source: oracle|human, reasoning).

#### 2.2 dish-presence 모델 호출 (router)
- 모델: **Gemini 2.5 Flash** (raw VLM과 같은 클라이언트, 인프라 통일)
- generationConfig: `{temperature: 0.1, top_p: 0.95, response_mime_type: 'application/json'}` (donts/vlm.md 룰 6)
- prompt: 짧고 명시적, **두 시그널 동시 결정**. 출력 스키마: `{dish_present: boolean, licking_behavior: boolean, confidence: number, reasoning: string}`.
- 호출 대상: 합집합 39건 (raw 출력이 `{drinking, eating_paste}` 또는 GT가 그쪽). 다른 클래스는 호출 X.
- 코드 위치: `web/eval/v35/infer-dish-presence.py` (Python, `infer-v35-zeroshot.py` 패턴 재사용).

#### 2.3 post-filter 룰
- 입력: raw VLM 9-class 출력 + dish-presence 결과 (`dish_present` + `licking_behavior` 두 시그널)
- 룰 (5개 + fallback):
  - `raw=eating_paste, dish=true`                         → final = `eating_paste` (confirm)
  - `raw=eating_paste, dish=false, licking=true`          → final = `drinking` (다른 사물 핥음)
  - `raw=eating_paste, dish=false, licking=false`         → final = `moving` (먹지도 핥지도 않음 — 9건 회복 카드)
  - `raw=drinking, dish=true`                             → final = `eating_paste` (그릇 보고 사료 먹는 중)
  - `raw=drinking, dish=false`                            → final = `drinking` (confirm)
  - 그 외 raw                                             → final = raw (그대로)
- 코드 위치: Python 함수 `apply_dish_postfilter(raw, dish, licking)` — `web/eval/v35/postfilter.py`.
- TS 포팅(production)은 평가 결과 채택 후 별도 spec.

#### 2.4 정확도 평가
- **dish-presence 자체 정확도** (39건 GT 대비, 두 시그널 각각):
  - `dish_present` 일치율, `licking_behavior` 일치율, 둘 다 일치율
  - **목표: 두 시그널 각각 90%+**. 미달 시 prompt 보정 또는 모델 후보(Flash-Lite, Haiku 4.5) 비교.
- **post-filter 적용 후 159건 final 정확도**: v3.5 raw 86.2% 대비.
  - **회귀 가드: 86.2% 이상** (락인 floor 미달 시 채택 X).
  - 목표: 91~93% (예상 회복 = drinking 4건 + moving 9건 중 다수).
- 5-카테고리 분석 (held-correct / recovered / broken / still-wrong / missing) — `recovered > broken` 의무.

#### 2.5 결과 저장 / DB 스키마
- raw + final + dish-presence 셋 다 보존.
- 옵션 후보 (**구현 단계에서 결정** — 사용자 합의 2026-05-01):
  - A. `behavior_logs.action`은 raw 그대로, `action_final` + `dish_present` 컬럼 추가
  - B. 별도 테이블 `behavior_logs_postfilter` (clip_id FK + final_action + dish_present + dish_model + dish_reasoning)
- 기본 추천: B (책임 분리, 향후 후처리 추가에 확장 용이). 단순함이 우선이면 A.
- raw 보존 원칙은 옵션 어느 쪽이든 동일.

#### 2.6 회귀 가드 의무
- 본 spec 변경(dish-presence prompt, 룰, 모델 교체)마다 159건 재평가 → 86.2% floor 미달 시 채택 X.
- 재현 자료 보존: `web/eval/v35/{dish-zeroshot,postfilter-final}.jsonl` + 분석 스크립트.

#### 2.7 문서 동기화
- `feature-poc-vlm-web.md`에 §3-14 (post-filter 결과) 추가, 본 spec 링크.
- SOT (`petcam-poc-vlm.md`) 결정 항목 동기화 (**yes로 확정** — 사용자 합의 2026-05-01):
  - 결정 한 줄: "분류 파이프라인 = VLM 1차(Flash, 9-class) + dish-presence router 2차(Flash binary, drinking/paste 케이스 한정). 회귀 가드 floor 86.2%."
  - 비용 구조 변경 명시 (클립당 LLM 호출 1 → 1.x회).
  - 모니터링 지표 추가 (final 정확도 + dish-presence 자체 정확도).

### Out (이번 스펙에서 **안 한다**)

- VLM raw prompt / 모델 / generationConfig 변경 — v3.5 락인 (`project_vlm_v35_baseline_lock.md`).
- F2 LabelForm UX 변경 — human label은 raw 9클래스 그대로, 단축키 1~9 유지.
- F3·피드 UI 매핑 통합 — post-filter가 raw를 정확히 분리하면 UI는 final 그대로 표시하면 됨. UI 묶음(feeding) 별도 spec 불필요. (보류된 [feature-vlm-feeding-merge-ux.md](feature-vlm-feeding-merge-ux.md)는 post-filter 실패 시 fallback 후보로만)
- 객체 검출 모델(YOLO 밥그릇 학습) — 라벨링 + 학습 비용 큼. PoC 단계 과투자. 장기 후보.
- 정적 ROI(밥그릇 위치 박스 사전 등록) — 그릇 위치 가변이라 신뢰도 약함. 폐기.
- drinking-region ROI / 메타 입력 UX (오너가 "밥 줬어요" 토글) — dish-presence 시각 시그널이 더 단순/정확. 폐기.
- hiding ↔ moving 보정 — 평가 레이어 한정 그대로 유지. UI/raw 변경 X.
- 159건 재추론 — raw VLM 출력은 동일, dish-presence 호출 + post-filter만 추가.

> **스코프 변경은 합의 후에만.** 작업 중 In/Out 경계가 흔들리면 이 섹션 수정 + 사유 기록.

## 3. 완료 조건

- [x] **dish-candidates 합집합 추출** — 39건. `web/eval/v35/dish-candidates.jsonl` (2026-05-01).
- [x] **dish-presence GT** — `dish-presence-gt.jsonl` 34건 (handfeeding 5건 제외). human 12 + oracle 22. dish=T 20 / dish=F 14 / lick=T 25 / lick=F 9.
- [x] **dish-presence 모델 호출 코드** — `infer-dish-presence.py` (Flash) + `oracle-dish-presence.py` (Pro). 39건 완료 → `dish-zeroshot.jsonl`.
- [x] **dish-presence 자체 정확도 측정** — **90% 미달**. dish 79.4% / lick 73.5% / both 67.6%. human GT 12건에선 50%/25% (oracle GT 22건이 정확도 부풀림 — 같은 환각 학습).
- [x] **post-filter 함수** `apply_dish_postfilter(raw, dish, licking)` 구현 (`postfilter.py`). 5 룰 작동 확인.
- [x] **154건 final 정확도 측정** — **84.42% FAIL** (floor 85.7% 미달). recovered 2 / broken 0 / still-wrong-same 23 / still-wrong-changed 1. **메커니즘은 안전(broken=0)하나 활성화 횟수 부족(3/154)**.
- [x] **multi-track ablation 추가 진단** (2026-05-02) — 오답 26건에 5 prompt 변형 호출, 누구도 baseline(A=D=8/26) 못 이김. prompt 보정 불가 6번째 검증.
- [ ] ~~DB 스키마 결정~~ — 폐기.
- [ ] ~~`feature-poc-vlm-web.md` §3-14 추가~~ — 폐기 사유 한 줄로 대체.
- [x] **SOT 동기화** — 분류 파이프라인 변경 없음. 후속 spec 진행 중 명시.
- [x] 본 spec 🗑️ + `specs/README.md` 목록 갱신.

## 4. 설계 메모

- **선택한 방법**: 2단계 분류. VLM(Flash, 9-class)이 행동 차원만 담당, dish-presence(Flash, binary)가 환경 차원 담당. raw 출력이 `{drinking, paste}`일 때만 router 동작.
- **dish_present 정의** (2026-05-01 prompt 보강):
  - 기존 정의 "그릇 보임" → 사용자 사육장(A 환경)은 그릇이 항상 들어 있어 무효. oracle 8건 시범 결과 drinking GT 5건 중 4건이 dish=true로 판정 → binary 시그널 의미 없음.
  - 신규 정의 "**사료가 그릇 안/위에 보이냐**" → 빈 그릇은 false, 사료 담긴 그릇만 true. A 환경(그릇 항상)·B 환경(급여만) 둘 다 일관 작동.
  - 사용자 사실(2026-05-01): 제품 일반은 B 환경(급여 시 그릇 넣었다 뺌), 평가셋 영상은 A 환경(그릇 항상).
- **고려했던 대안**:
  - prompt에 "drinking/paste 통합 후 환경 근거로 분리" 박기 → v3.5 락인 위반 + 룰 5(evidence-forcing) 위험. 폐기.
  - 객체 검출 모델(YOLO) → 라벨링·학습 비용 큼. 장기 후보로 보관.
  - 정적 ROI → 밥그릇 위치 가변. 폐기.
  - 오너 입력 메타("밥 줬어요" 토글) → 입력 UX 비용 + 윈도우 어긋남. 시각 시그널이 더 단순. 폐기.
- **양방향 보정 메커니즘**:
  - raw eating_paste + dish=false → drinking (eating_paste over-trigger 흡수)
  - raw drinking + dish=true → eating_paste (drinking 시각 한계 4건 흡수)
  - 두 false 모드 다 커버.
- **기존 구조와의 관계**: `BEHAVIOR_CLASSES` (raw 9, DB enum 미러)는 그대로 유지. final도 같은 9-class 공간. dish-presence는 추가 컬럼/테이블로 별도 보존.
- **리스크 / 미해결 질문**:
  - dish-presence 모델 자체 정확도가 raw VLM의 분리 정확도(86.2% 안의 drinking/paste 분리분)보다 낮으면 **backfire** — final이 raw 미달. 회귀 가드 의무.
  - "그릇 있음 + 게코는 정수기 핥는 중" 같은 컴포지션 케이스 — dish=true지만 GT는 drinking. 룰만으로 분리 못 함 → 룰 정제(예: dish=true이고 raw가 drinking이면 confidence 임계 적용) 검토.
  - GT 라벨링에서 "그릇 일부만 보이는" 모호 케이스 처리 — oracle reasoning 활용 + 사람 spot check.
  - 5-카테고리 broken 발생 시(raw 정답을 final이 뒤집은 케이스) 즉시 ablation.

## 5. 학습 노트

### 5.1 "fair한 GT"가 self-validating loop이 되는 문제 (2026-05-02)
oracle(Pro)와 router(Flash)에 **동일 prompt**를 쓴 의도는 fairness 확보였다. 그런데 실제론 Pro의 환각("approaches dish → eats from dish")을 Flash가 똑같이 학습 → router 정확도가 oracle GT 대비 95%/100%로 부풀림. human GT 12건으로 검증해야 진짜 정확도(50%/25%)가 보임. **교훈**: Pro→Flash GT 파이프라인은 같은 prompt 쓰면 측정값 인플레이션. cross-prompt 또는 human 검수 필수.

### 5.2 multi-track ablation으로 "prompt 한계" vs "시각 한계" 격리 (2026-05-02)
오답 26건 × 5 track = 130 호출로 검증한 결과, **모든 track이 baseline 동률 또는 회귀**. 가장 큰 그룹 G1(moving→eating_paste 환각, 10건)에서 5/10 천장이 모든 track 공통 — **prompt가 결과를 결정하는 게 아니라 클립의 시각 정보량이 결정**. 같은 5건은 어떤 prompt로도 못 잡고, 다른 5건은 어떤 prompt로도 잡힘. 이는 v3.6/v3.7-A/v3.7-B/v4의 전체셋 회귀(`feedback_vlm_rule_overcorrection`) + 부분셋 ablation 회귀까지 합쳐 6번째 prompt-한계 검증. **교훈**: 부분셋 ablation은 "prompt 시도 종료" 결정의 강한 증거. 향후 같은 종류의 시도를 막는 용도로 재사용 가능.

### 5.3 evidence-forcing 변형 (`donts/vlm.md` 룰 5 강화)
Track B "위치 식별 강조"는 eating_paste 환각을 **줄인 게 아니라 늘림** (15/26 vs A의 7/26). Track C "혀 표면 4지선다"도 동일 패턴. → 명시적 가이드가 모델을 "그 가이드를 따른 답"으로 끌어당기는 evidence-forcing의 변형. 룰 5의 적용 범위를 "negative rules"뿐 아니라 "강한 양성 가이드"로 확장 필요.

### 5.4 broken=0 + recovered 2의 의미
postfilter 5룰이 raw 정답 케이스를 망가뜨리지 않은 것은 메커니즘 자체는 보수적·안전했음을 보여줌. 하지만 활성화가 3/154뿐이라 효과도 제한적. **router 신호 신뢰도가 낮은 상황에선 보수적 룰이 안전하지만 효과도 작다**는 trade-off. 향후 비슷한 2단계 분류 도입 시 회귀 가드 비용을 감안해 활성화 횟수와 신호 신뢰도 둘 다 측정 의무.

## 6. 참고

- 본 레포 spec:
  - [`feature-poc-vlm-web.md`](feature-poc-vlm-web.md) — Round 1~3 전체 결정 이력
  - [`feature-vlm-feeding-merge-ux.md`](feature-vlm-feeding-merge-ux.md) — UI 매핑 (보류, fallback 후보)
- 자동 메모리:
  - `~/.claude/projects/-Users-baek-petcam-lab/memory/project_vlm_v35_baseline_lock.md`
  - `~/.claude/projects/-Users-baek-petcam-lab/memory/feedback_vlm_visual_information_limit.md`
  - `~/.claude/projects/-Users-baek-petcam-lab/memory/feedback_vlm_ux_merge_validation.md`
- SOT: `../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md` (라운드 진화 + 결정 16건)
- 룰: `.claude/rules/donts/vlm.md` 룰 5(evidence-forcing 회피), 룰 6(deterministic config)
