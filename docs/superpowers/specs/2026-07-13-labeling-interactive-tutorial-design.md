# 라벨링 웹 대화형 튜토리얼 설계

> 상태: **production 배포·5개 seed·`tutorial-v1` 활성화 완료 · 활동 중 라벨러 2명 모두 0/5, 1명 pilot 지정 대기** (2026-07-14)
> 구현 계획서: [`../plans/2026-07-13-labeling-interactive-tutorial-plan.md`](../plans/2026-07-13-labeling-interactive-tutorial-plan.md)
> 최종 검증: web 245 tests·tsc·Vercel production build·Python 334 통과. DB 검증 client_policies=0/RLS 4/4/funcs 6.
> 남은 릴리스 단계(§17): 라벨러 2명 중 1명 5개 E2E → 본 큐 진입·첫 본작업 5개 확인 → 나머지 팀원 개방.
> 작성일: 2026-07-13
> 구현 담당: Claude
> 선행 조건: 라벨러 가입·owner 승인 기능 production 배포 및 실제 계정 E2E 완료
> 관련: [라벨링 웹 v2](2026-07-12-labeling-web-v2-design.md) · [가입·승인·날짜 선택](2026-07-13-labeler-signup-date-controls-design.md) · [RBA Data Engine v1](../../../specs/feature-rba-data-engine-v1.md)

## 1. 한 줄 결정

승인된 신규 라벨러는 일반 큐에 들어가기 전에 owner가 지정한 동일한 5개 영상을
실제 라벨링 화면과 같은 순서로 검수한다. 각 영상의 Blind GT와 VLM 검수를 모두
제출한 뒤 기준 답안·차이·해설을 확인하면서 배운다. 5개 해설을 모두 확인하면
본작업 큐가 열린다. 점수 합격선은 두지 않는다.

튜토리얼 답안은 production `behavior_labels`와 `clip_labeling_sessions`에 쓰지 않는다.
학습용 시도와 운영 GT를 분리해야 튜토리얼 정답 공개와 재시도가 데이터셋을
오염시키지 않는다.

## 2. 왜 지금 필요한가

회원가입과 날짜 배분만으로는 라벨 품질이 보장되지 않는다. 특히 다음 기준은 안내문만
읽고 일관되게 적용하기 어렵다.

- visible/partial/absent/uncertain 구분
- 일반 이동과 wheel/object interaction 구분
- 빠른 움직임과 playing evidence 구분
- 대표 행동과 복수 관찰 행동·구간의 관계
- 실제 shedding과 의심 장면 구분
- GT를 먼저 잠근 뒤 VLM을 독립적으로 검수하는 순서

5개 공통 영상은 통계적 평가 표본이 아니다. 목적은 대량 투입 전에 UI 사용 오류와
큰 기준 오해를 발견하고 즉시 교정하는 것이다. VLM 정확도나 라벨러 일치도를 주장하려면
후속 공통 30개 이상과 별도 adjudication이 필요하다.

## 3. 접근안 비교

### A. 기존 운영 라벨링 세션 재사용

구현은 가장 빠르지만 튜토리얼 답안이 GT와 `behavior_labels`에 섞인다. 정답을 본 뒤
재시도한 값이 사람 blind GT처럼 보이는 심각한 provenance 오류가 생겨 채택하지 않는다.

### B. 고정 Tutorial v1 + 별도 시도 기록 — 채택

owner가 확정한 5개 clip·기준 GT·고정 VLM snapshot·해설을 하나의 버전으로 저장한다.
라벨러 답안과 진행도는 튜토리얼 전용 테이블에 저장한다. 구현 범위가 통제되고 데이터
분리와 재현성이 확보된다.

### C. 범용 커리큘럼 제작·편집 시스템

owner가 웹에서 영상 검색, 순서 변경, 기준 답안 편집, 다중 코스 운영까지 할 수 있다.
장기적으로 유용하지만 현재 5개 파일럿보다 범위가 크다. Tutorial v1 운영 결과가 나온
뒤 별도 기능으로 검토한다.

