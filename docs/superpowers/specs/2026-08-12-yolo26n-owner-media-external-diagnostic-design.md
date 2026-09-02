# YOLO26n Owner 촬영물 외부 진단 설계

## 1. 목적

`/Users/baek/yolo-gecko-demo`의 휴대폰 사진·영상을 이용해 펫캠과 다른 주간·근접·고해상도 환경에서
YOLO26n v2.2가 게코를 한 개체로 찾는지 진단한다. 이 자료는 과거 공개 데모에서 일부 모델 결과를 본
가능성이 있으므로 production future holdout으로 부르지 않는다.

## 2. Decision gate

- SOT 부합: GME의 detector 개선과 사람 GT 우선 원칙에 부합한다.
- 기대효과: 근접 사진의 미검출·몸 일부 중복 박스 문제를 수치화하고 v2.3 hard example 후보를 만든다.
- 측정 가능: 사람 bbox를 먼저 확정한 뒤 고정 v2.2 checkpoint·threshold로 recall, precision, duplicate
  box, IoU를 계산한다.
- 유효한 계획: 원본 불변, private local artifact만 생성, DB·R2·service·active model write 0이다.

판정은 `adopt / external diagnostic only`다. formal future holdout 승격 근거로 쓰지 않는다.

## 3. 사용자 체험

1. `[화면]` CVAT에 모델 박스 없는 익명 사진이 보인다.
2. `[조작]` 사람은 보이는 게코마다 머리·몸통을 중심으로 보이는 몸 영역 bbox를 그린다. 꼬리 끝은
   화면 밖이거나 가려졌다면 억지로 추정하지 않는다.
3. `[반응]` 게코가 없으면 빈 프레임으로 남기고, 사람도 판정하기 어려우면 별도 ambiguous CSV에
   `true`를 기록한다.
4. `[감정]` 모델 답에 끌려가지 않고 자신의 판단만 제출한다.
5. 제출 검증이 끝난 뒤에만 고정 모델 결과를 reveal해 차이를 본다.

## 4. 표본 계약

- 1차 큐는 사진 exact 240장이다. 영상 35개는 이번 큐에 섞지 않는다.
- 콘텐츠 생성일을 capture-day로 쓰고 날짜당 최대 3장으로 제한한다.
- 콘텐츠 SHA-256 완전중복과 Dataset v2.2 exact SHA overlap은 0이어야 한다.
- selection은 seed와 source SHA로 결정론적이어야 한다.
- capture-day를 먼저 나눠 60장은 `external_diagnostic`, 180장은 `training_candidate`로 고정한다.
- 양성·음성 수는 사람 검수 전 추측하지 않는다. diagnostic에 양성·음성이 각각 30장 미만이면
  정밀도·재현율을 함께 채점하지 않고 부족 수를 보고한다.

## 5. 개인정보·무결성

- CVAT 이미지 이름은 `O0001.jpg`부터 시작하며 원본 파일명·촬영일·기종을 노출하지 않는다.
- 파생 JPEG는 auto-orient 후 장축 1920px 이하로 축소하고 EXIF·GPS를 제거한다.
- private manifest만 원본 상대 이름, source SHA, capture-day, 기종, 파생 SHA를 가진다.
- 원본 파일은 읽기 전용이며 이동·이름 변경·삭제하지 않는다.
- 모델 예측, confidence, bbox는 selection과 사람 검수 화면에 포함하지 않는다.

## 6. 성공·중단 조건

- exact 240, capture-day 최소 80, 날짜당 최대 3, decode 실패 0, source/derived SHA 중복 0,
  EXIF profile 잔존 0, ZIP/manifest/index 수량 일치면 `OWNER_MEDIA_HUMAN_REVIEW_REQUIRED`다.
- 하나라도 실패하면 ZIP을 발행하지 않고 fail-closed한다.
- 사람 export 검증 전 inference·학습을 시작하지 않는다.
- DB·R2·production service·active model·Vercel은 변경하지 않는다.
