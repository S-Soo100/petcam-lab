# RBA 사건 묶기 Shadow v2 TEST-SHEET

**상태:** `BLOCKED_MEDIA_PREFLIGHT_FAILED` — metadata exact-120 성공, R2 228/240
**실험일:** 2026-07-31
**목표:** 기존 닫힌 활동 영상에서 정확히 120개의 인접 pair를 뽑아 사건 경계 GT를 만든다.

## 1. 질문

같은 카메라·같은 활동일에서 시간상 이웃한 두 원본 clip은 하나의 연속 활동 사건인가?

두 non-owner reviewer가 상대 답과 기존 행동 답을 보지 않고 각각 아래 하나를 고른다.

- `same_event`
- `different_event`
- `uncertain`

불일치와 `uncertain`만 owner가 최종 판정한다.

## 2. 입력과 보호 집합

- source cutoff: `started_at < 2026-07-31T03:44:27.183403+09:00` (strict). 같은 시각 이상인
  Blind30 v2 future pool과 겹치지 않는다.
- KST 07:00 경계로 완전히 닫힌 activity day만 사용한다.
- metadata 입력: `motion_clips.id,camera_id,started_at,duration_sec`
- integrity 입력: `motion_clip_system_exclusions`
- 보호 입력: `motion_clip_review_slots`의 `cohort_kind='canary'`,
  `labeling_tutorial_lessons`, 명시적으로 전달한 frozen manifest
- ordinary live slot/submission/session/consensus는 행동 연구 이력일 뿐 boundary target 정답이
  아니므로 blocker로 쓰지 않는다. selector는 그 답 내용을 조회하지 않는다.
- Python Evidence, Gate, VLM, 행동 label은 조회하지 않는다. R2 key는 선택된 240개의 HEAD
  preflight에만 사용하고 selector 입력·공개 출력에는 넣지 않으며 URL은 조회하지 않는다.
- `motion_clip_review_slots.cohort_kind`의 관측 distinct 값은 정확히 `{live, canary}`여야 한다.
  그 외 값이 하나라도 있으면 fail-closed한다. 보호 집합은 `cohort_kind != 'live'` 전부다.

모든 source clip은 `activity_candidate`, `diagnostic_integrity`, `blocked_research` 중 정확히 하나로
accounting한다. diagnostic과 blocked는 사건 연속성을 끊는다.

## 3. Gap과 exact 표본

```text
gap_sec = next.started_at - (current.started_at + current.duration_sec)
```

- short: `gap <= 30s`
- medium: `30s < gap <= 60s`
- long: `60s < gap <= 300s`
- development 6 camera-nights + historical holdout 6 camera-nights
- 각 split 60 pair: short/medium/long 각각 20
- 전체 120 pair, unique clip 240, clip reuse 0
- 각 split 최소 camera 2대
- split별 한 camera 최대 36/60
- split·bin별 한 camera 최대 14/20

## 4. 선택 알고리즘

- seed: `rba-event-grouping-shadow-v2`
- attempt `0..1999`의 deterministic camera-night partition을 검사한다.
- 각 partition에서 3개 bin 처리 순서 6가지를 모두 검사한다.
- exact 계약을 만족한 witness 중 canonical SHA-256이 가장 작은 하나를 선택한다.
- 전부 실패하면 `BLOCKED_SELECTOR_SEARCH_EXHAUSTED`로 끝낸다. 데이터 부족과 섞어 보고하지 않는다.
- 입력 순서를 뒤집어도 manifest hash가 같아야 하고 같은 입력 3회 결과가 byte-identical이어야 한다.

## 5. Media preflight

- exact 120 pair를 찾은 뒤 artifact 생성 전에 unique clip 240개를 R2 `HeadObject`로 1회씩 검사한다.
- HTTP 200, 양수 content length, non-empty ETag를 모두 요구한다.
- key·URL·ETag 원문은 출력·artifact에 저장하지 않는다. 실행 salt를 섞은 media digest와
  `verified=240` aggregate만 기록한다.
- 1개라도 실패하면 pair 교체 없이 `BLOCKED_MEDIA_PREFLIGHT_FAILED`로 전체 중단한다.
- R2 GET·frame decode는 하지 않는다.

## 6. 사람 검수와 판정

