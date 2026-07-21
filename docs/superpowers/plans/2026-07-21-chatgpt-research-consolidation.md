# ChatGPT Research Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude가 수행한 유효 연구 이력을 보존하면서 ChatGPT가 관리하는 하나의 논리 연구선으로 통합한다.

**Architecture:** `petcam-nightly-reporter`에서 최신 Python Evidence main과 분기된 P1 연구를 merge commit으로 합친다. `petcam-lab`은 레포별 정확한 SHA와 활성 판정을 관리하는 단일 연구 manifest를 제공한다.

**Tech Stack:** Git worktree, Markdown SOT, Python/pytest

## Global Constraints

- 활성 논리 브랜치명은 두 변경 레포 모두 `codex/research-consolidation-20260721`이다.
- 기존 커밋을 squash/rebase/force-push하지 않는다.
- 기존 Claude 브랜치와 dirty checkout을 수정·삭제하지 않는다.
- production DB, LaunchAgent, VLM, Slack, 배포 상태를 변경하지 않는다.
- nightly 테스트는 최신 Gate temporal evidence 소스가 import되도록 검증 경로를 명시한다.

---

### Task 1: 기준선과 branch 포함관계 동결

**Files:**
- Modify: `docs/research/ACTIVE-RESEARCH.md`

**Interfaces:**
- Consumes: 각 레포의 `origin/main`, `origin/feat/vlm-basking-classification`
- Produces: 레포별 40자리 SHA와 branch 포함관계 표

- [ ] **Step 1: 각 레포 remote를 fetch하고 SHA를 기록한다**

Run:

```bash
git fetch --prune origin
git rev-parse origin/main
```

Expected: 각 명령이 40자리 SHA를 출력한다.

- [ ] **Step 2: 이미 main에 포함된 브랜치를 확인한다**

Run:

```bash
git merge-base --is-ancestor <branch> origin/main
```

Expected: nightly P1 branch만 nonzero, 나머지 관련 branch는 exit 0.

### Task 2: nightly 분기 연구 통합

**Files:**
- Modify: `reporter/config.py`
- Modify: `specs/next-session.md`
- Preserve: `experiments/label-determinism-remeasure/**`
- Preserve: `reporter/python_evidence_*.py`

**Interfaces:**
- Consumes: `origin/main`, `origin/feat/vlm-basking-classification`
- Produces: 양쪽 commit을 모두 조상으로 갖는 merge commit

- [ ] **Step 1: merge를 실행한다**

```bash
git merge --no-ff origin/feat/vlm-basking-classification
```

Expected: `reporter/config.py`, `specs/next-session.md` 충돌 가능. 그 밖의 파일은 자동 병합.

- [ ] **Step 2: config 충돌을 양쪽 설정 보존으로 해결한다**

검증:

```bash
rg 'PYTHON_EVIDENCE|ANTHROPIC|VLM_' reporter/config.py
```

Expected: Python Evidence와 P1 관련 설정이 모두 존재하고 conflict marker는 0건.

- [ ] **Step 3: next-session 충돌을 additive history로 해결한다**

검증:

```bash
rg 'P1|Python Evidence|SUPERSEDED' specs/next-session.md
```

Expected: 현재 운영 정본과 P1 결과가 모두 남고 conflict marker는 0건.

- [ ] **Step 4: nightly 전체 테스트를 실행한다**

```bash
PYTHONPATH=/Users/baek/myPythonProjects/gecko-vision-gate/.claude/worktrees/python-evidence-universal/src uv run pytest -q
```

Expected: 0 failures.

- [ ] **Step 5: merge commit을 완료한다**

```bash
git add reporter/config.py specs/next-session.md
git commit
```

Expected: merge commit 1개, parent 2개.

### Task 3: ChatGPT 연구 정본 작성

**Files:**
- Create: `docs/research/ACTIVE-RESEARCH.md`
- Modify: `AGENTS.md`
- Modify: `specs/next-session.md`
- Modify: `docs/handoff-prompts/2026-07-21-codex-takeover.md`
- Modify: `.claude/donts-audit.md`

**Interfaces:**
- Consumes: Task 2 nightly merge SHA와 각 레포 main SHA
- Produces: 모든 연구 agent가 읽는 단일 활성 정본

- [ ] **Step 1: 역할 경계를 기록한다**

`ACTIVE-RESEARCH.md`에 ChatGPT=plan/decision/review/SOT, Claude=implementation/experiment/report, owner=approval/domain GT로 명시한다.

- [ ] **Step 2: 활성 판정과 작업 큐를 이전한다**

P1 adopt(운영 배선 보류), P2 hold, T0/T1 reject, W1→W2→W3 순서를 기록한다.

- [ ] **Step 3: takeover 문서를 historical handoff로 봉인한다**

작성 commit을 `5f50242f0971275dd98da9e32b9df85605d15419`로 고치고 활성 정본 링크를 추가한다.

- [ ] **Step 4: 문서 정합성을 검사한다**

```bash
rg 'ChatGPT|ACTIVE-RESEARCH|5f50242f0971275dd98da9e32b9df85605d15419' AGENTS.md specs/next-session.md docs/research/ACTIVE-RESEARCH.md docs/handoff-prompts/2026-07-21-codex-takeover.md
rg -n '<<<<<<<|=======|>>>>>>>' AGENTS.md specs/next-session.md docs
```

Expected: 필수 문자열 존재, conflict marker 0건.

### Task 4: 교차 레포 검증과 push

**Files:**
- Verify only: all changed files

**Interfaces:**
- Consumes: Task 2~3 결과
- Produces: 원격에서 재현 가능한 두 integration branch

- [ ] **Step 1: lab 전체 테스트를 실행한다**

```bash
uv run pytest -q
```

Expected: 0 failures.

- [ ] **Step 2: 양쪽 diff와 branch ancestry를 확인한다**

```bash
git diff --check
git status --short --branch
```

Nightly 추가 검증:

```bash
git merge-base --is-ancestor origin/main HEAD
git merge-base --is-ancestor origin/feat/vlm-basking-classification HEAD
```

Expected: 전부 exit 0.

- [ ] **Step 3: lab 문서를 commit한다**

```bash
git add AGENTS.md specs/next-session.md docs/research/ACTIVE-RESEARCH.md docs/handoff-prompts/2026-07-21-codex-takeover.md docs/superpowers/specs/2026-07-21-chatgpt-research-consolidation-design.md docs/superpowers/plans/2026-07-21-chatgpt-research-consolidation.md .claude/donts-audit.md
git commit -m "docs: ChatGPT 연구 정본과 Claude 연구 통합선 확정"
```

- [ ] **Step 4: 두 브랜치를 push한다**

```bash
git push -u origin codex/research-consolidation-20260721
```

Expected: 두 레포 모두 local HEAD == remote branch HEAD.

- [ ] **Step 5: 기존 checkout이 보존됐는지 확인한다**

원래 checkout에서 `git status --short --branch`를 다시 실행해 사전 감사와 동일한 사용자 변경이 남아 있는지 확인한다.
