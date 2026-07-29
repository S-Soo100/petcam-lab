# News comments/admin migration implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 익명 댓글과 뉴스 전용 관리자 발행을 table-write 없이 RPC 경계로 배포한다.

**Architecture:** `news_admins`와 `news_comments`를 기존 `news_articles` 옆에 독립 추가하고,
RLS와 SECURITY DEFINER RPC로 공개 읽기·익명 제출·관리자 쓰기를 분리한다. Storage는
`news-media` bucket과 관리자 전용 쓰기 정책을 같은 forward migration에 포함한다.

**Tech Stack:** PostgreSQL 15, Supabase Auth/RLS/Storage, PostgREST RPC, pytest

## Global Constraints

- 기존 `migrations/2026-07-29_news_articles.sql`은 수정하지 않는다.
- anon/authenticated 테이블 INSERT·UPDATE·DELETE grant는 0이다.
- 기존 영상·라벨·GT·RBA·blind·R2/media 데이터는 변경하지 않는다.
- production 적용 직전 현재 R1 측정창을 planned external DB change로 종료한다.
- 적용 후 R1을 fresh baseline에서 0초부터 다시 시작한다.

---

### Task 1: 정적 migration 계약

**Files:**
- Create: `tests/test_news_comments_admin_migration.py`
- Create: `migrations/2026-07-29_news_comments_admin.sql`

**Interfaces:**
- Consumes: `public.news_articles`, Supabase roles, `auth.uid()`
- Produces: `news_admins`, `news_comments`, helper/RPC 7종, Storage bucket/policy 4종

- [x] **Step 1: Write failing static contract tests**

원자성, collision fail-closed, RLS/grant, search_path, advisory lock, Storage update
`WITH CHECK`, 기존 도메인 무변경을 각각 독립 테스트로 작성한다.

- [x] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_news_comments_admin_migration.py`

Expected: migration file missing으로 실패.

- [x] **Step 3: Implement minimal migration**

요청서 SQL을 기반으로 design의 동시성·헤더 parse·Storage 정책 하드닝만 추가한다.

- [x] **Step 4: Verify GREEN**

Run: `uv run pytest -q tests/test_news_comments_admin_migration.py`

Expected: all pass.

### Task 2: Disposable PostgreSQL runtime probe

**Files:**
- Create: `scripts/run_news_comments_admin_probe.py`
- Create: `tests/test_news_comments_admin_runtime_probe.py`

**Interfaces:**
- Consumes: Task 1 migration
- Produces: `NEWS_COMMENTS_RUNTIME_OK`, `NEWS_ADMIN_RLS_OK`,
  `NEWS_COMMENT_RATE_LIMIT_OK`, `NEWS_STORAGE_POLICY_OK`, `PROBE_RESIDUE=0`

- [x] **Step 1: Write failing runner contract test**

runner가 없어서 실패하고, marker·cleanup 계약을 고정한다.

- [x] **Step 2: Verify RED**

Run: `uv run pytest -q tests/test_news_comments_admin_runtime_probe.py`

Expected: runner missing.

- [x] **Step 3: Implement disposable DB runner**

무작위 `news_admin_probe_<hex>` DB만 만들고 role/auth/storage 최소 fixture를 만든다.
정상·적대 시나리오를 실행하고 `finally`에서 DB와 새 역할만 제거한다.

- [x] **Step 4: Verify GREEN and full regression**

Run:

```bash
uv run pytest -q tests/test_news_comments_admin_runtime_probe.py
uv run pytest -q
git diff --check
```

Expected: focused/full all pass, residue 0.

### Task 3: Production apply and probe

**Files:**
- Modify: `docs/DATABASE.md`
- Modify: `.claude/donts-audit.md`
- Create: `docs/handoff-prompts/2026-07-29-news-comments-admin-migration-report.md`

**Interfaces:**
- Consumes: committed migration SHA and local probe evidence
- Produces: Supabase migration history, public REST evidence, additive R1 handoff

- [x] **Step 1: End current R1 window**

Mac mini task에 `SUPERSEDED_PLANNED_EXTERNAL_DB_CHANGE` 종료를 지시하고 automation을
중복 없이 제거한다. service는 유지한다.

- [x] **Step 2: Apply production migration**

precheck로 객체 부재와 선행 `news_articles` 계약을 확인한 뒤 tracked SQL을 atomic
migration으로 적용한다.

- [x] **Step 3: Run rollback/catalog/REST probes**

설계의 성공 조건 10개를 확인하고 모든 probe row를 정리한다. 관리자 계정은 임의 등록하지
않고 `registered=false`로 보고한다.

- [ ] **Step 4: Document, test, commit, FF-only main**

전체 테스트와 diff-check 후 feature branch를 push하고 origin/main에 force 없이
fast-forward한다.

- [ ] **Step 5: Restart R1**

적용 완료 보고서를 attestation으로 사용해 Mac mini에서 새 baseline과 24시간 창을
0초부터 시작하고 시작 증거를 보고서에 additive 기록한다.
