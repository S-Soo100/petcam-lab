# 라벨링 후보 격리함 설계

> 상태: **코드 구현·H7 하드닝 완료 / production migration 적용·rollback probe 통과**(worker 미실행 / 격리 데이터 0).
>   migration `migrations/2026-07-15_labeling_triage.sql` + 실행권한 후속
>   `migrations/2026-07-15_labeling_triage_guard_execute_revoke.sql`, 구현 계획
>   `docs/superpowers/plans/2026-07-15-labeling-triage-quarantine.md`.
>   다음은 §11의 web 배포·owner/labeler E2E → worker preview 30 → canary → backfill 순서다.
> 작성일: 2026-07-15
> 대상: `petcam-lab` Web/DB/API + `petcam-nightly-reporter` 제안 worker

## 1. 목적

영상이 빠르게 쌓이는 상황에서 모든 클립을 같은 우선순위로 사람에게 보여주지 않는다. 시스템이 라벨링 가치가 낮아 보이는 영상을 별도 격리함으로 보내고, owner가 영상을 직접 확인한 뒤 다음 중 하나를 결정한다.

- 라벨링으로 보냄
- 라벨링 안 함
- 아직 결정하지 않고 나중에 봄

이 기능은 영상을 삭제하거나 자동으로 GT를 만드는 기능이 아니다. 사람의 라벨링 시간을 어디에 먼저 쓸지 정리하는 작업 큐다.

## 2. 확인된 현재 상태

- 일반 라벨링 큐의 정본은 `camera_clips`다.
- 현재 Gate/activity shadow 데이터의 정본은 `motion_clips`다.
- 라이브 DB 감사 시 라벨링 가능 `camera_clips`와 activity assessment가 있는 `motion_clips` 사이 ID 겹침은 0건이었다.
- 따라서 기존 `clip_activity_assessments`를 라벨링 큐에 직접 조인하면 안 된다.
- 라벨링용 `camera_clips`를 직접 읽고 Gate evidence를 새로 계산하는 별도 제안 worker가 필요하다.

## 3. 제품 원칙

1. **자동 삭제 없음**: 시스템은 격리를 제안할 뿐 영상과 메타데이터를 삭제하지 않는다.
2. **사람 결정 우선**: owner의 `label` 또는 `skip` 결정은 이후 시스템 제안보다 항상 우선한다.
3. **모르면 본 큐 유지**: 미분석, 오류, `unknown`은 라벨링 큐에 남긴다.
4. **이미 시작한 작업 보호**: 라벨링 세션이 하나라도 생긴 클립은 시스템이 자동 격리하지 못한다.
5. **연구 트랙 분리**: Gate는 evidence sensor이고, 제품 라우팅과 격리 정책은 nightly worker와 labeling DB가 담당한다.
6. **감사 가능성**: 현재 상태뿐 아니라 누가 언제 어떤 이유로 바꿨는지 append-only 이벤트로 남긴다.

## 4. 사용자 체험 설계

### 4.1 라벨러

1. `[화면]` 기존 라벨링 큐에 바로 검수할 영상만 보인다.
2. `[조작]` 날짜를 고르고 영상을 연다.
3. `[반응]` 기존 GT → VLM 검수 흐름은 그대로 동작한다.
4. `[감정]` 명백히 비어 있거나 정적인 영상이 줄어들어 실제 행동 영상에 집중할 수 있다.

라벨러는 격리함 메뉴, 시스템 evidence, owner 결정 기능을 볼 수 없다.

### 4.2 owner의 격리함 검토

1. `[화면]` `/labeling/quarantine`에 `검토 필요`, `라벨링 안 함`, `라벨링으로 보냄` 탭과 각 건수가 보인다.
2. `[조작]` `검토 필요` 영상을 연다.
3. `[반응]` 영상, 촬영 시각, 카메라, 쉬운 한국어 사유가 표시된다. 내부 threshold나 raw detector payload는 기본 화면에 노출하지 않는다.
4. `[조작]` 다음 중 하나를 누른다.
   - `라벨링으로 보내기`
   - `라벨링 안 함`
   - `나중에 보기`
5. `[반응]` 결정 저장 후 다음 미결정 영상으로 자동 이동한다. `나중에 보기`는 상태를 바꾸지 않고 다음 영상으로 이동한다.
6. `[감정]` 삭제 위험 없이 빠르게 후보를 분류하고, 잘못 분류한 건 언제든 되돌릴 수 있다.

### 4.3 되돌리기

1. `[화면]` owner가 `라벨링 안 함` 또는 `라벨링으로 보냄` 탭을 연다.
2. `[조작]` 영상을 열고 `결정 초기화`를 누른다.
3. `[반응]` owner 결정이 제거되고 현재 시스템 제안이 다시 적용된다.
4. `[감정]` 영구 삭제가 아니라 감사 가능한 큐 이동임을 확신할 수 있다.

## 5. 상태 모델

### 5.1 입력 상태

- 시스템 제안: `label | quarantine`
- owner 결정: `label | skip | null`
- 기존 라벨링 세션 존재 여부

