# 연구 중앙 카탈로그

> 마지막 정리: 2026-07-27 · 기계용 원장: [`catalog.json`](catalog.json)

이 디렉터리는 연구의 **찾기·판정·재개점**을 모은 중앙 카탈로그야. 원문 설계·시험지·보고서는
각 실험과 레포에 그대로 남아 있고, 여기서는 옮기거나 요약으로 대체하지 않아.

## 지금 할 일

1. [`AI 연구 운영 계약`](AI-OPERATING-CONTRACT.md)의 final-review 보정 구현을 controller가 독립
   검수한다. 현재 상태는 `IMPLEMENTED_AWAITING_FINAL_REVIEW`다.
2. 검수 뒤 R1 전용 run manifest를 A→M→B→C lifecycle로 만들고 host·clean Git·승인 gate를
   통과한다.
3. [`RBA 연구 시스템 v1`](../superpowers/specs/2026-07-27-rba-research-system-v1-design.md)의 R1 Mac mini 기반부터 하나씩 진행한다.
4. 사람 이중 블라인드 GT는 2~3주 계속 축적한다.
5. dataset-v1 split과 현재 worker 기준선이 동결되기 전에는 prompt·candidate model 성적을 확정하지 않는다.

## 상태표

| ID | 상태 | 결론 | 다음 허용 행동 |
|---|---|---|---|
| `ai-operating-contract-v1` | 운영 중·최종검수 대기 | A→M→B→C, trusted approval, host/runtime provenance를 fail-closed manifest로 고정 | controller 독립 final review |
| `rba-research-system-v1` | 계획됨 | Mac mini → dataset-v1 → 재기준선 → 후보평가 순서 동결 | written spec 확인 후 R1 계획 작성 |
| `owner-gt-audit-20260727` | 제한적 유효 | 172 GT는 진단 입력으로 유효, 일반화에는 부족 | fresh 이중 블라인드 holdout과 결합 |
| `owner-gt-python-evidence-benchmark-20260727` | 기각 | `roi_mean` 공통 motion 신호 가설 불성립 | 새 camera-specific 가설은 새 시험지 필요 |
| `unified-gt-failure-audit-20260727` | 제한적 유효 | historical failure 후보를 좁힘 | 후보 생성·재현에만 사용 |
| `visibility-bbox-roi-20260727` | 기각 | 현행 반복 실패 표적이 최소치보다 부족 | 판정 변동·fresh GT 후 재제안 가능 |
| `vlm-risk-consensus-shadow-v1` | 계획됨 | 위험 action만 3회 shadow로 변동 측정 | Lab 원장 구현 → worker 구현 → 별도 배포 승인 |
| `double-blind-fresh-ground-truth` | 진행 중 | 두 라벨러 독립 제출과 Owner 해소를 축적 | 2~3주 뒤 VLM shadow와 대조 |
| `python-evidence-croi-throughput` | 제한적 검증 | 전처리 처리량은 확인 | 정확도·자동제외 근거로 사용 금지 |
| `local-router-v0-v2-validity-audit` | 대체됨 | 이전 결과는 adoption 무효 | router-cost-v2의 fresh holdout만 재개 가능 |
| `gate-v3-human-holdout` | 계획됨 | Gate는 visibility/bbox evidence 센서 | 다환경 사람 GT·future holdout 확보 |

## 트랙 경계

| 트랙 | 하는 일 | 하지 않는 일 |
|---|---|---|
| 사람 GT | 독립 라벨·불일치 해결·fresh holdout | 한 사람 의견을 합의 GT로 취급 |
| Claude/VLM 품질 | 같은 입력에서 판정 정확도·변동 측정 | local router 결과를 정답으로 사용 |
| Python Evidence | 처리량·raw sensor evidence 측정 | 행동 자동 판정·자동 제외 |
| Gate | 게코 보임·confidence·bbox evidence | drinking/feeding 같은 행동 확정 |
| Local router | cloud VLM 호출 우선순위 연구 | 자동 skip/auto-label |

## 원문으로 가기

- 현재 연구 정본: [`../specs/next-session.md`](../../specs/next-session.md)
- AI 연구 실행 계약: [`AI-OPERATING-CONTRACT.md`](AI-OPERATING-CONTRACT.md) · [`RUN-MANIFEST.schema.json`](RUN-MANIFEST.schema.json) · [`RUN-MANIFEST.example.json`](RUN-MANIFEST.example.json) · [`validator`](../../scripts/verify_research_run_manifest.py)
- 실험 전체 인덱스: [`../../experiments/INDEX.md`](../../experiments/INDEX.md)
- Owner GT → ROI → consensus 정리: [`../handoff-prompts/2026-07-27-owner-gt-visibility-consensus-closure.md`](../handoff-prompts/2026-07-27-owner-gt-visibility-consensus-closure.md)
- 보존·정리 정책: [`RETENTION.md`](RETENTION.md)

## 카탈로그 갱신 규칙

- 새 연구는 TEST-SHEET와 REPORT가 생긴 뒤 `catalog.json`에 추가한다.
- 결과가 기각·보류여도 삭제하지 말고 `do_not`과 재등판 조건을 기록한다.
- 외부 레포 문서는 `repo-relative path + 확인 commit`으로 링크한다.
- 원문과 카탈로그가 다르면 원문이 우선이며, 다음 정리에서 카탈로그를 고친다.

## Run manifest 사용 주의

- `--schema-only` 성공 marker는 구조 검증만 뜻한다. stdlib parser의 의미 authority나 Git
  lifecycle, 현재 host, Owner 승인, runtime attestation의 증거가 아니다.
- Draft 2020-12 schema는 structural superset이고 stdlib parser가 semantic authority다. 공통
  corpus는 공유 가능한 구조 규칙만 다루며 P3/P4 target identity 충돌과 model fallback 관계는
  parser-only regression으로 고정한다.
- 문자열을 strip해서 받아들이지 않는다. 앞뒤 whitespace와 control character는 schema와
  parser가 모두 거부한다.
- P3/P4는 manifest에 적었다는 사실만으로 승인되지 않는다. trusted approval verifier가 없는
  기본 CLI는 fail-closed한다.
- non-`none` runtime의 final 검증도 runtime attestation verifier가 없는 기본 CLI에서는
  fail-closed한다.
- 실제 실행은 A(base) → M(start manifest 전용 commit) → B(implementation) → C(final record
  전용 commit) 순서를 지킨다.