## 4. 목표와 비목표

### 목표

- 승인된 신규 라벨러가 5개를 완료하기 전 일반 큐·일반 clip API에 접근하지 못한다.
- 실제 v2 흐름과 동일하게 `Blind GT → VLM 검수 → 기준 피드백`을 경험한다.
- 각 영상 완료 직후 기준 답안과 본인 답의 차이를 이해한다.
- 5개를 모두 완료하면 자동으로 일반 큐가 열린다.
- 중간 이탈 후 정확한 단계에서 이어서 할 수 있다.
- owner가 팀원별 진행 상태와 주로 틀린 기준을 확인할 수 있다.
- 튜토리얼 답안·정답·점수는 production GT와 완전히 분리한다.

### 비목표

- 5개 결과로 라벨러를 합격·탈락시키기
- 튜토리얼 점수로 계정이나 승인 상태 자동 변경
- Tutorial v1에서 범용 코스 편집기 만들기
- 튜토리얼 답안을 train/validation/holdout GT로 export하기
- AI가 기준 답안이나 해설을 자동 생성하기
- 라벨러끼리 답안을 보거나 비교하기
- 이메일·Slack 자동 알림
- 모바일 앱에 동일 기능 추가

## 5. 운영 정책

1. owner는 튜토리얼 의무 대상에서 제외하고 언제든 preview할 수 있다.
2. owner가 승인해 `labelers`가 된 일반 사용자는 active tutorial을 완료하기 전
   `/labeling/tutorial`만 사용할 수 있다.
3. 완료 조건은 5개 lesson의 `피드백 확인`이다. 정답률이나 점수 기준은 없다.
4. 점수와 차이는 교육·관리자 진단용이며 사용자에게 `불합격` 표현을 쓰지 않는다.
5. 완료 후 헤더의 `튜토리얼` 버튼으로 요약과 기존 해설을 다시 볼 수 있다.
6. 재실습이 필요하면 owner가 팀원 관리에서 `튜토리얼 다시 시작`을 실행한다.
   이전 답안은 삭제하지 않고 run 번호를 올려 보존한다.
7. active tutorial이 없거나 5개 구성이 불완전하면 fail closed한다. 신규 라벨러에게
   일반 큐를 열지 않고 `튜토리얼 준비 중 · 관리자에게 문의`를 표시한다.
8. owner는 긴급한 경우에만 완료 면제를 부여할 수 있다. 면제 사유·시각·처리자를 보존한다.

## 6. 사용자 체험 설계

### 6.1 승인 직후

1. `[화면]` 라벨러가 승인 안내를 받고 `상태 새로고침`을 누른다.
2. `[반응]` 일반 큐가 아니라 `/labeling/tutorial`로 이동한다.
3. `[화면]` `본작업 전 5개 연습`과 `약 15~25분`, 진행도 `0/5`를 본다.
4. `[조작]` `튜토리얼 시작`을 누른다.
5. `[감정]` 시험이나 탈락 절차가 아니라 실제 작업을 배우는 과정임을 이해한다.

### 6.2 영상 1개 학습

1. `[화면]` 상단에서 `2/5 · 일반 이동과 상호작용 구분`처럼 현재 목표를 본다.
2. `[화면]` 영상과 재생·frame step·속도 조절, Blind GT 폼을 본다.
3. `[조작]` 영상을 끝까지 확인하고 가시성, 대표/복수 행동, 구간, target,
   confidence, 품질·환경, activity/enrichment 정보를 입력한다.
4. `[조작]` `GT 잠그고 VLM 보기`를 누른다.
5. `[반응]` GT는 수정 불가 상태가 되고 고정된 VLM snapshot이 공개된다.
   이 시점에는 기준 답안을 공개하지 않는다.
