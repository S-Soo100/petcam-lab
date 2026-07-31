# 사건 경계 검수 + 팀 공용 데이터 대시보드 설계

**상태:** 사용자 승인 · 구현 전 동결

**작성일:** 2026-07-31

**대상:** `petcam-lab/web` 라벨링 웹
**선행 정본:** `rba-event-media-eligibility-v1-design.md`의 R2 HEAD 240/240 exact-120 private artifact

## 1. 한 줄 결론

기존 행동 교차검수는 그대로 두고, 지정된 두 사람이 “연속된 두 영상이 같은 사건인가”를 따로
판정하는 화면과 승인된 팀원 모두가 현재 영상·GT 현황을 보는 집계 대시보드만 추가한다.

## 2. In / Out

### In

- `영상 이어짐 확인`: owner와 지정 peer에게 배정된 pair만 표시
- 두 사람의 독립 최초 판정: `same_event / different_event / uncertain`
- 서로 다르거나 하나라도 `uncertain`이면 owner가 이유를 적고 최종 해결
- 팀 공용 `데이터 현황`: 영상 기록, 재생 가능 영상, GT 완료 영상, 행동별 GT 분포
- 기존 인증·R2 서명·라벨링 웹 디자인 체계 재사용

### Out

- 기존 교차검수·GT·slot·consensus 변경
- 자동 사건 병합, 원본 영상 병합·삭제, 앱 사건 카드
- Python Evidence, VLM, Gate, router 출력 사용
- holdout 자동 공개, 모델 threshold 결정

## 3. 역할과 공개 범위

| 기능 | Owner | 승인 라벨러 | 미승인 사용자 |
|---|---|---|---|
| 데이터 현황(집계만) | 보기 | 보기 | 차단 |
| 기존 교차검수 | 기존 권한 유지 | 기존 권한 유지 | 차단 |
| 영상 이어짐 확인 | 배정됐을 때 보기·최초 판정 | 지정 peer로 배정됐을 때만 보기·최초 판정 | 차단 |
| 경계 불일치·uncertain 해결 | owner만 | 차단 | 차단 |

메뉴 숨김은 보안 경계가 아니다. 모든 경계 API는 먼저 `owner 또는 현재 활성 labeler`인지 확인한
뒤 로그인 사용자 UUID와 DB assignment를 다시 검사한다. labelers에서 제거된 peer는 assignment가
남아도 즉시 차단된다. 이메일은 초기 배정 때만 계정을 찾는 입력으로 쓰고 API 권한 판단에는 쓰지 않는다.

## 4. 사용자 체험 시뮬레이션

### 4.1 사건 경계 검수

`[화면] 기존 라벨링 메뉴에 ‘이어짐 확인’과 남은 수가 보임`

→ `[조작] 한 문제를 열어 영상 A를 보고 영상 B를 이어서 봄`

→ `[반응] 같은 사건 / 다른 사건 / 모르겠음 중 하나를 고르고 제출`

→ `[반응] 답은 수정되지 않고 상대 답도 보이지 않은 채 다음 문제로 이동`

→ `[감정] 행동 이름을 다시 붙이는 일이 아니라 영상 사이의 이어짐만 판단한다고 이해함`

두 답이 다르거나 둘 중 하나라도 `uncertain`이면 owner에게만 별도 `경계 해결` 목록이 생긴다.
둘 다 `uncertain`이어도 자동 합의로 닫지 않는다. owner는 두 최초 답을 본 뒤 최종 판정과 이유를
한 번 제출한다. owner가 검수자이자 해결자라는 한계는 결과 보고서에 명시한다.

### 4.2 데이터 현황

`[화면] 로그인 직후 메뉴에서 ‘데이터 현황’을 누름`

→ `[반응] 영상 기록 / 재생 가능 / GT 완료 숫자와 행동별 막대가 보임`

→ `[조작] 새로고침`

→ `[반응] 현재 DB 기준 집계 시각과 숫자가 함께 갱신됨`

→ `[감정] Python Evidence나 VLM 숫자와 섞이지 않은 사람 정답 축적량을 바로 이해함`

## 5. 사건 경계 데이터 계약

### 5.1 테이블

- `rba_boundary_review_cohorts`: 한 연구 묶음, manifest digest, 상태
- `rba_boundary_review_pairs`: split, 순번, A/B clip, gap, pair digest
- `rba_boundary_review_assignments`: pair별 owner/peer 한 명씩
- `rba_boundary_review_submissions`: 사람별 immutable 최초 판정
- `rba_boundary_review_resolutions`: 불일치·uncertain pair의 owner immutable 최종 판정과 이유

