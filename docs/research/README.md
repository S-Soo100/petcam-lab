# 연구 중앙 카탈로그

> 마지막 정리: 2026-07-27 · 기계용 원장: [`catalog.json`](catalog.json)

이 디렉터리는 연구의 **찾기·판정·재개점**을 모은 중앙 카탈로그야. 원문 설계·시험지·보고서는
각 실험과 레포에 그대로 남아 있고, 여기서는 옮기거나 요약으로 대체하지 않아.

## 지금 할 일

1. 사람 이중 블라인드 GT를 2~3주 축적한다.
2. 위험 VLM action 3회 consensus shadow는 설계만 완료된 상태다. Lab 원장 구현부터 clean session으로 재개한다.
3. production 결과·selector·prompt·ROI는 위 두 연구의 fresh evidence가 쌓이기 전까지 바꾸지 않는다.

## 상태표

| ID | 상태 | 결론 | 다음 허용 행동 |
|---|---|---|---|
| `owner-gt-audit-20260727` | 제한적 유효 | 172 GT는 진단 입력으로 유효, 일반화에는 부족 | fresh 이중 블라인드 holdout과 결합 |
| `owner-gt-python-evidence-benchmark-20260727` | 기각 | `roi_mean` 공통 motion 신호 가설 불성립 | 새 camera-specific 가설은 새 시험지 필요 |
| `unified-gt-failure-audit-20260727` | 제한적 유효 | historical failure 후보를 좁힘 | 후보 생성·재현에만 사용 |
| `visibility-bbox-roi-20260727` | 기각 | 현행 반복 실패 표적이 최소치보다 부족 | 판정 변동·fresh GT 후 재제안 가능 |
| `vlm-risk-consensus-shadow-v1` | 계획됨 | 위험 action만 3회 shadow로 변동 측정 | Lab 원장 구현 → worker 구현 → 별도 배포 승인 |
| `double-blind-fresh-ground-truth` | 진행 중 | 두 라벨러 독립 제출과 Owner 해소를 축적 | 2~3주 뒤 VLM shadow와 대조 |
| `python-evidence-croi-throughput` | 제한적 검증 | 전처리 처리량은 확인 | 정확도·자동제외 근거로 사용 금지 |
| `local-router-v0-v2-validity-audit` | 대체됨 | 이전 결과는 adoption 무효 | router-cost-v2의 fresh holdout만 재개 가능 |
| `gate-v3-human-holdout` | 계획됨 | Gate는 visibility/bbox evidence 센서 | 다환경 사람 GT·future holdout 확보 |

## 트랙 경계

| 트랙 | 하는 일 | 하지 않는 일 |
|---|---|---|
| 사람 GT | 독립 라벨·불일치 해결·fresh holdout | 한 사람 의견을 합의 GT로 취급 |
| Claude/VLM 품질 | 같은 입력에서 판정 정확도·변동 측정 | local router 결과를 정답으로 사용 |
| Python Evidence | 처리량·raw sensor evidence 측정 | 행동 자동 판정·자동 제외 |
| Gate | 게코 보임·confidence·bbox evidence | drinking/feeding 같은 행동 확정 |
| Local router | cloud VLM 호출 우선순위 연구 | 자동 skip/auto-label |

## 원문으로 가기

- 현재 연구 정본: [`../specs/next-session.md`](../../specs/next-session.md)
- 실험 전체 인덱스: [`../../experiments/INDEX.md`](../../experiments/INDEX.md)
- Owner GT → ROI → consensus 정리: [`../handoff-prompts/2026-07-27-owner-gt-visibility-consensus-closure.md`](../handoff-prompts/2026-07-27-owner-gt-visibility-consensus-closure.md)
- 보존·정리 정책: [`RETENTION.md`](RETENTION.md)

## 카탈로그 갱신 규칙

- 새 연구는 TEST-SHEET와 REPORT가 생긴 뒤 `catalog.json`에 추가한다.
- 결과가 기각·보류여도 삭제하지 말고 `do_not`과 재등판 조건을 기록한다.
- 외부 레포 문서는 `repo-relative path + 확인 commit`으로 링크한다.
- 원문과 카탈로그가 다르면 원문이 우선이며, 다음 정리에서 카탈로그를 고친다.
