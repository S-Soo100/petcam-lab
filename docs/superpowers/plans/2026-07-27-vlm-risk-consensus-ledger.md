# VLM Risk Consensus Shadow Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 위험 라벨 VLM 3회 판독을 production 결과와 분리된 service-role-only append-only 원장에 안전하게 저장한다.

**Architecture:** `clip_vlm_jobs`를 부모 identity로 삼는 원장 테이블과 원자 batch insert RPC를 forward migration 하나로 추가한다. 정적 계약 테스트와 disposable PostgreSQL rollback probe를 분리해 SQL 문구와 실제 잠금·권한·멱등 동작을 모두 검증한다.

**Tech Stack:** PostgreSQL 15, Supabase/PostgREST RPC, Python 3.12, pytest

## Global Constraints

- protocol version은 정확히 `risk-consensus-shadow-v1`이다.
- attempt index는 `1..3`, batch size는 `1..4`, batch position은 `0..batch_size-1`이다.
- production `clip_vlm_jobs`, `motion_clips`, GT, behavior, activity, app row는 수정하지 않는다.
- 원장에는 reasoning, frame path, R2 key, signed URL, 이메일, 사용자 identity를 저장하지 않는다.
- RLS enabled, client policy 0, service_role only, `SECURITY INVOKER SET search_path=''`를 사용한다.
- UPDATE·DELETE·TRUNCATE는 role과 무관하게 SQLSTATE `0A000`으로 차단한다.
- migration은 forward-only 신규 파일이며 기존 migration을 수정하지 않는다.
- production apply, model inference, R2 write, app/web 변경은 이 계획 범위 밖이다.

---

## File Structure

- Create: `migrations/2026-07-27_vlm_risk_consensus_shadow.sql`
  - 테이블, append-only trigger, 원자 insert RPC, grant를 정의한다.
- Create: `tests/test_vlm_risk_consensus_shadow_migration.py`
  - migration의 정적 보안·무결성 계약을 고정한다.
- Create: `tests/sql/vlm_risk_consensus_shadow_prerequisites.sql`
  - disposable PostgreSQL에 부모 테이블과 role의 최소 fixture를 만든다.
- Create: `tests/sql/vlm_risk_consensus_shadow_probe.sql`
  - 정상·멱등·위조·append-only·권한 시나리오를 rollback 안에서 검증한다.
- Create: `scripts/run_vlm_risk_consensus_shadow_probe.py`
  - localhost의 무작위 임시 DB만 만들고 항상 정리하는 fail-closed runner다.
- Create: `tests/test_vlm_risk_consensus_shadow_runtime_probe.py`
  - runner의 DB명·localhost·cleanup 계약을 단위 테스트한다.
- Modify: `specs/next-session.md`
  - 구현 상태와 production 미적용 경계를 additive로 기록한다.
- Modify: `.claude/donts-audit.md`
  - append-only payload allowlist와 cross-job 검증 교훈을 한 줄 남긴다.

### Task 1: 원장 DDL과 정적 계약

**Files:**
- Create: `tests/test_vlm_risk_consensus_shadow_migration.py`
- Create: `migrations/2026-07-27_vlm_risk_consensus_shadow.sql`

**Interfaces:**
- Consumes: 기존 `public.clip_vlm_jobs(id, clip_id, model_requested, prompt_version, prompt_sha256, sampler_version)`.
- Produces: `public.clip_vlm_shadow_attempts`와 append-only trigger.

- [ ] **Step 1: 정적 계약의 failing test를 작성한다**

