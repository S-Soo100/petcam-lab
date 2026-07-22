# Local VLM Evidence B1R Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code change uses superpowers:test-driven-development.

**Goal:** 과거 `motion_clips`의 active Python Evidence를 완주하고 selector v2의 multi-match/scarcity-first 배정으로 6 strata×30 시험지 가용성을 다시 판정한다.

**Architecture:** `petcam-nightly-reporter`의 기존 durable queue/worker는 유지하고, history enqueuer만 missing clip로 계속 전진하도록 하드닝한다. `petcam-lab`에는 고정 cutoff coverage 감사와 selector v2를 추가한다. Mac mini에서 coverage closure를 만든 뒤 동일 snapshot을 두 독립 계산으로 검증하며, B1R 통과 전에는 모델·B2·GT write를 실행하지 않는다.

**Tech Stack:** Python 3.12, uv, pytest, Supabase/PostgREST SELECT, existing `python_evidence_jobs`, existing Mac mini LaunchAgent, deterministic JSON/SHA-256.

## Global Constraints

- Design SOT: `docs/superpowers/specs/2026-07-22-local-vlm-evidence-b1r-design.md`.
- Selector identity: `local-vlm-evidence-selector-v2`; v1 artifact와 SHA를 덮어쓰지 않는다.
- Evidence identity: `python-evidence-raw-v1` + `croi-temporal-v1`.
- Runtime host: `baeg-endeuui-Macmini.local`; laptop execution과 expected-host 우회 금지.
- Study contract: 6 strata×30, dev120/holdout60, global clip/30-minute episode overlap 0.
- Backfill write scope: `python_evidence_jobs` enqueue만. Python Evidence run은 기존 worker/RPC만 쓴다.
- Model download/inference, VLM/GT/behavior/activity/app write, B2 migration/API/UI는 금지한다.
- Per-clip artifact와 R2 key는 `storage/` 아래 gitignored 파일에만 둔다.
- 기존 `B1` 산출물·보고서는 수정하지 않는다. 모든 새 verdict는 `B1R_*` namespace를 쓴다.
- 커밋은 task별 명시 파일만. 다른 세션 untracked 파일을 add/delete하지 않는다.

---

### Task 0: Handoff와 runtime drift fail-closed preflight

**Files:**
- Read: `AGENTS.md`
- Read: `docs/superpowers/specs/2026-07-22-local-vlm-evidence-b1r-design.md`
- Read: `docs/handoff-prompts/2026-07-17-python-evidence-universal-worker-runtime-handoff.md`
- Create: `reports/local-vlm-evidence-b1r/RUNTIME-SNAPSHOT.md`

**Interfaces:**
- Consumes: handoff front matter와 Mac mini SSH alias `home-mac`.
- Produces: `runtime_verdict`, 세 repo runtime HEAD, LaunchAgent contract, active evidence identity, fixed `coverage_cutoff_started_at`.

- [ ] **Step 1: Handoff를 검증한다**

```bash
cd /Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/.codex/handoffs/2026-07-22-local-vlm-evidence-b1r-handoff.md
```

Expected: exact prefix `HANDOFF_OK task=local-vlm-evidence-b1r`.

- [ ] **Step 2: laptop repo 상태를 기록한다**

```bash
git status --short --branch
git rev-parse HEAD
git -C /Users/baek/petcam-nightly-reporter fetch origin
git -C /Users/baek/petcam-nightly-reporter rev-parse main origin/main
git -C /Users/baek/petcam-nightly-reporter merge-base --is-ancestor 618f4f854254525b0ebc6f0fcf9153f8e0cd6bc1 origin/main
```

Expected: lab handoff repo clean. 마지막 명령이 nonzero여도 merge하지 말고 drift 증거로 기록한다.

- [ ] **Step 3: Mac mini runtime을 read-only로 실측한다**

```bash
ssh home-mac 'set -eu
hostname
for r in /Users/baek-end/petcam-lab /Users/baek-end/petcam-nightly-reporter /Users/baek-end/myPythonProjects/gecko-vision-gate; do
  git -C "$r" status --short --branch
  git -C "$r" rev-parse HEAD
  git -C "$r" rev-parse origin/main
done
launchctl print gui/$(id -u)/com.petcam.python-evidence-worker | sed -n "1,180p"
plutil -p "$HOME/Library/LaunchAgents/com.petcam.python-evidence-worker.plist"
' 
```

