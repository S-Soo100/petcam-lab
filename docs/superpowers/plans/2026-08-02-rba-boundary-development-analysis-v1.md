# RBA 사건 경계 Development 분석 v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 완료된 74개 사람 사건 경계를 무결성 검증하고, 최종 사건 묶음·사람 품질 지표·gap threshold utility를 결정론적으로 계산해 local VLM baseline 진입 여부를 판정한다.

**Architecture:** pure Python analyzer가 seed manifest와 production SELECT snapshot을 받아 final boundary GT, 익명 사건 묶음, aggregate metrics를 만든다. 별도 runner는 Mac mini에서 기존 `0600` env를 읽어 production을 SELECT만 하고, 같은 salt로 analyzer를 세 번 실행해 hash가 일치할 때 private artifact와 public report를 각각 한 번만 쓴다.

**Tech Stack:** Python 3.12, dataclasses, hashlib/json, Supabase Python client, pytest, uv

## Global Constraints

- pinned experiment: `rba-event-sequence-review-v2`
- pinned manifest: `edd3f2c230adacb70c0b8bc70072eb632eb0ac48718bdd1ffbeca88649e9dfca`
- expected production counts: cohort pair row `120`, effective assigned pair `74`, assignment `148`, submission `148`, resolution `26`
- source artifact: `/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-event-media-eligibility-v1-20260731T124018Z/boundary-pairs.json`
- private output: `/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-boundary-development-v1`
- private directory/file mode: `0700/0600`, no-overwrite
- production DB: SELECT only; RPC/INSERT/UPDATE/DELETE `0`
- R2/frames/Python Evidence/Gate/VLM/service calls: `0`
- historical holdout, local VLM 실행, production event schema: 범위 밖
- raw UUID, reviewer identity, reason 원문, camera/date, secret은 public report에 `0`
- user-owned `AGENTS.md` 변경은 보존하고 commit에 포함하지 않는다.

---

## File Structure

- Create `experiments/rba-boundary-development-v1/TEST-SHEET.md`: 실행 전 고정 가설·지표·판정 계약
- Create `experiments/rba-boundary-development-v1/REPORT.md`: aggregate 실행 결과
- Create `scripts/rba_boundary_development_analysis.py`: pure validation, metrics, event grouping, rendering
- Create `scripts/run_rba_boundary_development_analysis.py`: production SELECT-only runner와 private/public writer
- Create `tests/test_rba_boundary_development_analysis.py`: pure analyzer TDD
- Create `tests/test_run_rba_boundary_development_analysis.py`: runner safety·determinism·redaction TDD
- Modify `docs/superpowers/specs/2026-08-02-rba-boundary-development-analysis-v1-design.md`: checklist·verdict 반영
- Modify `specs/next-session.md`: 최신 실행 결과 정본
- Modify `experiments/rba-event-grouping-shadow-v2/TEST-SHEET.md`: 과거 R2 blocker와 이번 development 결과의 관계만 append

---

### Task 1: TEST-SHEET 선동결

**Files:**
- Create: `experiments/rba-boundary-development-v1/TEST-SHEET.md`

**Interfaces:**
- Consumes: approved design and pinned production provenance
- Produces: scorer가 구현 전에 따라야 할 exact hypotheses, metrics, verdict rules

- [x] **Step 1: TEST-SHEET를 작성한다**

문서에 다음 계약을 정확히 넣는다.

```markdown
# RBA 사건 경계 Development 분석 v1 TEST-SHEET

**상태:** FROZEN_BEFORE_SCORING
**질문:** 완료된 사람 경계로 누락·중복 없는 사건 GT를 만들 수 있는가?

## Pinned input
- experiment_id: rba-event-sequence-review-v2
- manifest_digest: edd3f2c230adacb70c0b8bc70072eb632eb0ac48718bdd1ffbeca88649e9dfca
- total/effective/submission/resolution: 120/74/148/26

## GT verdict
- count/provenance/adjacency 위반: BLOCKED_GT_INTEGRITY
- final uncertain > 0: HOLD_UNRESOLVED_BOUNDARY
- 위반 0 + 3회 hash 동일: DEVELOPMENT_EVENT_GT_READY_FOR_LOCAL_VLM_BASELINE

## Utility verdict
- human final event reduction >= 0.15이고 zero-overmerge threshold 존재: PASS
- 그 외: EVENT_GT_READY_ROUTER_UTILITY_HOLD

agreement와 kappa는 descriptive이며 GT 채택 gate가 아니다.
```