```python
from pathlib import Path

SQL = Path("migrations/2026-07-27_vlm_risk_consensus_shadow.sql")


def text() -> str:
    return SQL.read_text().lower()


def test_creates_closed_shadow_attempt_ledger():
    sql = text()
    assert "create table public.clip_vlm_shadow_attempts" in sql
    for value in ("succeeded", "deferred", "failed", "integrity_failure", "not_run"):
        assert f"'{value}'" in sql
    assert "unique (job_id, protocol_version, attempt_index)" in sql
    assert "attempt_index between 1 and 3" in sql
    assert "batch_size between 1 and 4" in sql


def test_ledger_is_service_role_only_append_only():
    sql = text()
    assert "enable row level security" in sql
    assert "create policy" not in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
    for operation in ("before update", "before delete", "before truncate"):
        assert operation in sql
    assert "errcode='0a000'" in sql or "errcode = '0a000'" in sql


def test_no_forbidden_raw_fields_are_columns():
    sql = text()
    for forbidden in ("reasoning", "r2_key", "signed_url", "frame_path", "email"):
        assert forbidden not in sql
```

- [ ] **Step 2: RED를 확인한다**

Run: `uv run pytest -q tests/test_vlm_risk_consensus_shadow_migration.py`

Expected: FAIL because the migration file does not exist.

- [ ] **Step 3: 테이블·CHECK·append-only DDL을 최소 구현한다**

```sql
create table public.clip_vlm_shadow_attempts (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.clip_vlm_jobs(id) on delete restrict,
  clip_id uuid not null references public.motion_clips(id) on delete restrict,
  protocol_version text not null check (protocol_version = 'risk-consensus-shadow-v1'),
  batch_identity_sha256 text not null check (batch_identity_sha256 ~ '^[0-9a-f]{64}$'),
  batch_size smallint not null check (batch_size between 1 and 4),
  batch_position smallint not null check (batch_position between 0 and 3),
  attempt_index smallint not null check (attempt_index between 1 and 3),
  status text not null check (
    status in ('succeeded','deferred','failed','integrity_failure','not_run')
  ),
  failure_code text check (
    failure_code is null or failure_code in (
      'shadow_deferred_deadline','not_logged_in','auth_probe_failed','quota_exceeded',
      'shadow_provider_error','shadow_model_mismatch','shadow_clip_set_mismatch',
      'shadow_not_run_breaker'
    )
  ),
  action text check (
    action is null or action in (
      'eating_paste','eating_prey','drinking','shedding','moving','unseen','hand_feeding'
    )
  ),
  confidence numeric check (confidence is null or confidence between 0 and 1),
  provider text not null check (provider = 'claude_cli_batch'),
  model_requested text not null,
  model_actual text,
  prompt_version text not null,
  prompt_sha256 text not null check (prompt_sha256 ~ '^[0-9a-f]{64}$'),
  sampler_version text not null,
  provider_request_sha256 text
    check (provider_request_sha256 is null or provider_request_sha256 ~ '^[0-9a-f]{64}$'),
  input_tokens bigint check (input_tokens is null or input_tokens >= 0),
  cache_creation_input_tokens bigint
    check (cache_creation_input_tokens is null or cache_creation_input_tokens >= 0),
  cache_read_input_tokens bigint
    check (cache_read_input_tokens is null or cache_read_input_tokens >= 0),
  output_tokens bigint check (output_tokens is null or output_tokens >= 0),
  provider_estimated_cost_usd numeric(12,6)
    check (provider_estimated_cost_usd is null or provider_estimated_cost_usd >= 0),
  created_at timestamptz not null default now(),
  unique (job_id, protocol_version, attempt_index),
  check (
    (status = 'succeeded' and failure_code is null and action is not null and confidence is not null)
    or
    (status <> 'succeeded' and failure_code is not null and action is null and confidence is null)
  ),
  check (batch_position < batch_size)
);

create index idx_clip_vlm_shadow_attempts_batch
  on public.clip_vlm_shadow_attempts(protocol_version, batch_identity_sha256, attempt_index);
create index idx_clip_vlm_shadow_attempts_job
  on public.clip_vlm_shadow_attempts(job_id, created_at);

alter table public.clip_vlm_shadow_attempts enable row level security;
revoke all on public.clip_vlm_shadow_attempts from public, anon, authenticated;
grant select, insert on public.clip_vlm_shadow_attempts to service_role;

create function public.fn_block_vlm_shadow_attempt_mutation() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  raise exception 'clip_vlm_shadow_attempts is append-only' using errcode='0A000';
end $$;

create trigger trg_block_vlm_shadow_attempt_update
  before update on public.clip_vlm_shadow_attempts
  for each row execute function public.fn_block_vlm_shadow_attempt_mutation();
create trigger trg_block_vlm_shadow_attempt_delete
  before delete on public.clip_vlm_shadow_attempts
  for each row execute function public.fn_block_vlm_shadow_attempt_mutation();
create trigger trg_block_vlm_shadow_attempt_truncate
  before truncate on public.clip_vlm_shadow_attempts
  for each statement execute function public.fn_block_vlm_shadow_attempt_mutation();
```

