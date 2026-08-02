# RBA 사건 경계 Development 분석 v1 TEST-SHEET

**상태:** `FROZEN_BEFORE_SCORING`

**동결일:** 2026-08-02
**질문:** 완료된 사람 경계로 누락·중복 없는 사건 GT(사람이 확정한 정답)를 만들 수 있는가?

## 연구 목표

1. 두 검수자의 판단과 Owner 최종 결정을 이용해 74개 유효 경계를 하나의 결정론적 GT로 확정한다.
2. 확정 경계를 따라 여러 영상을 사건 단위로 묶고, 같은 입력에서 항상 같은 결과가 나오는지 확인한다.
3. 단순 시간 간격 규칙이 사람 경계를 얼마나 안전하게 흉내 내는지 측정해 local VLM baseline 진입 여부를 판정한다.

## Pinned input

- `experiment_id`: `rba-event-sequence-review-v2`
- `manifest_digest`: `edd3f2c230adacb70c0b8bc70072eb632eb0ac48718bdd1ffbeca88649e9dfca`
- 전체 pair row / 유효 pair / assignment / submission / resolution: `120/74/148/148/26`
- source artifact: `/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-event-media-eligibility-v1-20260731T124018Z/boundary-pairs.json`

## 연구 단계

1. 입력 provenance·개수·배정·제출·해결 집합을 fail-closed로 검사한다.
2. 두 사람의 raw agreement, Cohen's kappa, 3×3 confusion matrix, uncertain 비율을 기술 통계로 계산한다.
3. 합의 경계는 합의값으로, 불일치·uncertain 경계는 Owner resolution으로 최종 GT를 만든다.
4. 유효한 연속 run 안에서 최종 `same_event` 경계를 연결해 사건 그룹을 만든다.
5. gap 후보 `(0, 5, 15, 30, 60, 120)`초를 사람 GT와 비교한다.
6. 같은 salt와 입력으로 순서를 바꿔 세 번 계산하고 private hash·public report hash가 모두 같은지 확인한다.

## GT verdict

- count/provenance/assignment/submission/resolution/adjacency 위반: `BLOCKED_GT_INTEGRITY`
- 최종 `uncertain`이 1개 이상: `HOLD_UNRESOLVED_BOUNDARY`
- 위반 0 + 최종 uncertain 0 + 3회 hash 동일: `DEVELOPMENT_EVENT_GT_READY_FOR_LOCAL_VLM_BASELINE`

agreement와 kappa는 descriptive(현재 사람 판단 특성을 설명하는 수치)이며 GT 채택 gate가 아니다. 두 사람이 많이 달라도 모든 경계가 Owner로 해결되고 무결성이 맞으면 development GT는 만들 수 있다.

## Utility verdict

- 사람 최종 사건 수 감소율이 `0.15` 이상이고 `0초보다 큰` zero-overmerge threshold가 존재: `PASS`
- 그 외: `EVENT_GT_READY_ROUTER_UTILITY_HOLD`

### 점수 계산 전 정정 — 2026-08-02 Claude 구현 검수

최초 문구의 “threshold가 존재”는 `0초`도 실용 자동 묶기 기준처럼 해석될 여지가 있었어. 설계 §5와 맞추기 위해 실제 점수를 보기 전에 `0초보다 큰 threshold`로 명확히 고쳤다. `0초`만 안전하면 사람 사건 GT는 유지하지만 metadata-only router utility는 보류한다.

감사 재실행은 최초 private `run-salt.bin`을 `--salt-file`로 지정하고, 그 파일이 `0600`·32 bytes인지 검사한 뒤 새 no-overwrite 출력 디렉터리에 같은 salt를 복제해 사용한다.

최종 경계에 `uncertain`이 하나라도 남아 GT가 `HOLD_UNRESOLVED_BOUNDARY`이면, 채택할 사건 GT가 없으므로 gap threshold 조건을 만족하더라도 router utility는 `EVENT_GT_READY_ROUTER_UTILITY_HOLD`로 함께 보류한다.

### 첫 one-shot fail-closed 후 provenance 정정 — 2026-08-02

첫 실행은 DB `gap_sec`와 동결 manifest의 exact float 비교에서 중단됐다. 식별자 없는 읽기 전용 진단 결과 74개 중 23개가 달랐지만 최대 절대차는 `3.979039320256561e-13`초였고, ordinal·gap bin 불일치는 각각 0개였다. 이는 표본 변경이 아니라 float DB roundtrip 표현 차이다. 재실행 전에 `abs_tol=1e-9`, `rel_tol=0`으로 고정하며, `1e-6`초 차이는 계속 `PAIR_PROVENANCE:gap`으로 차단하는 테스트를 함께 둔다. 실패 실행의 `0600` salt는 삭제하지 않고 `--salt-file`로 재사용한다.

threshold 선택 규칙은 사람 GT의 `different_event`를 하나라도 잘못 합치는 후보를 먼저 제외하고, 남은 후보 중 `same_event`를 가장 적게 놓치는 값을 고른다. 동률이면 더 낮은 threshold를 고른다.

## 기대효과

- 클립 수와 사건 수를 구분해 사용자가 실제 활동을 더 자연스럽게 보게 할 기반이 생긴다.
- local VLM이 모든 클립이 아니라 사건 단위로 설명할 수 있는지 다음 시험의 정확한 입력이 생긴다.
- 단순 gap 규칙의 안전 한계를 숫자로 알 수 있어 과도한 자동 병합을 막는다.
- Owner 개입량과 두 검수자의 불확실성을 측정해 다음 라벨링 비용을 예측할 수 있다.

## 진행 체크리스트

- [ ] pinned experiment/digest가 정확히 일치한다.
- [ ] `120/74/148/148/26` 개수가 정확히 일치한다.
- [ ] 유효 pair마다 서로 다른 두 reviewer의 assignment와 submission이 정확히 하나씩 있다.
- [ ] 불일치 또는 uncertain pair만 resolution을 갖고, 필요한 resolution이 빠지지 않는다.
- [ ] manifest 안의 유효 경계만 사용하고 끊긴 경계는 별도 subsegment로 나눈다.
- [ ] 최종 uncertain이 0인지 확인한다.
- [ ] 세 번의 private/public hash가 각각 동일하다.
- [ ] public report에 UUID, reviewer identity, 원문 reason, camera/date, secret이 없다.
- [ ] private output 디렉터리/파일 권한이 `0700/0600`이고 덮어쓰지 않는다.
- [ ] production DB 호출은 SELECT뿐이고 RPC/INSERT/UPDATE/DELETE는 0이다.
- [ ] R2, frame 추출, Python Evidence, Gate, VLM, service 호출은 0이다.

## 범위 밖

- historical holdout 공개·재사용
- local/cloud VLM, SegmentVLM, Gate 실행
- production event schema·GT·DB·R2·service 변경
- 자동 skip 또는 행동 라벨 자동 확정
