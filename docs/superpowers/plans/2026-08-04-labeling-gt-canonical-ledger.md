# Labeling Web Canonical GT Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 완료된 `motion_clips` 사람 행동 GT를 append-only revision ledger와 clip별 head로 통일하고, 진행 중인 교차검수에 영향을 주지 않은 채 direct GT·보관함·대시보드·export가 같은 revision을 읽게 한다.

**Architecture:** 기존 session/submission/consensus/event 테이블은 immutable source로 보존한다. 별도 service-role RPC가 완료 source를 idempotent하게 shadow projection하고, owner-only reconciliation/override RPC만 head를 이동한다. 기존 소비자는 feature flag를 켠 순서대로 canonical read RPC로 전환하며 blind submit/finalize 함수에는 trigger나 동기 호출을 추가하지 않는다.

**Tech Stack:** PostgreSQL/Supabase migration + RLS/RPC, Python 3.12/pytest/uv, Next.js 14/TypeScript/Vitest, Vercel feature flags

## Global Constraints

- 설계 정본: `docs/superpowers/specs/2026-08-04-labeling-gt-canonical-ledger-design.md`.
- 구현 시작점은 최신 `origin/main`이어야 하며, 시작 전에 모든 active worktree의 dirty/owned 파일을 다시 감사한다.
- 기존 `motion_clip_labeling_sessions`, `motion_clip_blind_submissions`, `motion_clip_consensus`, `motion_clip_consensus_events` 행을 삭제·rewrite하지 않는다.
- `fn_submit_motion_blind_review`, `fn_resolve_motion_blind_consensus`와 blind finalize path에는 trigger, synchronous canonical write, 새 실패 조건을 추가하지 않는다.
- canary, tutorial, awaiting, conflict, VLM/Gate/Python Evidence, boundary GT는 canonical 행동 GT에서 제외한다.
- production DB migration/backfill, Vercel 배포, commit/push는 각 단계의 명시적 owner 승인 전 실행하지 않는다.
- 현재 충돌 중인 `codex/rba-boundary-blind-hardening`의 소유 파일이 main에 통합되기 전에는 해당 파일을 수정하지 않는다.
- 패키지는 `uv`/`npm ci`만 사용하며 새 dependency는 추가하지 않는다.

## File Structure

| 파일 | 책임 |
|---|---|
| `migrations/2026-08-04_motion_clip_canonical_gt_ledger.sql` | revision/head/reconciliation/projection-run schema와 service-role RPC |
| `tests/test_motion_clip_canonical_gt_ledger_migration.py` | migration 정적 안전 계약 |
| `tests/sql/motion_clip_canonical_gt_ledger_probe.sql` | 원자성·idempotency·blind 비변경 DB 실증 |
| `scripts/run_motion_clip_canonical_gt_ledger_probe.py` | disposable PostgreSQL probe runner |
| `scripts/project_motion_clip_canonical_gt.py` | read-only dry-run 또는 명시적 apply shadow projector 호출/보고 |
| `tests/test_project_motion_clip_canonical_gt.py` | projector CLI·fail-closed·비밀 비노출 테스트 |
| `web/src/app/api/internal/canonical-gt/project/route.ts` | blind writer와 분리된 수동 복구 projection entrypoint |
| `web/src/app/api/internal/canonical-gt/project/route.test.ts` | 비밀 인증·disabled 기본값·bounded RPC 테스트 |
| `web/src/app/api/labeling-v3/canonical-gt/health/route.ts` | owner용 projection staleness/lag 상태 |
| `web/src/app/api/labeling-v3/canonical-gt/health/route.test.ts` | 20분 health gate 권한·상태 테스트 |
| `migrations/2026-08-04_motion_clip_canonical_gt_scheduler.sql` | Supabase pg_cron 10분 job과 disabled config |
| `tests/test_motion_clip_canonical_gt_scheduler_migration.py` | scheduler 분리·권한·fail-closed 정적 계약 |
| `web/src/lib/canonicalMotionGt.ts` | canonical 공개 타입와 순수 상태/표시 규칙 |
| `web/src/lib/canonicalMotionGt.test.ts` | 타입 매핑·blind 공개 규칙 단위 테스트 |
| `web/src/lib/canonicalMotionGtServer.ts` | canonical RPC row의 서버 전용 화이트리스트 매핑 |
| `web/src/app/api/labeling-v3/[clipId]/canonical-gt/route.ts` | owner-only shadow/canary 조회와 override API |
| `web/src/app/api/labeling-v3/[clipId]/canonical-gt/route.test.ts` | 권한·검증·오류·RPC 호출 테스트 |
| `web/src/lib/labelingV3.ts` | `MotionClipDetail.canonical_gt` 공개 계약 |
| `web/src/lib/labelingV3Server.ts` | 상세 응답에 canonical 상태를 안전하게 병합 |
| `web/src/app/api/labeling-v3/[clipId]/route.ts` | flag가 켜진 owner에게 canonical read 추가 |
| `web/src/app/labeling/motion/[clipId]/page.tsx` | 완료/진행/불일치 표시와 canonical owner 정정 UX |
| `migrations/2026-08-04_motion_clip_canonical_gt_consumers.sql` | library/dashboard용 canonical read 전환 RPC |
| `web/src/app/api/labeling-v3/library/route.ts` | canonical library RPC flag 전환 |
| `web/src/app/api/labeling-v3/library/[clipId]/route.ts` | canonical library 단건 flag 전환 |
| `web/src/app/api/labeling-dashboard/route.ts` | canonical dashboard RPC flag 전환 |
| `docs/DATABASE.md` | 최종 schema/RPC/권한 계약 |
| `docs/ENV.md`, `web/.env.example` | read/write feature flag 정의 |
| `scripts/audit_motion_clip_canonical_gt_rollout.py` | production 전후 row/digest/parity 감사 |