- [ ] **Step 4: GREEN을 확인한다**

Run: `uv run pytest -q tests/test_vlm_risk_consensus_shadow_migration.py`

Expected: PASS.

- [ ] **Step 5: Task 1을 커밋한다**

```bash
git add migrations/2026-07-27_vlm_risk_consensus_shadow.sql \
  tests/test_vlm_risk_consensus_shadow_migration.py
git commit -m "feat: VLM consensus shadow 원장 추가"
```

### Task 2: 원자 batch insert RPC와 payload 경계

**Files:**
- Modify: `tests/test_vlm_risk_consensus_shadow_migration.py`
- Modify: `migrations/2026-07-27_vlm_risk_consensus_shadow.sql`

**Interfaces:**
- Consumes: attempt payload JSON array, 한 호출당 동일 batch·attempt의 1~4 rows.
- Produces: `fn_insert_vlm_shadow_attempt_batch(p_attempts jsonb) returns integer`.

- [ ] **Step 1: RPC 무결성 정적 테스트를 추가한다**

```python
def test_atomic_insert_rpc_validates_shape_identity_and_provenance():
    sql = text()
    assert "fn_insert_vlm_shadow_attempt_batch" in sql
    assert "jsonb_array_length(p_attempts) < 1" in sql
    assert "jsonb_array_length(p_attempts) > 4" in sql
    assert "order by j.id for update" in sql
    assert "shadow payload does not match vlm job provenance" in sql
    assert "shadow batch identity mismatch" in sql
    assert "shadow duplicate payload mismatch" in sql
    assert "unexpected shadow payload key" in sql


def test_rpc_is_service_role_only_with_empty_search_path():
    sql = text()
    assert "security invoker set search_path=''" in sql
    assert (
        "revoke all on function public.fn_insert_vlm_shadow_attempt_batch(jsonb) "
        "from public, anon, authenticated"
    ) in sql
    assert (
        "grant execute on function public.fn_insert_vlm_shadow_attempt_batch(jsonb) "
        "to service_role"
    ) in sql
```

- [ ] **Step 2: RED를 확인한다**

Run: `uv run pytest -q tests/test_vlm_risk_consensus_shadow_migration.py`

Expected: FAIL because the RPC does not exist.

- [ ] **Step 3: migration에 원자 RPC를 추가한다**

RPC 구현은 아래 순서를 그대로 따른다.