6. `[조작]` VLM verdict와 오류 유형을 독립적으로 입력한다.
7. `[조작]` `검수 제출하고 해설 보기`를 누른다.
8. `[반응]` 본인 답, 기준 답, 일치한 점, 다시 볼 점, 행동별 해설이 나타난다.
9. `[조작]` 영상을 필요한 만큼 다시 재생하고 `해설 확인하고 다음`을 누른다.
10. `[감정]` 무엇이 틀렸는지만이 아니라 다음 영상에서 적용할 기준을 이해한다.

### 6.3 중간 이탈과 복귀

- GT 전 이탈: 저장된 draft가 있다면 복구하고, 없다면 해당 lesson 처음부터 시작한다.
- GT 잠금 후 이탈: 고정 VLM snapshot부터 이어간다.
- 검수 제출 후 이탈: 해설 화면으로 복귀한다.
- 피드백 확인 후 이탈: 다음 미완료 lesson으로 이동한다.
- 이미 제출한 최초 GT와 최초 VLM review는 클라이언트에서 덮어쓸 수 없다.

### 6.4 5개 완료

1. `[화면]` `튜토리얼 완료 · 이제 날짜별 본작업을 시작할 수 있어`를 본다.
2. `[화면]` 다섯 lesson별 핵심 교정 항목과 본인의 `다시 볼 기준` 요약을 본다.
3. `[조작]` `라벨 대기 큐로 이동`을 누른다.
4. `[반응]` 일반 큐 접근 게이트가 열리고 전달받은 날짜를 선택할 수 있다.

## 7. Tutorial v1의 5개 교육 목표

실제 clip은 아래 목표를 충족하는 owner 검수 완료 영상으로 선택한다. 행동명이 아니라
해당 영상에서 실제로 확인되는 evidence를 기준으로 고른다.

| 순서 | 교육 목표 | 반드시 가르칠 내용 |
|---|---|---|
| 1 | 가시성·unseen | visible/partial/absent/uncertain, 안 보임과 판단 불가 구분 |
| 2 | 일반 이동 | 등반·위치 이동·자세 변경, 대표 행동과 행동 구간 입력 |
| 3 | wheel interaction | 빠르기만으로 playing 처리하지 않음, wheel+ride/push/rotate evidence, activity intensity 분리 |
| 4 | 복수 행동·object interaction | 대표 행동 1개와 관찰 행동 여러 개, target, enrichment object, interaction type, 구간 |
| 5 | 모호한 케어 행동·VLM 오류 | 실제 shedding과 의심 분리, confidence/unjudgeable 사용, VLM 오류 tag 선택 |

선정 clip 5개는 모두 다음을 만족해야 한다.

- R2 원본과 썸네일 재생 가능
- owner의 완료된 v2 session 존재
- owner가 직접 확정한 `initial_gt/current_gt` 존재
- exact `prediction_snapshot`과 owner VLM review 존재
- 영상·기준 답·해설을 owner가 최종 확인
- 다섯 clip이 서로 중복되지 않음

VLM prediction이 없는 clip은 Tutorial v1에 넣지 않는다. 전체 2단계 작업을 배워야 하기
때문이다.

## 8. 화면과 라우팅

### 공통 헤더

- 승인된 labeler에게 `튜토리얼` 메뉴를 표시한다.
- 미완료면 강조 badge `필수 · N/5`, 완료면 일반 메뉴 `튜토리얼`로 표시한다.
- owner는 `미리보기` badge와 함께 접근한다.

### `/labeling/tutorial`

- 목적, 예상 시간, 점수 합격선이 없다는 설명
- 5개 lesson 목록과 잠금/진행/완료 상태
- `시작`, `계속하기`, 완료 후 `해설 다시 보기`
- 일반 큐가 언제 열리는지 명확히 표시

### `/labeling/tutorial/[position]`

- 기존 상세 영상 플레이어·frame step·속도 제어 재사용
- Tutorial 전용 GT/VLM/feedback 상태 머신 사용
- 상단 `N/5`, 교육 목표, 진행 bar
- 제출 전 tip은 판단 원칙만 제공하고 이 영상의 답을 노출하지 않음
- feedback 화면은 `일치`, `다시 보기`, `개인차 가능` 세 그룹으로 표현
- 숫자 총점과 `불합격` 문구는 표시하지 않음

