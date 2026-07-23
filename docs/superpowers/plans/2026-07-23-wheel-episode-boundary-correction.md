# 쳇바퀴 에피소드 10분 경계 교정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 연속 clip chaining으로 10분을 초과한 wheel 그룹을 만들던 v1 결함을 1회 교정하고, 동일 frozen signature에서 채택 가능성을 재측정한다.

**Architecture:** grouping의 `이전 clip 간격`과 `run 전체 길이`를 분리하고 전체 길이 불변식을 순수 함수와 산출물 경계에서 이중 검증한다. R2/DB를 다시 읽지 않는 별도 replay runner가 기존 커밋된 signature를 입력으로 새 디렉터리에 결과와 blind review를 만든다.

**Tech Stack:** Python 3.12, dataclasses, pytest, JSON/CSV, uv

## Global Constraints

- correction 기회는 이번 1회뿐이다. 실패 시 새 threshold·ROI·mode 튜닝 없이 reject한다.
- 기존 ROI와 threshold 4종은 byte-equivalent로 유지한다.
- 기존 shadow 산출물은 수정·삭제하지 않는다.
- production DB/R2/Slack/VLM/worker/web에 접근하거나 쓰지 않는다.
- main merge·배포는 금지한다.
- 구현은 TDD RED→GREEN, task별 명시 파일만 commit·push한다.

---

## File Map

| 파일 | 책임 |
|---|---|
| `scripts/wheel_shadow/grouping.py` | 두 시간 경계로 bounded run 생성, 그룹 span 검증 |
| `tests/test_wheel_shadow.py` | chaining·정확 경계·span 불변식 회귀 |
| `scripts/run_wheel_boundary_correction.py` | 커밋된 signature replay, 입력 SHA 검증, 결과 생성 |
| `tests/test_wheel_boundary_correction.py` | runner fail-closed·결정론·출력 계약 |
| `experiments/wheel-episode-dedup-boundary-fix/TEST-SHEET.md` | 실행 전 동결한 판정 계약 |
| `experiments/wheel-episode-dedup-boundary-fix/RESULT.json` | 기계 판정과 provenance |
| `experiments/wheel-episode-dedup-boundary-fix/BLIND-REVIEW.csv` | owner 검수용 점수 비노출 목록 |
| `experiments/wheel-episode-dedup-boundary-fix/REPORT.md` | 결과 해석과 최종 기계 판정 |
| `docs/handoff-prompts/2026-07-23-wheel-episode-boundary-correction-report.md` | Claude 완료 보고 |

---

### Task 1: 시험지 사전등록

**Files:**
- Create: `experiments/wheel-episode-dedup-boundary-fix/TEST-SHEET.md`

**Interfaces:**
- Consumes: design §4~§7
- Produces: 실행 전에 동결된 입력 SHA·알고리즘 버전·판정 게이트

- [ ] **Step 1: 시험지를 작성한다**

반드시 다음 값을 전문으로 기록한다.

```text
algorithm_version=wheel-episode-dedup-shadow-v1.1-boundary-fix
max_inter_clip_gap_sec=600
max_episode_span_sec=600
wheel_motion_floor=0.01
hamming_threshold=7
motion_tolerance=0.02
novelty_min_hamming=6
evidence_audit_sha256=23789fa8ea430c4dc24b015847c360a6afa72565c897c3d4b7b8654702a508e3
frozen_cohort_sha256=b67b32f27259d132cda5861f8126f6b48f4bb704528c0458ebbf63a95d17f953
roi_profile_sha256=653e64c25e057339ce9a1844d27c570ce99916d20986023fafdabd84935c7825
```

판정은 design §5의 7개 기계 게이트를 그대로 쓰고, owner 검수 전 채택 금지를 명시한다.

- [ ] **Step 2: 금지 문자열과 누락을 검사한다**

Run:

```bash
rg -n "TBD|TODO|추후 결정|threshold 변경|ROI 변경" \
  experiments/wheel-episode-dedup-boundary-fix/TEST-SHEET.md
```

Expected: `threshold 변경`과 `ROI 변경`은 금지문에서만 등장하고 placeholder는 0건.

- [ ] **Step 3: 시험지만 커밋한다**

```bash
git add experiments/wheel-episode-dedup-boundary-fix/TEST-SHEET.md
git commit -m "test: 쳇바퀴 10분 경계 교정 시험지 동결"
```

---

### Task 2: 연쇄 결합 회귀를 RED로 고정