---

### Task 1: 구현 시작점과 원천/소비자 계약을 다시 동결

**Files:**
- Create: `docs/handoff-prompts/2026-08-04-canonical-gt-implementation-manifest.md`
- Create: `artifacts/canonical-gt/source-consumer-inventory.json`
- Test: `tests/test_verify_agent_handoff.py`

**Interfaces:**
- Consumes: 설계 §2, §4, §9와 최신 main/worktree 상태.
- Produces: `HANDOFF_OK` manifest와 source/consumer path+symbol inventory; Task 2 이후는 이 SHA와 inventory만 기준으로 삼는다.

- [ ] **Step 1: 최신 main과 모든 worktree를 read-only로 감사**

Run:

```bash
git fetch origin main
git rev-parse origin/main
git worktree list --porcelain
git -C /Users/baek/petcam-lab status --short
```

Expected: 40자리 `origin/main` SHA와 각 dirty worktree가 출력된다. dirty 파일은 수정하지 않고 manifest의 `excluded_owned_paths`에 그대로 기록한다.

- [ ] **Step 2: GT producer/consumer inventory를 grep으로 재생성**

Run:

```bash
rg -n "motion_clip_labeling_sessions|motion_clip_blind_submissions|motion_clip_consensus|current_gt|final_gt|fn_list_motion_labeling_library|fn_get_labeling_data_dashboard" migrations web scripts tests docs specs
```

Expected: 각 hit를 `producer`, `canonical_candidate`, `consumer`, `excluded` 중 하나로 분류할 수 있다. 새 route/RPC가 발견되면 inventory에 추가한다.

- [ ] **Step 3: inventory schema 검증 테스트를 먼저 추가**

```python
def test_canonical_gt_inventory_has_required_classes() -> None:
    data = json.loads(Path("artifacts/canonical-gt/source-consumer-inventory.json").read_text())
    assert {item["classification"] for item in data["items"]} >= {
        "producer", "canonical_candidate", "consumer", "excluded"
    }
    assert all(Path(item["path"]).exists() for item in data["items"])
    assert data["baseline_sha"] == data["handoff_sha"]
```

- [ ] **Step 4: test가 파일 부재로 실패하는지 확인**

Run: `uv run pytest tests/test_verify_agent_handoff.py -q`

Expected: inventory 또는 manifest 부재 assertion으로 FAIL.

- [ ] **Step 5: manifest와 inventory를 작성하고 handoff 검증**

Manifest에는 다음 필드를 실제 값으로 쓴다.

```markdown
- execution_repo: /absolute/isolated/worktree/path
- plan_path: /absolute/path/docs/superpowers/plans/2026-08-04-labeling-gt-canonical-ledger.md
- design_path: /absolute/path/docs/superpowers/specs/2026-08-04-labeling-gt-canonical-ledger-design.md
- commit_sha: `git rev-parse HEAD` 출력 전문
- implementation_host: `hostname` 출력 전문
- runtime_kind: none
- runtime_host: none
- service_label: none
- excluded_owned_paths: Step 1 `git worktree list`와 각 `git status --short`에서 확인한 실제 경로 목록
```

Run:

```bash
uv run python scripts/verify_agent_handoff.py --manifest /absolute/path/docs/handoff-prompts/2026-08-04-canonical-gt-implementation-manifest.md
uv run pytest tests/test_verify_agent_handoff.py -q
```

Expected: `HANDOFF_OK`와 PASS.

- [ ] **Step 6: owner에게 파일 범위와 구현 시작 승인을 받기**

Expected: 승인 전 Task 2로 이동하지 않는다. commit도 별도 명시 승인이 없으면 만들지 않는다.

### Task 2: Additive canonical ledger와 projection RPC

**Files:**
- Create: `migrations/2026-08-04_motion_clip_canonical_gt_ledger.sql`
- Create: `tests/test_motion_clip_canonical_gt_ledger_migration.py`
- Create: `tests/sql/motion_clip_canonical_gt_ledger_probe.sql`
- Create: `scripts/run_motion_clip_canonical_gt_ledger_probe.py`

**Interfaces:**
- Consumes: finalized live `motion_clip_consensus`; completed owner `motion_clip_labeling_sessions`.
- Produces: `fn_project_motion_clip_canonical_gt(p_owner_id uuid, p_apply boolean, p_limit integer, p_after_source_id uuid, p_projection_run_id uuid) RETURNS jsonb`, `fn_get_motion_clip_canonical_gt(p_clip_id uuid, p_actor_id uuid) RETURNS jsonb`, `fn_override_motion_clip_canonical_gt(p_clip_id uuid, p_actor_id uuid, p_expected_revision_id uuid, p_new_gt jsonb, p_reason text) RETURNS jsonb`, `fn_resolve_motion_clip_gt_reconciliation(p_clip_id uuid, p_actor_id uuid, p_expected_head_revision_id uuid, p_selected_source text, p_new_gt jsonb, p_reason text) RETURNS jsonb`, `fn_record_motion_clip_gt_projection_run(...) RETURNS void`, `fn_get_motion_clip_gt_projection_health() RETURNS jsonb`.

- [ ] **Step 1: migration 정적 테스트를 실패하게 작성**

