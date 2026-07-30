# RBA Data Engine formal blind 30 테스트 시험지

> 규칙: [연구 테스트 프로토콜](../../.claude/rules/research-testing.md).
> **제출 전에 동결하며 결과를 본 뒤 바꾸지 않는다.**

**실험 ID:** `rba-data-engine-blind30-v1`
**작성일:** 2026-07-31
**상태:** 🔒 계약 동결 / `EXECUTION_BLOCKED_RESERVATION_AND_REVIEWER_PAIR`

이 시험은 tutorial 완료 non-owner 두 명의 공통 표본 일치도를 확인하는 운영 품질 gate다.
production VLM, Gate, 모델 또는 router의 채택 시험이 아니다. 기존 paired 53건은 운영 EDA,
`owner-single-adopt-v1` 47건은 단일 reviewer 운영 final로만 보존하며 둘 다 표본에 넣지 않는다.

## 1. 가설

- **H0:** 두 reviewer의 독립 판정 일치도 또는 abstain/owner-adjudication 부담이 사전 기준을
  충족하지 못한다.
- **H1:** 두 reviewer가 정답·peer·VLM·Gate를 보지 않고 같은 30개를 검수해 아래 품질·운영
  기준을 모두 충족한다.

N=30은 onboarding 이후 기준 정합성 gate다. train/validation 품질이나 production 모델 성능을
일반화하지 않는다.

## 2. Reviewer 자격

두 reviewer는 모두 다음을 만족해야 한다.

1. owner가 아닌 production `labelers` row와 approved application을 가진다.
2. 같은 active review group의 서로 다른 두 member다.
3. active `tutorial-v1`의 현재 run에서 waiver 없이 position 1..5 attempt가 모두 completed다.
4. owner adjudicator와 reviewer는 겸하지 않는다.
5. 실행 중 peer 답, consensus, VLM prediction/result, Gate/Python evidence를 보지 않는다.

2026-07-31 preflight에서 실제 non-owner tutorial 완료자는 두 명이지만 각각 A/B그룹에 속한다.
owner 완료자는 reviewer 자격이 없다. 따라서 현재 reviewer pair는 위 2번을 만족하지 않는다.
waiver를 tutorial 완료로 세거나 운영 group을 임시 재배정하지 않는다.

## 3. 표본 선택

### 3.1 eligibility

freeze 시각 `T0`에 아래 조건을 모두 만족하는 production `motion_clips`만 후보로 읽는다.

- `started_at < T0`이며 activity day가 닫힌 clip
- `r2_key IS NOT NULL`
- `fn_motion_blind_clip_is_labelable(id) = true`
- `motion_clip_system_exclusions.state`가 `quarantined|media_deleted`가 아님
- tutorial lesson clip이 아님
- canary/formal scope(`cohort_kind='canary'`)의 slot 또는 consensus에 들어간 적이 없음
- `motion_clip_blind_submissions`가 cohort 종류와 무관하게 0건
- 제출 전 live slot과 `status='awaiting'` live consensus는 일일 큐 materialization
  bookkeeping이므로 후보에서 제외하지 않음. live `agreed|conflict|owner_resolved`는 제외함
- legacy/motion-v3 사람 GT session이 0건
- `owner-single-adopt-v1` 및 기존 paired 53건과 무관한 clip

선택기는 answer/GT, VLM/Gate/Python evidence, consensus result/status, triage decision을 읽지 않는다.
eligibility 확인에 필요한 ID·camera·started_at·duration·media/exclusion 존재 여부만 읽는다.

### 3.2 near-duplicate와 camera-night

1. `activity_day_kst = (started_at AT TIME ZONE 'Asia/Seoul' - interval '7 hours')::date`.
2. `(camera_id, activity_day_kst, floor(epoch(started_at)/300))` 5분 bucket마다 hash가 가장 작은
   clip 하나만 남긴다.
3. stratum은 `(camera_id, activity_day_kst)`다. 각 stratum 최대 5개, 전체 최소 6개
   camera-night, 최소 2개 camera를 요구한다.
4. seed 문자열은 `rba-data-engine-blind30-v1`로 고정한다.
5. stratum 순서는
   `sha256(seed|camera_id|activity_day_kst)`, stratum 내부는
   `sha256(seed|clip_id)` 오름차순이다.
6. stratum을 round-robin하며 하나씩 뽑아 정확히 30개에서 멈춘다. 조건을 만족하는 30개가
   없으면 표본을 완화하지 않고 `INSUFFICIENT_ELIGIBLE_POOL`로 중단한다.

선택 뒤 clip 교체는 금지한다. media 재생 불가나 사후 부적격이 한 건이라도 발견되면 그 run은
`INVALID_SAMPLE_AFTER_FREEZE`로 중단하고, 원인을 고친 뒤 새 version/새 미래 pool로 다시 동결한다.

### 3.3 manifest

선택 시점에 다음 artifact를 mode `0600`으로 만든다.

`/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-blind30-v1-manifest.json`

