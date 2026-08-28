# YOLO26n v2.6 최근 연속영상 촘촘 재학습 설계

**상태:** 사람 GT·독립 QA 완료 / dataset v2.6 build 준비
**승인일:** 2026-08-26 KST
**목적:** 최근 연속영상에서 확인된 GME YOLO v2.5의 미탐·오탐·잘못된 bbox를 사람 GT로 교정하고, 연속영상 분포를 대표하는 다음 development-only detector를 만든다.

## 1. 한 줄 결정

2026-08-24 00:00 KST부터 2026-08-26 16:13 KST까지의 production motion clip 566개를 source ledger에 남긴다. 이전 Owner 승인으로 삭제된 55초 미만 137개는 tombstone으로 보존하고, R2 원본이 남은 429개를 모두 읽어 2fps raw frame ledger를 만든다. raw frame을 모델 정답으로 사용하지 않고, 모든 유효 clip을 포함하는 균일 표본·확실한 빈 화면 후보·오류 가능성이 높은 표본·IID 무작위 표본을 사람에게 blind bbox 검수시킨다. 사람 확정 GT만 기존 replay GT와 결합해 matched warm-start와 clean-reference를 비교학습한다. 최종 GME 서빙 판별은 **10fps**로 고정하고 단일 frame이 아니라 연속 frame을 합쳐 clip 판정을 내린다.

Claude는 코드·데이터 계약·누수 방지 교차검수에만 사용한다. 영상 판독, bbox 생성, GT 확정에는 사용하지 않는다.

### 1.1 2026-08-28 Owner 운영 결정

v2.5는 최근 야간 시야에서 게코를 거의 잡지 못하는 사례가 반복돼 현재 라벨링 보조용 detector로도 품질 문제가 크다. 그렇다고 진행 중인 v2.6 비교를 중간 후보 하나로 조기 종료하지 않는다. warm-start/clean-reference 각 seed `26/27/28`의 6회 학습과 동일 protocol 평가를 2026-08-30 전후까지 그대로 완료한다.

- 6회 결과 중 development validation 기준을 통과한 최적 후보를 고르고 threshold/NMS/10fps temporal rule과 old fixed-test regression을 확인한다.
- 기준을 통과하면 v2.6은 장기 future holdout 완료를 기다리지 않고 active GME shadow와 라벨링 웹의 YOLO 보조 표시에 우선 반영할 수 있다. 이는 심각한 v2.5를 교체하기 위한 가역적 운영 조치이며 production 성능 채택 주장이 아니다.
- v2.5 checkpoint와 detector identity는 즉시 롤백할 수 있게 보존한다. v2.6 결과만으로 영상 삭제, 자동 skip, 사람 정답 확정, 활동량 사용자 지표 승격을 허용하지 않는다.
- 반영 뒤 확인되는 미탐·오탐·bbox 오류는 사람 검수 원장에 축적해 v2.7의 우선 hard-case로 넘긴다.

## 2. 관찰 근거와 원인 가설

고정 창의 read-only 실측은 다음과 같다.

- production DB clip 566개, camera 2대, 총 28,341.8초
- 55초 미만 삭제 정책과 정확히 일치하는 R2 tombstone 137개, 2,214.63초
- 접근 가능한 원본 429개, 26,127.14초, 5.81GB
- v2.5 GME run 566개 모두 계산 성공, 동일 detector identity
- GME는 이미 median 10fps로 분석했다. 따라서 이번 문제는 런타임 sampling 간격이 성기기 때문이라고 볼 수 없다.
- active detector는 YOLO26n v2.5 warm-start, `imgsz=960`, threshold `0.20`, NMS IoU `0.70`이다.
- v2.5 기존 dataset은 positive 1,213 / negative 750이지만 새 hard-case 201장은 positive 198 / negative 3이었다.
- 과거 validation은 precision 0.621 / recall 0.774, internal fixed-test는 precision 0.731 / recall 0.756이었다. 두 시험은 반복 사용된 과거 분포의 regression 확인용이고 formal future holdout이 아니었다.

현재 가장 유력한 원인은 다음 조합이다.