```python
SQL = Path("migrations/2026-08-04_motion_clip_canonical_gt_ledger.sql")

def test_adds_isolated_append_only_ledger() -> None:
    sql = SQL.read_text().lower()
    for table in ("motion_clip_gt_revisions", "motion_clip_gt_heads", "motion_clip_gt_reconciliation", "motion_clip_gt_projection_runs"):
        assert f"create table public.{table}" in sql
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on table public.{table} from public, anon, authenticated" in sql
    assert "before update or delete or truncate on public.motion_clip_gt_revisions" in sql

def test_does_not_touch_blind_writers_or_source_rows() -> None:
    sql = SQL.read_text().lower()
    for forbidden in (
        "create or replace function public.fn_submit_motion_blind_review",
        "create or replace function public.fn_resolve_motion_blind_consensus",
        "update public.motion_clip_consensus",
        "delete from public.motion_clip_consensus",
        "update public.motion_clip_labeling_sessions",
        "delete from public.motion_clip_labeling_sessions",
    ):
        assert forbidden not in sql

def test_projection_excludes_non_final_sources() -> None:
    sql = SQL.read_text().lower()
    assert "cohort_kind = 'live'" in sql
    assert "status in ('agreed','owner_resolved')" in sql
    assert "cohort_kind = 'canary'" not in sql
    assert "status in ('awaiting','conflict')" not in sql
```

- [ ] **Step 2: 정적 테스트가 migration 부재로 실패하는지 확인**

Run: `uv run pytest tests/test_motion_clip_canonical_gt_ledger_migration.py -q`

Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: 최소 additive schema를 작성**

Migration에는 아래 shape를 그대로 구현한다.

```sql
CREATE TABLE public.motion_clip_gt_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clip_id uuid NOT NULL REFERENCES public.motion_clips(id),
  revision_no integer NOT NULL CHECK (revision_no > 0),
  final_decision text NOT NULL CHECK (final_decision IN ('label','hold','exclude')),
  gt jsonb,
  source_type text NOT NULL CHECK (source_type IN (
    'blind_consensus','owner_adjudication','owner_override',
    'owner_direct_legacy','owner_single_adopt'
  )),
  source_table text NOT NULL,
  source_id uuid NOT NULL,
  source_version text NOT NULL,
  source_event_key text NOT NULL UNIQUE,
  parent_revision_id uuid REFERENCES public.motion_clip_gt_revisions(id),
  reason text,
  actor_id uuid,
  projection_run_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (clip_id, revision_no),
  CHECK ((final_decision='label' AND gt IS NOT NULL) OR (final_decision IN ('hold','exclude') AND gt IS NULL)),
  CHECK (source_type <> 'owner_override' OR
    (parent_revision_id IS NOT NULL AND actor_id IS NOT NULL AND char_length(btrim(reason)) BETWEEN 10 AND 500))
);

CREATE TABLE public.motion_clip_gt_heads (
  clip_id uuid PRIMARY KEY REFERENCES public.motion_clips(id),
  revision_id uuid NOT NULL UNIQUE REFERENCES public.motion_clip_gt_revisions(id),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.motion_clip_gt_reconciliation (
  clip_id uuid PRIMARY KEY REFERENCES public.motion_clips(id),
  consensus_id uuid REFERENCES public.motion_clip_consensus(id),
  session_id uuid REFERENCES public.motion_clip_labeling_sessions(id),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','resolved')),
  resolved_revision_id uuid REFERENCES public.motion_clip_gt_revisions(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  resolved_at timestamptz
);

CREATE TABLE public.motion_clip_gt_projection_runs (
  id uuid PRIMARY KEY,
  status text NOT NULL CHECK (status IN ('succeeded','failed')),
  scanned integer NOT NULL DEFAULT 0 CHECK (scanned >= 0),
  inserted integer NOT NULL DEFAULT 0 CHECK (inserted >= 0),
  error_code text,
  started_at timestamptz NOT NULL,
  finished_at timestamptz NOT NULL DEFAULT now()
);
```

또한 revision/projection-run mutation reject trigger, head/revision same-clip deferred constraint trigger,
네 테이블 RLS/revoke, 모든 RPC의 `SECURITY DEFINER SET search_path=''`와 service_role-only grant를
구현한다. `anon`, `authenticated`, 별도 blind writer role에는 table 권한과 RPC execute를 주지 않는다.

- [ ] **Step 4: projection RPC를 dry-run 우선으로 구현**

`fn_project_motion_clip_canonical_gt`는 다음 JSON shape를 반환한다.

```json
{
  "scanned": 0,
  "inserted": 0,
  "already_present": 0,
  "conflicts": 0,
  "dry_run": true,
  "next_after_source_id": null
}
```

규칙은 다음 순서로 SQL에 직접 명시한다.

```sql
-- candidate 1: live final consensus only
c.cohort_kind = 'live'
AND c.status IN ('agreed','owner_resolved')
AND c.final_decision IN ('label','hold','exclude')
AND (c.final_decision <> 'label' OR c.final_gt IS NOT NULL)

-- candidate 2: completed owner direct session only
s.reviewed_by = p_owner_id
AND s.stage = 'completed'
AND COALESCE(s.current_gt, s.initial_gt) IS NOT NULL
```

한 clip에 두 source가 있으면 JSONB equality와 무관하게 reconciliation row를 만들고 자동 head를
만들지 않는다. source 하나만 있으면 `p_apply=true`일 때 advisory lock/row lock 아래 revision insert와
head insert를 같은 transaction에서 수행한다. `source_event_key`는
`source_table || ':' || source_id || ':' || source_version`으로 고정한다.

RPC는 후보별 exception을 삼키지 않는다. 한 후보가 constraint/error로 실패하면 500건 batch 전체가
rollback되며 cursor도 전진하지 않는다. `fn_record_motion_clip_gt_projection_run`만 호출 route가 별도
transaction에서 성공/실패 결과를 기록한다.

- [ ] **Step 5: disposable DB probe를 작성**

Probe fixture는 live agreed, live owner_resolved, live awaiting, live conflict, canary agreed,
direct-only, source-overlap을 각각 1개 만든 뒤 다음을 assert한다.

