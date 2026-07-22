# Local VLM Evidence B1R2 Media Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code change uses superpowers:test-driven-development.

**Goal:** R2에 실제로 남아 있는 역사 motion clip을 정본화하고, media-available clip만 Python Evidence canary/backfill한 뒤 selector v2의 6 strata×30 가용성을 다시 판정한다.

**Architecture:** `petcam-lab`이 R2 inventory와 DB를 read-only로 join해 tracked aggregate와 gitignored per-clip manifest를 만든다. `petcam-nightly-reporter`는 그 manifest만 enqueue하고 R2 404/403/일시 오류를 구분한다. Mac mini의 기존 Universal Evidence worker를 그대로 사용하며 inventory integrity, canary 30/30, recoverable coverage closure를 순차 gate로 둔다.

**Tech Stack:** Python 3.12, uv, pytest, boto3/botocore, Supabase/PostgREST, PostgreSQL forward migration, existing Mac mini LaunchAgent, JSONL, SHA-256.

## Global Constraints

- Design SOT: `docs/superpowers/specs/2026-07-22-local-vlm-evidence-b1r2-media-availability-design.md`.
- Fixed cutoff: `2026-07-22T02:45:33+00:00`.
- Evidence identity: `python-evidence-raw-v1` + `croi-temporal-v1`.
- Selector identity: `local-vlm-evidence-selector-v2`.
- Runtime host: `baeg-endeuui-Macmini.local`; expected-host 우회와 laptop worker 실행 금지.
- Existing successful run은 R2 object가 없어도 `evidence_succeeded`로 유지한다.
- `source_expired`는 success로 위장하거나 aggregate에서 숨기지 않는다.
- Study contract: 6 strata×30, dev120/holdout60, global clip/30-minute episode overlap 0.
- Model download/inference, VLM/GT/behavior/activity/app write, B2 migration/API/UI는 금지한다.
- R2 key/signed URL/secret/per-clip availability는 Git·Slack·tracked report에 노출하지 않는다.
- Private manifests는 `storage/local-vlm-evidence-analyst/b1r2/` 아래에만 둔다.
- B1/B1R artifact와 report는 수정하지 않는다. B1R2 namespace 신규 파일만 사용한다.
- 다른 세션 untracked 파일을 add/delete/commit하지 않는다.

---

### Task 0: Handoff·runtime·baseline fail-closed preflight

**Files:**
- Read: `AGENTS.md`
- Read: `docs/superpowers/specs/2026-07-22-local-vlm-evidence-b1r2-media-availability-design.md`
- Read: `docs/superpowers/plans/2026-07-22-local-vlm-evidence-b1r2-media-availability.md`
- Create: `reports/local-vlm-evidence-b1r2/RUNTIME-SNAPSHOT.md`

**Interfaces:**
- Consumes: handoff front matter, SSH alias `home-mac`, fixed cutoff.
- Produces: `B1R2_RUNTIME_OK` or a blocking verdict before any R2/DB write.

- [ ] **Step 1: Handoff와 lab baseline을 검증한다**

```bash
cd /Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/.codex/handoffs/2026-07-22-local-vlm-evidence-b1r2-media-availability-handoff.md
git status --short --branch
uv run pytest -q
git diff --check
```

Expected: `HANDOFF_OK task=local-vlm-evidence-b1r2-media-availability`, clean, 736개 이상 PASS. 실패하면 구현하지 않는다.

- [ ] **Step 2: Mac mini runtime을 read-only로 확인한다**

```bash
ssh home-mac 'set -eu
test "$(hostname)" = "baeg-endeuui-Macmini.local"
for r in /Users/baek-end/petcam-lab /Users/baek-end/petcam-nightly-reporter /Users/baek-end/myPythonProjects/gecko-vision-gate; do
  git -C "$r" status --short --branch
  git -C "$r" rev-parse HEAD
  git -C "$r" rev-parse origin/main
done
launchctl print gui/$(id -u)/com.petcam.python-evidence-worker | sed -n "1,180p"
plutil -p "$HOME/Library/LaunchAgents/com.petcam.python-evidence-worker.plist"
'
```

