# for-cross-review — 외부 에이전트 교차 리뷰 가이드

> 다른 LLM/에이전트(GPT-5, Claude, Gemini Pro, etc.)에게 이 패키지를 전달할 때 함께 보낼 지시문. 4가지 리뷰 유형별로 분리.

---

## 사용법

이 파일과 함께 `vlm-classifier-portable/` 디렉토리 통째로 전달. 외부 에이전트에게:

> "vlm-classifier-portable/ 디렉토리를 읽고, [for-cross-review.md §X] 형식으로 리뷰해줘."

§ 번호로 어떤 리뷰가 필요한지 지정.

---

## §1. Prompt critique (프롬프트 비판)

**목적:** 현재 v3.5 prompt의 약점 발견. 안티패턴 회피하면서 개선 방향 제안.

### 지시문

```
vlm-classifier-portable/prompt/system_base.md 와 species/crested_gecko.md를 읽고
prompt critique를 수행해줘.

읽기 순서:
1. README.md (1분 컨텍스트)
2. CHALLENGE.md §3 (안티패턴 4종 — 절대 추천 금지)
3. prompt/system_base.md
4. prompt/species/crested_gecko.md
5. HISTORY.md (왜 지금 이 형태가 됐는지)

리뷰 항목:
- 프롬프트 구조의 약점 (모호함, 충돌, 빠진 정의)
- 9 클래스 정의 중 시각적으로 구분하기 어려운 페어
- 안티패턴 4종 재현 위험이 있는 룰

출력 양식:
1. 발견한 문제 N개 (각각 한 줄 + 근거)
2. 문제 별 처방 (안티패턴 회피 명시)
3. 시도 우선순위 (impact x cost)

금지:
- "evidence-forcing" 룰 (타임스탬프/근거 적어라) 추천 금지 — Round 1에서 -2.6%p 검증
- "confidence threshold 단독 분기" 추천 금지 — Round 3에서 무용 검증
- prompt clean-slate 재작성 추천 금지 — Round 3에서 -6.9%p 검증
- 채택 권장 시 반드시 "재추론 + 5-카테고리 비교 후 결정" 명시
```

---

## §2. Code review (코드 리뷰)

**목적:** eval/ 코드 품질 검증. 평가 자체가 정확한지.

### 지시문

```
vlm-classifier-portable/eval/ 의 Python 코드를 리뷰해줘.

읽기 순서:
1. README.md
2. data/README.md (jsonl 형식)
3. data/classes.json (매핑 룰)
4. eval/README.md
5. eval/run.py (모델 호출 + 출력)
6. eval/analyze.py (정확도 계산)
7. eval/compare.py (5-카테고리 분석)

리뷰 항목:
- 평가 로직 정확성 (raw/feeding-merge/eval-only-extra 정확히 적용?)
- model adapter 추상화 (Gemini → Anthropic/OpenAI 포팅 가능?)
- 안전성 (API key, retry, error handling)
- 재현성 (random seed, ordering 일관성)
- 테스트 커버리지 (있다면)

출력 양식:
- Critical bugs (우선순위 높음, 평가 결과 왜곡 가능성)
- Logic issues (정확도 계산 의심)
- Code quality (네이밍, 구조, DRY)
- Suggestions (포팅 편의성, 확장)

금지:
- 과잉 리팩토링 추천 금지 — 평가 로직 정확성이 우선
- DRY 규칙 강박 — 5줄 helper 분리 < 5줄 인라인 (가독성 우선)
```

---

## §3. Model comparison (모델 비교)

**목적:** Gemini Flash 한계가 모델 한계인지 검증. 다른 모델로 같은 평가셋 재실행 → 비교.

### 지시문

