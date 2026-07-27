# AI 연구 운영 계약 완료 보고

검증 시각: 2026-07-28 KST
검증 대상 구현 commit: `0721b7711c70308b3b990816f6278ca8d6d79a5f`
branch: `codex/research-catalog-20260727`
upstream (검증 시작 시점): `origin/codex/research-catalog-20260727` @ `46e1df2674d7547506ff3d71d60c3157e06ef36c`
상태 (검증 시작 시점): tracked/untracked 변경 없음, local branch가 upstream보다 12 commits ahead

## 판정

`AI_OPERATING_CONTRACT_V1_VERIFIED`

아래 focused·전체 회귀, compile, JSON parse, manifest CLI schema-only, 정적 보안/권한 감사와
`git diff --check`가 모두 fresh 실행에서 exit 0이었어. 이 판정은 계약 구현과 문서의 검증
완료를 뜻하며, production 배포나 Mac mini runtime 변경을 뜻하지는 않아.

## 권한

- P0~P2: 승인된 package에서 자동 실행한다.
- P3: exact target·rollback·canary와 package 승인이 모두 있어야 한다.
- P4: 별도 Owner 승인이 항상 필요하다.
- 이번 작업에서 실제 사용한 권한은 P1(문서 작성, 테스트, feature commit/push)뿐이다.
  P2/P3/P4 mutation은 0건이다.

## 모델 provenance

| 작업 | requested model / reasoning | actual model / reasoning | surface | fallback |
|---|---|---|---|---|
| Task 1 | `gpt-5.6-terra` / `high` | `unverified` / `unverified` | Codex desktop orchestration | 없음 |
| Task 2 | `gpt-5.6-terra` / `high` | `unverified` / `unverified` | Codex desktop orchestration | 없음 |
| Task 3 | `gpt-5.6-sol` / `high` | `unverified` / `unverified` | Codex desktop orchestration | 없음 |
| Task 4 | `gpt-5.6-sol` / `xhigh` | `unverified` / `unverified` | Codex desktop orchestration | 없음 |
| Task 5 | `gpt-5.6-terra` / `high` | `unverified` / `unverified` | Codex desktop orchestration | 없음 |
| Task 6 | `gpt-5.6-terra` / `high` | `unverified` / `unverified` | Codex desktop orchestration | 없음 |
| 최종 독립 검수 (예정) | `gpt-5.6-sol` / `ultra` | `unverified` / `unverified` | 독립 Codex review surface 예정 | 없음 |

orchestration이 requested assignment를 기록했지만 runtime은 실제 model identity나 reasoning을
별도로 증명하지 않았어. 따라서 모델명을 actual 값으로 추정하지 않았고 모두 `unverified`로
기록했어. budget, token, provider cost는 `not-measured`다.

## 검증

| 명령 / 감사 | 실제 결과 |
|---|---|
| `uv run pytest -q tests/test_ai_operating_contract.py tests/test_verify_research_run_manifest.py` | exit 0, **180 passed** (3.18s) |
| `uv run pytest -q` | exit 0, **1,012 passed, 3 skipped** (11.21s) |
| `python3 -m compileall -q scripts/verify_research_run_manifest.py` | exit 0 |
| `python3 -m json.tool` on schema, example, catalog | 세 파일 모두 exit 0 |
| manifest CLI schema-only | example manifest의 `--phase start`와 `--phase final` 모두 exit 0, `RUN_MANIFEST_SCHEMA_OK task=research-run-example permission=P2` |
| `git diff --check` | exit 0 |
| secret field regex | 지정한 `\"(password|api_key|webhook|cookie|signed_url|secret)\"\\s*:` 패턴은 `docs/research`, validator, validator tests에서 **0 matches**. production example/schema에 secret field나 값은 없다. 더 넓은 이름 검색의 일치 항목은 validator의 `FORBIDDEN_SECRET_KEYS`, `secret_field_forbidden` 로직, 계약의 금지 설명, 그리고 테스트의 negative fixture `\"redacted\"`뿐이며 실제 secret 값은 없다. |
| permission regression regex | exit 0. 계약 문서는 `P0~P2`, `P4는 항상 별도 Owner 승인`을 명시하고 validator는 `p3_authorization_missing` 9개, `p4_authorization_missing` 6개 throw site로 fail-closed gate를 노출한다. |

검증 범위는 계약 코드·문서·테스트뿐이며 dataset split이나 media는 접근하지 않았어. production,
GT, behavior/app/R2 mutation과 deployment는 모두 0건이다.

## Git 및 완료 처리

이 보고서 작성 전 검증 대상 HEAD는 위의 `0721b7711c70308b3b990816f6278ca8d6d79a5f`였어.
Task 6 문서 commit·push 뒤에는 `HEAD == @{u}`와 빈 `git status --porcelain`을 다시 확인해서
최종 동기화 결과를 작업 handoff에 기록한다. 보고서가 자기 자신의 commit SHA를 포함하면
commit hash가 바뀌는 self-reference 문제가 있으므로, 최종 Task 6 commit SHA는 handoff 결과를
정본으로 삼는다.

## 다음

R1 Mac mini research runtime foundation 계획 작성은 허용한다. 다만 production 변경, destructive
작업, credential 변경, 비용 확대는 이 검증 판정으로 승인되지 않으며 P3/P4 계약을 새 manifest로
따라야 해.
