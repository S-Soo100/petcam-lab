# Task 4 execution-quality fix 보고서

## 상태

- 구현 상태: `DONE`
- 운영 재실행 상태: 미실행. Task 4 executor가 새 v2 attempt에서 수행한다.
- 라이브 DB/R2/YOLO 호출: 0
- v1 artifact: 인공 shortage 실패 provenance로 동결, 덮어쓰기·CVAT 업로드 금지
- 새 artifact: `/Users/baek-end/private-rba/yolo26n-v22-candidates/attempt-20260810-owner-v2/`

## 확인한 원인

- eligible inventory 9,319 source의 raw bucket은 hard-positive 5,564 / hard-negative 3,755였다.
- 기존 `24 frames/night` 계약은 24-frame probe source 하나가 night cap 전체를 차지하게 했다.
- hard-positive 선처리 공유 counter 때문에 겹치는 night의 hard-negative가 0 source로 굶었다.
- 최종 exact SHA/dHash 중복 또는 unreadable frame 거부 뒤에 ranked probe/source backfill이 없었다.

## 수정 결과

- inventory cap을 `--probe-max-sources-per-night 8`로 교체하고 옛 frame 기반 flag는 parser에서 거부한다.
- bucket을 번갈아 선택해 공용 8 source/night cap 아래 HP 220/HN 100 exact selection을 만든다.
- metadata-only pool/selection summary를 R2 GET 전에 기록하고 exact가 아니면 download 0회로 종료한다.
- 최종 승인 시 같은 source의 남은 ranked probe, 이후 같은 bucket reserve source를 소비한다.
- source 2장, camera-night 12장, global exact SHA, source-local dHash 규칙과 bucket 간 backfill 금지를 유지한다.
- private manifest에는 inventory pool/selection 및 bucket별 planned/accepted/deduplicated/unreadable/shortfall 집계를 남긴다.
- reviewer-facing CSV/ZIP에는 prediction box와 source ID를 추가하지 않았다.

## 검증

- TDD RED: 새 source-cap CLI가 기존 parser에서 거부됨을 확인했다.
- TDD RED: accepted materialization helper 부재와 inventory shortage의 선행 R2 GET을 각각 재현했다.
- 회귀: Task 2/Task 3/v2.1 관련 테스트 `69 passed`.
- `py_compile` 통과, `git diff --check` 통과.
- DB/R2 write API 감사 0건, 실행 문서의 옛 frame 기반 flag 0건.
- 아래 exact 구현 commit만 handoff한다.

## 남은 운영 확인

- 새 v2 attempt의 실제 metadata preflight가 HP 220/HN 100인지 확인한 뒤에만 download한다.
- 실제 accepted 320장이 아니면 CVAT에 올리지 않고 manifest의 bucket별 shortage 집계를 보고한다.

## Round 2 execution-quality hardening

### 추가 원인

- `_extract_probes`가 decode/imwrite 실패를 row 없이 버려 최종 `unreadable=0`처럼 보일 수 있었다.
- materialization summary가 night cap과 source/candidate pool exhaustion을 구분하지 않았다.
- 최종 manifest가 inventory download/missing 집계를 전달하지 않았다.
- CLI output 경로와 기존 partial artifact를 제한하지 않아 v1 또는 stale v2 산출물을 덮거나 섞을 수 있었다.

### 추가 수정

- source별 `requested/readable/decode_failed/imwrite_failed`를 private analyzed ledger에 보존하고,
  final manifest에는 bucket aggregate만 기록한다.
  `readable`은 decode 성공 수이며 실제 저장 probe 수는 `readable - imwrite_failed`다.
- final materialization 집계에 `candidate_sources`, `candidate_exhausted`,
  `source_exhausted`, `night_cap_blocked`, extraction/duplicate/unreadable/shortfall을 기록한다.
  `candidate_exhausted`는 남은 frame quota 수, `source_exhausted`는 소진된 source 수다.
- inventory downloaded/missing source 및 bucket count를 final manifest까지 전달한다.
- inventory/analyze 모두 exact v2 output 절대경로만 허용하고 외부 read 전 fresh-output preflight를 수행한다.
- analyze는 정상 inventory artifact 외 probe/review/analyzed/manifest/ZIP 등 partial output을 거부한다.

### Round 2 검증

- TDD RED: decode/imwrite failure 반환 누락, night-cap reason 누락, download summary 누락,
  output path/fresh-output gate 누락, analyze provenance 전달 누락을 각각 재현했다.
- scoped v2.1/Task 2/Task 3/Task 4 회귀 테스트 `80 passed`.
- runner/test `py_compile`과 scoped `git diff --check`를 통과했다.
- DB/R2 write API 감사 0건, 실행 문서의 옛 frame 기반 flag 0건을 확인했다.
- 라이브 DB/R2/YOLO 호출은 하지 않았다.

## Task4b official review round 2 — code snapshot binding

- 상태: `DONE`
- implementation commit A: `a9429320ca3bb2a0ecce0826c9a38f6521bab49d`
- 실행 파일 SHA-256:
  - `scripts/run_yolo26n_v22_hp_reserve_merge.py`:
    `7cc77bbeee3cc736276dba1471774e6e42244a085b33bcf9acbc96c8242da73c`
  - `scripts/run_yolo26n_v22_candidate_mining.py`:
    `33610d52916b0a4a44135172d781dee58342d4a67f8fae5ae8abcb7bb43706bb`
  - `scripts/build_yolo26n_v22_candidate_queue.py`:
    `a692f0680e9fdfcdaac5ced0da937593b9edc1135868a9456a990b62cee201a9`
- TDD: helper 두 파일/runner tamper, extra/missing, stale source commit, eager import 순서를 RED로 재현하고
  snapshot gate 및 lazy helper import로 수정했다.
- 검증: Task4b `37 passed`, scoped `127 passed`, full `1390 passed, 5 skipped`, pycompile/diff/write audit PASS.
- implementation과 docs가 서로 hash를 참조하는 self-reference를 피하려고 A(code+tests)와
  B(docs literal pin) 두 commit으로 분리했다. archive와 runtime verification은 A를 대상으로 한다.
- 라이브 DB/R2/YOLO 호출은 하지 않았다.