```
vlm-classifier-portable/ 데이터셋으로 다른 모델 비교 실험 진행해줘.

읽기 순서:
1. README.md
2. CHALLENGE.md (특히 §4-A: 다른 모델 영상 입력 비교)
3. data/eval-159.jsonl (Gemini Flash baseline 출력)
4. data/gt-159.jsonl (GT 라벨)
5. prompt/system_base.md + species/crested_gecko.md (current prompt)

실행:
1. 같은 prompt로 다른 모델 (Anthropic Sonnet 4.6+, GPT-4o, Gemini Pro 등) 호출
2. 동일 형식 jsonl 출력 (eval-{model}.jsonl)
3. CHALLENGE.md §5 평가 절차 적용
4. 5-카테고리 비교 (Gemini Flash baseline vs new model)

출력 양식:
- 모델 별 정확도 표 (raw / feeding-merged / production baseline)
- Δ vs Gemini Flash 85.5% (+/- %p)
- 5-카테고리 분포 (held-correct / recovered / broken / still-wrong-same / still-wrong-changed)
- 비용 비교 (call-per-clip, total)
- 모델 별 강점/약점 (어떤 클래스에서 이김/짐)
- 채택 권장 여부 (Δ > +3%p AND recovered > broken AND 비용 합리)

주의:
- 영상 입력 지원 확인 (Anthropic은 vision/video 지원, OpenAI는 frame extraction 필요할 수 있음)
- temperature 0.1, JSON 응답 강제 — 모델별 동일하게 적용
- prompt 변경 금지 — 모델 효과 단독 측정
```

---

## §4. Residual mismatch validation (잔존 오답 검증)

**목적:** 26 잔존 오답이 정말 시각 한계인지, prompt로 풀 수 있는지 다른 모델 시각으로 재판정.

### 지시문

```
vlm-classifier-portable/ 의 잔존 오답 26건이 정말 "시각 한계"인지 검증해줘.

읽기 순서:
1. README.md
2. CHALLENGE.md §2 (그룹 G1~G5 분류)
3. data/eval-159.jsonl + data/gt-159.jsonl
4. HISTORY.md (왜 시각 한계로 결론났는지)

작업:
1. eval과 gt 비교 → 오답 26건 추출 (eval action != gt action, eval-only-extra 적용 후)
2. 영상 클립 ID 리스트 (clip_id 26개)
3. 각 클립을 다른 모델 (가급적 vision-strong: Gemini Pro, Anthropic Sonnet 4.6+ vision)로 단독 분석
4. 그룹별 검증:
   - G1 (12건, moving over-trigger): 다른 모델도 eating_paste로 잘못 갈까?
   - G2 (5건, defecating): 다른 모델은 인식 가능한가?
   - G3 (4건, drinking ↔ eating_paste): 진짜 시각적으로 같나?
   - G4/G5 (6건, eating_prey/shedding): 모호한 거 맞나?

출력 양식:
- 그룹별 표: 다른 모델의 답 / Gemini Flash 답 / GT
- 일치율 (다른 모델이 GT 맞춘 비율)
- 결론:
  - "시각 한계 검증" — 다른 모델도 GT 못 맞추면 → HITL 정공법 유지
  - "Flash 한계 발견" — 다른 모델은 맞추면 → 모델 교체 검토
  - "GT 의심" — 사람도 헷갈릴 만한 케이스면 → GT 재검토 필요

주의:
- 26건 cherry-pick 자체로 결론 X. 100건+ 평가가 정공법 ([feedback memory](feedback_vlm_cherry_pick_diagnostic.md)).
  → 이 §4 결과는 "방향 결정용"으로만, 채택 결정은 §3 model comparison으로.
```

---

## 모든 리뷰 공통

### 결과 보고 양식

CHALLENGE.md §7 양식 따를 것:

```markdown
## 시도: {짧은 이름}

### 변경
- {prompt/model/code 어디 어떻게}

### 결과 (159건 평가)
- raw: {X}/159 = {X.X}%
- feeding-merged: {X}/159 = {X.X}%
- production baseline: {X}/159 = {X.X}% (vs 85.5%, Δ = ±X.Xp)

### 5-카테고리
- held-correct: {N}
- recovered: {N}
- broken: {N}
- still-wrong-same: {N}
- still-wrong-changed: {N}

### 결론
- 채택 권장: YES/NO ({이유})
- 다음 단계: {있다면}
```

### Cross-check 권장

여러 에이전트의 결과를 받았다면:
- **합의 시도** — 같은 처방을 여러 에이전트가 추천하면 가중치 ↑
- **불일치 시도** — 한 명만 추천하면 더 깊은 검증 필요
- **자기 동의 편향 주의** — 같은 모델 자기 리뷰 금지 ([CLAUDE.md donts.md rule 6](../CLAUDE.md))
