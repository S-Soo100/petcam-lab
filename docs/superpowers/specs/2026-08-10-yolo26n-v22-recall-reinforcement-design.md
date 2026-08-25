# YOLO26n v2.2 재현율 우선 보강학습 설계

**상태:** Owner 설계 방향 승인 · 구현 전 문서 검토
**목적:** 게코를 놓치는 미탐을 줄이되, 오탐을 무제한 허용하지 않는 다음 검출기 후보를 만든다.

## 1. 현재 근거

Dataset v2.1은 사람 bbox만으로 구성한 698장, 양성 398장, bbox 426개다. 카메라와 촬영 밤을
기준으로 train/val/test를 분리했고 이미지 해시 중복과 split 간 camera-night 누출은 0건이었다.

YOLO26n 960px 학습은 100 epoch를 완료했지만 최고점은 80 epoch였다. 내부 val 최고 성적은
precision 0.741, recall 0.642, mAP50 0.774, mAP50-95 0.390이고, 100 epoch에서는
mAP50-95가 0.358로 내려갔다. 따라서 같은 데이터로 epoch만 연장하는 안은 기각한다.

새 source에서 camera-night 단위로 분리한 development holdout 34장·23 bbox의 공통 비교는 다음과
같았다.

| 모델 | Precision | Recall | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|
| v2.0 | 0.711 | 0.478 | 0.491 | 0.270 |
| v2.1 | 0.674 | 0.565 | 0.640 | 0.317 |

v2.1은 더 많은 게코를 찾았지만 precision이 3.7%p 내려갔다. 남은 실패는 작은 개체, 부분 가림,
쳇바퀴, 야간·과노출, 다개체에 집중됐다. 이 34장은 이미 결과를 본 development 자료이므로 최종
채택 holdout으로 다시 쓰지 않는다.

## 2. 선택한 접근

v2.2는 **hard-case 표적 보강 + 전체 데이터 재학습**으로 간다.

기각한 대안은 두 가지다.

- v2.1 checkpoint를 같은 698장으로 계속 학습: 80 epoch 이후 하락 근거가 있어 과적합 위험이 크다.
- 무작위 프레임 대량 추가: 인접 프레임과 같은 camera-night 중복이 늘어 실제 독립성보다 장수만 커진다.

## 3. 데이터 구성

후보는 기존 Dataset v2.1 source와 이미지 해시를 제외한 production-purpose 원본에서만 만든다.
`test/` prefix, quarantine, source missing, media deleted, 촬영 오류는 제외한다. 모델·GME 출력은
후보 탐색에만 사용하고 사람 정답으로 채택하지 않는다.

목표는 최대 320장이다.

- hard positive 220장: 작은 게코, 부분 가림, 쳇바퀴 내부, 화면 가장자리, 야간 IR, 과노출,
  낮/밤 전환, 다개체를 우선한다.
- hard negative 100장: 게코처럼 보이는 잎·로프·은신처·반사·그림자·빈 사육장을 포함한다.
- 한 source에서 최대 2장, 한 camera-night에서 최대 12장만 허용한다.
- 가능한 모든 운영 카메라를 포함하고, 최소 3개 카메라를 확보하지 못하면 분포 제한을 보고한다.
- 인접 프레임·동일 이미지 해시·동일 source의 과대표집은 validator가 거부한다.

현재 34장 development holdout은 결과표를 동결한 뒤 development pool로 내린다. v2.2 split에 포함될
수는 있지만, 이후 성적표나 최종 채택 근거로 다시 쓰지 않는다.

## 4. 사람 검수 계약

CVAT에는 모델 bbox를 미리 넣지 않는다. Owner가 원본만 보고 `gecko` bbox를 직접 그린다.

- 머리와 몸통 또는 게코임을 식별할 충분한 신체 구조가 보이면 bbox를 친다.
- 꼬리만, 불확실한 그림자, 장식물처럼 게코라고 확정할 수 없으면 bbox를 치지 않는다.
- 여러 마리가 보이면 확인 가능한 개체마다 bbox를 하나씩 친다.
- 화면 밖으로 잘린 개체는 보이는 몸 영역을 tight box로 표시한다.
- 노출·가림 때문에 사람도 판정할 수 없는 이미지는 `ambiguous`로 제외한다.