- [x] **Step 2: 문서 계약을 점검한다**

Run:

```bash
rg -n "FROZEN_BEFORE_SCORING|120/74/148/26|BLOCKED_GT_INTEGRITY|HOLD_UNRESOLVED_BOUNDARY|DEVELOPMENT_EVENT_GT_READY_FOR_LOCAL_VLM_BASELINE|0.15|agreement.*descriptive" experiments/rba-boundary-development-v1/TEST-SHEET.md
```

Expected: 모든 marker가 한 번 이상 출력되고 `TBD|TODO`는 0건이다.

- [x] **Step 3: 문서만 commit한다**

```bash
git add experiments/rba-boundary-development-v1/TEST-SHEET.md
git commit -m "docs: 사건 경계 development 시험지 동결"
```

---

### Task 2: Pure analyzer TDD

**Files:**
- Create: `scripts/rba_boundary_development_analysis.py`
- Create: `tests/test_rba_boundary_development_analysis.py`

**Interfaces:**
- Consumes: seed manifest rows and `StudySnapshot`
- Produces: `analyze_study(snapshot: StudySnapshot, manifest: dict[str, object], salt: bytes) -> AnalysisResult`
- Produces: `render_public_report(result: AnalysisResult) -> str`

- [x] **Step 1: failing integrity tests를 작성한다**

다음 dataclass 계약을 import하는 테스트를 먼저 쓴다.

```python
from scripts.rba_boundary_development_analysis import (
    AnalysisBlocked,
    StudySnapshot,
    analyze_study,
)

def test_count_drift_is_blocked(snapshot, manifest):
    broken = dataclasses.replace(snapshot, submissions=snapshot.submissions[:-1])
    with pytest.raises(AnalysisBlocked, match="COUNT_DRIFT"):
        analyze_study(broken, manifest, b"fixed-salt")

def test_unnecessary_or_missing_resolution_is_blocked(snapshot, manifest):
    with pytest.raises(AnalysisBlocked, match="RESOLUTION_SET_MISMATCH"):
        analyze_study(dataclasses.replace(snapshot, resolutions=()), manifest, b"fixed-salt")

def test_manifest_provenance_mismatch_is_blocked(snapshot, manifest):
    manifest["manifest_sha256"] = "0" * 64
    with pytest.raises(AnalysisBlocked, match="COHORT_PROVENANCE"):
        analyze_study(snapshot, manifest, b"fixed-salt")
```

- [x] **Step 2: RED를 확인한다**

Run:

```bash
uv run pytest tests/test_rba_boundary_development_analysis.py -q
```

Expected: import error because module does not exist.

- [x] **Step 3: 최소 dataclass와 integrity validator를 구현한다**

`scripts/rba_boundary_development_analysis.py`에 다음 public types를 만든다.

```python
Decision = Literal["same_event", "different_event", "uncertain"]

@dataclass(frozen=True, slots=True)
class AssignmentRow:
    assignment_id: str
    pair_id: str
    reviewer_id: str
    reviewer_role: str

@dataclass(frozen=True, slots=True)
class SubmissionRow:
    assignment_id: str
    pair_id: str
    reviewer_id: str
    decision: Decision

@dataclass(frozen=True, slots=True)
class ResolutionRow:
    pair_id: str
    final_decision: Decision

@dataclass(frozen=True, slots=True)
class StudySnapshot:
    experiment_id: str
    manifest_digest: str
    total_pair_count: int
    effective_pairs: tuple[dict[str, object], ...]
    assignments: tuple[AssignmentRow, ...]
    submissions: tuple[SubmissionRow, ...]
    resolutions: tuple[ResolutionRow, ...]

class AnalysisBlocked(RuntimeError):
    pass
```

