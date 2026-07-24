# 짧은 오류 영상 Visibility-first 운영 재배치 설계

**상태:** Owner 승인 / 구현계획 작성 대상  
**작성일:** 2026-07-25  
**선행 설계:** `2026-07-24-short-clip-device-error-retention-design.md`  
**선행 production 결과:** Phase A 검증 완료, Phase B 경계 위반 후 안전 rollback

## 1. 한 줄 결정

짧은 오류 영상은 R2에서 물리 삭제하지 않는다. `motion_clip_system_exclusions`를 단일 원장으로 삼아
앱·라벨링 웹·신규 분석 소비자에서만 숨기고, 사람의 기존 `owner_decision`은 시스템 격리 해제와
완전히 분리한다.

배포 후 Mac mini 스위치는 정확히 다음 상태다.

```text
SHORT_CLIP_RETENTION_ENABLED=1
SHORT_CLIP_RETENTION_WRITE_ENABLED=1
SHORT_CLIP_RETENTION_DELETE_ENABLED=0
```

`DELETE_ENABLED=0`은 임시 canary가 아니라 이 설계의 운영 정본이다.

## 2. 왜 재배치하나

2026-07-25 production Phase B에서 P4 Cam 2(dev)의 표시 4초·11초 40건을 정확히 격리했지만,
실제 clip을 사용한 복구 canary가 `fn_restore_short_clip_exclusion`의 기존 계약 때문에 사람의
`skip` 판정을 `label`로 덮어썼다. 즉, 자동 제외 결과는 맞았지만 “시스템 격리 해제”와
“사람 판정 변경”을 한 RPC에 묶은 경계가 잘못됐다.

rollback 후 현재 안전 상태는 다음과 같다.

- 검증된 40건은 시스템 `quarantined`이며 기존 사람 판정은 모두 `skip`
- 다른 카메라 자동 격리 0
- worker는 `enabled=1 / write=0 / delete=0`
- R2 delete·delete claim·lease 0
- 시스템 원장 823건과 append-only event 824건은 감사 증거로 보존

물리 삭제는 저장비용 절감보다 오삭제 위험이 크고, 제품 목표는 app/web·분석 비용에서 오류 영상을
제외하는 것이다. 따라서 삭제 파이프라인은 구현을 보존하되 운영에서 사용하지 않는다.

## 3. 접근법 비교

### A. Flutter·웹에서 각각 길이 필터

- 장점: 구현이 단순하다.
- 단점: 카메라별 검증 규칙을 클라이언트마다 복제하고, 직접 URL·활동 집계·백그라운드 소비자가
  누락될 수 있다.
- 판정: 기각.

### B. 앱 전용 목록 RPC로 Flutter 조회 전면 교체

- 장점: 앱 응답을 명시적으로 통제할 수 있다.
- 단점: 목록, 최신 clip, 단건, 활동 집계, 썸네일 등 여러 경로를 함께 교체해야 하며 Flutter의
  미푸시 작업과 충돌한다.
- 판정: 현 단계에서 과도하다.

### C. DB RLS + 웹 소비자 가드 + API 서명 가드

- 장점: `motion_clips` 직접 조회와 `security_invoker` 활동 view가 같은 exclusion 원장을 자동
  상속한다. Flutter 변경 없이 앱 목록·최신 clip·단건·활동시간에서 숨겨진다. 웹은 이미 적용된
  service-role RPC 가드를 유지하고, 직접 media URL은 서버에서 다시 차단한다.
- 단점: RLS helper와 API guard를 적대적으로 검증해야 한다.
- 판정: 채택.

## 4. 사용자 체험

### 앱 사용자

1. `[화면]` 크레캠 영상 목록과 최신 포스터에 장치 오류 clip이 보이지 않는다.
2. `[조작]` 날짜별 영상이나 활동시간 그래프를 연다.
3. `[반응]` 자동 격리 clip은 목록과 활동시간 합계 모두에서 빠진다.
4. `[감정]` 4초·11초 오류 영상이 정상 활동처럼 쌓이지 않는다.

직접 알고 있던 clip URL로 접근해도 서버는 signed URL을 발급하지 않는다. 이미 로컬에 저장한
즐겨찾기 파일은 이번 범위에서 삭제하지 않는다.

### 라벨링 웹 Owner

1. 기본 큐·라이브러리에는 자동 격리 clip이 보이지 않는다.
2. `자동 제외` 화면에서 원장과 사유를 확인할 수 있다.
3. `자동 제외만 해제`를 누르면 시스템 상태만 `restored`로 바뀐다.
4. 기존 사람이 `skip` 또는 `label`로 판정한 값은 그대로 유지된다.
5. 라벨 대상으로 바꾸고 싶으면 영상 상세의 명시적 Owner 판정 기능을 별도로 사용한다.

### 일반 라벨러·분석 worker

- 격리 clip은 신규 라벨 큐, blind slot, VLM job, Python Evidence job에 들어오지 않는다.
- 이미 존재하는 사람 GT·submission·consensus·분석 결과는 수정하거나 삭제하지 않는다.

## 5. 데이터·권한 계약

### 5.1 복구 의미 분리

forward-only migration으로 `fn_restore_short_clip_exclusion`을 교체한다.

복구 RPC가 하는 일:

- lock: `motion_clips → motion_clip_system_exclusions`
- `quarantined` 상태와 delete lease 부재 검증
- exclusion을 `restored`로 전환
- delete deadline/lease 필드 clear
- `owner_restored` append-only event 기록

