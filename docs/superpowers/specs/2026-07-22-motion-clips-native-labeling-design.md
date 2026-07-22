# `motion_clips` 네이티브 운영 라벨링 v3 설계

> **상태:** owner 설계 승인 / 구현계획 작성 전 문서 검토
>
> **작성일:** 2026-07-22
>
> **기준 commit:** `petcam-lab` `origin/main` `e2d3920e3c098b97edd3f17657ab2ba127ed6a62`
>
> **격리 작업 경계:** 진행 중인 `local-vlm-evidence-web-gt` worktree와 파일·브랜치를 공유하지 않는다.

## 1. 결론

일반 운영 라벨링의 신규 영상 정본을 legacy `camera_clips`에서 production `motion_clips`로 전환한다.
기존 튜토리얼·과거 행동 GT·Local VLM Evidence GT 연구는 그대로 보존하고, 운영 라벨링에만 독립적인
v3 API와 DB 계약을 추가한다.

owner는 별도 승인 없이 모든 `motion_clips`를 조회·재생·직접 라벨링할 수 있다. owner의 `label` 결정은
일반 라벨러에게 영상을 보내는 동작이며, owner 자신의 접근을 여는 승인 절차가 아니다.

## 2. 확인된 문제와 live 근거

2026-07-22 SELECT-only 진단에서 다음을 확인했다.

- 현재 `/api/labeling-v2/queue`는 `camera_clips`만 읽는다.
- `camera_clips.started_at` 최신값은 2026-07-08 KST 부근에서 멈췄다.
- `motion_clips`는 2026-07-22에도 계속 유입되고 있다.
- 최근 3일 URL의 KST 범위는 올바르게 생성됐지만 조회 정본이 낡아 큐가 0건이었다.
- 2026-07-21 16:30~17:30 KST에 2번 카메라 영상 41건이 존재하고 41건 모두 R2 재생 가능하다.
- 3번 카메라는 2026-07-21 15:14 이후 2026-07-22 07:16까지 수집 공백이라 17시 원본이 없다.
- 세 테스트 카메라는 product owner와 분리된 테스트 계정 소유다.
- 기존 v2 queue의 `owner -> camera_clips.user_id = owner` 조건과 legacy 카메라 옵션 API는 product owner의
  전체 운영 카메라 접근 요구와 맞지 않는다.
- 최신순 정렬 자체는 이미 production에서 `(started_at DESC, id DESC)`로 구현·검증됐다. 문제는 정렬
  대상이 낡은 테이블이라는 점이다.

## 3. 목표와 비목표

### 3.1 목표

1. owner가 모든 운영 영상을 최신 촬영순으로 본다.
2. owner가 카메라·날짜·시간·분류 상태로 원하는 영상을 찾는다.
3. owner는 어떤 영상이든 즉시 직접 라벨링할 수 있다.
4. owner가 `라벨 대상 | 보류 | 제외`를 결정한다.
5. 일반 라벨러는 `라벨 대상` 영상만 본다.
6. 행동 GT는 VLM·Python Evidence·Gate 결과를 보기 전에 잠근다.
7. legacy 튜토리얼과 과거 GT를 변경하지 않는다.
8. `motion_clips -> camera_clips` 복사·미러 없이 운영한다.

### 3.2 비목표

- Python Evidence나 detector로 영상을 자동 제외하지 않는다.
- VLM 결과를 사람 GT로 변환하지 않는다.
- Local VLM Evidence GT 180건 연구 화면·manifest·annotation을 재사용하지 않는다.
- 원본 영상 삭제·R2 보존정책 변경을 하지 않는다.
- Flutter 활동시간·야간 리포트·VLM selector를 변경하지 않는다.
- 기존 `camera_clips` GT를 일괄 변환하거나 삭제하지 않는다.

## 4. 접근 비교와 결정

### A. `motion_clips`를 `camera_clips`로 계속 미러 — 기각

기존 v2를 즉시 재사용할 수 있지만 신규 영상마다 동기화가 필요하고, 소유 계정·R2 key·삭제 상태가
갈라진다. 이미 발생한 두 정본 문제를 영구화하므로 사용하지 않는다.

