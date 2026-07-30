# RBA Data Engine Formal Blind30 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 일일 이중 블라인드 원장과 comparator를 바꾸지 않고, 동결된 30개를 두 자격 reviewer에게 원자 예약하고 raw 제출로 별도 연구 지표를 계산하는 formal Blind30 실행 경로를 만든다.

**Architecture:** 기존 `canary` cohort/queue/submit/consensus 저장 구조를 재사용하되 exact-30 생성만 별도 service-role RPC로 추가한다. 표본 선택·manifest 생성과 연구 채점은 Python 순수 함수/CLI로 분리하고, 운영 `motion-blind-v1`은 owner adjudication 라우팅에만 그대로 사용한다. 신규 migration 배포와 실제 cohort 예약을 분리해 reviewer pair가 준비되기 전 production row 생성은 0으로 유지한다.

**Tech Stack:** PostgreSQL 15 / Supabase RPC / Python 3.12 + pytest / TypeScript + Vitest 회귀 테스트 / `uv`

## Global Constraints

- 연구 계약 정본은 `experiments/rba-data-engine-blind30/TEST-SHEET.md`다. 결과를 본 뒤 selection, threshold, comparator, abstain 규칙을 바꾸지 않는다.
- 기존 `motion_clip_review_slots`, `motion_clip_blind_submissions`, `motion_clip_consensus`, event/final row를 삭제·rewrite하지 않는다.
- 운영 `web/src/lib/motionBlindReview.ts`와 comparator version `motion-blind-v1`을 수정하지 않는다.
- 신규 cohort는 기존 `kind='canary'` 저장 구조를 재사용하고 label을 `b30v1:<64 lowercase hex>`로 고정한다.
- exact 30개, distinct reviewer 2명, slot 60개, awaiting consensus 30개를 한 DB transaction에서 만들거나 전부 rollback한다.
- 두 reviewer는 같은 active group의 approved non-owner이고 active `tutorial-v1` 현재 run 5/5를 waiver 없이 완료해야 한다.
- 선택기는 answer/GT, VLM/Gate/Python evidence, consensus result/status, triage decision을 읽지 않는다.
- 기존 제출 전 live slot과 `awaiting` live consensus는 후보로 허용한다. canary/formal 이력, live submission, live terminal consensus는 제외한다.
- manifest는 `/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-blind30-v1-manifest.json`에 mode `0600`으로 쓰고 Git에 넣지 않는다.
- reviewer에게 manifest, peer 답, prediction, consensus를 노출하지 않는다. cohort URL 한 개만 전달한다.
- agent/owner는 reviewer 대신 human submission을 만들지 않는다.
- Gemini CLI 실행·재설치·인증·fallback 등록을 금지한다.

---

## File Map

- Create `migrations/2026-07-31_motion_blind_formal30.sql`: exact-30 원자 예약 RPC와 service-role 권한.
- Create `tests/sql/motion_blind_formal30_probe.sql`: 성공/실패/rollback SQL assertion.
- Create `tests/sql/motion_blind_formal30_prerequisites.sql`: disposable DB용 tutorial/owner 최소 fixture.
- Create `scripts/run_motion_blind_formal30_probe.py`: disposable PostgreSQL에 prerequisite+migration+probe 적용.
- Create `tests/test_motion_blind_formal30_runtime_probe.py`: local-only DB guard와 runner 계약.
- Create `tests/test_motion_blind_formal30_migration.py`: migration signature, exact-30, privilege 정적 계약.
- Create `scripts/prepare_rba_blind30.py`: metadata-only 후보 정규화, deterministic selection, canonical manifest, mode `0600` write.
- Create `tests/test_prepare_rba_blind30.py`: eligibility/near-duplicate/camera-night/hash/secret exclusion 단위 테스트.
- Create `scripts/score_rba_blind30.py`: immutable raw submission 두 벌을 항목별 agreement와 segment P/R/F1로 채점.
- Create `tests/test_score_rba_blind30.py`: abstain, set, segment matching, pass/hold/fail 단위 테스트.
- Modify `specs/feature-rba-data-engine-v1.md`: 신규 GT의 `highlight_recommendation`과 legacy `activity_intensity=null` 정합화.
- Modify `experiments/rba-data-engine-blind30/TEST-SHEET.md`: live awaiting bookkeeping 허용 범위와 별도 scorer blocker 명시.
- Modify `specs/next-session.md`: 구현/배포/예약 상태와 다음 human step 기록.
- Modify `specs/README.md`: formal Blind30 상태/계획 링크 갱신.