### `/labeling/team`

- 활동 중 팀원마다 `튜토리얼 0/5`, `진행 중 3/5`, `완료`, `면제` 표시
- 상세에서 lesson별 mismatch dimension을 확인
- owner action: `다시 시작`, `완료 면제`
- 다시 시작은 기존 기록을 삭제하지 않고 `current_run_no + 1`

### 일반 큐·일반 상세

- incomplete labeler가 URL을 직접 입력해도 서버가 403
  `{ detail: 'tutorial_required' }`를 반환한다.
- 클라이언트는 이 응답을 받으면 `/labeling/tutorial`로 이동한다.
- owner와 완료/면제 labeler만 기존 흐름을 사용한다.

## 9. 데이터 모델

모든 신규 테이블은 RLS를 켜고 client role 정책을 만들지 않는다. Next.js route가 bearer를
검증한 뒤 `service_role`로만 접근한다. 정답 JSON은 브라우저가 Supabase를 직접 조회할 수
없어야 한다.

### `labeling_tutorial_sets`

| 컬럼 | 계약 |
|---|---|
| `id` | UUID PK |
| `version` | TEXT UNIQUE, 예: `tutorial-v1` |
| `title` | TEXT |
| `status` | `draft / active / archived` |
| `created_by` | auth.users FK |
| `activated_at` | TIMESTAMPTZ NULL |
| `created_at`, `updated_at` | TIMESTAMPTZ |

`status='active'`는 partial unique index로 전체 1개만 허용한다. active 전환은 정확히
5개 lesson과 모든 기준 snapshot 존재를 검사하는 service-role RPC로만 수행한다.

### `labeling_tutorial_lessons`

| 컬럼 | 계약 |
|---|---|
| `id` | UUID PK |
| `tutorial_set_id` | set FK ON DELETE RESTRICT |
| `position` | SMALLINT, 1~5 |
| `clip_id` | camera_clips FK ON DELETE RESTRICT |
| `title`, `learning_objective`, `pre_submit_tip` | 교육 문구 |
| `reference_gt` | owner가 확정한 GroundTruthInput JSONB |
| `prediction_snapshot` | 활성화 시 고정한 VLM JSONB |
| `reference_vlm_review` | owner verdict/error tags JSONB |
| `feedback_content` | dimension별 해설 JSONB |

UNIQUE `(tutorial_set_id, position)`, `(tutorial_set_id, clip_id)`를 둔다. 활성화 뒤 lesson의
clip·reference·prediction·feedback은 수정하지 않는다. 변경은 새 tutorial version으로 만든다.

### `labeling_tutorial_progress`

| 컬럼 | 계약 |
|---|---|
| `tutorial_set_id`, `user_id` | 복합 PK |
| `current_run_no` | INTEGER, 기본 1 |
| `started_at`, `completed_at` | TIMESTAMPTZ |
| `waived_at`, `waived_by`, `waiver_reason` | owner 면제 audit |
| `updated_at` | TIMESTAMPTZ |

본 큐 접근 조건은 owner이거나 active set의 `completed_at IS NOT NULL` 또는
`waived_at IS NOT NULL`이다. lesson 완료 수는 attempt를 세어 응답하고, gate hot path는
progress 한 row만 조회한다.

### `labeling_tutorial_attempts`

| 컬럼 | 계약 |
|---|---|
| `id` | UUID PK |
| `tutorial_set_id`, `lesson_id`, `user_id`, `run_no` | 시도 식별자 |
| `stage` | `draft / gt_locked / review_submitted / completed` |
| `submitted_gt` | 최초 tutorial GT JSONB |
| `submitted_vlm_review` | 최초 VLM review JSONB |
| `comparison` | 서버가 생성한 dimension별 비교 JSONB |
| `gt_locked_at`, `review_submitted_at`, `feedback_viewed_at`, `completed_at` | 단계 시각 |
| `created_at`, `updated_at` | TIMESTAMPTZ |