### B. 기존 v2·튜토리얼·GT FK를 한 번에 `motion_clips`로 교체 — 기각

최종 구조는 단순해 보이지만 활성 튜토리얼과 과거 감사기록까지 동시에 이주해야 한다. 사용자에게 필요한
운영 영상 라벨링보다 위험과 범위가 크다.

### C. 운영 라벨링만 `motion_clips` 네이티브 v3로 추가 — 채택

새 운영 큐·미디어·세션·감사기록만 `motion_clips`를 사용한다. 기존 v2와 튜토리얼은 legacy archive로
유지한다. 충분히 검증한 뒤 `/labeling`의 기본 소비자를 v3로 전환한다.

## 5. 사용자 체험 설계

### 5.1 owner — 전체 영상 찾기

1. **[화면]** `/labeling`에 `전체 영상`, `라벨 대기`, `보류`, `제외` 탭이 보인다. 기본 탭은
   `전체 영상`, 기본 정렬은 최신 촬영순이다.
2. **[조작]** owner가 2번 카메라, 2026-07-21, 16:30~17:30을 선택한다.
3. **[반응]** 해당 구간 41건이 `(started_at DESC, id DESC)` 순서로 나타난다.
4. **[감정]** DB 테이블이나 clip ID를 몰라도 실제 사건 시각으로 영상을 찾을 수 있다.

`최근 3일`, `최근 7일`, 날짜 직접 선택, 전체 기간을 제공한다. 카메라 옵션은 product owner 소유 여부가
아니라 production `cameras` 전체에서 만든다.

### 5.2 owner — 직접 라벨링

1. **[화면]** 영상을 열면 촬영시각·카메라·재생 영상과 사람 판정 폼만 보인다.
2. **[조작]** owner가 미분류 영상에서 바로 GT를 작성한다. 사전 `label` 승인은 요구하지 않는다.
3. **[반응]** 첫 저장 시 해당 clip은 원자적으로 `label` 상태가 되고 blind GT가 잠긴다.
4. **[반응]** VLM 성공 결과가 있으면 잠근 뒤에만 비교 화면이 열린다. 없으면 `AI 판정 없음`으로 완료한다.
5. **[감정]** 팀 큐 정리와 자신의 라벨링을 별도 절차로 반복하지 않는다.

### 5.3 owner — 팀 큐 분류

1. **[조작]** 목록 또는 상세에서 `라벨 대상으로 보내기`, `보류`, `제외` 중 하나를 선택한다.
2. **[반응]** 상태와 actor·시각·사유가 감사 이벤트에 기록된다.
3. **[반응]** `보류`·`제외` 영상도 owner의 전체 영상과 해당 상태 탭에서 계속 재생할 수 있다.
4. **[조작]** owner는 결정을 초기화하거나 다른 상태로 바꿀 수 있다.

이미 누군가 라벨링을 시작한 영상은 `제외`로 바꿀 수 없다. `보류`는 신규 배정을 막되 기존 세션은
보존한다.

### 5.4 일반 라벨러

1. **[화면]** 일반 라벨러는 `라벨 대기`만 본다.
2. **[반응]** owner 결정이 `label`이고 R2 원본이 재생 가능하며 본인이 완료하지 않은 영상만 나온다.
3. **[금지]** `전체 영상`, `보류`, `제외`, owner 결정·감사기록, Python Evidence, Gate, VLM 결과는
   GT 잠금 전에 보이지 않는다.

### 5.5 재생 불가 영상

owner의 `전체 영상`에는 `r2_key`가 없거나 signed URL 발급이 실패한 clip도 숨기지 않는다. 카드에
`원본 재생 불가` 상태와 재시도 버튼을 표시하고 라벨링·팀 전송 버튼을 비활성화한다. 일반 라벨러 큐에는
노출하지 않는다.

## 6. 정보구조와 라우트

### 6.1 페이지

- `/labeling` — 역할에 따라 v3 owner 전체 영상 또는 일반 라벨 대기
- `/labeling/[clipId]` — v3 `motion_clips` 상세·GT·VLM 검수
- `/labeling/legacy` — owner 전용 과거 `camera_clips` 큐·세션 진입점
- `/labeling/tutorial/**` — 현행 유지
- `/labeling/evidence/**` — Local VLM 연구가 구현될 경우 별도 유지

