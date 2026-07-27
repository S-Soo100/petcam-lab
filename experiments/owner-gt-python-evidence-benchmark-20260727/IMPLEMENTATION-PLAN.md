# Owner GT Python Evidence Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Owner GT 172건과 기존 Python Evidence를 SELECT-only로 연결해 `roi_mean`의 moving/static-only 구분력을 재현 가능한 descriptive benchmark로 측정한다.

**Architecture:** production DB에서는 익명화된 단일 JSON snapshot과 6개 source table fingerprint만 SELECT한다. 순수 Python 분석기는 snapshot에서 기술 coverage, AUROC, episode-cluster bootstrap CI와 verdict를 계산하고, 별도 verifier가 summary를 독립 재계산한다.

**Tech Stack:** Python 3.12, stdlib `json/random/statistics/hashlib`, SciPy 1.17, pytest 9, PostgreSQL JSONB/pgcrypto, Supabase SELECT-only MCP.

## Global Constraints

- 변경 경로는 `experiments/owner-gt-python-evidence-benchmark-20260727/`만 허용한다.
- 고정 cohort는 172건, ordered SHA-256은 `8e2bf4e73f8f033288d7632e25e2fbfd69d3de98c62dade2996bbe33686c96ba`다.
- discrimination population은 moving 108, static-only 32, 제외 32가 기대값이며 불일치 시 HOLD다.
- primary feature는 `motion_summary.roi_mean`, 높은 값이 moving 방향이다.
- 5분 episode bootstrap은 seed `20260727`, 10,000 iterations로 고정한다.
- 모델 학습, feature 합성, weight/threshold sweep, VLM 호출, DB/R2 write, runtime/deploy 변경을 금지한다.
- tracked artifact에 UUID, 메모, URL, R2 key, 이메일을 저장하지 않는다.
- production 판정이 아니라 retrospective descriptive verdict만 낸다.

---

## File Map

- `TEST-SHEET.md`: 결과 조회 전에 동결되는 질문·표본·feature·통계·판정 계약
- `benchmark.sql`: Owner cohort, episode, 익명 feature row, provenance, source fingerprint SELECT
- `analyze.py`: snapshot schema 검증과 primary/secondary summary 계산
- `test_analyze.py`: label, AUROC, bootstrap, verdict, snapshot 계약 단위 테스트
- `verify_results.py`: `analyze.py`를 import하지 않는 독립 summary/verdict 재계산
- `test_verify_results.py`: 변조된 summary와 민감 원시값 거부 테스트
- `snapshot-aggregate.json`: DB SELECT 결과의 익명화된 분석 row와 provenance
- `fingerprints-start.csv`, `fingerprints-end.csv`: 6개 source table 시작/종료 count+ordered hash
- `summary.json`: 분석 정본
- `REPORT.md`: 결과, 한계, 다음 최소 행동, mutation 0 범위

---

### Task 1: Freeze TEST-SHEET and SELECT Contract

**Files:**
- Create: `experiments/owner-gt-python-evidence-benchmark-20260727/TEST-SHEET.md`
- Create: `experiments/owner-gt-python-evidence-benchmark-20260727/benchmark.sql`

**Interfaces:**
- Consumes: `DESIGN.md`의 cohort SHA, population, feature, bootstrap, verdict 계약
- Produces: `benchmark.sql` statement 1의 `snapshot` JSON object와 statement 2의 fingerprint rows

- [ ] **Step 1: Write the frozen TEST-SHEET**

`TEST-SHEET.md`에 아래 값을 그대로 고정한다.

```markdown
# TEST-SHEET — Owner GT × Python Evidence Motion Signal

**상태:** 🔒 FROZEN
**승인:** owner 대화 승인, 2026-07-27
**질문:** roi_mean이 moving 108과 static-only 32를 높은 값=moving 방향으로 구분하는가?
**cohort:** eligible 172, SHA-256 8e2bf4e73f8f033288d7632e25e2fbfd69d3de98c62dade2996bbe33686c96ba
**primary:** motion_summary.roi_mean raw AUROC
**bootstrap:** 5분 episode cluster, seed 20260727, iterations 10000, percentile 95% CI
**금지:** threshold/feature/weight 튜닝, classifier, VLM, DB/R2 write, production 변경
```