Expected: service loaded/exit 0, WorkingDirectory `/Users/baek-end/petcam-nightly-reporter`, feature flag 1, expected host exact. Secret 값은 출력하지 않는다.

- [ ] **Step 3: Snapshot을 작성하고 commit한다**

Hostname, 세 repo HEAD, service label, working directory, fixed cutoff, evidence/selector identity를 기록한다. Drift/access failure면 정지한다.

```bash
git add reports/local-vlm-evidence-b1r2/RUNTIME-SNAPSHOT.md
git commit -m "docs: B1R2 runtime 정본 기록"
```

---

### Task 1: R2 inventory + media coverage partition

**Files:**
- Create: `scripts/audit_local_vlm_evidence_b1r2_media.py`
- Create: `tests/test_audit_local_vlm_evidence_b1r2_media.py`
- Runtime tracked: `experiments/local-vlm-evidence-analyst/b1r2-media-availability.json`
- Runtime tracked: `reports/local-vlm-evidence-b1r2/MEDIA-AVAILABILITY.md`
- Runtime private: `storage/local-vlm-evidence-analyst/b1r2/media-availability.jsonl`

**Interfaces:**
- Produces: `MediaCoverageRow`, `MediaCoverageSnapshot`, `partition_media_coverage`, `availability_sha256`.
- Consumes: fixed cutoff, DB motion/job/run rows, R2 `list_objects_v2` keys.

- [ ] **Step 1: RED tests를 작성한다**

```python
def test_existing_run_wins_when_object_is_missing():
    snap, rows = partition_media_coverage(
        [clip("a", key="clips/a.mp4")], runs=[ok_run("a")], jobs=[], available_keys=set()
    )
    assert rows[0].status == "evidence_succeeded"
    assert (snap.evidence_succeeded, snap.source_expired) == (1, 0)

def test_missing_object_without_run_is_source_expired():
    snap, rows = partition_media_coverage(
        [clip("a", key="clips/a.mp4")], runs=[], jobs=[], available_keys=set()
    )
    assert rows[0].status == "source_expired"

def test_partition_is_exhaustive_and_exclusive():
    snap, rows = partition_media_coverage(FIVE_STATE_FIXTURE, RUNS, JOBS, AVAILABLE)
    assert len(rows) == snap.study_total == (
        snap.evidence_succeeded + snap.media_available_open
        + snap.media_available_silent + snap.media_available_terminal
        + snap.source_expired
    )
    assert len({row.clip_id for row in rows}) == len(rows)

def test_inventory_paginates_beyond_1000_and_discards_partial_error():
    assert len(list_available_mp4_keys(FakeR2(pages=[objects(1000), objects(7)]), "b", "clips/")) == 1007
    with pytest.raises(MediaAuditError, match="inventory_failed"):
        list_available_mp4_keys(FakeR2(pages=[objects(1000), RuntimeError("boom")]), "b", "clips/")
```

- [ ] **Step 2: RED 후 최소 core를 구현한다**

```bash
uv run pytest -q tests/test_audit_local_vlm_evidence_b1r2_media.py
```

```python
@dataclass(frozen=True, slots=True)
class MediaCoverageRow:
    clip_id: str
    camera_id: str
    started_at: str
    source_date: str
    status: str

@dataclass(frozen=True, slots=True)
class MediaCoverageSnapshot:
    cutoff_started_at: str
    study_total: int
    evidence_succeeded: int
    media_available_open: int
    media_available_silent: int
    media_available_terminal: int
    source_expired: int
    camera_date_status_counts: Mapping[str, int]
    availability_sha256: str
```