### 5.2 유효 상태 우선순위

| 조건 | 유효 상태 | 본 라벨링 큐 | 격리함 탭 |
|---|---|---:|---|
| owner 결정=`label` | 라벨링으로 보냄 | 포함 | `라벨링으로 보냄` |
| owner 결정=`skip` | 라벨링 안 함 | 제외 | `라벨링 안 함` |
| owner 결정 없음 + 시스템=`quarantine` | 검토 필요 | 제외 | `검토 필요` |
| owner 결정 없음 + 시스템=`label` | 라벨링 | 포함 | 없음 |
| triage row 없음 | 라벨링 | 포함 | 없음 |
| 분석 실패/unknown | 라벨링 | 포함 | 없음 |

owner 결정이 항상 최상위다. `reset`은 owner 결정만 제거하며 시스템 evidence와 제안은 보존한다.

### 5.3 `라벨링 안 함`의 의미

- 모든 팀원의 일반 라벨링 큐에서 기한 없이 제외한다.
- 원본 영상, `camera_clips`, triage 상태, 감사 이벤트는 보존한다.
- owner는 언제든 `라벨링으로 보내기` 또는 `결정 초기화`로 복구할 수 있다.
- 기존 라벨링 세션이 있으면 `skip`은 `409 labeling_started`로 거부한다.

## 6. 데이터 설계

### 6.1 `clip_labeling_triage`

현재 라우팅 상태를 빠르게 읽기 위한 테이블이다.

| 컬럼 | 계약 |
|---|---|
| `clip_id uuid primary key` | `camera_clips(id)` FK |
| `suggested_route text` | `label | quarantine` |
| `suggestion_reason text` | `gate_active | gate_absent | gate_static | manual` |
| `suggestion_source text` | 예: `gate_activity_policy` 또는 `owner_manual` |
| `policy_version text` | 판정 정책 버전 |
| `evidence_snapshot jsonb` | 판정 당시의 최소 evidence와 provenance |
| `owner_decision text null` | `label | skip | null` |
| `decided_by uuid null` | owner 사용자 ID |
| `decided_at timestamptz null` | 결정 시각 |
| `decision_note text null` | 선택 메모, 길이 제한 |
| `created_at timestamptz` | 생성 시각 |
| `updated_at timestamptz` | optimistic concurrency 기준 |

제약:

- enum 성격 컬럼은 CHECK로 허용값을 제한한다.
- `owner_decision is null`이면 `decided_by/decided_at`도 null이어야 한다.
- evidence에는 비밀값, 전체 로컬 경로, 인증 정보, 원본 CLI 출력이 들어가면 안 된다.
- `clip_id`, 유효 상태, `updated_at` 조회에 필요한 인덱스를 둔다.

### 6.2 `clip_labeling_triage_events`

상태 변경 이력을 보존하는 append-only 테이블이다.

- `id bigint generated always as identity`
- `clip_id uuid` — append-only 감사기록이 원본 영상 삭제 뒤에도 남도록 의도적으로 FK를 두지 않는다. 이벤트는 RPC만 생성한다.
- `event_type`: `suggested | owner_labeled | owner_skipped | owner_reset | manual_quarantined`
- `actor_type`: `system | owner`
- `actor_id uuid null`
- `before_state jsonb`
- `after_state jsonb`
- `reason text null`
- `created_at timestamptz`

UPDATE, DELETE, TRUNCATE를 트리거로 차단한다. 단순 REVOKE에만 의존하지 않는다.

### 6.3 RPC

상태 row와 이벤트 row는 한 트랜잭션에서 함께 기록한다.

1. `fn_upsert_clip_labeling_triage_suggestion(...)`
   - service-role 전용
   - 시스템 evidence 갱신용
   - owner 결정이 있으면 제안만 갱신하고 유효 owner 결정을 덮지 않는다.
   - 라벨링 세션이 있으면 새 `quarantine` 제안을 거부하거나 `label`로 fail-open한다.
2. `fn_decide_clip_labeling_triage(...)`
   - service-role 전용, API에서 owner 인증 후 호출
   - `label | skip | reset`
   - `expected_updated_at`이 다르면 stale `409`
   - `skip` 시 기존 라벨링 세션이 있으면 `409 labeling_started`
3. `fn_manual_quarantine_clip_for_labeling(...)`
   - service-role 전용, owner 인증 후 호출
   - 시스템 evidence 없이 owner가 본 큐에서 격리함으로 옮길 때 사용
   - owner의 명시적 새 동작이므로 기존 `owner_decision`과 결정 메타를 null로 초기화해 `검토 필요`로 이동한다.
   - 기존 세션이 있으면 거부한다.

마이그레이션은 기존 파일을 수정하지 않는 forward-only 신규 파일로 만든다.

## 7. 권한과 보안