```sql
create function public.fn_insert_vlm_shadow_attempt_batch(p_attempts jsonb)
returns integer
language plpgsql security invoker set search_path='' as $$
declare
  item jsonb;
  j public.clip_vlm_jobs%rowtype;
  existing public.clip_vlm_shadow_attempts%rowtype;
  expected_keys constant text[] := array[
    'job_id','clip_id','protocol_version','batch_identity_sha256','batch_size',
    'batch_position','attempt_index','status','failure_code','action','confidence',
    'provider','model_requested','model_actual','prompt_version','prompt_sha256',
    'sampler_version','provider_request_sha256','input_tokens',
    'cache_creation_input_tokens','cache_read_input_tokens','output_tokens',
    'provider_estimated_cost_usd'
  ];
  first_protocol text;
  first_batch text;
  first_attempt integer;
  first_size integer;
  positions integer[];
  affected integer := 0;
begin
  if jsonb_typeof(p_attempts) is distinct from 'array'
     or jsonb_array_length(p_attempts) < 1
     or jsonb_array_length(p_attempts) > 4 then
    raise exception 'shadow attempts must be array size 1..4' using errcode='22023';
  end if;

  select value->>'protocol_version',
         value->>'batch_identity_sha256',
         (value->>'attempt_index')::integer,
         (value->>'batch_size')::integer
    into first_protocol, first_batch, first_attempt, first_size
    from jsonb_array_elements(p_attempts) limit 1;

  if first_size <> jsonb_array_length(p_attempts) then
    raise exception 'shadow batch size mismatch' using errcode='22023';
  end if;

  select array_agg((value->>'batch_position')::integer order by (value->>'batch_position')::integer)
    into positions from jsonb_array_elements(p_attempts);
  if positions <> (select array_agg(x) from generate_series(0, first_size - 1) x) then
    raise exception 'shadow batch positions mismatch' using errcode='22023';
  end if;

  -- 같은 job 집합을 다르게 정렬한 동시 payload도 deadlock을 만들지 않도록 잠금 순서를 고정한다.
  perform 1
    from public.clip_vlm_jobs j
    where j.id in (
      select (value->>'job_id')::uuid from jsonb_array_elements(p_attempts)
    )
    order by j.id for update;

  for item in select value from jsonb_array_elements(p_attempts) loop
    if exists (
      select 1 from jsonb_object_keys(item) key
      where not (key = any(expected_keys))
    ) then
      raise exception 'unexpected shadow payload key' using errcode='22023';
    end if;
    if item->>'protocol_version' is distinct from first_protocol
       or item->>'batch_identity_sha256' is distinct from first_batch
       or (item->>'attempt_index')::integer is distinct from first_attempt
       or (item->>'batch_size')::integer is distinct from first_size then
      raise exception 'shadow batch identity mismatch' using errcode='22023';
    end if;

    select * into j from public.clip_vlm_jobs
      where id=(item->>'job_id')::uuid;
    if not found
       or j.clip_id is distinct from (item->>'clip_id')::uuid
       or j.model_requested is distinct from item->>'model_requested'
       or j.prompt_version is distinct from item->>'prompt_version'
       or j.prompt_sha256 is distinct from item->>'prompt_sha256'
       or j.sampler_version is distinct from item->>'sampler_version' then
      raise exception 'shadow payload does not match vlm job provenance' using errcode='22023';
    end if;

    insert into public.clip_vlm_shadow_attempts (
      job_id,clip_id,protocol_version,batch_identity_sha256,batch_size,batch_position,
      attempt_index,status,failure_code,action,confidence,provider,model_requested,
      model_actual,prompt_version,prompt_sha256,sampler_version,provider_request_sha256,
      input_tokens,cache_creation_input_tokens,cache_read_input_tokens,output_tokens,
      provider_estimated_cost_usd
    ) values (
      (item->>'job_id')::uuid,(item->>'clip_id')::uuid,item->>'protocol_version',
      item->>'batch_identity_sha256',(item->>'batch_size')::smallint,
      (item->>'batch_position')::smallint,(item->>'attempt_index')::smallint,
      item->>'status',nullif(item->>'failure_code',''),nullif(item->>'action',''),
      nullif(item->>'confidence','')::numeric,item->>'provider',item->>'model_requested',
      nullif(item->>'model_actual',''),item->>'prompt_version',item->>'prompt_sha256',
      item->>'sampler_version',nullif(item->>'provider_request_sha256',''),
      nullif(item->>'input_tokens','')::bigint,
      nullif(item->>'cache_creation_input_tokens','')::bigint,
      nullif(item->>'cache_read_input_tokens','')::bigint,
      nullif(item->>'output_tokens','')::bigint,
      nullif(item->>'provider_estimated_cost_usd','')::numeric
    ) on conflict (job_id,protocol_version,attempt_index) do nothing;

    if not found then
      select * into existing from public.clip_vlm_shadow_attempts
        where job_id=(item->>'job_id')::uuid
          and protocol_version=item->>'protocol_version'
          and attempt_index=(item->>'attempt_index')::smallint;
      if existing.clip_id is distinct from (item->>'clip_id')::uuid
         or existing.batch_identity_sha256 is distinct from item->>'batch_identity_sha256'
         or existing.batch_size is distinct from (item->>'batch_size')::smallint
         or existing.batch_position is distinct from (item->>'batch_position')::smallint
         or existing.status is distinct from item->>'status'
         or existing.failure_code is distinct from nullif(item->>'failure_code','')
         or existing.action is distinct from nullif(item->>'action','')
         or existing.confidence is distinct from nullif(item->>'confidence','')::numeric
         or existing.provider is distinct from item->>'provider'
         or existing.model_requested is distinct from item->>'model_requested'
         or existing.model_actual is distinct from nullif(item->>'model_actual','')
         or existing.prompt_version is distinct from item->>'prompt_version'
         or existing.prompt_sha256 is distinct from item->>'prompt_sha256'
         or existing.sampler_version is distinct from item->>'sampler_version'
         or existing.provider_request_sha256 is distinct from
              nullif(item->>'provider_request_sha256','')
         or existing.input_tokens is distinct from nullif(item->>'input_tokens','')::bigint
         or existing.cache_creation_input_tokens is distinct from
              nullif(item->>'cache_creation_input_tokens','')::bigint
         or existing.cache_read_input_tokens is distinct from
              nullif(item->>'cache_read_input_tokens','')::bigint
         or existing.output_tokens is distinct from nullif(item->>'output_tokens','')::bigint
         or existing.provider_estimated_cost_usd is distinct from
              nullif(item->>'provider_estimated_cost_usd','')::numeric then
        raise exception 'shadow duplicate payload mismatch' using errcode='22023';
      end if;
    end if;
    affected := affected + 1;
  end loop;
  return affected;
end $$;

revoke all on function public.fn_block_vlm_shadow_attempt_mutation()
  from public, anon, authenticated;
revoke all on function public.fn_insert_vlm_shadow_attempt_batch(jsonb)
  from public, anon, authenticated;
grant execute on function public.fn_insert_vlm_shadow_attempt_batch(jsonb)
  to service_role;
```

