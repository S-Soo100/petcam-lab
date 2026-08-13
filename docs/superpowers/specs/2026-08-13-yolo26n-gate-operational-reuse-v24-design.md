# YOLO26n Gate 운영 GT 재사용 v2.4 설계

**상태:** 구현·전체 회귀 검증 완료 / Mac mini 학습 전
**승인일:** 2026-08-13 KST
**목적:** 과거 Gecko Vision Gate에서 사람이 검수한 운영 펫캠 bbox를 현재 YOLO26n의 재현율 보강에
안전하게 재사용할 가치가 있는지 v2.3과의 고정 비교로 검증한다.

## 1. 한 줄 결정

과거 Gate 데이터 중 `operational` 사람 GT만 정규화·중복 축소해 v2.4의 **train 전용 보강 후보**로
사용한다. Roboflow 1,430장과 과거 Gate validation/test 역할은 그대로 가져오지 않는다. 현재 v2.3의
validation/test와 Owner 외부 진단 60장은 변경하지 않고, v2.3과 v2.4를 같은 두 평가면에서 비교한다.

## 2. Decision gate

- **SOT 부합:** Gecko Vision Gate를 계속 업그레이드하되 검출 실패를 자동 부재·삭제·skip으로 바꾸지
  않는 GME SOT와 일치한다.
- **기대효과:** 과거 운영 환경의 부분 노출 positive와 동일 배경 hard negative를 함께 학습해 v2.3의
  외부 회귀시험에서 확인된 낮은 재현율을 개선한다.
- **측정 가능:** v2.3의 동결 validation/test와 Owner 외부 진단 60장을 그대로 두고 bbox recall,
  positive-image recall, precision 참고값, FP, FN, duplicate를 동일 방식으로 비교한다.
- **유효한 계획:** 원본·과거 COCO·v2.3 artifact는 읽기 전용이다. 새 private dataset/run/report만 만들고
  DB·R2·service·active model·GME checkpoint는 변경하지 않는다.

판정은 `adopt / controlled v2.4 training experiment`다. 이 실험 결과만으로 production 모델을 교체하지
않는다.

## 3. 확인된 입력 현황

MacBook 원본 `/Users/baek/myPythonProjects/gecko-vision-gate/datasets`에서 다음을 확인했다.

| 구분 | 이미지 | 양성 | 음성 | bbox |
|---|---:|---:|---:|---:|
| 운영 사람 GT | 1,951 | 1,361 | 590 | 1,373 |
| Roboflow 주간 외부 자료 | 1,430 | 1,430 | 0 | 1,430 |
| 합계 | 3,381 | 2,791 | 590 | 2,803 |

- 운영 자료는 458개 source clip에서 왔다.
- 이미지 누락 0, SHA 완전중복 0, 기존 Gate train/val/test 사이 clip 누수 0이다.
- 현재 v2.3 이미지와 exact SHA overlap은 0이다.
- 운영 bbox 16개는 경계를 1~2px 벗어나 현재 strict 계약에 맞지 않는다.
- 운영 frame pair 4,026개 중 dHash 거리 2 이하가 2,812개이며 390/458 clip에 near-duplicate가 있다.
- Roboflow 자료에는 사실상 중복인 2-box 이미지가 최소 1개 확인됐고 현재 bbox 정책·출처 정책과도
  다르므로 이번 실험에서 제외한다.

## 4. 사용자 체험

이 실험은 별도 사람 라벨링 화면을 새로 요구하지 않는다.

1. `[화면]` Owner는 현재 v2.3 결과와 Gate 자료 감사 결과만 보고, 예측 bbox로 과거 GT를 덮어쓰지
   않는다.
2. `[조작]` strict 경계를 벗어난 16장은 자동 보정하지 않고 1차 실험에서 제외한다.
3. `[반응]` 시스템은 같은 clip의 유사 frame을 줄이고 positive와 negative를 함께 보존한 private v2.4
   candidate manifest를 만든다.
4. `[반응]` v2.3과 v2.4를 같은 validation/test와 외부 진단 60장으로 비교한다.
5. `[감정]` 장수가 늘었다는 이유가 아니라 실제 FN 감소와 FP 비악화를 보고 채택 여부를 판단한다.

## 5. 후보 선택 계약

### 입력 허용

- `source=operational`, `labeled=yes`인 COCO 이미지 1,951장만 허용한다.
- 과거 Roboflow·crawler·autolabel-only 자료는 모두 제외한다.
- strict image decode, image SHA, COCO image id/file name, 단일 `gecko` class, bbox finite/positive-area/
  image-boundary 검증을 통과해야 한다.
- 경계 밖 bbox 16장은 자동 clamp하지 않고 `invalid_bbox_quarantine`으로 남긴다.

### clip 단위 near-duplicate 축소

- seed는 `yolo26n-gate-operational-reuse-v24-v1`로 고정한다.
- source clip별 최종 cap은 2장이다.
- 한 clip에 positive와 negative가 모두 있으면 각 1장을 선택한다.
- 한 상태만 있으면 SHA rank anchor 1장과 anchor 대비 dHash 거리가 2보다 큰 가장 먼 frame 1장을
  선택한다. 동률은 seed+clip+state+image SHA rank로 결정한다.
- 현재 read-only 재계산에서는 strict bbox 16장을 제외한 1,935장에서 638장
  (`positive=342`, `negative=296`, `clip=458`)이 나온다.
