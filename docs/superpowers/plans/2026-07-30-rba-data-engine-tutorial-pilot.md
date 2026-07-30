# RBA Data Engine tutorial-v1 실제 라벨러 pilot 실행 계획

> 설계: [`2026-07-30-rba-data-engine-tutorial-pilot-design.md`](../specs/2026-07-30-rba-data-engine-tutorial-pilot-design.md)
> 상태: 실행 준비 / production 변경·provider 호출 미실행

## 0. 안전 경계

- `tutorial-v1` set/lesson/reference/prediction을 변경하지 않는다.
- production DB는 정해진 라벨링 웹 사용자 흐름 외 수동 쓰기하지 않는다.
- R2/media/dataset 삭제·수정, provider/VLM/Claude/Gate 호출은 0이다.
- pilot 답은 tutorial 전용 원장에만 기록한다.
- observer는 라벨러에게 정답을 말하거나 입력을 대신하지 않는다.

## 1. Read-only preflight

1. production deployment와 active tutorial version이 `tutorial-v1`인지 확인한다.
2. lesson 수/position이 정확히 5이고 media 5개가 재생 가능한지 확인한다.
3. 지정 라벨러가 active이고 현재 progress가 0/5인지 확인한다.
4. 일반 큐가 tutorial 미완료 상태에서 fail-closed인지 확인한다.
5. tutorial 5개가 production GT·blind 30 후보에서 제외되는 계약을 확인한다.

하나라도 다르면 쓰기를 시작하지 않고 exact blocker를 기록한다.

## 2. Pilot worksheet 동결

실행 전에 로컬 audit 문서에 다음 빈 필드를 만든다.

- pilot 식별자는 raw email 대신 내부 user ID의 짧은 fingerprint
- start/end KST·UTC, interruption 구간
- lesson별 enter/GT lock/review submit/feedback acknowledge 시각
- uncertain 사용 여부와 comparison `review` dimension 수
- 저장/media/이해 어려움/이어하기 이슈
- 첫 본작업 5개 ID fingerprint와 owner 재검수 필요 여부

worksheet에는 token, signed URL, raw prediction/reference, 개인정보를 넣지 않는다.

## 3. Tutorial 5개 실행

각 position 1..5에서 아래 순서를 반복한다.

1. lesson 진입 시각 기록
2. 라벨러가 영상과 입력 폼을 독립적으로 확인
3. Blind GT 제출 후 prediction이 처음 공개되는지 확인
4. VLM review 제출 후에만 reference/feedback이 공개되는지 확인
5. feedback acknowledge 뒤 다음 position만 열리는지 확인
6. stage timestamp와 observer 시각을 대조

오류가 나면 재시도 버튼을 무작정 누르지 않고 오류 코드·stage·position을 기록하고 중단한다.

## 4. 일반 큐와 첫 본작업 5개

1. 5/5 후 tutorial 완료 화면과 일반 큐 gate 해제를 확인한다.
2. 지정 날짜/큐에서 실제 작업 5개를 독립 제출한다.
3. owner는 제출 뒤에만 필수 필드, 의미, segment를 검수한다.
4. 교정이 필요한 clip 수와 이유만 기록하고 답을 pilot 도중 선행 제공하지 않는다.
5. 5개 뒤 추가 작업을 멈추고 범위 밖 데이터 생산을 방지한다.

## 5. 계산·보고

1. 총/lesson/GT/VLM 단계 시간을 계산한다.
2. uncertain 사용 lesson 수 / 5를 계산한다.
3. tutorial correction lesson 수 / 5를 계산한다.
4. 첫 본작업 owner 재검수 clip 수 / 5를 계산한다.
5. 정답 조기 노출, 원장 혼입, gate 우회, media/storage mutation이 모두 0인지 확인한다.
6. 결과 보고서를 additive 작성하되 5개로 agreement나 모델 품질을 주장하지 않는다.

## 6. 다음 gate

pilot 보고를 읽고 나서만 공통 blind 30 TEST-SHEET를 작성한다. sample 30, reviewer,
comparison, uncertain/adjudication, 수용 기준을 실행 전에 owner와 동결하며, blind 30 실행은
별도 작업이다.

## 검증 명령

코드 변경이 없는 준비 단계에서는 아래 정적 검증만 수행한다.

```bash
git diff --check
rg -n "production GT|tutorial-v1|blind 30|provider" \
  docs/superpowers/specs/2026-07-30-rba-data-engine-tutorial-pilot-design.md \
  docs/superpowers/plans/2026-07-30-rba-data-engine-tutorial-pilot.md
```