- 두 테이블 모두 RLS를 켠다.
- anon/authenticated 클라이언트 직접 write policy는 만들지 않는다.
- API 서버가 bearer 인증과 owner 판정을 수행한 뒤 service-role로 RPC를 호출한다.
- 목록/상세/결정 API 모두 owner-only다.
- 라벨러가 URL을 직접 입력해도 `403`이어야 한다.
- DB 오류는 서버 로그에만 남기고 응답에는 일반화된 `502`를 반환한다.
- UI에는 `게코가 보이지 않을 가능성이 높음`, `움직임이 거의 없을 가능성이 높음`, `owner가 직접 보류함`처럼 사전 정의한 문구만 보여준다.

## 8. API 설계

### 8.1 목록

`GET /api/labeling-triage?state=pending|skipped|labeled&cursor=...&limit=...`

- owner-only
- 촬영일, 카메라 필터 지원
- cursor pagination
- 응답에 영상 썸네일용 ID, 촬영 시각, 카메라, 표시용 reason, `updated_at` 포함
- raw evidence는 기본 목록 응답에서 제외

### 8.2 상세

`GET /api/labeling-triage/[clipId]`

- owner-only
- 현재 상태, 표시용 reason, 최소 provenance, 촬영 정보 반환
- 영상 URL은 기존 인증된 file URL 경로를 재사용한다.

### 8.3 결정

`PATCH /api/labeling-triage/[clipId]`

```json
{
  "decision": "label",
  "expected_updated_at": "2026-07-15T00:00:00Z",
  "note": "선택 메모"
}
```

- decision: `label | skip | reset`
- `200`: 저장 성공
- `400`: body/enum/note 길이 오류
- `401`: 인증 없음
- `403`: owner 아님
- `404`: clip 또는 triage row 없음
- `409 stale_state`: 다른 화면에서 먼저 변경됨
- `409 labeling_started`: 이미 라벨링이 시작됨
- `502`: 일반화된 DB 오류

### 8.4 owner 수동 격리

`POST /api/labeling-triage/[clipId]/quarantine`

본 큐에서 owner가 직접 격리함으로 옮길 때 쓴다. 이미 라벨링이 시작된 영상은 거부한다.

## 9. 일반 라벨링 큐 변경

현재 큐의 카메라·날짜·현재 reviewer 세션 필터 계약은 유지한다.

- 후보 batch를 읽을 때 해당 clip ID의 triage row를 함께 조회한다.
- 유효 상태가 `검토 필요` 또는 `라벨링 안 함`이면 제외한다.
- owner 결정=`label`이면 시스템 제안과 무관하게 포함한다.
- triage 조회 실패 시 큐 전체를 빈 목록으로 위장하지 말고 일반화된 서버 오류를 반환한다.
- 모든 triage ID를 한 번에 메모리에 모아 거대한 `NOT IN` 쿼리를 만들지 않는다.
- 기존 bounded `collectQueuePage` 스캔에서 batch 단위로 session/triage 상태를 적용한다.

## 10. 시스템 제안 worker 경계

worker는 `petcam-nightly-reporter`에 둔다.

- 입력: 라벨링 가능한 `camera_clips`
- 센서: `gecko-vision-gate`의 frame evidence/activity policy
- 출력: `clip_labeling_triage` 시스템 제안과 감사 이벤트
- 금지: GT, `behavior_labels`, `clip_labeling_sessions`, 활동시간 view, 앱 데이터 변경

기존 `motion_clips` activity assessment를 복사하지 않는다. 구체 계약은 `petcam-nightly-reporter/specs/2026-07-15-camera-clips-labeling-triage-worker-design.md`를 따른다.

## 11. 출시 순서

1. DB migration + rollback probe
2. owner API + route tests
3. 격리함 UI + 사용자 체험 테스트
4. 일반 큐 triage 필터 + 회귀 테스트
5. worker read-only preview 30개
6. owner가 30개를 직접 확인하고 오격리율 검토
7. 통과할 때만 제안 write canary
8. 격리함에서 owner E2E
9. 승인 후 제한 backfill

5~9는 각각 별도 승인 경계다. worker launchd와 전체 backfill은 구현 완료만으로 자동 실행하지 않는다.

## 12. 수용 기준

- 라벨러는 격리 후보와 `skip` 영상을 일반 큐에서 볼 수 없다.
- owner `label` 결정은 즉시 일반 큐에 반영된다.
- owner `skip`은 영상과 감사기록을 삭제하지 않는다.
- 기존 세션이 있는 clip에 자동 격리나 skip이 불가능하다.
- 시스템 unknown/error는 일반 큐에 남는다.
- owner 결정 이후 worker가 다시 실행돼도 결정이 유지된다.
- stale 브라우저 탭의 결정은 409로 거부된다.
- 이벤트 UPDATE/DELETE/TRUNCATE가 DB에서 차단된다.
- 라벨링 GT, 앱 활동시간, 원본 영상 수는 이 기능 전후 동일하다.

## 13. 범위 밖

- 영상 자동 삭제
- 격리 영상을 자동 GT로 사용
- Gate 출력으로 행동 정답 생성
- 라벨러별 업무 자동 배분
- Flutter 앱 변경
- 기존 activity-filter 스위치 변경
- Gate v3 학습 또는 detector threshold 재튜닝
