# 그룹 이중 블라인드 라벨링 운영 설계

> 승인된 라벨러 두 명이 담당 카메라의 같은 영상을 독립적으로 판정하고, 불일치 건만 owner가 최종 검수한다.

**상태:** 설계 승인 · 구현 전
**작성:** 2026-07-23
**연관 SOT:** [운영자 라벨링 대시보드](https://github.com/S-Soo100/tera-ai-product-master/blob/main/docs/specs/petcam-labeling-dashboard.md), [AI 파이프라인](https://github.com/S-Soo100/tera-ai-product-master/blob/main/docs/specs/petcam-ai-pipeline.md), `../../../specs/feature-rba-data-engine-v1.md`
**기존 기반:** `2026-07-22-motion-clips-native-labeling-design.md`

## 1. 목적

현재 `motion_clips` 운영 라벨링 v3는 owner가 먼저 `label`로 분류한 영상만 일반 라벨러에게 보여준다. 이 구조에서는 owner가 모든 영상의 1차 분류를 떠안고, 한 사람의 판정이 곧 정답처럼 굳는다.

이번 변경은 다음을 동시에 달성한다.

1. 담당 카메라의 원본 영상을 승인 라벨러에게 직접 분배한다.
2. 같은 영상을 두 사람이 서로의 답을 보지 않고 독립 판정한다.
3. 두 답이 일치하면 자동 합의하고, 불일치한 영상만 owner에게 보낸다.
4. 매일 닫힌 활동일(`07:00~다음 날 07:00 KST`)부터 처리해 30일 보존창 안에서 backlog를 최신순으로 줄인다.
5. 처음 접속한 사람도 별도 구두 설명 없이 작업할 수 있게 한다.

이는 Phase 1 운영자 라벨링 확대, 사람 blind GT 축적, owner 검수 부담 축소라는 제품 SOT와 정합한다.

## 2. 확정된 운영 배정

초기 운영 배정은 다음과 같다.

| 그룹 | 구성 | 담당 카메라 |
|---|---|---|
| A | 크랑이아빠 + owner가 운영 적용 시 지정하는 A2 계정 | `P4 Cam (dev)` |
| B | owner가 운영 적용 시 지정하는 B1·B2 계정 | `P4 Cam 2(dev)`, `P4 Cam 3` |
| owner 전용 | product owner | `P4 Cam 4` 및 전체 감사 |

개인 이메일이나 auth UUID는 migration·소스·tracked 문서에 하드코딩하지 않는다. A2·B1·B2의 실제 계정 매핑은 production 적용 gate의 필수 owner 입력이며, server-side 관리 RPC가 `approved` 상태를 확인한 뒤 auth UUID로 저장한다. 적용 결과는 비밀값 없는 운영 보고서에 그룹별 인원 수와 display name만 남긴다.

초기 버전에서 활성 그룹은 정확히 두 명으로 구성하고, 하나의 카메라는 동시에 하나의 활성 그룹에만 속한다. owner는 그룹원이 아니며 모든 그룹을 감사·재배정할 수 있다.

## 3. 용어와 완료 정의

### 3.1 활동일

`activity_day_kst`는 다음 식으로 정한다.

```text
(started_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date
```

따라서 `2026-07-22` 활동일은 `2026-07-22 07:00 KST` 이상, `2026-07-23 07:00 KST` 미만이다.

- 기본 작업일: 현재 활동일 직전의 완전히 닫힌 활동일
- 날짜 진행: 기본 작업일을 끝낸 뒤 하루 전 활동일을 순차 개방
- 정렬: 활동일 안에서는 `(started_at DESC, id DESC)` 최신순

### 3.2 라벨러 한 명의 제출 완료

영상 하나에 대해 다음 중 하나를 최초 제출하면 그 라벨러의 작업이 완료된다.

- `exclude`: 게코 부재, 촬영 오류, 재생 불가 등 행동 데이터로 쓸 수 없음
- `hold`: 영상이 애매하거나 owner 판단이 필요함
- `label`: 최초 사람 GT(`initial_gt`) 저장 완료

`label` 버튼만 누르고 GT를 저장하지 않은 상태는 완료가 아니다. AI/VLM을 본 뒤의 수정값은 이중 블라인드 합의에 사용하지 않는다.

### 3.3 그룹 합의 완료

한 영상에 배정된 두 review slot 모두 최초 제출된 뒤 자동 비교한다.

- 일치: 자동 합의 완료
- 불일치: owner 검수 대기

Owner 검수가 밀려도 라벨러의 다음 날짜 진행은 막지 않는다. 라벨러의 날짜 완료는 자기 review slot을 모두 제출했는지로 판단하고, 그룹 완료는 두 사람의 slot이 모두 제출됐는지로 판단한다.

## 4. 사용자 체험 설계

### 4.1 첫 접속

`[화면]` 상단에 그룹·담당 카메라·우선 활동일·진행률이 보인다.

```text
A그룹 · P4 Cam (dev)
우선 작업: 7월 22일 07:00 ~ 7월 23일 07:00
내 작업 34/100 · 파트너 28/100
그룹 합의 22 · 불일치 4 · 비교 대기 74
```

`[조작]` 처음 접속한 사용자는 1분 안내를 읽고 `작업 시작`을 누른다.

`[반응]` 다음 세 문장을 보여주며 언제든 `작업 방법`으로 다시 열 수 있다.

> 같은 영상을 두 사람이 따로 확인해.
>
> 라벨러 화면에는 상대방의 답이 보이지 않아.
>
> 두 답이 같으면 자동 완료되고, 다르면 관리자가 확인해.

`[감정]` 사용자는 왜 같은 영상을 다시 보는지, 무엇을 끝내야 하는지 바로 이해한다.

### 4.2 영상 판정

영상 위에 세 개의 큰 선택지를 설명과 함께 보여준다.

| 버튼 | 사용자 안내 |
|---|---|
| `라벨링하기` | 게코의 의미 있는 행동이 보여서 행동과 시간을 기록해야 해 |
| `보류하기` | 영상이 애매해 지금은 확정 행동 라벨을 만들기 어려워 |
| `제외하기` | 게코가 없거나 촬영·재생 오류라 행동 데이터로 쓸 수 없어 |

`보류`와 `제외`는 최종 제출 확인을 거친다. `라벨링하기`는 기존 GT 폼으로 이동하고 최초 사람 판정을 저장해야 완료된다.

제출 후에는 `내 판정이 저장됐어 · 상대 판정 대기 중` 또는 `두 판정 비교 완료`만 보여준다. 상대방의 실제 선택은 라벨러에게 노출하지 않는다.

### 4.3 개인 진행과 그룹 진행

- 개인: 자기 어제분을 모두 제출하면 그 전날 하루가 열린다.
- 그룹: 두 사람 모두 어제분을 제출하면 `그룹 어제 작업 완료`가 표시된다.
- 빠른 라벨러는 파트너를 기다리지 않고 자기 과거 작업을 계속한다.
- 뒤늦게 유입된 어제 영상은 `어제 추가 N건`으로 최우선 표시한다.
- 늦은 유입은 이미 개방된 과거 날짜를 다시 잠그지 않는다.

### 4.4 팀 진행 현황

라벨러에게 다음을 보여준다.

- 현재 우선 활동일의 전체 clip 수와 자기 제출 수
- 파트너 제출 수
- 합의 완료·불일치·비교 대기 clip 수
- 현재 활동일 07:00 이후 각 멤버가 제출한 고유 clip 수
- 그룹 전체의 비교 상태 집계만 표시하고, 멤버별 `라벨 / 보류 / 제외` 분포는 라벨러에게 숨긴다.

취소·재시도·버튼 클릭 횟수가 아니라 최초 제출이 존재하는 고유 review slot만 센다. 이름은 `display_name`을 우선하고, 없을 때만 마스킹한 이메일을 쓴다.

### 4.5 Owner 불일치 검수

Owner 기본 검수함에는 불일치 영상만 나온다.

```text
영상
├─ 라벨러 A 최초 판정
├─ 라벨러 B 최초 판정
├─ 서로 다른 필드 강조
├─ 각자 메모
└─ owner 최종 판정: A 채택 / B 채택 / 새 판정
```

Owner가 최종 판정을 제출하면 판정과 사유를 append-only 이력으로 남긴다. 자동 합의 영상은 기본 큐에서 제외하지만 owner 감사 화면에서 언제든 조회할 수 있다.

## 5. 블라인드·비교 계약

### 5.1 블라인드

각 라벨러는 제출 전후 모두 상대방의 다음 정보를 받지 않는다.

- triage 결정
- GT·시간 구간
- 메모
- 현재 어떤 영상을 열었는지
- 제출 시각

진행 현황 API는 집계 숫자만 반환한다. 상세·목록·오류 응답에도 상대 제출 JSON, 비교 hash, 내부 auth UUID를 넣지 않는다. Owner API만 두 제출을 함께 읽을 수 있다.

### 5.2 결정론적 일치 규칙

비교 대상은 두 사람의 immutable 최초 제출이다. 비교 버전을 결과에 저장한다.

1. `exclude | hold | label`이 다르면 불일치
2. 둘 다 `exclude` 또는 둘 다 `hold`면 일치
3. 둘 다 `label`이면:
   - enum과 scalar 필드는 exact match
   - 배열은 중복 제거 후 canonical sort하여 집합 비교
   - segment 수와 대응 행동이 같아야 함
   - segment 시작·끝은 정수 millisecond로 정규화하고 각 경계 차이가 `500ms 이하`면 같음
   - 자유 메모는 비교에서 제외하고 원문 보존

AI/VLM 검수 후 `current_gt`, prediction, evidence는 합의 입력이 아니다.

### 5.3 비교 실행

API 프로세스가 두 제출을 읽어 임의로 상태를 덮지 않는다.

1. 제출 RPC가 review slot과 clip을 잠그고 최초 제출을 immutable 저장한다.
2. 두 번째 제출이 생기면 API의 versioned pure comparator가 결과와 두 submission digest를 만든다.
3. finalize RPC가 두 제출을 다시 잠그고 digest·비교 버전을 검증한 뒤 consensus를 멱등 저장한다.
4. 경합·stale digest면 재조회 후 다시 비교하며, 중복 consensus나 제출 손실을 허용하지 않는다.

## 6. 데이터 경계

기존 `motion_clip_labeling_triage`와 `motion_clip_labeling_sessions`를 개인 blind 제출 저장소로 재사용하지 않는다. 첫 라벨러의 전역 상태가 두 번째 라벨러에게 노출되고 기존 owner 흐름과 충돌하기 때문이다.

새 forward migration은 역할별로 다음 데이터를 분리한다.

| 단위 | 책임 |
|---|---|
| review group | 그룹 이름·활성 상태 |
| group member | 승인 사용자와 그룹의 현재 관계 |
| group camera | 카메라와 활성 그룹 관계 |
| canary cohort | 운영 GT와 격리된 preview 검증 묶음과 open/closed 상태 |
| reviewer progress | 라벨러별 가장 오래 개방된 활동일과 진행 갱신 시각 |
| review slot | clip별 필수 reviewer 두 명의 snapshot + `live/canary` cohort |
| blind submission | reviewer별 immutable 최초 결정·initial GT·메모 |
| consensus | awaiting/agreed/conflict/owner_resolved 현재 상태 |
| consensus event/revision | 자동 비교와 owner 최종 판정 append-only 감사 |
| personal lease | 같은 reviewer의 여러 탭 충돌 방지용 30분 lease |

### 6.1 Assignment snapshot

활동일 clip이 큐에 처음 편입될 때 해당 그룹의 활성 멤버 두 명을 review slot으로 snapshot한다.

- 그룹원 변경은 이미 제출된 slot을 바꾸지 않는다.
- 미제출 slot만 owner 관리 RPC로 새 멤버에게 재배정할 수 있다.
- 새 멤버는 비어 있는 두 번째 판정만 수행한다.
- 단일 제출을 합의 완료로 승격하는 우회는 없다.

### 6.2 기존 v3와의 관계

- 기존 owner 단독 라벨링·튜토리얼·legacy v2 데이터는 수정하지 않는다.
- 이중 블라인드 합의/owner resolution은 새 canonical 결과로 보존한다.
- 기존 triage/session에 투영이 필요한 소비처는 별도 adapter에서 명시적으로 읽으며, 개인 제출을 전역 owner decision으로 조용히 복사하지 않는다.
- 자동 VLM 호출, Python Evidence, Gate, 활동시간 계산은 이번 스코프 밖이다.

### 6.3 Canary 격리

Immutable 사람 제출을 검증 뒤 삭제하는 "가역 canary"는 사용하지 않는다. Review slot에는 `cohort_kind=live|canary`와 `cohort_id`를 저장한다.

- 일반 큐·진행률·GT export는 `live`만 읽는다.
- Owner가 지정한 test clip만 별도 canary cohort에 넣는다.
- Canary 제출·합의도 append-only로 보존하되 운영 GT와 통계에서 제외한다.
- Labeler는 owner가 발급한 canary 진입 링크에서만 자기 canary slot을 본다.
- Canary 종료는 cohort를 `closed`로 바꾸는 것이며 row 삭제가 아니다.

### 6.4 개인 날짜 개방 상태

`reviewer progress`는 `(group_id, reviewer_id)`별 `oldest_unlocked_activity_day`를 영속 저장한다.

- 첫 진입 때 직전의 완전히 닫힌 활동일로 초기화한다.
- 라벨러가 자기 우선 활동일의 live slot을 모두 제출하면 30일 보존창 안에서 하루 전으로 이동한다. clip이 없는 날은 자동 통과한다.
- 이미 더 과거로 이동한 값은 늦은 clip 유입이나 파트너 상태 때문에 앞으로 되돌리지 않는다.
- 늦게 생긴 미제출 slot은 별도 priority로 위에 보여주되 `oldest_unlocked_activity_day`를 바꾸지 않는다.
- 그룹 재배정은 기존 slot/submission과 과거 progress를 보존하고, 새 그룹 progress를 별도 초기화한다.

## 7. API·권한 계약

모든 브라우저 요청은 bearer identity를 서버에서 얻고 body의 user/group 값은 신뢰하지 않는다.

- labeler queue: 자신에게 배정된 review slot과 담당 카메라만
- labeler detail/media: 해당 slot이 존재할 때만
- submit: 자기 미제출 slot에만 한 번
- progress: 자기 그룹의 집계만, 상대 원문 0
- owner conflict: 두 제출이 모두 있고 status가 conflict인 clip만
- owner group admin: approved labeler만 배정, 카메라 중복 배정 차단

테이블은 RLS ON, client 정책 0, service-role RPC 전용으로 유지한다. RPC는 `search_path=''`, 입력 UUID·enum·JSON 구조 검증, row lock, 안정 SQLSTATE, DB 원문 비노출을 지킨다.

개인 이메일·비밀번호·service role·R2 key·raw evidence는 응답과 로그에 남기지 않는다.

상태 변경 요청은 기존 Supabase bearer 인증을 반드시 요구하고 cookie-only 인증으로 처리하지 않는다. 모든 문자열·UUID·날짜·cursor·배열 길이를 allowlist 검증하며, 메모는 최대 2,000자 plain text로만 렌더한다. Lease token과 submission digest는 로그·오류 응답에 남기지 않는다.

## 8. 오류·복구

| 상황 | 동작 |
|---|---|
| 네트워크 단절 | 폼 draft를 로컬에 보존하고 제출 재시도 안내 |
| 같은 사용자의 여러 탭 | personal lease/version mismatch로 한 탭만 제출, 다른 탭은 최신 상태 reload |
| 두 라벨러 동시 제출 | row lock+digest 검증으로 consensus 1건 |
| 미디어 URL 실패 | 재시도 후 `재생 오류` 제출 경로 제공; 일반 게코 부재와 reason 분리 |
| 그룹원 장기 미접속 | owner가 미제출 slot만 다른 approved labeler에게 재배정 |
| 늦은 clip 유입 | 현재 우선 큐에 추가하되 과거 unlock 회수 없음 |
| comparator 오류 | 제출은 보존, consensus는 awaiting 상태, owner/운영 로그에 일반화된 오류 |
| owner 판정 수정 | 원본 resolution 보존 + revision append, overwrite 금지 |

## 9. 접근성·문구 완료 조건

- 모바일 1열, 넓은 화면 2열 이상에서도 주요 CTA와 진행률이 첫 화면에 보인다.
- 상태는 색상만으로 구분하지 않고 텍스트·아이콘을 함께 쓴다.
- 선택 컨트롤은 전체 카드 클릭, `aria-pressed`, 키보드 focus를 지원한다.
- 빈 큐는 `왜 비었는지`와 다음 행동을 말한다.
  - `어제 내 작업을 모두 끝냈어. 그 전날 작업을 시작할 수 있어.`
  - `담당 카메라가 아직 배정되지 않았어. 관리자에게 문의해.`
  - `파트너 제출을 기다리는 중이야. 너는 과거 작업을 계속할 수 있어.`
- 내부 용어 `triage`, `consensus`, `slot`은 사용자 화면에 노출하지 않는다.
- 최초 안내는 다시 열 수 있고, 닫았다는 상태만 사용자별로 저장한다.

## 10. 검증 계획

### 10.1 자동 테스트

- 그룹 활성 멤버 정확히 두 명·카메라 단일 그룹
- 담당 밖 카메라 queue/detail/media/submit 404
- 상대 submission·GT·메모·UUID 응답 누출 0
- 두 reviewer가 같은 clip에 각각 한 번 제출
- 같은 reviewer 중복/다중 탭 제출 차단
- triage 3×3 조합의 agree/conflict
- 배열 순서 무관, 메모 무관
- 시간 경계 `500ms` 일치, `501ms` 불일치
- 동시 두 번째 제출에도 consensus 1건
- 개인 완료 뒤 과거 하루 unlock
- 파트너 미완료가 개인 unlock을 막지 않음
- 늦은 clip이 우선 큐에 추가되지만 unlock을 회수하지 않음
- 처리량은 고유 submission 수이며 undo/retry로 증가하지 않음
- owner는 conflict만 기본 조회, agreed는 감사 조회
- 멤버 교체 시 제출 보존·미제출 slot만 이동
- canary slot/submission이 live 큐·진행률·export에 섞이지 않음
- 기존 owner v3·legacy v2·튜토리얼 회귀

### 10.2 Preview·production canary

Production live mapping 전 preview에서 실제 두 labeler 계정과 owner 계정으로 최소 12개 격리 canary를 수행한다. Canary row는 삭제하지 않고 `cohort_kind=canary`로 운영 GT·진행률·export에서 제외한다.

- agree: exclude 2, hold 2, label+GT 2
- conflict: decision conflict 2, GT field conflict 2, 시간 500/501ms 경계 2
- 상대 답 누출 0
- 독립 comparator recompute 12/12 일치
- owner conflict queue expected==actual
- draft·재시도·다중 탭에서 제출 손실 0

Production 첫 30개는 정상 모드와 별도로 owner가 agreed 결과까지 사후 감사한다. 자동 합의 정확성 문제가 한 건이라도 있으면 자동 합의를 중지하고 두 제출을 보존한 채 owner 전수 검수로 fail-open한다.

## 11. 도입 순서

1. 설계·구현계획 승인
2. forward migration + rollback probe
3. API/순수 comparator TDD
4. 라벨러 queue/detail/progress UX
5. owner conflict/admin UX
6. preview 12-canary
7. main FF-only + production migration/deploy
8. 실제 그룹 UUID 매핑
9. production 첫 30개 감사
10. 통과 후 일반 운영

각 단계는 이전 단계가 통과해야 진행한다. 그룹 mapping, migration apply, production write, deploy는 별도 owner 승인 경계다.

## 12. In / Out

### In

- 두 명 그룹·카메라 배정
- 활동일 우선 개인 큐와 순차 과거 unlock
- 두 개의 immutable blind 제출
- 결정론적 자동 합의와 owner conflict 검수
- 그룹 진행 현황
- 초보자 안내·빈 상태·복구 UX
- API/DB 권한과 감사 이력

### Out

- 세 명 이상 다수결
- 라벨러 성과 순위·보상·경쟁 UI
- VLM·Gate·Python Evidence로 사람 판정 대체
- agreed 결과의 무작위 자동 QA 운영(첫 30개 canary 감사만 수행)
- P4 Cam 4 일반 라벨러 배정
- 기존 GT 삭제·재작성
- 이메일·비밀번호를 소스나 migration에 저장

## 13. 고려한 대안

### A. 그룹 공동 일일 큐 + 개인 순차 unlock — 채택

누락 없이 최신 활동일을 우선하고, 빠른 라벨러가 파트너 때문에 멈추지 않는다. 두 제출 비교가 자연스럽다.

### B. 과거 전체 자유 탐색

구현은 단순하지만 쉬운 영상만 고르는 selection bias와 날짜별 누락이 생긴다.

### C. Owner가 매번 batch 수동 배정

중복은 막기 쉽지만 owner 부담을 줄이려는 목표와 충돌한다.

### D. 한 명 라벨 + 다른 한 명 표본 QA

처리량은 높지만 모든 영상에 독립 판정 두 개를 확보하려는 owner 결정과 다르다.

## 14. 성공 판정

기능 배포만으로 라벨 품질 개선을 주장하지 않는다. 다음을 모두 만족해야 운영 검증 완료다.

- 지정 그룹/카메라 밖 접근 0
- 상대 답 사전 노출 0
- 배정 clip당 서로 다른 reviewer의 최초 제출 정확히 2개
- comparator 독립 재계산 불일치 0
- 제출 유실·중복 consensus 0
- owner 기본 큐가 conflict와 정확히 일치
- 날짜 unlock·진행 수치 오류 0
- 첫 30개 agreed owner 사후 감사에서 자동 합의 오류 0

Owner 부담 절감률은 `conflict clip / double-reviewed clip`로 별도 보고하며 사전 성공 수치로 과장하지 않는다.
