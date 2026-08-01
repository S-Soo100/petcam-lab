# 사건 이어짐 v2: Owner 선별 + 연속 경계 검수 설계

**상태:** 사용자 승인 · 구현 기준 동결

**작성일:** 2026-08-01

**대상:** `petcam-lab/web` 라벨링 웹, Supabase 사건 경계 검수 도메인

## 1. 한 줄 결론

서로 떨어진 2개 영상 문제를 바로 두 사람에게 주던 기존 묶음은 닫고, 실제 시간순으로 겹치는
120개 경계(`A-B`, `B-C`, `C-D`)를 Owner가 먼저 유효/무효 선별한 뒤 유효한 경계만 두 사람이
독립 검수한다.

## 2. 왜 다시 만드는가

기존 exact-120은 R2 파일 존재만 확인했고 게코가 실제로 보이는지는 확인하지 않았다. 또한 영상
240개를 한 번씩만 쓰는 독립 pair라 `A-B`와 `B-C`를 이어 3개 이상의 영상을 한 사건으로 묶을 수
없다. 현재 제출과 해결은 모두 0건이므로 사람 답을 잃지 않고 잘못된 cohort를 감사 이력으로 닫을
수 있다.

이번 변경은 영상 부족을 해결하는 작업이 아니다. 이미 쌓인 영상에서 **연속성 연구에 맞는 문제를
다시 만드는 작업**이다. Python Evidence, VLM, 행동 GT는 유효성 정답으로 자동 사용하지 않는다.

## 3. In / Out

### In

- 기존 development source에서 시간순으로 인접한 경계 120개를 결정론적으로 선택
- 같은 카메라·같은 activity day, 미촬영 시간 300초 이하만 인접 경계로 인정
- Owner 전용 1차 자격 검사와 immutable 판정
- 자격 판정: `유효`, `A 게코 없음`, `B 게코 없음`, `둘 다 게코 없음`, `촬영/재생 오류`
- 120개 자격 검사가 끝나면 유효 경계 전체를 Owner와 지정 peer에게 각각 배정
- 유효 경계가 60개 이상이면 boundary phase 자동 개방, 미만이면 fail-closed
- 두 사람 최초 답과 Owner 불일치 해결은 기존 `same/different/uncertain` 계약 재사용
- 기존 잘못된 cohort는 `invalid_eligibility` 상태와 사유로 보존

### Out

- 원본 mp4 파일을 물리적으로 합치거나 삭제하는 일
- 기존 행동 교차검수·GT·slot·consensus 변경
- holdout 공개·재선정·사용
- Python Evidence/VLM/Gate로 게코 부재 자동 제외
- 사건 결과의 production 자동 반영
- 유효 표본 수를 맞추기 위한 규칙 완화 또는 임의 교체

## 4. 사용자 체험 시뮬레이션

### 4.1 Owner 자격 검사

`[화면] Owner가 ‘이어짐 확인’을 열면 ‘1단계: 영상 자격 확인 0/120’과 A/B 영상이 보임`

→ `[조작] 두 영상을 보고 유효 또는 구체적인 무효 이유 하나를 누름`

→ `[반응] 답은 감사 기록으로 고정되고 다음 시간순 경계가 나타남. 같은/다른 사건 버튼은 아직 없음`

→ `[감정] 빈 화면을 사건 문제로 억지 판단하지 않고, 게코가 보이는 문제만 골라낸다고 이해함`

### 4.2 두 사람 경계 검수

`[화면] 120개 선별 완료 후 유효 경계가 60개 이상이면 ‘2단계: 영상 이어짐 확인’으로 자동 전환`

→ `[조작] Owner와 peer가 서로의 답을 모른 채 A/B가 같은 사건인지 각각 판정`

→ `[반응] A-B와 B-C가 모두 같은 사건으로 최종 확정되면 A+B+C가 하나의 사건 그룹이 됨`

→ `[감정] 파일을 합치는 작업이 아니라 시간표에서 이어지는 칸에 선을 긋는 일로 이해함`

