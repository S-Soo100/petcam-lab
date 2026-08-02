# RBA 사건 경계 Development 분석 v1 설계

**상태:** Owner 사전 승인 / Claude 교차검수 완료 / Important 6·Minor 4 반영
**작성일:** 2026-08-02
**선행 연구:** [`사건 묶기 shadow v2`](2026-07-31-rba-event-grouping-shadow-v2-design.md) ·
[`사건 이어짐 자격검사 v2`](2026-08-01-rba-sequence-eligibility-review-design.md)

## 1. 한 줄 결론

두 사람이 독립 검수하고 Owner가 불일치를 모두 해결한 development 경계를 읽기 전용으로
검증·점수화해, clip을 실제 사건 단위로 묶을 수 있는지와 local VLM baseline으로 넘어갈 수
있는지를 판정한다.

이번 단계는 local VLM을 실행하지 않는다. 먼저 사람 경계가 완전하고 일관된지, 최종 경계로
결정론적인 사건 묶음을 만들 수 있는지를 증명한다.

## 2. 연구 목표

1. 최신 유효 development cohort의 사람 검수 원장이 완전한지 확인한다.
2. 두 reviewer의 최초 일치율, 불확실률, Owner 개입률과 방향 편향을 측정한다.
3. 합의된 답과 Owner 최종답을 하나의 final boundary GT로 결정론적으로 합친다.
4. `same_event` 경계를 연결하고 `different_event` 경계에서 끊어 사건 묶음을 만든다.
5. metadata-only gap threshold 후보가 over-merge 없이 사건 수를 줄일 수 있는지 측정한다.
6. 다음 단계인 frozen local VLM baseline의 입력 단위로 사용할 수 있는지 판정한다.

## 3. 연구 질문

- 두 사람은 같은 인접 경계를 독립적으로 봤을 때 얼마나 자주 같은 답을 내는가?
- 의견이 갈린 경계는 어떤 gap bin과 camera-night에 집중되는가?
- Owner 최종답 이후에도 `uncertain`이 남는가?
- final boundary GT로 모든 clip을 누락·중복 없이 선형 사건으로 묶을 수 있는가?
- 단순 gap threshold가 `different_event`를 잘못 합치는 over-merge 없이 얼마나 많은 분할을
  줄일 수 있는가?
- 사건당 한 번 분석한다고 가정할 때 clip별 분석 대비 호출 분모가 얼마나 줄어드는가?

## 4. 비교한 접근과 선택

| 접근 | 장점 | 한계 | 판정 |
|---|---|---|---|
| 합의율 집계만 | 가장 빠르고 구현이 작다 | 사건 묶음과 VLM 분모가 나오지 않는다 | 기각 |
| 결정론적 scorer + private manifest + public report | 사람 품질, 사건 단위, 비용 분모를 한 번에 검증한다 | 무결성 검사가 더 필요하다 | **채택** |
| local VLM 즉시 실행 | 모델 결과를 빨리 볼 수 있다 | 검증되지 않은 사건 단위 위에서 평가해 연구 순서가 뒤집힌다 | 기각 |

## 5. 연구 단계

### Stage 0. SOT와 실행 경계 고정

- scorer 실행 전에 별도 TEST-SHEET에 가설·지표·합격 숫자·decision rule을 동결한다.
- 실행 대상은 “최신”으로 다시 찾지 않는다. 승인된 cohort의 `experiment_id`와
  `manifest_digest`를 구현 계획과 private artifact에 pin하고, production 값이 다르면
  `BLOCKED_COHORT_PROVENANCE`로 중단한다.
- 이번 실행 pin은 `experiment_id=rba-event-sequence-review-v2`,
  `manifest_digest=edd3f2c230adacb70c0b8bc70072eb632eb0ac48718bdd1ffbeca88649e9dfca`다.
- historical holdout은 열거나 읽지 않는다.
- 행동 GT, Python Evidence, Gate, VLM 결과는 입력으로 읽지 않는다.
- production DB는 SELECT만 허용하고 RPC·INSERT·UPDATE·DELETE는 0이다.
- R2, frame decode, model, service 호출은 0이다.
- 공개 집계 전에 실행 salt를 최초 1회 private `0600` 파일로 만들고, 이후 익명 label과
  3회 rerun이 모두 같은 salt를 재사용한다.

### Stage 1. 사람 원장 무결성 감사

다음을 모두 만족해야 scoring을 시작한다.