1. development 60만 먼저 연다.
2. 두 reviewer의 불일치·uncertain만 owner가 판정한다.
3. development로 시간 threshold 하나를 동결한다.
4. 그 뒤에만 holdout 60을 연다.
5. holdout의 `different_event`를 합친 over-merge는 전체·camera별 0이어야 한다.
6. event reduction은 activity candidate 대비 최소 15%여야 한다.
7. over-split, reviewer agreement, uncertain, owner 개입률을 함께 보고한다.

이 historical holdout은 내부 기술 타당성만 인증한다. production 앱 적용은 알고리즘 동결 뒤 별도
future holdout이 필요하다.

artifact 생성 직후에는 reviewer에게 배정하지 않는다. 다음 별도 동결 전에는
`PREPARED_MEDIA_VERIFIED_AWAITING_HUMAN_CHANNEL`까지만 선언한다.

- reviewer×clip 과거 접촉은 배정 시 SELECT-only로 ID 존재만 확인하고 답 내용은 읽지 않는다.
- 가능한 pair는 두 reviewer 모두 사전 접촉이 없는 사람에게 우선 배정하고, 불가피한 중복 비율을
  aggregate로 보고한다.
- 영상 열람 방식, worksheet 전달, 답 저장 위치, 접근권한, 암호화/삭제 계약을 별도 문서로 동결한다.
- production 라벨링 DB나 live slot을 재사용하지 않는다. 그 채널이 정해지기 전에는
  `READY_FOR_HUMAN_BOUNDARY_GT_V2`를 선언하지 않는다.

20/20/20 층화표본의 pooled 오류율은 자연 production 발생률이 아니다. holdout 0/60은 이
표본에서 관측 오류 0이라는 뜻으로만 보고한다.

## 7. 안전·완료 조건

- production DB SELECT만, RPC/mutation 0
- R2 HEAD 240, R2 GET/frame/model/Gate/Python Evidence 호출 0
- private artifact `0600`, no-overwrite
- raw clip/camera/reviewer ID, GT, R2 key/URL은 공개 보고서에 0
- exact 120 private manifest와 빈 worksheet 생성
- 독립 aggregate audit로 60/60, 20×3, 12박 분리, unique 240, cap, hash, mode 검증
- artifact 생성 성공 상태는 `PREPARED_MEDIA_VERIFIED_AWAITING_HUMAN_CHANNEL`; 별도 사람 채널
  계약 뒤에만 `READY_FOR_HUMAN_BOUNDARY_GT_V2`다. 둘 다 사건 묶기 알고리즘 채택이나
  production 준비 완료를 뜻하지 않는다.

## 8. 실행 결과 (2026-07-31)

- exact 120 pair와 unique clip 240 선택 성공
- development/holdout 각 60, 각 gap bin 20, 12 camera-nights 분리, camera cap 통과
- R2 HEAD 결과 `verified=228`, `failed=12`; 별도 read-only 원인 분류는 12건 모두
  `404 Not Found`, auth/기타 오류 0
- 동결 규칙대로 교체 없이 전체 중단
- output directory, manifest, worksheet 생성 0
- 현재 상태는 사람 검수 준비가 아니라 `BLOCKED_MEDIA_PREFLIGHT_FAILED`

이 실패는 historical 영상 총량 부족을 뜻하지 않는다. 선택된 240개의 DB→R2 media integrity
문제다. 실패 원인 감사와 재실행 규칙은 이 결과를 본 뒤 생긴 새 결정이므로 별도 동결 전까지
임의 재추출하지 않는다.

## 9. 2026-08-02 development 경계 분석과의 관계

이 문서의 `228/240` blocker는 독립 clip pair 방식의 historical v2 감사 이력으로 유지한다. 이후 별도 sequence eligibility 채널에서 R2 검증과 Owner 자격검사를 통과한 유효 경계 74개를 두 사람이 검수하고 Owner가 26개를 해결했다. 그 별도 cohort의 결과는 [`../rba-boundary-development-v1/REPORT.md`](../rba-boundary-development-v1/REPORT.md)가 정본이다.

새 결과는 이 과거 표본을 소급 수정하거나 historical holdout을 여는 것이 아니다. 사람 사건 GT `78 clips → 21 events`는 준비됐지만 gap-only router는 utility hold이며, local VLM baseline·future holdout·production 채택은 여전히 별도 gate다.