---

### Task 1: 동결 계약과 회귀 경계 고정

**Files:**
- Modify: `specs/feature-rba-data-engine-v1.md`
- Modify: `experiments/rba-data-engine-blind30/TEST-SHEET.md`
- Test: `web/src/lib/motionBlindReview.test.ts`

**Interfaces:**
- Consumes: 현재 `GroundTruthInput`과 `motion-blind-v1`.
- Produces: 신규 구현이 지켜야 할 eligibility와 comparator 분리 계약.

- [x] **Step 1: 문서의 신규 GT 계약을 실제 구현과 맞춘다**

`feature-rba-data-engine-v1.md` §4-2를 다음 의미로 고정한다.

```text
신규 GT는 highlight_recommendation을 기록한다.
activity_intensity는 legacy read 전용이며 신규 GT에서는 null이다.
```

- [x] **Step 2: formal30 eligibility에서 live bookkeeping을 명시한다**

`TEST-SHEET.md` §3.1에 다음을 명시한다.

```text
cohort_kind='canary' slot/consensus 이력은 제외한다.
live submission 0건이면 제출 전 live slot과 awaiting consensus는 허용한다.
live agreed|conflict|owner_resolved는 제외한다.
```

- [x] **Step 3: 운영 comparator가 그대로인지 회귀 테스트를 실행한다**

Run:

```bash
cd web
npm test -- src/lib/motionBlindReview.test.ts src/lib/labelingV2.test.ts
```

Expected: PASS. `motionBlindReview.ts` diff 0, `BLIND_COMPARATOR_VERSION='motion-blind-v1'`.

- [x] **Step 4: 문서 변경을 커밋한다**

```bash
git add specs/feature-rba-data-engine-v1.md experiments/rba-data-engine-blind30/TEST-SHEET.md
git commit -m "docs: formal blind30 데이터 계약 정합화"
```

### Task 2: exact-30 원자 예약 RPC를 TDD로 추가

**Files:**
- Create: `tests/test_motion_blind_formal30_migration.py`
- Create: `migrations/2026-07-31_motion_blind_formal30.sql`

**Interfaces:**
- Consumes: `fn_motion_blind_clip_is_labelable(uuid)`, tutorial/labeler/group tables, 기존 canary tables.
- Produces:

```sql
public.fn_create_motion_blind_formal30(
  p_actor_id uuid,
  p_group_id uuid,
  p_clip_ids uuid[],
  p_reviewer_ids uuid[],
  p_manifest_sha256 text,
  p_selection_t0 timestamptz
) RETURNS uuid
```

- [ ] **Step 1: RED 정적 계약 테스트를 작성한다**

`tests/test_motion_blind_formal30_migration.py`에서 migration text에 아래 계약이 모두 있는지 검사한다.

```python
def test_formal30_migration_has_exact_atomic_contract() -> None:
    sql = MIGRATION.read_text()
    assert "fn_create_motion_blind_formal30" in sql
    assert "array_length(p_clip_ids, 1) <> 30" in sql
    assert "count(DISTINCT clip_id) <> 30" in sql
    assert "b30v1:" in sql
    assert "cohort_kind = 'canary'" in sql
    assert "GRANT EXECUTE" in sql and "TO service_role" in sql
    assert "FROM PUBLIC, anon, authenticated" in sql
```

- [ ] **Step 2: RED를 확인한다**

Run:

```bash
uv run pytest tests/test_motion_blind_formal30_migration.py -q
```

Expected: FAIL because migration is missing.

- [ ] **Step 3: 최소 forward RPC를 구현한다**

RPC는 다음 순서를 한 PL/pgSQL transaction 안에서 수행한다.

```sql
IF p_selection_t0 IS NULL OR p_selection_t0 >= clock_timestamp() THEN
  RAISE EXCEPTION 'formal30 invalid T0' USING ERRCODE = '22023';
END IF;
IF p_manifest_sha256 !~ '^[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'formal30 invalid manifest hash' USING ERRCODE = '22023';
END IF;
IF array_length(p_clip_ids, 1) <> 30
   OR (SELECT count(DISTINCT x) FROM unnest(p_clip_ids) x) <> 30 THEN
  RAISE EXCEPTION 'formal30 needs 30 distinct clips' USING ERRCODE = '22023';
END IF;
IF array_length(p_reviewer_ids, 1) <> 2
   OR p_reviewer_ids[1] = p_reviewer_ids[2] THEN
  RAISE EXCEPTION 'formal30 needs two distinct reviewers' USING ERRCODE = 'PT425';
END IF;
```

Reviewer 자격은 두 UUID 각각에 대해 `labelers`, approved `labeler_applications`,
`motion_labeling_review_group_members.ended_at IS NULL`, active
`labeling_tutorial_sets.version='tutorial-v1'`, `labeling_tutorial_progress.current_run_no`,
`completed_at IS NOT NULL`, `waived_at IS NULL`, 그리고 그 run의
`labeling_tutorial_attempts.stage='completed'` position 1..5를 재검증한다.
`p_actor_id = ANY(p_reviewer_ids)`이면 `PT425`로 거부해 owner adjudicator가 reviewer를 겸하지
못하게 한다.

Clip은 UUID 오름차순으로 `FOR UPDATE` 잠그고 다음을 전부 재검증한다.

```text
started_at < p_selection_t0
r2_key not null
fn_motion_blind_clip_is_labelable(id)
quarantined/media_deleted 아님
tutorial lesson 아님
canary slot/consensus 이력 없음
blind submission 0
legacy/motion-v3 사람 GT session 0
live terminal consensus 없음
```

검증 뒤 다음 row count를 exact assertion한다.

```text
motion_blind_review_cohorts: 1
motion_clip_review_slots: 60
motion_clip_consensus(awaiting): 30
```

`ON CONFLICT DO NOTHING`으로 부분 성공을 숨기지 않는다. 충돌은 예외로 전체 rollback한다.

- [ ] **Step 4: 실행 권한을 service_role로 한정한다**

```sql
REVOKE ALL ON FUNCTION public.fn_create_motion_blind_formal30(
  uuid, uuid, uuid[], uuid[], text, timestamptz
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fn_create_motion_blind_formal30(
  uuid, uuid, uuid[], uuid[], text, timestamptz
) TO service_role;
```

- [ ] **Step 5: GREEN을 확인한다**

Run:

```bash
uv run pytest tests/test_motion_blind_formal30_migration.py -q
git diff --check
```

Expected: PASS, whitespace errors 0.

- [ ] **Step 6: RPC 단위를 커밋한다**

```bash
git add migrations/2026-07-31_motion_blind_formal30.sql tests/test_motion_blind_formal30_migration.py
git commit -m "feat: formal blind30 원자 예약 RPC"
```

### Task 3: disposable PostgreSQL 실증

**Files:**
- Create: `tests/sql/motion_blind_formal30_probe.sql`
- Create: `tests/sql/motion_blind_formal30_prerequisites.sql`
- Create: `scripts/run_motion_blind_formal30_probe.py`
- Create: `tests/test_motion_blind_formal30_runtime_probe.py`

**Interfaces:**
- Consumes: Task 2 migration.
- Produces: `FORMAL30_PROBE_OK` marker and local-only runner.

- [ ] **Step 1: runner safety RED 테스트를 작성한다**