복구 RPC가 절대 하지 않는 일:

- `motion_clip_labeling_triage` INSERT/UPDATE/DELETE
- `motion_clip_labeling_triage_events` INSERT
- Owner의 `skip/hold/label` 결정 변경
- 라벨링 session·GT·consensus 변경

기존 이름 `fn_restore_short_clip_exclusion`은 API 호환을 위해 유지하지만, UI 문구는
`자동 제외만 해제`로 바꾼다.

### 5.2 앱 가시성 RLS

`SECURITY DEFINER`, `STABLE`, 고정 `search_path=''` helper를 추가한다.

```sql
fn_motion_clip_visible_to_owner(p_clip_id uuid, p_owner_id uuid) returns boolean
```

반환 조건:

- `p_owner_id = auth.uid()`
- 해당 clip의 exclusion 상태가 `quarantined` 또는 `media_deleted`가 아님

기존 `motion_clips` SELECT policy `own clips select`의 owner 조건을 helper 호출로 교체한다.
DELETE policy와 service_role 동작은 바꾸지 않는다. helper는 boolean만 반환하고 raw exclusion,
rule, actor, R2 key를 노출하지 않는다.

이 정책은 Flutter의 다음 직접 조회를 함께 막는다.

- `listByCamera`
- `getById`
- `latestByCamera`
- `latestMotionAt`
- `v_clip_effective_activity` (`security_invoker=on`)

### 5.3 웹과 media URL

기존 라벨링 v3 RPC의 `quarantined/media_deleted` 가드는 유지한다.

서버에서 signed URL을 만들기 직전 exclusion 상태를 다시 조회한다. `quarantined`는 404로
존재를 숨기고 `media_deleted`는 410을 반환한다. 서명 함수 호출은 0회여야 한다. service_role
경로가 RLS를 우회해도 media guard는 우회하지 않는다.

### 5.4 삭제 기능

- migration에 이미 존재하는 delete lease/RPC/table은 감사·호환을 위해 삭제하지 않는다.
- LaunchAgent의 `SHORT_CLIP_RETENTION_DELETE_ENABLED=0`을 유지한다.
- R2 delete canary, delete claim, lease 발급, prefix/list/bulk delete는 실행하지 않는다.
- `delete_after`는 과거 provenance일 뿐 운영 실행 예약으로 해석하지 않는다.

## 6. 오류 처리

- RLS helper가 exclusion 상태를 읽지 못하면 앱 조회를 허용하지 않고 fail-closed한다.
- 복구 중 triage fingerprint가 변하면 transaction을 rollback하고 배포를 중단한다.
- media guard DB 조회가 실패하면 signed URL을 발급하지 않고 502를 반환한다.
- Mac mini에서 host/HEAD/LaunchAgent drift가 있으면 write switch를 올리지 않는다.
- production probe는 합성 row를 transaction 안에서 만들고 전량 rollback한다. 실제 사람 clip으로
  복구 canary를 하지 않는다.

## 7. 검증

### DB runtime probe

합성 Owner/clip/exclusion/triage를 transaction 안에서 생성해 다음을 확인한다.

1. `skip` + quarantined → restore 후 triage fingerprint byte-identical
2. `label` + quarantined → restore 후 triage fingerprint byte-identical
3. triage row 없음 → restore 후에도 triage row 없음
4. exclusion은 restored, event는 정확히 1개 증가
5. lease가 있으면 PT409, 어떤 상태도 변하지 않음
6. authenticated Owner SELECT는 quarantined/media_deleted를 0건으로 봄
7. restored/candidate는 Owner에게 보임
8. 다른 Owner clip은 계속 RLS로 숨김
9. service_role은 운영·감사를 위해 모든 상태를 읽을 수 있음
10. probe residue 0

### 코드 테스트

- migration 정적 계약
- media signer 0회 회귀
- 웹 버튼·안내 문구와 기존 payload 호환
- 전체 Python/Web/TypeScript 회귀
- Vercel build와 Fly API health

### production acceptance

- 기존 사람 triage 전체 fingerprint pre==post
- 현재 40건은 quarantined + 기존 `skip` 유지
- P4 Cam 2(dev) 표시 4/11 외 신규 quarantine 0
- 앱 Owner JWT로 quarantined 목록·단건·활동 view 0
- 웹 기본 큐 0, 자동 제외 화면 40건 노출
- Mac mini `enabled=1/write=1/delete=0`
- 자연 hourly cycle exit 0
- R2 delete/claim/lease 0

## 8. 도입 순서와 rollback

1. forward migration 및 local PG probe
2. backend/web 테스트와 build
3. main FF-only 통합
4. production migration apply + transaction rollback probe
5. Vercel production + Fly API 배포
6. app/web read-only smoke
7. Mac mini write switch만 `1`로 변경, delete는 `0`
8. 1회 canary + 자연 hourly cycle

문제가 생기면:

- 카메라 정책 `enabled=false`
- Mac mini `write=0/delete=0`
- Vercel/Fly 직전 안정 SHA로 rollback
- RLS SELECT policy를 직전 owner-only 정의로 되돌리는 forward migration
- 시스템 원장과 append-only event는 삭제하지 않음

## 9. 범위 밖

- R2 객체 삭제 및 저장비 최적화
- Flutter 코드 수정·배포
- 다른 카메라 정책 자동 확대
- 15초 미만 전역 격리
- 기존 823 candidate의 일괄 재판정
- 사람 GT·라벨·151 frozen set 변경