표본, secondary diagnostics, 판정 4종, mutation fingerprint 6개 table, raw 비추적 규칙은
`DESIGN.md` §4~§10과 동일한 문장으로 포함한다.

- [ ] **Step 2: Write the anonymous snapshot SELECT**

`benchmark.sql`의 첫 statement는 다음 CTE 구조를 사용한다.

```sql
WITH owner_identity AS (
  SELECT u.id
  FROM auth.users u
  JOIN public.user_profiles p ON p.id = u.id
  LEFT JOIN public.labelers l ON l.user_id = u.id
  WHERE p.display_name = '운영자'
    AND l.user_id IS NULL
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_sessions s
      WHERE s.reviewed_by = u.id
    )
    AND EXISTS (
      SELECT 1 FROM public.motion_clip_labeling_triage_events e
      WHERE e.actor_id = u.id AND e.event_type = 'owner_started_labeling'
    )
),
cohort AS (
  SELECT
    s.*,
    mc.camera_id,
    mc.started_at,
    mc.duration_sec,
    mc.file_size
  FROM public.motion_clip_labeling_sessions s
  JOIN owner_identity o ON o.id = s.reviewed_by
  JOIN public.motion_clips mc ON mc.id = s.clip_id
  WHERE s.stage = 'completed'
    AND s.initial_gt IS NOT NULL
    AND s.current_gt IS NOT NULL
    AND s.completed_at IS NOT NULL
),
cohort_fingerprint AS (
  SELECT
    count(*) AS eligible_count,
    encode(
      digest(
        coalesce(string_agg(row_hash, '' ORDER BY clip_id), ''),
        'sha256'
      ),
      'hex'
    ) AS eligible_ordered_sha256
  FROM (
    SELECT
      clip_id,
      encode(digest(to_jsonb(c)::text, 'sha256'), 'hex') AS row_hash
    FROM cohort c
  ) hashed
),
eligible AS (
  SELECT
    c.clip_id,
    c.current_gt,
    c.camera_id,
    c.started_at,
    r.level0_status,
    r.level1_status,
    r.evidence_schema_version,
    r.algorithm_version,
    r.model_name,
    r.model_version,
    r.checkpoint_sha256,
    r.threshold,
    r.sampler_version,
    r.schema_version,
    r.frames_sampled,
    r.source_prelabel_identity,
    r.decoded_frame_count,
    r.motion_summary,
    r.spatial_dwell,
    r.periodicity_summary,
    jsonb_array_length(r.global_motion_series) AS global_series_length,
    jsonb_array_length(r.roi_motion_series) AS roi_series_length
  FROM cohort c
  JOIN public.clip_python_evidence_runs r ON r.clip_id = c.clip_id
),
ordered AS (
  SELECT
    *,
    lag(started_at) OVER (
      PARTITION BY camera_id ORDER BY started_at, clip_id
    ) AS previous_start
  FROM eligible
),
episode_numbered AS (
  SELECT
    *,
    sum(
      CASE
        WHEN previous_start IS NULL
          OR started_at - previous_start > interval '5 minutes'
        THEN 1 ELSE 0
      END
    ) OVER (
      PARTITION BY camera_id ORDER BY started_at, clip_id
    ) AS episode_number
  FROM ordered
),
anonymous_rows AS (
  SELECT
    substr(encode(digest(clip_id::text, 'sha256'), 'hex'), 1, 16) AS sample_key,
    substr(
      encode(
        digest(camera_id::text || ':' || episode_number::text, 'sha256'),
        'hex'
      ),
      1,
      16
    ) AS episode_key,
    'camera_' || (dense_rank() OVER (ORDER BY camera_id))::text AS camera_group,
    'camera_' || (dense_rank() OVER (ORDER BY camera_id))::text
      || ':' || (started_at AT TIME ZONE 'Asia/Seoul')::date::text AS camera_night,
    CASE
      WHEN current_gt->'observed_actions' ? 'moving' THEN 'moving'
      WHEN current_gt->'observed_actions' ? 'static'
        AND NOT (current_gt->'observed_actions' ? 'moving') THEN 'static_only'
      ELSE 'excluded'
    END AS label,
    level0_status,
    level1_status,
    decoded_frame_count,
    global_series_length,
    roi_series_length,
    nullif(motion_summary->>'roi_mean', '')::double precision AS roi_mean,
    nullif(spatial_dwell->>'observed_sec', '')::double precision AS observed_sec,
    nullif(periodicity_summary->>'peak_autocorr', '')::double precision
      AS peak_autocorr,
    evidence_schema_version,
    algorithm_version,
    model_name,
    model_version,
    checkpoint_sha256,
    threshold,
    sampler_version,
    schema_version,
    frames_sampled,
    source_prelabel_identity
  FROM episode_numbered
)
SELECT jsonb_build_object(
  'contract', jsonb_build_object(
    'snapshot_at_utc', now(),
    'eligible_count', count(*),
    'eligible_ordered_sha256',
      (SELECT eligible_ordered_sha256 FROM cohort_fingerprint),
    'episode_count', count(DISTINCT episode_key),
    'moving_count', count(*) FILTER (WHERE label = 'moving'),
    'static_only_count', count(*) FILTER (WHERE label = 'static_only'),
    'excluded_count', count(*) FILTER (WHERE label = 'excluded'),
    'provenance_contract_count',
      count(DISTINCT concat_ws(
        '|',
        evidence_schema_version,
        algorithm_version,
        model_name,
        model_version,
        checkpoint_sha256,
        threshold,
        sampler_version,
        schema_version,
        frames_sampled
      ))
  ),
  'records',
    jsonb_agg(
      to_jsonb(anonymous_rows)
        - 'evidence_schema_version'
        - 'algorithm_version'
        - 'model_name'
        - 'model_version'
        - 'checkpoint_sha256'
        - 'threshold'
        - 'sampler_version'
        - 'schema_version'
        - 'frames_sampled'
        - 'source_prelabel_identity'
      ORDER BY sample_key
    )
) AS snapshot
FROM anonymous_rows;
```