Expected: hostname exact match, service loaded, nightly WorkingDirectory exact, `PYTHON_EVIDENCE_ENABLED=1`, expected-host exact, threshold `0.10`. Secret values는 출력하지 않는다.

- [ ] **Step 4: runtime 판정을 작성한다**

명령 출력으로 값을 채운다. cutoff는 production `motion_clips.started_at` 최댓값을 SELECT-only로 읽는다.

```bash
LAB_HEAD="$(ssh home-mac 'git -C /Users/baek-end/petcam-lab rev-parse HEAD')"
NIGHTLY_HEAD="$(ssh home-mac 'git -C /Users/baek-end/petcam-nightly-reporter rev-parse HEAD')"
GATE_HEAD="$(ssh home-mac 'git -C /Users/baek-end/myPythonProjects/gecko-vision-gate rev-parse HEAD')"
CUTOFF="$(uv run python - <<'PY'
from backend.supabase_client import get_supabase_client
rows = (get_supabase_client().table("motion_clips").select("started_at")
        .order("started_at", desc=True).limit(1).execute().data or [])
if len(rows) != 1 or not rows[0].get("started_at"):
    raise SystemExit("cutoff_missing")
print(rows[0]["started_at"])
PY
)"
mkdir -p reports/local-vlm-evidence-b1r
{
  echo "# B1R Runtime Snapshot"
  echo
  echo "- runtime_verdict: B1R_RUNTIME_OK"
  echo "- runtime_host: baeg-endeuui-Macmini.local"
  echo "- lab_head: $LAB_HEAD"
  echo "- nightly_head: $NIGHTLY_HEAD"
  echo "- gate_head: $GATE_HEAD"
  echo "- service_loaded: true"
  echo "- working_directory: /Users/baek-end/petcam-nightly-reporter"
  echo "- evidence_schema_version: python-evidence-raw-v1"
  echo "- algorithm_version: croi-temporal-v1"
  echo "- coverage_cutoff_started_at: $CUTOFF"
} > reports/local-vlm-evidence-b1r/RUNTIME-SNAPSHOT.md
```

If access fails or runtime code is not safely traceable to pushed Git history, stop with the matching verdict. Do not continue locally.

- [ ] **Step 5: snapshot만 commit한다**

```bash
git add reports/local-vlm-evidence-b1r/RUNTIME-SNAPSHOT.md
git commit -m "docs: B1R runtime 정본 기록"
```

---

### Task 1: Fixed-cutoff Python Evidence coverage audit

**Files:**
- Create: `scripts/audit_local_vlm_evidence_b1r_coverage.py`
- Create: `tests/test_audit_local_vlm_evidence_b1r_coverage.py`
- Create at runtime: `experiments/local-vlm-evidence-analyst/b1r-coverage-before.json`
- Create at runtime: `experiments/local-vlm-evidence-analyst/b1r-coverage-after.json`
- Create at runtime: `reports/local-vlm-evidence-b1r/COVERAGE-BEFORE.md`
- Create at runtime: `reports/local-vlm-evidence-b1r/COVERAGE-AFTER.md`

**Interfaces:**
- Consumes: `coverage_cutoff_started_at`, active schema/algo.
- Produces: `CoverageSnapshot` and `evaluate_coverage_closure(snapshot) -> str`.

- [ ] **Step 1: RED tests를 작성한다**

```python
def test_cutoff_excludes_new_live_clip():
    rows = [clip("old", "2026-07-22T00:00:00Z"), clip("new", "2026-07-22T00:00:01Z")]
    snap = build_snapshot(rows, jobs=[], runs=[], cutoff=ts("2026-07-22T00:00:00Z"))
    assert snap.eligible == 1
    assert snap.silent_missing == 1

def test_closure_requires_no_open_or_silent_missing():
    assert evaluate_coverage_closure(snapshot(eligible=2, succeeded=1, terminal=1)) == "COVERAGE_CLOSED"
    assert evaluate_coverage_closure(snapshot(eligible=2, succeeded=1, terminal=0, silent=1)) == "COVERAGE_OPEN"
    assert evaluate_coverage_closure(snapshot(eligible=2, succeeded=1, terminal=0, queued=1)) == "COVERAGE_OPEN"

def test_terminal_is_not_counted_as_success():
    snap = build_snapshot([clip("a"), clip("b")], [terminal_job("b")], [ok_run("a")], cutoff=FAR_FUTURE)
    assert snap.succeeded_with_active_run == 1
    assert snap.allowlisted_terminal == 1
```

