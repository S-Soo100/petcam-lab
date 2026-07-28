# Gemini CLI 운영 폐기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MacBook과 Mac mini의 Gemini CLI 실행·인증·자동 호출 경로를 제거한다.

**Architecture:** machine package/credential, active policy, ideaBank executable fallback을 별도
경계로 제거한다. 역사 문서와 Gemini API는 보존하고, Mac mini는 P3 설치 전 fail-closed
게이트로 실행한다.

**Tech Stack:** npm global prefix, zsh/bash, Markdown policy, Python image backend registry, JSON.

## Global Constraints

- Gemini CLI만 폐기하고 Gemini API와 Codex CLI는 유지한다.
- 과거 보고서·감사·TIL은 수정하지 않는다.
- Mac mini에는 현재 세션에서 접속하지 않는다.
- production DB/R2/media/기존 service는 수정하지 않는다.

---

### Task 1: MacBook package·credential 제거

**Files:**
- Remove runtime package: `/opt/homebrew/lib/node_modules/@google/gemini-cli`
- Remove runtime credential root: `/Users/baek/.gemini`

**Interfaces:**
- Consumes: explicit Owner retirement approval.
- Produces: no `gemini` executable and no local Gemini CLI credential.

- [ ] 전역 npm package owner/version을 기록한다.
- [ ] `/opt/homebrew/bin/npm uninstall -g @google/gemini-cli`로 package를 제거한다.
- [ ] `~/.gemini`만 삭제한다.
- [ ] `command -v gemini` 실패와 두 경로 부재를 확인한다.

### Task 2: active policy 수정

**Files:**
- Modify: `/Users/baek/AGENTS.md`
- Modify: `/Users/baek/.codex/AGENTS.md`
- Modify: `AGENTS.md`
- Modify: `specs/experiment-weak-model-levers.md`

**Interfaces:**
- Consumes: retired CLI state.
- Produces: agents cannot select or reinstall Gemini CLI.

- [ ] user-level policy는 Codex CLI만 허용하고 Gemini CLI 금지를 명시한다.
- [ ] project policy의 Gemini 진입점·외부 CLI 허용 문구를 폐기 상태로 바꾼다.
- [ ] active experiment chain에서 Gemini CLI를 제거한다.

### Task 3: ideaBank executable path 제거

**Files:**
- Remove: `tools/gemini-cli.sh`
- Remove: `tools/_gemini_auth_check.sh`
- Remove: `tools/gemini-summarize.sh`
- Remove: `tools/code-review.sh`
- Remove: `tools/consistency-check.sh`
- Remove: `tools/design-report.sh`
- Modify: `tools/_img_gen_backends.py`
- Modify: `tools/_img_gen.py`
- Modify: `tools/presets/default.json`
- Modify active status/rule/agent references.

**Interfaces:**
- Consumes: Gemini CLI prohibition.
- Produces: no executable wrapper or automatic Gemini CLI fallback; Gemini API remains.

- [ ] CLI backend class·registry·default priority를 제거한다.
- [ ] Gemini-dependent shell wrappers를 삭제한다.
- [ ] active docs/agents/status는 Codex·Claude workflow로 전환한다.
- [ ] historical audit/playbook/TIL references는 유지한다.

### Task 4: Mac mini P3 handoff gate

**Files:**
- Modify: `docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-p3-install-handoff.md`
- Modify: `docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-p3-preinstall-report.md`

**Interfaces:**
- Consumes: MacBook retirement evidence.
- Produces: Mac mini installation cannot begin while Gemini CLI/credential remains.

- [ ] inventory→package removal→credential removal→absence assertion을 설치 1번 전에 넣는다.
- [ ] Gemini API는 삭제 대상이 아님을 기록한다.
- [ ] 제거 실패 시 P3 installer를 실행하지 않는 stop condition을 추가한다.

### Task 5: 검증·기록

**Files:**
- Modify: `.claude/donts-audit.md`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: committed audit and clean pushed branches.

- [ ] active executable/policy grep에서 허용·호출 참조 0을 확인한다.
- [ ] ideaBank Python compile, JSON parse, bash syntax를 검증한다.
- [ ] petcam focused tests와 `git diff --check`를 실행한다.
- [ ] petcam과 ideaBank를 각각 명시 파일만 commit/push한다.
