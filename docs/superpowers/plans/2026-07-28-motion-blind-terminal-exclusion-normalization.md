# Motion Blind Terminal Exclusion Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 교차검수 live 큐와 workspace 집계에서 `quarantined`·`media_deleted` 영상을 제외해 재생 가능한 작업만 노출한다.

**Architecture:** 기존 `motion_clip_review_slots`·`motion_clip_consensus`·삭제 감사 원장은 보존한다. 첫 forward migration이 `fn_list_motion_blind_queue`와 `fn_get_motion_blind_workspace`의 모든 경로에 terminal-exclusion 술어를 적용한다. 두 번째 forward migration은 B그룹 배정 카메라 `P4 Cam 2(dev)`·`P4 Cam 3`에만 50초 최소 길이를 추가하고 다른 카메라는 길이로 제외하지 않는다.

**Tech Stack:** PostgreSQL 15, PL/pgSQL, pytest, disposable local PostgreSQL probe

## Global Constraints

- 기존 slot·consensus·submission·system exclusion row를 UPDATE/DELETE하지 않는다.
- `candidate`·`restored`·`deletion_blocked`는 기존처럼 작업 대상에 남긴다.
- `quarantined`·`media_deleted`만 큐·날짜·진행 집계에서 제외한다.
- 50초 최소 길이는 B그룹 배정 카메라 2대에만 적용하고 다른 카메라는 건드리지 않는다.
- migration은 forward-only이고 함수 권한은 service_role 전용을 유지한다.
- production 적용 전 정적 테스트와 disposable PostgreSQL runtime probe를 통과한다.
- 사용자 승인 없는 git commit은 만들지 않는다.

---

### Task 1: 회귀 계약을 RED로 고정

**Files:**
- Create: `tests/test_motion_blind_terminal_exclusion_normalization_migration.py`
- Modify: `tests/sql/short_clip_device_error_retention_probe.sql`
- Modify: `scripts/run_short_clip_retention_probe.py`

**Interfaces:**
- Consumes: `fn_list_motion_blind_queue(uuid,date,text,uuid,timestamptz,uuid,integer)`, `fn_get_motion_blind_workspace(uuid)`
- Produces: terminal exclusion이 blind queue와 workspace에 포함되지 않는 정적·실 DB 회귀 계약

- [x] migration 파일 경로와 두 함수 교체, terminal-exclusion 술어, service-role grant를 요구하는 정적 테스트를 작성한다.
- [x] 기존 slot 생성 뒤 `media_deleted`가 된 clip과 정상 clip을 함께 두는 SQL probe assertion을 추가한다.
- [x] probe runner 적용 순서에 새 migration 경로를 추가한다.
- [x] `uv run pytest tests/test_motion_blind_terminal_exclusion_normalization_migration.py -q`를 실행해 migration 부재로 실패하는지 확인한다.

### Task 2: 최소 forward migration 구현

**Files:**
- Create: `migrations/2026-07-28_motion_blind_terminal_exclusion_normalization.sql`

**Interfaces:**
- Produces: 기존 시그니처를 유지하는 `fn_list_motion_blind_queue`, `fn_get_motion_blind_workspace`

- [x] 최신 production 함수 본문을 기준으로 두 함수를 `CREATE OR REPLACE`한다.
- [x] queue의 미제출 slot WHERE에 `NOT EXISTS (... state IN ('quarantined','media_deleted'))`를 추가한다.
- [x] workspace의 progress 후진, priority, available days, clip/submit/late-added 집계에 같은 술어를 적용한다.
- [x] `REVOKE ... FROM PUBLIC, anon, authenticated`와 `GRANT EXECUTE ... TO service_role`을 재선언한다.
- [x] 정적 테스트를 다시 실행해 GREEN을 확인한다.

### Task 2.1: B그룹 카메라 최소 길이 forward migration

**Files:**
- Create: `migrations/2026-07-28_motion_blind_minimum_duration_normalization.sql`
- Create: `tests/test_motion_blind_minimum_duration_normalization_migration.py`

- [x] RED 계약으로 50초 기준, B그룹 카메라 2대 scope, 다른 카메라 보존을 고정한다.
- [x] 공용 eligibility helper를 추가하고 queue·workspace 전 경로에서 사용한다.
- [x] disposable PostgreSQL에서 B그룹 카메라 12초 제외·60초 포함·다른 카메라 12초 보존을 확인한다.

### Task 3: 런타임·회귀 검증

**Files:**
- Verify: `tests/sql/short_clip_device_error_retention_probe.sql`
- Verify: `scripts/run_short_clip_retention_probe.py`

- [x] 실제 disposable PostgreSQL probe로 함수 동작을 검증한다.
- [x] 관련 Python migration tests와 web blind API tests를 실행한다.
- [x] `git diff --check`와 변경 파일 diff를 검토한다.

### Task 4: Production 적용과 B그룹 검증

**Files:**
- Apply: `migrations/2026-07-28_motion_blind_terminal_exclusion_normalization.sql`

- [x] production에 terminal exclusion migration과 B그룹 카메라 최소 길이 migration을 순서대로 적용한다.
- [x] B그룹 2026-07-21 큐에서 terminal exclusion 281건이 사라졌는지 확인한다.
- [x] 두 reviewer 모두 `media_deleted` 0건, 50초 이상 재생 가능 영상 12건을 조회하는지 확인한다.
- [x] 각 reviewer의 원본 slot 294건이 보존되고, 다른 카메라의 50초 미만 영상은 허용되는지 확인한다.