UNIQUE `(tutorial_set_id, lesson_id, user_id, run_no)`를 둔다. `(user_id,
tutorial_set_id, run_no, stage)` 조회용 B-tree index를 둔다. trigger로 최초
`submitted_gt`, `submitted_vlm_review`, `comparison`을 불변으로 만든다.

`behavior_labels`와 `clip_labeling_sessions`에는 아무것도 쓰지 않는다.

## 10. 답안 비교와 피드백

비교는 서버의 순수 함수로 계산하고 결과를 snapshot으로 저장한다. 기준 답안이 나중에
바뀌는 문제를 막기 위해 active lesson은 불변이다.

- exact 비교: visibility, primary_action, target, activity_intensity,
  enrichment_object, VLM verdict
- set 비교: observed_actions, interaction_types, VLM error_tags
- segment 비교: 같은 action끼리 start/end 각각 기준 답과 1초 이내면 일치
- 참고만: human_confidence, context_tags, note

피드백은 필드 값을 나열하는 데서 끝내지 않는다.

- `네 답`: 사용자가 제출한 값
- `기준`: owner reference
- `왜`: 해당 lesson의 행동 evidence와 경계 기준
- `다음 영상에서`: 한 문장 행동 지침

비교 결과는 `matched`, `review`, `subjective` dimension 목록을 제공하지만 aggregate
pass/fail을 계산하지 않는다. owner 화면에는 run별 mismatch dimension 수만 보여준다.

## 11. API 계약

### 라벨러용

- `GET /api/labeling-tutorial`
  - active set, 진행도, 현재 run, 5개 lesson의 공개 metadata 반환
- `GET /api/labeling-tutorial/lessons/[position]`
  - 제출 전: clip metadata·학습 목표·tip·본인 attempt만 반환
  - review 제출 후: reference·comparison·feedback도 반환
- `GET /api/labeling-tutorial/lessons/[position]/thumbnail/url`
- `GET /api/labeling-tutorial/lessons/[position]/file/url`
  - active lesson인지와 호출 사용자의 tutorial 접근을 서버에서 검증
- `POST /api/labeling-tutorial/lessons/[position]/gt`
  - 기존 `validateGroundTruth` 재사용, reference는 반환하지 않고 고정 VLM snapshot만 반환
- `POST /api/labeling-tutorial/lessons/[position]/vlm-review`
  - `validateVlmReview` 재사용, 최초 review 저장 후 comparison·reference·feedback 반환
- `POST /api/labeling-tutorial/lessons/[position]/acknowledge`
  - feedback 조회 가능한 stage에서만 lesson completed
  - 다섯 번째면 같은 DB transaction/RPC에서 progress completed 처리

모든 POST는 재호출에 안전해야 한다. 같은 payload 재전송은 기존 결과를 반환하고, 최초
제출과 다른 payload로 덮어쓰려 하면 409를 반환한다.

### owner용

- `GET /api/labeling-tutorial/team-progress`
- `POST /api/labeling-tutorial/users/[userId]/reset`
- `POST /api/labeling-tutorial/users/[userId]/waive`

모두 `requireOwner`를 사용한다. reset은 run 번호만 증가시키고 기존 attempt를 보존한다.
waive는 1~200자 사유를 필수로 받는다.

### 기존 access 계약 변경

`GET /api/labeling-access`에 다음을 추가한다.

```ts
tutorial: {
  required: boolean;
  status: 'not_started' | 'in_progress' | 'completed' | 'waived' | 'unavailable';
  completed_lessons: number;
  total_lessons: 5;
}
```

기존 `access='labeler'` 의미는 멤버십으로 유지한다. tutorial 상태를 access enum에 섞지
않아 가입 승인과 교육 완료를 별도 축으로 보존한다.

## 12. 접근 제어와 보안