Partition priority는 design §4와 같아야 한다. `list_available_mp4_keys`는 paginator 전량을 읽고 `.mp4`이며 size>0인 key만 메모리 set에 넣는다. 중간 오류면 일부 결과를 반환하지 않는다.

- [ ] **Step 3: Artifact 경계와 SHA를 구현한다**

Tracked aggregate에는 상태별 수량/camera-date 분포/SHA만 기록한다. Private JSONL에는 `clip_id,camera_id,started_at,source_date,status`만 기록한다.

```python
def availability_sha256(rows):
    payload = "\n".join(
        f"{r.clip_id}\t{r.status}" for r in sorted(rows, key=lambda x: x.clip_id)
    )
    return hashlib.sha256(payload.encode()).hexdigest()
```

- [ ] **Step 4: GREEN·전체 회귀·commit을 실행한다**

```bash
uv run pytest -q tests/test_audit_local_vlm_evidence_b1r2_media.py
uv run pytest -q
git diff --check
git add scripts/audit_local_vlm_evidence_b1r2_media.py tests/test_audit_local_vlm_evidence_b1r2_media.py
git commit -m "feat: B1R2 R2 media availability 감사 추가"
```

---

### Task 2: Independent recompute + production read-only inventory

**Files:**
- Create: `scripts/recompute_local_vlm_evidence_b1r2_media.py`
- Create: `tests/test_recompute_local_vlm_evidence_b1r2_media.py`
- Produce Task 1 runtime artifacts.

**Interfaces:**
- Consumes: private JSONL and aggregate JSON.
- Produces: exact `MATCH availability_sha256=...` or nonzero mismatch.

- [ ] **Step 1: Independent RED tests를 작성한다**

```python
def test_recompute_matches_counts_and_sha(tmp_path):
    aggregate, manifest = write_fixture(tmp_path, FIVE_STATE_ROWS)
    assert recompute(aggregate, manifest).matched is True

def test_recompute_rejects_changed_status(tmp_path):
    aggregate, manifest = write_fixture(tmp_path, FIVE_STATE_ROWS)
    mutate_one_status(manifest)
    assert recompute(aggregate, manifest).matched is False

def test_recompute_does_not_import_primary_module():
    source = Path("scripts/recompute_local_vlm_evidence_b1r2_media.py").read_text()
    assert "audit_local_vlm_evidence_b1r2_media" not in source
```

- [ ] **Step 2: stdlib-only 재계산기를 구현하고 GREEN을 확인한다**

```bash
uv run pytest -q tests/test_recompute_local_vlm_evidence_b1r2_media.py
uv run pytest -q
```

- [ ] **Step 3: Production snapshot을 SELECT/R2-list read-only로 실행한다**

```bash
mkdir -p storage/local-vlm-evidence-analyst/b1r2 reports/local-vlm-evidence-b1r2
uv run python scripts/audit_local_vlm_evidence_b1r2_media.py \
  --cutoff-started-at 2026-07-22T02:45:33+00:00 \
  --aggregate-out experiments/local-vlm-evidence-analyst/b1r2-media-availability.json \
  --private-manifest-out storage/local-vlm-evidence-analyst/b1r2/media-availability.jsonl \
  --report-out reports/local-vlm-evidence-b1r2/MEDIA-AVAILABILITY.md
uv run python scripts/recompute_local_vlm_evidence_b1r2_media.py \
  --aggregate experiments/local-vlm-evidence-analyst/b1r2-media-availability.json \
  --private-manifest storage/local-vlm-evidence-analyst/b1r2/media-availability.jsonl
```

Expected: `B1R2_MEDIA_AUDIT_VERIFIED` + `MATCH`. Partial listing/SHA/partition mismatch면 즉시 정지한다.

- [ ] **Step 4: Bounded HEAD 표본과 artifacts를 검증·commit한다**