- 유효 development pair 수와 두 reviewer assignment가 정확히 대응한다.
- 모든 assignment에 submission이 정확히 하나 있다.
- reviewer는 서로 다른 두 사람이고 pair별 역할이 중복되지 않는다.
- 최초 답이 다르거나 어느 한쪽이 `uncertain`인 pair에는 resolution이 정확히 하나 있다.
- 합의된 non-uncertain pair에는 불필요한 resolution이 없다.
- 미해결 conflict는 0이다.
- pair가 같은 run 안에서 선형 인접성을 유지한다.
- run 정체성은 digest를 검증한 seed manifest를 SOT로 쓴다. 자격검사 무효 clip/경계로
  원래 run에 구멍이 생긴 경우 각 sub-segment를 독립 선형 체인으로 검사한다.
- 사전 관측 기대값은 cohort pair row `120`, 자격검사 뒤 배정된 유효 pair `74`,
  assignment·submission `148`, resolution `26`이다. 하나라도 다르면
  `BLOCKED_GT_INTEGRITY:COUNT_DRIFT`로 scorer를 실행하지 않고 원장 drift를 보고한다.

하나라도 어기면 `BLOCKED_GT_INTEGRITY`로 중단한다. 누락 답을 추정하거나 자동 보완하지 않는다.

### Stage 2. 사람 측정 품질 계산

공개 보고서에는 aggregate만 남긴다.

- raw agreement, Cohen's kappa와 3×3 decision confusion matrix
- reviewer별 `same_event / different_event / uncertain` 비율
- uncertain 포함률과 Owner adjudication률
- Owner 최종답이 최초 어느 방향을 채택했는지의 익명 집계
- gap bin·camera-night별 sample 수, agreement와 final class count
- Owner 최종답이 Owner 자신의 최초답과 같은 비율

agreement와 uncertain 수준은 이번 final GT의 채택 gate로 쓰지 않는다. 모든 불일치·uncertain을
Owner가 최종 해결하는 측정 설계를 이미 선택했기 때문이다. 대신 낮은 agreement는 taxonomy와
경계 정의의 한계로 공개 보고서에 반드시 적고, 다음 자동화 utility를 보수적으로 해석한다.

reviewer identity, pair ID, clip ID, 이유 원문은 공개 보고서에 쓰지 않는다. camera-night도 실제
camera 이름과 날짜 대신 실행 salt로 만든 익명 label만 사용한다.

### Stage 3. Final boundary GT와 사건 묶음 생성

- 두 최초 답이 같고 non-uncertain이면 그 답을 final로 쓴다.
- 그 외에는 Owner resolution만 final로 쓴다.
- final `uncertain`이 하나라도 남으면 사건 묶음 채택은 `HOLD_UNRESOLVED_BOUNDARY`다.
- `same_event`는 같은 run의 다음 clip과 연결한다.
- `different_event`는 사건을 끊는다.
- 모든 source clip은 정확히 한 사건에만 속해야 한다.
- 서로 다른 camera, activity day, run을 가로지르는 연결은 0이어야 한다.

private artifact에는 salted pair/event digest와 ordinal만 저장하며 raw 식별자는 공개하지 않는다.
Stage 0에서 만든 salt를 모든 rerun이 재사용한다.
3회 rerun hash는 salt 고정 상태에서 비교한다. 파일 mode는 directory `0700`, artifact `0600`,
no-overwrite다.

### Stage 4. Gap threshold와 utility 평가

기존 development 후보 `0, 5, 15, 30, 60, 120초`를 그대로 비교한다.

- `different_event`를 `same_event`로 합친 over-merge가 0인 threshold만 후보로 둔다.
- 후보 중 over-split이 가장 작은 threshold를 고르고 동률이면 더 작은 값을 택한다.
- 사람 final 사건 수와 threshold 사건 수를 각각 계산한다.
- `source_clip_count`는 final boundary GT에 참여한 unique clip 수이며 자격검사에서 무효가 된
  clip은 제외한다.
- event reduction은 `1 - final_event_count / source_clip_count`로 계산한다.
- local VLM 잠재 호출 감소율은 사건당 1회 가정의 분모 변화로만 보고하며 실제 비용 절감으로
  과장하지 않는다.

이 표본은 자격검사 뒤 남은 development 표본이므로 production 자연분포의 정확한 발생률로
일반화하지 않는다.

### Stage 5. 진입 판정