1. 선택된 정지 frame 중심 학습과 최근 연속영상 사이의 분포 차이
2. 새 hard-case 보강에서 연속 장면 hard negative가 거의 없었던 불균형
3. old validation에서 정한 낮은 threshold 0.20이 새 배경의 false positive를 충분히 억제하지 못함
4. 기존 평가지가 최근 카메라·조명·가림·배경을 대표하지 못했음
5. 50초 영상에서 약 500번의 frame 판정을 개별 OR처럼 취급해 작은 frame 오탐률이 clip 오탐으로 증폭됐을 가능성

이번 연구는 이 가설을 데이터로 검증한다. 단순 threshold 조정만으로 해결됐다고 주장하지 않는다.

## 3. 역할과 불변 경계

| 자산 | 역할 | 금지 |
|---|---|---|
| 최근 DB clip 566 | development source 계보 | tombstone 복구 추정, 자동 GT화 |
| 접근 가능 clip 429 | 실제 frame 후보 모집단 | 원본 수정·삭제 |
| 2fps raw ledger | 검수 후보를 다양하게 뽑기 위한 모든 영상 접근 증거 | 전량 JPEG 영구 중복 저장 |
| v2.5 prediction | queue 층화·선택 보조 | 사람 GT 대체, 자동 bbox 확정 |
| 사람 presence/bbox | 신규 train/validation GT | 예측을 보지 않은 것처럼 허위 기록 |
| v2.5 dataset | replay와 old regression | 기존 val/test 수정 |
| 최근 566 | 오류 노출된 development 자료 | formal future holdout 주장 |
| cutoff 이후 새 영상 | sealed future holdout 후보 | threshold·후처리 선택 |
| 10fps GME 판정 | 실제 서빙 시간축 계약 | 한 frame 검출만으로 clip 존재 확정 |

이번 연구의 고정 실행 호스트는 **BaekBook-Pro-14-M5.local(MacBook Pro M5, 32GB, MPS)**이다. 맥미니는 운영 GME와 원본 생산 장비로만 유지하고 연구 코드·학습 부하를 올리지 않는다. production DB/R2 row, 기존 GME run, active checkpoint, 라벨링 GT는 이번 준비·학습에서 수정하지 않는다. 새 산출물은 맥북 private attempt의 신규 경로에만 쓴다.

## 4. 데이터 준비 계약

### 4.1 raw sampling

- 접근 가능한 429 clip을 2fps, 즉 0.5초 간격으로 순차 decode한다.
- 실측 raw ledger는 52,356 frame이다.
- 각 raw row에 camera-night group, clip reference, timestamp, decoded frame index, image SHA와 dHash를 기록한다. source SHA와 decode 완료·frame-count 검사는 clip completion 원장에 한 번 기록하고, join·selection은 그 completion/ledger SHA를 다시 검증한다.
- raw frame은 스트리밍으로 처리하고 선택되지 않은 JPEG는 저장하지 않는다. 원본 8.07GiB와 맥미니 여유공간을 동시에 보호하기 위해서다.
- decode 실패, duration/count mismatch, source SHA drift는 해당 clip을 조용히 건너뛰지 않고 별도 shortage로 남긴다.

### 4.2 선택과 중복 제거

CVAT 후보는 다음 네 층과 별도 QA 층을 합친다.

1. **coverage layer 858장:** 모든 유효 clip 429개에서 2개 timestamp를 보존한다.
2. **uncertainty/disagreement 900장:** 사람 feedback 주변, detection 유무 전환, low-confidence와 OpenCV motion 동시 발생, scene 변화 구간을 추가한다.
3. **hard-negative 후보 350장:** 기존 모델이 높은 신뢰도로 검출했지만 화면 변화가 작았던 후보를 보존한다. 같은 정적 배경 반복을 억지로 700장 채우지 않는다.
4. **IID random 400장:** 모델 점수와 무관한 무작위 표본을 유지해 active-learning 편향을 측정한다.
5. **gold double-review 200장:** 위 표본 일부를 예측 정보 없이 독립 재검수한다.

exact SHA 중복은 전역 제거한다. dHash distance `<=2`는 같은 clip의 시간 중복 제거에 사용하되, 사람 feedback 주변 `±2초`와 detection transition은 최대 2장의 near-duplicate 예외를 허용한다. camera-night/clip 단위 cap으로 한 장면 과대표집을 막는다. 층 간 중복은 한 장으로 합치되 모든 선정 사유를 원장에 남기며, 부족분을 다른 층으로 조용히 전용하지 않는다.