각 camera/date에서 available/expired 최대 6개를 결정론적으로 검증한다. Available은 HEAD success, expired는 404여야 한다. 403/5xx/timeout은 audit failure로 처리한다. Key/URL은 출력하지 않는다.

```bash
git add scripts/recompute_local_vlm_evidence_b1r2_media.py \
  tests/test_recompute_local_vlm_evidence_b1r2_media.py \
  experiments/local-vlm-evidence-analyst/b1r2-media-availability.json \
  reports/local-vlm-evidence-b1r2/MEDIA-AVAILABILITY.md
git commit -m "docs: B1R2 media availability 실측 기록"
```

---

### Task 3: R2 failure typing + forward migration

**Files (`petcam-nightly-reporter`, disposable worktree from `origin/main`):**
- Modify: `reporter/r2.py`
- Modify: `reporter/python_evidence_worker.py`
- Modify: `reporter/python_evidence_store.py`
- Modify: `tests/test_python_evidence_worker.py`
- Create: `tests/test_r2_failure_classification.py`

**Files (`petcam-lab`):**
- Create: `migrations/2026-07-22_python_evidence_source_media_failure_codes.sql`
- Create: `tests/test_python_evidence_source_media_failure_codes_migration.py`

**Interfaces:**
- Produces exceptions `R2SourceMissing`, `R2AccessDenied` and codes `source_media_missing`, `r2_access_denied`.
- Preserves transient/unknown errors as retryable `r2_download_failed`.

- [ ] **Step 1: Nightly disposable worktree를 만든다**

```bash
git -C /Users/baek/petcam-nightly-reporter fetch origin
git -C /Users/baek/petcam-nightly-reporter worktree add /tmp/nightly-b1r2 origin/main
git -C /tmp/nightly-b1r2 switch -c feat/local-vlm-evidence-b1r2-media
```

- [ ] **Step 2: RED tests로 error mapping을 고정한다**

```python
@pytest.mark.parametrize("code", ["404", "NoSuchKey", "NotFound"])
def test_missing_object_is_terminal(code):
    assert run_failure(raising_client_error(code)) == ("source_media_missing", False)

@pytest.mark.parametrize("code", ["403", "AccessDenied"])
def test_access_denied_is_terminal(code):
    assert run_failure(raising_client_error(code)) == ("r2_access_denied", False)

@pytest.mark.parametrize("code", ["429", "500", "503", "RequestTimeout"])
def test_transient_error_is_retryable(code):
    assert run_failure(raising_client_error(code)) == ("r2_download_failed", True)
```

- [ ] **Step 3: Typed exception과 worker mapping을 구현한다**

```python
class R2SourceMissing(RuntimeError):
    pass

class R2AccessDenied(RuntimeError):
    pass

def _error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))
```

Typed exceptions에는 raw message/key를 담지 않는다. Worker는 specific exception을 generic download exception보다 먼저 catch한다.

- [ ] **Step 4: Forward migration RED→GREEN을 구현한다**

기존 migration은 수정하지 않는다. 새 migration은 `python_evidence_jobs_failure_code_check`를 같은 이름으로 교체하고 기존 code에 신규 2개만 추가한다.

```sql
alter table public.python_evidence_jobs
  drop constraint if exists python_evidence_jobs_failure_code_check;
alter table public.python_evidence_jobs
  add constraint python_evidence_jobs_failure_code_check
  check (failure_code is null or failure_code in (
    'r2_download_failed','source_media_missing','r2_access_denied',
    'decode_no_frames','decode_insufficient_frames','invalid_metadata',
    'detector_failed','temporal_compute_failed','db_transient','db_error','internal_error'
  ));
```

Test는 기존/신규 허용, 임의 code 거부, RLS/grant 불변, 기존 migration byte 불변을 확인한다.

- [ ] **Step 5: 양쪽 전체 회귀와 task commit/push를 실행한다**