```sql
-- dry-run은 write 0
SELECT count(*) FROM public.motion_clip_gt_revisions; -- 0
-- apply 후 live final/direct-only만 head 보유
-- canary/awaiting/conflict는 revision/head 0
-- overlap은 reconciliation pending, head 0
-- 두 번째 apply의 inserted=0, digest 불변
-- batch 3번째 후보에 강제 오류를 내면 revision/head/reconciliation write 전체 0
-- revision UPDATE/DELETE/TRUNCATE는 SQLSTATE 0A000
-- head/revision clip 불일치는 차단
-- source consensus/session row count와 md5(string_agg(...))는 전후 동일
-- anon/authenticated/blind role의 table SELECT/INSERT와 RPC EXECUTE는 거부
```

동시성 probe는 같은 head/revision을 기준으로 10개 connection이 override를 제출하게 하고 정확히
1개만 성공, 9개는 `PT409`, 새 revision 1개만 생성됨을 검증한다. reconciliation도 같은 방식으로
정확히 한 번만 완료돼야 한다.

- [ ] **Step 6: 정적/실증 테스트를 통과**

Run:

```bash
uv run pytest tests/test_motion_clip_canonical_gt_ledger_migration.py -q
uv run python scripts/run_motion_clip_canonical_gt_ledger_probe.py --pg-bin /opt/homebrew/opt/postgresql@17/bin
```

Expected: PASS and `CANONICAL_GT_LEDGER_PROBE_OK`.

- [ ] **Step 7: 명시적 승인 후에만 Task 2 변경을 commit**

```bash
git add migrations/2026-08-04_motion_clip_canonical_gt_ledger.sql tests/test_motion_clip_canonical_gt_ledger_migration.py tests/sql/motion_clip_canonical_gt_ledger_probe.sql scripts/run_motion_clip_canonical_gt_ledger_probe.py
git commit -m "feat: canonical GT 원장과 projection 계약 추가"
```

Expected: owner가 commit을 명시 승인한 경우에만 실행.

### Task 3: Shadow projector CLI와 production parity 감사

**Files:**
- Create: `scripts/project_motion_clip_canonical_gt.py`
- Create: `tests/test_project_motion_clip_canonical_gt.py`
- Create: `scripts/audit_motion_clip_canonical_gt_rollout.py`
- Create: `tests/test_audit_motion_clip_canonical_gt_rollout.py`
- Create: `web/src/app/api/internal/canonical-gt/project/route.ts`
- Create: `web/src/app/api/internal/canonical-gt/project/route.test.ts`
- Create: `web/src/app/api/labeling-v3/canonical-gt/health/route.ts`
- Create: `web/src/app/api/labeling-v3/canonical-gt/health/route.test.ts`
- Create: `migrations/2026-08-04_motion_clip_canonical_gt_scheduler.sql`
- Create: `tests/test_motion_clip_canonical_gt_scheduler_migration.py`
- Modify: `web/.env.example`

**Interfaces:**
- Consumes: Task 2의 `fn_project_motion_clip_canonical_gt`와 read-only Supabase REST/RPC.
- Produces: 기본 dry-run JSON report, `--apply --confirm-run-id "$RUN_ID"`가 현재 실행 run id와 일치할 때만 write; source/canonical aggregate+digest audit JSON; blind writer와 독립된 Supabase pg_cron 10분 bounded projection job.

- [ ] **Step 1: CLI fail-closed 테스트를 먼저 작성**

```python
def test_projector_defaults_to_dry_run(monkeypatch, capsys):
    client = FakeRpcClient({"dry_run": True, "inserted": 0})
    assert main([], client_factory=lambda: client) == 0
    assert client.calls[0].params["p_apply"] is False

def test_apply_requires_matching_confirmation(monkeypatch):
    with pytest.raises(SystemExit):
        main(["--apply"])

def test_output_never_contains_service_key(capsys):
    secret = "service-secret"
    main([], client_factory=lambda: FakeRpcClient({}, secret=secret))
    assert secret not in capsys.readouterr().out
```

- [ ] **Step 2: 테스트가 module 부재로 실패하는지 확인**

Run: `uv run pytest tests/test_project_motion_clip_canonical_gt.py tests/test_audit_motion_clip_canonical_gt_rollout.py -q`

Expected: FAIL on import.

- [ ] **Step 3: 표준 라이브러리 기반 CLI를 구현**

```python
@dataclass(frozen=True)
class ProjectionOptions:
    apply: bool
    run_id: UUID
    limit: int = 500
    after_source_id: UUID | None = None

def build_rpc_params(options: ProjectionOptions) -> dict[str, object]:
    return {
        "p_owner_id": require_uuid_env("DEV_USER_ID"),
        "p_apply": options.apply,
        "p_limit": options.limit,
        "p_after_source_id": str(options.after_source_id) if options.after_source_id else None,
        "p_projection_run_id": str(options.run_id),
    }
```

환경변수는 기존 Supabase helper가 쓰는 이름을 재사용하고 값은 출력하지 않는다. `--apply`는
`--confirm-run-id`가 생성 run id와 정확히 같을 때만 허용한다. HTTP/RPC error, 응답 shape 누락,
`conflicts > 0`은 exit 1로 fail-loud한다. dry-run report는 `artifacts/canonical-gt/`에 저장하되
clip UUID와 GT 원문은 제외하고 aggregate만 쓴다.

- [ ] **Step 4: audit 스크립트를 구현**

Audit 결과 shape를 고정한다.

```python
class CanonicalGtAudit(TypedDict):
    source_counts: dict[str, int]
    canonical_counts: dict[str, int]
    excluded_counts: dict[str, int]
    overlap_count: int
    reconciliation_pending: int
    orphan_head_count: int
    source_mutation_digest: str
    parity_mismatch_count: int
```