validator는 pinned provenance와 `120/74/148/148/26`, assignment/submission bijection,
pair별 서로 다른 reviewer 2명, exact required resolution set을 fail-closed한다.

- [x] **Step 4: GREEN을 확인한다**

Run: `uv run pytest tests/test_rba_boundary_development_analysis.py -q`

Expected: integrity tests PASS.

- [x] **Step 5: event grouping·metrics failing tests를 추가한다**

다음을 검증한다.

```python
def test_groups_linear_subsegments_without_crossing_invalid_edges(...): ...
def test_final_uncertain_returns_hold_without_guessing(...): ...
def test_agreement_kappa_owner_intervention_and_confusion_matrix(...): ...
def test_event_reduction_uses_effective_unique_clips_only(...): ...
def test_threshold_prefers_zero_overmerge_then_minimum_oversplit(...): ...
def test_same_salt_and_reordered_inputs_have_identical_hash(...): ...
def test_public_report_contains_no_uuid_email_camera_or_reason(...): ...
```

- [x] **Step 6: event grouping과 metrics를 구현한다**

구현 규칙:

```python
final[pair] = submitted if both equal and non_uncertain else resolution[pair]
required_resolution = disagreement or either_uncertain
source_clip_count = count(unique clips touched by effective assigned pairs)
human_event_count = source_clip_count - count(final same_event edges)
event_reduction = 1 - human_event_count / source_clip_count
```

manifest의 `run_ordinal`과 연속 left/right를 SOT로 쓰고, effective pair가 빠진 곳에서 sub-segment를
끊는다. Cohen's kappa는 observed agreement와 reviewer marginal expected agreement로 직접 계산한다.
threshold 후보는 `(0, 5, 15, 30, 60, 120)`으로 고정한다.

- [x] **Step 7: focused GREEN과 결정론을 확인한다**

Run:

```bash
uv run pytest tests/test_rba_boundary_development_analysis.py -q
```

Expected: all PASS.

- [x] **Step 8: analyzer를 commit한다**

```bash
git add scripts/rba_boundary_development_analysis.py tests/test_rba_boundary_development_analysis.py
git commit -m "feat: 사람 사건 경계 development scorer"
```

---

### Task 3: Production SELECT-only runner TDD

**Files:**
- Create: `scripts/run_rba_boundary_development_analysis.py`
- Create: `tests/test_run_rba_boundary_development_analysis.py`

**Interfaces:**
- Consumes: `--base-artifact`, `--env-file`, `--output-dir`, `--report`
- Produces: `run-salt.bin`, `analysis-private.json`, aggregate `REPORT.md`

- [x] **Step 1: runner safety failing tests를 작성한다**

```python
def test_runner_source_has_no_rpc_or_mutation_calls(): ...
def test_runner_requires_env_file_mode_0600(): ...
def test_runner_refuses_existing_output_directory(): ...
def test_runner_writes_0700_0600_and_same_hash_three_times(): ...
def test_runner_does_not_select_reason_or_behavior_gt_columns(): ...
```

- [x] **Step 2: RED를 확인한다**

Run: `uv run pytest tests/test_run_rba_boundary_development_analysis.py -q`

Expected: import/file missing failure.

- [x] **Step 3: SELECT-only loader를 구현한다**

runner는 `load_env_file`을 재사용하되 env mode가 `0600`이 아니면 중단한다. Supabase query는
다음 table과 column만 허용한다.

```text
rba_boundary_review_cohorts: id,experiment_id,manifest_digest,status
rba_boundary_review_pairs: id,cohort_id,ordinal,pair_digest,gap_sec,gap_bin
rba_boundary_review_assignments: id,pair_id,reviewer_id,reviewer_role
rba_boundary_review_submissions: assignment_id,pair_id,reviewer_id,decision,digest,submitted_at
rba_boundary_review_resolutions: pair_id,final_decision,digest,resolved_at
```