- [ ] **Step 3: Add source fingerprint SELECT**

두 번째 statement는 정확히 아래 6개 table만 대상으로 canonical row MD5를 계산한다.

```sql
SELECT
  now() AS snapshot_at_utc,
  'motion_clips' AS table_name,
  count(*) AS row_count,
  md5(coalesce(string_agg(
    md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)
  ), '')) AS ordered_fingerprint_md5
FROM public.motion_clips t
UNION ALL
SELECT
  now(),
  'motion_clip_labeling_triage',
  count(*),
  md5(coalesce(string_agg(
    md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)
  ), ''))
FROM public.motion_clip_labeling_triage t
UNION ALL
SELECT
  now(),
  'motion_clip_labeling_sessions',
  count(*),
  md5(coalesce(string_agg(
    md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)
  ), ''))
FROM public.motion_clip_labeling_sessions t
UNION ALL
SELECT
  now(),
  'motion_clip_labeling_session_revisions',
  count(*),
  md5(coalesce(string_agg(
    md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)
  ), ''))
FROM public.motion_clip_labeling_session_revisions t
UNION ALL
SELECT
  now(),
  'clip_python_evidence_runs',
  count(*),
  md5(coalesce(string_agg(
    md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)
  ), ''))
FROM public.clip_python_evidence_runs t
UNION ALL
SELECT
  now(),
  'clip_prelabels',
  count(*),
  md5(coalesce(string_agg(
    md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)
  ), ''))
FROM public.clip_prelabels t
ORDER BY table_name;
```

- [ ] **Step 4: Validate SELECT-only and frozen constants**

Run:

```bash
rg -n "\\b(INSERT|UPDATE|DELETE|MERGE|ALTER|DROP|TRUNCATE|CALL)\\b" \
  experiments/owner-gt-python-evidence-benchmark-20260727/benchmark.sql
rg -n "20260727|10000|roi_mean|8e2bf4e73f8" \
  experiments/owner-gt-python-evidence-benchmark-20260727/TEST-SHEET.md
```

Expected: 첫 명령 출력 0줄, 두 번째 명령은 동결값 4종을 모두 찾는다.

- [ ] **Step 5: Commit**

```bash
git add experiments/owner-gt-python-evidence-benchmark-20260727/TEST-SHEET.md \
  experiments/owner-gt-python-evidence-benchmark-20260727/benchmark.sql
git commit -m "test: Owner GT Evidence 벤치마크 계약 동결"
```

---

### Task 2: Build Pure Analysis Core with TDD

**Files:**
- Create: `experiments/owner-gt-python-evidence-benchmark-20260727/analyze.py`
- Create: `experiments/owner-gt-python-evidence-benchmark-20260727/test_analyze.py`

**Interfaces:**
- Consumes: `snapshot-aggregate.json` with `contract` and `records`
- Produces:
  - `validate_snapshot(snapshot: dict) -> None`
  - `auc_higher(records: list[dict], feature: str) -> float`
  - `cluster_bootstrap(records: list[dict], feature: str, iterations: int, seed: int) -> dict`
  - `decide(summary: dict) -> str`
  - `summarize(snapshot: dict) -> dict`

- [ ] **Step 1: Write failing partition and schema tests**

```python
def test_validate_snapshot_accepts_frozen_contract():
    snapshot = fixture_snapshot()
    validate_snapshot(snapshot)


def test_validate_snapshot_rejects_population_drift():
    snapshot = fixture_snapshot()
    snapshot["contract"]["eligible_count"] = 171
    with pytest.raises(ValueError, match="eligible_count"):
        validate_snapshot(snapshot)
```

Fixture는 172행을 만들지 않고 `validate_snapshot`에 optional expected-count parameters를
주입해 4/2/1/1의 축소 계약으로 검사한다. production 기본값만 172/108/32/32/39다.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
uv run pytest experiments/owner-gt-python-evidence-benchmark-20260727/test_analyze.py -q
```

Expected: import 또는 undefined function 실패.

- [ ] **Step 3: Implement snapshot validation**

```python
FROZEN = {
    "eligible_count": 172,
    "moving_count": 108,
    "static_only_count": 32,
    "excluded_count": 32,
    "episode_count": 39,
    "provenance_contract_count": 1,
}


def validate_snapshot(snapshot: dict, expected: dict | None = None) -> None:
    contract = snapshot.get("contract")
    records = snapshot.get("records")
    if not isinstance(contract, dict) or not isinstance(records, list):
        raise ValueError("snapshot requires contract and records")
    wanted = FROZEN if expected is None else expected
    for key, value in wanted.items():
        if contract.get(key) != value:
            raise ValueError(f"{key}: expected {value}, got {contract.get(key)}")
    if len(records) != contract["eligible_count"]:
        raise ValueError("record count does not match eligible_count")
```

각 record의 허용 key, label enum, finite numeric, unique `sample_key`, non-empty episode/camera
fields도 같은 함수에서 검사한다.

- [ ] **Step 4: Write failing AUROC tests**

```python
def test_auc_higher_perfect_and_tied():
    perfect = [
        {"label": "moving", "roi_mean": 3.0},
        {"label": "moving", "roi_mean": 4.0},
        {"label": "static_only", "roi_mean": 1.0},
        {"label": "static_only", "roi_mean": 2.0},
    ]
    assert auc_higher(perfect, "roi_mean") == 1.0
    tied = [
        {"label": "moving", "roi_mean": 1.0},
        {"label": "static_only", "roi_mean": 1.0},
    ]
    assert auc_higher(tied, "roi_mean") == 0.5
