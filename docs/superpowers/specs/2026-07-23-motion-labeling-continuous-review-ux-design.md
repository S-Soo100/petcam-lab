# Motion Labeling v3 연속 검수 UX 설계

## 1. 목적

owner가 운영 영상을 수십 건 연속 검수할 때 `영상 확인 → 분류 → 결과 확인 → 다음 미분류 영상`을 한 화면 흐름으로 반복할 수 있게 한다.

현재는 `보류/제외` 성공 직후 해당 카테고리 목록으로 강제 이동한다. 사용자는 다시 `전체 영상`을 누르고 다음 영상을 찾아야 하며, 원래 날짜·카메라·스크롤 위치도 잃는다. GT 안전장치는 유지하되, 분류 결과 확인과 다음 영상 이동을 분리한다.

## 2. 확인된 문제

1. `motionDecisionListPath()`가 `hold/skip` 성공 후 `/labeling/motion?state=...`로 강제 이동한다.
2. owner 탭에 `미분류`가 없고 `전체 영상`에 처리 완료·보류·제외·미분류가 섞인다.
3. 카드 상세 링크가 목록의 `state/camera/date/media` 문맥을 전달하지 않는다.
4. 상세의 `← 목록` 링크가 항상 `/labeling/motion`으로 돌아가 필터와 스크롤을 잃는다.
5. 상세에 `다음 영상` 동작이 없다.
6. `hold/skip` 뒤 GT 폼이 비활성 상태로 길게 남아 결과와 다음 행동이 눈에 띄지 않는다.
7. 결정 성공 피드백과 즉시 취소 경로가 분리돼 있지 않다.

## 3. 사용자 체험

### 3.1 미분류 큐 진입

- `[화면]` owner가 `/labeling/motion`을 연다.
- `[반응]` 기본 탭은 `미분류`이고 최신 촬영순 영상만 보인다.
- `[선택]` `전체 영상` 탭을 누르면 처리 상태와 관계없이 모든 영상을 볼 수 있다.
- `[감정]` 새로 처리할 영상과 과거 기록 조회 목적을 혼동하지 않는다.

### 3.2 보류·제외

- `[화면]` 사용자가 영상을 확인하고 `보류` 또는 `제외`를 누른다.
- `[반응]` 페이지는 이동하지 않고 상단 상태 배지와 성공 안내가 즉시 갱신된다.
- `[행동]` 사용자는 `결정 취소` 또는 `다음 미분류 영상`을 선택한다.
- `[반응]` GT 폼은 화면에서 접혀 잘못 입력할 수 없고, DB PT424 guard는 그대로 유지된다.
- `[감정]` 저장 결과를 확인한 뒤 스스로 다음 영상으로 넘어간다.

### 3.3 라벨 대상

- `[화면]` `라벨 대상으로 보내기`를 누르면 현재 화면에 머문다.
- `[반응]` GT 폼은 계속 활성화되고 `지금 사람 판정 작성`과 `나중에 라벨링하고 다음 영상`이 보인다.
- `[행동]` 지금 라벨링하거나 다음 미분류 영상으로 넘어간다.

### 3.4 목록 복귀와 완료

- `[행동]` `← 목록`을 누르면 원래 탭·카메라·날짜·재생 필터와 스크롤 위치가 복원된다.
- `[행동]` `다음 미분류 영상`을 누르면 현재 필터에서 현재 영상보다 바로 이전 순서의 미분류 영상으로 이동한다.
- `[완료]` 다음 영상이 없으면 목록으로 돌아가 `이 조건의 검수를 모두 마쳤어`를 보여준다.

## 4. 상태·탭 계약

owner 탭 순서는 다음으로 고정한다.

1. `미분류` (`state=unreviewed`) — 기본
2. `전체 영상` (`state=all`) — 명시적인 query 값
3. `라벨 대기` (`state=label`)
4. `보류` (`state=hold`)
5. `제외` (`state=skip`)

빈 query는 `unreviewed`로 해석한다. `전체 영상`은 `state=all`을 URL에 명시해 목록 복귀 시 뜻이 바뀌지 않게 한다. labeler 큐의 기존 서버 강제 `label` 계약은 변경하지 않는다.

## 5. 목록 문맥 계약

카드 링크는 목록의 공개 필터 query를 상세 URL에 그대로 전달한다.

```text
/labeling/motion/{clipId}?state=unreviewed&camera_id=...&date_from=...&date_to=...&media=ready
```

허용 필드는 기존 `MotionQueueUiFilters`의 `state`, `camera_id`, `date_from`, `date_to`, `media`뿐이다. 상세의 목록 링크와 다음 영상 API도 이 필터만 사용한다. 임의 외부 URL을 `returnTo`로 받지 않아 open redirect를 만들지 않는다.

목록은 상세 진입 직전 `window.scrollY`를 `sessionStorage`에 저장한다. key는 정규화된 목록 query로 만들고, 목록 재진입 시 한 번 복원한 뒤 삭제한다. 저장 실패는 큐 사용을 막지 않는다.

## 6. 다음 미분류 영상 계약

신규 owner 전용 endpoint를 추가한다.

