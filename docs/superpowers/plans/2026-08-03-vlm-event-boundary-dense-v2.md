# VLM Event Boundary Dense v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 잘못된 전체구간 4+4 프레임 시험을 폐기하고, 같은 74개 owner-final 경계를 A 끝 6장+B 시작 6장으로 GPT 3개와 local VLM 2개에 전부 재시험해.

**Architecture:** 기존 private 영상·owner-final pair identity·사람 정답은 그대로 고정하고 프레임 표현만 교체해. 두 장의 3x2 contact sheet를 모델에 전달하며, 모델 실행 ledger에는 사람 정답을 넣지 않고 모든 호출 뒤 독립 scorer가 join해.

**Tech Stack:** Python 3.12, OpenCV, Codex CLI ChatGPT subscription, Ollama, pytest

## Global Constraints

- 표본은 owner-final development 경계 74개(`same=57`, `different=17`) 그대로야.
- A는 종료 전 `6,4,2,1,0.5,0.1초`, B는 시작 후 `0.1,0.5,1,2,4,6초`를 시간순으로 봐.
- 각 영상은 별도 3x2 JPEG로 만들어 한 프레임의 해상도를 기존 combined 4x2보다 높게 유지해.
- 모델은 사람 정답·clip id·행동 label·DB·R2·reviewer 정보를 보지 않아.
- GPT는 Mini/Luna/Terra, local은 MiniCPM/Qwen을 모두 측정해.
- retry 0, score gate는 schema 74/74 + over-merge 0 + same 정답 29/57 이상이야.
- production DB/R2/GT/event/skip/service/UI는 수정하지 않아.
- 기존 4+4 결과는 이력으로 보존하지만 모델 채택 근거로 사용하지 않아.
- 커밋은 사용자 명시 승인 없이는 만들지 않아.

---

### Task 1: Boundary-dense input contract

**Files:**
- Create: `scripts/vlm_event_boundary_dense.py`
- Create: `tests/test_vlm_event_boundary_dense.py`

**Interfaces:**
- Consumes: A/B mp4와 pair별 gap seconds
- Produces: `boundary_frame_indices()`, `extract_boundary_frames()`, `build_boundary_sheets()`

- [x] **Step 1:** 6+6 초 단위 sampling과 2장 layout의 failing tests를 작성해.
- [x] **Step 2:** `uv run pytest tests/test_vlm_event_boundary_dense.py -x -q`가 missing module로 실패하는 걸 확인해.
- [x] **Step 3:** OpenCV seek/release와 timestamp 비가림 header를 최소 구현해.
- [x] **Step 4:** focused test 4개 통과를 확인해.

### Task 2: Frozen input preparation

**Files:**
- Create: `scripts/prepare_openai_subscription_vlm_event_boundary_dense.py`
- Create: `tests/test_prepare_openai_subscription_vlm_event_boundary_dense.py`

**Interfaces:**
- Consumes: 기존 frozen media 78개, source manifest, owner-final mapping
- Produces: dense JPEG 148장과 `frozen-manifest.json`

- [x] **Step 1:** clip token/hash와 gap mapping의 failing tests를 작성해.
- [x] **Step 2:** missing module failure를 확인해.
- [x] **Step 3:** source media hash 78/78, pair identity 74/74를 fail-closed하는 prep을 구현해.
- [x] **Step 4:** Mac mini private root에서 입력을 생성하고 exact manifest SHA를 동결해.

### Task 3: Five-model measured rerun

**Files:**
- Modify: `scripts/run_openai_subscription_vlm_event_boundary.py`
- Modify: `scripts/recompute_openai_subscription_vlm_event_boundary.py`
- Create: `scripts/run_local_vlm_event_boundary_dense.py`
- Create: `tests/test_run_local_vlm_event_boundary_dense.py`
- Create: `experiments/vlm-event-boundary-dense-v2/TEST-SHEET.md`

**Interfaces:**
- Consumes: Task 2 frozen dense inputs
- Produces: GPT 222건 + local 148건 GT-free ledgers와 summary

- [x] **Step 1:** multi-image CLI와 dense independent recompute failing tests를 작성해.
- [x] **Step 2:** legacy 1-image 계약을 보존하며 dense 2-image 계약을 구현해.
- [x] **Step 3:** local deterministic payload의 failing test와 runner를 구현해.
- [x] **Step 4:** TEST-SHEET를 hash 동결하고 Claude plan review P0/P1=0을 확인해.
- [x] **Step 5:** Mac mini에서 5개 모델을 retry 0으로 직렬 실행해.

### Task 4: Independent scoring and report

**Files:**
- Create: `experiments/vlm-event-boundary-dense-v2/REPORT.md`
- Modify: `experiments/INDEX.md`
- Modify: `specs/next-session.md`
- Modify: `docs/decision-gate.md`
- Modify: `.claude/donts-audit.md`

**Interfaces:**
- Consumes: measured ledgers, source manifest, legacy report
- Produces: dense-v2 성적표·paired 변화·제품 판단

- [x] **Step 1:** runner-import-free GPT recompute와 별도 local recompute로 score/hash를 대조해.
- [x] **Step 2:** 모델별 over-merge/over-split/uncertain/latency와 legacy 대비 변화를 보고서에 기록해.
- [x] **Step 3:** Claude 결과 리뷰 P0/P1=0과 focused/full test, py_compile, diff-check를 실행해.
- [x] **Step 4:** Slack에 검증된 결론을 공유하고 사용자에게 최종 보고해.
