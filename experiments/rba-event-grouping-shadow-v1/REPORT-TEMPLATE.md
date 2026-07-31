# RBA 사건 묶기 shadow v1 보고서

## 상태

- 구현: `IMPLEMENTED_VERIFIED`
- production prepare: `BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS`
- 실험 verdict: `BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS`

인증된 SELECT-only production snapshot을 실제로 읽었지만 frozen 기준을 만족하는
camera-night가 부족했다. 기준을 완화하거나 표본을 임의 교체하지 않고 fail-closed했다.

## Exact source and code provenance

- handoff:
  `HANDOFF_OK task=rba-event-grouping-shadow-v1 repo=rba-event-grouping-shadow-v1 commit=38381f74 runtime=oneshot@baeg-endeuui-Macmini.local`
- source cutoff: `2026-07-31T03:44:27.183403+09:00`
- implementation host: `baeg-endeuui-Macmini.local`
- verified implementation code HEAD:
  `e1fa6db8ff4313dabc6fdaaa9ab62a9dac32f793`

## Production read-only preflight

- 허용 테이블: `motion_clips`, `motion_clip_system_exclusions`,
  `motion_clip_review_slots`
- DB write/RPC: `0/0`
- 2026-07-31 preflight: 전용 env 파일은 regular file·non-symlink·current owner·mode `0600`,
  required variable name 2개 exactly once/non-empty를 값 출력 없이 통과했다.
- 직접 실행 import 회귀를 `52ca204`에서, offset pagination의 고유키 정렬을 `e1fa6db`에서
  RED→GREEN으로 보정했다.
- 최종 prepare의 정렬 SELECT pagination은 `61` requests였고, shortage aggregate 확인용
  별도 SELECT-only 진단도 `61` requests였다. 앞선 원인 진단은 `81` requests였으며,
  정렬 전 실패 시도 1회의 exact request count는 계측하지 못했다.

## Accounting population

- closed accounting: `19,279`
- activity candidate / diagnostic integrity / blocked research:
  `261 / 101 / 18,917`
- output directory 생성 전 split gate에서 중단돼 frozen source/accounting artifact는 없다.

## Boundary-pair manifest

- candidate pairs: `209`
- gap bins: `≤15s 0 / 15–60s 132 / 60–300s 77`
- pair camera-nights/cameras: `5 / 2`
- exact 12 camera-nights: 부족으로 미동결
- development/holdout: `0/0`
- exact boundary pairs: `0`
- reviewer worksheets: dev/holdout 분리 6개 모두 미생성

## Three-run determinism

- threshold `0` run hashes: prepare가 split gate에서 중단돼 미실행

## Mutation and forbidden-input audit

- production DB write/RPC: `0/0`
- R2/model/frame/service calls: `0/0/0/0`
- 정적 mutation/RPC 및 forbidden-input scan: `0` matches
- final focused tests: Mac mini·local 모두 `55 passed`
- final local full tests: `995 passed, 5 skipped`
- Mac mini full tests at predecessor `4ad9690`: `990 passed, 5 skipped`,
  환경 의존 실패 3개(다른 사용자 절대경로 1, PostgreSQL role probe 2)

## Human GT status

사람 답을 생성하지 않았다. exact 120 동결이 가능한 future pool이 생긴 뒤 두 blind reviewer가 development 60을 먼저
작성하고 불일치와 uncertain만 owner가 adjudicate한다. threshold freeze 뒤에만 별도 holdout
60 파일을 열어 같은 순서로 진행한다.

## Deviations

prepare는 인증된 SELECT-only 환경에서 실행했다. 그러나 후보 pair가 있는 camera-night가
`5`뿐이고 `≤15s` gap bin이 `0`이라 exact 12박 split을 만들 수 없었다. output directory 생성
전 중단했고 threshold `0` group은 실행하지 않았다. cutoff/bin/camera-night/camera cap을
완화하지 않았다.

## Verdict

`BLOCKED_INSUFFICIENT_BOUNDARY_PAIRS`

현재 historical closed-day pool로는 frozen 시험지를 만들 수 없다는 실험 verdict다. future
closed-day 데이터가 충분히 쌓이기 전에는 재실행하지 않고, exact 12 camera-nights와 세 gap
bin 기준도 바꾸지 않는다.