GT 원문/UUID는 report에 쓰지 않고 서버가 계산한 aggregate와 SHA-256 digest만 저장한다.

- [ ] **Step 5: CLI 테스트와 lint를 통과**

Run:

```bash
uv run pytest tests/test_project_motion_clip_canonical_gt.py tests/test_audit_motion_clip_canonical_gt_rollout.py -q
uv run ruff check scripts/project_motion_clip_canonical_gt.py scripts/audit_motion_clip_canonical_gt_rollout.py tests/test_project_motion_clip_canonical_gt.py tests/test_audit_motion_clip_canonical_gt_rollout.py
```

Expected: PASS.

- [ ] **Step 6: blind writer와 분리된 수동 복구 route 테스트를 먼저 작성**

```ts
it('기본 disabled 상태에서는 RPC를 호출하지 않는다', async () => {
  delete process.env.LABELING_CANONICAL_GT_PROJECTION_ENABLED;
  const response = await GET(requestWithBearer('cron-secret'));
  expect(response.status).toBe(404);
  expect(rpc).not.toHaveBeenCalled();
});

it('enabled 상태에서도 한 번에 500개만 projection한다', async () => {
  process.env.LABELING_CANONICAL_GT_PROJECTION_ENABLED = 'true';
  const response = await GET(requestWithBearer('cron-secret'));
  expect(response.status).toBe(200);
  expect(rpc).toHaveBeenCalledWith('fn_project_motion_clip_canonical_gt', expect.objectContaining({
    p_owner_id: process.env.DEV_USER_ID,
    p_apply: true,
    p_limit: 500,
  }));
});
```

Run: `cd web && npm test -- --run src/app/api/internal/canonical-gt/project/route.test.ts`

Expected: FAIL because route does not exist.

- [ ] **Step 7: cron 인증·disabled 기본값·bounded route를 구현**

```ts
export async function GET(req: NextRequest) {
  const secret = process.env.CRON_SECRET;
  if (!secret || req.headers.get('authorization') !== `Bearer ${secret}`) {
    return NextResponse.json({ detail: 'not found' }, { status: 404 });
  }
  if (process.env.LABELING_CANONICAL_GT_PROJECTION_ENABLED !== 'true') {
    return NextResponse.json({ detail: 'not found' }, { status: 404 });
  }
  const ownerId = process.env.DEV_USER_ID;
  if (!ownerId) return NextResponse.json({ detail: 'unavailable' }, { status: 503 });
  const runId = crypto.randomUUID();
  const { data, error } = await supabaseAdmin.rpc('fn_project_motion_clip_canonical_gt', {
    p_owner_id: ownerId,
    p_apply: true,
    p_limit: 500,
    p_after_source_id: null,
    p_projection_run_id: runId,
  });
  if (error) {
    await recordProjectionRun({ runId, status: 'failed', errorCode: stableErrorCode(error) });
    return databaseUnavailable('canonical gt projection', error);
  }
  await recordProjectionRun({ runId, status: 'succeeded', result: data });
  return NextResponse.json({ ok: true, run_id: runId, result: data });
}
```

`web/.env.example`에는 `CRON_SECRET=`와 `LABELING_CANONICAL_GT_PROJECTION_ENABLED=false`를 추가한다.
route는 blind submit/resolve route에서 import하거나 호출하지 않는다.

- [ ] **Step 8: Supabase pg_cron scheduler를 disabled 기본값으로 추가**

`pg_cron` extension이 없으면 `pg_cron_required`로 migration 전체를 중단한다. config singleton은
`enabled=false`로 생성하고, named job `canonical-motion-gt-projector-v1`만 10분 간격으로 등록한다.
job은 `fn_run_motion_clip_canonical_gt_schedule()`만 호출하며 config가 false면 write 없이
`status=disabled`를 반환한다. Vercel Hobby는 하루 1회 제한이므로 `vercel.json` cron을 만들지 않는다.

- [ ] **Step 9: 20분 staleness/lag health route를 구현**

owner-only route가 `fn_get_motion_clip_gt_projection_health`를 읽어 다음 공개 shape만 반환한다.

```ts
interface CanonicalGtProjectionHealth {
  healthy: boolean;
  lastSuccessAt: string | null;
  lagSeconds: number | null;
  pendingFinalSourceCount: number;
  lastErrorCode: string | null;
}
```

`lastSuccessAt`이 없거나 1,200초 이상 지났거나 `lagSeconds > 1200`이면 `healthy=false`다. peer 답,
GT 원문, source UUID는 반환하지 않는다. 모든 canonical consumer flag는 health가 Preview에서 연속
3회 healthy인 증거가 있기 전 production에서 켜지 않는다.

- [ ] **Step 10: scheduler·수동 route와 전체 테스트를 통과**

Run:

```bash
cd web
npm test -- --run src/app/api/internal/canonical-gt/project/route.test.ts
npm test -- --run src/app/api/labeling-v3/canonical-gt/health/route.test.ts
npx tsc --noEmit
cd ..
uv run pytest tests/test_motion_clip_canonical_gt_scheduler_migration.py -q
```

Expected: PASS, type error 0.

- [ ] **Step 11: production에서는 dry-run만 실행하고 결과 승인 받기**

Run: `uv run python scripts/project_motion_clip_canonical_gt.py --limit 500`

Expected: `dry_run=true`, source write 0, canonical write 0. `--apply`는 migration 적용과 별도 owner 승인 전 금지.

### Task 4: Owner-only canonical API와 direct GT read canary