```python
def test_rejects_non_loopback_database_url() -> None:
    with pytest.raises(ProbeFailed, match="loopback"):
        validate_database_url("postgresql://prod.example.com/db")
```

Runner는 `run_motion_double_blind_concurrency_probe.py`의 `LocalPostgresBackend`,
`validate_database_url`, `_find_pg_tool`을 재사용하고 production hostname을 거부한다.
`motion_blind_formal30_prerequisites.sql`은 기존 base prerequisite 적용 뒤 active tutorial set,
current run, five completed attempts와 owner/reviewer 구분에 필요한 synthetic row만 추가한다.

- [ ] **Step 2: SQL probe를 작성한다**

한 transaction에서 synthetic UUID만 사용해 다음 assertion을 실행하고 마지막에 rollback한다.

```text
30 distinct eligible + qualified pair -> cohort 1 / slots 60 / consensus 30
29, 31, duplicate clip -> 22023
same reviewer, owner reviewer, inactive group, unapproved, tutorial 4/5, waiver -> PT425
unsubmitted live slot + awaiting live consensus -> 허용
기존 submission, canary slot/consensus, live terminal consensus -> 거부
두 번째 동일 예약 -> 거부, 기존 60/30 row 불변
중간 1개 부적격 -> cohort/slot/consensus 0으로 rollback
authenticated/anon execute -> denied
```

- [ ] **Step 3: RED를 확인한다**

Run:

```bash
uv run pytest tests/test_motion_blind_formal30_runtime_probe.py -q
```

Expected: FAIL until runner and SQL fixture exist.

- [ ] **Step 4: runner를 구현하고 local PostgreSQL에서 실증한다**

Run:

```bash
uv run python scripts/run_motion_blind_formal30_probe.py --backend local-postgres
```

Expected:

```text
FORMAL30_PROBE_OK
```

- [ ] **Step 5: GREEN을 확인하고 커밋한다**

```bash
uv run pytest tests/test_motion_blind_formal30_runtime_probe.py tests/test_motion_blind_formal30_migration.py -q
git add tests/sql/motion_blind_formal30_probe.sql tests/sql/motion_blind_formal30_prerequisites.sql scripts/run_motion_blind_formal30_probe.py tests/test_motion_blind_formal30_runtime_probe.py
git commit -m "test: formal blind30 DB 원자성 실증"
```

### Task 4: metadata-only 선택기와 manifest 생성기

**Files:**
- Create: `scripts/prepare_rba_blind30.py`
- Create: `tests/test_prepare_rba_blind30.py`

**Interfaces:**
- Consumes:

```python
@dataclass(frozen=True)
class Candidate:
    clip_id: str
    camera_id: str
    started_at: datetime
    duration_sec: float
    r2_ready: bool
    labelable: bool
    excluded: bool
    tutorial: bool
    canary_history: bool
    submission_count: int
    live_terminal_consensus: bool
    legacy_gt_count: int
```

- Produces:

```python
def select_formal30(candidates: Sequence[Candidate], *, t0: datetime) -> list[Candidate]
def build_manifest(selected: Sequence[Candidate], *, t0: datetime, reviewer_fingerprints: Sequence[str]) -> dict[str, object]
def write_manifest(path: Path, manifest: Mapping[str, object]) -> str
```

- [ ] **Step 1: RED 선택 테스트를 작성한다**

테스트는 input order를 뒤집어도 같은 30개/순서/hash가 나오고 다음을 검증한다.

```text
5분 bucket 하나만 유지
stratum 최대 5
camera-night 최소 6
camera 최소 2
30 미만이면 INSUFFICIENT_ELIGIBLE_POOL
live awaiting bookkeeping은 포함
submission/canary/live terminal/legacy GT는 제외
```

- [ ] **Step 2: RED manifest 보안 테스트를 작성한다**