- `requireLabelingAccess`: owner 또는 실제 `labelers` 멤버인지 확인. tutorial API에 사용.
- 신규 `requireProductionLabelingAccess`: 위 조건 + owner bypass 또는 active tutorial
  completed/waived 확인. 기존 큐·일반 clip metadata·thumbnail·재생·다운로드·GT·VLM
  review 전체에 사용.
- tutorial media route는 요청 lesson의 clip_id만 허용한다. 일반 clip UUID를 넣어도 404.
- reference GT·prediction·feedback은 VLM review 최초 제출 전 API 응답, HTML, client props,
  로그에 포함하지 않는다.
- 정답 테이블은 RLS ENABLE + anon/authenticated 정책 0건 + service_role 전용.
- user_id, position, body는 서버에서 whitelist 검증한다.
- Supabase 내부 오류와 stack trace는 클라이언트에 노출하지 않는다.
- owner reset/waive, tutorial 완료 시각은 audit 가능해야 한다.
- 일반 큐 차단은 client redirect가 아니라 모든 API의 server authorization으로 강제한다.

## 13. 오류·예외 처리

- active set 없음/lesson 5개 미만: labeler는 준비 중 화면, owner는 누락 원인 표시
- 영상/R2 없음: 해당 lesson 완료 금지, 재시도와 관리자 문의 표시
- GT validation 실패: 기존 v2와 같은 구체적 400 문구
- GT 중복 제출: 같은 값이면 성공 응답, 다른 값이면 409
- 순서 건너뛰기: 이전 lesson 미완료면 현재 가능한 lesson 위치와 409 반환
- VLM review 전 reference 요청: response에서 reference key 자체를 생략
- feedback acknowledge 재호출: 이미 완료된 상태를 그대로 반환
- reset 중 진행: 새 run을 시작하고 이전 run은 read-only history로 보존
- 권한 해제: tutorial 이력은 삭제하지 않지만 모든 영상 접근은 즉시 차단

## 14. owner가 5개를 지정하는 방법

Tutorial v1에는 범용 편집 UI를 만들지 않는다. 초기 설정은 다음 절차로 한다.

1. owner가 일반 v2 화면에서 후보 5개를 끝까지 검수한다.
2. migration과 함께 제공되는 seed SQL/RPC 입력 템플릿에 clip_id, 순서, 교육 문구를 넣는다.
3. 서버가 owner session의 `current_gt`, `prediction_snapshot`, VLM review를 lesson snapshot으로 복사한다.
4. owner가 생성된 draft set을 preview한다.
5. owner-only activation RPC가 5개·reference·prediction·feedback 완전성을 검사하고 active로 바꾼다.
6. active 뒤 수정이 필요하면 기존 set을 archive하고 새 version을 만든다.

Claude 구현 결과에는 비밀값이나 임의 clip UUID가 들어간 seed를 커밋하지 않는다.
실제 5개 clip 선정과 활성화 SQL은 사용자 검토 후 별도로 실행한다.

## 15. 검증 계획

### unit/API

- active set은 하나만 존재
- tutorial GT/VLM validation이 기존 v2 validator와 동일
- 최초 tutorial 답안 불변
- review 제출 전 reference 미노출
- comparison exact/set/segment 1초 허용 경계
- 1~4개 완료 시 일반 큐 403, 5개 feedback 확인 후 200
- owner bypass, waive, reset run 보존
- 일반 labeler가 다른 clip UUID로 tutorial media 접근 시 404
- 다른 사용자의 attempt/progress 접근 차단
- active set 없음 fail closed
- 같은 POST 재전송 idempotency와 다른 payload 409

### production E2E

1. 테스트 라벨러 가입·owner 승인
2. 승인 직후 tutorial redirect와 일반 큐/API 차단
3. lesson 1 GT 제출 전 DOM/network에 reference 없음
4. GT 잠금 후 고정 VLM 공개, reference는 여전히 없음
5. VLM review 제출 후 기준·차이·해설 공개
6. 중간 로그아웃·로그인 후 단계 복구
7. 5개 feedback 확인 후 큐 접근
8. owner 팀원 관리에서 5/5와 mismatch dimension 확인
9. reset 후 run 2 시작, run 1 보존
10. 390px viewport에서 가로 overflow 없이 영상·폼·해설 사용

