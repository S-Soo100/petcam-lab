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