```bash
cd /tmp/nightly-b1r2
uv run pytest -q tests/test_r2_failure_classification.py tests/test_python_evidence_worker.py
uv run pytest -q
python -m compileall -q reporter scripts
git diff --check
git add reporter/r2.py reporter/python_evidence_worker.py reporter/python_evidence_store.py tests/test_python_evidence_worker.py tests/test_r2_failure_classification.py
git commit -m "fix: R2 원본 소실과 일시 오류 분리"
git push -u origin feat/local-vlm-evidence-b1r2-media

cd /Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt
uv run pytest -q tests/test_python_evidence_source_media_failure_codes_migration.py
uv run pytest -q
git add migrations/2026-07-22_python_evidence_source_media_failure_codes.sql tests/test_python_evidence_source_media_failure_codes_migration.py
git commit -m "feat: Python Evidence 원본 소실 실패코드 추가"
```

---

### Task 4: Manifest-bound canary/history enqueuer

**Files (`petcam-nightly-reporter`):**
- Modify: `scripts/enqueue_python_evidence_backfill.py`
- Modify: `tests/test_enqueue_python_evidence_backfill.py`

**Files (`petcam-lab`):**
- Modify: `scripts/audit_local_vlm_evidence_b1r2_media.py`
- Modify: `tests/test_audit_local_vlm_evidence_b1r2_media.py`
- Runtime private: `storage/local-vlm-evidence-analyst/b1r2/canary.jsonl`

**Interfaces:**
- Audit produces deterministic camera/date round-robin canary 30.
- Enqueuer consumes private JSONL + exact SHA, and only `media_available_silent` IDs.

- [ ] **Step 1: RED tests를 작성한다**

```python
def test_canary_is_deterministic_and_distributed():
    a = select_canary(shuffled(POOL, 1), limit=30)
    b = select_canary(shuffled(POOL, 2), limit=30)
    assert [x.clip_id for x in a] == [x.clip_id for x in b]
    assert len({x.clip_id for x in a}) == 30
    assert len({x.camera_id for x in a}) >= 2
    assert len({x.source_date for x in a}) >= 3

def test_enqueuer_rejects_wrong_sha_and_non_silent_rows():
    with pytest.raises(ValueError, match="manifest_sha_mismatch"):
        enqueue_from_manifest(sb, path, expected_sha="0" * 64, limit=30, dry_run=True)
    stats = enqueue_from_manifest(sb, mixed_manifest, expected_sha=SHA, limit=30, dry_run=False)
    assert set(sb.inserted_clip_ids) == SILENT_IDS
```

- [ ] **Step 2: Selector와 CLI contract를 구현한다**

Canary는 `(camera_id,source_date)` bucket round-robin, bucket 내부 `(started_at,clip_id)` 오름차순이다. Enqueuer CLI:

```text
--availability-manifest <absolute-jsonl>
--expected-manifest-sha <64-hex>
--required-status media_available_silent
--limit 1..500
--dry-run
```

- [ ] **Step 3: 양쪽 tests·commit·push를 실행한다**

```bash
cd /tmp/nightly-b1r2
uv run pytest -q tests/test_enqueue_python_evidence_backfill.py
uv run pytest -q
git add scripts/enqueue_python_evidence_backfill.py tests/test_enqueue_python_evidence_backfill.py
git commit -m "feat: R2 가용 manifest 기반 history enqueue"
git push

cd /Users/baek/petcam-lab/.worktrees/local-vlm-evidence-web-gt
uv run pytest -q tests/test_audit_local_vlm_evidence_b1r2_media.py
uv run pytest -q
git add scripts/audit_local_vlm_evidence_b1r2_media.py tests/test_audit_local_vlm_evidence_b1r2_media.py
git commit -m "feat: B1R2 분산 canary manifest 생성"
```

---

### Task 5: Cross-repo review, FF integration, migration apply, Mac mini deploy

**Files:** Task 3~4의 변경만.