## 16. 성공 기준과 유효성

### 기능 성공

- 신규 라벨러 100%가 일반 큐 전에 5개 해설을 확인한다.
- 튜토리얼 답안이 production GT 테이블에 0건 기록된다.
- 중간 이탈 후 재개 성공률 100%.
- reference의 조기 노출 보안 테스트가 모두 통과한다.

### 운영 성공

- 첫 3명 중 3명이 별도 구두 조작 설명 없이 5개를 완료한다.
- 5개 완료 후 owner가 각 팀원의 주요 mismatch 기준을 확인할 수 있다.
- 공통 오해가 발견되면 해설 문구나 본작업 SOP를 수정할 근거가 생긴다.
- 튜토리얼 뒤 각 팀원이 본작업 5개를 추가 수행했을 때 필수 필드 누락과 흐름 오류가 없다.

### 이 단계가 증명하지 않는 것

- 5개만으로 라벨러 간 신뢰도나 행동별 정확도를 통계적으로 증명하지 않는다.
- tutorial clip은 답이 공개되므로 모델 평가·holdout에 쓰지 않는다.
- VLM 개선 여부는 별도 blind GT와 future camera-night에서 평가한다.

튜토리얼이 유효한 이유는 모델 성능을 직접 높이기 때문이 아니라, 더 많은 사람이 같은
라벨 계약을 지키도록 만들어 이후 GT의 오라벨 비용을 줄이기 때문이다. 다음 의사결정은
튜토리얼 완료자들이 공통 blind 30개에서 허용 가능한 일치도를 보이는지로 한다.

## 17. 배포 순서

1. ✅ 가입·승인 기능 production 배포
2. ✅ tutorial migration 적용
3. ✅ 코드 배포·unit/API/build 검증
4. ✅ owner 후보 5개 일반 v2 검수와 2건 revision 보정
5. ✅ draft Tutorial v1 seed·owner preview
6. ✅ active 전환(2026-07-14 KST, active 1·lesson 5)
7. 🚧 활동 중 라벨러 2명 중 1명 end-to-end pilot
8. ✅ production 운영 화면 확인(승인 대기 0명·활동 중 2명·두 명 모두 0/5)
9. ⏳ pilot 5/5·본 큐 진입·첫 본작업 5개 확인 후 나머지 팀원 개방

DB·콘텐츠·웹 활성화는 완료됐다. 현재 release gate는 지정한 pilot 1명의
`5/5 완료 → 본 큐 진입 → 첫 본작업 5개 owner 확인`이며, 그 전에는 전체 팀 본작업을 개방하지 않는다.

## 18. 구현 파일 예상 범위

Claude는 상세 구현 계획에서 실제 파일을 확정하되 다음 경계를 유지한다.

- migration: `migrations/2026-07-13_labeling_tutorial.sql`
- types/validation/comparison: `web/src/lib/labelingTutorial.ts`
- access gate: `web/src/lib/labelingAccess.ts`, `web/src/lib/clipPerms.ts`
- client API: `web/src/lib/labelingApi.ts`
- tutorial API: `web/src/app/api/labeling-tutorial/**`
- summary/detail UI: `web/src/app/labeling/tutorial/**`
- navigation/redirect: `web/src/app/labeling/layout.tsx`, login/pending routing
- owner progress: `web/src/app/labeling/team/page.tsx`
- focused tests: validator/comparison/access/route/UI state
- SOT: `docs/DATABASE.md`, `docs/FEATURES.md`, `specs/next-session.md`

기존 `/labeling/[clipId]` 전체를 복사해 두 개의 거대한 페이지로 만들지 않는다. 영상 플레이어와
GT/VLM 폼을 mode-independent component로 필요한 만큼만 분리하되, tutorial 저장 API와
production 저장 API는 명확히 분리한다.