- [ ] **Step 2: RED를 확인한다**

```bash
cd /Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt
uv run pytest -q tests/test_audit_local_vlm_evidence_b1r_coverage.py
```

Expected: import/file missing failure.

- [ ] **Step 3: 최소 coverage core를 구현한다**

```python
EVIDENCE_SCHEMA_VERSION = "python-evidence-raw-v1"
ALGORITHM_VERSION = "croi-temporal-v1"

@dataclass(frozen=True, slots=True)
class CoverageSnapshot:
    cutoff_started_at: str
    range_start_date: str
    range_end_date: str
    eligible: int
    succeeded_with_active_run: int
    allowlisted_terminal: int
    queued: int
    processing: int
    failed_retryable: int
    silent_missing: int
    terminal_by_code: Mapping[str, int]
    camera_date_counts: Mapping[str, int]

def evaluate_coverage_closure(s: CoverageSnapshot) -> str:
    accounted = s.succeeded_with_active_run + s.allowlisted_terminal
    open_jobs = s.queued + s.processing + s.failed_retryable
    return "COVERAGE_CLOSED" if accounted == s.eligible and s.silent_missing == 0 and open_jobs == 0 else "COVERAGE_OPEN"
```

Production loader는 `(started_at,id)` 안정 pagination으로 cutoff 이하 playable motion clips, active identity jobs/runs를 모두 읽는다. Supabase 기본 1000행 상한을 허용하지 않는다. raw exception, R2 key, per-clip ID를 aggregate에 넣지 않는다.
CLI는 `--cutoff-started-at`, `--json-out`, `--report-out`을 모두 required로 받는다.

- [ ] **Step 4: GREEN과 전체 lab 회귀를 확인한다**

```bash
uv run pytest -q tests/test_audit_local_vlm_evidence_b1r_coverage.py
uv run pytest -q
git diff --check
```

Expected: focused PASS, full suite PASS, whitespace clean.

- [ ] **Step 5: commit한다**

```bash
git add scripts/audit_local_vlm_evidence_b1r_coverage.py tests/test_audit_local_vlm_evidence_b1r_coverage.py
git commit -m "feat: B1R Python Evidence coverage 감사 추가"
```

- [ ] **Step 6: initial production snapshot을 SELECT-only로 만든다**

```bash
CUTOFF="$(awk -F': ' '/^- coverage_cutoff_started_at:/ {print $2}' reports/local-vlm-evidence-b1r/RUNTIME-SNAPSHOT.md)"
uv run python scripts/audit_local_vlm_evidence_b1r_coverage.py \
  --cutoff-started-at "$CUTOFF" \
  --json-out experiments/local-vlm-evidence-analyst/b1r-coverage-before.json \
  --report-out reports/local-vlm-evidence-b1r/COVERAGE-BEFORE.md
```

Expected: `coverage_verdict=COVERAGE_OPEN`, `range_start_date`/`range_end_date` populated, query는 SELECT-only.

---

### Task 2: Historical enqueuer missing-progress hardening

**Files (`petcam-nightly-reporter`):**
- Modify: `scripts/enqueue_python_evidence_backfill.py`
- Modify: `tests/test_enqueue_python_evidence_backfill.py`

**Interfaces:**
- Consumes: date range, cutoff, active schema/algo, `limit` 1..5000.
- Produces: `load_missing_clips(...) -> list[dict]`, same public `enqueue_backfill(...) -> dict`.

- [ ] **Step 1: 안전한 code base에서 feature branch를 만든다**

Mac mini runtime HEAD가 pushed history에 있고 `origin/main`과 FF 관계일 때만 진행한다. runtime commit이
origin/main에 포함되지 않았지만 origin/main이 runtime commit의 조상이면 disposable worktree에서 FF-only
push를 수행한다. 두 commit이 non-ancestor면 `B1R_BLOCKED_RUNTIME_DRIFT`로 멈춘다.

