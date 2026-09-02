# OpenAI Subscription VLM Event Boundary v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mac mini의 ChatGPT 구독 Codex CLI에서 비용 후보 GPT 세 모델이 기존 local VLM과 동일한 74개 사건 경계 시험을 풀게 하고, 독립 채점 성적표를 남긴다.

**Architecture:** 기존 private `combined_4x2` 입력과 frozen manifest를 다시 생성하지 않고 exact SHA-256으로 검증한다. 모델마다 stateless Codex CLI 호출을 74회 실행하고 구조화 JSON을 private ledger에 기록한 뒤, 기존 `local_vlm_event_boundary` scorer로 집계한다.

**Tech Stack:** Python 3.12, uv, Codex CLI ChatGPT subscription auth, pytest, JSON Schema

## Global Constraints

- 모델은 `gpt-5.4-mini`, `gpt-5.6-luna`, `gpt-5.6-terra` 정확히 세 개다.
- 입력·prompt·GT는 `local-vlm-event-boundary-v1`의 동결본을 재사용한다.
- 모델은 사람 정답, pair 의미, DB, R2, 원문 GT를 볼 수 없다.
- pair 전용 cwd에는 input JPEG 1장만 두고 CLI event의 tool/file 접근은 0이어야 한다.
- measured ledger는 GT-free이며 사람 정답 join은 모든 모델 호출이 끝난 뒤 독립 scorer만 수행한다.
- 모델당 pair당 요청 1회, retry 0, `model_reasoning_effort=low`다.
- 결과는 private `0700/0600` artifact와 aggregate 공개 보고서에만 기록한다.
- production worker, DB/R2, GT, submission, service, 자동 병합·skip은 수정하지 않는다.
- 커밋은 별도 사용자 승인 없이는 만들지 않는다.

---

### Task 1: Frozen input validator and CLI contract

**Files:**
- Create: `tests/test_run_openai_subscription_vlm_event_boundary.py`
- Create: `scripts/run_openai_subscription_vlm_event_boundary.py`

**Interfaces:**
- Consumes: local VLM `frozen-manifest.json`, `inputs/*-AB.jpg`, Codex CLI executable
- Produces: `load_frozen_inputs()`, `build_codex_command()`, `run_experiment()`

- [x] **Step 1: Write failing tests**

검증 대상은 74개 exact identity/hash, 허용 모델, read-only/ephemeral CLI 옵션, GT 비노출이다.

- [x] **Step 2: Verify RED**

Run: `uv run pytest tests/test_run_openai_subscription_vlm_event_boundary.py -q`

Expected: import failure because the runner does not exist.

- [x] **Step 3: Implement the minimal runner**

`load_frozen_inputs()`는 representation/count/hash가 하나라도 다르면 fail-closed한다. `build_codex_command()`는 `--ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check -s read-only`, exact model, low reasoning, one image, output schema, one output file만 사용한다.

- [x] **Step 4: Verify GREEN**

Run: `uv run pytest tests/test_run_openai_subscription_vlm_event_boundary.py tests/test_local_vlm_event_boundary.py -q`

Expected: all tests pass.

### Task 2: Mac mini measured run

**Files:**
- Create on Mac mini private root: `.../openai-subscription/event-boundary-v1/run-20260803-v1/`
- Create: `experiments/openai-subscription-vlm-event-boundary-v1/TEST-SHEET.md`

**Interfaces:**
- Consumes: Task 1 runner and exact local input root
- Produces: private `frozen-run.json`, `schema.json`, GT-free model ledgers, `summary.json`

- [x] **Step 1: Freeze TEST-SHEET and hash it**

Run: `shasum -a 256 experiments/openai-subscription-vlm-event-boundary-v1/TEST-SHEET.md`

- [x] **Step 2: Verify Mac mini preflight**

Check exact host, Codex version, ChatGPT login, available model slugs, source manifest/input hashes, output nonexistence.

- [x] **Step 3: Run three models sequentially**

Run the runner on Mac mini with `gpt-5.4-mini,gpt-5.6-luna,gpt-5.6-terra`. Do not retry failed measured calls.

각 process는 pair 전용 cwd의 이미지 1장만 보며 `--json` trace에서 tool/file event가 나오면 즉시
integrity reject한다. quota/limit 오류는 품질 실패와 분리한다.

- [x] **Step 4: Recompute aggregate scores**

`scripts/recompute_openai_subscription_vlm_event_boundary.py`가 runner를 import하지 않고 source manifest와
GT-free ledger만 읽어 confusion matrix, over-merge, over-split, same/different recall, schema validity,
latency, verdict를 재계산한다. runner summary와 score/latency/ledger digest가 exact 일치해야 한다.

### Task 3: Report and Slack handoff

**Files:**
- Create: `experiments/openai-subscription-vlm-event-boundary-v1/REPORT.md`
- Modify: `experiments/INDEX.md`
- Modify: `specs/next-session.md`
- Modify: `docs/decision-gate.md`

**Interfaces:**
- Consumes: verified Task 2 summary and artifact digests
- Produces: public scorecard with no raw GT, credentials, or private paths

- [x] **Step 1: Write aggregate report**

Compare the three subscription models against MiniCPM and Qwen local baselines. Separate `CLI feasibility` from `API production approval`.

- [x] **Step 2: Verify report evidence**

Run scorer equivalence, artifact mode/hash checks, `git diff --check`, and the focused pytest command.

- [x] **Step 3: Share Slack result**

Post the conclusion, model score table, caveats, and next decision to `#99-petcam-lab-auto` without broad mentions.