```

- [ ] **Step 5: Implement AUROC without fitting**

```python
def auc_higher(records: list[dict], feature: str) -> float:
    positive = [float(r[feature]) for r in records
                if r["label"] == "moving" and r.get(feature) is not None]
    negative = [float(r[feature]) for r in records
                if r["label"] == "static_only" and r.get(feature) is not None]
    if not positive or not negative:
        raise ValueError("AUROC requires both classes")
    wins = sum(
        1.0 if p > n else 0.5 if p == n else 0.0
        for p in positive
        for n in negative
    )
    return wins / (len(positive) * len(negative))
```

- [ ] **Step 6: Write failing deterministic clustered-bootstrap test**

```python
def test_cluster_bootstrap_is_deterministic_and_clustered():
    result_a = cluster_bootstrap(records, "roi_mean", iterations=200, seed=7)
    result_b = cluster_bootstrap(records, "roi_mean", iterations=200, seed=7)
    assert result_a == result_b
    assert result_a["valid_iterations"] <= 200
    assert 0.0 <= result_a["ci_low"] <= result_a["ci_high"] <= 1.0
```

Fixture는 episode 4개, 각 episode에 같은 class 2행을 둬 clip 단위가 아니라 episode 단위
복원추출인지 `sampled_episode_count` 진단으로 확인한다.

- [ ] **Step 7: Implement clustered bootstrap**

`episode_key`별 record를 묶고 `random.Random(seed).choices(episode_keys, k=len(episode_keys))`로
episode를 복원추출한다. 각 선택 occurrence의 record를 별도 복제해 합치고, 두 class가 모두
있을 때만 AUROC를 추가한다. `statistics.quantiles` 대신 선형 보간 percentile 함수를 구현해
2.5/97.5 percentile을 계산한다.

- [ ] **Step 8: Write failing verdict tests**

```python
@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        (supported_summary(), "PE_MOTION_SIGNAL_DESCRIPTIVE_SUPPORTED"),
        (inconclusive_summary(), "PE_MOTION_SIGNAL_INCONCLUSIVE"),
        (rejected_summary(), "PE_MOTION_SIGNAL_REJECTED"),
    ],
)
def test_decide(summary, expected):
    assert decide(summary) == expected
```

supported fixture는 coverage 0.96, CI low 0.60, 두 camera AUROC 0.55/0.70이야.
inconclusive는 CI low 0.48, rejected는 coverage 0.70이야.

- [ ] **Step 9: Implement summary and CLI**

`summarize`는 technical count, feature coverage, label distribution, primary AUROC/CI,
camera별 AUROC, camera-night median/IQR, secondary distributions, bootstrap invalid rate,
verdict를 반환해. CLI는 아래만 지원해.

```bash
uv run python experiments/owner-gt-python-evidence-benchmark-20260727/analyze.py \
  --snapshot experiments/owner-gt-python-evidence-benchmark-20260727/snapshot-aggregate.json \
  --output experiments/owner-gt-python-evidence-benchmark-20260727/summary.json
```

- [ ] **Step 10: Run analysis tests GREEN**

Run:

```bash
uv run pytest experiments/owner-gt-python-evidence-benchmark-20260727/test_analyze.py -q
```

Expected: all pass.

- [ ] **Step 11: Commit**

```bash
git add experiments/owner-gt-python-evidence-benchmark-20260727/analyze.py \
  experiments/owner-gt-python-evidence-benchmark-20260727/test_analyze.py
git commit -m "test: Evidence motion 신호 분석기 구현"
```

---

### Task 3: Build Independent Verifier and Artifact Guard

**Files:**
- Create: `experiments/owner-gt-python-evidence-benchmark-20260727/verify_results.py`
- Create: `experiments/owner-gt-python-evidence-benchmark-20260727/test_verify_results.py`

**Interfaces:**
- Consumes: snapshot, summary, start/end fingerprint CSV, all tracked experiment text
- Produces: exit 0 with `PE_BENCHMARK_ARTIFACTS_OK`, otherwise exit 1 with reason code

- [ ] **Step 1: Write failing summary-tamper test**

```python
def test_verifier_rejects_tampered_auc(tmp_path):
    write_valid_fixture(tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text())
    summary["primary"]["auc"] = 0.01
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    result = run_verifier(tmp_path)
    assert result.returncode == 1
    assert "SUMMARY_MISMATCH" in result.stderr
