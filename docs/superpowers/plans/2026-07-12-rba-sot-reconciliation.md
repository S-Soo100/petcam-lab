# RBA SOT Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** petcam-lab의 제품 목표, RBA/VLM 역할, router 연구 판정, 다음 실행 계획을 최신 결정으로 통일한다.

**Architecture:** 북극성 → RBA 전략 → 최신 연구 판정/시험지 → next-session → 진입 문서 순서의 SOT 계층을 적용한다. 과거 보고서는 보존하고 활성 요약 문서만 최신 판정을 가리키게 한다.

**Tech Stack:** Markdown, Git, Python 3.12/pytest, Next.js TypeScript

## Global Constraints

- 과거 실험 report와 append-only 감사 기록은 소급 수정하지 않는다.
- Gemini 2.5 Flash/v3.5는 historical baseline으로만 표현한다.
- local router는 production 채택 근거가 아니며 metadata/review 인프라만 유지한다.
- P0 30건은 pilot, 최소 150건은 adoption 판단 목표로 구분한다.
- 코드·DB·worker 동작은 변경하지 않는다.

---

### Task 1: 최상위 목표와 RBA 전략 정합화

**Files:**
- Modify: `docs/petcam-north-star.md`
- Modify: `docs/AI-VIDEO-ANALYSIS-STRATEGY.md`

**Interfaces:**
- Consumes: `reports/router-research-validity-audit-20260712/REPORT.md`의 최신 판정
- Produces: 하위 진입 문서가 요약할 제품 목표와 Track A/B의 현재 정의

- [x] **Step 1:** 북극성 상태를 확정으로 바꾸고 2026-07-12 실행 원칙을 추가한다.
- [x] **Step 2:** Track A 표에서 현재 모델 미확정, Gemini historical, Track B 품질 연구를 명시한다.
- [x] **Step 3:** Evidence-First와 local router 섹션에 유효성 감사 이후의 채택/중단 경계를 반영한다.
- [x] **Step 4:** Phase 1의 v3.5 production 고정 문구를 frozen API baseline 선정으로 교체한다.

### Task 2: 실행 진입점과 인덱스 정합화

**Files:**
- Modify: `specs/next-session.md`
- Modify: `specs/README.md`
- Modify: `experiments/INDEX.md`
- Modify: `experiments/router-cost-v2/TEST-SHEET.md`

**Interfaces:**
- Consumes: Task 1의 최신 전략
- Produces: 다음 세션이 그대로 실행할 순서와 사전 등록 비용 계약

- [x] **Step 1:** `next-session.md` 최상단에 2026-07-12 결정 블록을 추가해 이전 7월 10일 착수점을 supersede한다.
- [x] **Step 2:** 기존 72/203/v1/v1.1 데이터는 EDA 전용이고 다음 작업은 baseline 계약 동결임을 명시한다.
- [x] **Step 3:** specs 인덱스의 v3.5 항목을 historical로 바꾸고 `router-cost-v2` 실행 전 상태를 등록한다.
- [x] **Step 4:** 시험지에서 30 P0 pilot과 150 P0 adoption을 구분하고 비용 tracker, retry, prompt caching 계약을 추가한다.

### Task 3: 사용자·에이전트 진입 문서 정합화

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/FEATURES.md`
- Modify: `docs/GLOSSARY.md`

**Interfaces:**
- Consumes: Task 1~2의 SOT
- Produces: 사람과 에이전트가 처음 읽는 일관된 프로젝트 요약

- [x] **Step 1:** README의 Track A와 로드맵을 현재 모델 미확정·baseline 계약 대기로 바꾼다.
- [x] **Step 2:** AGENTS와 CLAUDE의 Track A 정의를 역할 중심으로 바꾸고 테스트 수를 최신화한다.
- [x] **Step 3:** FEATURES와 GLOSSARY의 Gemini production 표현을 historical baseline으로 교체한다.
- [x] **Step 4:** 모든 진입 문서에서 최신 감사와 시험지 링크가 도달 가능한지 확인한다.

### Task 4: 정합성·회귀 검증과 반영

**Files:**
- Verify: all modified Markdown files

**Interfaces:**
- Consumes: Task 1~3의 문서 변경
- Produces: clean main commit and synchronized origin/main

- [x] **Step 1:** `rg`로 금지된 활성 표현과 placeholder를 검사한다.
- [x] **Step 2:** 로컬 Markdown 링크 대상이 존재하는지 검사한다.
- [x] **Step 3:** `git diff --check`를 실행해 공백 오류가 없음을 확인한다.
- [x] **Step 4:** `uv run pytest`를 실행해 334개 전체 테스트가 통과하는지 확인한다.
- [x] **Step 5:** `cd web && npx tsc --noEmit`을 실행해 TypeScript 오류가 없음을 확인한다.
- [x] **Step 6:** 문서 변경을 논리적 커밋으로 만들고 `main`을 push한다.
- [x] **Step 7:** `git status --short --branch`와 `git rev-list --left-right --count origin/main...main`이 clean, `0 0`인지 확인한다.