다음이 모두 참이면 `DEVELOPMENT_EVENT_GT_READY_FOR_LOCAL_VLM_BASELINE`이다.

- GT integrity 위반 0
- unresolved final boundary 0
- accounting 누락·중복 0
- cross-camera/day/run merge 0
- scorer 3회 rerun hash 동일
- 공개 보고서에 raw ID·원문 이유·비밀값 0

event reduction이 작거나 zero-overmerge threshold가 0초뿐이어도 GT 자체가 무효가 되는 것은
아니다. 이 경우 `EVENT_GT_READY_ROUTER_UTILITY_HOLD`로 분리해, 사람 사건 단위는 보존하되
metadata-only 자동 묶기 효용은 보류한다.

## 6. 기대효과

### 즉시 효과

- “두 영상을 같은 사건으로 볼 수 있는가”를 사람 품질 지표로 수치화한다.
- 지금까지의 clip 중심 데이터를 실제 사건 단위로 재구성할 수 있는지 확인한다.
- 어느 시간 간격에서 사람이 자주 갈리는지 파악한다.
- Owner가 개입해야 하는 비율을 알아 다음 검수 비용을 추정한다.

### 다음 연구 효과

- local VLM이 clip이 아니라 사건마다 한 번 분석할 수 있는 입력 단위를 얻는다.
- Python Evidence를 사건 안의 시계열로 합칠 기준을 얻는다.
- 사건당 local VLM 전수 분석과 어려운 사건의 cloud/SegmentVLM 승격을 분리할 수 있다.
- clip별 호출 대비 가능한 호출 감소율의 상한이 아니라 실제 분모를 얻는다.

### 보장하지 않는 것

- local VLM 행동 정확도, 모델 가중치 적합성, 실제 비용 절감
- future camera/morph/enclosure 일반화
- production 자동 병합, 자동 skip, 앱 사건 카드
- historical holdout이나 future holdout 통과

## 7. 산출물

1. scorer와 단위 테스트
2. Mac mini private event manifest와 metrics artifact (`0700/0600`, no-overwrite)
3. 공개 aggregate report
4. 연구 verdict와 다음 local VLM baseline 진입 조건
5. `specs/next-session.md`와 관련 TEST-SHEET의 현재 상태 갱신

## 8. 진행 체크리스트

### 설계·검수

- [x] 본 설계 self-review: placeholder·모순·범위 누락 0
- [x] iTerm2 공식 AppleScript로 Claude 교차검수
- [x] Claude Important 6·Minor 4를 SOT·코드와 대조해 전부 채택
- [x] 구현 계획과 exact command 작성

### 구현·테스트

- [x] TEST-SHEET에 가설·지표·합격 숫자·decision rule 선동결
- [x] synthetic RED: missing/duplicate submission, 불필요/누락 resolution 차단
- [x] synthetic RED: final uncertain, broken adjacency, cross-run merge 차단
- [x] aggregate metrics와 event grouping GREEN
- [x] 입력 순서 변경과 3회 rerun hash 결정론 검증
- [x] public report redaction 검사
- [x] focused test와 전체 Python test 통과

### Mac mini 실행

- [x] handoff manifest `HANDOFF_OK`
- [x] exact repo/commit/host 확인
- [x] pinned `experiment_id`·`manifest_digest` 일치 확인
- [x] production SELECT-only preflight
- [x] pair row `120` / 유효·배정 pair `74` / assignment·submission `148` /
  resolution `26` completeness 확인
- [x] private directory `0700`, artifact `0600`, no-overwrite
- [x] 최초 salt를 private `0600` artifact에 저장하고 3회 rerun에서 재사용
- [x] DB write/RPC/R2/model/service mutation 0
- [x] SELECT용 service key는 기존 `0600` env에서만 읽고 stdout/stderr에 출력하지 않음
- [x] aggregate report에 raw ID·원문 GT·secret 0

### 종료 판정

- [x] final event count와 event reduction 계산
- [x] reviewer agreement·uncertain·Owner intervention 보고
- [x] threshold별 over-merge/over-split 표 작성
- [x] verdict 확정
- [x] local VLM baseline은 별도 계획 전 실행하지 않음

## 9. 명시적 범위 밖

- historical holdout 개방
- local/cloud VLM, SegmentVLM, Gate, Python frame 분석 실행
- production event table 또는 worker 추가
- 기존 사람 답·resolution 수정
- 자동 skip, 영상 삭제·병합, 앱 노출 변경
