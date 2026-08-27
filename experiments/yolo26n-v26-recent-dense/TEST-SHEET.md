# YOLO26n v2.6 recent dense — TEST-SHEET

**상태:** 사전등록 고정 / 사람 GT·독립 QA 완료
**실행 호스트:** `BaekBook-Pro-14-M5.local`
**운영 변경:** 금지

## 1. 고정 입력

- source window: `2026-08-24T00:00:00+09:00` 이상, `2026-08-26T16:13:29.838806+09:00` 이하
- expected clip: 566
- expected camera: 2
- expected duration aggregate: 28,341.8초
- approved prior deletion tombstone: 55초 미만 137개 / 2,214.63초
- accessible source: 429개 / 26,127.14초 / 5,808,315,022 bytes
- source는 DB/R2 read-only로 접근하며 private attempt 외 쓰기는 0이다.
- 최근 566개는 development 자료이며 future holdout으로 부르지 않는다.

## 2. 추출과 사람 GT

- raw decode: 2fps, 접근 가능 429 clip, 실측 52,356 frame ledger
- unique queue 목표: coverage 858 / uncertainty-disagreement 900 / hard-negative 후보 350 / IID random 400
- double-review gold: 200
- exact SHA 전역 dedup, same-clip dHash `<=2` dedup
- `GME 미검출`은 `미검수`이며 사람 확인 전 negative가 아니다.
- 학습 입력은 사람 확정 `gecko_present+bbox`와 `gecko_absent`만 허용한다.
- final confirmed-empty 비율 `>=35%`, hard-negative 후보 350 결과 별도 집계, confirmed-empty `>=700`
- blind bundle 실측: primary 2,508장 / double-review 200장 / source clip coverage 429개
- 독립 검수: image/ZIP SHA mismatch 0, 익명 파일명 위반 0, primary exact duplicate 0, protected dHash distance `<=2` overlap 0
- 최종 사람 GT: 2,508장 중 present 1,465 / absent 1,043 / bbox 1,474, Owner adjudication 완료

## 3. split

- 60초 이내 인접 clip을 하나의 episode로 묶는다.
- episode 단위 split, camera-night 층화
- 신규 recent cohort는 episode group 기준 train/validation `80:20`으로 고정한다.
- source/image exact SHA overlap 0
- 같은 camera-night·절대 촬영시각 5분 이내의 cross-split dHash distance `<=8` overlap 0
- 5분을 넘긴 전역 dHash 유사도는 고정 카메라 배경 충돌이므로 경고 집계만 한다.
- old val153/test151은 수정하지 않고 regression 전용으로 유지한다.
- v2.5 train/val/test 전체 image·label SHA는 별도 replay integrity 원장과 일치해야 한다.

## 4. 학습

- 후보: v2.5 warm-start / approved YOLO26n clean-reference
- 두 후보의 initialization 외 recipe는 동일하다.
- seed: 26, 27, 28
- 공통 recipe: epochs 100 / patience 20 / lr0 0.001
- 공통: AdamW / imgsz 960 / batch 2 / MPS / workers 0 / v2.5 augmentation 계약 상속
- MacBook MPS 실행, fresh no-overwrite run root
- YOLO entrypoint SHA와 runtime Python 3.12.13 / ultralytics 8.4.118 / torch 2.13.0 package set을 실행 전후 고정
- train/serve preprocessing parity를 manifest에 고정한다.

2026-08-27 사전 코드리뷰에서 후보별 epoch/lr 차이가 initialization 효과와
optimization budget 효과를 섞는 문제가 확인됐다. 따라서 v2.6 비교는 두 후보 모두
위 공통 recipe를 쓰며, initializer만 다르게 고정한다.

## 5. GME 판정 계약

- detector analysis rate: 최대 10fps, 낮은 원본 fps는 복제 금지
- sampling: 절대 `n/10초` deadline grid, 25fps·29.97fps drift 테스트 필수
- frozen source GME lineage: exact set / detector identity / status `succeeded` 전수 일치
- 사전등록 기본 temporal rule: 5 frame 중 3 frame 이상 검출
- 단발 1~2 frame 검출: `unknown/review`, clip present 확정 금지
- detector threshold/NMS/temporal gap은 development validation에서만 고른 뒤 함께 freeze한다.

## 6. 평가

- frame precision/recall/specificity/duplicate/bad-box
- clip TP/FP/FN, clip precision/recall, false-positive clip rate
- camera/night/episode strata
- episode cluster bootstrap 95% CI
- old fixed-test regression: precision/recall 각각 v2.5 대비 `-0.02` 이내
- recent development: clip FP rate 상대 `-50%` 및 절대 `-5%p`, clip recall 하락 `<=2%p`

## 7. sealed future holdout

- freeze cutoff 이후 최소 3 night / 300 clip
- 최소 150 clip에서 1,200 frame 사람 GT
- model/threshold/NMS/temporal rule 변경 없이 정확히 한 번 평가
- 수량 부족이면 shortage이며 production 성능을 주장하지 않는다.

## 8. 중단 조건

- source count/window/SHA drift
- 사람 GT 미완료 또는 negative 계약 미달
- protected overlap, split leakage, partial artifact
- train/serve preprocessing 불일치
- 운영 DB/R2/service/checkpoint write 감지

통과해도 결과는 `shadow candidate`이며 production 채택·배포는 별도 승인이다.
