# GME Slow Motion v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 느린 게코 이동을 판정하고 v0와 섞이지 않는 append-only v1 운영 계약으로 배포한다.

**Architecture:** Gate는 3초 중심창 순이동으로 static frame을 moving으로 승격한다. DB·worker·웹은 engine/algorithm/detector의 exact contract를 사용하고 v1 canary 뒤에만 active algorithm을 전환한다.

**Tech Stack:** Python 3.12, OpenCV, PostgreSQL/Supabase, Next.js/TypeScript, Vercel, launchd

**Spec:** `docs/superpowers/specs/2026-09-03-gme-slow-motion-v1-design.md`

## Global Constraints

- 기존 `gme-motion-v0` job/run/artifact와 사람 GT, 원본 영상은 수정·삭제하지 않는다.
- 새 결과는 `gme-motion-v1` append-only 원장으로만 저장한다.
- canary가 실패하면 live/web 전환과 historical enqueue를 수행하지 않는다.

---

### Task 1: Gate 느린 이동 판정

**Files:**
- Modify: `gecko-vision-gate/src/gecko_vision_gate/gme_motion.py`
- Modify: `gecko-vision-gate/src/gecko_vision_gate/gme_engine.py`
- Modify: `gecko-vision-gate/src/gecko_vision_gate/gme_contracts.py`
- Test: `gecko-vision-gate/tests/test_gme_motion.py`

- [x] 느린 선형 이동과 정지 jitter 실패 테스트를 먼저 실행한다.
- [x] 3초 중심창 판정과 `gme-motion-v1` provenance를 구현한다.
- [x] Gate 전체 테스트와 문제 영상 artifact replay를 실행한다.

### Task 2: Worker exact contract

**Files:**
- Modify: `reporter/gme_store.py`
- Modify: `reporter/gme_worker.py`
- Modify: `scripts/enqueue_gme_backfill.py`
- Test: `tests/test_gme_store.py`, `tests/test_gme_worker.py`, `tests/test_enqueue_gme_backfill.py`

- [ ] algorithm이 다른 job을 claim·저장하지 않는 실패 테스트를 작성한다.
- [ ] claim/enqueue/runtime provenance를 `gme-motion-v1` exact contract로 구현한다.
- [ ] worker 관련 회귀 테스트를 실행한다.

### Task 3: DB와 웹 exact read contract

**Files:**
- Create: `migrations/2026-09-03_gme_slow_motion_v1.sql`
- Modify: `web/src/lib/gmeOverlayServer.ts`
- Modify: `web/src/lib/labelingV3Server.ts`
- Modify: 관련 route와 테스트

- [ ] algorithm 분리 조회가 없는 현재 동작을 실패 테스트로 고정한다.
- [ ] 신규 claim/read RPC와 live v1 trigger migration을 작성한다.
- [ ] 웹 overlay·관측 시간 조회를 active algorithm에 묶고 회귀 테스트를 실행한다.

### Task 4: 순차 배포와 canary

**Files:**
- Modify: 각 저장소의 배포 증거 문서

- [ ] 세 저장소 테스트·타입검사·diff 검사를 완료하고 커밋·푸시한다.
- [ ] DB 읽기 계약과 v0 호환 웹을 먼저 배포한다.
- [ ] Mac mini worker를 v1 exact claim으로 전환하고 문제 영상·정지 음성 canary를 실행한다.
- [ ] canary 통과 뒤 live trigger·웹 active algorithm을 v1으로 전환한다.
- [ ] 신규·기존 영상 v1 queue 상태와 금지된 부수 변경 0을 확인한다.