**Files:**
- Create: `web/src/lib/canonicalMotionGt.ts`
- Create: `web/src/lib/canonicalMotionGt.test.ts`
- Create: `web/src/lib/canonicalMotionGtServer.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/canonical-gt/route.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/canonical-gt/route.test.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/canonical-gt/reconcile/route.ts`
- Create: `web/src/app/api/labeling-v3/[clipId]/canonical-gt/reconcile/route.test.ts`
- Modify: `web/src/lib/labelingV3.ts`
- Modify: `web/src/lib/labelingV3Server.ts`
- Modify: `web/src/app/api/labeling-v3/[clipId]/route.ts`
- Modify: `web/src/app/api/labeling-v3/[clipId]/route.test.ts`
- Modify: `web/src/app/api/labeling-v3/[clipId]/revise/route.ts`
- Modify: `web/src/app/api/labeling-v3/[clipId]/revise/route.test.ts`
- Modify: `web/src/app/labeling/motion/[clipId]/page.tsx`
- Create: `web/src/app/labeling/motion/[clipId]/page.test.tsx`
- Modify: `web/.env.example`

**Interfaces:**
- Consumes: `fn_get_motion_clip_canonical_gt`, `fn_override_motion_clip_canonical_gt`.
- Produces: `CanonicalMotionGt`, owner-only GET/override/reconciliation API, `LABELING_CANONICAL_GT_OWNER_READ_ENABLED` and `LABELING_CANONICAL_GT_OWNER_WRITE_ENABLED` flags.

- [ ] **Step 1: 순수 공개 계약 테스트를 먼저 작성**

```ts
it('진행 중인 blind 상태에서는 GT를 공개하지 않는다', () => {
  expect(mapCanonicalMotionGtRow({ status: 'awaiting', revision_id: null, gt: null })).toEqual({
    status: 'review_in_progress', revisionId: null, decision: null, gt: null, source: null,
  });
});

it('완료 head만 revision과 source를 공개한다', () => {
  expect(mapCanonicalMotionGtRow(finalRow())).toMatchObject({
    status: 'final', revisionId: REVISION_ID, source: 'blind_consensus',
  });
});
```

- [ ] **Step 2: route 권한/validation 테스트를 실패하게 작성**

검증 항목: unauthenticated 401, labeler 403, invalid UUID 400, GET RPC error 502, awaiting GT null,
POST reason 10~500, invalid GT 400, stale revision `PT409`→409, 성공 시 새 revision id만 반환.
reconciliation route는 pending row가 없으면 404, 이미 해결됐으면 409, source 채택 또는 새 GT+사유만
허용하고 두 source의 raw reviewer UUID는 응답하지 않는다.

Run:

```bash
cd web
npm test -- --run src/lib/canonicalMotionGt.test.ts 'src/app/api/labeling-v3/[clipId]/canonical-gt/route.test.ts'
```

Expected: FAIL because modules/routes do not exist.

- [ ] **Step 3: 공개 타입와 화이트리스트 매퍼 구현**

```ts
export type CanonicalGtStatus = 'none' | 'review_in_progress' | 'conflict' | 'final';
export type CanonicalGtSource =
  | 'blind_consensus' | 'owner_adjudication' | 'owner_override'
  | 'owner_direct_legacy' | 'owner_single_adopt';

export interface CanonicalMotionGt {
  status: CanonicalGtStatus;
  revisionId: string | null;
  decision: 'label' | 'hold' | 'exclude' | null;
  gt: GroundTruthInput | null;
  source: CanonicalGtSource | null;
  sourceLabel: string | null;
  updatedAt: string | null;
}
```

매퍼는 위 필드만 복사하고 source UUID, reviewer UUID, peer answer, raw DB error를 반환하지 않는다.

- [ ] **Step 4: owner-only GET/POST route 구현**

GET은 `requireOwner` 후 read RPC를 호출한다. POST는 기존 `validateGroundTruth`와 whitelist sanitize를
재사용하고 `{expectedRevisionId, gt, reason}`만 받아 override RPC를 호출한다. flag가 false면
canonical POST는 404로 숨긴다.

`/reconcile`은 `{expectedHeadRevisionId, selectedSource, gt, reason}`을 받아 resolve RPC를 호출한다.
`selectedSource`는 `consensus | direct | new`만 허용하고 `new`에서만 새 GT를 요구한다.

기존 `/revise`는 write flag가 false일 때 현재 RPC를 그대로 호출한다. write flag가 true면 같은
validated payload를 canonical override RPC로 전달해 구형 client도 legacy session만 수정해 divergence를
새로 만들 수 없게 한다.

- [ ] **Step 5: direct detail에 read flag를 붙임**

```ts
const canonicalEnabled = process.env.LABELING_CANONICAL_GT_OWNER_READ_ENABLED === 'true';
if (canonicalEnabled && acc.isOwner) {
  detailRow.canonical_gt = await loadCanonicalMotionGt(acc.clip.id, acc.userId);
}
```

flag false 응답은 현재 JSON과 byte-level shape가 같아야 한다. `MotionClipDetail.canonical_gt`는 optional로
추가하고 labeler 응답에는 키 자체가 없어야 한다.

- [ ] **Step 6: 프레임 단위 UX를 구현**

- `canonical_gt.status='final'`: canonical GT로 form prefill, source badge 표시.
- `review_in_progress`: “교차검수 진행 중”만 표시, 답/GT 없음.
- `conflict`: “Owner 해결 대기”만 표시, peer 답 없음.
- `none`: 기존 session UX 유지.
- write flag true + final: 정정 사유 입력 후 canonical POST; 성공 시 reload.
- 두 flag false: 기존 UI와 동작 동일.

owner conflict 화면에서는 provenance를 가진 두 source만 나란히 보여주고 reviewer 신원은 숨긴다.
`consensus 채택`, `direct 채택`, `새 GT 입력`과 필수 사유를 제출하면 resolve RPC 결과 revision으로
reload한다. 자동 선택과 일괄 해결 버튼은 만들지 않는다.