**Files:**
- Modify: `tests/test_wheel_shadow.py`

**Interfaces:**
- Consumes: `GroupingParams`, `group_clips`
- Produces: 전체 길이 600초 계약을 판별하는 실패 테스트

- [ ] **Step 1: 다음 회귀 테스트를 추가한다**

```python
def test_grouping_chain_cannot_exceed_total_episode_span():
    sigs = [
        _sig("a", "2026-07-19T03:00:00+00:00", ph=0b1111),
        _sig("b", "2026-07-19T03:05:00+00:00", ph=0b1111),
        _sig("c", "2026-07-19T03:10:00+00:00", ph=0b1111),
        _sig("d", "2026-07-19T03:15:00+00:00", ph=0b1111),
        _sig("e", "2026-07-19T03:20:00+00:00", ph=0b1111),
    ]
    params = grp.GroupingParams(
        max_inter_clip_gap_sec=600,
        max_episode_span_sec=600,
        wheel_motion_floor=0.1,
        hamming_threshold=4,
        motion_tolerance=0.1,
    )
    groups, ungrouped = grp.group_clips(sigs, params, select_representatives)
    assert [set(g.member_clip_ids) for g in groups] == [
        {"a", "b", "c"},
        {"d", "e"},
    ]
    assert ungrouped == []
    assert all(grp.group_span_sec(g) <= 600 for g in groups)
```

정확히 600초 포함 테스트와 601초 분리 테스트도 각각 추가한다.

- [ ] **Step 2: RED를 확인한다**

Run:

```bash
uv run pytest -q tests/test_wheel_shadow.py \
  -k "chain_cannot_exceed or exact_episode_span or over_episode_span"
```

Expected: 새 필드 또는 `group_span_sec` 부재, 혹은 chaining 결과 불일치로 FAIL.

- [ ] **Step 3: 테스트만 커밋한다**

```bash
git add tests/test_wheel_shadow.py
git commit -m "test: 10분 초과 연쇄 결합 회귀 고정"
```

---

### Task 3: 두 시간 경계와 span 불변식 구현

**Files:**
- Modify: `scripts/wheel_shadow/grouping.py`
- Modify: `scripts/run_wheel_shadow.py`
- Test: `tests/test_wheel_shadow.py`

**Interfaces:**
- Produces:
  - `GroupingParams.max_inter_clip_gap_sec: float`
  - `GroupingParams.max_episode_span_sec: float`
  - `group_span_sec(group: Group) -> float`
  - `validate_group_spans(groups: Sequence[Group], max_span_sec: float) -> None`

- [ ] **Step 1: 파라미터를 분리한다**

`GroupingParams`를 다음 계약으로 바꾼다. 나머지 threshold 기본값은 그대로 둔다.

```python
@dataclasses.dataclass(frozen=True, slots=True)
class GroupingParams:
    max_inter_clip_gap_sec: float = 600.0
    max_episode_span_sec: float = 600.0
    wheel_motion_floor: float = 0.08
    hamming_threshold: int = 8
    motion_tolerance: float = 0.08
```

- [ ] **Step 2: run 분리 조건을 최소 수정한다**

```python
if cur:
    inter_gap = _epoch(s.started_at) - _epoch(cur[-1].started_at)
    total_span = _epoch(s.started_at) - _epoch(cur[0].started_at)
    if (
        inter_gap > params.max_inter_clip_gap_sec
        or total_span > params.max_episode_span_sec
    ):
        runs.append(cur)
        cur = []
```

정렬·anchor·similarity·대표 선택 코드는 바꾸지 않는다.

- [ ] **Step 3: 산출물 불변식 검증기를 추가한다**

```python
def group_span_sec(group: Group) -> float:
    return _epoch(group.started_at_last) - _epoch(group.started_at_first)


def validate_group_spans(
    groups: Sequence[Group], max_span_sec: float
) -> None:
    violations = [g.group_id for g in groups if group_span_sec(g) > max_span_sec]
    if violations:
        raise ValueError(
            f"group_span_contract_violation count={len(violations)}"
        )
```

오류에는 clip ID·시각·원시 데이터를 넣지 않는다.

- [ ] **Step 4: 구 profile 변환을 명시한다**

`_params_from_profile`은 기존 `max_gap_sec`을
`max_inter_clip_gap_sec`으로 읽고 `max_episode_span_sec=600.0`을 명시한다.
ROI와 나머지 threshold는 기존 값을 그대로 읽는다.

- [ ] **Step 5: focused GREEN을 확인한다**

