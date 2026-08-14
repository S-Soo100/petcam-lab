# YOLO26n v2.5 사람 hard-case 보강 학습 설계

**상태:** Owner 설계 승인 / 구현 전
**승인일:** 2026-08-15 KST
**목적:** blind CVAT에서 확정한 Owner hard-case 201장을 v2.4 parent train에 append-only로 결합하고,
동일 데이터로 warm-start와 clean-reference를 비교해 다음 development-only detector 후보를 고른다.

## 1. 한 줄 결정

CVAT Task 167 / Job 164의 완료 원장을 exact bytes로 동결하고, 201장·bbox 219개·빈 frame 3장을 모두
사람 GT로 사용한다. 기존 v2.4 train 1,458장은 그대로 복사해 새 v2.5 train 1,659장을 만들고,
validation 153장과 internal test 151장은 bytes·순서·GT를 변경하지 않는다. 같은 dataset으로
v2.4 warm-start와 YOLO26n clean-reference를 각각 한 번 학습하고 validation만으로 후보와 threshold를 고른다.

이 결과는 `development-only`다. 새 formal future holdout 전에는 production, Gecko Vision Gate, GME,
라벨링 웹 모델을 교체하지 않는다.

## 2. 선택한 접근과 기각한 접근

### 채택: 동일 데이터의 warm-start / clean-reference 비교

- warm-start는 v2.4에서 이미 배운 일반 게코 특징을 보존하면서 어려운 Owner 장면을 보강한다.
- clean-reference는 같은 데이터가 처음부터 학습될 때의 기준점이다.
- 둘을 동일 split·seed·imgsz·augmentation·device 계약에서 비교하므로, 개선이 새 GT 때문인지 기존
  checkpoint 계승 때문인지 분리해 해석할 수 있다.

### 기각: warm-start 단독

학습은 빠르지만 새 데이터 자체의 효과와 기존 가중치 효과를 분리할 수 없어 연구 결론이 약해진다.

### 기각: 모델이 틀린 frame만 선별 재학습

이번 201장은 frozen v2.4 신호로 찾아졌지만 사람은 prediction을 보지 않고 전부 다시 bbox했다. 여기서
다시 모델 오류 여부로 일부만 남기면 선택편향이 커지고, 빈 frame·다양한 종·쉬운 양성의 regularization
효과를 잃는다. 사람 acceptance를 통과한 201장을 한 cohort로 유지한다.

## 3. 입력 역할과 불변 경계

| 자산 | 수량 | v2.5 역할 | 금지 |
|---|---:|---|---|
| v2.4 train | 1,458 | parent train, bytes 그대로 복제 | 수정·재라벨 |
| CVAT Task 167 / Job 164 | 201 / bbox 219 / 빈 3 | 새 train-only GT | validation/test 편입 |
| v2.4 validation | 153 | 두 후보 metric·threshold 선택 | 학습 |
| internal fixed-test | 151 | 선택 완료 뒤 역사 비교 1회 | 후보·threshold 선택 |
| Owner external diagnostic | 60 | 역사 보고서 비교만 | 학습·선택·새 성능 주장 |
| Gate operational GT | 1,951 | 전량 quarantine | 읽기·복사·학습 |
| v2.4b formal future holdout | shortage 상태 | 별도 연구 계약 유지 | 이번 201장으로 대체 주장 |

CVAT 원장과 queue image는 다음을 모두 만족해야 한다.

- task 167, job 164, state `completed`, frame range 0..200
- 단일 label `gecko`, raw label id 11, static manual axis-aligned rectangle만 허용
- image sequence `V250001..V250201`, queue manifest 순서와 exact bijection
- rectangle 219개, annotated frame 198개, empty frame 3개
- 모든 point는 finite, positive-area, 실제 image boundary 내부
- queue JPEG bytes SHA와 dimensions는 기존 accepted blind queue manifest와 exact 일치
- raw annotation bytes SHA, normalized snapshot SHA, 사람 GT aggregate를 private provenance에 기록

한 조건이라도 다르면 dataset을 만들지 않고 `V25_HUMAN_EXPORT_REJECTED`로 멈춘다.

## 4. 데이터 흐름