```bash
git -C /Users/baek/petcam-nightly-reporter fetch origin
git -C /Users/baek/petcam-nightly-reporter worktree add /tmp/nightly-b1r origin/main
git -C /tmp/nightly-b1r switch -c feat/local-vlm-evidence-b1r
```

- [ ] **Step 2: starvation RED tests를 작성한다**

```python
def test_existing_first_page_advances_to_later_missing_clips():
    sb = FakeJobsSB(_clips(120), existing_job_clip_ids=[f"clip-{i:03d}" for i in range(100)])
    stats = bf.enqueue_backfill(sb, start_date=D, end_date=D, limit=20, dry_run=False, page_size=25)
    assert stats["enqueued"] == 20
    assert {j["clip_id"] for j in sb.jobs} >= {f"clip-{i:03d}" for i in range(100, 120)}

def test_same_range_second_run_reaches_next_missing_page():
    sb = FakeJobsSB(_clips(80))
    first = bf.enqueue_backfill(sb, start_date=D, end_date=D, limit=30, dry_run=False, page_size=10)
    second = bf.enqueue_backfill(sb, start_date=D, end_date=D, limit=30, dry_run=False, page_size=10)
    assert (first["enqueued"], second["enqueued"]) == (30, 30)
    assert len({j["clip_id"] for j in sb.jobs}) == 60

def test_cutoff_prevents_new_live_clip_from_historical_enqueue():
    stats = bf.enqueue_backfill(sb_with_clip_after_cutoff, start_date=D, end_date=D, limit=30,
                                cutoff_started_at=CUTOFF, dry_run=False)
    assert stats["enqueued"] == 0
```

- [ ] **Step 3: RED를 확인한다**

```bash
cd /tmp/nightly-b1r
uv run pytest -q tests/test_enqueue_python_evidence_backfill.py
```

Expected: existing implementation scans the first N and the new tests fail.

- [ ] **Step 4: keyset missing scan을 구현한다**

```python
def load_missing_clips(sb, *, start_date, end_date, cutoff_started_at, limit, page_size=500):
    """(started_at,id) keyset scan; active job이 없는 playable clip만 최대 limit 반환."""
    out, cursor = [], None
    while len(out) < limit:
        page = _fetch_motion_page(sb, start_date, end_date, cutoff_started_at, cursor, page_size)
        if not page:
            break
        existing = _load_existing_job_clip_ids(sb, [row["id"] for row in page])
        out.extend(row for row in page if row["id"] not in existing)
        cursor = (page[-1]["started_at"], page[-1]["id"])
    return out[:limit]
```

`_fetch_motion_page`는 `started_at > cursor.ts OR (started_at == cursor.ts AND id > cursor.id)`의 keyset을 사용한다. `_load_existing_job_clip_ids`는 ID를 최대 200개 chunk로 조회한다. `dry_run`도 같은 missing set을 계산하지만 upsert 호출은 0이어야 한다.

- [ ] **Step 5: GREEN과 nightly 전체 회귀를 확인한다**

```bash
uv run pytest -q tests/test_enqueue_python_evidence_backfill.py
uv run pytest -q
python -m compileall -q reporter scripts
git diff --check
```

Expected: focused/full PASS and clean.

- [ ] **Step 6: commit·push하고 Mac mini에는 아직 배포하지 않는다**

```bash
git add scripts/enqueue_python_evidence_backfill.py tests/test_enqueue_python_evidence_backfill.py
git commit -m "fix: Python Evidence 역사 enqueue 굶김 방지"
git push -u origin feat/local-vlm-evidence-b1r
```

---

### Task 3: Selector v2 multi-match eligibility

**Files:**
- Modify: `scripts/local_vlm_evidence_candidates.py`
- Modify: `tests/test_local_vlm_evidence_candidates.py`

**Interfaces:**
- Consumes: existing `SourceRow`, `Quantiles`, six frozen predicates.
- Produces: `classify_eligible_strata(row, q) -> dict[str, tuple[str, ...]]` and `SELECTOR_VERSION_V2`.

- [ ] **Step 1: RED tests를 작성한다**

