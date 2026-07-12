# Router 연구 데이터 역할 등록부 — 2026-07-12

## 목적

이 문서는 local router 후속 연구에서 기존 데이터를 어떤 용도로 다시 사용할 수 있는지 고정하는 등록부다. 기존 데이터와 라벨은 삭제하지 않고 EDA, failure analysis, regression, training 자산으로 보존하되, 정책 개발에 노출된 데이터는 독립 holdout으로 재사용하지 않는다.

## 데이터 역할

| 데이터 그룹 | 허용 역할 | 금지 역할 |
|---|---|---|
| dataset203 | feature EDA, regression, training | 독립 router holdout |
| operational 72 | sentinel/regression, training | 독립 holdout |
| v1 demote 60 | failure analysis, training | 독립 holdout |
| v1 review 150 | EDA/training | 독립 holdout |
| v1.1 review 150 | EDA/training | 독립 holdout |
| future time-split nights | frozen-policy evaluation | threshold tuning |

## 독립 holdout 제외 목록

향후 router 정책의 독립 holdout으로 재사용하면 안 되는 데이터는 다음과 같다.

- dataset203
- operational 72
- v1 demote 60
- v1 review 150
- v1.1 review 150

이 데이터에서 파생된 review label이나 부분집합도 원본의 역할 제한을 그대로 상속한다. 새로운 라벨을 붙이거나 표본 이름을 바꿔도 독립성이 복원되지는 않는다.

## 미래 평가 규칙

독립 평가는 정책과 threshold를 먼저 동결한 뒤 수집한 `future time-split nights`만 사용한다. 평가 결과를 본 뒤 threshold를 조정하면 해당 표본은 더 이상 frozen-policy evaluation holdout이 아니며, 이후 EDA/training 데이터로만 취급한다.

## 중복 근거

`overlap-summary.csv`는 두 review queue의 `clip_id` 집합을 직접 비교한 결과다. 각 CSV 내부의 `clip_id`는 모두 유일했으며, 전체 review queue는 150건 중 123건, `guard_demote_cloud_now` 부분집합은 v1 60건과 v1.1 57건 중 30건이 겹쳤다. 따라서 두 비교 모두 독립 holdout으로 유효하지 않다.