- [ ] **Step 4: GREEN을 확인한다**

Run: `uv run pytest -q tests/test_vlm_risk_consensus_shadow_migration.py`

Expected: PASS.

- [ ] **Step 5: Task 2를 커밋한다**

```bash
git add migrations/2026-07-27_vlm_risk_consensus_shadow.sql \
  tests/test_vlm_risk_consensus_shadow_migration.py
git commit -m "feat: VLM shadow batch 원자 저장 강제"
```

### Task 3: disposable PostgreSQL 적대 probe

**Files:**
- Create: `tests/sql/vlm_risk_consensus_shadow_prerequisites.sql`
- Create: `tests/sql/vlm_risk_consensus_shadow_probe.sql`
- Create: `scripts/run_vlm_risk_consensus_shadow_probe.py`
- Create: `tests/test_vlm_risk_consensus_shadow_runtime_probe.py`

**Interfaces:**
- Consumes: Task 2 migration.
- Produces: 성공 시 `VLM_SHADOW_RUNTIME_OK`, `VLM_SHADOW_INTEGRITY_OK`,
  `VLM_SHADOW_CONCURRENCY_OK`, `VLM_SHADOW_SECURITY_OK`, `PROBE_RESIDUE=0` 다섯 marker.

- [ ] **Step 1: runner 경계의 failing unit test를 작성한다**

```python
from scripts.run_vlm_risk_consensus_shadow_probe import (
    temp_database_name,
    validate_database_url,
    validate_temp_database_name,
)


def test_temp_database_name_is_scoped():
    name = temp_database_name()
    assert name.startswith("vlm_shadow_probe_")
    assert validate_temp_database_name(name) == name


def test_runner_rejects_non_local_database():
    for url in (
        "postgresql://u:p@example.com/db",
        "postgresql://u:p@10.0.0.5/db",
        "postgresql://u:p@localhost/production",
    ):
        try:
            validate_database_url(url)
        except ValueError:
            pass
        else:
            raise AssertionError(url)
```