- [ ] **Step 7: web targeted/full 검증**

Run:

```bash
cd web
npm test -- --run src/lib/canonicalMotionGt.test.ts 'src/app/api/labeling-v3/[clipId]/canonical-gt/route.test.ts' 'src/app/api/labeling-v3/[clipId]/route.test.ts' 'src/app/labeling/motion/[clipId]/page.test.tsx'
npm test -- --run 'src/app/api/labeling-v3/[clipId]/canonical-gt/reconcile/route.test.ts' 'src/app/api/labeling-v3/[clipId]/revise/route.test.ts'
npm test -- --run
npx tsc --noEmit
```

Expected: targeted PASS, 전체 943개 이상 PASS, type error 0.

- [ ] **Step 8: Preview owner-only canary 승인 gate**

read flag만 true인 Preview에서 final/direct-only/conflict/awaiting 각 1건을 확인한다. production과 write flag는
false로 유지한다. 결과 캡처와 revision id/digest만 기록하고 GT 원문은 로그에 남기지 않는다.

### Task 5: Library·dashboard·export 소비자 전환

**Files:**
- Create: `migrations/2026-08-04_motion_clip_canonical_gt_consumers.sql`
- Create: `tests/test_motion_clip_canonical_gt_consumers_migration.py`
- Create: `tests/sql/motion_clip_canonical_gt_consumers_probe.sql`
- Create: `scripts/run_motion_clip_canonical_gt_consumers_probe.py`
- Modify: `web/src/app/api/labeling-v3/library/route.ts`
- Modify: `web/src/app/api/labeling-v3/library/route.test.ts`
- Modify: `web/src/app/api/labeling-v3/library/[clipId]/route.ts`
- Modify: `web/src/app/api/labeling-v3/library/[clipId]/route.test.ts`
- Modify: `web/src/app/api/labeling-dashboard/route.ts`
- Modify: `web/src/app/api/labeling-dashboard/route.test.ts`
- Modify: `web/src/lib/labelingRoleServer.ts`
- Modify: `web/src/lib/rbaBoundaryServer.ts`
- Create: `scripts/export_motion_clip_canonical_gt.py`
- Create: `tests/test_export_motion_clip_canonical_gt.py`
- Modify: `web/.env.example`

**Interfaces:**
- Consumes: canonical head view/RPC from Task 2.
- Produces: `fn_list_motion_labeling_library_canonical`, `fn_get_labeling_data_dashboard_canonical`, versioned JSONL export with `revision_id` and provenance.

- [ ] **Step 1: consumer migration 안전 테스트를 먼저 작성**

```python
def test_consumers_read_heads_not_source_precedence() -> None:
    sql = SQL.read_text().lower()
    assert "motion_clip_gt_heads" in sql
    assert "motion_clip_gt_revisions" in sql
    for forbidden in ("motion_clip_consensus", "motion_clip_labeling_sessions", "coalesce(s.current_gt"):
        assert forbidden not in sql

def test_consumer_migration_does_not_replace_existing_rpc() -> None:
    sql = SQL.read_text().lower()
    assert "create or replace function public.fn_list_motion_labeling_library(" not in sql
    assert "create or replace function public.fn_get_labeling_data_dashboard(" not in sql
```

- [ ] **Step 2: 테스트가 migration 부재로 실패하는지 확인**

Run: `uv run pytest tests/test_motion_clip_canonical_gt_consumers_migration.py -q`

Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: 새 이름의 canonical consumer RPC를 구현**

기존 RPC를 replace하지 않고 `_canonical` suffix의 새 RPC를 만든다. 반환에는 기존 필드와 함께
`gt_revision_id`, `gt_source_type`, `gt_updated_at`을 추가한다. `label_state='re_review'`와
확정 전 공개 규칙은 유지하며 canonical head가 없는 clip의 `final_gt`는 null이다.

- [ ] **Step 4: disposable probe에서 세 소비자의 revision/digest 일치를 검증**

```sql
-- 같은 clip에 대해 다음 세 값이 같아야 함
library.gt_revision_id = dashboard source revision id
library.final_gt = canonical head revision.gt
export.gt_revision_id = library.gt_revision_id
-- awaiting/conflict/canary는 세 소비자 모두 GT null 또는 제외
```

Run: `uv run python scripts/run_motion_clip_canonical_gt_consumers_probe.py --pg-bin /opt/homebrew/opt/postgresql@17/bin`

Expected: `CANONICAL_GT_CONSUMERS_PROBE_OK`.

- [ ] **Step 5: route를 독립 flag로 전환**

```ts
const rpcName = process.env.LABELING_CANONICAL_GT_LIBRARY_READ_ENABLED === 'true'
  ? 'fn_list_motion_labeling_library_canonical'
  : 'fn_list_motion_labeling_library';
```

Dashboard는 `LABELING_CANONICAL_GT_DASHBOARD_READ_ENABLED`, export는 CLI의
`--source canonical` 명시 옵션을 각각 사용한다. false일 때 기존 RPC 이름과 response shape를 유지한다.

- [ ] **Step 6: export를 GT 원문과 provenance를 분리해 구현**

```json
{"clip_id":"...","revision_id":"...","decision":"label","gt":{},"provenance":{"source_type":"blind_consensus","source_version":"motion-blind-v1"}}
```

기본 출력은 local `artifacts/canonical-gt/exports/`이며 R2 upload, DB write, prediction 포함을 하지 않는다.
manifest에는 export schema version, source snapshot digest, generated_at을 기록한다.

- [ ] **Step 7: targeted/full 검증**

Run:

