# Router Research Validity Audit — 2026-07-12

## 목적과 범위

이 문서는 local router care guard v1/v1.1 연구의 채택 근거 유효성을 사후 감사하는 append-only 판정 SOT다. 기존 보고서, review label, DB row, 스크립트 및 산출물은 삭제하거나 덮어쓰지 않는다. 아래 판정은 기존 결과를 새 성능 주장으로 재해석하지 않고, 어떤 근거를 보존하고 어떤 주장을 채택 근거에서 제외할지만 정한다.

## 감사 근거

### 1. v1/v1.1 평가 표본은 독립적이지 않다

- `router-care-guard-v1-eval-20260710` CSV는 150건이고, `router-care-guard-v1_1-eval-20260711` CSV도 150건이다.
- 두 CSV의 `clip_id` 집합을 대조하면 v1.1 150건 중 123건이 v1 150건과 중복된다.
- `guard_demote_cloud_now` 그룹은 v1 60건, v1.1 57건이며, 두 그룹 사이에 30건이 중복된다.
- 따라서 v1.1 review batch는 v1과 독립된 holdout이 아니며, 이 배치에서 관찰한 결과를 독립 재현 또는 production 채택 근거로 사용할 수 없다.

### 2. 평가 데이터를 본 뒤 threshold를 반복 수정했다

- v1 보고서는 operational 72건과 dataset203을 같은 guardrail/goal check에 사용한다. dataset203의 care 사례 2건을 직접 확인한 뒤 `active_motion_ratio < 0.95` guard를 추가했다고 기록한다.
- v1 규칙은 `center_motion_ratio < 0.8`이었다.
- v1.1 보고서와 현재 report script는 운영 검수 60건을 본 뒤 `center_motion_ratio < 0.55`와 `last_motion_sec < 56.0`을 추가했다고 명시한다.
- 즉 72건, dataset203, 검수 60건의 결과를 본 뒤 threshold가 반복 수정됐다. 이 데이터는 정책 개발과 failure analysis에는 쓸 수 있지만, 수정된 정책의 독립 holdout으로 다시 쓸 수 없다.
- 이는 research-testing protocol의 “합격 기준 사후 변경 금지”와 독립 평가 원칙에 맞지 않는다. 결과를 본 뒤 수정된 정책은 별도의 미래 holdout으로 다시 평가해야 한다.

### 3. route 이동은 총 VLM 비용 절감을 뜻하지 않는다

- router 계약에서 `cloud_later`는 영구 skip이 아니라 나중에 분석하는 route다.
- `local_router_v0.py`와 operational report script도 eventual cloud VLM을 `cloud_now + cloud_later`로 집계한다.
- 따라서 `cloud_now -> cloud_later`는 즉시 호출을 지연시킬 뿐 eventual VLM 호출을 제거하지 않는다.
- v1/v1.1 보고서는 DB/R2/LLM/VLM 호출이 모두 0인 read-only smoke이며, 실제 eventual 호출 수, 모델별 토큰, 원화 비용을 측정하지 않았다. 비용 절감 주장은 측정되지 않았다.

### 4. pass 판정은 adoption gate가 아니다

- 현재 care guard report script의 `pass-two-goal-smoke`는 운영 검수에서 regression 3건이 `cloud_now` 또는 `review_candidate`에 남고, non-inspection `cloud_now` 수가 감소하면 통과한다.
- 이 pass 로직에는 total eventual VLM cost, 독립 holdout 여부, `review_candidate`를 포함한 사람 검수 부담이 없다.
- 그러므로 `pass-two-goal-smoke`는 제한된 두 목표의 smoke 결과일 뿐 비용 절감 또는 production eligibility 판정이 아니다.

### 5. `random_control`은 random sample이 아니다

- feature row 조회는 `started_at` 오름차순이고, 후보 선택도 `_stable_sort`로 `started_at`, `clip_id` 오름차순 정렬한다.
- `random_control`은 앞선 그룹에 포함되지 않은 행 중 이 정렬의 앞 30건을 선택한다. 난수 seed, shuffle, reservoir sampling은 없다.
- 따라서 이 그룹은 시간순 앞 30건인 deterministic control이며, 모집단을 대표하는 random control로 해석할 수 없다.

## 판정

```text
metadata/review infrastructure: retain
v1 failure evidence: retain as exploratory negative evidence
v1.1 performance claim: invalid-for-adoption
cost reduction claim: not-measured
production eligibility: rejected
```

판정 범위는 다음과 같다.

- metadata/review infrastructure는 재현 가능한 feature 저장, review queue 생성, label 수집과 failure analysis에 계속 사용할 수 있다.
- v1 failure evidence는 정책이 과도하게 보수적이거나 입력 신뢰도에 제약받았다는 탐색적 음성 증거로 보존한다. 독립 성능 추정치로 승격하지 않는다.
- v1.1 결과와 `pass-two-goal-smoke`는 정책 조정 과정의 기록으로 보존하되 adoption 근거로는 무효다.
- 비용 절감은 실제 total eventual VLM cost와 사람 검수 비용을 측정하지 않았으므로 `not-measured`다.
- 현재 근거로 production 적용 자격은 `rejected`다. 이는 코드나 데이터를 삭제하라는 뜻이 아니라, 사전 등록된 미래 비중복 holdout 평가 전까지 운영 채택 근거로 쓰지 말라는 판정이다.

## 근거 파일

- `reports/router-care-guard-v1-20260710/REPORT.md`
- `reports/router-care-guard-v1_1-20260711/REPORT.md`
- `reports/router-care-guard-v1-eval-20260710/manual_review_queue.csv`
- `reports/router-care-guard-v1_1-eval-20260711/manual_review_queue.csv`
- `scripts/router_care_guard_v1_report.py`
- `scripts/build_router_care_guard_review_batch.py`
- `scripts/local_router_v0.py`
- `scripts/router_operational_v0_report.py`
- `.claude/rules/research-testing.md`

## 후속 연구 경계

기존 72건, dataset203, 검수 60건, v1/v1.1 review batch는 EDA, failure analysis, regression, training에는 보존할 수 있지만 새 정책의 독립 holdout으로 재사용하지 않는다. production 재검토에는 threshold와 비용 계약을 먼저 동결하고, 이후 촬영된 비중복 time-split 표본에서 eventual VLM 호출률, 총 원화 비용, P0 event recall, 분석 지연, `review_candidate` 및 사람 검수 부담을 함께 측정해야 한다.
