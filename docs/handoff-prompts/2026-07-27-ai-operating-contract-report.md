# AI 연구 운영 계약 final-review 보정 보고

보정일: 2026-07-28 KST
구현 commits:

- `27515349ceb0e1554f309a9e545594e9d8a237e7` — validator/schema/trusted boundary
- `e961a829e1d45f5b13620edef848f75877aafda0` — strict B와 M→B manifest 불변성
- `16293b054b243c762135d1e955a31b84013f80f1` — M..B 전 구간 불변성, 빈 B 거부,
  parser/schema 의미 경계
- `41476f3eb4399bae18fa26bcd3d9c18ba84a8b91` — canonical RFC3339 timestamp와
  parse-only CLI 의미
- `a96dee9303b5726e3fe9cee5b9db92037a609af8` — canonical documents 기준
- `bf45fb58b34d9a5a74fc0a9e5602d354aef6a94e` — catalog provenance 갱신
- `dc5fc891b16e9bca0129deacd027e310d7246ec3` — RFC3339 schema exact-end 보정
- `fb5b882cd633bdfe911e3e315053a520112a6b46` — exact-end canonical documents 기준
- `18d7e20b9765a80281a082edf8a65f684a093502` — exact-end catalog provenance 갱신
branch: `codex/research-catalog-20260727`

## 판정

`IMPLEMENTED_AWAITING_FINAL_REVIEW`

코드·schema·테스트·정본 문서 보정은 구현됐지만 controller의 post-fix 독립 검수는 아직
끝나지 않았어. 이전 보고서의 최종 verified 판정은 신뢰 경계 검수 전에 너무 일찍 기록된
주장이어서 철회했다. controller 검수와 별도 report-only 승격 commit 전에는 R1 Mac mini
runtime 구현이나 장기 job을 시작하지 않는다.

## prior final review findings

기존 구현에 아래 결함이 있었고 이번 보정에서 계약과 회귀 테스트로 닫았어.

1. start manifest가 repo 밖의 working file이어도 통과했고, manifest 자기 주장만으로 P3/P4를
   승인할 수 있었다.
2. 하나의 `commit_sha`를 start와 final에 동시에 쓰는 자기참조 수명주기로 구현 commit과
   기록 commit을 구분하지 못했다.
3. `implementation_host`를 현재 host와 비교하지 않았고 non-`none` runtime final 검증에
   실행 host/service 증거가 필요하지 않았다.
4. `require_clean=false`와 사용자 `status.showUntrackedFiles=no` 설정이 dirty provenance를
   숨길 수 있었다.
5. JSON Schema와 stdlib parser의 action, conditional, deadline, canonical string 의미가
   달랐다.
6. P3/P4 object 중복을 전체 object equality로만 봐 같은 target identity의 충돌을 허용했다.
7. requested model/reasoning이 비어도 되고 `unverified`를 proven fallback처럼 잘못 취급했다.
8. Preview 상태 어휘가 상위 execution contract와 달랐고, 독립 검수 전에 최종 판정을 기록했다.
9. AGENTS/CLAUDE 진입점과 catalog canonical set의 구조 회귀가 테스트되지 않았다.

## 구현 결과

- `source.commit_sha=A`, start manifest commit `M`, implementation commit `B`, final record commit
  `C`를 분리했다. `M^ == A`, `C^ == B`, `M` ancestor of `B`를 확인하고 M/C는 manifest만
  바꾸는 전용 commit으로 강제한다.
- `B != M`을 요구하고 `git rev-list M..B`의 모든 reachable commit에서 manifest blob이 M과
  byte-identical인지 확인한다. 중간 변경 후 B에서 복원하는 우회와 manifest 외 tracked
  endpoint diff가 없는 빈 implementation도 거부한다.
- start는 lifecycle/actual/fallback 필드가 모두 `null`이어야 한다. final은 M의 원본
  manifest를 Git object에서 읽어 다섯 provenance 필드 외 변경을 거부한다.