Run:

```bash
uv run pytest -q tests/test_wheel_shadow.py
```

Expected: 모든 wheel 테스트 PASS.

- [ ] **Step 6: 구현을 커밋한다**

```bash
git add scripts/wheel_shadow/grouping.py scripts/run_wheel_shadow.py tests/test_wheel_shadow.py
git commit -m "fix: 쳇바퀴 에피소드 전체 길이 10분 강제"
```

---

### Task 4: frozen signature 전용 correction runner

**Files:**
- Create: `scripts/run_wheel_boundary_correction.py`
- Create: `tests/test_wheel_boundary_correction.py`

**Interfaces:**
- Consumes:
  - `experiments/wheel-episode-dedup-shadow/EVIDENCE-AUDIT.json`
  - `experiments/wheel-episode-dedup-shadow/frozen-cohort.json`
  - `experiments/wheel-episode-dedup-shadow/wheel-roi-profile-v1.json`
- Produces:
  - `run(input_dir: Path, output_dir: Path) -> dict`
  - `RESULT.json`
  - `BLIND-REVIEW.csv`

- [ ] **Step 1: 입력 SHA fail-closed 테스트를 RED로 작성한다**

fixture 입력 중 한 byte를 바꾸면 `INPUT_SHA_MISMATCH`로 nonzero/예외 종료하고 결과 파일을 만들지
않는 테스트를 작성한다.

- [ ] **Step 2: 결정론·span·threshold 불변 테스트를 RED로 작성한다**

작은 fixture에서 runner를 서로 다른 두 출력 디렉터리에 실행해:

```python
assert result_a["result_sha256"] == result_b["result_sha256"]
assert result_a["span_violation_count"] == 0
assert result_a["effective_params"] == {
    "max_inter_clip_gap_sec": 600.0,
    "max_episode_span_sec": 600.0,
    "wheel_motion_floor": 0.01,
    "hamming_threshold": 7,
    "motion_tolerance": 0.02,
    "novelty_min_hamming": 6,
}
```

`BLIND-REVIEW.csv`에는 evidence score·motion·hash·provenance 열이 없어야 한다.

- [ ] **Step 3: RED를 확인한다**

Run:

```bash
uv run pytest -q tests/test_wheel_boundary_correction.py
```

Expected: runner module 부재로 FAIL.

- [ ] **Step 4: runner를 구현한다**

runner는 표준 라이브러리와 기존 순수 모듈만 import한다. Supabase/R2/client config를 import하지
않는다. 시작 시 입력 SHA 3개를 검증하고 저장된 signature를 `dict_to_sig`와 동일한 명시 필드로
복원한다.

fresh·known wheel을 각각 두 번 그룹화하고 각 SHA가 일치하는지 검사한다. 그룹 생성 직후
`validate_group_spans`를 호출한다. overlap·known review reduction을 계산한다.

`RESULT.json`에는 최소한 다음을 기록한다.

```json
{
  "algorithm_version": "wheel-episode-dedup-shadow-v1.1-boundary-fix",
  "input_sha256": {},
  "effective_params": {},
  "fresh": {
    "n_total": 0,
    "n_groups": 0,
    "n_membership": 0,
    "n_representatives": 0,
    "n_ungrouped": 0,
    "max_group_span_sec": 0,
    "span_violation_count": 0,
    "overlap_count": 0
  },
  "known_wheel": {
    "n_total": 0,
    "n_groups": 0,
    "n_representatives": 0,
    "workload_reduction": 0
  },
  "result_sha256": "",
  "replay_sha256": "",
  "machine_verdict": ""
}
```

machine verdict는 design §5를 모두 통과할 때만
`BOUNDARY_CORRECTION_READY_FOR_OWNER_REVIEW`, 아니면
`BOUNDARY_CORRECTION_REJECTED`다.

- [ ] **Step 5: GREEN을 확인한다**

Run:

```bash
uv run pytest -q tests/test_wheel_boundary_correction.py tests/test_wheel_shadow.py
```

Expected: 모두 PASS.

- [ ] **Step 6: runner와 테스트를 커밋한다**

```bash
git add scripts/run_wheel_boundary_correction.py tests/test_wheel_boundary_correction.py
git commit -m "feat: frozen signature 경계 교정 replay 추가"
```

---

### Task 5: 동일 frozen cohort 재계산