```text
CVAT completed annotations + accepted blind queue 201
  -> strict normalized human snapshot
  -> v2.4 parent train 1,458과 exact/dHash overlap 재검증
  -> immutable v2.5 dataset (train 1,659 / val 153 / test 151)
  -> warm-start one-shot
  -> clean-reference one-shot
  -> v2.4 baseline + 두 v2.5 후보 validation low-confidence ledger 각 1회
  -> validation-only candidate + threshold freeze
  -> selected candidate internal fixed-test 1회
  -> v2.4/v2.5 development comparison report
  -> 새 future holdout 사람 작업 전 정지
```

새 201장은 `train`에만 추가한다. 기존 val/test record와 실제 image/label bytes는 v2.4 dataset에서 그대로
복사하고 raw SHA·record order를 재검증한다. historical fingerprint와 v2.4 dataset에 대한 exact SHA 및
dHash distance `<=2` overlap은 0이어야 한다. overlap이 있으면 조용히 제거하지 않고 provenance 결함으로
fail-closed한다.

## 5. Dataset v2.5 계약

- schema: `yolo26n-owner-dataset-v25`
- status: `V25_DATASET_READY`
- split counts: train 1,659 / val 153 / test 151 / total 1,963
- train source counts: v2.4 parent 1,458 / Owner hard-case 201
- Owner hard-case aggregate: positive frame 198 / negative frame 3 / box 219
- class: YOLO class id 0, name `gecko`
- bbox conversion: actual width/height로 xyxy를 normalized `x_center y_center width height`로 변환하고
  소수점 경계 오차는 `1e-6` 안에서만 clamp한다.
- empty frame 3장도 누락 image가 아니라 의도된 hard negative임을 증명하도록 크기 0인 label 파일을 만든다.
- directories 0700, files 0600, regular non-symlink, fresh output, no-overwrite
- manifest는 parent dataset SHA, CVAT raw SHA, normalized snapshot SHA, queue manifest SHA, 모든 image/label SHA,
  split·source aggregate, DB/R2/service/deploy write count 0을 고정한다.

staging 완성 뒤 exact file set, 모든 bytes SHA, label decode/bounds, aggregate를 다시 검증하고 destination을
no-clobber로 publish한다. partial dataset은 READY가 아니다.

## 6. 두 후보 학습 계약

공통값은 v2.2/v2.4의 검증된 Mac mini MPS 계약을 유지한다.

| 항목 | warm-start | clean-reference |
|---|---:|---:|
| initializer | frozen v2.4 best.pt | 기존 승인 YOLO26n base checkpoint |
| epochs | 60 | 100 |
| patience | 15 | 20 |
| lr0 | 0.001 | 0.01 |
| optimizer | AdamW | AdamW |
| imgsz / batch | 960 / 2 | 960 / 2 |
| device / workers | mps / 0 | mps / 0 |
| seed | 26 | 26 |

augmentation과 나머지 command는 기존 검증된 training contract를 그대로 사용한다. candidate마다 별도
0600 STARTED lock과 fresh run directory를 가진다. hard-stop identity는 dataset SHA, initializer SHA, code SHA
세 개로 한정한다. runtime은 Python과 Ultralytics/Torch/TorchVision/NumPy/OpenCV/Pillow의 version ledger를
기록하며 version 차이는 warning이지 학습 결과 폐기 조건이 아니다. 한 후보가 실패해도 다른 후보 결과로
자동 승격하지 않고 실패 원인과 성공 후보를 함께 보고한다.

## 7. 선택·평가 계약

frozen v2.4 checkpoint와 두 v2.5 후보는 모두 validation 153장에 `conf=0.001`, `imgsz=960`,
`nms_iou=0.70`, `max_det=50`, MPS로 정확히 한 번 prediction ledger를 만든다. confidence threshold는
`0.05..0.80`, 간격 `0.05`, match IoU `0.50`으로 ledger를 재계산한다. 이 동일 프로토콜 v2.4 행만 직접
baseline 비교에 사용하고, 과거 v2.4b `nms_iou=0.40` 수치는 참고 열로만 남긴다.

후보별 threshold 조건:

1. precision `>=0.60`
2. 조건을 만족하는 threshold 중 recall 최대
3. 동률이면 duplicate 최소, FP 최소, threshold 높은 순

두 후보 중 global 선택은 validation precision floor를 통과한 후보만 대상으로 recall 최대, duplicate 최소,
FP 최소, warm-start 우선 순으로 결정론적으로 정한다. 둘 다 precision floor를 못 넘으면
`V25_VALIDATION_SHORTAGE`로 종료하고 test를 열지 않는다.

선택 뒤 frozen v2.4 baseline과 선택된 v2.5 후보를 internal fixed-test 151장에 같은 프로토콜로 각각 딱 한 번
실행한다. Owner external 60장은 이미 여러 버전에서 본 진단지이므로 새 one-shot 성능 시험으로 재실행하지
않고 기존 보고서의 오류 유형 참고값만 사용한다. validation 153과 internal test 151은 hard-case 201과 분포가
다르고 반복 노출된 개발 benchmark이므로 이번 수치는 회귀 없음 확인용이며 새 hard-case 성능 증명이나
production 채택 근거가 아님을 보고서에 명시한다.

## 8. 성공 판정과 다음 사람 작업

`V25_TRAINED_DEVELOPMENT_ONLY` 조건:

- dataset, 두 training run, validation ledgers, selection freeze, selected fixed-test lineage가 모두 완전함
- 선택 threshold validation precision `>=0.60`
- selected fixed-test 결과와 v2.4 대비 수치가 재계산 가능함
- overlap, decode, bbox, schema, one-shot, write/deploy 위반 0

이 상태는 production 채택이 아니다. 다음 단계는 v2.5 학습·선택 이후 새로 촬영된 영상에서 independent
future holdout을 만들고, 모델 prediction을 숨긴 채 사람 presence/bbox 검수를 수행하는 것이다. 그 holdout을
통과하기 전에는 Gecko Vision Gate, GME, labeling web worker의 모델을 교체하지 않는다.

## 9. 오류 처리와 안전 경계

- CVAT/queue/parent/protected SHA mismatch: dataset publication 전 중단
- train candidate failure: 기존 output 보존, 삭제·덮어쓰기·동일 경로 재실행 금지
- validation candidate shortage: test 접근 전 중단
- partial artifact 또는 output race: READY 없음, self-owned staging만 격리
- DB/R2/service/production model/GME/labeling web mutation: exact 0
- 비밀값, 원문 image, 원문 GT, source identity는 console·tracked report에 출력하지 않음

## 10. 검증 전략

1. normalizer 단위/적대 테스트: wrong task/job/label, bool-as-int, malformed shape, missing/extra frame, SHA/dimension
   drift, partial publication을 모두 거부한다.
2. dataset builder 단위/적대 테스트: exact counts, parent bytes/order preservation, train-only append, overlap,
   bbox normalization, source/protected role, no-overwrite를 검증한다.
3. training runner 테스트: exact two specs, pre-inference lock, dataset/checkpoint/code pins, manifest completeness,
   partial candidate failure를 검증한다. warm/clean의 epoch·learning-rate 차이는 각 초기화의 기존 표준
   recipe이며 완전히 동일한 optimization system 비교가 아님을 manifest와 보고서에 남긴다.
4. evaluator 테스트: validation-only selection, fixed precision floor, deterministic metric/threshold tie-break,
   test-before-freeze 거부, one-shot lock을 검증한다.
5. Mac mini live execution은 exact reviewed commit의 clean detached checkout과 private fresh attempt에서만 수행한다.
6. 최종 독립 검수는 manifests/results/best.pt/ledgers/report를 raw SHA와 재계산 metric으로 대조한다.
   MPS와 augmentation은 seed 고정에도 bitwise deterministic하지 않으므로 두 학습은 one-shot 비교이며
   반복 평균이나 통계적 우월성을 주장하지 않는다.

## 11. 범위 밖

- Gate 1,951 재사용 또는 복구
- production/GME/labeling web 모델 배포
- 행동명·활동시간·부재·마릿수 판단
- 기존 v2.4/v2.4b artifact 수정
- future holdout을 이번 201장으로 대체