중간 영상 B가 무효면 A-C를 자동으로 이어 붙이지 않는다. 무효·different·uncertain 경계는 chain을
끊는다.

## 5. 데이터 계약

기존 테이블을 유지하고 additive migration으로 다음을 추가한다.

- cohort status: `eligibility_open`, `insufficient_valid`, `invalid_eligibility`
- cohort reviewer: `owner_id`, `peer_id` (seed 시 고정)
- `rba_boundary_eligibility_reviews`: pair별 Owner immutable 최초 자격 판정
- 기존 pairs: 새 cohort에는 development 120개만 저장, ordinal 1~120
- 기존 assignments: 자격 검사 중에는 0개, freeze 성공 뒤 유효 pair마다 owner/peer 2개 생성
- 기존 submissions/resolutions: boundary phase에서만 사용

자격 판정 테이블은 UPDATE/DELETE/TRUNCATE를 막고 RLS + service-role RPC만 허용한다. 일반 peer는
`eligibility_open` cohort의 존재, 진행률, 영상 URL을 조회할 수 없다. Owner도 자격 판정 단계에는
상대 답이나 사건 판정 UI를 볼 수 없다.

120번째 자격 판정과 phase 전환은 한 DB transaction에서 실행한다. submit RPC는 cohort row를
`FOR UPDATE`로 잠가 119·120번째 동시 요청을 직렬화한다. 기존 boundary submit은 cohort row를
`FOR SHARE`로 잠그고 열린 status를 다시 확인하며, invalidation은 같은 row의 `FOR UPDATE` lock을
잡아 “0답 확인 직후 제출 1건 발생” 경쟁조건을 막는다.

1. `eligible` 개수를 센다. 어느 pair에서든 `A/B 게코 없음`으로 지목된 clip이 있으면 그 clip을
   포함한 모든 경계를 보수적으로 제외한다. 다른 pair에서 같은 clip을 `유효`로 봤더라도 자동
   연결하지 않고 모순 건수로 감사한다.
2. 60개 이상이면 위 보수 규칙까지 통과한 유효 pair에만 owner/peer assignment를 생성하고
   `development_open`으로 전환한다.
3. 60개 미만이면 `insufficient_valid`로 닫고 assignment를 만들지 않는다.

기존 cohort는 submissions/resolutions가 0인지 재확인한 원자적 RPC만
`development_open → invalid_eligibility`로 바꾼다. row와 media는 삭제하지 않는다.

## 6. 표본 계약

- experiment: `rba-event-sequence-review-v2`
- initial candidate boundary: exact 120 (목표 60의 2배)
- source: 기존 frozen development inventory, holdout은 읽거나 섞지 않음
- 최소 2 cameras와 최소 6 camera-nights 유지
- 모든 경계는 같은 camera/activity day의 바로 다음 activity candidate
- 선택 단위는 최소 6 camera-nights에서 뽑은 **연속 run**이다. run 내부 인접 경계는 하나도
  빼지 않고 모두 포함하며 총합을 exact 120으로 맞춘다. 실제 긴 run의 앞뒤를 자른 경우 manifest에
  `left_censored/right_censored`를 기록하고 사건 크기·reduction 계산에서 완전 관측처럼 취급하지 않는다.
- 동일 clip은 `A-B`, `B-C`처럼 왼쪽/오른쪽 이웃 경계에 겹쳐 등장해야 한다. 흩어진 pair 120개는
  selector가 거절한다.
- R2 HEAD는 seed 전과 직전에 unique clip 전부 2회 확인
- manifest와 selector 결과는 private artifact로 저장하고 DB에는 digest와 필요한 clip 참조만 저장
- 화면 순서는 시간순 chain 구조를 숨기지 않되 행동 GT/VLM/Python Evidence는 공개하지 않음

유효가 60개 미만이면 자동으로 과거 영상을 임의 추가하지 않는다. 별도 동결된 reserve block을 같은
규칙으로 만들고 다시 승인·감사하는 후속 절차가 필요하다.

