# YOLO26n v2.6 최근 연속영상 촘촘 재학습 실행 계획

> 설계: `docs/superpowers/specs/2026-08-26-yolo26n-v26-recent-dense-retraining-design.md`

## Task 1 — read-only source freeze

- KST window와 DB 566개, 접근 가능 429개, 55초 미만 tombstone 137개 identity를 private manifest로 동결한다.
- camera/day/size/duration/GME lineage aggregate를 독립 재계산하고, exact clip set의 GME status가 전부 `succeeded`인지 확인한다.
- 기존 train/val/test/future-holdout fingerprint와 overlap 검사를 준비한다.

## Task 2 — dense extractor TDD

- 2fps timestamp 생성, exact frame identity, 조기 decode failure, reported/decoded count, source drift와 resume 계약 테스트를 먼저 작성한다.
- 원본을 한 번에 하나씩 스트리밍 decode하는 extractor를 구현한다.
- 선택되지 않은 JPEG는 남기지 않고 raw ledger만 보존한다.

## Task 3 — deterministic queue selector TDD

- every-clip 2-frame coverage를 강제한다.
- coverage 858 / uncertainty 900 / hard-negative 후보 350 / IID random 400 / gold double-review 200 계약을 검증한다.
- feedback band, transition, motion-with-low-confidence, persistent detection, scene change strata를 합친다.
- exact/dHash/temporal dedup과 per-clip/camera-night cap을 검증한다.
- protected overlap과 split leakage를 fail closed로 거부한다.

## Task 4 — TEST-SHEET, Claude pre-review와 MacBook runtime freeze

- 데이터 접근 전에 window, strata, split, 10fps temporal rule, metric, stop rule을 TEST-SHEET에 고정한다.
- Claude는 코드·계약·테스트만 read-only 교차검수한다.
- MacBook Pro M5/32GB, MPS, package version, source code SHA를 private runtime manifest에 고정한다.
- 맥미니 GME service와 active checkpoint는 읽기 전용 provenance 확인만 한다.

## Task 5 — MacBook source read와 blind queue 생성

- 상태: 완료. primary 2,508장, double-review 200장, 429 clip coverage와 protected overlap 0을 확인했다.
- R2 원본은 맥북 private temp에 순차적으로 내려받고 매 clip 처리 후 제거한다.
- 접근 가능한 429개 전체의 2fps raw ledger를 만든다.
- 목표 2,508개 고유 이미지와 200개 double-review task의 no-overwrite CVAT ZIP/private review index를 만든다.
- 원본, DB, R2, service, active checkpoint를 수정하지 않는다.

## Task 6 — 사람 presence/bbox 검수

- 상태: 완료. primary 2,508장, double-review 200장과 Owner adjudication을 최종 GT로 확정했다.
- prediction을 숨긴 채 present/absent/uncertain/media_error를 판정한다.
- present에는 bbox를 필수로 그린다.
- 10% 독립 QA와 Owner adjudication을 완료한다.
- 최종 GT와 QA artifact의 exact SHA 검증 완료 전 training 시작을 금지한다.

## Task 7 — dataset v2.6 build

- 상태: 완료. 전체 4,471장, active train 3,662장 / validation 505장과 old regression-val 153장 / regression-test 151장을 분리했다.
- 사람 승인 GT와 기존 v2.5 replay를 결합한다.
- final GT는 원본 primary/double-review/adjudication export와 review/selection 원장의 SHA에 다시 묶고, confirmed-empty `>=700`, 비율 `>=35%`, camera-night별 negative 존재를 재검증한다.
- reserve 교체 frame은 원래 selection SHA와 실제 dense ledger row/SHA를 함께 확인하고, 계산된 double-review conflict 전부가 adjudication index에 포함됐는지 집합 비교한다.
- 신규 recent cohort를 60초 인접 episode group 기준 `80:20`으로 나누고, camera-night 층화와 같은 camera-night·5분 이내 cross-split dHash `<=8` 검사를 수행한다.
- dense completion의 source SHA를 결합해 같은 source bytes가 train/validation으로 갈라지지 않게 한다.
- selection → enriched join completion → dense completion → source window의 raw file SHA와 lineage SHA를 연속 검증한다.
- v2.5 replay integrity 원장으로 train/val/test의 모든 image·label bytes를 전수 재검증한다.
- empty label, bbox bounds, image/label SHA와 aggregate를 독립 검증한다.

## Task 8 — warm/clean comparison training

- 상태: 완료. 2026-08-27 15:24 KST부터 2026-08-31 21:10 KST까지 warm-start와 clean-reference 각각 seed 26/27/28 총 6회를 실행했다.
- 6개 run 모두 `results.csv`, `best.pt`, completion manifest와 return code 0을 확인했다. 순수 학습시간 합계는 78시간 43분, 전체 경과시간은 4일 5시간 46분이다.
- 학습 내부 validation 잠정 선두는 `warm-start-s28`이지만, Task 9의 독립 재평가 전에는 선택 후보나 운영 모델로 확정하지 않는다.
- v2.5 warm-start와 YOLO26n clean-reference를 공통 `epochs=100 / patience=20 / lr0=0.001` recipe, seed 26/27/28의 fresh path에서 실행한다.
- 실행 직전 repository HEAD, manifest, data.yaml, initializer와 모든 image/label SHA를 다시 확인한다.
- YOLO entrypoint SHA와 해당 runtime Python의 승인 package 버전/MPS 상태도 lock 전후에 확인한다.
- results.csv, best.pt, completion manifest를 no-overwrite로 남긴다.

## Task 9 — evaluation freeze

- 상태: 다음 실행 단계. 학습 내부 validation은 후보 탐색 참고값일 뿐이며, 동일 protocol 독립 ledger에서 다시 계산한다.
- 신규 validation에서 precision/recall/specificity/camera strata를 재계산한다.
- 합격 후보만 threshold/NMS와 10fps `3-of-5` temporal rule을 동결한다.
- frame metric 외에 clip-level TP/FP/FN, false-positive clip rate, episode cluster bootstrap CI를 계산한다.
- old fixed-test로 regression만 확인한다.

## Task 10 — sealed future holdout

- freeze cutoff 이후 새 camera-night에서 사람 blind holdout을 만든다.
- 선택 후보를 정확히 한 번 평가한다.
- 통과해도 shadow candidate로만 보고하고 production 배포는 별도 승인받는다.
