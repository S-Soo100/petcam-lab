# RBA Data Engine 공통 튜토리얼 5개·라벨러 1명 pilot 설계

**상태:** 실행 준비 / production 쓰기 미실행
**작성일:** 2026-07-30
**상위 SOT:** [`feature-rba-data-engine-v1.md`](../../../specs/feature-rba-data-engine-v1.md)
**기존 구현 SOT:** [`labeling interactive tutorial`](2026-07-13-labeling-interactive-tutorial-design.md)

## 1. 결정

새 튜토리얼 시스템을 만들지 않는다. production에 활성화된 `tutorial-v1`의 고정 5개를
지정 라벨러 1명이 실제로 완료하고, 첫 본작업 5개까지 이어가며 운영 가능성과 측정값을
확인한다. 5개 tutorial은 교육·UI calibration이고 agreement 표본이 아니다.

## 2. 범위

### 포함

- 지정 라벨러 1명의 tutorial 0/5 -> 5/5
- 일반 큐 gate 해제와 첫 본작업 5개 진입 확인
- 시간, uncertain 사용, tutorial correction, 운영 재검수 측정
- 오류·문구 혼동·중단/복귀·media 재생 문제 기록
- 결과 보고 뒤 공통 blind 30 TEST-SHEET 작성

### 제외

- tutorial set/lesson/reference/prediction 수정
- tutorial 답안을 production GT나 학습 데이터로 export
- 라벨러 합격·탈락 자동 판정
- production DB/R2 media의 정리·삭제
- VLM/Claude/Gate/provider 신규 호출
- blind 30 실행 또는 수용 기준의 사후 결정

## 3. 데이터 격리 계약

1. tutorial 답은 `labeling_tutorial_progress`와 `labeling_tutorial_attempts`에만 남긴다.
2. `behavior_labels`, `clip_labeling_sessions`, motion blind GT 원장으로 복사하지 않는다.
3. 최초 GT 전에는 prediction/reference/peer 답을 노출하지 않는다.
4. tutorial clip은 train/validation/future holdout과 blind 30에서 제외한다.
5. reset이 필요하면 기존 attempt를 지우지 않고 `run_no + 1`로 보존한다.
6. pilot 관찰 때문에 R2 object나 DB row를 수동 보정하지 않는다. media 오류는 blocker로 기록한다.

## 4. 측정 계약

한 명 pilot이라 통계적 품질을 주장하지 않고, 아래 운영 지표만 기록한다.

| 지표 | 정의 | 근거 |
|---|---|---|
| tutorial 총 경과 | 시작 버튼 시각부터 5번째 feedback 확인까지 | observer 시계 + progress `started_at/completed_at` 대조 |
| lesson 작업 시간 | lesson 진입부터 feedback 확인까지, 5개 각각 | observer worksheet; DB stage timestamp는 교차검증 |
| GT 단계 시간 | lesson 진입부터 `gt_locked_at`까지 | observer worksheet |
| VLM 검수 시간 | `gt_locked_at`부터 `review_submitted_at`까지 | tutorial attempt timestamp |
| uncertain 사용률 | visibility=`uncertain`, confidence=`uncertain/unjudgeable`, target/object=`uncertain` 중 하나라도 쓴 lesson 수 / 5 | 최초 `submitted_gt` |
| tutorial correction 비율 | subjective를 제외한 comparison dimension이 `review`인 lesson 수 / 5 | 불변 `comparison` |
| 운영 재검수 비율 | 첫 본작업 5개 중 owner가 의미·구간·필수 필드 교정을 요구한 clip 수 / 5 | owner pilot worksheet |
| 흐름 오류 | 저장 실패, 정답 조기 노출, gate 우회, 이어하기 실패, media 실패 건수 | 화면 관찰 + 서버 오류 코드 |

브라우저의 탭 방치 시간을 실제 작업시간으로 오해하지 않도록 observer가 `active_start`,
`active_stop`, 중단 시간을 별도 기록한다. 현재 DB timestamp만으로 최초 영상 관찰 시간을
정확히 복원할 수 없으므로 pilot 한 명에서는 새 telemetry schema를 추가하지 않는다.

## 5. 성공·중단 기준

### pilot 완료

- 동일 라벨러가 5 lesson을 순서대로 완료
- 최초 GT 전 prediction/reference 누출 0
- tutorial 답의 production GT 유입 0
- 일반 큐 gate가 5/5 전 닫히고 5/5 뒤 열림
- 첫 본작업 5개 저장 가능
- 위 지표와 관찰 이슈가 누락 없이 보고됨

### 즉시 중단

- 정답·VLM·peer 답의 조기 노출
- tutorial 답이 production GT에 기록됨
- 다른 사용자의 attempt/clip 접근
- tutorial clip media 불일치 또는 잘못된 set/version
- 저장 오류를 우회하기 위한 DB 수동 수정이 필요함

중단은 pilot 실패로 기록하고 데이터나 attempt를 삭제하지 않는다.

## 6. blind 30으로 이어지는 계약

pilot 보고가 끝난 뒤 별도 TEST-SHEET에서 다음을 실행 전에 동결한다.

- tutorial 5개와 겹치지 않는 media-ready 30 clip의 exact ID/hash
- camera-night 누수와 near-duplicate 제거 규칙
- 최소 2명의 tutorial 완료 reviewer, 상호 답·VLM·Gate 완전 은닉
- visibility, primary action, observed-action set, target, segment 허용오차의 비교 함수
- uncertain/abstain 처리와 owner adjudication 순서
- agreement 지표와 수용/재교육 기준

pilot의 5개 comparison이나 owner reference 일치율을 blind 30 agreement로 재사용하지 않는다.
