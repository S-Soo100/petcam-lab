# 사건 이어짐 자격검사 사유 분리 UI 설계

**상태:** 승인됨
**승인:** 2026-08-01, Owner가 UI 분류와 22번 A/B 오탐 정정 승인
**범위:** 라벨링 웹 사건 이어짐 1단계 자격검사와 그 판정 저장 계약

## 목표

현재 한 격자에 섞여 있는 5개 선택지를 의미별로 나누고, 게코는 보이지만 그림자·빛·곤충 때문에
움직임 이벤트가 잘못 생성된 영상을 사건 이어짐 표본에서 제외한다. 어떤 쪽 영상이 문제인지 A/B/둘
다로 저장해 같은 clip을 공유하는 다른 경계에도 무효 판정을 전파한다.

## 사용자 체험

`[화면] Owner가 23번을 열면 A/B 영상 아래에 유효·게코 부재·활동 오탐·영상 오류가 서로
분리된 영역으로 보임`
`[조작] Owner가 사유 영역에서 A/B/둘 다 중 정확한 버튼 하나를 누름`
`[반응] 선택한 버튼만 강조되고, 제출 버튼을 눌러야 비로소 immutable 판정이 저장됨`
`[감정] 긴 문장을 하나씩 다시 읽지 않고도 어느 종류의 문제인지 빠르게 구분할 수 있음`

## 화면 구조

1. **유효** — 초록 계열의 단독 전체폭 버튼
   - `두 영상 모두 유효`
2. **게코가 안 보임** — A / B / 둘 다
3. **실제 게코 활동 없음** — A / B / 둘 다
   - 그림자·빛·곤충 등으로 motion trigger가 발생했지만 게코가 실제로 움직이지 않은 경우
4. **영상 자체를 확인할 수 없음** — A / B / 둘 다
   - 재생 실패, 검은 화면, 멈춤, 심한 가림·노출 문제

각 무효 영역에는 짧은 제목과 한 줄 설명을 두고, 버튼은 데스크톱 3열·좁은 화면 1열로 배치한다.
선택 즉시 저장하지 않고 기존 제출 버튼과 immutable 안내를 유지한다.

## 데이터 계약

기존 5개 decision은 감사 이력 때문에 모두 허용 상태로 보존한다. UI는 기존 generic
`capture_or_media_error`를 더 이상 새 판정으로 노출하지 않는다. 다음 6개 side-aware decision을
추가한다.

- `left_no_gecko_activity`, `right_no_gecko_activity`, `both_no_gecko_activity`
- `left_capture_or_media_error`, `right_capture_or_media_error`, `both_capture_or_media_error`

120번째 판정에서 만드는 `invalid_clips`는 게코 부재, 활동 오탐, side-aware 영상 오류를 모두 A/B
방향에 맞게 포함한다. 기존 generic `capture_or_media_error`는 어느 쪽인지 알 수 없으므로 해당 pair만
eligible이 아니며 clip 전체 전파에는 사용하지 않는다. 기존 제출 row는 수정·삭제하지 않는다.

### 22번 오제출 정정

production 확인 결과 22번은 2026-08-01 22:03:27 KST에 `eligible`로 저장됐지만, Owner가 실제로는
A/B 모두 그림자 오탐이며 `both_no_gecko_activity`가 맞다고 확인했다. 원본 row는 immutable 감사
이력으로 보존하고 별도 append-only correction row를 한 건 추가한다.

- correction은 원본 review와 pair에 각각 unique라 한 번만 기록할 수 있다.
- 원본 decision·digest는 수정하지 않는다.
- correction에는 replacement decision, 사유, Owner, digest, 시각을 저장한다.
- correction RPC는 cohort가 `eligibility_open`이고 원래 Owner가 호출한 경우에만 허용한다.
- 120번째 최종 계산은 `coalesce(correction.replacement_decision, review.decision)`을 사용한다.
- 22번 correction은 `both_no_gecko_activity`이므로 A/B clip과 이를 공유하는 인접 경계를 제외한다.
- 일반 라벨링 UI에는 정정 메뉴를 추가하지 않는다. 사람의 최초 제출은 계속 immutable하며, 확인된
  입력 실수만 service-role append-only 감사 경로로 정정한다.

## 오류와 동시성

- 제출 API는 새 decision만 추가 허용하고 기존 UUID·Owner·중복 제출 검증을 그대로 유지한다.
- migration은 append-only trigger와 RLS를 변경하지 않는다.
- 1~22번 원본 review count와 digest는 migration 전후 모두 그대로다.
- 웹 배포보다 DB migration을 먼저 적용해 새 UI가 아직 DB에서 거절되는 창을 만들지 않는다.

## 검증

- React 테스트로 네 영역, A/B/둘 다 decision 매핑, 선택과 제출의 분리, 사건 판정 숨김을 확인한다.
- TypeScript decision guard가 기존 값과 새 side-aware 값을 허용하고 임의 값은 거절하는지 확인한다.
- migration 테스트로 기존 row 보존, check 확장, 새 판정의 clip 전파 조건을 확인한다.
- 일회용 PostgreSQL runtime probe에서 v2로 21개 원본을 만든 뒤 migration 전후 count·digest 동일,
  신규 6개 decision matrix, generic 오류의 pair-only 제외, correction 우선순위를 검증한다.
- production에서는 배포 전 Owner progress가 22/120·next=23인지 read-only로 확인하고, correction
  적용 뒤에도 원본 22개가 그대로인지 확인한다. 배포 후 23번 화면만 smoke하며 새 판정을 제출하지 않는다.

## 제외 범위

- 이미 제출한 1~22번 원본 데이터 수정·삭제
- 사건 이어짐 본 판정 UI 변경
- holdout, Blind30, 기존 행동 GT·교차검수 변경
- 자동 VLM/Python 판정 추가
