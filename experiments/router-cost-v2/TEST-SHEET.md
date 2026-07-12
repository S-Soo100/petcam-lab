# router-cost-v2 테스트 시험지 (Test Sheet)

> 규칙: [연구 테스트 프로토콜](../../.claude/rules/research-testing.md). **실행 전 고정 — 사후 변경 금지.**
>
> 선행 근거: [Router Research Validity Audit](../../reports/router-research-validity-audit-20260712/REPORT.md) · [Router 연구 데이터 역할 등록부](../../reports/router-research-validity-audit-20260712/DATA-ROLE.md)

**실험 ID:** `router-cost-v2` · **작성일:** 2026-07-12 · **상태:** 🟡 실행 전 / 사용자 승인 대기

이 문서는 threshold를 수정하기 전에 동결할 독립 비용 검증 계약의 승인안이다. 사용자 승인 전에는 inference, threshold tuning, DB write, R2 write를 하지 않는다. 승인 과정에서 숫자나 계약을 수정할 수 있지만, 승인·동결 뒤 결과를 보고 수정하면 기존 표본은 독립 holdout 자격을 잃는다.

## 1. 가설

- **H0 (귀무):** frozen router는 전수 저비용 VLM baseline 대비 총비용을 줄이지 못하거나 P0 event recall을 허용 범위 이상 훼손한다.
- **H1 (대립):** frozen router는 P0 event recall 허용 범위를 지키면서 total eventual VLM cost를 유의미하게 줄인다.

H1은 비용 gate와 안전성 gate를 모두 통과해야 채택한다. 즉 비용만 줄거나 recall만 유지되는 결과로는 H1을 지지하지 않는다.

## 2. 비교 정책과 route 비용 계약

### 비교 정책

- **Baseline:** 같은 평가 표본의 모든 clip을 동일한 저비용 VLM으로 분석한다. 실제 호출 수, 입력·출력 토큰과 당시 원화 환산 비용을 기록한다.
- **Candidate:** inference 전에 version, feature schema, route rule, threshold, local model/prompt가 있으면 그 버전까지 동결한 router를 사용한다.
- 두 정책은 동일 clip list와 동일 P0 ground truth로 비교한다. baseline과 candidate의 VLM 모델·입력표현·프롬프트 버전은 승인 시 기록하고 평가 중 바꾸지 않는다.

### route별 실제 후속 처리 계약

| route | 동결할 후속 처리 | 비용·지연 집계 계약 |
|---|---|---|
| `cloud_now` | 저비용 VLM 분석을 즉시 예약한다. | 실제 eventual VLM 호출·토큰·KRW를 모두 집계한다. clip 촬영 종료부터 분석 결과 완료까지 최대 5분 이하여야 한다. |
| `cloud_later` | 저비용 VLM 분석을 지연 예약한다. 영구 skip이 아니다. | 실제 eventual VLM 호출·토큰·KRW를 모두 집계한다. `cloud_now -> cloud_later` 이동만으로는 비용 절감으로 세지 않는다. clip 촬영 종료부터 분석 결과 완료까지 최대 12시간 이하여야 한다. |
| `review_candidate` | 사람이 먼저 검수하고, 승인 시 동결된 저비용 VLM 분석으로 보낸다. | 사람 검수 시간을 전부 기록하며, 실제로 발생한 조건부 VLM 호출·토큰·KRW도 eventual cost에 포함한다. 미검수 backlog를 비용 0으로 간주하지 않는다. |
| `activity_only` | VLM과 사람 검수 없이 activity metadata만 남긴다. | eventual VLM 호출은 0건으로 집계한다. 단, P0 label clip이 이 route로 가면 즉시 안전성 gate 실패다. |

`total eventual VLM cost`는 평가 horizon 안에 즉시 또는 지연·검수 후 실제 발생한 모든 VLM 호출의 원화 비용 합계다. route 이름이나 최초 queue 위치가 아니라 최종 후속 처리를 기준으로 센다. 사람 검수 부담은 VLM 비용과 별도 지표로 보고하며, 숨은 운영 비용을 막기 위한 독립 gate로 적용한다.