```

- [ ] **Step 2: Write failing sensitive-data and mutation tests**

민감 문자열은 소스에 literal로 남지 않도록 조각을 합쳐 fixture에 써.

```python
uuid_value = "-".join(["123e4567", "e89b", "12d3", "a456", "426614174000"])
url_value = "https" + "://" + "example.invalid/video"
```

start/end row_count 또는 hash 하나를 바꿨을 때 `SOURCE_MUTATION`, UUID/URL/email/R2 key가
있을 때 `SENSITIVE_RAW_DATA`로 실패하는지 검사한다.

- [ ] **Step 3: Run verifier tests RED**

Run:

```bash
uv run pytest \
  experiments/owner-gt-python-evidence-benchmark-20260727/test_verify_results.py -q
```

Expected: verifier missing/import failure.

- [ ] **Step 4: Implement independent calculations**

`verify_results.py`는 `analyze.py`를 import하지 않아. 자체 pairwise AUROC, episode bootstrap,
verdict 함수를 중복 구현하고 snapshot에서 summary 핵심 필드를 다시 계산해 exact 또는
`abs(a-b) <= 1e-12`로 대조한다.

- [ ] **Step 5: Implement source and raw guards**

- fingerprint CSV는 timestamp를 제외한 `(table_name,row_count,ordered_fingerprint_md5)`를 비교해.
- `.md/.sql/.py/.json/.csv`를 스캔해 UUID, URL, email, `terra-clips/`, `motion-clips/`를 거부해.
- `benchmark.sql`은 comment를 제거한 뒤 각 statement가 SELECT/WITH로 시작하고 write keyword가
  없는지 검사해.

- [ ] **Step 6: Run verifier tests GREEN**

Run:

```bash
uv run pytest \
  experiments/owner-gt-python-evidence-benchmark-20260727/test_verify_results.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add experiments/owner-gt-python-evidence-benchmark-20260727/verify_results.py \
  experiments/owner-gt-python-evidence-benchmark-20260727/test_verify_results.py
git commit -m "test: Evidence benchmark 독립 검증기 추가"
```

---

### Task 4: Execute SELECT-only Snapshot and Benchmark

**Files:**
- Create: `experiments/owner-gt-python-evidence-benchmark-20260727/fingerprints-start.csv`
- Create: `experiments/owner-gt-python-evidence-benchmark-20260727/snapshot-aggregate.json`
- Create: `experiments/owner-gt-python-evidence-benchmark-20260727/summary.json`
- Create: `experiments/owner-gt-python-evidence-benchmark-20260727/fingerprints-end.csv`

**Interfaces:**
- Consumes: frozen `benchmark.sql`, production DB SELECT access, `analyze.py`
- Produces: immutable anonymized snapshot, source mutation evidence, benchmark verdict

- [ ] **Step 1: Record git and source baseline**

Run:

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

Expected: experiment branch, no unrelated changes.

- [ ] **Step 2: Execute start fingerprint SELECT**

Supabase MCP에서 `benchmark.sql` statement 2만 실행해 6개 table의 count+ordered hash를
`fingerprints-start.csv`로 저장한다. INSERT/UPDATE/DELETE/RPC/migration은 실행하지 않아.

- [ ] **Step 3: Execute anonymous snapshot SELECT**

Supabase MCP에서 statement 1만 실행해 단일 `snapshot` JSON을 얻고
`snapshot-aggregate.json`에 저장해. 다음 assertion이 모두 맞지 않으면 분석하지 말고 HOLD해.

```text
eligible=172
episodes=39
moving=108
static_only=32
excluded=32
provenance_contract_count=1
records length=172
```

- [ ] **Step 4: Run analysis**

Run:

```bash
uv run python experiments/owner-gt-python-evidence-benchmark-20260727/analyze.py \
  --snapshot experiments/owner-gt-python-evidence-benchmark-20260727/snapshot-aggregate.json \
  --output experiments/owner-gt-python-evidence-benchmark-20260727/summary.json
