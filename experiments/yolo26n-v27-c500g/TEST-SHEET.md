# YOLO26n v2.7 C500G TEST-SHEET

> 상태: `OWNER_REVIEW_PENDING / PIXEL_ACCESS_BLOCKED`
>
> 이 sheet는 source identity·원본 pixel·prediction 없이 role, quota, acceptance와 중단 기준을
> 먼저 고정한다. 승인된 이 파일의 SHA-256을 이후 모든 CLI input manifest에 pin해야 한다.

## 순서와 역할 경계

**role freeze before pixels**. metadata-only inventory 뒤 `camera-night`를 atomic role로 freeze하고,
그 완료 전에는 thumbnail·video·frame을 열지 않는다. v2.6 sealed holdout, v2.7 validation,
v2.7 future holdout은 pilot, representation 결정, teacher mining에서 제외한다.

ROI calibration과 pilot은 `v27_train` 역할 또는 study 이전 calibration frame에서만 한다. 첫 blind
pass와 double review에는 prediction bbox, confidence, source identity를 표시하지 않는다. `uncertain`과
`media_error`는 negative가 아니며, sibling ROI에 어느 하나라도 있으면 해당 full-frame은 발행하지 않는다.

## 사전등록 quota

| 항목 | 고정값 | 집계와 경계 |
|---|---:|---|
| warmup | 27 | 판단·시간·품질 통계에서 제외한다. |
| pilot | 600 | train-only unique ROI judgment이며 total unique judgment target에 포함한다. |
| pilot double | 60 | pilot의 blind independent second review다. |
| total unique judgment target | 3000 | pilot 포함 구성은 `600+1200+600+600`이다. |
| total double target | 300 | pilot double 포함 구성은 `60+120+60+60`이다. |
| ROI negative | 30–40% | 분자=사람 확인 `absent`; 분모=warmup/reserve를 제외한 완료된 unique ROI judgment 전체다. |
| uncertain+media_error | <=10% | unique ROI judgment 분모에서 관찰하는 상한이다. |
| dish_visible 하한 (2026-09-10 addendum) | 사육장별 >=10% | train base 의 unique ROI judgment 중 `dish_visible=true` 슬롯 유래 비율, 9개 사육장 각각. 태그는 role freeze 뒤 train·validation thumbnail 만 사람이 붙이고 holdout thumbnail 은 열지 않는다. 미달 시 재층화·shortage 규칙 동일. |

`present`, `absent`, `uncertain`, `media_error`의 완료된 unique ROI judgment는 모두 ROI negative
분모에 넣고, `absent`만 분자에 넣는다. 아직 사람에게 제시하지 않은 reserve candidate와 warmup은
분자·분모 모두에서 제외한다.

## Conditional expansion preregistration

현재 prospective budget은 initial total unique 3000, blind double 300(10%)에서 끝난다. conditional
expansion ceiling은 total unique 6000, total double 600이며 추가분은 최대 unique 3000 + double 300이다.
이 ceiling은 자동 queue 증설 권한이 아니다.

확장은 별도 승인된 v2.7 training/evaluation plan에서 동일 training recipe로 1500과 3000 subset을
비교한 뒤에만 판단한다. performance trigger A 또는 B 중 하나, data trigger, Owner expansion
재승인을 모두 만족해야 한다. 셋 중 하나라도 빠지면 3000에서 종료한다.

| gate | 재현 가능한 기준 |
|---|---|
| performance trigger A | camera-night validation recall이 1500→3000에서 absolute +0.02 이상 상승한다. |
| performance trigger B | `small_object|occlusion|ir_transition|reflection` 중 최소 한 critical slice recall이 overall recall보다 absolute 0.05 이상 낮다. |
| data trigger | 추가 후보는 protected role 제외, camera-night/source lineage 분리, exact/near-duplicate 제거를 통과하고 under-covered strata 또는 새 eligible train camera-night에서 온다. |

별도 training/evaluation plan, performance/data trigger, Owner 재승인 없이는 3,001번째 unique 또는
301번째 double을 열지 않는다. current preparation plan은 initial 3000에서 끝난다. training/evaluation과
initial 3,000 이후의 추가 extraction/CVAT/labeling은 별도 plan과 Owner approval 전까지 금지한다.
초기 3,000을 만드는 current preparation의 CVAT/labeling은 이 범위 안에서 허용한다.

## Representation acceptance

pilot의 사람 GT를 frozen full-frame serve preprocessing에 적용해 아래 기준을 측정한다.

| 측정 | acceptance | 판정 |
|---|---:|---|
| GT bbox short side | >=16px fraction >=0.95 | 만족하면 full-frame publication을 우선한다. |
| ROI edge issue | <=0.02 | `edge_issue != none인 eligible review image fraction`이며, 초과하면 representation을 고르기 전에 ROI 경계·padding을 재보정한다. |

이 기준은 pilot 결과를 본 뒤 완화하거나 바꾸지 않는다. short side 기준을 만족하지 못하면 ROI crop
publication과 3-tile serving contract를 별도 고정해야 하며, full-frame과 crop을 같은 timestamp의
독립 학습 예제로 함께 발행하지 않는다.

## 재층화·중단 규칙

ROI negative가 30–40% 밖이거나 strata coverage가 특정 enclosure, 시간대, 조명, 가림, 빈 화면에
치우치면 prediction 없이 다시 층화한다. `uncertain+media_error >10%`이면 원인을 기록하고
해당 queue의 publication을 멈춘다. ROI edge issue가 `>0.02`이면 ROI recalibration 뒤 재측정하며,
re-stratification/ROI recalibration maximum 3이다.

reserve candidate는 initial quota 안에서 아직 사람에게 제시하지 않은 항목을 교체하거나 후속 batch에
배분할 때만 쓴다. re-stratification과 후속 batch도 initial unique 3000·double 300을 넘지 않는다.
3,000/300에 도달한 뒤에도 quota 또는 coverage가 미달이면 대체 source나 model prediction으로 채우지
않고 shortage로 종료한다. 실제 분포, shortage, 시도 횟수와 중단 이유를 기록하고 Owner 판단으로 넘긴다.

## Immutable TEST-SHEET, SHA pin과 Owner gate

Owner 승인 뒤 TEST-SHEET 전체 파일은 immutable이다. 후속 CLI는 실행 input manifest에 이 whole-file
SHA-256을 literal로 넣고, 실행 시 현재 TEST-SHEET의 SHA-256과 exact match를 검증한다. 값이 없거나
불일치하면 fail-closed한다. 승인 시 addendum과 TEST-SHEET의 SHA-256을 각각 runtime manifest에
기록한다.

Task 11의 실행 결과는 TEST-SHEET에 append하지 않고 별도 `experiments/yolo26n-v27-c500g/RESULTS.md`에
aggregate-only로 append한다. RESULTS에는 비밀값이나 개별 source 식별자를 넣지 않는다.

Owner가 addendum과 이 TEST-SHEET을 함께 승인하기 전에는 Task 1, pixel access, ROI calibration,
pilot queue, CVAT task 생성, 추론, 학습을 시작하지 않는다.
