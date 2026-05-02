# Don'ts — VLM / LLM API

> Round 1+ 영상 라벨링·VLM 작업에서 반복될 만한 실수. 루트 [`../donts.md`](../donts.md)의 제너럴 규칙과 함께 적용.
> 현재는 초기 추정치이므로 실제 재발 시에만 유지, 아니면 삭제.

## 🤖 모델 선택

1. **이미지 판정·라벨링 디폴트는 Sonnet 4.6 이상** — VLM은 텍스트 분류보다 모델 간 격차가 훨씬 큼. Round 1 경험상 Haiku는 신뢰도 부족(eating_paste/tongue_flicking 같은 미세 행동 판정에서 일관성 떨어짐). Haiku는 단순 분류·regex 결과 검증·메타 분류 같은 보조 작업에만.
2. **결정론적 처리 우선, LLM은 폴백** — 구조화 텍스트(파싱·룰 매칭·rule-based 판정)는 regex/heuristic 먼저 (실측 95%+ 처리). 저신뢰 케이스만 LLM. 이유: 비용 + 재현성. ECC 스킬 `regex-vs-llm-structured-text` 참고.

## 💰 비용 추적

3. **비용/파싱 결과는 immutable로 누적** — `@dataclass(frozen=True, slots=True)`로 `CostRecord`/`ParsedItem` 모델링. 새 항목 추가 시 새 인스턴스 반환, 절대 mutate 금지. 안 그러면 "이번 배치 왜 $X 썼지" / "어느 항목이 LLM 폴백 탔지" 추적 불가능.

## 🔁 재시도 정책

4. **LLM API retry는 일시 에러만** — `RateLimitError` / `APIConnectionError` / `InternalServerError` (Anthropic SDK 기준) 만 exponential backoff (최대 3회). `AuthenticationError` / `BadRequestError` / `PermissionDeniedError` 는 즉시 raise. 영구 실패에 retry = budget 낭비.

## 📝 프롬프트 작성

5. **"근거 강제(evidence-forcing) 룰" 신중 도입** — "타임스탬프 명시 필수" / "관찰된 근거 인용 필수" 같은 룰은 환각을 줄이는 게 아니라 **부풀린다**. Round 1 v3.2 사고 사례: "타임스탬프와 함께 근거를 적어라" 룰 추가 → 모델이 오답을 정당화하기 위해 가짜 timestamp("12초경 밥그릇 앞으로 가는것 확인")를 만들어냄. 76.3% → 73.7% 퇴행.
   - **Why:** 모델은 "근거를 적어라"를 "정답이라고 우길 근거를 적어라"로 해석함. 빈약한 시각 근거를 **확신에 찬 서사**로 포장 (Gemini critic 표현: "confabulation").
   - **How to apply:** "근거 강제" 룰 도입 전에 (a) 모호 케이스에서 모델이 "uncertain" / 낮은 confidence를 자연스럽게 낼 수 있게 confidence 가이드부터 강화. (b) 도입할거면 **즉시 reinference로 부작용(broken) 측정**, 회복(recovered)만 보고 채택 금지. (c) 의심되면 **롤백 우선**.

6. **분류/판정 task는 generationConfig 명시** — `temperature` 미지정 = 기본 1.0(또는 0.7~1.0 범위) = 같은 입력에도 호출마다 다른 출력. Round 1 사고 사례: 같은 클립 3회 호출 → drinking → moving → drinking, label이 흔들림 → 평가 자체가 noisy → 프롬프트 효과 측정 불가.
   - **Why:** 분류는 generative와 달리 결정론적 출력이 정답에 가까움. 다양성/창의성이 필요 없음.
   - **How to apply:** Gemini는 `{temperature: 0.1, topP: 0.95, responseMimeType: 'application/json'}` 박아둘 것. Anthropic은 `temperature: 0` 또는 `0.1`. JSON 응답 강제도 함께 — 정규식 fallback 제거 가능.

---
**상태:** 룰 5, 6은 Round 1 v3.2/v3.3 사이 사고로 추가됨 (2026-04-28). 재발 시 audit 기록.
