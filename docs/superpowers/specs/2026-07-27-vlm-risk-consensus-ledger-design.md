# VLM 위험 라벨 consensus shadow 원장 설계

**상태:** owner 승인 완료
**상위 설계:** `petcam-nightly-reporter`의
`docs/superpowers/specs/2026-07-27-vlm-risk-consensus-shadow-design.md`
**이 레포의 책임:** shadow attempt를 안전하게 저장하는 DB 계약만 담당

## 1. 목적

Mac mini 정규 VLM worker가 위험 라벨 batch를 동일 조건으로 세 번 판독할 때, 각 판독을
production 결과와 분리된 append-only 원장에 저장한다. 이 원장은 비결정성, 비용, deadline
영향을 측정하기 위한 연구 데이터이며 앱·라벨링 웹·행동 기록의 입력이 아니다.

## 2. 저장 단위

한 row는 `clip_vlm_jobs`의 한 job에 대한 한 durable shadow attempt다.

- identity: `job_id + protocol_version + attempt_index`
- protocol: `risk-consensus-shadow-v1`
- attempt: `1`, `2`, `3`
- batch identity: ordered job·clip 집합에서 worker가 만든 SHA-256
- attempt 1: 기존 production 첫 판정의 immutable snapshot
- attempt 2·3: 같은 batch·frame·prompt·model 조건의 추가 판정 또는 명시적 미실행 상태

같은 identity의 재삽입은 모든 저장 필드가 동일할 때만 멱등 성공한다. 하나라도 다르면
SQLSTATE `22023`으로 거부한다.

## 3. 저장 필드

- 관계: `job_id`, `clip_id`
- 재현성: `protocol_version`, `batch_identity_sha256`, `batch_size`, `batch_position`
- 시도: `attempt_index`, `status`, `failure_code`
- 결과: `action`, `confidence`
- provenance: `provider`, `model_requested`, `model_actual`, `prompt_version`,
  `prompt_sha256`, `sampler_version`, `provider_request_sha256`
- 사용량: input/cache-create/cache-read/output token, provider 추정 비용
- 시각: `created_at`

상태는 `succeeded`, `deferred`, `failed`, `integrity_failure`, `not_run`만 허용한다.
성공 row만 action·confidence를 갖고, 나머지는 allowlist failure code를 가져야 한다.

## 4. DB 무결성

원자 RPC `fn_insert_vlm_shadow_attempt_batch(jsonb)`만 writer가 사용한다.

1. 입력은 1~4개 JSON object 배열이어야 한다.
2. 정의된 key 외 필드는 거부한다. `reasoning`, 경로, R2 key가 들어오면 저장되지 않고
   전체 호출이 실패한다.
3. 모든 job을 `id` 순서로 잠그고 payload의 `clip_id`, model, prompt, sampler provenance가
   실제 `clip_vlm_jobs`와 일치하는지 확인한다.
4. 한 RPC의 row는 protocol, batch hash, batch size, attempt index가 같고 position이
   `0..batch_size-1`을 정확히 한 번씩 포함해야 한다.
5. clip 또는 job이 다른 batch에 섞인 cross-object payload를 거부한다.

## 5. 보안·보존

- RLS enabled, client policy 0
- `anon`, `authenticated`, `public` 권한 0
- `service_role`만 table 접근과 RPC 실행 허용
- RPC는 `SECURITY INVOKER SET search_path=''`, 모든 객체는 `public.`으로 한정
- UPDATE·DELETE·TRUNCATE는 role과 무관하게 SQLSTATE `0A000`으로 차단
- 원본 reasoning, frame path, R2 key, signed URL, 이메일, 사용자 UUID는 저장 금지
- `motion_clips`, `clip_vlm_jobs`, GT, behavior, activity, app row는 이 migration이 수정하지 않음

## 6. 범위 밖

- consensus 계산 또는 production 결과 채택
- 기존 job status/result 변경
- 앱·웹 조회 API와 RLS 정책
- VLM 호출, prompt·selector·threshold 변경
- historical 44개 재실행
- production migration 적용

## 7. 완료 조건

- 정적 migration 계약 테스트 통과
- disposable PostgreSQL에서 정상 insert, 멱등, forged payload, append-only, role 권한을 실증
- probe 종료 후 임시 DB·role·row residue 0
- 전체 `petcam-lab` pytest 회귀 통과
- production 데이터 write 0