- current manifest는 `execution_repo` 내부의 tracked file이어야 하고 현재 HEAD blob과
  byte-identical이어야 한다.
- P3/P4는 주입된 trusted approval verifier가 없으면 fail-closed한다. P4는 별도
  `approval_ref`도 요구한다. 기본 CLI에는 approval backend가 없다.
- 주입된 current-host lookup과 `implementation_host`를 exact canonical match로 비교한다.
  non-`none` runtime의 final 검증은 runtime attestation verifier 없이는 실패한다.
- `require_clean=true`를 고정하고
  `git status --porcelain=v1 --untracked-files=all --ignore-submodules=none`을 사용한다.
- P3/rollback/residue, runtime service/host guard/lock, disposable DB/residue, rollback
  probe/rollback/residue 관계를 강제한다.
- requested model/reasoning은 필수다. actual identity가 미확인이면
  `unverified`/`unverified`와 `fallback_reason=null`을 기록한다. 실제 차이가 확인된 경우에만
  fallback 이유가 필수다.
- Draft 2020-12 schema는 structural superset이고 stdlib parser가 semantic authority다. 공통
  corpus는 양쪽이 표현할 수 있는 구조 규칙만 공유한다. P3/P4 projected identity uniqueness와
  requested/actual fallback 관계는 parser-only semantic regression으로 분리했다. production
  validator에는 stdlib만 사용하고 `jsonschema`는 dev dependency로만 추가했다.
- raw string의 앞뒤 whitespace와 control character를 strip/canonicalize하지 않고 schema와
  parser가 모두 거부한다. `approved_at`/non-null `deadline`은 extended RFC3339
  `YYYY-MM-DDTHH:MM:SS[.fraction](Z|±HH:MM)`만 허용한다.
- `--parse-only`와 호환 alias `--schema-only`는 stdlib parser를 실행하고
  `RUN_MANIFEST_PARSE_OK`를 출력한다. 이 marker는 Git/host/runtime/approval 검증 증거가 아니다.
- preview 어휘는 `PREVIEW_READY`로 상위 계약과 맞췄다.

## 모델 provenance

| 작업 | requested | actual | surface | fallback |
|---|---|---|---|---|
| final-review 보정 구현 | `gpt-5.6-sol` / `xhigh` | `unverified` / `unverified` | Codex desktop orchestration | `null` |
| controller post-fix 검수 | 별도 controller가 기록 | `unverified` / `unverified` | 독립 review 예정 | `null` |

runtime이 실제 model identity와 reasoning을 증명하지 않았으므로 actual 값은 추정하지 않았어.
token, provider cost, wall budget은 `not-measured`다.

## 검증

| 명령 / 감사 | 현재 결과 |
|---|---|
| `uv run pytest -x -q tests/test_ai_operating_contract.py tests/test_verify_research_run_manifest.py` | `295 passed` |
| `uv run pytest -x -q` | `1127 passed, 3 skipped` |
| `uv run python -m compileall -q scripts/verify_research_run_manifest.py` | exit 0 |
| schema, example, catalog `python3 -m json.tool` | 세 파일 모두 exit 0 |
| Draft 2020-12 schema check + example format validation | `DRAFT_2020_12_EXAMPLE_OK` |
| shared structural + parser-only semantic corpus | `30 passed` |
| timestamp schema without format checker | `12 passed` |
| manifest CLI parse-only start | `RUN_MANIFEST_PARSE_OK task=research-run-example permission=P2` |
| secret-shaped JSON field scan | production docs/validator에서 0 matches |
| protected contract diff | `docs/agent-execution-contract.md`, `scripts/verify_agent_handoff.py` 변경 0 |
| `git diff --check` | exit 0 |

검증 범위는 계약 코드·schema·문서·테스트뿐이야. production, Mac mini, dataset, DB, R2,
credential, deployment mutation은 모두 0건이다.

## Git과 다음 gate

