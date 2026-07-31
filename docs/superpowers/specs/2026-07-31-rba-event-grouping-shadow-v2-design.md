# RBA 사건 묶기 shadow v2 설계

**상태:** owner 방향·gap 계약 승인 / 구현 전  
**작성일:** 2026-07-31  
**선행 이력:** [`shadow v1 TEST-SHEET`](../../../experiments/rba-event-grouping-shadow-v1/TEST-SHEET.md) ·
[`shadow v1 보고서`](../../../experiments/rba-event-grouping-shadow-v1/REPORT-TEMPLATE.md) ·
[`사건 단위 전수 분석 방향`](2026-07-31-rba-event-first-total-coverage-design.md)

## 1. 결론

기존 `motion_clips` 약 2만 건은 부족하지 않다. shadow v1이 모든
`motion_clip_review_slots`를 사람 노출로 간주해 `18,917`개를 차단했고, 실제 캡처 분포에 거의
없는 `gap <= 15s` pair를 exact 40개 요구한 것이 blocker의 원인이다.

v2는 새 영상을 기다리지 않는다. 같은 historical cutoff에서 **slot 배정과 실제 사람 노출을
분리**하고, 사람 GT를 보기 전에 실측 metadata 분포에 맞춘 gap bin을 동결한다. v1 verdict
`BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS`와 artifact 부재는 감사 이력으로 보존한다.

## 2. 확인된 production inventory

2026-07-31 Mac mini에서 production DB를 SELECT-only로 재계산했다. raw clip/camera/reviewer ID,
GT, R2 key는 출력·저장하지 않았다.

| 항목 | v1 all-slot block | v2 strict actual exposure |
|---|---:|---:|
| closed source | 19,279 | 19,279 |
| blocked research | 18,917 | 551 |
| diagnostic integrity | 101 | 1,594 |
| activity candidate | 261 | 17,134 |
| adjacent pair | 209 | 16,211 |
| pair camera-night | 5 | 54 |
| camera | 2 | 3 |

v2 protected union `551`의 source-intersection은 blind submission `243`, labeling session `217`,
canary/formal slot `42`, tutorial `3`, live terminal consensus `132`, frozen manifest `58`이다. 서로
겹치는 clip이 있으므로 사유별 합계와 union은 다르다.

## 3. Exposure 계약

### 3.1 차단하는 것

다음 중 하나에 닿은 clip은 `blocked_research`로 accounting하고 사건·boundary pair 입력에서
제외한다.

- `motion_clip_blind_submissions`의 실제 제출
- `motion_clip_labeling_sessions`의 사람 라벨링 세션
- `cohort_kind='canary'` slot. `b30v1:*`, `b30v2:*` formal cohort를 포함한다
- `labeling_tutorial_lessons`
- live consensus가 `agreed`, `conflict`, `owner_resolved`인 clip
- 기존 canary/formal/tutorial/frozen holdout manifest의 clip

### 3.2 차단하지 않는 것

제출·terminal consensus가 없는 일반 live slot은 **배정 자리일 뿐 사람 노출 증거가 아니므로**
차단하지 않는다. 다른 행동 연구의 AI/VLM/Gate/Python Evidence 결과도 boundary 선택과 label에
사용하지 않는다.

system exclusion의 활성 상태와 유효하지 않은 duration은 v1과 같이
`diagnostic_integrity`로 accounting하고 사건 연속성을 끊는다. blocked가 아니라고 해서
diagnostic을 activity로 승격하지 않는다.

## 4. Gap 계약

`gap_sec`는 파일 길이가 아니라 앞 clip 종료와 다음 clip 시작 사이의 미촬영 시간이다.

```text
gap_sec = next.started_at - (current.started_at + current.duration_sec)
```

v2 bin은 다음 exact 경계로 동결한다.

| bin | 경계 | production pair | camera-night | camera |
|---|---|---:|---:|---:|
| short | `gap <= 30s` | 10,094 | 47 | 3 |
| medium | `30s < gap <= 60s` | 3,804 | 51 | 3 |
| long | `60s < gap <= 300s` | 2,313 | 54 | 3 |

이 경계는 사람 GT·행동 label·모델 결과를 보지 않고 metadata 분포와 캡처 cadence만으로 정했다.
실측 gap 중앙값은 `29.4s`, p90은 `81.4s`다. v1의 `<=15s` bin은 1 pair뿐이라 폐기한다.

## 5. Exact 120 선택

v1의 품질 계약은 유지한다.

- exact 12 camera-nights: development 6, historical holdout 6
- split은 camera-night 단위 완전 분리, 각 split 최소 2 cameras
- split별 short/medium/long 각 20, 합계 60
- 전체 120 pair, unique clip 240, clip reuse 0
- split별 한 camera 최대 36/60
- split·bin별 한 camera 최대 14/20
- source cutoff는 `2026-07-31T03:44:27.183403+09:00`
- KST 07:00 기준 닫힌 activity day만 사용