사용 흐름은 `[CVAT 원본] 후보 이미지 확인 → [Owner 조작] bbox 추가·수정 또는 빈 이미지 유지 →
[반응] 저장된 사람 정답만 export → [감정] 모델 답을 따라 그리지 않고 일관된 기준으로 직접 판단`이다.

## 5. 학습 설계

기존 698장과 Owner가 승인한 신규 이미지를 합치고 source·camera-night 단위로 다시 분할한다.
같은 source나 camera-night가 둘 이상의 split에 들어가면 빌드를 실패시킨다.

동일 데이터로 후보 두 개를 만든다.

1. **warm start:** v2.1 `best.pt`에서 시작해 낮은 학습률로 최대 60 epoch, patience 15.
2. **clean reference:** 공식 YOLO26n pretrained checkpoint에서 시작해 최대 100 epoch, patience 20.

두 후보는 960px, 동일 seed, 동일 split, 동일 augmentation 계약으로 학습한다. warm start가 기존 능력을
유지하면서 hard case를 빨리 배우는지, clean reference가 누적 편향 없이 더 잘 일반화하는지를 같은
development set에서 비교한다. 한 후보만 유리하다고 미리 정하지 않는다.

## 6. Threshold와 성공 기준

confidence threshold는 future holdout을 보기 전에 development set에서 고정한다. 0.05~0.80 범위를
검사해 precision 0.60 이상을 만족하는 지점 중 recall이 가장 높은 값을 선택하고 모델·checkpoint·
threshold·이미지 크기를 한 묶음으로 기록한다.

최종 future holdout은 학습·후보 채굴·CVAT 검수에 쓰지 않은 이후 production-purpose 영상만 사용한다.
최소 조건은 120장, 양성 60장 이상, 음성 60장 이상, 최소 3카메라·6 camera-night다. 데이터가
부족하면 표본을 과거에서 보충하지 않고 촬영 재개를 기다린다.

v2.2 승격 조건은 다음과 같다.

- fixed-threshold recall 0.70 이상
- 같은 future holdout에서 v2.1보다 recall 10%p 이상 개선
- fixed-threshold precision 0.60 이상
- 작은 개체·가림·쳇바퀴·다개체·야간 strata별 결과 별도 보고
- decode 오류, label geometry 오류, source·camera-night 누출 0건

한 조건이라도 실패하면 `DEVELOPMENT_ONLY`로 유지한다. 표본이 작은 stratum은 성공으로 과장하지
않고 신뢰구간과 원수를 함께 보고한다.

## 7. 안전 경계

- YOLO는 게코 후보 bbox만 만든다. 행동명, 하이라이트, 활동시간, GT를 확정하지 않는다.
- `not detected`는 게코 부재가 아니며 `unresolved`과 합치지 않는다.
- 자동 skip, A/B 경로 이동, 원본 삭제, VLM 호출 차단 근거로 쓰지 않는다.
- DB·R2·production service·active model은 future holdout과 Owner 승인 전까지 변경하지 않는다.
- 학습 산출물은 Mac mini private artifact에 versioned checkpoint와 manifest로 보존한다.
- 라벨링 웹 public demo·팀 기여 기능은 별도 작업이며 이 학습 설계가 production 배포를 승인하지 않는다.

## 8. 단계와 완료 신호

1. `V22_CANDIDATE_QUEUE_READY`: 후보·제외 목록·중복 감사·strata 수량표가 준비됨.
2. `V22_HUMAN_REVIEW_REQUIRED`: CVAT Owner 검수가 필요함.
3. `V22_DATASET_READY`: 사람 export 병합, split, geometry, hash, camera-night 검증 통과.
4. `V22_TRAINED_DEVELOPMENT_ONLY`: 두 후보 학습과 development 비교 완료.
5. `V22_FUTURE_HOLDOUT_READY`: future pool 최소 조건 충족·시험지 동결.
6. `V22_ADOPTION_CANDIDATE`: 모든 성공 기준 통과. 이 상태도 Owner의 별도 active-model 승인이 필요함.
