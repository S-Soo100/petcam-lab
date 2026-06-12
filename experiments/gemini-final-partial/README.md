# Gemini 트랙 클로징 기록 (2026-06-12, 부분 145/202)

**맥락:** 2026-06-07~11 AQ. key 전역 차단이 06-12 풀려서 4버전 × 202건 정량회귀를 병렬
시작 → **63% 지점에서 사용자 결정으로 중단** ("Gemini API 호출 포기, Claude 구독 트랙으로
피벗" — `specs/experiment-claude-montage-v2.md` 참조). 이 폴더가 Gemini 트랙의 마지막 정량 기록.

- 4런이 같은 클립을 같은 순서(clip_id 정렬)로 처리 → **145건 paired 교차비교 유효**
- GT는 2026-06-09 정정(drinking 4건→moving) **반영 후** 기준. 145건은 202의 비무작위
  부분집합(clip_id 앞쪽)이라 절대치는 공식 수치 아님 — 버전 간 Δ 위주로 읽을 것
- jsonl 4개 = clip별 raw (action/conf/reasoning/tokens/GT). REPORT.txt = 통합 채점
  (`scripts/_compare_regression_versions.py`, 경로만 이쪽으로 바꾸면 재현)

## 헤드라인 (145건 paired)

| version | P0 feeding-merged | OOD recall | 비고 |
|---|---|---|---|
| v3.5 | **82.2%** | 0/16 (구조적) | 클로징 기준선 |
| v3.6 | 73.4% | 16/16 | OOD 완벽, P0 큰 퇴행 (moving 60%) |
| v3.6.1 | **78.3%** | 16/16 | v3.6+ 중 최선 |
| v3.6.2-draft | 76.0% | 16/16 | ⚠️ IR 가드가 Gemini에선 **-2.3%p 퇴행** |

## 교훈 (피벗 후에도 유효)

1. **표적룰은 모델 특이적** — P3 IR shedding 가드: Sonnet +6.9%p(투영) ↔ Gemini -2.3%p.
   한 모델의 실패모드 패치를 다른 모델에 이식하면 역효과. 프롬프트-모델 쌍 단위로 검증할 것.
2. **OOD(hand_feeding) 룰은 v3.6+ 전 버전 16/16** — OOD 설계 자체는 모델 무관하게 견고.
3. v3.6 계열의 P0 손실 주범은 moving 과탐 전이(v3.5 76% → v3.6 60%) — OOD 클래스 추가가
   기존 클래스 경계를 흔드는 비용 실측.