- [ ] **Step 2: RED를 확인한다**

Run: `uv run pytest -q tests/test_vlm_risk_consensus_shadow_runtime_probe.py`

Expected: FAIL because the runner module does not exist.

- [ ] **Step 3: fail-closed runner를 작성한다**

`scripts/run_motion_double_blind_concurrency_probe.py`의 `_Backend` 패턴을 재사용하되,
prefix와 SQL 파일만 다음처럼 고정한다.

```python
PREFIX = "vlm_shadow_probe_"
SQL_FILES = (
    "tests/sql/vlm_risk_consensus_shadow_prerequisites.sql",
    "migrations/2026-07-15_clip_vlm_candidate_jobs.sql",
    "migrations/2026-07-27_vlm_risk_consensus_shadow.sql",
    "tests/sql/vlm_risk_consensus_shadow_probe.sql",
)


def temp_database_name() -> str:
    import secrets
    return PREFIX + secrets.token_hex(8)


def validate_temp_database_name(name: str) -> str:
    import re
    if re.fullmatch(r"vlm_shadow_probe_[0-9a-f]{16}", name) is None:
        raise ValueError("invalid temporary database name")
    return name


def validate_database_url(url: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("probe database must be local")
    if parsed.path.lstrip("/") in {"", "postgres", "template0", "template1", "production"}:
        raise ValueError("probe database name is not disposable")
    validate_temp_database_name(parsed.path.lstrip("/"))
    return url
```

Runner main은 `createdb` 후 네 SQL을 순서대로 `psql -v ON_ERROR_STOP=1 -f`로 실행하고,
`finally`에서 정확히 검증된 임시 DB만 `dropdb`한다. create·query·drop return code 중 하나라도
실패하면 exit 2이며 `PROBE_RESIDUE=0`을 출력하지 않는다.

정상 probe가 끝난 뒤 서로 다른 두 `psql` process에 같은 job 4개를 정순·역순 JSON으로
동시에 전달한다. 두 process의 stdin을 먼저 모두 열고 50ms 안에 flush한 뒤 각각 완료를
기다려야 하며, 순차 `communicate()`로 동시성을 가장하면 안 된다. 둘 다 5초 안에 종료하고
row가 정확히 4개면 `VLM_SHADOW_CONCURRENCY_OK`를 출력한다.

- [ ] **Step 4: rollback probe SQL을 작성한다**

`tests/sql/vlm_risk_consensus_shadow_probe.sql`은 transaction 안에서 다음 assertion을 모두
실행한다.

```sql
begin;
-- fixture job 4개와 동일 batch attempt 1을 삽입
select public.fn_insert_vlm_shadow_attempt_batch(:'valid_attempt_1'::jsonb);
-- 동일 payload 멱등
select public.fn_insert_vlm_shadow_attempt_batch(:'valid_attempt_1'::jsonb);
do $$ begin
  assert (select count(*) from public.clip_vlm_shadow_attempts) = 4;
  raise notice 'VLM_SHADOW_RUNTIME_OK';
end $$;

-- 같은 identity에서 action 하나를 바꾼 payload는 22023
do $$ begin
  begin
    perform public.fn_insert_vlm_shadow_attempt_batch(:'conflicting_duplicate'::jsonb);
    raise exception 'expected duplicate mismatch';
  exception when sqlstate '22023' then null;
  end;
  -- wrong clip/model/prompt, missing position, duplicate position, unknown reasoning key도 각각 22023
  raise notice 'VLM_SHADOW_INTEGRITY_OK';
end $$;

-- append-only 0A000과 role 권한 42501
do $$ begin
  begin
    update public.clip_vlm_shadow_attempts set status='failed';
    raise exception 'expected append-only blocker';
  exception when sqlstate '0A000' then null;
  end;
  raise notice 'VLM_SHADOW_SECURITY_OK';
end $$;
rollback;
```

