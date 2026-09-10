# 하이라이트 봉인 평가 표본

2.6.1 전환(무조건 전체 적용) 당일 규칙 숫자(10초/5초)를 바로 재보정하기 위한 **사람 O/X 기준선**. 검출기 채택 판정용이 아니다.
계획: `docs/superpowers/plans/2026-09-09-pre-v261-labeling-prep.md` Task 1~5.

## 정의

| 항목 | 값 |
|---|---|
| 표본 id | `eval-2026-09` |
| 후보 | 최근 14일 · 미디어 있음 · 운영 적격 · 활성 계약(`gme-motion-v1` / `deccfc83…`) run 있음 · 사람 확정 없음 |
| 층화 | 카메라 × 규칙 initial(O/X), 층당 최대 30 (후보가 적으면 있는 만큼, 억지로 안 채움) |
| seed | 20260909 (`scripts/build_highlight_eval_sample.py`) |
| 등록 | owner 승인 뒤 `--register` 1회 → `motion_clip_eval_samples` (RPC 전용) |
| 라벨링 | 라벨링 웹 목록의 `📌 평가 표본` 칩 → 평소처럼 O/X. 기존 확정은 재작성하지 않는다 |
| 보고 | `scripts/report_highlight_eval_sample.py` → `<id>-report-<date>.md` (층별 4분할 · 모집단 가중 · 임계값 후보표) |

## 규칙

- 표본 확정이 끝나기 전엔 유지율로 규칙을 바꾸지 않는다. 검출기 전환 뒤 같은 표본에 새 계약 숫자를 붙여(`--contract`) 임계값 후보표를 다시 낸다.
- 단순 합산 회수율은 보고하지 않는다(표본이 O/X 균형 추출이라 모집단과 다름). 층 비중은 후보 수로 가중.
- 옛 3-class GT 를 O/X 로 변환하지 않는다. 사람 교차검증을 복원하지 않는다.