```python
def test_manifest_excludes_answers_and_credentials(tmp_path: Path) -> None:
    manifest = build_manifest(...)
    raw = json.dumps(manifest, sort_keys=True)
    for forbidden in ("email", "r2_key", "signed_url", "prediction", "ground_truth", "credential"):
        assert forbidden not in raw
    out = tmp_path / "manifest.json"
    digest = write_manifest(out, manifest)
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert digest == hashlib.sha256(out.read_bytes()).hexdigest()
```

- [ ] **Step 3: RED를 확인한다**

```bash
uv run pytest tests/test_prepare_rba_blind30.py -q
```

Expected: FAIL because module is missing.

- [ ] **Step 4: deterministic selector를 최소 구현한다**

Hash는 canonical UTF-8 string에 SHA-256을 사용한다.

```python
def stable_hash(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()
```

Activity day:

```python
kst = ZoneInfo("Asia/Seoul")
activity_day = (started_at.astimezone(kst) - timedelta(hours=7)).date()
bucket = int(started_at.timestamp()) // 300
```

Stratum order와 내부 order는 TEST-SHEET §3.2 그대로 적용하고 round-robin으로 30개를 뽑는다.

- [ ] **Step 5: GREEN과 전체 순수 테스트를 확인한다**

```bash
uv run pytest tests/test_prepare_rba_blind30.py -q
git diff --check
```

Expected: PASS.

- [ ] **Step 6: 선택기를 커밋한다**

```bash
git add scripts/prepare_rba_blind30.py tests/test_prepare_rba_blind30.py
git commit -m "feat: formal blind30 표본과 manifest 동결"
```

### Task 5: raw submission 기반 별도 채점기

**Files:**
- Create: `scripts/score_rba_blind30.py`
- Create: `tests/test_score_rba_blind30.py`

**Interfaces:**
- Consumes: reviewer별 immutable `decision`, `reason_code`, `initial_gt`, `submitted_at`; cohort metadata.
- Produces:

```python
def score_blind30(
    reviewer_a: Sequence[Mapping[str, object]],
    reviewer_b: Sequence[Mapping[str, object]],
) -> dict[str, object]

def classify_result(metrics: Mapping[str, object]) -> Literal["PASS", "HOLD", "FAIL"]
```

- [ ] **Step 1: RED 항목별 agreement 테스트를 작성한다**

```python
def test_agreement_is_scored_from_raw_submissions_not_consensus() -> None:
    a = submission(decision="hold", confidence="uncertain")
    b = submission(decision="hold", confidence="certain")
    result = score_blind30([a], [b])
    assert result["automatic_agreement"] == 0
    assert result["owner_adjudication"] == 1
```

`uncertain`/`unjudgeable`은 해당 dimension 분모에서 제외하고 둘 다 abstain이어도 agreement로 세지 않는다.

- [ ] **Step 2: RED segment maximum matching 테스트를 작성한다**

같은 action끼리 bipartite edge를 만들고 아래 조건이면 match 가능하다.

```python
iou >= 0.50 or (
    abs(a["start_sec"] - b["start_sec"]) <= 2.0
    and abs(a["end_sec"] - b["end_sec"]) <= 2.0
)
```

최대 cardinality matching 결과로 TP, unmatched A=FP, unmatched B=FN을 계산한다. 입력 순서와 무관해야 한다.

- [ ] **Step 3: RED pass/hold/fail 테스트를 작성한다**

정확히 30 clip, reviewer별 30/30, duplicate/missing 0을 요구한다. TEST-SHEET §6 threshold를 그대로 fixtures에 적용한다.

- [ ] **Step 4: RED를 확인한다**

```bash
uv run pytest tests/test_score_rba_blind30.py -q
```

Expected: FAIL because module is missing.

- [ ] **Step 5: 최소 scorer를 구현한다**

Scorer는 DB나 network를 호출하지 않는 pure module로 만들고 JSON input/output CLI만 제공한다.

```bash
uv run python scripts/score_rba_blind30.py \
  --submissions /absolute/private/blind30-submissions.json \
  --manifest /absolute/private/rba-blind30-v1-manifest.json \
  --out /absolute/private/rba-blind30-v1-report.json
```