```python
def test_v2_keeps_hardcase_and_absent_eligibility():
    got = classify_eligible_strata(
        source(activity_decision="exclude_absent", gecko_visible=False,
               frames_sampled=3, level1_status="no_bbox"), quantiles()
    )
    assert set(got) == {"absent", "hardcase"}

def test_v2_keeps_hardcase_and_rest_eligibility():
    got = classify_eligible_strata(
        source(activity_decision="unknown", gecko_visible=True, level1_status="no_bbox",
               global_motion_series=(0.1,), roi_motion_series=(0.9,)),
        Quantiles(0.5, 0.8, 0.3),
    )
    assert {"hardcase", "rest_micro"} <= set(got)

def test_v1_single_assignment_is_preserved_for_reproduction():
    assert classify_candidate(source(level1_status="no_bbox", excursion_count=4), quantiles()).stratum == "hardcase"
```

- [ ] **Step 2: RED를 확인한다**

```bash
uv run pytest -q tests/test_local_vlm_evidence_candidates.py -k "v2 or v1_single"
```

Expected: missing `classify_eligible_strata` failure.

- [ ] **Step 3: independent predicates를 구현한다**

```python
SELECTOR_VERSION_V2 = "local-vlm-evidence-selector-v2"

def classify_eligible_strata(row: SourceRow, q: Quantiles) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    hardcase = _hardcase_reasons(row)
    if hardcase:
        result["hardcase"] = hardcase
    # wheel, lick, rest, big, absent를 elif가 아닌 독립 if로 평가한다.
    # 각 reason tuple은 기존 v1 predicate와 같은 의미를 유지한다.
    return {name: result[name] for name in STRATA if name in result}
```

기존 `_classify`, `classify_candidate`, `build_episode_candidates`는 v1 재현용으로 그대로 유지한다. 모델 출력 필드를 SourceRow에 추가하지 않는다.

- [ ] **Step 4: GREEN과 회귀를 확인한다**

```bash
uv run pytest -q tests/test_local_vlm_evidence_candidates.py
git diff --check
```

- [ ] **Step 5: commit한다**

```bash
git add scripts/local_vlm_evidence_candidates.py tests/test_local_vlm_evidence_candidates.py
git commit -m "feat: Local VLM selector v2 다중 적격 판정"
```

---

### Task 4: Scarcity-first global allocator

**Files:**
- Modify: `scripts/local_vlm_evidence_candidates.py`
- Modify: `tests/test_local_vlm_evidence_candidates.py`

**Interfaces:**
- Consumes: `classify_eligible_strata`, existing episode clustering and stratum sort.
- Produces: `build_episode_candidates_v2(rows, target_per_stratum=30) -> list[Candidate]`.

- [ ] **Step 1: RED tests를 작성한다**

```python
def test_scarcity_first_assigns_shared_episode_to_absent_not_hardcase():
    rows = [shared_absent_hardcase("shared"), hardcase_only("h2"), hardcase_only("h3")]
    got = build_episode_candidates_v2(rows, target_per_stratum=1)
    assert [(c.stratum, c.clip_id) for c in got] == [("absent", "shared"), ("hardcase", "h2")]

def test_v2_global_clip_and_episode_overlap_is_zero():
    got = build_episode_candidates_v2(overlapping_fixture(), target_per_stratum=2)
    assert len({c.clip_id for c in got}) == len(got)
    assert len({c.episode_key for c in got}) == len(got)

def test_v2_is_input_order_invariant():
    baseline = candidates_sha256(build_episode_candidates_v2(rows, target_per_stratum=2))
    assert all(candidates_sha256(build_episode_candidates_v2(shuffle(rows, seed), 2)) == baseline
               for seed in (1, 7, 42))
```

- [ ] **Step 2: RED를 확인한다**

```bash
uv run pytest -q tests/test_local_vlm_evidence_candidates.py -k "scarcity or v2_global or v2_is_input"
```

- [ ] **Step 3: allocator를 구현한다**

```python
def build_episode_candidates_v2(rows: Sequence[SourceRow], target_per_stratum: int = 30) -> list[Candidate]:
    """각 (episode,stratum) 대표를 만든 뒤 remaining 수가 적은 stratum부터 1자리씩 배정."""
    if target_per_stratum < 1:
        raise ValueError("target_per_stratum must be positive")
    # pending[stratum] = deterministic representatives
    # assigned_clips/assigned_episodes는 전역 집합
    # 매 round마다 usable count가 가장 작은 미완성 stratum 선택
    # tie-break는 STRATA index
    # 배정 후 모든 pending에서 같은 clip/episode 제거하고 scarcity 재계산
```

