# YOLO26n v2.6.1 expanded hard-case queue 결과

## 결론

4,096장 blind queue의 사람 bbox 검수와 CVAT export 동결을 완료했다. 4개 Owner 오류 영상만
반복하지 않고, v2.6 이후 새 영상과 v2.6 미사용 영상까지 합쳐 1,187개 독립 source를 포함했다.
사람이 확정한 실제 게코 image는 2,699장, 실제 게코가 없는 empty image는 1,397장이다.

## 데이터 구성

| 항목 | 결과 |
|---|---:|
| 고정 source snapshot | 2,004 clips |
| post-v2.6 source | 1,215 clips |
| sealed future holdout | 300 clips / 2 cameras / 10 nights |
| development source | 1,187 clips |
| download/decode 성공 | 1,187 / 1,187 |
| 중복 제거 전 frame | 10,785 |
| 최종 blind frame | 4,096 |
| source coverage | 1,187 / 1,187 |
| GME detector anomaly signal frame | 2,093 |
| IID control frame | 510 |
| Owner-confirmed hard-case frame | 84 |
| 사람 확인 positive image | 2,699 |
| 사람 확인 empty image | 1,397 |
| 실제 게코 bbox | 2,732 |
| uncertain / media_error | 0 / 0 |

일반 source는 서로 거의 같은 장면을 무제한 보존하지 않고 최소 3장 coverage를 유지했다. Owner가
확정한 반사·가림·오탐·미탐·과대 bbox source는 최대 21장까지 남겼다.

## 무결성

- future holdout과 development source overlap 0
- future holdout frame/GT 접근 0
- v2.6 dataset exact image overlap 0
- 익명 ZIP filename 외 source 식별 정보 0
- ZIP 3개 무결성 검사 통과: 2,000장 + 2,000장 + 96장
- private directory/file mode `0700/0600`
- production DB write 0, R2 write/delete 0, service/model/labeling web 변경 0
- Task 4/5/6의 CVAT export에는 각각 2,000/2,000/96 image가 있고 queue part의 익명 filename과
  순서가 정확히 일치한다.
- 허용 label, bbox bounds와 양의 면적, tag 충돌, 전역 익명 번호 `V0000001..V0004096` 검사를
  통과했다.

## 중간 정정 이력

첫 추출은 MP4 헤더의 reported frame count와 실제 decoded count 차이를 손상으로 오인했다. source
SHA와 두 번의 실제 decode를 유지하면서 실제 decoded count를 정본으로 쓰도록 고쳤고 회귀 테스트를
추가했다.

다음 추출은 과거 frame과 비슷한 고정 사육장 배경을 다른 source에서도 중복으로 제거해 새 source
coverage를 과도하게 줄였다. global exact SHA는 계속 차단하되 perceptual dHash는 같은 source 안에서만
적용하고, 일반 source 2장·Owner source 20장의 제한된 유사 frame 예외를 허용했다. superseded 결과는
삭제하거나 덮어쓰지 않고 private 감사 이력으로 남겼다.

## 다음 단계

1. 동결 export를 private review index와 결합해 final human GT 원장을 만든다.
2. 신규 frame은 clip/인접 episode 단위 train/validation 80:20으로 분리한다.
3. v2.6 train만 replay하고 v2.6 recent val505와 old validation153/test151은 학습에서 제외한다.
4. matched warm-start/clean-reference 3-seed 학습과 baseline 포함 validation 7회는 별도 실행 승인 뒤
   진행한다.

구현과 실행 순서는
[`dataset·training·validation 계획`](../../docs/superpowers/plans/2026-09-04-yolo26n-v261-dataset-training-validation.md)에
고정했다. sealed future holdout 300 clips는 계속 열지 않는다.

## 구현 상태

GT normalizer, episode-group dataset builder, warm/clean 3-seed training runner, baseline 포함 validation
7회·freeze·regression evaluator를 구현했다. 신규/기존 v2.6.1 관련 테스트 68개가 통과했다.
독립 코드리뷰 뒤 exact GT 계약, protected 근사중복, 외부 승인 split SHA와 입력 lineage 재검증,
학습 입력 전후 전수 검증, 7개 checkpoint/6개 completion 및 승인 v2.6 baseline 사전결합,
resize/color·future/old-validation 보호 증거와 505/151 fixed-suite regression binding을 추가했다.
private GT 원장은 4,096장(양성 2,699, 음성 1,397, bbox 2,732)으로 생성했고 episode split
dry-run은 신규 train 3,274장, validation 822장으로 고정했다. 서로 다른 source의 유사한 야간 배경까지
전역 dHash 중복으로 막던 builder 버그는 queue와 동일한 source-scoped 규칙으로 고쳤고, 시간상 가까운
근사중복 episode는 split 전에 하나의 안전 그룹으로 합쳤다. 교차 근사중복은 0이다. dataset
materialize, 정식 학습, validation prediction은 실행하지 않았다. 전체 저장소 회귀 테스트는
2,478 passed, 5 skipped이고, 최종 독립 코드리뷰는 Critical 0, Important 0, Ready Yes다.