실측 고유 이미지 큐는 2,508장(858+900+350+400)이며, 200장 blind double-review를 더해 사람 판정 작업은 2,708건이다. 자동 결과가 층별 목표를 벗어나면 임의 truncate하거나 모델 예측으로 채우지 않고 strata별 shortage/overflow를 보고한다.

2026-08-26 독립 검수에서 primary 2,508장과 double-review 200장의 ZIP/image SHA 연결이 모두 일치했다. 익명 파일명 위반, 중복 primary SHA, 과거 protected fingerprint distance `<=2` 혼입은 각각 0건이다. 손상된 H264 구간 1장은 같은 source clip 안의 deterministic reserve frame으로 교체했으며, 교체 전 selection SHA와 교체 후 dense ledger row/SHA를 함께 검증하고 429개 clip coverage를 유지한다.

2026-08-27 사람 판정과 Owner adjudication까지 완료됐다. 최종 GT는 2,508장 중 present 1,465장, absent 1,043장, bbox 1,474개이며, primary/double-review/adjudication export와 review/selection 원장의 SHA에 묶였다. 이 수치는 dataset builder가 원본 QA artifact를 다시 검증한 경우에만 학습 입력으로 인정한다.

### 4.3 negative 보존

새 cohort는 사람 판정 후 `gecko_absent` frame을 최소 35%, 목표 40~50% 보존한다. hard-negative 후보 350장의 사람 결과와 전체 사람 확인 empty 최소 700장을 별도로 집계한다. 이는 모델이 정한 negative가 아니라 사람이 확인한 hard negative다. `GME 미검출`은 `미검수`일 뿐 empty로 간주하지 않는다. 각 camera-night에서 negative가 빠지지 않아야 하며, positive만 많은 clip도 coverage 표본을 유지한다.

### 4.4 환경별 파충류 행동량 연구 영상의 후속 편입

`환경별 파충류 행동량 연구 문서화` 세션에서 C500G로 촬영하는 야간 영상은 기존 두 카메라와 다른 사육장·조명·가림·배경 분포를 보강하는 prospective source다. 이 영상은 이미 동결된 v2.6 dataset과 진행 중인 6회 비교학습에는 추가하지 않는다.

2026-08-28 Owner가 승인한 다음 학습 목표는 **일주일 동안 9개 사육장을 하루 약 12시간씩 촬영한 원본**을 v2.7의 주 데이터로 사용하는 것이다. 계획 상한은 약 `9 × 12 × 7 = 756 enclosure-hours`이며, 실제 편입량은 녹화 완료 뒤 USB/R2/DB manifest의 exact source 수·재생 가능 시간·SHA를 대조해 확정한다. 현재 일부 카메라에서 먼저 쌓인 녹화는 초기 수집분이며 일주일 전체 수량으로 확대 해석하지 않는다.

- model/threshold freeze 전에 촬영한 설치 canary·30분 테스트·야간 영상은 사람 presence/bbox 검수 후 v2.7 development train/validation 후보로만 사용한다.
- v2.6 detector threshold·NMS·10fps temporal rule을 동결한 뒤 촬영되는 첫 3개 complete camera-night은 sealed future holdout으로 예약한다. 최소 300 clip과 1,200 frame GT를 채우기 전에는 수량을 줄여 성능을 주장하지 않는다.
- sealed future holdout에 들어간 source·frame은 이후 v2.7 학습자료로 재사용하지 않는다. holdout 평가가 끝난 뒤 촬영한 영상과 별도 development cohort에서 확인된 오탐·미탐만 v2.7 보강 후보로 넘긴다.
- 같은 camera-night의 frame을 train/validation/holdout에 나누지 않는다. camera-night 전체를 하나의 group으로 고정하고 source video SHA, camera, 촬영 시작·종료, 사육환경 유형과 익명 개체·사육장 key를 provenance에 남긴다.
- v2.7은 모든 원본 영상을 source inventory에 포함하되 모든 연속 frame을 그대로 학습하지 않는다. 사육장·night별 coverage, 게코 존재/부재, 야간 IR, 가림, 정지/이동, 배경 hard-negative와 v2.6 오류 strata를 균형 있게 추출하고 동일 장면 반복은 exact/dHash/시간 중복 제거로 제한한다.
- v2.6 prediction은 검수 우선순위를 정하는 보조 정보일 뿐 정답이 아니다. v2.6 미검출도 자동 `gecko_absent`로 두지 않고 사람이 presence와 각 개체 bbox를 확정한 자료만 v2.7 GT가 된다.
- v2.7 split의 최소 경계는 `enclosure-night`이다. 같은 사육장·같은 밤에서 파생된 영상·frame은 train/validation/holdout 중 하나에만 들어가며, 사육장별·night별 데이터 양과 positive/negative 비율을 따로 보고한다.
- 행동량 연구의 행동명·이동거리·환경군 판정은 YOLO 정답으로 사용하지 않는다. YOLO 학습에는 사람이 확정한 `gecko_present`/`gecko_absent`와 bbox만 사용한다.
- 원본 USB·R2·DB는 read-only source로 취급하고, 추출·검수·학습 산출물은 별도 private attempt에 no-overwrite로 저장한다.