`.rpc`, `.insert`, `.update`, `.delete`, R2 client import는 사용하지 않는다. `reason`, 행동 GT,
Python Evidence, Gate, VLM table은 조회하지 않는다.

- [x] **Step 4: deterministic three-pass writer를 구현한다**

1. output directory가 이미 있으면 중단한다.
2. mode `0700`으로 directory를 만들고 `run-salt.bin`을 `0600`으로 한 번 쓴다.
3. 같은 snapshot/salt로 normal, reversed, stable-shuffled input을 분석한다.
4. 세 metrics/private digest가 모두 같지 않으면 artifact/report를 쓰지 않고 중단한다.
5. private JSON을 `0600` no-overwrite로 쓴다.
6. public report는 raw 식별자가 없는 aggregate renderer 결과만 쓴다.

- [x] **Step 5: focused GREEN을 확인한다**

Run:

```bash
uv run pytest tests/test_rba_boundary_development_analysis.py tests/test_run_rba_boundary_development_analysis.py -q
```

Expected: all PASS.

- [x] **Step 6: runner를 commit한다**

```bash
git add scripts/run_rba_boundary_development_analysis.py tests/test_run_rba_boundary_development_analysis.py
git commit -m "feat: 사건 경계 production read-only 분석 runner"
```

---

### Task 4: Local verification와 handoff gate

**Files:**
- Create: `docs/handoff-prompts/2026-08-02-rba-boundary-development-analysis-v1-handoff.md`

**Interfaces:**
- Consumes: clean tracked design, plan, TEST-SHEET, implementation commits
- Produces: exact `HANDOFF_OK` manifest for Mac mini one-shot execution

- [x] **Step 1: focused와 full test를 실행한다**

```bash
uv run pytest tests/test_rba_boundary_development_analysis.py tests/test_run_rba_boundary_development_analysis.py -q
uv run pytest
git diff --check
```

Expected: focused all PASS, full suite 0 failures, diff check clean.

- [x] **Step 2: handoff manifest를 실제 40자리 HEAD로 작성한다**

manifest 필수값:

```markdown
task: rba-boundary-development-analysis-v1
execution_repo: /Users/baek-end/petcam-lab-boundary-development-v1
plan: /Users/baek-end/petcam-lab-boundary-development-v1/docs/superpowers/plans/2026-08-02-rba-boundary-development-analysis-v1.md
design: /Users/baek-end/petcam-lab-boundary-development-v1/docs/superpowers/specs/2026-08-02-rba-boundary-development-analysis-v1-design.md
implementation_commit: <git rev-parse HEAD의 실제 40자리 SHA>
implementation_host: baeg-endeuui-Macmini.local
runtime_kind: one-shot-research
runtime_host: baeg-endeuui-Macmini.local
service_label: none
```

`<...>` 문자열을 남기지 않고 실제 SHA를 넣는다.

- [x] **Step 3: manifest를 commit·push한다**

```bash
git add docs/handoff-prompts/2026-08-02-rba-boundary-development-analysis-v1-handoff.md
git commit -m "docs: 사건 경계 분석 Mac mini 핸드오프"
git push origin HEAD:codex/rba-boundary-blind-hardening
```

- [x] **Step 4: handoff validator를 실행한다**

```bash
uv run python scripts/verify_agent_handoff.py --manifest /absolute/path/to/docs/handoff-prompts/2026-08-02-rba-boundary-development-analysis-v1-handoff.md
```

Expected: exact `HANDOFF_OK`.

---

### Task 5: Mac mini SELECT-only 실행

**Files:**
- Create runtime artifact outside repo: `/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-boundary-development-v1/*`
- Modify: `experiments/rba-boundary-development-v1/REPORT.md`

**Interfaces:**
- Consumes: exact handoff commit, existing `0600` env, pinned base artifact
- Produces: private artifact and public aggregate verdict

- [x] **Step 1: isolated worktree와 exact HEAD를 확인한다**

Mac mini에서 primary dirty checkout을 수정하지 않고 execution repo를 exact handoff SHA로 만든다.