이번 결과의 주장 범위는 development 내부 연구다. 기존 holdout은 독립 pair 표본이라 chain 검증에
재사용하지 않는다. production 채택 전에는 별도의 night 단위 sealed holdout run을 동결해 같은 규칙으로
검증해야 한다.

## 7. API/UI 계약

- `GET /api/rba-boundary/workspace`: `mode=eligibility|boundary|waiting`, 본인 progress와 다음 pair 하나
- `GET /api/rba-boundary/pairs/[pairId]/file/url`: eligibility Owner 또는 열린 boundary assignment만 서명
- `POST /api/rba-boundary/pairs/[pairId]/eligibility`: Owner만 허용, 판정은 한 번만 저장
- `POST /api/rba-boundary/pairs/[pairId]/submit`: 열린 boundary assignment만 기존 사건 판정 저장

Owner 자격 화면에는 다음 다섯 버튼만 표시한다.

1. `둘 다 게코가 보여 — 유효`
2. `영상 A에 게코가 없어`
3. `영상 B에 게코가 없어`
4. `둘 다 게코가 없어`
5. `촬영 오류 또는 화면 확인 불가`

버튼에는 제출 후 변경할 수 없다는 안내를 붙인다. peer는 eligibility 완료 전에는 메뉴가 보이지 않아도
되고 직접 URL 접근 시 ‘Owner 선별을 기다리는 중’만 본다.

`행동이 작다`, `판단이 어렵다`, `이어지는지 모르겠다`는 무효 사유가 아니다. 게코 부재 또는 실제
촬영·재생 장애만 무효다. 보고서에는 사유별 무효 수, 전체 무효율, 같은 clip의 유효/무효 모순 수를
필수로 남겨 Owner 선별로 쉬운 문제만 남는 낙관 편향을 감사한다.

## 8. 여러 영상을 사건으로 묶는 규칙

사건 그룹은 동영상 합성물이 아니라 clip ID 목록이다. 인접 경계의 최종 판정을 그래프 edge로 본다.

- `same_event`: 좌우 clip을 같은 연결 요소에 포함
- `different_event`: 여기서 사건을 분리
- `uncertain`: 자동 연결 금지
- eligibility invalid: 해당 경계와 무효 clip을 통한 우회 연결 금지

예: `A-B=same`, `B-C=same`, `C-D=different`면 `[A,B,C]`, `[D]`다. 이 계산은 연구 결과 단계에서만
수행하고 현재 migration은 production 사건 테이블을 만들거나 갱신하지 않는다.

## 9. 배포·검증 계약

1. selector unit test가 정확히 120개, 겹치는 clip, 인접성, 다양성, 결정론을 증명한다.
2. SQL 정적 계약과 disposable PostgreSQL probe로 권한·append-only·phase 전환을 검증한다.
3. API/UI 테스트를 RED로 만든 뒤 구현한다.
4. production migration 전 기존 cohort 답 0건을 다시 확인하고 invalidation한다.
5. Mac mini의 격리 작업 디렉터리에서 manifest를 만들고 R2 2회 preflight한다.
6. 새 cohort seed 후 owner=120/0 eligibility, peer=waiting/0을 aggregate로 확인한다.
7. Vercel production에서 Owner 로그인 화면, 영상 A/B 재생, 다섯 자격 버튼을 확인한다.
8. 자동화는 사람을 대신해 자격 답을 제출하지 않는다. 최종 완료선은 Owner가 첫 판정을 시작할 수 있는 상태다.

배포 순서는 migration 후 웹 배포다. 교체 workspace RPC는 이 사이 구 웹이 호출해도 깨지지 않도록
기존 `enabled/reviewer_role/split/total/completed/next_pair` 키를 그대로 유지하고 `mode`만 additive로
추가한다. open cohort unique index에는 `eligibility_open`도 포함하며, seed RPC는 다른 open cohort가
있으면 거절한다. 배포 후에는 기존 cohort status와 pair/submission/resolution row 수 불변도 함께 확인한다.
