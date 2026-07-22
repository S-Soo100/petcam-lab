# Motion Labeling v3 제외·보류 GT Guard 설계

## 1. 목적

owner가 운영 영상 상세에서 `제외` 또는 `보류`를 선택한 뒤 같은 화면의 사람 판정을 저장하면, 현재 `fn_lock_motion_clip_gt`가 분류를 다시 `label`로 자동 전환한다. 사용자가 확정한 분류를 GT 저장이 조용히 덮어쓰지 못하게 막는다.

## 2. 확인된 원인

2026-07-22 production 감사 기록에서 최신 6건을 확인했다.

- 5건: `owner_skipped → owner_started_labeling`, 현재 `owner_decision=label`
- 1건: `owner_started_labeling`, 현재 `owner_decision=label`
- `state=skip` 목록은 0건

목록 배지의 표시 오류가 아니다. 상세 화면이 `skip/hold` 이후에도 GT 폼을 활성 상태로 유지하고, owner GT 잠금 RPC가 `label`이 아닌 모든 상태를 `label`로 원자 전환하는 것이 원인이다.

## 3. 사용자 체험

- `[상세 화면]` 사용자가 `제외`를 누른다.
- `[확인]` 기존 확인창에서 제외를 확정한다.
- `[반응]` 저장 성공 직후 `/labeling/motion?state=skip`으로 이동하고 방금 영상이 `제외` 배지로 보인다.
- `[감정]` 결정이 저장됐다는 사실을 즉시 확인하고 다음 영상을 고를 수 있다.

- `[상세 직접 진입]` 제외 또는 보류된 URL을 다시 연다.
- `[반응]` 영상과 분류 버튼은 보이지만 사람 판정 폼은 비활성화되고, `라벨 대상으로 보내기`를 먼저 누르라는 안내가 보인다.
- `[안전]` 오래 열린 탭이나 직접 API 요청이 GT 저장을 시도해도 DB가 409로 거부한다.

## 4. 상태 계약

| 현재 상태 | owner GT 잠금 | labeler GT 잠금 |
|---|---:|---:|
| `unreviewed` | 허용, 기존처럼 원자적으로 `label` 전환 | 거부 |
| `label` | 허용 | 허용 |
| `hold` | 거부 | 거부 |
| `skip` | 거부 | 거부 |

`hold/skip`을 다시 라벨링하려면 owner가 먼저 `라벨 대상으로 보내기`를 눌러 명시적으로 `label`로 바꿔야 한다.

## 5. 구현 경계

### 5.1 Client

- `canWriteMotionGt(state)` 순수 규칙을 공유 계약에 추가한다.
- `hold/skip`에서는 GT fieldset과 저장 버튼을 비활성화한다.
- 안내문을 노출한다: `보류/제외 상태에서는 사람 판정을 저장할 수 없어. 먼저 라벨 대상으로 보내기를 눌러줘.`
- `hold/skip` 결정 성공 직후 각각의 필터 탭으로 이동한다.

### 5.2 API와 DB

- 기존 `2026-07-22_motion_clip_labeling_v3.sql`은 수정하지 않는다.
- forward-only migration `2026-07-22_motion_clip_gt_decision_guard.sql`에서 `fn_lock_motion_clip_gt`를 `CREATE OR REPLACE`한다.
- 기존 lock 순서, media 검증, labeler 권한, initial GT 불변, prediction snapshot, session upsert 계약을 그대로 보존한다.
- owner이고 기존 triage가 `hold/skip`이면 세션 쓰기 전에 `PT424 decision_blocks_labeling`을 발생시킨다.
- API는 PT424를 `409`, 공개 code `decision_blocks_labeling`으로 매핑하고 DB 원문은 노출하지 않는다.

## 6. 기존 데이터

진단 대상 6건과 기존 session/GT/triage/event를 자동 변경하지 않는다. 이미 생성된 session이 있는 영상을 `skip`으로 바꾸는 정책은 이번 결함 수정 범위 밖이다. 필요하면 별도 제품 결정을 거쳐 새 migration/RPC로 다룬다.

## 7. 테스트와 수용 기준

- 순수 규칙: `unreviewed/label=true`, `hold/skip=false`.
- UI: `hold/skip`이면 GT 작성이 비활성화되고 결정 성공 후 해당 탭 경로가 선택된다.
- API: PT424가 409와 안정 code로 매핑된다.
- DB rollback probe:
  - `skip → GT lock`과 `hold → GT lock`은 PT424, session/event 추가 0.
  - `unreviewed owner → GT lock`은 기존처럼 label+gt_locked.
  - `label owner/labeler → GT lock` 정상.
  - initial GT, append-only, 권한·RLS 회귀 통과.
- production smoke: 제외한 새 canary 1건이 `state=skip`에 남고 GT 저장이 차단된다.

## 8. 금지 범위

- 기존 6건 재분류·session/GT 삭제·수정
- legacy 라벨링, 튜토리얼, VLM/Python Evidence, activity 데이터 변경
- `LABELING_QUEUE_SOURCE` 기본값 전환
- 원본 migration 수정, force push, 파괴적 git