실제 파일에서는 `psql` variable 대신 SQL 안에서 `jsonb_build_array/jsonb_build_object`로
fixture를 완성해 단독 실행 가능하게 한다. `anon`, `authenticated`, `service_role`을
`SET LOCAL ROLE`로 각각 검사하고 원래 role로 복귀한다.

- [ ] **Step 5: unit과 실제 DB probe를 실행한다**

Run:

```bash
uv run pytest -q tests/test_vlm_risk_consensus_shadow_runtime_probe.py
uv run python scripts/run_vlm_risk_consensus_shadow_probe.py
```

Expected:

```text
VLM_SHADOW_RUNTIME_OK
VLM_SHADOW_INTEGRITY_OK
VLM_SHADOW_CONCURRENCY_OK
VLM_SHADOW_SECURITY_OK
PROBE_RESIDUE=0
```

- [ ] **Step 6: Task 3을 커밋한다**

```bash
git add tests/sql/vlm_risk_consensus_shadow_prerequisites.sql \
  tests/sql/vlm_risk_consensus_shadow_probe.sql \
  scripts/run_vlm_risk_consensus_shadow_probe.py \
  tests/test_vlm_risk_consensus_shadow_runtime_probe.py
git commit -m "test: VLM shadow 원장 실 DB probe 추가"
```

### Task 4: 전체 검증과 구현 handoff 기록

**Files:**
- Modify: `specs/next-session.md`
- Modify: `.claude/donts-audit.md`
- Create: `docs/handoff-prompts/2026-07-27-vlm-risk-consensus-ledger-report.md`

**Interfaces:**
- Consumes: Tasks 1~3.
- Produces: nightly worker가 소비할 RPC 계약과 DB implementation SHA.

- [ ] **Step 1: 전체 회귀를 실행한다**

Run:

```bash
uv run pytest -q
uv run python scripts/run_vlm_risk_consensus_shadow_probe.py
git diff --check
```

Expected: 전체 pytest PASS, 네 DB marker, `PROBE_RESIDUE=0`, diff-check clean.

- [ ] **Step 2: 금지 필드와 production mutation을 정적 감사한다**

Run:

```bash
rg -n "reasoning|r2_key|signed_url|frame_path|email" \
  migrations/2026-07-27_vlm_risk_consensus_shadow.sql
git diff origin/main -- migrations tests scripts
```

Expected: 첫 명령 0 match. 두 번째 diff에 기존 migration 수정, production connection,
모델/R2/app/web 코드가 없다.

- [ ] **Step 3: 상태 문서와 보고서를 additive로 기록한다**

보고서에는 정확히 다음을 포함한다.

```markdown
# VLM risk consensus ledger implementation report

## Verdict
VLM_RISK_CONSENSUS_LEDGER_READY_FOR_DEPLOY_REVIEW

## Contract
- RPC: fn_insert_vlm_shadow_attempt_batch(jsonb) returns integer
- Protocol: risk-consensus-shadow-v1
- RLS/client policy: enabled/0
- Writer: service_role only
- Production applied: false

## Evidence
- pytest 명령과 실제 stdout을 이 절에 그대로 기록
- DB markers: VLM_SHADOW_RUNTIME_OK / VLM_SHADOW_INTEGRITY_OK /
  VLM_SHADOW_CONCURRENCY_OK / VLM_SHADOW_SECURITY_OK / PROBE_RESIDUE=0
- forbidden raw fields: 0

## Non-actions
production migration apply, VLM inference, R2 write, app/web/GT/behavior mutation = 0
```

- [ ] **Step 4: 문서와 보고서를 커밋하고 push한다**

```bash
git add specs/next-session.md .claude/donts-audit.md \
  docs/handoff-prompts/2026-07-27-vlm-risk-consensus-ledger-report.md
git commit -m "docs: VLM shadow 원장 구현 증거 기록"
git push -u origin codex/vlm-risk-consensus-ledger
```

Expected: local HEAD equals upstream, tracked tree clean. Production migration은 적용하지 않는다.