Candidate identity에는 `selector_version=SELECTOR_VERSION_V2`를 넣는다. v1 identity 함수는 default v1을 유지해 기존 SHA 재현을 보존한다.

- [ ] **Step 4: full selector tests를 통과시킨다**

```bash
uv run pytest -q tests/test_local_vlm_evidence_candidates.py
git diff --check
```

- [ ] **Step 5: commit한다**

```bash
git add scripts/local_vlm_evidence_candidates.py tests/test_local_vlm_evidence_candidates.py
git commit -m "feat: Local VLM 희소군 우선 후보 배정"
```

---

### Task 5: B1R probe, exact human join, independent recomputation

**Files:**
- Modify: `scripts/probe_local_vlm_evidence_candidates.py`
- Modify: `tests/test_probe_local_vlm_evidence_candidates.py`
- Create: `scripts/recompute_local_vlm_evidence_b1r.py`
- Create: `tests/test_recompute_local_vlm_evidence_b1r.py`

**Interfaces:**
- Consumes: fixed cutoff, active runs, `build_episode_candidates_v2`.
- Produces: v1/v2 stage counts, v2 pool SHA, optional 180 manifest, independent match verdict.

- [ ] **Step 1: RED tests를 작성한다**

```python
def test_probe_uses_v2_without_overwriting_v1_artifacts(tmp_path):
    result = build_availability(rows, selector_version="local-vlm-evidence-selector-v2")
    assert result.selector_version == "local-vlm-evidence-selector-v2"
    assert result.legacy_v1_counts is not None

def test_exact_human_clip_join_enables_lick_candidate():
    client = fake_client(evidence_clip="motion-1", human_behavior_clip="motion-1", action="drinking")
    assert load_sources(client, cutoff=CUTOFF)[0].human_actions == frozenset({"drinking"})

def test_fuzzy_time_or_filename_join_is_forbidden():
    client = fake_client(evidence_clip="motion-1", human_behavior_clip="different", action="drinking")
    assert load_sources(client, cutoff=CUTOFF)[0].human_actions == frozenset()
```

- [ ] **Step 2: RED를 확인한다**

```bash
uv run pytest -q tests/test_probe_local_vlm_evidence_candidates.py tests/test_recompute_local_vlm_evidence_b1r.py
```

- [ ] **Step 3: probe v2를 구현한다**

CLI에 필수 `--selector-version local-vlm-evidence-selector-v2`와 필수 `--cutoff-started-at`을 추가한다. aggregate에 아래 stage를 모두 기록한다.

```json
{
  "raw_eligible_clip_counts": {},
  "episode_representative_counts": {},
  "final_allocated_counts": {},
  "legacy_v1_counts": {},
  "clip_overlap": 0,
  "episode_overlap": 0,
  "manifest_emitted": false
}
```

180 manifest는 모든 final count가 30이고 camera/date/overlap 계약을 통과할 때만 생성한다. 기존 B1 aggregate/report 경로를 쓰지 않는다.

- [ ] **Step 4: 독립 recompute를 구현한다**

`recompute_local_vlm_evidence_b1r.py`는 `build_availability`와 `build_episode_candidates_v2`를 import하지 않는다. 동일 pool artifact를 stdlib로 읽어 count, overlap, canonical SHA를 재계산하고 mismatch면 exit 1을 반환한다.

- [ ] **Step 5: GREEN과 lab 전체 회귀를 확인한다**

```bash
uv run pytest -q tests/test_probe_local_vlm_evidence_candidates.py tests/test_recompute_local_vlm_evidence_b1r.py
uv run pytest -q
git diff --check
```

- [ ] **Step 6: commit한다**

```bash
git add scripts/probe_local_vlm_evidence_candidates.py scripts/recompute_local_vlm_evidence_b1r.py \
  tests/test_probe_local_vlm_evidence_candidates.py tests/test_recompute_local_vlm_evidence_b1r.py
git commit -m "feat: Local VLM B1R 독립 가용성 검증"
```

---

