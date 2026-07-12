# Router Research Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검증 오염과 비용 목표 불일치가 확인된 `VLM 검증 전략 연구`를 안전하게 중단하고, 재사용 가능한 인프라는 보존하면서 기존 결과를 탐색용으로 재분류한 뒤 독립적인 비용 검증을 다시 시작할 준비를 한다.

**Architecture:** 기존 코드·DB·리뷰 라벨을 삭제하지 않고 append-only 감사 기록으로 정정한다. 기존 v1/v1.1 산출물은 `exploratory / invalid-for-adoption`으로 강등하고, 미래 날짜의 비중복 운영 영상만 새 holdout으로 허용한다. 새 연구는 즉시 호출률이 아니라 eventual VLM 호출률·원화 비용·P0 event recall·사람 검수 시간을 사전 등록한다.

**Tech Stack:** Markdown research records, Codex task management, Git, Python 3.12/pytest for later metric implementation, Supabase read-only audit.

## Global Constraints

- 기존 공유 작업트리의 사용자/다른 작업 변경을 되돌리거나 덮어쓰지 않는다.
- 기존 DB row, review label, report artifact를 삭제하지 않는다.
- `reset --hard`, 강제 push, branch 삭제를 사용하지 않는다.
- 커밋은 사용자 명시 승인 전까지 하지 않는다.
- 기존 72건, v1 demote 60건, dataset203, v1/v1.1 150건은 독립 holdout으로 재사용하지 않는다.
- `cloud_later`는 eventual VLM 비용 발생 route로 계산한다.
- `review_candidate`는 VLM 비용 또는 사람 검수 비용이 발생하는 abstention route로 계산한다.
- 각 Task가 끝날 때 사용자에게 결과를 보고하고 다음 Task 진행 전 확인받는다.

---

### Task 1: 기존 VLM 검증 작업 종료·보관

**Files:**
- Create: `docs/superpowers/plans/2026-07-12-router-research-reset.md`
- No existing repository files modified.

**Interfaces:**
- Consumes: Codex task id `019f445d-968d-7331-9123-54bbecbe6aa1`
- Produces: archived Codex task; 이후 자동/수동 진행이 중단된 상태

- [x] **Step 1: 현재 작업 상태를 읽기 전용으로 확인한다**

Codex task 목록에서 제목 `VLM 검증 전략 연구`, id `019f445d-968d-7331-9123-54bbecbe6aa1`, status `idle`을 확인한다.

- [x] **Step 2: 작업을 archive한다**

`set_thread_archived`에 `threadId=019f445d-968d-7331-9123-54bbecbe6aa1`, `archived=true`를 전달한다.

- [x] **Step 3: archive 결과를 검증한다**

같은 task를 다시 조회해 archived 처리 성공을 확인한다. repository 파일과 git index에는 변경을 만들지 않는다.

- [x] **Step 4: 사용자 체크포인트**

작업 보관 성공과 다음 단계가 `무효성 감사 기록`임을 보고하고 멈춘다.

### Task 2: 연구 무효성 감사 기록

**Files:**
- Create: `reports/router-research-validity-audit-20260712/REPORT.md`

**Interfaces:**
- Consumes: v1/v1.1 report, review queue CSV 두 개, router scripts, research-testing protocol
- Produces: 삭제 없는 append-only 감사 판정 SOT

- [x] **Step 1: 감사 근거를 고정한다**

다음 근거를 REPORT에 명시한다.

- v1.1 150건 중 v1 150건과 중복 123건
- v1.1 demote 57건 중 기존 v1 demote와 중복 30건
- 72건·dataset203·검수 60건을 본 뒤 threshold를 반복 수정함
- `cloud_now -> cloud_later`는 eventual 호출을 제거하지 않음
- pass 로직이 total cost, holdout, review burden을 포함하지 않음
- `random_control`이 `started_at` 정렬 앞 30건임

- [x] **Step 2: 판정 범위를 분리한다**

REPORT에 다음 decision을 기록한다.

```text
metadata/review infrastructure: retain
v1 failure evidence: retain as exploratory negative evidence
v1.1 performance claim: invalid-for-adoption
cost reduction claim: not-measured
production eligibility: rejected
```

- [x] **Step 3: 자체 검토한다**

`TBD|TODO|FIXME`가 없고, 기존 데이터를 삭제하거나 성능을 새로 주장하지 않는지 확인한다.

- [x] **Step 4: 사용자 체크포인트**

감사 문서 링크와 핵심 판정을 보고하고 멈춘다.

### Task 3: 기존 결과를 탐색용으로 강등

**Files:**
- Modify: `reports/router-care-guard-v1-20260710/REPORT.md`
- Modify: `reports/router-care-guard-v1_1-20260711/REPORT.md`
- Modify: `specs/experiment-local-router-without-detector.md`
- Modify: `experiments/INDEX.md`
- Modify: `specs/README.md`

**Interfaces:**
- Consumes: Task 2 audit decision
- Produces: 모든 진입점에서 동일하게 보이는 `exploratory / invalid-for-adoption` 상태

- [x] **Step 1: 보고서 상단에 비파괴적 validity banner를 추가한다**

기존 결과 본문은 보존하고 다음 의미를 상단에 추가한다.

```text
Validity: exploratory / invalid-for-adoption
Reason: post-hoc threshold tuning, evaluation overlap, total VLM cost not measured
Canonical audit: reports/router-research-validity-audit-20260712/REPORT.md
```