```bash
uv run pytest tests/test_motion_clip_canonical_gt_consumers_migration.py tests/test_export_motion_clip_canonical_gt.py -q
cd web
npm test -- --run 'src/app/api/labeling-v3/library/route.test.ts' 'src/app/api/labeling-v3/library/[clipId]/route.test.ts' src/app/api/labeling-dashboard/route.test.ts
npm test -- --run
npx tsc --noEmit
```

Expected: all PASS.

### Task 6: 문서화, 전체 검증, 단계별 production rollout

**Files:**
- Modify: `docs/DATABASE.md`
- Modify: `docs/ENV.md`
- Modify: `docs/FEATURES.md`
- Modify: `specs/feature-rba-data-engine-v1.md`
- Modify: `specs/next-session.md`
- Modify: `specs/README.md`
- Modify: `.claude/donts-audit.md`
- Create: `docs/handoff-prompts/2026-08-04-canonical-gt-rollout-report.md`

**Interfaces:**
- Consumes: Task 1~5의 schema, flags, probes, audit reports.
- Produces: 운영 SOT, 단계별 go/no-go/rollback 기록, 최종 `DEPLOYED_VERIFIED` 증거.

- [ ] **Step 1: 문서 계약을 실제 symbol과 맞춰 갱신**

`docs/DATABASE.md`에는 테이블/RPC signature, RLS, append-only, source exclusion을 기록한다.
`docs/ENV.md`와 `.env.example`에는 네 flag를 모두 기본 `false`로 기록한다.

```dotenv
LABELING_CANONICAL_GT_OWNER_READ_ENABLED=false
LABELING_CANONICAL_GT_OWNER_WRITE_ENABLED=false
LABELING_CANONICAL_GT_LIBRARY_READ_ENABLED=false
LABELING_CANONICAL_GT_DASHBOARD_READ_ENABLED=false
LABELING_CANONICAL_GT_PROJECTION_ENABLED=false
CRON_SECRET=
```

- [ ] **Step 2: 전체 로컬 검증**

Run:

```bash
uv run pytest
cd web && npm test -- --run && npx tsc --noEmit && npm run build
```

Expected: Python 1,173개 이상 PASS(known skip만), web 943개 이상 PASS, type error 0, build exit 0.

- [ ] **Step 3: production mutation 전 승인과 preflight**

승인 요청에는 정확히 다음을 제시한다.

- target migration 파일과 SHA-256
- production source status별 count/digest
- 현재 live awaiting count
- dry-run projected/already-present/conflict count
- 네 flag가 모두 false임
- rollback이 flag-off + projector stop임

Expected: 명시 승인 전 migration apply/backfill/deploy 금지.

- [ ] **Step 4: additive migration 적용 후 기존 runtime 불변 확인**

Migration 적용 직후 projector apply 전에 audit를 실행한다.

Expected: source row count/digest 동일, revision/head 0, blind submit/resolve smoke PASS, 현재 교차검수 UI 정상.

- [ ] **Step 5: shadow projection을 bounded batch로 적용**

Run:

```bash
RUN_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
SOURCE_DIGEST="$(uv run python scripts/audit_motion_clip_canonical_gt_rollout.py --print-source-digest)"
uv run python scripts/project_motion_clip_canonical_gt.py --apply --run-id "$RUN_ID" --confirm-run-id "$RUN_ID" --limit 500
uv run python scripts/audit_motion_clip_canonical_gt_rollout.py --expected-source-digest "$SOURCE_DIGEST"
```

Expected: source digest 동일, orphan head 0, excluded source revision 0. 각 batch 사이 audit PASS 후 다음 batch로 이동한다.

- [ ] **Step 6: Preview에서 flag를 한 개씩 켜고 검증**

순서: owner read → owner write → library → dashboard. 각 단계마다 final/direct-only/awaiting/conflict
fixture와 role matrix(owner/labeler/unauthenticated)를 확인한다. 실패 시 해당 flag만 false로 되돌리고
다음 단계로 이동하지 않는다.

- [ ] **Step 7: production canary와 관측**

owner read만 먼저 켜고 최소 한 운영 관측 기간 동안 API 5xx, canonical RPC latency, blind completion
rate, source digest를 비교한다. 이상 0일 때만 owner write, library, dashboard를 별도 승인으로 순차 전환한다.

- [ ] **Step 8: 최종 증거를 기록**

Rollout report에 다음 실제 값을 적는다.

```markdown
- repository HEAD / upstream
- tracked / staged / untracked status
- production migration identifiers
- Vercel deployment URL and deployment id
- all feature flag values
- pre/post source counts and digest
- revision/head/reconciliation counts
- direct/library/dashboard/export parity mismatch count
- blind smoke result and awaiting/completion count delta
- rollback test result
```

완료 판정은 `docs/agent-execution-contract.md`의 `DEPLOYED_VERIFIED` 증거를 모두 만족할 때만 한다.

- [ ] **Step 9: 명시적 승인 후 문서와 구현을 commit/push**

```bash
git add migrations tests scripts web docs specs .claude/donts-audit.md
git commit -m "feat: labeling web canonical GT 원장 통일"
git push -u origin codex/labeling-gt-canonical-ledger
```

Expected: owner가 commit과 push를 각각 명시 승인한 경우에만 실행한다.

## Execution Order and Stop Gates

1. Task 1은 구현 승인 전 stop gate다.
2. Task 2~3은 production 미사용 schema/shadow 도구이며 migration 적용 승인 전 stop gate다.
3. Task 4는 Preview owner-only read가 통과하기 전 write flag를 켜지 않는다.
4. Task 5는 direct canary parity가 통과하기 전 시작하지 않는다.
5. Task 6의 production 각 단계는 독립 승인·rollback gate다.
6. 어떤 단계에서도 source digest가 바뀌거나 blind smoke가 실패하면 즉시 중단하고 flag-off/projector stop으로 복구한다.
