# YOLO26n v2.7 C500G 데이터셋 설계 addendum — `dish_present` 층 추가

> 상태: `OWNER_APPROVED / DESIGN_ADDENDUM` · 승인: 2026-09-10 KST (owner "넣자")
>
> 대상 정본: `docs/superpowers/specs/2026-08-28-yolo26n-v27-c500g-prospective-dataset-design.md` §6.1 (Codex 브랜치
> `codex/yolo26n-v27-c500g-preparation`, 2026-09-10 현재 main 미병합). 이 addendum 은 그 문서 §6.1 에 병합될
> 텍스트를 정의한다. 병합 전까지는 이 파일이 정본이며, 충돌 시 이 파일이 §6.1 의 기존 층 목록에 **추가**만 한다.
>
> 결정 로그: `docs/decision-gate.md` 2026-09-10 "RAP 라벨링 순서 + dish_present 층".

## 1. 결정

C500G 30분 슬롯마다 존재하는 thumbnail(슬롯 시작 5~10초의 첫 decodable frame)로 **그릇 상태를 슬롯 단위로
태깅**하고, 그 태그를 v2.7 prediction-independent base(§6.1)의 **층(stratum)** 으로 추가한다. 그릇이 보이는
슬롯이 학습에 반드시 포함되게 하는 **하한 규칙**이며, 예측과 무관한 사람 눈 판정이라 cherry-pick 이 아니다.

## 2. §6.1 에 추가되는 텍스트 (병합용)

```
- 그릇 상태 (dish_present, 슬롯 단위·thumbnail 기준):
  `dish_visible`(그릇 객체가 보임) / `food_in_dish`(그릇에 먹이가 있음 — 빈 그릇은 false) 두 단계.
  선택 항목으로 그릇의 상/중/하 위치. 태그는 role freeze 뒤 train·validation role 의 thumbnail 에서만
  사람이 붙이고, sealed holdout·future holdout 의 thumbnail 은 열지 않는다.
  하한: train base 에서 9개 사육장 각각에 `dish_visible` 슬롯 유래 ROI 판단이 최소 10% 포함돼야 한다.
  부족하면 모델로 채우지 않고 재층화·shortage 보고 규칙을 그대로 따른다.
```

## 3. 태그 계약

| 항목 | 값 |
|---|---|
| 단위 | 카메라 × 30분 슬롯 (thumbnail 1장) |
| 값 | `dish_visible ∈ {true,false}`, `food_in_dish ∈ {true,false,unsure}`, `dish_zone ∈ {top,mid,bottom,unsure,null}` (사육장 3개 각각) |
| 정의 | `food_in_dish` 는 "food in/on dish" 좁은 정의(2026-05-01 dish_present 결정과 동일). 빈 그릇 → `dish_visible=true, food_in_dish=false` |
| 한계 명시 | 슬롯 **시작 시점** 상태다. 슬롯 중간에 급여가 일어난 경우는 다음 슬롯 태그에 나타난다 |
| 판정자 | 사람(owner 또는 팀 라벨러). 모델·VLM 사용 금지 (prediction-independent 유지) |
| 시점 | **metadata-only role freeze 완료 뒤** (계획서 Global Constraints "동결 전 thumbnail/video pixel 미개방" 준수) |
| 범위 | train·validation role 슬롯만. `v26_holdout`, `v26_holdout_date_guard`, `v27_future_holdout` 슬롯의 thumbnail 은 열지 않는다 |
| 저장 | private attempt 아래 append-only `dish-tags-v1.private.json` (slot key, 태그, tagger, timestamp, `dish_tag_version=1`). production DB/R2 write 0 |
| 비용 | 7일 = 504 thumbnail, 사람 30~40분 |

## 4. 용도 두 가지 (분리)

1. **detector 학습 층(이 addendum 의 본문).** 그릇 옆·위의 게코, 그릇 자체의 오검출 구조를 train base 가 반드시
   담게 한다. 하한은 §2 의 10%.
2. **급여 행동 GT 후보 목록(별도 원장, 이 문서 범위 밖).** `food_in_dish=true` 슬롯은 RAP 행동 GT(급여 창 O/X)의
   후보 목록으로 넘긴다. 행동 GT 계획은 별도 스펙에서 정의하며, 이 태그를 행동 라벨로 **복사하지 않는다**.

## 5. 금지

- holdout role thumbnail 열람·태깅
- 태그로 holdout 선정·hard-case 순위화에 영향 주기 (§8 teacher 경계와 동일하게 train-only)
- 태그를 모델 예측으로 대체하거나 사후 보정
- `food_in_dish` 를 `eating_paste` GT 로 승격

## 6. 병합 체크리스트 (Codex v2.7 브랜치 담당)

- [ ] 설계 §6.1 층 목록에 §2 텍스트 추가
- [ ] 계획서 Task 4(층화)·Task 6(base 표본) 의 strata coverage 표에 `dish_visible` 행 추가, 하한 10% 검사
- [ ] `experiments/yolo26n-v27-c500g/TEST-SHEET.md` 층 목록·shortage 보고 항목에 반영
- [ ] 태그 스키마 `dish-tags-v1` 를 private_io 계약에 추가 (O_EXCL/no-overwrite, 0700/0600)
