# Router Operational v0 Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실제 `clip_router_features` 운영 데이터를 읽어 VLM 호출 전 우선순위 라우터 v0 성적서를 만든다.

**Architecture:** 기존 `local_router_v0`의 dataset-203 연구는 유지하고, 새 스크립트는 Supabase feature-store를 읽는 read-only operational report로 분리한다. 출력은 `cloud_now`, `cloud_later`, `activity_only`, `review_candidate` 분포와 위험 신호를 보고서로 남기며, DB/R2/LLM/VLM 쓰기나 호출은 하지 않는다.

**Tech Stack:** Python 3.12, Supabase Python client, pytest, CSV/JSONL/Markdown reports.

## Global Constraints

- `skip`, `auto_moving`, `auto_p0`는 금지한다.
- v0는 행동 판정기가 아니라 cloud VLM 우선순위 라우터다.
- DB writes `0`, R2 writes `0`, LLM/VLM calls `0`.
- 보고서 입력은 `clip_router_features`의 OpenCV/운영 metadata만 사용한다.
- 기존 Claude subscription 연구와 분리한다. 영상/frame/contact sheet를 보지 않는다.

---

### Task 1: Pure Rule API

**Files:**
- Create: `scripts/router_operational_v0_report.py`
- Test: `tests/test_router_operational_v0_report.py`

**Interfaces:**
- Produces: `route_operational_feature(row: dict[str, Any]) -> OperationalRouterDecision`
- Produces: `OperationalRouterDecision(route, priority, risk, reason)`

- [x] Write failing tests for allowed routes, low activity route, high motion route, and failed-status route.
- [x] Run tests and verify module import fails before implementation.
- [x] Implement minimal pure routing code.
- [x] Run tests and verify pass.

### Task 2: Summary And Report API

**Files:**
- Modify: `scripts/router_operational_v0_report.py`
- Test: `tests/test_router_operational_v0_report.py`

**Interfaces:**
- Produces: `summarize_decisions(decisions) -> dict[str, Any]`
- Produces: `write_report(rows, decisions, summary, out_dir) -> None`

- [x] Write tests for summary counts and report file creation.
- [x] Run tests and verify failure.
- [x] Implement JSON/CSV/Markdown output.
- [x] Run tests and verify pass.

### Task 3: Read-Only Supabase Run

**Files:**
- Modify: `scripts/router_operational_v0_report.py`
- Create: `reports/router-operational-v0-20260710/`

**Interfaces:**
- Produces CLI:
  - `uv run python scripts/router_operational_v0_report.py --out-dir reports/router-operational-v0-20260710`

- [x] Query `clip_router_features` read-only.
- [x] Apply pure router to rows.
- [x] Write report artifacts.
- [x] Verify output says DB/R2/LLM/VLM writes/calls are all zero.

### Task 4: Evaluation Notes

**Files:**
- Modify: `specs/experiment-local-router-without-detector.md`
- Modify: `docs/superpowers/plans/2026-07-10-router-operational-v0-report.md`

- [x] Record final decision from report.
- [x] Keep this as operational-data v0, not dataset-203 model-quality research.

Final result:

- Report: `reports/router-operational-v0-20260710/REPORT.md`
- Decision subtype: `hold-feature-reliability-low`
- Rows: `1358`
- `cloud_now`: `308` / `22.7%`
- `review_candidate`: `1036` / `76.3%`
- `cloud_later`: `14` / `1.0%`
- `activity_only`: `0` / `0.0%`
- Estimated immediate VLM reduction: `77.3%`
- Interpretation: reduction signal exists, but high `review_candidate` rate means reliability/debugging must precede recall guard and local LLM escalation.