출력에는 reviewer UUID/email, note 원문, R2 key, signed URL을 넣지 않는다.

- [ ] **Step 6: GREEN과 determinism을 확인한다**

```bash
uv run pytest tests/test_score_rba_blind30.py -q
git diff --check
```

Expected: PASS, 같은 input의 canonical report SHA-256 동일.

- [ ] **Step 7: scorer를 커밋한다**

```bash
git add scripts/score_rba_blind30.py tests/test_score_rba_blind30.py
git commit -m "feat: formal blind30 독립 채점기"
```

### Task 6: 통합 검증, review, migration 배포

**Files:**
- Modify: `specs/next-session.md`
- Modify: `specs/README.md`
- Create: `docs/handoff-prompts/2026-07-31-rba-data-engine-formal-blind30-report.md`

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: production에 RPC가 존재하지만 cohort row는 0인 `FORMAL30_INFRA_DEPLOYED_NO_RESERVATION`.

- [ ] **Step 1: 전체 관련 테스트를 실행한다**

```bash
uv run pytest -q
cd web
npm test
npm run audit:labeling-role-ui
npx tsc --noEmit
```

Expected: Python/Web/TypeScript/audit 모두 PASS.

- [ ] **Step 2: 독립 code review를 실행한다**

검토 범위:

```text
기존 comparator/원장 diff 0
exact 30 / 60 slots / 30 consensus 원자성
reviewer 자격과 tutorial 5/5
live awaiting 허용, terminal/history 제외
service_role only
manifest mode0600/secret exclusion
scorer raw submission 기반/abstain/segment matching
production reservation 0
```

- [ ] **Step 3: preview DB에 migration만 적용한다**

`fn_create_motion_blind_formal30` signature와 privilege를 확인하고 synthetic transaction은 rollback한다. 실제 cohort/slot/submission은 만들지 않는다.

- [ ] **Step 4: production에 forward migration만 적용한다**

배포 직후 read-only로 다음을 확인한다.

```text
function exists
authenticated/anon execute denied
service_role execute allowed
label LIKE 'b30v1:%' cohort count = 0
formal30 slot/submission/consensus count = 0
기존 live/canary aggregate와 hashes 불변
```

- [ ] **Step 5: SOT와 보고서를 갱신한다**

상태는 reviewer pair가 준비되기 전까지 다음으로 유지한다.

```text
FORMAL30_INFRA_DEPLOYED_NO_RESERVATION
BLIND30_BLOCKED_REVIEWER_PAIR
```

- [ ] **Step 6: 최종 검증 결과를 커밋하고 non-force push한다**

```bash
git add specs/next-session.md specs/README.md docs/handoff-prompts/2026-07-31-rba-data-engine-formal-blind30-report.md
git commit -m "docs: formal blind30 인프라 검증 기록"
git push --set-upstream origin codex/rba-data-engine-formal-blind30
```

main 통합은 `origin/main`이 계획 기준의 후손일 때만 non-force로 수행한다. primary checkout의 기존 dirty 파일은 건드리지 않는다.

### Task 7: reviewer pair 준비 뒤에만 표본 동결과 예약

**Files:**
- Runtime artifact only: `/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-blind30-v1-manifest.json`
- Modify after evidence: `specs/next-session.md`
- Append report: `docs/handoff-prompts/2026-07-31-rba-data-engine-formal-blind30-report.md`

**Interfaces:**
- Consumes: same active group의 qualified non-owner 2명, deployed RPC, metadata-only candidates.
- Produces: exactly one cohort URL and `BLIND30_PREFROZEN_READY`.

- [ ] **Step 1: reviewer pair를 read-only 재검증한다**

둘 다 approved, active group member, non-owner, tutorial current run 5/5, waiver 0이 아니면 중단한다. 기존 reviewer를 임시 group 이동하지 않는다.