구현 정본은 `dc5fc891b16e9bca0129deacd027e310d7246ec3`, canonical documents 기준은
`fb5b882cd633bdfe911e3e315053a520112a6b46`, catalog provenance commit은
`18d7e20b9765a80281a082edf8a65f684a093502`다. 이 report를 포함하는 report-only commit은
자신의 SHA를 본문에 넣지 않는다. HEAD/upstream/clean 상태는 handoff 결과에 기록하며 push는
controller 검수 전에는 하지 않는다.

다음 허용 행동은 controller의 post-fix 독립 review뿐이야. 검수가 통과하면 별도 report-only
commit에서 판정을 승격하고, 그 뒤에만 R1 전용 manifest와 구현계획을 시작한다.

## final-fix-report

- lifecycle: `git rev-list M..B`의 모든 commit에서 start manifest blob 불변을 검증하고,
  M..B endpoint tree에 manifest 외 tracked diff가 없으면 `implementation_change_missing`으로
  거부한다. change→restore와 빈 B 회귀 테스트가 RED→GREEN을 확인했다.
- provenance: catalog의 자기참조 `canonical.commit`을
  `canonical.implementation_commit=16293b054b243c762135d1e955a31b84013f80f1`과
  `canonical.documents_commit=bf31b0576a83d211488b3d4fd21dbd02ee73f6f4`로 분리했다.
  canonical documents의 현재 bytes가 `documents_commit:path` bytes와 같은지 테스트한다.
- authority: raw string의 앞뒤 whitespace/control을 schema와 parser가 함께 거부한다. schema는
  structural superset이고 stdlib parser가 semantic authority다. shared structural corpus와
  parser-only P3/P4 identity·model fallback regression을 분리했다.

### 잔여 재검수 보정

- timestamp: `approved_at`과 non-null `deadline`을 canonical extended RFC3339로 통일했다.
  schema는 `format`에만 의존하지 않고 전체 `pattern`으로 padding/control, space/basic/week
  date, offset seconds를 거부한다. parser도 같은 fullmatch 뒤 aware datetime을 검증한다.
- CLI 의미: production stdlib-only 원칙을 유지하기 위해 Draft schema runtime dependency를
  추가하지 않았다. 대신 실제 실행 의미를 `--parse-only`/`RUN_MANIFEST_PARSE_OK`로 고쳤고,
  기존 `--schema-only`는 같은 parser 동작의 호환 alias로만 남겼다.
- provenance: implementation은
  `41476f3eb4399bae18fa26bcd3d9c18ba84a8b91`, canonical documents는
  `a96dee9303b5726e3fe9cee5b9db92037a609af8`로 분리했고 catalog-only commit
  `bf45fb58b34d9a5a74fc0a9e5602d354aef6a94e`에서 원장만 갱신했다.
- 판정은 `IMPLEMENTED_AWAITING_FINAL_REVIEW`를 유지한다. 이번 보정은 controller final review를
  대체하지 않는다.

### exact-end 잔여 보정

- schema의 RFC3339 pattern 끝 `$`를 control negative-lookahead와
  `(?![\\s\\S])` exact-end로 교체했다. JSON Schema에서 `$`가 final newline 직전에도
  일치하는 우회를 approved_at/deadline 양쪽에서 닫았다.
- 두 필드의 trailing `\n`을 shared structural corpus와 format checker 없는 schema corpus에
  각각 추가했다. RED `4 failed, 34 passed`에서 GREEN `38 passed`로 전환했다.
- stale 실행 계획도 `--parse-only`/`RUN_MANIFEST_PARSE_OK`로 갱신했다.
- provenance는 implementation `dc5fc891b16e9bca0129deacd027e310d7246ec3`,
  canonical documents `fb5b882cd633bdfe911e3e315053a520112a6b46`, catalog-only
  `18d7e20b9765a80281a082edf8a65f684a093502`로 다시 분리했다.
- 판정은 계속 `IMPLEMENTED_AWAITING_FINAL_REVIEW`다.
