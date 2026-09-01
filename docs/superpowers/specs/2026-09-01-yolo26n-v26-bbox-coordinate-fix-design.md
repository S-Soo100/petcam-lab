# YOLO26n v2.6 bbox 좌표 계약 수정 설계

## 문제

Ultralytics `boxes.xywh`는 중심점 `(center_x, center_y, width, height)`을 반환하지만 GME의
`Detection.bbox_xywh`와 tracker는 좌상단 `(x, y, width, height)`을 받는 계약이다. 기존 adapter가
변환 없이 전달해 라벨링 웹 박스와 GME 추적 영역이 각각 박스 너비의 절반만큼 오른쪽, 높이의 절반만큼
아래로 이동했다.

복수 탐지 자체는 오류가 아니다. 실제 게코와 유리 반사를 동시에 잡은 박스는 각각 독립 탐지로 보존한다.

## 범위

### 포함

- YOLO adapter 경계에서 중심 xywh를 좌상단 xywh로 변환
- post-NMS는 기존과 같은 중심 xywh에서 수행해 복수/반사 탐지 의미 보존
- 좌표 계약을 v2.6 execution contract에 추가하고 새 detector identity 생성
- worker, live enqueue, 라벨링 웹이 새 identity만 사용하도록 전환
- 기존 job, run, artifact를 수정하지 않는 append-only 재분석

### 제외

- 모델 checkpoint, threshold, NMS 수치, tracker 알고리즘 변경
- 반사 박스 제거
- 사람 GT, 라벨링 판정, 원본 영상 변경
- 기존 잘못된 artifact의 삭제·덮어쓰기·인플레이스 보정

## 고정 계약

- model version: `v2.6-warm-start-s28`
- checkpoint SHA-256: `a00e5a7a1e1f9197accb036339a38a7c821f03c8ab79611ebce89e5cde59b513`
- 이전 detector identity: `89e4738a60ebb71900e05e96f5b7262e8b900f5c9bba9b9cb9e34fca36f789b7`
- 새 bbox coordinate contract: `xywh-top-left-v1`
- 새 detector identity: `deccfc8315d3c00edb5bf59db3c573dca568e9d6d7a5da8d7dc93d2082bdb899`

새 identity는 좌표 계약을 포함한 canonical execution contract SHA-256이다. 웹은 새 identity의 성공 run만
표시하므로 기존 좌표가 잘못된 artifact로 fallback하지 않는다.

## 승인 기준

1. 중심 `(50, 40, 20, 10)`이 좌상단 `(40, 35, 20, 10)`으로 변환된다.
2. 겹치지 않는 실제/반사 두 박스는 두 개로 유지된다.
3. Gate, worker, backend, web 회귀 테스트와 web typecheck가 통과한다.
4. migration은 현재 live 함수가 이전 identity인지, identity-isolated claim RPC가 있는지 확인하고 실패 시 중단한다.
5. 새 identity canary에서 박스가 게코 몸에 맞고 job/run/artifact provenance가 일치한다.
6. canary 성공 전에는 live trigger, web active identity, historical backfill을 전환하지 않는다.

## 롤백

canary나 live 검증 실패 시 worker를 중지하고 live 함수·웹 active identity를 이전 identity로 되돌린다.
새 identity로 이미 생성된 job, run, artifact는 감사 증거로 보존한다. 기존 및 신규 산출물을 삭제하거나
덮어쓰지 않는다.