```

Expected: exit 0 and one frozen verdict.

- [ ] **Step 5: Execute end fingerprint SELECT**

statement 2를 다시 실행해 `fingerprints-end.csv`에 저장해. start/end timestamp는 달라도 되고
6개 table의 count+ordered hash는 모두 같아야 해.

- [ ] **Step 6: Run independent artifact verifier**

Run:

```bash
uv run python experiments/owner-gt-python-evidence-benchmark-20260727/verify_results.py \
  --root experiments/owner-gt-python-evidence-benchmark-20260727
```

Expected: `PE_BENCHMARK_ARTIFACTS_OK`.

- [ ] **Step 7: Commit measured artifacts**

```bash
git add experiments/owner-gt-python-evidence-benchmark-20260727/fingerprints-start.csv \
  experiments/owner-gt-python-evidence-benchmark-20260727/fingerprints-end.csv \
  experiments/owner-gt-python-evidence-benchmark-20260727/snapshot-aggregate.json \
  experiments/owner-gt-python-evidence-benchmark-20260727/summary.json
git commit -m "test: Owner GT Evidence benchmark 실측"
```

---

### Task 5: Report, Review, and Final Verification

**Files:**
- Create: `experiments/owner-gt-python-evidence-benchmark-20260727/REPORT.md`
- Modify: `experiments/owner-gt-python-evidence-benchmark-20260727/TEST-SHEET.md`

**Interfaces:**
- Consumes: verified `summary.json`, fingerprints, design limits
- Produces: review-ready report and pushed feature branch

- [ ] **Step 1: Write REPORT from measured summary**

REPORT는 정확히 아래 순서로 작성해.

```markdown
# Owner GT × Python Evidence Motion Signal Benchmark
## Verdict
## Frozen contract
## Cohort and mutation scope
## Technical coverage
## Primary AUROC and clustered CI
## Camera/camera-night drift
## Secondary diagnostics
## Interpretation and limitations
## Service impact
## Next minimum action
## Not run
## Git and verification
```

서비스 영향에는 즉시 production 변경 0, SUPPORTED면 selector 후보 TEST-SHEET만 허용,
INCONCLUSIVE면 future camera-night 수집, REJECTED면 `roi_mean` 후보 폐기를 명시해.

- [ ] **Step 2: Link REPORT from TEST-SHEET without changing frozen rules**

TEST-SHEET 하단에 REPORT 상대 링크와 실행 commit만 append해. 질문·표본·feature·seed·iterations·
판정 기준은 수정하지 않아.

- [ ] **Step 3: Run experiment tests and verifier**

Run:

```bash
uv run pytest experiments/owner-gt-python-evidence-benchmark-20260727 -q
uv run python experiments/owner-gt-python-evidence-benchmark-20260727/verify_results.py \
  --root experiments/owner-gt-python-evidence-benchmark-20260727
git diff --check
```

Expected: all tests pass, `PE_BENCHMARK_ARTIFACTS_OK`, diff errors 0.

- [ ] **Step 4: Run full regression**

Run:

```bash
uv run pytest -q
```

Expected: existing suite plus new tests pass; skipped tests는 기존 이유만 허용.

- [ ] **Step 5: Independent review**

reviewer에게 DESIGN/TEST-SHEET 정합, 통계 구현, SQL SELECT-only, raw 누출, summary/report 일치,
production 과장 여부를 검수시켜 Critical/Important blocker 0을 요구해.

- [ ] **Step 6: Commit report and push**

```bash
git add experiments/owner-gt-python-evidence-benchmark-20260727
git commit -m "docs: Owner GT Evidence benchmark 결과 보고"
git push -u origin codex/owner-gt-python-evidence-benchmark-20260727
```

- [ ] **Step 7: Record final state**

Run:

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse '@{upstream}'
git rev-parse origin/main
```

Expected: worktree clean, HEAD=upstream, main merge/deploy 없음.