- 이 638은 scene-leakage 검사 전 최대 후보 수다. 아래 v2.3 보호 집합과 source/clip/camera-night가
  겹치면 추가 제외하며 수량을 억지로 채우지 않는다.
- 최종 후보는 최소 300장, positive 150장, negative 100장, source clip 200개를 모두 만족해야 한다.
  하나라도 부족하면 학습하지 않고 `V24_GATE_REUSE_SHORTAGE`로 종료한다.

### 사람 bbox 정책 호환 감사

- 과거에 사람이 검수했다는 사실만으로 현재 bbox 정책과 같다고 가정하지 않는다.
- 최종 후보에서 서로 다른 clip의 positive 40장과 negative 20장을 결정론적으로 뽑아 bbox overlay를
  만든다. positive는 큰/작은 bbox, 1/2개체, frame edge를 포함한다.
- Owner가 현재 규칙인 “보이는 머리·몸통 중심, 가려진 영역과 화면 밖 꼬리는 추정하지 않음”에 맞는지
  확인하기 전에는 dataset materialization과 학습을 시작하지 않는다.
- 감사에서 수정이 필요한 positive가 1장이라도 나오면 60장만 고치는 대신 최종 positive 후보 전체를
  current-policy 재검수 대상으로 전환한다. negative 오라벨도 같은 방식으로 전체 검수 gate를 연다.

## 6. 누수 방지와 split 계약

- v2.3 dataset 1,193장과 validation/test의 bytes·순서·label은 완전히 동결한다.
- Gate 후보는 v2.3 validation/test와 image SHA뿐 아니라 source clip·camera-night·동일 원본 파생
  관계가 겹치지 않아야 한다.
- source identity를 v2.3 private provenance와 결정론적으로 연결할 수 없는 후보는 train에 넣지 않고
  `unresolved_lineage`로 격리한다.
- 통과한 Gate 후보는 모두 v2.4 `train`에만 추가한다. validation/test로 재분배하지 않는다.
- Owner 외부 진단 60장, ambiguous 3장, Owner training 177장의 기존 역할을 바꾸지 않는다.
- dataset v2.4 manifest는 v2.3 parent manifest SHA, Gate COCO 3개 SHA, 원본 이미지 SHA, selector code SHA,
  제외 사유와 최종 aggregate를 기록한다.

## 7. 학습·비교 계약

- 모델은 YOLO26n이고 v2.3 selected warm-start checkpoint에서 시작한다.
- v2.3과 같은 seed, imgsz, optimizer, epoch/patience, augmentation, MPS 계약을 유지한다.
- clean-reference 재학습은 하지 않는다. 이번 질문은 모델 구조가 아니라 Gate 운영 GT 보강 효과다.
- threshold는 v2.4 validation에서 precision floor 0.60을 지키는 grid로 다시 고정한다.
- threshold 고정 전 test와 외부 60장 inference는 금지한다.
- 선택된 v2.4 checkpoint를 internal fixed test에 한 번, Owner 외부 진단 60장에 한 번만 실행한다.

## 8. 성공·실패 판정

### 채택 후보

v2.4는 아래를 모두 만족할 때만 detector 승격 후보가 된다.

1. internal fixed test box recall이 v2.3 `0.5889`보다 최소 `+0.05` 높아진다.
2. internal fixed test precision이 `0.60` 이상이다.
3. Owner 외부 60장 box recall이 v2.3 `0.4211`보다 낮아지지 않는다.
4. Owner 외부 60장 FP가 v2.3 `20`보다 증가하지 않고 duplicate가 `4`보다 증가하지 않는다.
5. decode/label/provenance/overlap/write 위반이 0이다.

Owner 외부 진단은 negative가 6장뿐이므로 precision은 참고값으로만 남기고 production adoption 근거로
사용하지 않는다. 위 조건을 통과해도 future holdout 전에는 상태가
`V24_TRAINED_DEVELOPMENT_ONLY`다.

### 실패·중단

- final candidate가 300장, positive 150장, negative 100장, source clip 200개 중 하나라도 부족하면
  학습하지 않고 shortage로 종료한다.
- validation에서 precision floor 0.60을 만족하는 threshold가 없으면 test를 열지 않는다.
- test 또는 외부 60장에서 재현율/FP/duplicate 조건 하나라도 악화되면 Gate 자료 병합을 채택하지 않는다.
- 결과가 나쁘다고 같은 frozen test를 보고 후보 선택·라벨·threshold를 반복 수정하지 않는다.

## 9. 쓰기·보존 경계

- 허용: Mac mini private dataset v2.4 candidate, 학습 run, prediction ledger, 비교 report.
- 불변: 원본 Gate dataset, 과거 RF-DETR checkpoint, v2.3 dataset/run/evaluation, 외부 진단 v2.2/v2.3
  attempt.
- 금지: DB/R2/service/GME/labeling web/active model write, 원본 이동·삭제, 사람 GT 자동 수정.
- production 적용은 별도 Owner 승인과 Gecko Vision Gate/GME wrapper 호환 검증 뒤에만 진행한다.

## 10. 이번 범위 밖

- Roboflow 1,430장 재라벨링·라이선스 재검토
- 과거 RF-DETR과 YOLO의 구조 비교
- segmentation·pose·multi-class 확장
- 행동명·하이라이트·VLM route·자동 absent/skip/삭제
- 별도 future holdout 수집과 production checkpoint 교체