URL만으로 source를 추측하지 않는다. v3 상세 API는 `motion_clips`만 조회하고, legacy 화면은 v2 API만
사용한다.

### 6.2 API namespace

- `GET /api/labeling-v3/queue`
- `GET /api/labeling-v3/cameras`
- `GET /api/labeling-v3/[clipId]`
- `GET /api/labeling-v3/[clipId]/file/url`
- `POST /api/labeling-v3/[clipId]/decision`
- `POST /api/labeling-v3/[clipId]/gt`
- `POST /api/labeling-v3/[clipId]/vlm-review`
- `POST /api/labeling-v3/[clipId]/revise` — owner만

v2 endpoint는 제거하지 않는다. v3에서 v2의 `camera_clips` permission helper를 재사용하지 않는다.

## 7. 데이터 모델

### 7.1 `motion_clip_labeling_triage`

`motion_clips`의 현재 제품 라우팅 상태다. row가 없으면 `unreviewed`다.

- `clip_id uuid primary key references motion_clips(id) on delete restrict`
- `owner_decision text null`: `label | hold | skip`
- `decided_by uuid null`
- `decided_at timestamptz null`
- `decision_note text null`
- `created_at`, `updated_at`

owner 결정이 null이면 결정 메타도 null이어야 한다. `label`만 일반 라벨러 큐에 포함한다.

### 7.2 `motion_clip_labeling_triage_events`

append-only 감사기록이다.

- `event_type`: `owner_labeled | owner_held | owner_skipped | owner_reset | owner_started_labeling`
- `clip_id`, `actor_id`, `before_state`, `after_state`, `reason`, `created_at`

UPDATE·DELETE·TRUNCATE를 trigger로 차단한다. 시스템 suggestion/evidence는 v1 범위에 넣지 않는다.

### 7.3 `motion_clip_labeling_sessions`

현행 `clip_labeling_sessions`의 blind GT 계약을 `motion_clips` FK로 분리 구현한다.

- unique `(clip_id, reviewed_by)`
- `stage`: `draft | gt_locked | completed`
- `initial_gt`: 최초 저장 뒤 불변
- `current_gt`: owner revision으로만 변경 가능
- `prediction_snapshot`: GT 잠금 시 서버가 최신 성공 `clip_vlm_jobs.result`를 복사
- `vlm_verdict`, `vlm_error_tags`, `vlm_review_note`, `completion_reason`
- lock·complete·revision 시각

클라이언트는 `prediction_snapshot`, reviewer, stage를 제출하지 않는다. VLM 결과가 없으면
`completion_reason=no_prediction`으로 완료할 수 있다.

### 7.4 `motion_clip_labeling_session_revisions`

owner의 완료 후 보정 감사기록이다. before/after GT·사유·actor·시각을 append-only로 남긴다.

### 7.5 쓰기 원칙

- 모든 상태 전환은 service-role 전용 RPC 한 트랜잭션으로 처리한다.
- session 시작과 `owner_decision=label` 전환은 원자적이다.
- 기존 session이 있는 clip의 `skip`은 `409 labeling_started`다.
- stale `updated_at` 또는 version은 `409 stale_state`다.
- 신규·기존 `motion_clips`를 미리 enqueue하거나 복사하지 않는다. 목록은 원본 테이블을 직접 읽는다.

## 8. 큐·필터·정렬 계약

### 8.1 owner 전체 영상

owner의 `all` view는 `motion_clips` 전체를 대상으로 한다. `owner_id`로 product owner의 auth ID를
필터링하지 않는다. product owner 인증 자체가 전체 운영 카메라 접근 권한이다.

필터:

- `camera_id`
- `date_from`, `date_to` — RFC3339 offset 포함
- `state`: `unreviewed | label | hold | skip`
- `media`: `ready | unavailable`

### 8.2 일반 라벨 대기

일반 라벨러는 다음을 모두 만족하는 clip만 본다.

- owner decision=`label`
- `r2_key is not null`
- 본인의 completed session 없음
- 현재 다른 상태 전환으로 제외되지 않음

### 8.3 정렬과 cursor

