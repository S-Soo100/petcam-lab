# REPORT — gate detector recall/specificity 검증

> 실행 후 (2026-07-07). 시험지: `TEST-SHEET.md`.

## 1. 결과 표

| 지표 | 값 |
|---|---|
| 매칭 | 300/300 (detector 에러 0) |
| detector visible 총 | 248/300 (83%) |
| claude 게코있음(moving+shedding 220) | detector 봄 **200** / 놓침 FN **20** |
| claude unseen(80) | detector 안봄 **32** / 오탐 FP **48** |
| **recall** | **90.9%** (200/220) |
| **specificity** | **40.0%** (32/80) |
| bbox unique | 223/248 (거의 다 다른 위치) |

## 2. 시험지 대비
- 변경 없음.

## 3. 가설 판정
- **H1 기각, H0 유지.** recall 90.9% < 95% AND specificity 40% < 50% — 둘 다 미달.

## 4. decision: **reject** (현 detector v2 · threshold 0.25 기준)
- recall < 95% → 시험지 하드룰상 reject.
- 실질 의미: gate 를 지금 켜면 **claude 가 게코라 본 것의 9%(20개)를 detector 가 놓쳐** 케어행동 손실 위험. 게다가 specificity 40% 라 **unseen 80개 중 32개만 걸러** claude 절감도 기대(≥50%) 이하.

## 4b. threshold sweep (A안, 2026-07-07) — 실패

`detected_objects` raw score 재활용, 재추론 없이 0.10~0.60 sweep:

| thr | recall | specificity |
|---|---|---|
| 0.10~0.25 | **90.9%** | 40.0% |
| 0.30 | 90.0% | 41.2% |
| 0.50 | 85.9% | 42.5% |
| 0.60 | 81.4% | 43.8% |

- **어느 threshold도 recall ≥ 95% 불가. recall 천장 = 90.9%.**
- 원인: FN 20개는 detector 검출 score = 0(게코 완전 놓침) → threshold 를 낮춰도 못 살림. specificity 도 44%가 상한.
- → threshold 튜닝으로 gate 부적합 **확정**. A안 종료, B(육안)/C(재학습)로.

## 5. 해석 / 한계
- **스모크 오탐 우려(bbox 고정)는 과했음** — 전수 bbox 223 unique 로 대부분 다른 위치. 스모크 5개가 연속 시각(20:00~20:05)이라 게코가 안 움직여 같은 위치였던 것. 고정 배경 오탐은 아님.
- **claude 프록시 GT 한계 (핵심)**: 불일치 68개(FN 20 + FP 48)는 claude·detector 중 누가 맞는지 GT 없이 모름.
  - FN 20 = claude "게코있음" ↔ detector "없음": claude 오답(moving 오판)일 수도, detector 놓침일 수도.
  - FP 48 = claude "unseen" ↔ detector "visible": detector 오탐일 수도, **claude 가 놓친 게코를 detector 가 잡은** 것일 수도.
  - → 진짜 성능은 이 68개 **육안 확인** 후에 확정.

## 6. 다음 액션
1. **불일치 68개 육안 검증** (사람 GT) → recall/specificity 재산정. 특히 FP 48 중 "detector 가 맞은" 비율이 높으면 실제 성능은 더 좋을 수 있음.
2. **threshold sweep** — 0.25 고정 대신 0.1~0.5 곡선으로 recall-specificity 트레이드오프 확인 (recall↑ 하려 낮추면 specificity↓ 딜레마 예상).
3. 위 둘로도 recall ≥95% 못 넘으면 **detector 재학습(v3)** — 이 야간 IR clip 의 오답을 학습셋에 추가.
- **당장 gate 를 production 자동화에 켜지 않는다.** 활동 프로파일(claude 0)은 예정대로 진행, 행동 분석 gate 는 위 개선 후 재검증.
