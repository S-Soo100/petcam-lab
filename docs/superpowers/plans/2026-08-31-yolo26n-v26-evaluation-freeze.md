# YOLO26n v2.6 evaluation freeze 실행 계획

> 선행 설계: `docs/superpowers/specs/2026-08-26-yolo26n-v26-recent-dense-retraining-design.md`
> 선행 학습 보고: `experiments/yolo26n-v26-recent-dense/TRAINING-REPORT.md`

## 목표

학습 내부 validation 최고점으로 모델을 고르지 않는다. frozen v2.5 baseline과 v2.6
6개 run을 최근 validation 505장에 같은 inference 계약으로 각각 한 번 실행하고,
사전등록된 frame·strata 기준을 통과한 후보만 detector threshold / NMS와 10fps
`3-of-5` 시간축 계약에 묶는다. 그 뒤 old regression-test 151장은 baseline과 선택
후보에 한 번씩만 사용한다.

## 고정 경계

- source repository와 commit, dataset manifest, recent split manifest, checkpoint,
  evaluator와 runtime SHA를 prediction 시작 전에 고정한다.
- validation 후보는 `baseline-v25`, `warm-start-s26/s27/s28`,
  `clean-reference-s26/s27/s28`의 정확히 7개다.
- validation inference는 confidence `0.001`, model NMS IoU `0.70`, max_det `50`,
  imgsz `960`, MPS로 한 번 실행한다.
- offline NMS 후보는 model NMS보다 강한 `0.40 / 0.55 / 0.70`만 허용한다.
- confidence threshold grid는 `0.05`부터 `0.80`까지 `0.05` 간격이다.
- validation은 선택에 사용하고 old regression-test는 선택·threshold 변경에 사용하지 않는다.
- prediction ledger, freeze와 report는 fresh private evaluation root에 O_EXCL로만 쓴다.
- DB / R2 / service / active checkpoint / labeling web / production deploy write는 0이다.

## 평가 기준

후보별 threshold/NMS row는 다음을 모두 만족해야 한다.

- frame precision `>=0.80`
- frame recall `>=0.90`
- 사람 확인 empty frame specificity `>=0.90`
- camera-night별 recall 최솟값 `>=0.85`

합격 row 중 recall 최대, specificity 최대, duplicate 최소, FP 최소, 높은 threshold,
warm-start 우선 순서로 결정론적으로 선택한다. 합격 후보가 없으면
`V26_VALIDATION_SHORTAGE`로 종료하고 old regression-test에 접근하지 않는다.

## 시간축·clip 해석 경계

최근 validation 505장은 2fps raw ledger에서 고른 sparse frame GT다. 각 row에는
camera-night와 episode가 있지만 전체 clip의 매 10fps frame GT는 없다. 따라서 다음을
구분한다.

1. detector threshold/NMS 선택과 frame/camera-night/episode cluster bootstrap은 505장으로 수행한다.
2. 10fps `3-of-5`는 사전등록 계약 그대로 freeze에 포함하되, sparse frame만으로
   clip-level TP/FP/FN 개선을 증명했다고 쓰지 않는다.
3. contiguous 10fps window 또는 사람 clip-level GT가 생기기 전까지 freeze에는
   `clip_level_acceptance_pending=true`를 남긴다.
4. old regression-test는 분포 퇴행 확인용으로 실행할 수 있지만 production·shadow
   채택은 clip-level acceptance와 sealed future holdout 전까지 금지한다.

## TDD 순서

### Task 1 — manifest와 preflight

- [x] v2.6 dataset 4,471장, active val 505장, regression-test 151장 계약 테스트
- [x] recent split 2,508장과 val 505장의 SHA·episode·camera-night join 테스트
- [x] 6개 training completion manifest / best.pt / results.csv / source commit 검증 테스트
- [x] partial artifact, path escape, hash drift, forbidden write count 거부 테스트

### Task 2 — immutable prediction ledger

- [x] validation 7개와 regression-test 허용 후보의 identity 테스트
- [x] one-shot claim이 inference보다 먼저 생성되고 재실행을 거부하는 테스트
- [x] low-confidence prediction 정렬·count·input drift 검증 테스트
- [x] dataset / split / checkpoint / evaluator / inference lineage 기록 테스트

### Task 3 — score와 freeze

- [x] offline single-class NMS `0.40/0.55/0.70` 테스트
- [x] precision/recall/specificity/duplicate/camera-night recall 테스트
- [x] episode cluster bootstrap seed와 반복 횟수 고정 테스트
- [x] 합격 gate와 결정론적 tie-break 테스트
- [x] baseline 포함 7개 same-protocol/GT ledger가 없으면 freeze 거부 테스트
- [x] `3-of-5` 시간축 계약과 `clip_level_acceptance_pending` 기록 테스트

### Task 4 — old regression-test

- [x] freeze 전 test 접근 거부 테스트
- [x] baseline과 선택 후보 외 test ledger 거부 테스트
- [x] old precision/recall이 baseline 대비 각각 `-0.02` 이내인지 판정 테스트
- [x] raw ledger에서 독립 재계산 가능한 report 테스트

### Task 5 — 실행과 독립 검수

- [ ] 구현 commit과 private runtime/source SHA 고정
- [ ] fresh evaluation root에서 validation prediction 7회
- [ ] validation freeze 또는 shortage 보고
- [ ] freeze 성공 시 regression-test prediction 2회와 report 생성
- [ ] manifest/ledger/freeze/report SHA·metric 독립 재계산
- [ ] production write/deploy 0 최종 확인

## 완료 정의

- detector 후보·threshold·NMS가 validation-only 계약에서 결정론적으로 동결되거나,
  명시적인 validation shortage로 종료된다.
- old regression-test는 freeze 성공 시에만 정확히 한 번 소비된다.
- sparse frame GT의 한계를 숨기지 않고 clip-level acceptance pending을 기록한다.
- 어떤 결과도 production 채택·배포로 해석하지 않는다.