**Interfaces:**
- Produces: production main SHA 2개, applied forward migration, Mac mini code parity.

- [ ] **Step 1: 금지동작과 전체 tests를 감사한다**

```bash
git diff --stat 858e830..HEAD
git -C /tmp/nightly-b1r2 diff --stat origin/main...HEAD
uv run pytest -q
git -C /tmp/nightly-b1r2 diff --check
```

신규 R2/DB delete·VLM/GT/activity write, secret/raw key 출력이 있으면 정지한다.

- [ ] **Step 2: 두 repo main을 disposable worktree에서 FF-only 통합한다**

Non-FF면 정지하고 rebase/force/reset하지 않는다. Push 후 local main과 origin/main SHA를 보고한다.

- [ ] **Step 3: Migration apply + rollback probe를 실행한다**

Probe transaction에서 기존 code와 신규 2개 허용, 임의 code 거부를 확인한 뒤 rollback한다. Existing job count/status/failure distribution은 apply 전후 동일해야 한다. Advisor 신규 critical 0을 확인한다.

- [ ] **Step 4: Mac mini FF pull과 focused tests를 실행한다**

```bash
ssh home-mac 'set -eu
git -C /Users/baek-end/petcam-nightly-reporter fetch origin
git -C /Users/baek-end/petcam-nightly-reporter merge --ff-only origin/main
cd /Users/baek-end/petcam-nightly-reporter
uv run pytest -q tests/test_r2_failure_classification.py tests/test_python_evidence_worker.py tests/test_enqueue_python_evidence_backfill.py
git status --short --branch
'
```

Expected: PASS, clean, HEAD==origin/main. LaunchAgent plist/schedule/env는 수정하지 않는다.

---

### Task 6: Media-available canary 30/30

**Files:**
- Runtime private manifests only.
- Create tracked: `reports/local-vlm-evidence-b1r2/CANARY.md`.

**Interfaces:**
- Produces `B1R2_CANARY_VERIFIED` or `B1R2_CANARY_REJECTED`.

- [ ] **Step 1: Inventory를 재생성하고 canary 30개 HEAD를 확인한다**

같은 cutoff로 Task 2를 재실행한다. Aggregate/private pair가 MATCH해야 하며 canary 30개는 bounded HEAD 전부 present여야 한다.

- [ ] **Step 2: Private manifest를 Mac mini `storage/`로 복사하고 SHA를 대조한다**

Git add 금지. Laptop/Mac mini SHA-256이 일치해야 한다.

- [ ] **Step 3: Dry-run 후 30건만 enqueue한다**

```bash
ssh home-mac 'cd /Users/baek-end/petcam-nightly-reporter && \
  uv run python scripts/enqueue_python_evidence_backfill.py \
  --availability-manifest /Users/baek-end/petcam-lab/storage/local-vlm-evidence-analyst/b1r2/canary.jsonl \
  --expected-manifest-sha "$B1R2_MANIFEST_SHA" --required-status media_available_silent \
  --limit 30 --dry-run'
```

Expected `selected=30 enqueued=0`. `--dry-run`만 제거해 enqueue하고 다른 clip ID 생성 0을 확인한다.

- [ ] **Step 4: Existing worker로 canary를 처리하고 판정한다**

실제 plist env로 kickstart한다. 성공/reused=30, source missing/retryable/access denied=0, temp 0, service exit 0, live lag p95≤15분, runtime drift 0이어야 한다. 하나라도 실패하면 `B1R2_CANARY_REJECTED`로 Task 7 bulk를 금지한다.

- [ ] **Step 5: Canary report를 commit한다**

```bash
git add reports/local-vlm-evidence-b1r2/CANARY.md
git commit -m "docs: B1R2 media-available canary 결과 기록"
```

---

### Task 7: Bounded backfill, closure, selector v2, final report