- 정본 정렬: `started_at DESC, id DESC`
- cursor: 원문 RFC3339 timestamp + canonical UUID를 opaque token으로 전달
- DB 마이크로초를 `Date`/`toISOString()`으로 재직렬화하지 않는다.
- client merge도 timestamp 마이크로초를 보존하고 id DESC tie-break를 적용한다.
- 필터 변경·더보기·상세 이동의 stale response는 request generation으로 폐기한다.

현재 production v2에서 검증된 cursor·stale-response helper를 복사하지 않고 공용 순수 모듈로 재사용한다.
Evidence GT 진행 세션이 같은 모듈을 수정 중이면 그 세션 완료 후 통합하고, 동시에 수정하지 않는다.

## 9. 미디어·VLM·blind 계약

- signed URL은 서버가 `motion_clips.r2_key`를 다시 조회해 짧게 발급한다.
- API 응답에 raw `r2_key`, secret, 로컬 경로를 포함하지 않는다.
- owner라도 GT 잠금 전 `clip_vlm_jobs.result`, selection reason, Python Evidence, Gate bbox를 볼 수 없다.
- prediction snapshot은 selector/version을 바꾸지 않고 실제 성공 job payload를 verbatim 보존한다.
- failed/retryable/terminal job은 prediction으로 취급하지 않는다.
- VLM job이 여러 개면 사전 고정된 우선순위와 완료시각 tie-break를 사용한다. 구현계획에서 정확한 SQL을
  동결하고 테스트한다.

## 10. 권한·보안

- product owner = 서버의 `DEV_USER_ID` 일치. owner는 모든 운영 카메라·상태에 접근한다.
- 일반 라벨러 = `labelers` 멤버 + 활성 튜토리얼 완료 또는 면제.
- pending/rejected/외부인은 clip 존재를 드러내지 않는 404를 받는다.
- owner 전용 decision/revise route는 `requireOwner`를 다시 검증한다.
- 신규 테이블은 RLS enabled, anon/authenticated 직접 policy 0, service_role 전용이다.
- RPC는 고정 `search_path`, 허용 enum·길이·JSON 구조·clip/session 관계를 DB에서도 검증한다.
- Supabase 원문 오류·evidence snapshot·모델 reasoning을 클라이언트 오류에 넣지 않는다.
- 카메라 옵션 API도 owner에게 전체 production cameras를 반환하고 일반 라벨러에게는 현재 label 대상에
  존재하는 카메라만 반환한다.

## 11. 기존 기능과 연구 트랙 분리

| 영역 | 정본 | 이번 변경 |
|---|---|---|
| 운영 라벨링 v3 | `motion_clips` | 신규 |
| legacy 라벨링 v2·튜토리얼 | `camera_clips` | 보존 |
| Local VLM Evidence GT | frozen study candidates + `motion_clips` | 별도 연구, 재사용 금지 |
| Universal Python Evidence | `clip_python_evidence_runs` | 읽지 않음 |
| VLM candidate/backfill | `clip_vlm_jobs` | GT 잠금 뒤 snapshot만 |

이번 설계는 B1R/B2 연구 blocker를 우회하거나 연구 후보를 변경하지 않는다. 운영 owner가 영상을 보는
제품 기능과 blind 연구 표본 수집을 같은 큐로 합치지 않는다.

## 12. 오류·경합 처리

- source clip 없음: 404
- R2 원본 없음/서명 실패: owner 카드 상태 표시, 상세 410 또는 일반 502, GT 저장 금지
- 상태 변경 중 session 생성 경합: DB row lock 후 둘 중 하나만 성공
- labeler가 열어둔 사이 owner가 hold/skip: session 미생성이면 저장 409, 이미 생성됐으면 session 보호
- 여러 탭 draft 충돌: optimistic version 불일치 409
- pagination 도중 신규 clip 유입: 기존 cursor보다 최신인 clip은 현재 page 앞에 끼우지 않고 새로고침 후 표시
- DB/RPC 오류: 실패 상태를 성공처럼 표시하지 않고 재시도 가능하게 유지

## 13. 배포 전략과 롤백

### Phase 0 — 구현 격리