manifest에는 schema/seed/T0/selection rule/version, reviewer 비식별 fingerprint, 30 clip ID,
camera/activity-day/started_at, eligibility flags, ordered-list SHA-256을 기록한다. 답·GT·VLM·Gate,
이메일, signed URL, credential은 기록하지 않는다. reviewer에게 manifest를 주지 않고 cohort
URL만 제공한다. manifest full SHA-256은 cohort label `b30v1:<sha256>`과 실행 보고에 고정한다.

## 4. 예약·격리

generic `fn_manage_motion_blind_canary`는 clip `1..20`만 허용하므로 두 cohort를 합치지 않는다.
실행 전에 별도 forward RPC `fn_create_motion_blind_formal30`을 TDD로 추가한다.

- 기존 canary 저장 구조를 재사용하되 clip 수는 **정확히 30**만 허용
- reviewer는 §2 자격을 DB에서 재검증
- manifest ordered-list hash와 30개 eligibility를 한 transaction에서 재검증
- 기존 submission/slot/cohort 이력이 하나라도 있으면 fail-closed
- cohort 1개, reviewer별 30개씩 slot 60개, awaiting consensus 30개를 원자 생성
- generic canary 20 제한은 그대로 유지
- 기존 slot/submission/consensus를 삭제·rewrite하지 않음

기존 canary detail/queue read API는 한 cohort 최대 100개를 읽을 수 있으므로 exact-30 cohort를
표시할 수 있다. 생성 RPC와 reviewer pair가 준비되기 전 production reservation은 0건이다.

## 5. Blind 제출과 comparator

- URL: reservation 뒤 `/labeling/blind/canary/{cohort_id}` 한 개만 전달한다.
- 두 reviewer 모두 같은 30개를 각자 제출한다.
- 최초 GT 잠금 전 prediction/reference/peer/consensus를 노출하지 않는다.
- comparator: exact `motion-blind-v1`.
- owner adjudication은 두 제출과 자동 비교가 모두 끝난 뒤 conflict만 처리한다.
- agent/owner는 reviewer를 대신해 submission을 만들지 않는다.

### 비교 차원

- decision, visibility, primary action, observed-action set, applicable target/context
- segment는 같은 action끼리 one-to-one 최대 매칭한다.
- segment match는 `IoU >= 0.50` 또는 start/end 각각 절대 오차 `<= 2.0초`다.
- unmatched segment는 false positive/false negative 각각 1건으로 센다.

`uncertain`/`unjudgeable`은 임의 class로 치환하지 않고 abstain으로 센다. 한쪽이라도 해당
dimension에서 abstain하면 그 dimension agreement 분모에서 제외하고 clip은 owner adjudication
대상으로 둔다. 둘 다 abstain이어도 자동 agreement로 세지 않는다.

## 6. 지표와 pass/fail

다음을 reviewer pair 기준으로 계산한다.

- decision exact agreement
- visibility exact agreement
- primary-action exact agreement
- observed-action set exact agreement
- applicable target/context exact agreement
- segment precision/recall/F1
- reviewer별 uncertain/abstain clip 비율
- automatic agreement 수와 owner adjudication 수
- 제출 완료율, 중복/누락 submission, 정답·peer·VLM·Gate 노출 사고

### PASS

아래를 전부 만족해야 한다.

- 두 reviewer 모두 30/30 제출, duplicate/missing 0
- decision, visibility, primary action exact agreement 각각 `>= 24/30`
- observed-action set과 applicable target/context evaluable agreement 각각 `>= 0.80`
- segment F1 `>= 0.80`
- reviewer별 uncertain/abstain clip `<= 6/30`
- owner adjudication `<= 6/30`
- blind 노출·표본 교체·계약 위반 0

### HOLD

evaluable denominator가 10 미만인 dimension이 있거나 media/시스템 문제로 정직한 판정이
불가능하지만 sample 계약 위반은 없는 경우다. threshold를 바꾸지 않고 원인을 보고한다.

### FAIL

PASS 수치 중 하나라도 미달하거나 blind 노출, 사후 표본 교체, reviewer 자격 위반, 기존
53쌍/47 single-adopt 재사용이 한 건이라도 있으면 실패다. 결과를 본 뒤 threshold를 낮추지 않는다.

## 7. 현재 실행 blocker

1. tutorial 완료 non-owner 두 명이 서로 다른 active group이라 현재 canary 접근 계약으로 같은
   cohort를 만들 수 없다.
2. generic canary RPC는 최대 20개라 exact 30 원자 예약이 불가능하다.
3. formal30 raw 제출 기반 항목별/segment 채점기가 아직 없다. 운영
   `motion-blind-v1` comparator와 consensus 원장은 변경하지 않는다.
4. 따라서 manifest, cohort, slot, reviewer URL은 아직 생성하지 않았다.

해소 순서는 `같은 active group의 두 번째 non-owner가 tutorial을 실제 5/5 완료` →
`fn_create_motion_blind_formal30` TDD/preview/production 검증 → raw 제출 기반 별도 채점기 검증 →
metadata-only selection → manifest mode0600/hash 고정 → cohort 1개/slots 60개 검증 → URL 전달이다.

**현재 판정:** `BLIND30_PREFROZEN_BLOCKED_REVIEWER_PAIR_AND_EXACT30_RESERVATION`
