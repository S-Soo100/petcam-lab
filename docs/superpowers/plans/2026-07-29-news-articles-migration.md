# terra ai News 공개 읽기 Migration 실행 계획

## Task 1 — 시작 계약

- design/plan을 clean commit으로 고정한다.
- untracked handoff manifest로 `HANDOFF_OK`를 확인한다.

## Task 2 — TDD migration 구현

- migration 부재를 실패로 고정하는 정적 계약 테스트를 먼저 실행한다.
- `migrations/2026-07-29_news_articles.sql`을 fail-closed로 구현한다.
- RLS, GRANT/REVOKE, slug·발행 시각 제약, 기존 도메인 무변경을 테스트한다.

## Task 3 — DB runtime probe

- disposable local PostgreSQL에 필요한 Supabase role만 임시 생성한다.
- migration을 적용하고 published/draft/future row를 만든다.
- anon published-only, anon write 차단, authenticated published-only, service_role write를 검증한다.
- 임시 DB와 probe role을 제거하고 `PROBE_RESIDUE=0`을 확인한다.

## Task 4 — production 적용

- 적용 전 객체 부재와 기존 anon 권한 baseline을 읽기 전용으로 고정한다.
- migration을 atomic apply한다.
- transaction rollback probe로 공개·쓰기·기존 테이블 경계를 검증한다.
- 신규 advisor 오류와 probe 잔여 0을 확인한다.

## Task 5 — 기록과 R1 재시작

- `docs/DATABASE.md`에 applied=true와 최초 공개 읽기 테이블임을 기록한다.
- production 적용 보고서를 작성해 commit/push한다.
- Mac mini R1에 새 production baseline을 기록하고 24시간 검증을 다시 시작한다.