## 3. 독립 표본과 오염 방지

### future holdout 구성

- 이 시험지의 사용자 승인과 정책·threshold 동결 **이후 촬영된 미래 날짜**만 사용한다.
- 연속 14박 이상을 평가하고, 최소 300 labeled clips와 최소 30 labeled P0 events를 확보한다. 셋 중 하나라도 부족하면 결론을 내리지 않고 표본 수집을 연장한다.
- 기존 camera/개체와 신규 camera/개체를 층화하고, 각 층의 clip 수·P0 event 수를 보고한다.
- 같은 밤의 clip을 train과 eval로 나누지 않는다. camera-night를 분할 최소 단위로 사용한다.
- sample seed와 최종 clip list를 inference 전에 고정하고, 승인 시 seed·생성 절차·`sample_list` 경로와 SHA-256을 이 문서에 추가한 뒤 상태를 `🔒 고정(실행 대기)`로 바꾼다.

### 기존 오염 데이터 제외

[데이터 역할 등록부](../../reports/router-research-validity-audit-20260712/DATA-ROLE.md)에 따라 다음 데이터와 여기서 파생된 review label·부분집합은 future holdout에서 제외한다.

- `dataset203`
- `operational 72`
- `v1 demote 60`
- `v1 review 150`
- `v1.1 review 150`

이 기존 데이터는 EDA, failure analysis, regression 또는 training에만 사용할 수 있다. 이름 변경이나 재라벨링으로 독립성이 복원되지 않는다. 평가 결과를 본 뒤 threshold, route rule, feature, prompt 또는 모델을 수정하면 해당 future set도 즉시 training/EDA로 강등하고, 다시 동결한 뒤 더 미래의 비중복 밤으로 새 평가를 시작한다.

### 승인 시 채울 동결 필드

| 항목 | 승인·동결 값 |
|---|---|
| 촬영 시작일 / 종료 조건 | 승인 후 날짜 / 연속 14박 이상 및 최소 표본 충족 |
| camera·개체 strata | 사용자 승인 시 확정 |
| sample seed | 사용자 승인 시 확정 |
| clip list 경로 / SHA-256 | inference 전 확정 |
| frozen router 버전 / commit | 사용자 승인 시 확정 |
| feature schema / threshold | 사용자 승인 시 확정 |
| baseline VLM / 입력 / prompt | 사용자 승인 시 확정 |
| KRW 환산 기준 | 실행 시점 공급자 실청구 또는 승인된 단가표 |

## 4. 측정 지표와 산식

- **eventual VLM call rate:** 평가 horizon 안에 실제 VLM이 한 번 이상 호출된 고유 clip 수 / 전체 평가 clip 수. `cloud_now`, `cloud_later`, `review_candidate`의 실제 후속 호출을 포함한다.
- **KRW/camera/night:** total eventual VLM cost / 고유 camera-night 수. baseline과 candidate를 같은 표본에서 각각 계산한다.
- **total eventual VLM cost reduction:** `(baseline total eventual VLM KRW - candidate total eventual VLM KRW) / baseline total eventual VLM KRW`.
- **P0 event recall:** 독립 라벨러가 확정한 P0 event 중 정책의 eventual 분석 결과가 P0를 포착한 event의 비율. 동일 event가 여러 clip에 걸치면 event 단위로 한 번만 센다.
- **P0 event recall 95% confidence interval:** camera-night를 cluster로 둔 paired bootstrap으로 baseline과 candidate의 recall 및 recall 차이를 계산한다. seed와 반복 횟수는 inference 전에 동결한다.
- **maximum analysis delay:** clip 촬영 종료부터 해당 route의 요구 결과가 완료될 때까지의 최대 경과 시간. route별 최대값과 미완료 backlog를 함께 보고한다.
- **human review minutes/night:** 실제 검수 총분 / 고유 camera-night 수. 대기·재검수 처리 규칙은 실행 전에 동결한다.
- **abstention / `review_candidate` rate:** 최초 route가 `review_candidate`인 clip 수 / 전체 평가 clip 수.
- **최악 성능:** camera, 개체, 밝기 strata별 eventual call rate, KRW/camera/night, P0 recall, delay, review burden을 각각 보고하고 최악값을 표시한다. 표본이 작은 strata는 N과 함께 기술하며 전체 평균으로 숨기지 않는다.
- **P0 -> `activity_only`:** P0 label이 있는 clip 중 최초 route가 `activity_only`인 건수.