```bash
hostname
git -C /Users/baek-end/petcam-lab fetch origin
git -C /Users/baek-end/petcam-lab worktree add --detach /Users/baek-end/petcam-lab-boundary-development-v1 <exact SHA>
git -C /Users/baek-end/petcam-lab-boundary-development-v1 rev-parse HEAD
```

Expected: hostname `baeg-endeuui-Macmini.local`, HEAD exact match.

- [x] **Step 2: Mac focused tests와 HANDOFF_OK를 재검증한다**

```bash
cd /Users/baek-end/petcam-lab-boundary-development-v1
/opt/homebrew/bin/uv run python scripts/verify_agent_handoff.py --manifest "$PWD/docs/handoff-prompts/2026-08-02-rba-boundary-development-analysis-v1-handoff.md"
/opt/homebrew/bin/uv run pytest tests/test_rba_boundary_development_analysis.py tests/test_run_rba_boundary_development_analysis.py -q
```

- [x] **Step 3: one-shot runner를 실행한다**

```bash
/opt/homebrew/bin/uv run python scripts/run_rba_boundary_development_analysis.py \
  --base-artifact "/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-event-media-eligibility-v1-20260731T124018Z/boundary-pairs.json" \
  --env-file "/Users/baek-end/.config/petcam/rba-shadow.env" \
  --output-dir "/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-boundary-development-v1" \
  --report "/Users/baek-end/petcam-lab-boundary-development-v1/experiments/rba-boundary-development-v1/REPORT.md"
```

Expected: aggregate counts와 verdict만 stdout. UUID/email/reason/secret/R2 key 출력 0.

- [x] **Step 4: 실행 후 안전 증거를 확인한다**

```bash
stat -f '%Lp %N' "/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-boundary-development-v1" "/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-boundary-development-v1"/*
git diff --check
```

Expected: directory `700`, files `600`, tracked diff는 public report 한정.

- [x] **Step 5: public report를 commit·push한다**

```bash
git add experiments/rba-boundary-development-v1/REPORT.md
git commit -m "docs: 사건 경계 development 분석 결과"
git push origin HEAD:codex/rba-boundary-blind-hardening
```

---

### Task 6: Result integration와 SOT 갱신

**Files:**
- Modify: `docs/superpowers/specs/2026-08-02-rba-boundary-development-analysis-v1-design.md`
- Modify: `experiments/rba-boundary-development-v1/TEST-SHEET.md`
- Modify: `experiments/rba-event-grouping-shadow-v2/TEST-SHEET.md`
- Modify: `specs/next-session.md`

**Interfaces:**
- Consumes: verified Mac mini aggregate report
- Produces: current SOT and next-step verdict

- [x] **Step 1: report와 private aggregate digest를 독립 대조한다**

raw IDs를 읽거나 출력하지 않고 counts, metrics SHA, verdict, file mode, write-zero evidence만 비교한다.

- [x] **Step 2: SOT 문서를 갱신한다**

기록 내용:

- 사람 agreement/kappa/uncertain/Owner intervention
- final events/source clips/event reduction
- chosen threshold와 over-merge/over-split
- GT verdict와 utility verdict
- DB/R2/model/service write 0
- local VLM baseline은 별도 계획 전 미실행

- [x] **Step 3: docs tests와 full tests를 재실행한다**

```bash
uv run pytest tests/test_rba_boundary_development_analysis.py tests/test_run_rba_boundary_development_analysis.py -q
uv run pytest
git diff --check
```

- [x] **Step 4: final docs commit과 main fast-forward push를 수행한다**

```bash
git add docs/superpowers/specs/2026-08-02-rba-boundary-development-analysis-v1-design.md experiments/rba-boundary-development-v1/TEST-SHEET.md experiments/rba-event-grouping-shadow-v2/TEST-SHEET.md specs/next-session.md
git commit -m "docs: 사건 경계 development 연구 판정 반영"
git fetch origin
git merge-base --is-ancestor origin/main HEAD
git push origin HEAD:codex/rba-boundary-blind-hardening
git push origin HEAD:main
```

Expected: non-force fast-forward, user-owned `AGENTS.md`는 unstaged 그대로 보존.
