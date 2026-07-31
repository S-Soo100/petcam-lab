# Motion Blind Live v2 Highlight-Soft Design

**상태:** Owner 설계 승인 / 구현 전 동결
**승인일:** 2026-07-31
**적용 경계:** `2026-08-01` activity-day부터 새로 생성되는 `live` slot
**비교기:** `motion-blind-live-v2-highlight-soft`

## 1. 문제와 근거

현재 `motion-blind-v1`은 두 라벨러가 모두 `label`을 제출하면 다음 11개 GT 필드 중 하나만
달라도 clip 전체를 `conflict`로 보낸다.

- `visibility`
- `primary_action`
- `observed_actions`
- `segments`
- `target`
- `human_confidence`
- `context_tags`
- `activity_intensity`
- `highlight_recommendation`
- `enrichment_object`
- `interaction_types`

자유 메모, `hold`/`exclude` 사유, set 순서는 이미 비교에서 완화하고 segment 경계는 500ms까지
허용한다. 하지만 `highlight_recommendation`은 고객에게 보여줄 장면인지에 대한 주관적 제품 판단이라
행동 GT가 같은 두 답을 owner 검수로 보내는 비용이 행동 데이터 품질 향상으로 이어지지 않는다.

Mac mini가 2026-07-31 12:13 KST production immutable paired submission 95개를 SELECT-only로
재계산한 결과는 다음과 같다.

| 규칙 | agreed | conflict | v1 대비 감소 |
|---|---:|---:|---:|
| 현행 v1 | 26 | 69 | - |
| highlight-only nonblocking | 35 | 60 | 9건, 13.0% |
| soft 4필드 전체 nonblocking | 39 | 56 | 13건, 18.8% |

highlight 하나만 완화해도 9건을 줄이고, `human_confidence`·`context_tags`까지 풀어 얻는 추가 효과는
4건뿐이다. segment 허용치를 1초 또는 2초로 늘려도 추가 감소는 0건이었다. 따라서 첫 변경은
highlight 하나로 제한한다.

## 2. 결정

1. 기존 `motion-blind-v1` 비교 동작과 formal Blind30 v1/v2 계약을 변경하지 않는다.
2. formal/canary, 기존 live slot, 기존 submission, 기존 consensus, 기존 draft는 v1을 유지한다.
3. `2026-08-01` activity-day부터 **새로 생성되는 live slot**만
   `motion-blind-live-v2-highlight-soft`를 snapshot한다.
4. v2는 v1 비교 결과가 `highlight_recommendation` 단독 차이일 때만 `agreed`로 바꾼다.
5. 이때 최종 GT의 `highlight_recommendation`은 어느 라벨러 답도 임의 채택하지 않고
   `uncertain`으로 병합한다.
6. 두 immutable submission 원문은 그대로 보존한다.
7. 합의 row와 감사 event에는 `differing_fields=['highlight_recommendation']`와 v2 comparator
   version을 기록한다.
8. highlight 외 필드가 하나라도 다르면 v1과 같은 `conflict`다.
9. `interaction_types`와 segment 500ms 허용치는 바꾸지 않는다.
10. 과거 conflict를 재판정하거나 기존 row를 UPDATE/DELETE하지 않는다.

## 3. 채택하지 않은 안

### soft 4필드 전체 완화

`highlight_recommendation`, `human_confidence`, `context_tags`, legacy `activity_intensity`를 모두
nonblocking으로 두는 안이다. conflict 감소는 13건이지만 highlight-only보다 4건만 더 줄고,
환경·사람 등장·영상 품질과 확신도 신호를 잃을 수 있어 채택하지 않는다.

### wheel 세부 행동 또는 segment 시간 완화

`ride`/`rotate`/`push`를 soft 처리하거나 segment 허용치를 1~2초로 늘리는 안이다.
wheel interaction conflict는 12건이지만 enrichment 연구의 의미 정보이고, 실제 재계산에서 시간
허용치 확대의 추가 감소는 0건이었다. 둘 다 core conflict로 유지한다.

### v1 직접 수정

코드는 단순하지만 formal Blind30 v2 TEST-SHEET가 `motion-blind-v1` 불변을 요구한다.
기존 cohort와 live 데이터의 provenance도 바뀌므로 금지한다.

## 4. 사용자 체험

### 라벨러

`[화면]` 기존과 같은 행동·쳇바퀴·하이라이트 질문을 본다
→ `[조작]` 두 라벨러가 상대 답을 보지 않고 각각 제출한다
→ `[반응]` 핵심 행동이 같고 highlight만 다르면 “두 사람의 검수가 일치했어”로 종료된다
→ `[감정]` 세부 제품 취향 차이 때문에 작업이 잘못됐다는 느낌을 받지 않는다.

핵심 행동, 쳇바퀴 상호작용 종류, 대상, 구간이 다르면 기존처럼 owner 확인으로 보낸다.

### Owner