**Files:**
- Produce: `experiments/local-vlm-evidence-analyst/b1r2-media-availability-final.json`
- Produce: `experiments/local-vlm-evidence-analyst/b1r2-candidate-availability.json`
- Produce: `reports/local-vlm-evidence-b1r2/COVERAGE-FINAL.md`
- Create: `docs/handoff-prompts/2026-07-22-local-vlm-evidence-b1r2-media-availability-report.md`
- Modify additively: `specs/next-session.md`
- Modify additively: `.claude/donts-audit.md`

**Interfaces:**
- Produces final B1R2 verdict and Stop Point report.

- [ ] **Step 1: Open historical queue cap 500으로 manifest를 drain한다**

한 호출은 최대 `500-current_open_historical`만 enqueue한다. Open이 500이면 enqueue 0. 자연 worker cycle마다 live lag, failures, temp, HEAD/service를 확인한다. 새 404는 `source_media_missing` terminal로 분리하고 inventory를 자동 재생성하지 않는다.

- [ ] **Step 2: Recoverable closure를 독립 재계산한다**

```text
media_available_open = 0
media_available_silent = 0
private_manifest_missing = 0
recompute = MATCH
```

- [ ] **Step 3: 같은 cutoff로 selector v2를 재실행한다**

```bash
PYTHONPATH=. uv run python scripts/probe_local_vlm_evidence_candidates.py \
  --selector-version local-vlm-evidence-selector-v2 \
  --cutoff-started-at 2026-07-22T02:45:33+00:00 \
  --aggregate-out experiments/local-vlm-evidence-analyst/b1r2-candidate-availability.json \
  --pool-out storage/local-vlm-evidence-analyst/b1r2/candidate-pool.json \
  --report-out reports/local-vlm-evidence-b1r2/CANDIDATE-AVAILABILITY.md
PYTHONPATH=. uv run python scripts/recompute_local_vlm_evidence_b1r.py \
  --aggregate experiments/local-vlm-evidence-analyst/b1r2-candidate-availability.json \
  --pool storage/local-vlm-evidence-analyst/b1r2/candidate-pool.json
```

- [ ] **Step 4: Verdict와 final report를 작성한다**

우선순위: inventory 불일치 → runtime drift → canary rejected → recoverable coverage open → closure 후 6×30 미달(`B1R2_BLOCKED_SEMANTIC_DATA`) → 전부 통과(`B1R2_DATA_AVAILABLE`). 정확한 R2 보존기간은 lifecycle policy를 직접 확인하지 않았다면 주장하지 않는다.

Report에는 study partition, source_expired 수량·분포, inventory/HEAD/recompute, canary, backfill, terminal codes, live 영향, selector counts/SHA, runtime SHA, mutation 범위를 포함한다.

- [ ] **Step 5: 전체 검증·commit·push한다**

```bash
uv run pytest -q
git diff --check
git add experiments/local-vlm-evidence-analyst/b1r2-media-availability-final.json \
  experiments/local-vlm-evidence-analyst/b1r2-candidate-availability.json \
  reports/local-vlm-evidence-b1r2 \
  docs/handoff-prompts/2026-07-22-local-vlm-evidence-b1r2-media-availability-report.md \
  specs/next-session.md .claude/donts-audit.md
git commit -m "docs: B1R2 media coverage와 selector 재판정"
git push
```

**Stop Point:** verdict와 무관하게 정지한다. B2, evidence GT 웹, Local VLM model download/inference를 시작하지 않는다.

## Plan Self-Review

- Design §1~12 요구를 Task 0~7에 모두 연결했다.
- Inventory integrity, source-expired 비은폐, typed failure, manifest-bound enqueue, canary, bounded backfill, selector 재판정을 독립 gate로 나눴다.
- Existing success + missing media 우선순위와 recoverable closure 정의가 design과 일치한다.
- Placeholder, 날짜 기반 availability, 무제한 HEAD, 결과 후 기준 완화, 자동 B2 실행은 없다.
