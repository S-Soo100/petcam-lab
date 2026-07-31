# RBA 사건 묶기 shadow v1 보고서

## 상태

- 구현: `IMPLEMENTED_VERIFIED`
- production prepare: `BLOCKED_PRODUCTION_READ_AUTH`
- 실험 verdict: 미판정

`READY_FOR_HUMAN_BOUNDARY_GT`, `BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS`,
`REJECT_INTEGRITY` 중 어느 것도 production source snapshot 없이 주장하지 않는다.

## Exact source and code provenance

- handoff:
  `HANDOFF_OK task=rba-event-grouping-shadow-v1 repo=rba-event-grouping-shadow-v1 commit=38381f74 runtime=oneshot@baeg-endeuui-Macmini.local`
- source cutoff: `2026-07-31T03:44:27.183403+09:00`
- implementation host: `baeg-endeuui-Macmini.local`
- implementation HEAD: 실행 완료 시 기록

## Production read-only preflight

- 허용 테이블: `motion_clips`, `motion_clip_system_exclusions`,
  `motion_clip_review_slots`
- DB write/RPC: `0/0`
- 2026-07-31 preflight: 현재 process에 `SUPABASE_URL`과
  `SUPABASE_SERVICE_ROLE_KEY`가 없고 기존 Supabase CLI project link도 없어 SELECT snapshot을
  실행하지 않았다.
- 금지: 브라우저 token, 저장 password, credential 추출로 우회하지 않는다.

## Accounting population

- source count: 미측정
- activity candidate / diagnostic integrity / blocked research: 미측정
- source/accounting set equality: production artifact 생성 뒤 독립 process에서 검증

## Boundary-pair manifest

- exact 12 camera-nights: 미동결
- development/holdout: `0/0`
- exact boundary pairs: `0`
- reviewer worksheets: production 표본 미동결로 dev/holdout 분리 6개 모두 미생성

## Three-run determinism

- threshold `0` run hashes: production manifest 미생성으로 미측정

## Mutation and forbidden-input audit

- production DB SELECT/write/RPC: `0/0/0`
- R2/model/frame/service calls: `0/0/0/0`
- 정적 mutation/RPC 및 forbidden-input scan: `0` matches
- focused tests: `48 passed`
- full tests: `985 passed, 5 skipped, 3 unrelated environment failures`

## Human GT status

사람 답을 생성하지 않았다. exact 120 동결 뒤 두 blind reviewer가 development 60을 먼저
작성하고 불일치와 uncertain만 owner가 adjudicate한다. threshold freeze 뒤에만 별도 holdout
60 파일을 열어 같은 순서로 진행한다.

## Deviations

production SELECT credential이 현재 execution process에 주입되지 않아 prepare one-shot,
artifact-only audit, threshold `0` 3회 실행은 시작하지 않았다. 임계값·camera-night·bin·cutoff를
완화하지 않았다.

## Verdict

`BLOCKED_PRODUCTION_READ_AUTH`

이 값은 실험 결과 verdict가 아니라 실행 precondition blocker다. 인증된 SELECT-only process로
동일 HEAD를 다시 실행하기 전에는 정본 실험 verdict 세 가지 중 하나로 바꾸지 않는다.
