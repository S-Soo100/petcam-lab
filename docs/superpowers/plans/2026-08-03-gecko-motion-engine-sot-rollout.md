# Gecko Motion Engine SOT Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 확정된 Gecko Motion Engine 이름·활동시간 정의·Gate 연구 계약을 현재 SOT에 반영하고 MacBook과 Mac mini를 같은 commit으로 맞춘다.

**Architecture:** 기존 `Python Evidence` 역사 기록은 그대로 보존하고 현재 지시문만 GME로 전환한다. 이번 rollout은 문서·git 동기화만 수행하며 DB, runtime, Gate checkpoint, production service는 변경하지 않는다.

**Tech Stack:** Markdown SOT, Git, SSH read-only preflight + fast-forward sync, Slack-ready Markdown draft

## Global Constraints

- 사용자 대표 활동시간은 한 마리 이상 게코가 실제로 움직인 시간의 합집합이다.
- 내부에는 개체별 움직임 합인 gecko-seconds를 별도로 둔다.
- `unknown`은 `static` 또는 `not_visible`로 강등하지 않는다.
- Gecko Vision Gate는 계속 업그레이드하지만 자동 skip·행동 GT·삭제 근거로 쓰지 않는다.
- 현재 production `activity-v1`과 DB·R2·service·Flutter는 이번 작업에서 변경하지 않는다.
- 기존 dirty 파일은 되돌리거나 stash하지 않는다.

---

### Task 1: 현재 SOT에 GME 결정 반영

**Files:**
- Create: `docs/superpowers/specs/2026-08-03-gecko-motion-engine-v1-design.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `specs/next-session.md`
- Modify: `specs/feature-rba-data-engine-v1.md`
- Modify: `docs/AI-VIDEO-ANALYSIS-STRATEGY.md`
- Modify: `specs/README.md`
- Modify: `docs/decision-gate.md`
- Modify: `.claude/donts-audit.md`

**Interfaces:**
- Consumes: owner-approved GME name, five-state interval contract, any-gecko activity seconds.
- Produces: future agent가 같은 정의를 읽는 single SOT chain.

- [ ] **Step 1:** 최신 블록에 GME 결정과 기존 `activity-v1` 비대체 경계를 추가한다.
- [ ] **Step 2:** 현재 지시의 `Python media preparation only`를 GME 역할로 교정한다.
- [ ] **Step 3:** Gate v3를 detector+tracker 입력으로 확장하되 자동 skip 금지를 유지한다.
- [ ] **Step 4:** `rg`로 현재 문서의 모순과 링크 누락을 검사한다.

### Task 2: 정본 문서 검증·커밋·푸시

**Files:** Task 1의 명시 파일만 stage한다.

**Interfaces:**
- Consumes: 검증된 Markdown SOT.
- Produces: 40자리 commit SHA와 origin branch/main의 동일 commit.

- [ ] **Step 1:** `git diff --check`와 Markdown link target 검사를 실행한다.
- [ ] **Step 2:** stage 목록에 web·migration·DB cleanup 코드가 없는지 확인한다.
- [ ] **Step 3:** `docs: Gecko Motion Engine 연구 정본 확정`으로 커밋한다.
- [ ] **Step 4:** 현재 branch와 `main`을 non-force fast-forward push한다.

### Task 3: Mac mini SOT fast-forward 동기화

**Files:**
- Update by Git fast-forward: `/Users/baek-end/petcam-lab`

**Interfaces:**
- Consumes: origin/main의 Task 2 commit.
- Produces: Mac mini main HEAD가 같은 40자리 SHA인 검증 증거.

- [ ] **Step 1:** Mac mini 기존 dirty 경로가 incoming SOT 파일과 겹치지 않는지 확인한다.
- [ ] **Step 2:** `git fetch origin main` 후 `git merge --ff-only origin/main`한다.
- [ ] **Step 3:** fast-forward가 실패하면 즉시 중단·보고하고 reset·force·stash로 우회하지 않는다.
- [ ] **Step 4:** hostname, branch, HEAD, upstream, dirty 경로 보존을 다시 확인한다.

### Task 4: Slack 공유 초안 작성

**Files:** 없음. 사용자 보고에 Slack-ready text를 포함한다.

**Interfaces:**
- Consumes: 실제 commit SHA와 양 기기 검증 결과.
- Produces: 수동 검토·전송 가능한 Slack 초안.

- [ ] **Step 1:** 이름 변경, 활동시간 정의, Gate 역할, 현재 비변경 범위, 다음 연구를 짧게 정리한다.
- [ ] **Step 2:** 과거 Python Evidence 실패를 삭제로 오해하거나 production 전환을 완료했다고 과장하지 않는다.
- [ ] **Step 3:** 초안만 사용자에게 보고하고 Slack에는 전송하지 않는다.