- 이 문서 브랜치와 별도 구현 worktree를 사용한다.
- 진행 중 `local-vlm-evidence-web-gt` 세션 완료·push 상태를 확인하기 전 공용 Web 파일을 수정하지 않는다.
- 신규 v3 API·DB·순수 모듈을 먼저 만들고 `/labeling` 전환은 마지막 작은 커밋으로 분리한다.

### Phase 1 — preview

- forward-only migration을 preview에 적용한다.
- 적대 DB probe로 cross-clip/session, stale state, append-only, unauthorized RPC를 검증한다.
- owner/labeler 두 역할 E2E를 수행한다.
- production DB write·대량 seed·mirror는 하지 않는다.

### Phase 2 — production canary

- schema와 v3 API를 배포하되 `/labeling` 기본은 feature flag로 legacy 유지한다.
- owner 전용 숨은 v3 URL에서 카메라 2번의 2026-07-21 16:30~17:30 41건, 최신 clip, 재생 URL을
  SELECT-only 대조한다.
- owner가 canary clip 1건을 직접 라벨링해 session·triage·audit 원자성을 확인한다.

### Phase 3 — 기본 전환

- owner `/labeling`을 v3 all view로 전환한다.
- 일반 라벨러는 초기에는 owner가 명시적으로 label한 소량만 받는다.
- legacy는 `/labeling/legacy`로 유지한다.

### 롤백

- UI/API feature flag를 legacy로 되돌린다.
- 신규 v3 데이터는 삭제하지 않는다.
- trigger나 capture 경로를 건드리지 않으므로 `motion_clips` 수집은 영향받지 않는다.
- migration rollback은 별도 forward migration으로 수행하며 적용된 파일을 수정하지 않는다.

## 14. 검증과 수용 기준

### 자동 테스트

- owner all view가 owner_id와 무관하게 세 카메라를 반환한다.
- labeler는 `label` 외 상태를 절대 받지 않는다.
- `(started_at,id)` keyset 2페이지의 누락·중복 0.
- RFC3339 마이크로초·offset cursor가 verbatim 보존된다.
- 필터 변경 후 늦은 응답이 새 목록을 덮지 않는다.
- owner direct GT가 triage label + session을 한 번에 만든다.
- started session의 skip 경합이 DB에서 차단된다.
- GT 잠금 전 VLM/evidence 필드가 응답에 없다.
- R2 key·DB 원문·secret이 API 오류와 로그에 없다.
- legacy tutorial/v2 회귀가 전부 통과한다.

### production smoke

1. owner가 세 카메라 옵션을 모두 본다.
2. 최근 3일에 실제 `motion_clips`가 표시된다.
3. 첫 카드가 DB의 최신 `motion_clips (started_at,id)`와 일치한다.
4. 2번 카메라 2026-07-21 16:30~17:30이 41건으로 대조된다.
5. 3번 카메라 수집 공백은 0건으로 정직하게 표시된다.
6. 일반 라벨러는 owner가 label한 canary만 본다.
7. `camera_clips` insert/update, behavior label 자동 생성, Evidence GT mutation은 0이다.
8. console error 0, signed URL 재생 성공, Vercel build 성공이다.

## 15. 구현 순서

1. 진행 세션과 base SHA 재대조, 구현 handoff 검증
2. DB migration·RPC·적대 probe
3. v3 server access·queue·camera·media API
4. v3 session/decision/revision API
5. 공용 최신순 cursor·request generation 재사용 경계 정리
6. owner all view와 role별 UI
7. preview owner/labeler E2E
8. production canary
9. `/labeling` 기본 전환
10. SOT·운영 문서 갱신

각 단계는 구현계획에서 RED→GREEN 테스트, 승인 경계, rollback 증거를 파일 단위로 고정한다.

## 16. 완결 조건

- owner가 모든 신규 운영 영상을 승인 없이 최신순으로 볼 수 있다.
- owner가 원하는 시간대 영상을 찾고 직접 GT를 완료할 수 있다.
- 일반 라벨러는 owner가 보낸 영상만 본다.
- 영상 정본·GT FK·media route가 모두 `motion_clips`로 일치한다.
- legacy·tutorial·Evidence GT·Python Evidence·VLM selector가 오염되지 않는다.
- mirror write 0과 role별 권한이 production smoke로 증명된다.