### Task 6: Mac mini canary와 bounded historical drain

**Files:**
- Update: `reports/local-vlm-evidence-b1r/RUNTIME-SNAPSHOT.md`
- Create: `reports/local-vlm-evidence-b1r/BACKFILL-PROGRESS.md`
- Runtime only: `/tmp/python-evidence-worker.log`

**Interfaces:**
- Consumes: pushed nightly hardening branch and Task 1 coverage audit.
- Produces: canary result, coverage checkpoints, closure or explicit block verdict.

- [ ] **Step 1: cross-repo review와 FF integration을 수행한다**

Lab/nightly 전체 테스트가 green이고 branch가 clean/pushed인 것을 확인한다. nightly hardening은 `origin/main`과 FF 가능할 때만 disposable worktree에서 FF-only 통합한다. lab B1R code도 현재 feature branch에 push하되 B2 코드는 없다. Force push 금지.

- [ ] **Step 2: Mac mini를 pull하고 30-clip canary dry-run을 한다**

```bash
ssh home-mac 'cd /Users/baek-end/petcam-nightly-reporter && git fetch origin && git merge --ff-only origin/main'
CUTOFF="$(awk -F': ' '/^- coverage_cutoff_started_at:/ {print $2}' reports/local-vlm-evidence-b1r/RUNTIME-SNAPSHOT.md)"
START_DATE="$(uv run python -c 'import json; print(json.load(open("experiments/local-vlm-evidence-analyst/b1r-coverage-before.json"))["range_start_date"])')"
END_DATE="${CUTOFF:0:10}"
ssh home-mac "cd /Users/baek-end/petcam-nightly-reporter && \
  uv run python -m scripts.enqueue_python_evidence_backfill \
  --start-date '$START_DATE' --end-date '$END_DATE' --limit 30 \
  --cutoff-started-at '$CUTOFF' --dry-run"
```

Expected: scanned progress includes existing-job pages and reports exactly up to 30 missing, mutation 0.

- [ ] **Step 3: 30개 enqueue·처리 canary를 수행한다**

```bash
ssh home-mac "cd /Users/baek-end/petcam-nightly-reporter && \
  uv run python -m scripts.enqueue_python_evidence_backfill \
  --start-date '$START_DATE' --end-date '$END_DATE' --limit 30 \
  --cutoff-started-at '$CUTOFF'"
```

기존 LaunchAgent의 자연 cycle 또는 동일 expected-host 환경의 foreground 1회로 처리한다. run/provenance, duplicate 0, temp 0, 금지 테이블 mutation 0을 확인한다. 하나라도 어기면 대량 enqueue 금지.

- [ ] **Step 4: bounded enqueue/drain을 반복한다**

한 enqueue 호출은 500 missing clip 이하로 제한한다. 각 checkpoint마다 coverage audit을 실행하고
`eligible/succeeded/terminal/open/silent_missing/live_lag_p95/temp/failure_by_code`를 append한다. live lag p95>15분,
두 cycle 연속 failure 증가, temp 잔류, runtime drift가 발생하면 즉시 정지한다.

- [ ] **Step 5: closure를 독립 대조한다**

```bash
uv run python scripts/audit_local_vlm_evidence_b1r_coverage.py \
  --cutoff-started-at "$CUTOFF" \
  --json-out experiments/local-vlm-evidence-analyst/b1r-coverage-after.json \
  --report-out reports/local-vlm-evidence-b1r/COVERAGE-AFTER.md
```

Expected:

```text
eligible = succeeded_with_active_run + allowlisted_terminal
silent_missing = 0
queued + processing + failed_retryable = 0
```

Terminal clip은 failure code별로 보고하고 exact authorized mapping이 있을 때만 label web URL을 붙인다.

---

### Task 7: Final B1R run, SOT, report, hard stop

**Files:**
- Create: `experiments/local-vlm-evidence-analyst/b1r-candidate-availability.json`
- Create: `experiments/local-vlm-evidence-analyst/B1R-CANDIDATE-AVAILABILITY.md`
- Create ignored: `storage/local-vlm-evidence-analyst/b1r-candidate-pool.json`
- Create ignored when passing: `storage/local-vlm-evidence-analyst/b1r-manifest.json`
- Create: `docs/handoff-prompts/2026-07-22-local-vlm-evidence-b1r-report.md`
- Modify additively: `specs/next-session.md`
- Modify additively: `.claude/donts-audit.md`