submissions/resolutions는 append-only trigger로 UPDATE/DELETE/TRUNCATE를 막는다. 모든 테이블은
RLS를 켜고 `PUBLIC/anon/authenticated` 직접 접근을 회수하며 `service_role`만 사용한다.

### 5.2 연구 순서

- development 60만 먼저 `open`으로 노출한다.
- holdout 60은 같은 DB에 준비할 수 있지만 cohort 상태 전환 전에는 조회·서명·제출 모두 막는다.
- 개발 답이 끝나고 규칙을 동결하기 전 holdout을 여는 API나 UI를 만들지 않는다.
- owner가 이전 행동 라벨링에서 본 pair가 일부 있어도 frozen 표본을 바꾸지 않고, 전체 결과와 해당
  pair 제외 민감도 결과를 함께 계산한다.

## 6. 사건 경계 API 계약

- `GET /api/rba-boundary/workspace`: 본인 배정 progress와 다음 미제출 pair, 상대 답 비공개
- `GET /api/rba-boundary/pairs/[pairId]/file/url?side=left|right`: 본인 배정 + 열린 split일 때만 R2 서명
- `POST /api/rba-boundary/pairs/[pairId]/submit`: decision만 수신, 사용자 UUID는 bearer token에서 파생
- `GET /api/rba-boundary/conflicts`: owner의 해결 대기만 반환
- `POST /api/rba-boundary/conflicts/[pairId]/resolve`: 두 답이 다르거나 uncertain일 때 final decision + 필수 reason

raw R2 key, 다른 검수자 UUID/답, holdout row는 일반 workspace 응답에 포함하지 않는다.

## 7. 팀 공용 대시보드 계약

대시보드는 개인 성과표가 아니라 팀이 공유하는 데이터 재고판이다.

- `video_record_count`: `motion_clips` 전체 행 수
- `playable_video_count`: `r2_key`가 있고 활성 `quarantined/media_deleted` 제외인 영상 수
- `gt_labeled_video_count`: 최종 decision이 `label`이고 canonical 사람 GT에 non-empty
  `primary_action`이 있는 unique clip 수
- `behavior_counts`: 바로 위 분모의 `primary_action`별 unique clip 수. 합계는 항상
  `gt_labeled_video_count`와 같다
- `generated_at`: 서버 집계 시각

대시보드는 blind 상태를 공개하는 보관함이 아니라 안정적인 누적 재고판이다. 따라서 열린
canary/live의 awaiting/conflict row로 기존 확정 GT를 마스킹하지 않는다. **완료된 사람 GT만**
다음 순서로 선택한다.

1. canary consensus `agreed/owner_resolved`이면서 `final_decision='label'`
2. live consensus `agreed/owner_resolved`이면서 `final_decision='label'`
3. 기존 `motion_clip_labeling_sessions` 최신본(owner 우선)

Blind 진행 중 답, VLM/Gate/Python Evidence, boundary 답은 GT 집계에 넣지 않는다. API는
`requireLabelingAccess`로 owner와 활성 승인 라벨러만 허용하고 reviewer 이름·개별 답은 반환하지 않는다.
`playable_video_count`는 R2에 실제 HEAD를 매번 보내는 수가 아니라 DB의 `r2_key`와 활성 exclusion
기준 수다. GT 집계가 안정적이라 열린 blind 배치 규모도 숫자 변화로 노출되지 않는다.

## 8. UI와 내비게이션

- owner와 labeler 공통 메뉴로 `데이터 현황`을 추가한다.
- `이어짐 확인`은 DB assignment가 있는 사용자에게만 추가한다.
- 기존 메뉴 순서·경로는 유지한다. 모바일 하단 메뉴는 항목 수에 맞춘 동적 grid를 써 320px에서
  가로 스크롤과 글자 잘림을 막는다.
- 대시보드 행동 라벨은 기존 한국어 표시명을 재사용하고, 0건 행동은 숨긴다.
- 숫자 집계 실패는 0으로 위장하지 않고 재시도 가능한 오류 카드로 표시한다.

## 9. 배포·안전 계약

1. migration 정적 계약 + disposable PostgreSQL probe를 통과한다.
2. route/권한/UI 테스트를 먼저 실패시키고 구현 후 통과시킨다.
3. Preview에서 owner/peer/일반 labeler/미승인 역할을 검증한다.
4. production migration은 forward-only로 적용하고 private exact-120 manifest에서 development 60만
   idempotent seed한다. 원문 UUID/R2 key는 로그에 출력하지 않는다.
5. Vercel production 배포 후 기존 교차검수 API smoke test와 신규 API 권한 test를 함께 확인한다.
6. 배포 전후 기존 GT/slot/consensus row 수가 변하지 않았음을 aggregate로 확인한다.
