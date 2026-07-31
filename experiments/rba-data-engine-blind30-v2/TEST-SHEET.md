# RBA Data Engine formal Blind30 v2 테스트 시험지

**실험 ID:** `rba-data-engine-blind30-v2`
**작성일:** 2026-07-31
**상태:** 계약 동결 / 실행 전

v1은 frozen 30개 중 실제 R2 object 5개 부재로 `INVALID_SAMPLE_AFTER_FREEZE` 종료했다.
human submission과 결과 관찰은 0이므로 v1의 threshold와 measurement 목적은 바꾸지 않는다.

## 가설과 인증 범위

H0/H1, 지표, PASS/HOLD/FAIL threshold, abstain, segment tolerance와 `motion-blind-v1`
comparator는 v1 TEST-SHEET §1, §5, §6과 정확히 같다.

PASS가 인증하는 것은 natural production distribution에서 두 reviewer의 일치도, abstain,
owner adjudication 부담, 제출·blind·표본 운영 무결성뿐이다. 희소 행동별 일치도, taxonomy,
train/validation GT, 모델/VLM/Gate/router/P0 성능, chance-corrected agreement는 인증하지 않는다.

## Reviewer

v1과 동일하게 같은 active group의 서로 다른 approved non-owner 2명, active
`tutorial-v1` current run 5/5, waiver 0을 요구한다. 임시 group 이동과 tutorial waiver는 금지한다.

## 표본

- seed: `rba-data-engine-blind30-v2`
- sample size: exact 30
- future pool: `started_at >= 2026-07-31T03:44:27.183403+09:00`
- 새 T0보다 이전이고 activity day가 닫힌 clip
- 나머지 metadata eligibility, 5분 dedup, stratum당 최대 5, 최소 6 camera-nights,
  최소 2 cameras는 v1과 같다
- v1과 모든 canary/formal history, any submission, live terminal consensus, tutorial,
  legacy GT, system exclusion은 제외한다
- 결과/GT/AI/VLM/Gate/consensus result는 selection에 사용하지 않는다

선택 뒤 한 건 교체는 금지한다.

## 실제 media preflight

선택된 exact 30의 DB `r2_key`를 transient input으로만 사용해 R2 `HeadObject`를 실행한다.

1. manifest 직전 30/30
2. RPC 직전 30/30

각 object는 HTTP 200, content length > 0, ETag 존재를 모두 만족해야 한다. 403, 404,
timeout, zero-size, ETag 누락이면 attempt 전체를 폐기한다. 두 batch는 같은 in-memory salt로
content length와 ETag를 digest하고 clip별 digest가 정확히 같아야 한다.

manifest에는 object key, endpoint, credential, signed URL, raw ETag를 넣지 않는다.
`verified_at`, salted media digest, bucket/account fingerprint만 기록하며 mode는 `0600`이다.

## 예약

새 `fn_create_motion_blind_formal30_v2`를 정확히 한 번 호출한다. label은
`b30v2:<manifest sha256>`이며 cohort 1, reviewer별 slots 30/30, awaiting consensus 30,
submission 0을 한 transaction에서 만들거나 모두 rollback한다. v1 row와 manifest는 보존한다.

## 결정

- media preflight 2회 30/30, digest 동일, DB 원자 예약과 blind guard 통과: human review open
- media 또는 DB invariant 한 건 실패: fail-closed, 표본 교체·RPC 재호출 0
- human 결과 판정은 reviewer 두 명이 각 30/30 제출한 뒤 v1과 같은 scorer/threshold로 수행한다