## 5. 합격 기준 (사용자 승인 전 제안 gate)

아래 숫자는 사용자 검토에서 그대로 승인하거나 **실행 전에만** 수정한다.

| 항목 | gate |
|---|---:|
| future evaluation window | 연속 14박 이상 |
| minimum labeled clips | 300 이상 |
| minimum labeled P0 events | 30 이상 |
| total eventual VLM cost reduction | 전수 저비용 VLM baseline 대비 20% 이상 |
| P0 event recall drop | 같은 표본 baseline 대비 2pp 이하 |
| P0 -> `activity_only` | 0건 |
| `review_candidate` rate | 30% 이하 |
| human review burden | 카메라 1대·1박당 5분 이하 |
| `cloud_now` maximum delay | 5분 이하 |
| `cloud_later` maximum delay | 12시간 이하 |

표본 최소치, 비용, recall, P0 안전성, review 부담과 지연 gate를 모두 통과해야 한다. P0 recall drop은 point estimate뿐 아니라 95% confidence interval을 함께 보고한다. 최소 30 P0 events로도 2pp 비열등성을 확정하기에 불충분하면 `hold / inconclusive`로 판정하고 gate를 완화하지 않은 채 미래 표본을 더 수집한다.

## 6. 예상 비용과 실행 전 산출물

금액은 아직 산정하지 않는다. baseline은 최소 300 clips 전수 저비용 VLM 호출, candidate는 route 계약에 따른 실제 eventual 호출과 조건부 검수 비용이 발생한다. 사용자 승인 전에 다음을 추가로 고정한다.

- baseline/candidate 모델별 입력·출력 예상 토큰과 단가, KRW 환율·환산 시점
- 예상 baseline 총 KRW와 candidate 상한 KRW
- sample seed, clip list, frozen policy artifact와 각 checksum
- ground-truth labeling 절차, 라벨러 blind 조건, P0 event 병합 규칙
- bootstrap seed와 반복 횟수, 미완료 backlog의 비용·지연 처리 규칙

## 7. Decision 룰

- **adopt:** 독립 표본 조건을 충족하고 모든 수치 gate를 통과하며, 오염·실행 계약 위반이 없다. H0를 기각하고 H1을 지지한다.
- **hold / inconclusive:** 최소 표본이나 통계 정밀도가 부족하거나 운영 데이터가 미완료여서 gate 판정이 불가능하다. threshold는 바꾸지 않고 미래 밤을 추가 수집한다.
- **reject:** 비용 절감 20% 미만, P0 recall drop 2pp 초과, P0 -> `activity_only` 1건 이상, `review_candidate` 30% 초과, 사람 검수 5분/camera/night 초과, 또는 route 지연 gate 중 하나라도 실패한다. H0를 유지한다.
- **invalid:** 정책 동결 뒤 threshold·feature·prompt·모델을 변경했거나, 기존 제외 데이터를 holdout에 섞었거나, sample list를 inference 뒤 변경했거나, route의 실제 eventual 비용을 누락했다. 이 경우 성능 판정에 쓰지 않고 해당 표본을 training/EDA로 강등한다.

## 8. 사용자 검토 관문

- [ ] H0/H1 승인
- [ ] route별 후속 처리와 비용 계약 승인
- [ ] 독립 표본·층화·오염 제외 규칙 승인
- [ ] 14박 / 300 clips / 30 P0 events와 모든 decision gate 승인 또는 실행 전 수정
- [ ] 모델·입력·prompt, frozen router·threshold, seed·clip list, 비용 단가, 통계 절차 동결
- [ ] 상태를 `🔒 고정(실행 대기)`로 변경

**현재 결론:** 실행 전 / 승인 대기. 위 체크리스트가 완료되기 전 inference, threshold tuning, DB write, R2 write 금지.
