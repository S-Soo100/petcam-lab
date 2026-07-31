# RBA Data Engine Formal Blind30 v2 Design

**상태:** 사용자 설계 승인 / 구현 전 동결
**기준:** v1 결과를 보지 않은 상태에서 media availability 결함만 보정한다.

## 문제

v1 cohort `dd2d4e6c-538c-41eb-81ce-02f39396e9a1`은 metadata eligibility를 통과한
30개 중 5개의 실제 R2 object가 freeze 뒤 `HeadObject=404`로 확인됐다. DB `r2_key`는
30/30 non-null이고 해당 5개에 system exclusion row가 없어 기존 selector와 RPC가
DB-R2 drift를 감지할 수 없었다. human submission은 0이었고, v1은 2026-07-31
10:15:19 KST에 공식 close RPC로 비파괴 종료했다.

판정은 실패나 표본 교체가 아니라 `INVALID_SAMPLE_AFTER_FREEZE`다. v1 cohort, slots 60,
awaiting consensus 30, manifest와 감사 증거는 삭제·수정하지 않는다.

## 결정

1. v2는 v1 T0 `2026-07-31T03:44:27.183403+09:00` 이상에서 시작한 clip만 후보로 삼는다.
2. 기존 threshold, `motion-blind-v1` comparator, 5분 dedup, 최소 2 cameras, 최소 6
   camera-nights, stratum당 최대 5개는 바꾸지 않는다.
3. metadata selector가 exact 30을 고른 뒤 실제 R2 `HeadObject`를 두 번 실행한다.
   - 1차: secure manifest를 쓰기 직전
   - 2차: create RPC를 호출하기 직전
4. 두 preflight 모두 exact key가 HTTP 200이고 content length가 0보다 커야 한다.
   403, 404, timeout, zero-size, ETag 누락은 attempt 전체를 fail-closed한다.
5. 실패 clip 한 건만 교체하지 않는다. 새 T0와 새 manifest를 사용하는 새 attempt만 허용한다.
6. 두 preflight의 30개 salted media digest가 전부 같아야 한다. 다르면 RPC를 호출하지 않는다.
7. manifest에는 `r2_key`, endpoint, credential, signed URL, raw ETag를 넣지 않는다.
   `verified_at`, content-length/ETag 기반 salted digest, bucket/account fingerprint만 기록한다.
8. v2는 새 `fn_create_motion_blind_formal30_v2`와 `b30v2:<manifest sha256>` label을 쓴다.
   v1 RPC, label, row, manifest를 변경하지 않는다.

## 컴포넌트

### Python media preflight

`scripts/prepare_rba_blind30.py`에 network 호출과 판정을 분리한다.

- `head_media_batch`: 주입된 S3 client로 exact 30 key를 한 번씩 HEAD한다.
- `assert_media_preflight_match`: 1차/2차 clip set과 salted digest가 정확히 같은지 확인한다.
- `build_manifest`: 비밀값 없는 media attestation을 clip별로 포함한다.

호출 순서는 selector -> preflight 1 -> manifest -> preflight 2 -> digest match -> RPC다.
두 batch 사이에 selection이나 ordered list는 바뀌지 않는다.

### PostgreSQL v2 RPC

새 forward migration은 다음만 추가한다.

- `b30v2:` label용 partial unique index
- live submission guard가 v1과 v2 formal label을 모두 인식하도록 확장
- v1과 동일한 exact 30/2 reviewers/60 slots/30 awaiting 원자성
- `started_at >= v1 T0` future-pool guard
- service-role-only EXECUTE

R2 존재 검증은 DB transaction 내부에서 재현할 수 없으므로 Python의 두 preflight가 담당한다.
DB RPC는 metadata race, reviewer race, live submission race를 계속 담당한다.

## 실패·복구

- preflight 실패: manifest/RPC 생성 0, 해당 attempt 전체 폐기
- 1차와 2차 digest 불일치: RPC 0, 표본 교체 0
- RPC 실패: 재호출 0, production state를 read-only 확인하고 보고
- RPC 성공 뒤 media 문제: run을 비파괴 close하고 새 version을 설계한다
- 기존 cohort/slot/submission/consensus/event/final 삭제·rewrite는 항상 0

## 보안

- R2 access key, secret, endpoint, object key, raw ETag는 로그·manifest·Git에 기록하지 않는다.
- manifest mode는 `0600`, audit directory는 `0700`이다.
- reviewer UUID/email과 clip ID는 사용자 보고에 노출하지 않는다.
- database 함수는 `PUBLIC`, `anon`, `authenticated` EXECUTE를 revoke하고 `service_role`만 허용한다.
