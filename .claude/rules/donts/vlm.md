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

---
**상태:** 초기 추정. 재발 시마다 `.claude/donts-audit.md`에 기록하고, 3회 쌓이지 않으면 정리.
