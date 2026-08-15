# YOLO26n v2.5 Future Holdout 설계

**상태:** 승인됨 — v2.5 학습 설계 Task 7의 후속 실행

**목적:** v2.5 선택 이후 새로 촬영된 production 영상만 사용해 prediction-blind 시험지를 만들고,
동결한 v2.4와 v2.5를 같은 조건으로 한 번씩 비교해 production 채택 여부를 판단한다.

## 1. 현재 근거와 경계

- v2.5 warm-start는 development internal test에서 threshold `0.20`, precision `0.7312`, recall
  `0.7556`이었다.
- 같은 프로토콜의 v2.4는 precision `0.7326`, recall `0.7000`이었다.
- 이 결과는 반복 노출된 old distribution의 regression 지표다. production 일반화 근거가 아니다.
- selection freeze 생성 시각 뒤에 촬영된 원본만 future 후보가 된다.
- v2.5 dataset 1,963장, validation 153장, internal test 151장, Owner external 60장과 그 파생물은
  exact SHA/source/night/dHash exclusion에 포함한다.
- threshold, checkpoint, NMS, imgsz, max_det은 holdout 결과를 보기 전에 동결하고 다시 튜닝하지 않는다.

## 2. 사람 체험 흐름

1. **[화면]** `P####` 익명 이미지와 `게코 보임 / 빈 장면 / 판단 불가`만 보여준다.
2. **[조작]** Owner가 모델 box·confidence·source·날짜를 보지 않고 presence를 판정한다.
3. **[반응]** 시스템이 판단 불가를 시험지에서 제외하고 양성·음성 균형과 provenance를 재검증한다.
4. **[화면]** exact final holdout을 새 CVAT 작업으로 보여준다. prediction은 계속 숨긴다.
5. **[조작]** 보이는 각 게코의 보이는 몸 영역에 bbox를 만든다. 꼬리 끝은 보이는 범위만 포함한다.
6. **[반응]** export validator가 이미지 SHA·크기·순서·bbox·0개 negative를 검증한다.
7. **[감정]** 사용자는 모델 답을 따라 그리는 게 아니라 독립 시험지를 만든다는 확신을 가진다.

## 3. 표본 계약

- 목표 final: 200장, 양성 100장 + 음성 100장.
- 최소 실행 가능선: 120장, 양성 60장 + 음성 60장. 목표 200장이 불가능할 때 자동 축소하지 않고
  Owner가 별도로 승인한다.
- reserve: 최대 400장. source당 최대 2장, camera-night당 최대 24장.
- 최소 3개 camera, 6개 camera-night. 낮/밤, 작은 개체, 가림, 쳇바퀴, 반사·과노출을 aggregate로
  기록하되 모델 신호로 표본을 고르지 않는다.
- 같은 영상·인접 파생 frame·동일 이미지 SHA·source-local dHash `<=2` 중복은 하나만 남긴다.

## 4. 데이터 흐름

```text
v2.5 selection freeze + selected checkpoint
  -> post-freeze production metadata SELECT
  -> historical/source/night/image/dHash exclusion
  -> blind reserve JPEG + private provenance
  -> Owner presence screen
  -> balanced final set
  -> blind CVAT bbox
  -> normalized immutable GT
  -> v2.4/v2.5 fixed one-shot ledgers
  -> independent metric recompute
  -> adopt / hold
```

DB와 R2는 metadata SELECT와 exact object GET만 허용한다. DB/R2 write, service 변경, Git 배포,
Gecko Vision Gate/GME/labeling worker 교체는 금지한다.

## 5. 동결 평가 계약

- checkpoint: frozen v2.4와 selected v2.5 warm-start만.
- confidence threshold: 두 모델 모두 `0.20`.
- inference: `imgsz=960`, low-confidence ledger `conf=0.001`, `nms_iou=0.70`, `max_det=50`.
- match IoU: `0.50`.
- 각 모델은 final holdout에 정확히 한 번만 inference한다.
- prediction ledger가 만들어지기 전에는 GT와 모델 결과를 결합하지 않는다.

## 6. 채택 판정

v2.5는 다음을 모두 만족할 때만 shadow 채택 후보가 된다.

1. precision `>=0.60`
2. recall `>=0.70`
3. 같은 holdout의 v2.4보다 recall `>=3%p` 개선
4. 낮/밤 주요 subgroup 중 어느 한쪽도 recall `>5%p` 후퇴하지 않음
5. lineage, overlap, decode, bbox, one-shot, write 위반 0

통과해도 바로 production 모델을 교체하지 않는다. Owner Preview와 Gate/GME shadow canary를 거친다.

## 7. 현재 readiness

selection freeze 뒤 production clip inventory는 `0`이다. 이는 규칙 오류가 아니라 새 촬영분이 아직 없는
실제 데이터 부족이다. 새 production clip이 쌓일 때까지 readiness는 read-only aggregate만 갱신하고,
예전 development 영상을 future라고 재분류하지 않는다.

## 8. 오류 처리

- 새 영상 0 또는 표본 부족: `WAITING_FOR_FUTURE_MEDIA`, R2 GET·사람 큐 0.
- protected overlap 또는 SHA drift: 해당 source 제외 후 aggregate 기록. 목표 수량 미달이면 중단.
- prediction/source 정보가 blind ZIP에 들어가면 전체 publish 실패.
- 사람이 `판단 불가`로 표시한 frame은 negative로 간주하지 않는다.
- one-shot lock 뒤 inference 실패 시 같은 경로를 재사용하지 않고 별도 승인된 attempt만 허용한다.

## 9. 완료 조건

- immutable readiness/inventory/provenance ledger
- blind reserve와 presence screen
- exact final holdout와 CVAT export acceptance
- v2.4/v2.5 one-shot ledger 및 독립 재계산 일치
- 채택 또는 보류 판정
- production/DB/R2/service/model write 0