## 5. 사람 검수 흐름

```text
[화면] 예측 박스와 GME 점수가 숨겨진 frame이 보인다.
→ [조작] 게코 있음 / 없음 / 불확실 / 영상 오류를 고른다.
→ [반응] 게코 있음이면 bbox를 직접 그리는 단계가 열린다.
→ [조작] 보이는 각 게코를 개별 bbox로 저장한다.
→ [반응] immutable 제출이 기록되고 다음 frame으로 이동한다.
→ [감정] 모델 답을 고치는 일이 아니라 실제 화면의 정답을 만드는 일이라고 느낀다.
```

- `gecko_present`: 하나 이상의 valid bbox 필수
- `gecko_absent`: 빈 label을 의도적으로 보존
- `uncertain`: absent에 합치지 않고 학습 제외
- `media_error`: 학습 제외와 decode 감사 대상으로 분리
- 200장은 blind double-review와 Owner adjudication으로 bbox 누락·과대 box·preannotation anchoring을 측정한다. presence 불일치와 bbox IoU `<0.5` conflict 집합은 adjudication index와 정확히 같아야 한다.

## 6. split과 누수 방지

- frame random split을 금지한다.
- 최소 분리 단위는 60초 이내 인접 clip을 묶은 episode다. camera-night를 층화해 한 night가 한 split을 독점하지 않게 한다.
- 신규 recent cohort는 episode group 기준 train/validation `80:20`으로 고정한다. 기존 v2.5 train은 replay로 train에만 들어가며, old val153/test151은 regression 전용으로 분리한다.
- 같은 episode, 동일 source SHA, exact image SHA가 train과 validation에 동시에 존재하면 fail closed다. dHash distance `<=8`은 같은 camera-night에서 절대 촬영시각이 5분 이내인 경우에만 중복 누수로 판정한다. 그보다 먼 전역 dHash 유사도는 고정 배경 충돌이므로 경고 집계만 한다.
- 최근 566 중 사람 판정 완료분은 development train/validation으로만 사용한다.
- 기존 v2.5 val153/test151은 bytes 그대로 old-distribution regression에만 사용한다.
- 기존 v2.5 train/val/test의 모든 image·label bytes는 별도 replay integrity 원장에 동결하고 dataset build 전에 전수 SHA를 대조한다.
- final 성능은 model/threshold/NMS를 동결한 뒤 cutoff 이후 촬영된 별도 camera-night future holdout으로만 판단한다.
- 환경별 행동량 연구 영상도 camera-night group 경계를 그대로 적용한다. 같은 개체·사육장·night의 인접 영상이 development와 future holdout 양쪽에 나타나면 fail closed다.

## 7. 학습 비교

같은 신규 dataset으로 두 후보를 한 번씩 비교한다.

- warm-start: frozen v2.5 checkpoint에서 시작
- clean-reference: 승인 YOLO26n base checkpoint에서 시작
- 기존 positive/negative replay를 유지해 최근 두 camera-night에만 과적합하지 않게 한다.
- initialization을 제외한 imgsz/batch/epoch/lr/augmentation/early-stop 조건을 동일하게 맞춘다.
- 공통 비교 recipe는 `epochs=100`, `patience=20`, `lr0=0.001`, `AdamW`, `imgsz=960`, `batch=2`로 고정한다. 이는 clean-reference에 충분한 학습 예산을 주면서 initializer 이외의 차이를 제거하기 위한 선택이다.
- seed `26/27/28` 세 개를 실행해 MPS 비결정성과 후보 우열의 안정성을 기록한다.
- 실행할 YOLO entrypoint SHA와 그 entrypoint가 가리키는 Python/package 버전을 학습 lock 전후에 다시 확인한다.
- train/serve resize, letterbox, color channel, normalization 계약의 parity를 테스트한다.
- 실패 run을 같은 경로에 덮어쓰지 않는다.