- [x] **Step 2: experiment spec 상태를 강등한다**

`experiment-local-router-without-detector.md`의 현재 상태를 `⏸ 중단 — 결과 감사 후 exploratory로 강등`으로 변경하고 v0/v1/v2/operational/care-guard 결과가 production 채택 근거가 아님을 기록한다.

- [x] **Step 3: 중앙 인덱스를 갱신한다**

`experiments/INDEX.md`와 `specs/README.md`에서 local router 후속 결과를 감사 문서에 연결하고 `invalid-for-adoption` 상태를 명시한다.

- [x] **Step 4: 링크와 상태 일관성을 검증한다**

`rg -n "invalid-for-adoption|router-research-validity-audit"`로 다섯 진입점이 모두 갱신됐는지 확인한다.

- [x] **Step 5: 사용자 체크포인트**

수정 파일 목록과 기존 결과를 삭제하지 않았음을 보고하고 멈춘다.

### Task 4: 데이터 역할 재분류

**Files:**
- Create: `reports/router-research-validity-audit-20260712/DATA-ROLE.md`
- Create: `reports/router-research-validity-audit-20260712/overlap-summary.csv`

**Interfaces:**
- Consumes: dataset203, operational 72, v1/v1.1 review queue and labels
- Produces: future 연구가 참조할 train/EDA/forbidden-holdout registry

- [x] **Step 1: 데이터 그룹을 등록한다**

다음 역할을 기록한다.

| 데이터 | 허용 역할 | 금지 역할 |
|---|---|---|
| dataset203 | feature EDA, regression, training | 독립 router holdout |
| operational 72 | sentinel/regression, training | 독립 holdout |
| v1 demote 60 | failure analysis, training | 독립 holdout |
| v1 review 150 | EDA/training | 독립 holdout |
| v1.1 review 150 | EDA/training | 독립 holdout |
| future time-split nights | frozen-policy evaluation | threshold tuning |

- [x] **Step 2: 중복 요약을 저장한다**

CSV에 최소 다음 행을 기록한다.

```csv
left,right,left_n,right_n,overlap_n,valid_as_independent_holdout
router-care-guard-v1-eval-20260710,router-care-guard-v1_1-eval-20260711,150,150,123,no
v1_guard_demote,v1_1_guard_demote,60,57,30,no
```

- [x] **Step 3: 사용자 체크포인트**

향후 holdout으로 재사용하면 안 되는 데이터 목록을 보고하고 멈춘다.

### Task 5: 독립 비용 검증 시험지 작성

**Files:**
- Create: `experiments/router-cost-v2/TEST-SHEET.md`
- Modify: `experiments/INDEX.md`

**Interfaces:**
- Consumes: Task 2 audit, Task 4 data-role registry
- Produces: threshold 수정 전 동결되는 새 연구 계약

- [x] **Step 1: H0/H1과 route 비용 의미를 고정한다**

```text
H0: frozen router는 전수 저비용 VLM baseline 대비 총비용을 줄이지 못하거나 P0 event recall을 허용 범위 이상 훼손한다.
H1: frozen router는 P0 event recall 허용 범위를 지키면서 total eventual VLM cost를 유의미하게 줄인다.
```

Route 비용은 `cloud_now`, `cloud_later`, `review_candidate`, `activity_only`별 실제 후속 처리 계약으로 정의한다.

- [x] **Step 2: 독립 표본 규칙을 고정한다**

- 시험지 작성 이후 촬영된 미래 날짜만 사용
- 기존 camera/개체와 신규 camera/개체를 층화
- 같은 밤의 clip을 train/eval에 분할하지 않음
- sample seed와 clip list를 inference 전 고정
- 평가 결과를 본 뒤 threshold를 수정하면 해당 set을 training으로 강등

- [x] **Step 3: 필수 지표와 decision gate를 고정한다**

- eventual VLM call rate
- KRW/camera/night
- P0 event recall과 95% confidence interval
- maximum analysis delay
- human review minutes/night
- abstention/review_candidate rate
- camera/개체/밝기별 최악 성능

초기 gate는 다음 숫자로 제안하고 TEST-SHEET 사용자 검토에서 그대로 승인하거나 실행 전에 수정한다.

```text
future evaluation window: 연속 14박 이상
minimum labeled clips: 300
minimum labeled P0 events: 30
total eventual VLM cost reduction: 전수 저비용 VLM 대비 20% 이상
P0 event recall drop: 같은 표본 baseline 대비 2pp 이하
P0 -> activity_only: 0건
review_candidate rate: 30% 이하
human review burden: 카메라 1대·1박당 5분 이하
cloud_now maximum delay: 5분 이하
cloud_later maximum delay: 12시간 이하
```

- [x] **Step 4: 사용자 검토 관문**

TEST-SHEET를 사용자에게 제시한다. 사용자 승인 전 inference, threshold tuning, DB write를 하지 않는다.

## Final Verification

- [x] 기존 Codex task가 archived 상태다.
- [x] 감사 REPORT가 기존 결과와 새 판정을 분리한다.
- [x] v1/v1.1 결과가 어느 진입점에서도 production-valid로 보이지 않는다.
- [x] 오염된 데이터가 future holdout에서 제외된다.
- [x] 새 비용 연구는 TEST-SHEET 승인 전 실행되지 않는다.
- [x] 커밋은 사용자 명시 승인 전까지 생성하지 않는다.
