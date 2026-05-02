# HISTORY — 라운드 진화 + 시도/폐기 이력

> v1 첫 시도부터 v3.5 production 락인까지. 다른 에이전트가 같은 함정에 빠지지 않도록 압축 정리. 결정 22건 중 외부 검토 시 알아야 할 핵심만.

---

## 타임라인

| 시점 | 라운드 | 결과 | 핵심 |
|---|---|---|---|
| 2026-04-25 | Round 1 (v1~v3.4) | raw 76.3% → 81.8% | 9-class 정의 + prompt 진화 + temperature 0.1 결정 |
| 2026-04-30 | Round 2 (v3.5) | feeding-merged **85.5%** (136/159) | drinking+eating_paste UI 통합 + hiding 폐기 + production 락인 |
| 2026-05-02 | Round 3 후속 (UX 통합 + 검증) | 동일 85.5% baseline | UI 매핑 적용 + DB SOT 정합 + portable 패키지 분리 + **86.2% 오기재 정정** |

---

## Round 1 — 9-class baseline 잡기 (v1 ~ v3.4)

### 시작
- 단일 가설: "Gemini 2.5 Flash zero-shot으로 크레스티드 게코 9 클래스 행동 분류 70%+ top-1"
- 70% 미달 시 → 프롬프트/few-shot/모델 변경. 50% 미달 시 → Phase 2 YOLO 직진.

### 진화 (압축)
- **v1**: bare prompt, 65% 수준
- **v2**: species context + tie-break 우선순위
- **v3.0~v3.3**: 각 클래스 정의 정밀화 + 부정 예시
- **v3.2 사고**: "타임스탬프와 함께 근거를 적어라" rule 추가 → 76.3% → **73.7% 퇴행** ([룰 5 donts/vlm.md](../.claude/rules/donts/vlm.md))
  - 모델이 "근거 적어라" 룰을 "정답이라고 우길 근거 적어라"로 해석 → 가짜 timestamp 만들어 오답 정당화
  - 즉시 롤백
- **v3.3 사고**: temperature 미지정 = 1.0 → 같은 클립 호출마다 라벨 흔들림 (drinking → moving → drinking) → 평가 noisy → prompt 효과 측정 불가
  - **temperature 0.1 + topP 0.95 + responseMimeType json** 박음 ([룰 6](../.claude/rules/donts/vlm.md))
- **v3.4**: shedding 클래스 추가 (9 → 9, eating_prey 미세 조정)

### 결과
- raw 81.8% / feeding-merged 83.6% (159 평가셋)

---

## Round 2 — UX 통합 + 85.5% 락인 (v3.5)

### 결정 핵심 (Round 2 진입 시 4건)

| # | 결정 | 검증 |
|---|---|---|
| #17 | **drinking + eating_paste → `feeding` UI 통합** | 평가 레이어 매핑으로 GT 29건 → feeding 예측 27/29 = **93.1%** |
| #18 | **hiding 클래스 폐기** (9 → 8) | motion-trigger 카메라에서 "은신처 정지"는 데이터 자체 부재 |
| #19 | eating_prey **stalking 포함** 정의 | 사용자 직관 ("사냥 자세도 사냥") 정합 |
| #20 | **HITL** (Human-in-the-Loop) 도입 결정 | 모호 케이스 1-tap 정정 → GT 자동 수집 |

### v3.5 prompt 변경

- 8 클래스로 명시 (hiding 제거)
- rule 7: eating_prey stalking 정의 명시
- rule 9: shedding vs eating_prey 구분 (둘 다 입 움직임)
- temperature 0.1 그대로

### 결과 (159건 평가)

| 매핑 | 정확도 |
|---|---|
| raw 9-class | 130/159 = 81.8% |
| **feeding-merged (UI)** | 133/159 = **83.6%** |
| **feeding + hiding-merge (eval only)** | **136/159 = 85.5%** ← **production baseline 락인** |

---

## Round 3 — baseline 깨기 시도 6번, 모두 실패 (2026-04-30 ~ 2026-05-02)

prompt tuning이 더 정확도 올릴 수 있는지 검증. 결과는 **모두 floor 미달**.

### 폐기 6종

| 시도 | 변경 | 결과 (delta vs 85.5%) | 학습 |
|---|---|---|---|
| **v3.6** | rule 강화 (evidence-forcing 추가) | **−1.9%p** | confabulation 재현 (룰 5 검증) |
| **v3.7-B** | rule 약화 (일부 제거) | **−5.0%p** | 누적된 도메인 룰의 가치 확인 |
| **v4** | clean-slate 재작성 | **−6.9%p** | 처음부터 다시 짜는 ROI 0 |
| **Track B** | confidence threshold 분기 | 무용 | confidence calibration 안 됨 (0.95+도 76% 정확도) |
| **Track C/D/E** | few-shot · 분기 룰 | 동률/퇴행 | 같은 시각 정보 다른 표현 → 동일 한계 |
| **dish-postfilter** | binary 라우터 (dish_present + licking) | 154건 84.42% (floor 85.7%) | binary 라우터도 prompt 레이어 — 같은 한계 |