현재 단일 greedy selector는 feasible inventory에서도 실패한다. v2는 다음 bounded deterministic
search를 사용한다.

1. attempt `0..1999`마다 `seed + attempt + camera-night` SHA-256 순서로 night를 정렬한다.
2. dev/holdout 각 6박, 최소 2 cameras, 세 bin 존재를 만족하는 disjoint partition만 남긴다.
3. 각 partition에서 bin 순서 6개 순열을 모두 시도하고 stable pair hash 순서로 clip reuse와 camera
   cap을 검사한다.
4. feasible witness 중 canonical manifest hash가 가장 작은 하나를 선택한다.
5. 2,000 partitions를 모두 소진하면 데이터 부족으로 뭉개지 않고
   `BLOCKED_SELECTOR_SEARCH_EXHAUSTED`로 별도 보고한다.

read-only preflight에서 7번째 stable partition이 exact 12박·120쌍·unique clip 240·camera cap
36/14를 모두 만족했다. 따라서 현재 inventory는 계약상 feasible하다.

## 6. Human GT와 판정

pair label과 scoring은 v1을 유지한다.

- 두 non-owner reviewer가 `same_event / different_event / uncertain`을 독립 판정한다.
- development 60을 먼저 완료하고 불일치·uncertain만 owner가 adjudicate한다.
- threshold를 동결한 뒤에만 historical holdout 60 파일을 연다.
- holdout over-merge는 전체·camera별 0이어야 한다.
- over-split, reviewer agreement, uncertain, event reduction, camera별 지표를 그대로 측정한다.
- activity candidate clip 대비 event 수가 최소 15% 감소해야 utility를 통과한다.

historical holdout은 **사건 묶기 내부 타당성**만 인증한다. production 일반화와 앱 노출은 알고리즘
동결 뒤 별도 future holdout을 통과해야 한다. 다만 future holdout은 v2 사람 GT 시작을 막지 않는다.

## 7. 기대효과

### 즉시 효과

- 새 영상 수집 없이 activity candidate `17,134`, pair `16,211`, 54 camera-nights를 연구에 사용한다.
- exact 120 boundary worksheet를 생성해 사람 검수를 바로 시작할 수 있다.
- slot 예약을 노출로 오인해 생기던 대규모 false block을 제거한다.
- feasible data를 단일 greedy 경로가 막던 false blocker를 제거한다.

### 검증 후 제품 효과

- over-merge 0을 유지하며 연속 clip을 논리적 사건으로 묶는다.
- 원본 clip은 전부 보존·열람 가능하고, 사용자는 중복 카드 대신 사건 타임라인을 본다.
- event reduction이 15%라면 사건당 1회 분석 기준 local VLM 기본 호출 수도 최소 15% 줄일 수
  있는 근거가 생긴다. 실제 chunk 수·latency·비용은 Phase 2 TEST-SHEET에서 별도 측정한다.
- Python Evidence를 clip별 숫자에서 사건별 시계열·요약으로 합칠 안정적인 단위를 얻는다.
- 어려운 사건만 cloud VLM/SegmentVLM/HITL로 올리는 다음 단계의 분모가 생긴다.

### 이 단계가 보장하지 않는 것

- local/cloud VLM 행동 정확도와 비용 절감의 실제 크기
- Blind30 v2 reviewer agreement, Gate v3 품질, care signal 정확도
- production worker, DB event schema, 앱 사건 카드
- future camera/morph/environment 일반화

## 8. 안전 경계

- production DB는 SELECT만 허용하며 RPC/mutation은 0이다.
- R2 GET/HEAD, frame 추출, Python Evidence, Gate, local/cloud model 호출은 0이다.
- v1 artifact·verdict·cutoff를 수정하지 않는다.
- raw UUID, reviewer identity, GT 원문은 private mode `0600` artifact 밖으로 내보내지 않는다.
- 자동 skip, 원본 삭제·병합, visibility 변경, production service 변경은 금지한다.
- 새 TEST-SHEET 동결과 TDD 구현·검증 전 production prepare를 실행하지 않는다.

## 9. 완료 조건

1. v2 TEST-SHEET가 exposure, gap, bounded search, historical holdout 한계를 동결한다.
2. regression test가 slot-only 허용과 실제 submission/formal 차단을 RED→GREEN으로 증명한다.
3. synthetic greedy false blocker가 bounded search에서 exact witness를 찾는다.
4. Mac mini SELECT-only prepare가 exact 12박·120쌍 private artifact를 한 번 생성한다.
5. 독립 aggregate audit가 60/60, 20×3/bin, clip reuse 0, cap, hash, mode를 확인한다.
6. 두 reviewer에게 development worksheet를 전달할 준비가 되면
   `READY_FOR_HUMAN_BOUNDARY_GT_V2`로 보고한다.