**Files:**
- Create: `experiments/wheel-episode-dedup-boundary-fix/RESULT.json`
- Create: `experiments/wheel-episode-dedup-boundary-fix/BLIND-REVIEW.csv`
- Create: `experiments/wheel-episode-dedup-boundary-fix/REPORT.md`

**Interfaces:**
- Consumes: Task 4 runner와 동결 입력
- Produces: owner가 검수할 최종 shadow artifact

- [ ] **Step 1: 작업 전 금지 I/O를 정적으로 확인한다**

Run:

```bash
rg -n "supabase|boto3|R2|Slack|VLM|requests|httpx|urllib" \
  scripts/run_wheel_boundary_correction.py
```

Expected: 실행 가능한 외부 I/O import/call 0건.

- [ ] **Step 2: correction runner를 실행한다**

Run:

```bash
uv run python scripts/run_wheel_boundary_correction.py
```

Expected: `RESULT.json`·`BLIND-REVIEW.csv` 생성, 기계 판정 1개 출력.

- [ ] **Step 3: 독립 표준 라이브러리 재계산을 실행한다**

runner를 import하지 않는 one-shot Python으로 `RESULT.json`과 CSV를 읽어 다음을 재확인한다.

- 모든 그룹 span ≤600
- membership 중복 0
- CSV 그룹/clip 수와 RESULT 일치
- known wheel reduction 계산 일치
- evidence 점수 관련 CSV 헤더 0

불일치하면 artifact를 커밋하지 않고 `BOUNDARY_CORRECTION_REJECTED`로 보고한다.

- [ ] **Step 4: REPORT를 작성한다**

다음을 수치로 기록한다.

- 교정 전: 19/32 그룹 위반, 위반 membership 296/326, max 18,224초
- 교정 후: 그룹·membership·representatives·max span·위반 수
- known wheel 24개의 그룹·대표·검토량 감소율
- input SHA 3개
- deterministic replay SHA 2개
- machine verdict
- owner audit가 미완이며 채택·배포가 아님

- [ ] **Step 5: 산출물을 커밋한다**

```bash
git add experiments/wheel-episode-dedup-boundary-fix
git commit -m "test: 쳇바퀴 경계 교정 shadow 재측정"
```

---

### Task 6: 전체 검증·보고·Stop Point

**Files:**
- Create: `docs/handoff-prompts/2026-07-23-wheel-episode-boundary-correction-report.md`
- Modify: `.claude/donts-audit.md`

- [ ] **Step 1: 전체 검증을 실행한다**

Run:

```bash
uv run pytest -q
git diff --check
git status --short
```

Expected: 전체 pytest PASS, whitespace clean. 보고서 작성 전 허용 변경만 존재.

- [ ] **Step 2: 기존 v1 산출물 불변을 확인한다**

Run:

```bash
git diff --exit-code 898278ff57aab089b46d2fbb616df479212820c4 -- \
  experiments/wheel-episode-dedup-shadow/EVIDENCE-AUDIT.json \
  experiments/wheel-episode-dedup-shadow/frozen-cohort.json \
  experiments/wheel-episode-dedup-shadow/wheel-roi-profile-v1.json \
  experiments/wheel-episode-dedup-shadow/shadow-groups.json
```

Expected: 출력 0, exit 0.

- [ ] **Step 3: 완료 보고서를 작성한다**

보고서에 다음을 포함한다.

1. 최종 machine verdict
2. root cause와 RED→GREEN
3. 교정 전/후 수치
4. 7개 기계 게이트별 PASS/FAIL
5. 기존 v1 artifact SHA 불변
6. 전체 테스트 결과
7. commit SHA·push 상태
8. owner blind audit 절대경로와 남은 사람 판정
9. 금지동작 0 증거

기계 게이트 통과 시에도 `READY_FOR_OWNER_REVIEW`까지만 주장한다.

- [ ] **Step 4: 문서만 커밋하고 feature branch를 push한다**

```bash
git add .claude/donts-audit.md \
  docs/handoff-prompts/2026-07-23-wheel-episode-boundary-correction-report.md
git commit -m "docs: 쳇바퀴 10분 경계 교정 결과 보고"
git push -u origin codex/wheel-episode-boundary-fix
```

- [ ] **Step 5: 최종 상태를 확인하고 멈춘다**

```bash
git status --short
git rev-list --left-right --count \
  HEAD...origin/codex/wheel-episode-boundary-fix
```

Expected: clean, `0 0`.

main merge·DB/UI 반영·추가 threshold 튜닝·owner 판정 대행 없이 Stop Point에서 정지한다.