**Interfaces:**
- Consumes: closed coverage snapshot and selector v2.
- Produces: one `B1R_*` verdict and immutable report.

- [ ] **Step 1: B1R probe를 동일 cutoff로 실행한다**

```bash
cd /Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt
CUTOFF="$(awk -F': ' '/^- coverage_cutoff_started_at:/ {print $2}' reports/local-vlm-evidence-b1r/RUNTIME-SNAPSHOT.md)"
uv run python scripts/probe_local_vlm_evidence_candidates.py \
  --selector-version local-vlm-evidence-selector-v2 \
  --cutoff-started-at "$CUTOFF" \
  --aggregate-out experiments/local-vlm-evidence-analyst/b1r-candidate-availability.json \
  --pool-out storage/local-vlm-evidence-analyst/b1r-candidate-pool.json \
  --report-out experiments/local-vlm-evidence-analyst/B1R-CANDIDATE-AVAILABILITY.md
```

- [ ] **Step 2: 독립 재계산을 실행한다**

```bash
uv run python scripts/recompute_local_vlm_evidence_b1r.py \
  --aggregate experiments/local-vlm-evidence-analyst/b1r-candidate-availability.json \
  --pool storage/local-vlm-evidence-analyst/b1r-candidate-pool.json
```

Expected: exact MATCH. mismatch는 `B1R_REJECT_INTEGRITY`.

- [ ] **Step 3: verdict를 결정한다**

우선순위는 다음과 같다.

```text
B1R_REJECT_INTEGRITY
> B1R_BLOCKED_RUNTIME_DRIFT
> B1R_BLOCKED_EVIDENCE_COVERAGE
> B1R_BLOCKED_SEMANTIC_DATA
> B1R_DATA_AVAILABLE
```

한 strata라도 final allocated <30이면 manifest를 만들지 않는다. 기준을 변경하지 않는다.

- [ ] **Step 4: 보고서와 SOT를 작성한다**

보고서에 다음을 전부 포함한다.

- runtime host/HEAD/service identity
- cutoff와 coverage closure 수치
- backfill canary·총 enqueue/처리/terminal·live 영향·temp
- v1 vs v2: raw eligible / episode rep / final allocated 6개 수량
- camera/date 분포, clip/episode/split overlap
- pool SHA와 independent recomputation
- exact/fuzzy human join 수량
- mutation 0과 금지동작 감사
- 최종 verdict와 다음 허용 작업

- [ ] **Step 5: 전체 검증한다**

```bash
uv run pytest -q
git diff --check
git status --short
```

Nightly와 gate도 실제 변경 branch에서 전체 테스트·compile/bash syntax를 다시 실행한다.

- [ ] **Step 6: 명시 산출물만 commit·push한다**

```bash
git add experiments/local-vlm-evidence-analyst/b1r-candidate-availability.json \
  experiments/local-vlm-evidence-analyst/B1R-CANDIDATE-AVAILABILITY.md \
  reports/local-vlm-evidence-b1r \
  docs/handoff-prompts/2026-07-22-local-vlm-evidence-b1r-report.md \
  specs/next-session.md .claude/donts-audit.md
git commit -m "docs: Local VLM B1R 가용성 판정 기록"
git push origin codex/local-vlm-evidence-web-gt
```

- [ ] **Step 7: 반드시 멈춘다**

`B1R_DATA_AVAILABLE`이어도 B2·모델 실행을 자동 시작하지 않는다. Owner가 report와 manifest SHA를 검토한 뒤 새 handoff를 발행해야 한다.

## Plan Self-Review Record

- Spec coverage: R0 runtime/cutoff, R1 missing-progress backfill, R2 multi-match/scarcity, R3 independent verdict 모두 task에 매핑됨.
- Scope: 기존 worker/LaunchAgent 재사용, 새 DB migration·새 service 없음.
- Identity: v1 재현 함수·artifact 보존, v2 identity 별도.
- Safety: laptop runtime 우회, model/B2/GT write, threshold 사후 변경 금지.
- Stop: runtime drift, coverage open, integrity mismatch, semantic shortage를 서로 다른 verdict로 분리함.