```text
GET /api/labeling-v3/{clipId}/next?camera_id=...&date_from=...&date_to=...&media=...
→ { "next_clip_id": "uuid" | null }
```

- 인증된 owner만 호출한다. labeler는 기존 큐 흐름을 유지한다.
- 현재 clip의 `started_at`과 `id`를 서버에서 다시 읽는다.
- 기존 `fn_list_motion_clip_labeling_queue`를 `p_state='unreviewed'`, cursor=`(current.started_at,current.id)`, `p_limit=1`로 호출한다.
- 정렬은 기존 `(started_at DESC, id DESC)`를 그대로 사용한다.
- 날짜·카메라·미디어 필터는 큐와 같은 validator를 재사용한다.
- 현재 영상과 동일한 timestamp도 `id DESC` tie-break로 중복·누락 없이 다음 위치를 찾는다.
- 다른 사용자가 이미 처리한 영상은 RPC의 `unreviewed` 조건에서 자연히 제외된다.
- DB migration이나 신규 RPC는 만들지 않는다.

## 7. 상세 화면 계약

### 7.1 분류 성공

- `router.push('/labeling/motion?state=hold|skip')`를 제거한다.
- 상세 state를 성공 응답으로 갱신한다.
- 직전 state, 새 state, 새 `updated_at`을 보관해 undo를 제공한다.
- `hold/skip`이면 GT 폼을 렌더하지 않는다. PT424/API 409은 최종 안전장치로 유지한다.
- `label`이면 GT 폼을 유지한다.

### 7.2 결과 안내

결정 성공 뒤 다음 행동을 한 Card에 모은다.

- 상태 문구: `제외로 저장됨`, `보류로 저장됨`, `라벨 대상으로 저장됨`
- `결정 취소`: 직전 상태로 복구. 직전이 `unreviewed`면 `reset`, 나머지는 해당 decision을 호출한다.
- `다음 미분류 영상`: next endpoint 호출 후 이동.
- label 상태에서는 `지금 사람 판정 작성`으로 GT 폼에 스크롤한다.
- next가 `null`이면 원래 필터 목록으로 이동하고 `review_complete=1`을 붙여 완료 안내를 표시한다.

자동으로 다음 영상으로 넘어가지 않는다.

### 7.3 오류

- 분류 저장 실패: 현재 화면·폼·state를 유지하고 기존 오류 문구를 표시한다.
- undo 경합: 최신 detail을 다시 읽고 사용자에게 다른 화면에서 상태가 바뀌었다고 알린다.
- next 조회 실패: 저장된 분류를 되돌리지 않고 `다음 영상 다시 찾기`를 제공한다.
- next 대상이 이동 사이에 처리되면 endpoint를 다시 호출해 다음 unreviewed를 찾는다. 최대 3회 뒤 목록으로 돌아가 새로고침을 안내한다.
- 인증 만료는 기존 로그인 redirect를 유지한다.

## 8. 구현 경계

### 포함

- motion v3 owner 탭·상세·클라이언트 helper
- next API와 기존 큐 query validator 재사용
- URL 문맥·스크롤 복원
- 결정 성공·undo·next UI
- 관련 단위/API/컴포넌트/브라우저 검증

### 제외

- DB migration, 기존 RPC 변경
- 자동 다음 이동, bulk 분류, 키보드 단축키
- legacy 큐, 튜토리얼, GT/VLM 계약 변경
- Python Evidence, behavior/activity 데이터 변경
- 기존 triage/event/session 데이터 보정

키보드 단축키와 bulk 분류는 연속 검수 흐름이 안정된 뒤 별도 UX 작업으로 평가한다.

## 9. 수용 기준

1. owner `/labeling/motion` 기본 탭은 미분류다.
2. `전체 영상`은 `state=all`로 유지되고 모든 상태를 볼 수 있다.
3. 보류·제외 후 URL과 상세 화면이 그대로 유지된다.
4. 결정 취소가 직전 상태로 복구된다.
5. hold/skip에서는 GT 폼이 렌더되지 않고 DB guard도 유지된다.
6. 다음 영상은 현재 카메라·날짜·미디어 필터를 유지한다.
7. 같은 timestamp에서도 중복·누락이 없다.
8. 목록 복귀 시 탭·필터·스크롤이 복원된다.
9. 다음 영상이 없으면 완료 안내가 표시된다.
10. label 상태에서 지금 GT 작성과 다음 영상 이동을 모두 선택할 수 있다.
11. labeler·legacy·tutorial·VLM·GT 저장 계약 회귀가 없다.
12. preview 연속 10건과 production reversible canary가 통과한다.

## 10. 배포와 rollback

1. feature branch에서 TDD와 전체 web/Python 회귀를 통과한다.
2. preview에서 owner가 연속 10건을 처리하되 테스트 clip은 종료 시 원상복구한다.
3. main을 FF-only로 통합하고 Vercel production을 배포한다.
4. production test-camera clip 1건으로 `제외 → 결정 취소`, 1건으로 `보류 → 다음 미분류`를 확인하고 canary 분류는 `reset`한다.
5. 결함이 있으면 Vercel을 직전 Ready deployment로 rollback하고 feature commit을 revert한다. DB rollback은 필요 없다.