- [ ] **Step 2: production metadata만 읽어 후보를 선택한다**

answer/GT/AI/consensus result를 query projection에 넣지 않는다. `prepare_rba_blind30.py`로 exact 30과 canonical manifest를 만든다.

- [ ] **Step 3: manifest 보안과 hash를 확인한다**

```bash
stat -f '%Lp %N' "/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-blind30-v1-manifest.json"
shasum -a 256 "/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-blind30-v1-manifest.json"
```

Expected: mode `600`, hash가 cohort label의 suffix와 동일.

- [ ] **Step 4: RPC를 한 번만 호출한다**

manifest의 ordered clip IDs, reviewer IDs, `T0`, manifest SHA-256을 전달한다. 실패하면 임의 INSERT/두 canary 합치기로 우회하지 않는다.

- [ ] **Step 5: exact row count와 blind 노출을 검증한다**

```text
cohort 1 open
reviewer A slots 30
reviewer B slots 30
awaiting consensus 30
submission 0
prediction/reference/peer/consensus reviewer 노출 0
```

- [ ] **Step 6: reviewer에게 URL 하나만 전달하고 human 단계에서 멈춘다**

```text
https://label.tera-ai.uk/labeling/blind/canary/<cohort_id>
```

agent는 제출하지 않는다. 두 reviewer 모두 30/30 완료할 때까지 owner adjudication을 시작하지 않는다.

### Task 8: human 제출 완료 뒤 채점과 판정

**Files:**
- Private runtime input/output only; Git에는 aggregate report만 기록.
- Modify: `specs/next-session.md`
- Append: `docs/handoff-prompts/2026-07-31-rba-data-engine-formal-blind30-report.md`

**Interfaces:**
- Consumes: immutable raw submissions 60건, manifest.
- Produces: `BLIND30_PASS`, `BLIND30_HOLD`, or `BLIND30_FAIL`.

- [ ] **Step 1: 제출 완전성을 read-only 확인한다**

두 reviewer 각 30, distinct `(slot_id)` 60, duplicate/missing 0이 아니면 채점하지 않고 FAIL/HOLD 계약대로 보고한다.

- [ ] **Step 2: raw 제출만 private JSON으로 export한다**

consensus final GT를 scorer input으로 사용하지 않는다. UUID/email/note 원문은 report에서 제거한다.

- [ ] **Step 3: 별도 scorer를 실행한다**

```bash
uv run python scripts/score_rba_blind30.py \
  --submissions /absolute/private/blind30-submissions.json \
  --manifest "/Users/baek-end/Library/Application Support/petcam/rba-data-engine/audit/rba-blind30-v1-manifest.json" \
  --out /absolute/private/rba-blind30-v1-report.json
```

- [ ] **Step 4: conflict만 owner adjudication한다**

운영 UI의 conflict workflow를 그대로 사용한다. raw submission과 scorer aggregate를 보존하고 기존 최초 제출을 수정하지 않는다.

- [ ] **Step 5: 동결 threshold로 최종 판정한다**

결과를 본 뒤 threshold, sample, segment tolerance를 변경하지 않는다. aggregate metrics와 artifact SHA만 tracked report에 기록한다.

---

## Self-Review

- Spec coverage: TEST-SHEET §2 reviewer, §3 selection/manifest, §4 reservation, §5 comparator/scorer, §6 threshold, §7 blockers가 Tasks 1-8에 모두 매핑된다.
- Placeholder scan: `TBD`, `TODO`, “적절히 처리”, 구현 없는 “테스트 추가” 문구가 없다.
- Type consistency: RPC signature는 Task 2/7에서 동일하고, selector/scorer 함수명은 Task 4/5/7/8에서 동일하다.
- Scope separation: Task 6은 migration 배포까지만 허용하고 실제 reservation은 Task 7 reviewer pair gate 뒤로 분리했다.
- Existing data safety: 모든 mutation은 신규 cohort/slot/consensus insert뿐이며 기존 row rewrite/delete 단계가 없다.