## 8. 10fps GME 시간축 판정

- GME detector 입력은 최대 `10fps`로 고정한다. 원본이 10fps 미만이면 frame을 복제하지 않는다.
- native frame 선택은 직전 선택 시각에 간격을 더하지 않고 절대 `n/10초` deadline grid에 맞춘다. 따라서 25fps·29.97fps에서도 누적 drift로 분석률이 낮아지지 않는다.
- source freeze에 포함되는 기존 GME job은 exact clip set과 detector identity뿐 아니라 status `succeeded`를 전부 만족해야 한다.
- 기본 존재 판정 후보는 `5 frame(0.5초) 중 3 frame 이상 검출`이다.
- 1~2 frame짜리 단발 box는 존재 확정이 아니라 `unknown/검수 후보`로 남긴다.
- 짧은 미탐 gap을 이어 붙이는 최대 길이와 bbox track 연결 조건은 development validation에서만 선택하고 freeze한다.
- frame precision/recall과 별도로 clip TP/FP/FN, false-positive clip rate, miss clip rate를 계산한다.
- 시간축 규칙과 detector threshold를 동결한 뒤에는 old test와 sealed future holdout에서 재선택하지 않는다.

## 9. 평가와 합격 기준

threshold는 신규 development validation에서 고정한다. 최소 후보 기준은 다음과 같다.

- 신규 validation precision `>=0.80`
- 신규 validation recall `>=0.90`
- 사람 확인 empty frame specificity `>=0.90`
- camera별 recall `>=0.85`
- duplicate rate가 v2.5보다 악화되지 않음
- old fixed-test precision/recall 각각 v2.5 대비 `-0.02` 이내
- recent development의 clip false-positive rate가 v2.5보다 상대 `50%` 이상, 절대 `5%p` 이상 감소
- recent development의 clip recall이 v2.5보다 `2%p` 넘게 하락하지 않음
- episode cluster bootstrap 95% CI로 개선 방향이 뒤집히지 않음
- lineage, protected overlap, partial artifact, forbidden write 0

동결 후 cutoff 이후 최소 3개 night, 300 clip, 150 clip 이상에서 뽑은 1,200 frame GT의 sealed future holdout에서도 같은 기준을 통과해야 정식 production 성능 후보가 된다. 수량이 부족하면 기다리지 않고 성능을 주장하는 대신 `holdout shortage`로 보고한다. 단 2026-08-28 Owner 결정에 따라 validation과 old regression을 통과한 v2.6을 가역적인 active GME shadow·라벨링 보조에 먼저 반영하는 것은 허용한다. 이 조기 교체는 future holdout 통과나 사용자 지표 승격을 뜻하지 않는다.

## 10. 실패 처리

- 사람 bbox GT 미완료: dataset build와 training을 시작하지 않는다.
- negative 비율 35% 미만: positive-only 보강을 진행하지 않고 queue를 재층화한다.
- protected overlap 또는 group leakage: dataset publish 전 fail closed
- 맥북 free space가 private attempt peak 예상량 + 30GiB보다 작음: 추출 시작 전 중단
- 일부 source decode 실패: 성공으로 숨기지 않고 exact count와 원인을 보고
- validation 기준 미달: future holdout 접근·active GME shadow 교체 금지

## 11. 완료 조건

- [x] 566개 DB source·429개 접근 가능·137개 tombstone의 immutable inventory와 lineage가 고정됨
- [x] 유효 source 429개를 2fps로 읽은 52,356-row raw ledger와 decode aggregate가 생성됨
- [x] coverage/uncertainty/hard-negative/IID/gold strata가 있는 blind bbox queue가 생성되고 독립 ZIP/SHA/protected-overlap 검수를 통과함
- [ ] 사람 presence/bbox 검수가 완료되고 negative 비율·bbox QA가 통과함
- [ ] group leakage 없는 dataset manifest가 생성됨
- [ ] matched warm/clean 3-seed 학습과 신규 validation detector/10fps temporal freeze가 완료됨
- [ ] old regression과 sealed future holdout report가 완료됨
- [ ] production/DB/R2/GME checkpoint write가 0임