### 결론

잔존 오답 26건의 본질 = **시각 정보 한계**. 영상 픽셀에 정답 신호가 없음 (drinking ↔ eating_paste 같은 dish 같은 자세 등). prompt/모델 변경으로 못 풀음.

### 다음 정공법 (Round 3 후속)

prompt tuning ROI 0 결론에 따라 **다른 채널** 3축:

| 카드 | 상태 | 적용 대상 |
|---|---|---|
| **(A) UX feeding-merge** ✅ 완료 (2026-05-02) | drinking + eating_paste → `feeding` UI 통합. raw DB 보존. | 잔존 오답 G3 (drinking 4건) |
| **(C) HITL ping** 🚧 spec 단계 | 일일 5건 + opt-in. confidence<0.7 또는 confusion-prone class 트리거. | G2 (defecating 5) + G4 (eating_prey 3) + G5 (shedding 3) |
| **(B) 메타데이터 보강** 미착수 | dish detection / before-after / 시간대 컨텍스트 | TBD |

---

## 잔존 오답 26건 그룹화 (Round 3 ablation 분석)

| 그룹 | 패턴 | 건수 | 처방 |
|---|---|---|---|
| G1 | moving → eating_paste (over-trigger) | 12 | UX 매핑 + HITL 정정 |
| G2 | defecating mismatch | 5 | HITL ping (모호) |
| G3 | drinking → eating_paste / vice versa | 4 | UX 매핑 ✅ |
| G4 | eating_prey mismatch | 3 | HITL ping |
| G5 | shedding mismatch | 3 | HITL ping |
| 기타 | hiding/unseen edge | 2 | 무시 |

**G3 (UX 매핑 적용 후 흡수)**: 4건 → 화면에서 자동 정답 처리.
**G2 + G4 + G5 (11건)**: 묶을 카운터파트 없음 → HITL 필수.
**G1 (12건)**: moving over-trigger는 prompt + UX 매핑으로도 잔존 → HITL 보조.

---

## 결정 22건 중 외부 검토 핵심 8건

| # | 결정 | 한 줄 |
|---|---|---|
| #2 | Gemini 2.5 Flash | 영상 native + 비용 (Pro 1/10) |
| #5 | 8 클래스 (raw 9 보존) | hiding 폐기 + drinking/eating_paste UI 통합 |
| #17 | drinking + eating_paste → feeding | 시각 구분 불가, 평가 검증 93.1% |
| #18 | hiding 폐기 | motion-trigger 카메라 ↔ 정의 충돌 |
| #19 | eating_prey stalking 포함 | 사용자 직관 정합 |
| #20 | HITL 도입 | UX + GT 자동 수집 + 진단 |
| #21 | v3.5 production 락인 | baseline 깨기 6번 모두 퇴행 |
| #22 | 다음 layer 3축 (A/B/C) | prompt tuning ROI 0 결론 |

전체 22건은 본 레포 SOT [`tera-ai-product-master/docs/specs/petcam-poc-vlm.md`](../../tera-ai-product-master/docs/specs/petcam-poc-vlm.md).

---

## 학습 요약 (다른 에이전트 onboarding)

### 효과 검증된 방법
1. **temperature 0.1 + JSON 강제** — 분류 task 결정성 ([룰 6](../.claude/rules/donts/vlm.md))
2. **클래스 정의 정밀화** — 부정 예시 + tie-break 명시
3. **UX 매핑 (raw 보존)** — 시각 한계는 표시 레이어에서 흡수

### 검증된 안티패턴 (반복 금지)
1. **evidence-forcing rule** — "근거 적어라" 룰 추가 → confabulation. 모델이 가짜 근거 만듦.
2. **confidence threshold 단독** — 0.95+도 76% 정확도. calibration 안 됨.
3. **clean-slate 재작성** — 누적된 도메인 룰 가치 ↑↑. -6.9%p 퇴행.
4. **binary 라우터 post-filter** — 같은 시각 정보로 같은 모델 호출 = 같은 한계.

### 미검증 (시도 가치)
1. **다른 모델 영상 입력** — Anthropic Claude / OpenAI GPT-4o / Gemini Pro 비교
2. **fine-tune** — HITL 답 충분히 누적 후
3. **메타데이터 보강** — dish detection 등 외부 시그널
4. **사용자별 모델 보정** — per-user few-shot
