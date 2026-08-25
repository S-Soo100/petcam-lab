# YOLO26n v2.1 표적 보강 실행 계획

**목표:** 640px 기준선의 투명 쳇바퀴 오탐과 부분 가림·가장자리·과노출·다개체 미탐을 줄이되, 현재 시험지를 재사용해 성능을 과장하지 않는다.

## 안전 계약

- GME와 현재 YOLO 결과는 사람이 볼 후보를 찾는 데만 사용한다.
- 예측 박스는 CVAT에 미리 넣지 않는다. Owner가 원본 프레임을 보고 박스를 확정한다.
- 기존 528장의 원본 source는 제외하고, 같은 source에서 최대 4장만 뽑는다.
- 같은 camera-night가 큐를 독점하지 못하게 source 수를 제한한다.
- 현재 test 실패 장면은 개발 자료로만 취급한다. 최종 성적은 새 future holdout으로 측정한다.
- DB·R2는 읽기 전용이다. 원본 이동·복사·삭제·라벨 쓰기를 하지 않는다.

## 실행 순서

1. 기존 528장의 source 목록과 해시를 제외 목록으로 고정한다.
2. 2026-07-15 이후 production clip을 camera-night별로 층화한다.
3. GME의 multi/visible/unknown 신호로 넓은 source pool을 만든다.
4. 각 source의 12개 probe frame에 640px 기준선을 실행한다.
5. `hard_negative`, `hard_positive`, `multi_gecko`, `coverage` 네 후보군에서 총 80 source를 고른다.
6. source당 최대 4개 원본 프레임, 총 목표 320장을 예측 박스 없이 CVAT 업로드 묶음으로 만든다.
7. Owner 검수 후 기존 528장과 병합해 Dataset v2.1을 처음부터 재학습한다.
8. 기존 test는 개발 비교용으로만 보고, 새 독립 holdout에서 presence·box·event 성능을 확정한다.

## 완료 신호

- `CANDIDATE_QUEUE_READY`: 후보 묶음·익명 manifest·중복 검사·수량표가 준비됨.
- `HUMAN_REVIEW_REQUIRED`: CVAT에서 Owner 박스 검수가 필요함.
- `DATASET_V2_1_READY`: 검수 결과 병합·split·학습 입력 검증 완료.