`[화면]` 운영 현황에서 core conflict만 불일치 수로 본다
→ `[조작]` 실제 행동·대상·시간이 다른 clip을 우선 검수한다
→ `[반응]` highlight-only 차이는 합의 이력에서 `uncertain` 병합과 원본 두 제출로 감사할 수 있다
→ `[감정]` 행동 GT 품질에 영향 없는 반복 검수가 줄어든다.

## 5. 버전 소유권

### 순수 비교기

- v1: `web/src/lib/motionBlindReview.ts`
- v2: `web/src/lib/motionBlindReviewV2.ts`
- dispatcher는 slot에서 읽은 version만 신뢰한다. request body의 version은 받지 않는다.
- v2는 v1 결과를 먼저 계산하고 highlight-only conflict만 좁게 변환한다.

### Slot snapshot

`motion_clip_review_slots.comparator_version`을 immutable snapshot으로 추가한다.

- 기존 row: `motion-blind-v1`
- canary/formal: 항상 `motion-blind-v1`
- live + activity day `< 2026-08-01`: `motion-blind-v1`
- live + activity day `>= 2026-08-01`: `motion-blind-live-v2-highlight-soft`

INSERT trigger가 위 규칙으로 값을 정하고, UPDATE로 바꾸는 시도는 `0A000`으로 차단한다.
slot materializer를 재실행해 과거 날짜 row를 늦게 만들더라도 날짜 경계가 같으므로 v1/v2가 섞이지
않는다.

### Finalize guard

기존 finalize RPC는 두 알려진 version을 받을 수 있게 forward 확장한다. 별도 DB trigger가
finalize 전이를 검증한다.

- 같은 clip의 두 slot이 정확히 두 개이고 version이 같아야 한다.
- consensus comparator version이 slot snapshot과 같아야 한다.
- canary는 v1 외 version을 거부한다.
- live v2는 activation activity-day 이전이면 거부한다.
- unknown/mixed/missing version은 fail-closed한다.

따라서 v2 slot이 생긴 뒤 오래된 v1 Web이 잘못 finalize하려 해도 submission은 보존되고 consensus는
`awaiting`에 남는다. 잘못된 v1 합의로 조용히 확정되지 않는다.

## 6. Web 데이터 흐름

1. 상세·제출 배정 조회가 본인 slot의 `comparator_version`을 allowlist 응답에 포함한다.
2. 상세 화면은 그 version으로 draft key/envelope를 만든다.
3. 기존 v1 draft는 v2 slot에서 복원되지 않고, 다른 user/clip/cohort draft도 계속 격리된다.
4. 제출 API는 인증된 slot에서 얻은 version으로 comparator를 선택한다.
5. 두 번째 제출이 오면 같은 version으로 비교하고 finalize한다.
6. 상대 답, digest, reviewer UUID, R2 key는 브라우저에 노출하지 않는다.

## 7. 배포와 복구

배포 순서는 migration → Web production → read-only smoke다. activation 전인 2026-07-31에 완료한다.

1. migration 후 기존 slot 전량 v1, canary/formal v1, unknown version 0을 확인한다.
2. Web 배포 후 기존 v1 live/canary 회귀를 확인한다.
3. 2026-08-01 activity-day 첫 live slot의 v2 snapshot을 확인한다.
4. v2 synthetic/disposable probe에서 highlight-only agreed+uncertain과 core conflict를 확인한다.

activation 전에는 Web을 이전 버전으로 되돌릴 수 있다. v2 slot 생성 후에는 v1-only Web으로
rollback하지 않고 future v2 생성을 forward-disable한 뒤 forward fix한다. production row
UPDATE/DELETE와 기존 consensus 재계산은 복구 수단으로 사용하지 않는다.

## 8. 검증 계약

- v1 comparator 회귀 전부 통과
- v2 highlight-only → agreed, final highlight `uncertain`
- highlight+core 차이 → conflict
- wheel interaction 차이 → conflict
- segment 500ms 일치, 501ms conflict
- 기존/canary slot v1, activation 이후 새 live slot v2
- mixed/unknown/canary-v2 finalize 차단
- 기존 slot/submission/consensus/event 지문 불변
- 상대 원문·secret·R2 key·reviewer UUID 응답 노출 0
- production 첫 v2 pair 전에 v1 formal Blind30 상태 불변 확인

## 9. Decision Gate

| Gate | 판정 | 근거 |
|---|---|---|
| SOT 부합 | ✓ | 사람 blind GT의 core 품질을 유지하며 owner conflict 검수 비용만 줄인다 |
| 기대효과 | ✓ | paired 95개 재계산에서 9/69 conflict 감소, core conflict 유실 0 |
| 측정가능 | ✓ | immutable submission read-only replay와 version별 consensus 지표로 전후 비교 가능 |
| 유효한 계획 | ✓ | 새 live version, 날짜 activation, DB snapshot/guard, rollback 경계가 고정됨 |
