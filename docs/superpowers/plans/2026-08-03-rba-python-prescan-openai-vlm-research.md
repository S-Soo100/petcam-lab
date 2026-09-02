# RBA Python 전수 계측 + OpenAI VLM 연구 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 316개 동결 행동 데이터와 실제 대조군을 대상으로, 모든 디코딩 프레임을 Python/Gate가 계측하고 모든 영상을 OpenAI VLM이 판독하는 정확도 상한선·비용·처리량을 재현 가능하게 측정한다.

**Architecture:** Python prescan, Gate shadow, VLM frame materializer, OpenAI Responses API runner, 독립 scorer를 서로 다른 append-only 단계로 분리한다. 클립 단위로는 Python 완료 후 VLM 입력을 만들지만, 전체 파이프라인에서는 `clip N VLM`과 `clip N+1 Python`을 동시에 진행한다. 어떤 Python/Gate 결과도 초기 VLM 호출을 막거나 사람 GT를 덮지 않는다.

**Tech Stack:** Python 3.12, uv, OpenCV, NumPy, OpenAI Python SDK/Responses API, JSON/JSONL, SHA-256, pytest, macOS launchd는 shadow 검증 후 별도 단계

## Global Constraints

- 정본 설계는 `docs/superpowers/specs/2026-08-03-rba-python-prescan-openai-vlm-research-design.md`다.
- local VLM, local text LLM, local router v0/v1/v2, care-guard, 자동 사건 묶기, 자동 skip은 사용하지 않는다.
- Python은 원본에 실제 존재하는 디코딩 가능 프레임을 최대 30fps까지 순서대로 모두 본다. 낮은 fps 영상을 복제하지 않는다.
- VLM Arm A는 전체 4fps, 6초 window, 1초 overlap이다. Arm C는 A에 Python 변화 구간 최대 20fps 개별 프레임을 추가한다.
- contact sheet, 임의 frame cap, 조용한 frame 누락은 금지한다. API hard limit으로 전량 입력할 수 없으면 `incomplete_input`이다.
- 초기에는 Gate가 `not_observed`여도 VLM을 호출한다. `not_observed != absent`다.
- 사람 GT, 행동명 파일명, 과거 모델 답, private R2 key는 API 입력과 prediction ledger에 넣지 않는다.
- 결과는 `media_sha256`, dataset/version, config digest, prompt/model/input-policy version으로 연결하고 append-only로 저장한다.
- API 키는 코드·Git·DB·R2·Slack·보고서·명령행 인자에 넣지 않는다. 전용 `0600` env 파일에서만 읽는다.
- measured run 전에 모델 접근 가능 여부와 공식 가격·image input·structured output 계약을 TEST-SHEET에 날짜와 함께 동결한다.
- 첫 measured API 모델은 `gpt-5.6-terra`, reasoning `low`, image detail `original`로 고정한다. 공식 계정에서 모델 접근이 불가능하면 돈을 쓰지 않고 `MODEL_ACCESS_BLOCKED`로 종료한다.
- 실행 순서는 3클립 smoke → development 63클립 A/B/C → 결과 동결 후 evaluation 253클립이다. smoke가 schema/coverage/비밀값 감사를 통과하지 못하면 다음 단계로 가지 않는다.
- 현재 연구는 production 사용자 결과, 알림, GT, DB/R2 row를 변경하지 않는 shadow다.
- 기존 dirty worktree의 타 세션 변경을 stage, commit, revert, stash, delete하지 않는다. 커밋은 사용자 명시 승인 뒤에만 한다.

---

## File Responsibility Map

| 책임 | 파일 |
|---|---|
| 연구 계약·판정 | `experiments/rba-python-prescan-openai-vlm-v1/TEST-SHEET.md`, `REPORT.md` |
| manifest 검증·split | `scripts/rba_openai_dataset.py` |
| Python 전수 계측 | `scripts/rba_python_prescan.py` |
| Gate 전수 shadow adapter | `scripts/rba_gate_shadow_adapter.py` |
| VLM 프레임/window 계약 | `scripts/rba_openai_frame_policy.py` |
| OpenAI 호출·ledger | `scripts/run_rba_openai_vlm.py` |
| window→clip 합성 | `scripts/rba_openai_clip_aggregate.py` |
| 독립 채점·비용 | `scripts/recompute_rba_openai_vlm.py` |
| Mac mini pipeline benchmark | `scripts/benchmark_rba_openai_pipeline.py` |
| 단위·계약 테스트 | `tests/test_rba_openai_dataset.py`, `tests/test_rba_python_prescan.py`, `tests/test_rba_gate_shadow_adapter.py`, `tests/test_rba_openai_frame_policy.py`, `tests/test_run_rba_openai_vlm.py`, `tests/test_rba_openai_clip_aggregate.py`, `tests/test_recompute_rba_openai_vlm.py`, `tests/test_benchmark_rba_openai_pipeline.py` |
| 합성 fixture | `tests/fixtures/rba_openai_vlm/` |

## Runtime and Artifact Layout

Mac mini private root:

```text
/Users/baek-end/.local/share/petcam/rba-openai-vlm-v1/
  dataset-manifest.json
  split-manifest.json
  prescan/RBA_RUN_ID/CLIP_ID.summary.json
  prescan/RBA_RUN_ID/CLIP_ID.frames.jsonl.gz
  frame-manifests/RBA_RUN_ID/ARM/CLIP_ID.json
  predictions/RBA_RUN_ID/ARM/CLIP_ID.windows.jsonl
  aggregates/RBA_RUN_ID/ARM/CLIP_ID.json
  reports/RBA_RUN_ID/summary.json
```

디렉터리는 `0700`, 파일은 `0600`이다. 원본 영상은 기존 격리 R2 dataset에서 읽기만 하며 runtime root에 영구 복제하지 않는다.

---

### Task 1: 연구 시험지와 316 manifest 계약 동결

**Files:**
- Create: `experiments/rba-python-prescan-openai-vlm-v1/TEST-SHEET.md`
- Create: `experiments/rba-python-prescan-openai-vlm-v1/REPORT.md`
- Create: `scripts/rba_openai_dataset.py`
- Test: `tests/test_rba_openai_dataset.py`

- [ ] **Step 1: manifest 실패 테스트 작성**

`316 unique`, `legacy=197`, `recent=119`, 전부 `highlight=include`, legacy segment=`not_measured`, media SHA 중복 0, split group leakage 0을 검사한다.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest tests/test_rba_openai_dataset.py -q`

Expected: `ModuleNotFoundError: scripts.rba_openai_dataset`.

- [ ] **Step 3: 최소 validator와 deterministic split 구현**

동일 clip·인접 clip·같은 camera-night·같은 확인된 사건을 하나의 group으로 묶고, 해시 정렬로 development 63개와 evaluation 253개를 고정한다. 실제 대조군은 별도 `control` partition으로만 받는다.

- [ ] **Step 4: GREEN 및 실제 manifest read-only preflight**

Run: `uv run pytest tests/test_rba_openai_dataset.py -q`

Expected: all tests pass. 실제 manifest 검증은 수량·digest만 출력하고 clip id, 이메일, R2 key, 원문 GT는 출력하지 않는다.

- [ ] **Step 5: TEST-SHEET hash 동결**

Run: `shasum -a 256 experiments/rba-python-prescan-openai-vlm-v1/TEST-SHEET.md`

Expected: 64자리 SHA-256 한 줄. 이후 measured 결과를 보기 전 TEST-SHEET 변경은 새 experiment version을 요구한다.

### Task 2: Python native-frame 전수 계측기

**Files:**
- Create: `scripts/rba_python_prescan.py`
- Test: `tests/test_rba_python_prescan.py`
- Create: `tests/fixtures/rba_openai_vlm/README.md`

- [ ] **Step 1: 합성 video fixture 생성 helper와 실패 테스트 작성**

30초/30fps, 낮은 fps, 가변 timestamp 대체 fixture, IR 밝기 전환, 전체 화면 흔들림, 국소 변화, 손상 파일을 테스트 안에서 임시 디렉터리에 생성한다. fixture binary는 Git에 넣지 않는다.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest tests/test_rba_python_prescan.py -q`

Expected: import failure.

- [ ] **Step 3: streaming decoder와 summary schema 구현**

`cv2.VideoCapture`를 한 번 열고 순차 `read()`하며 `try/finally`로 release한다. 메모리에는 이전 gray frame과 bounded per-second accumulator만 둔다. 출력 schema는 `python-prescan-v1`, summary 16KiB 이하, 상세 frame 수치는 gzip JSONL sidecar다.

- [ ] **Step 4: 계측 항목 구현**

decode/fps/duration/resolution, duplicate/freeze, brightness, IR transition, global shake, local change, per-second activity envelope, dense intervals를 계산한다. 이 단계는 행동명·presence 확정·highlight 결정을 만들지 않는다.

- [ ] **Step 5: GREEN과 누수 검사**

Run: `uv run pytest tests/test_rba_python_prescan.py -q`

Expected: 모든 native frame count가 fixture 기대값과 일치하고 손상 영상도 capture가 release된다.

### Task 3: Gate full-frame shadow adapter 계약

**Files:**
- Create: `scripts/rba_gate_shadow_adapter.py`
- Test: `tests/test_rba_gate_shadow_adapter.py`
- Create: `docs/handoff-prompts/2026-08-03-rba-gate-full-frame-shadow-handoff.md`

- [ ] **Step 1: Gate adapter 계약 테스트 작성**

decoded frame index/timestamp를 Gate에 정확히 한 번씩 전달하고 `present_candidate/not_observed/uncertain`만 허용한다. `absent`, `skip`, 행동명 출력은 거부한다.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest tests/test_rba_gate_shadow_adapter.py -q`

Expected: import failure.

- [ ] **Step 3: read-only dependency adapter 구현**

petcam-lab adapter는 Gate의 pinned checkpoint와 public inference interface만 호출한다. Gate 레포 수정이 필요하면 추측 구현하지 않고 handoff manifest에 `execution_repo`, plan/design 절대경로, 40자리 SHA, implementation/runtime host, runtime kind/service label을 기록한다.

- [ ] **Step 4: handoff gate와 GREEN 확인**

Run: `uv run python scripts/verify_agent_handoff.py --manifest /Users/baek/.codex/worktrees/8faf/petcam-lab/docs/handoff-prompts/2026-08-03-rba-gate-full-frame-shadow-handoff.md`

Expected: `HANDOFF_OK` 또는 Gate 작업 불필요 판정. 이어서 focused test가 통과한다.

### Task 4: VLM 4fps + dense 20fps frame policy

**Files:**
- Create: `scripts/rba_openai_frame_policy.py`
- Test: `tests/test_rba_openai_frame_policy.py`

- [ ] **Step 1: sampling/window 실패 테스트 작성**

30초·60초·29.97fps·15fps 영상에서 Arm A의 4fps coverage, 6초 window/1초 overlap, Arm C dense interval 최대 20fps, timestamp+digest dedupe, 마지막 꼬리 window 보존을 검사한다.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest tests/test_rba_openai_frame_policy.py -q`

Expected: import failure.

- [ ] **Step 3: frame manifest materializer 구현**

각 frame에 `frame_index`, `timestamp_sec`, `sha256`, `source_policy=base4fps|dense20fps`, `window_ids`를 기록한다. 계획 frame과 실제 파일 count/digest가 다르면 API 호출 전에 fail-closed한다.

- [ ] **Step 4: no-drop GREEN 확인**

Run: `uv run pytest tests/test_rba_openai_frame_policy.py -q`

Expected: 예상 frame set과 materialized frame set이 exact match하며 contact sheet가 생성되지 않는다.

### Task 5: OpenAI credential preflight와 Responses API runner

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `scripts/run_rba_openai_vlm.py`
- Test: `tests/test_run_rba_openai_vlm.py`

- [ ] **Step 1: SDK 의존성 추가**

Run: `uv add openai`

Expected: `pyproject.toml`과 `uv.lock`만 의존성 변경.

- [ ] **Step 2: fake client 기반 실패 테스트 작성**

환경변수 부재, key 로그 마스킹, model 접근 실패, structured output 불일치, rate limit retry, request id 보존, window 일부 실패, frame manifest drift를 검사한다.

- [ ] **Step 3: RED 확인**

Run: `uv run pytest tests/test_run_rba_openai_vlm.py -q`

Expected: runner import failure.

- [ ] **Step 4: 최소 Responses API runner 구현**

`OPENAI_API_KEY`는 환경에서만 읽고 `gpt-5.6-terra`, reasoning low, image detail original, strict JSON schema를 사용한다. transient retry는 지수 backoff 최대 2회, invalid schema와 content failure는 재시도하지 않는다. raw response 전체 대신 request id, usage, latency, structured prediction만 private ledger에 기록한다.

- [ ] **Step 5: GREEN과 secret scan**

Run: `uv run pytest tests/test_run_rba_openai_vlm.py -q`

Run: `rg -n "sk-[A-Za-z0-9_-]{10,}" . --glob '!storage/**' --glob '!reports/**'`

Expected: tests pass, secret pattern 0건.

### Task 6: window 결과의 결정론적 clip 합성

**Files:**
- Create: `scripts/rba_openai_clip_aggregate.py`
- Test: `tests/test_rba_openai_clip_aggregate.py`

- [ ] **Step 1: overlap·실패·동률 테스트 작성**

동일 timestamp digest dedupe, 1초 이내 같은 행동 segment union, 대표 행동 duration/first-evidence/vocabulary tie-break, max count, uncertain 보존, 누락 window incomplete를 검사한다.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest tests/test_rba_openai_clip_aggregate.py -q`

Expected: import failure.

- [ ] **Step 3: 순수 합성 함수 구현**

API나 GT를 읽지 않는 순수 함수로 만든다. 실패 window를 다른 window로 추정하지 않고 clip status를 `incomplete`로 둔다.

- [ ] **Step 4: GREEN 확인**

Run: `uv run pytest tests/test_rba_openai_clip_aggregate.py -q`

Expected: all tests pass and repeated aggregation has the same digest.

### Task 7: 3클립 유료 smoke

**Files:**
- Modify: `experiments/rba-python-prescan-openai-vlm-v1/TEST-SHEET.md` only before its measured hash is frozen
- Create private runtime artifacts only under the Mac mini runtime root

- [ ] **Step 1: Mac mini credential·billing·model read-only preflight**

키 값은 출력하지 않고 `key_present=true`, project/model access, account rate-limit headers만 확인한다. billing hard limit은 Platform에서 사용자가 설정한 값으로 기록하되 결제 정보는 기록하지 않는다.

- [ ] **Step 2: 3클립 선정**

development partition에서 30초 1개, 60초 1개, IR/흔들림 hard case 1개를 manifest hash 규칙으로 선택한다. 사람이 결과를 골라 선택하지 않는다.

- [ ] **Step 3: Arm A만 실제 호출**

Python clip 1 완료 후 VLM clip 1을 시작하면서 Python clip 2를 처리한다. API inflight=1, Python worker=1, 전체 pipeline active clip 최대 2다.

- [ ] **Step 4: smoke gate 판정**

세 클립 모두 planned/actual frame exact match, schema success 100%, window coverage 100%, secret/GT leak 0, usage/latency/cost ledger 존재여야 통과한다. 하나라도 실패하면 development 호출을 시작하지 않는다.

### Task 8: Development 63개 paired A/B/C 실행

**Files:**
- Create private ledgers under Mac mini runtime root
- Modify: `experiments/rba-python-prescan-openai-vlm-v1/REPORT.md`

- [ ] **Step 1: run manifest 동결**

dataset/split/TEST-SHEET/model/prompt/schema/Python config/frame-policy/Gate checkpoint SHA를 하나의 frozen-run JSON에 기록한다.

- [ ] **Step 2: Python/Gate 전수 실행**

63개 native frame을 전수 처리하고 summary와 sidecar digest를 검증한다. Python 실패 clip은 Arm A 4fps VLM으로 fail-open하되 B/C는 `prescan_unavailable`로 분리한다.

- [ ] **Step 3: A/B/C 순차 measured 실행**

같은 clip/model/prompt/schema/retry 규칙을 사용한다. A=4fps, B=A+숫자 summary, C=A+dense frames다. 모든 frame/token/call/latency/cost를 기록한다.

- [ ] **Step 4: 실행 완전성 검사**

63×3 clip aggregate가 존재하거나 명시적 incomplete reason을 가진다. 누락을 0점으로 숨기지 않고 reliability 분모에 포함한다.

### Task 9: 독립 재채점과 비용 보고

**Files:**
- Create: `scripts/recompute_rba_openai_vlm.py`
- Test: `tests/test_recompute_rba_openai_vlm.py`
- Modify: `experiments/rba-python-prescan-openai-vlm-v1/REPORT.md`

- [ ] **Step 1: runner import 금지 테스트 작성**

독립 scorer가 frozen GT manifest와 GT-free prediction ledger만 읽는지 검사한다.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest tests/test_recompute_rba_openai_vlm.py -q`

Expected: import failure.

- [ ] **Step 3: 성적·비용 계산 구현**

대표 행동 accuracy/macro F1/confusion, 완전 GT subset 복수 행동, measured subset segment IoU/boundary error, count exact/confusion, hallucination, schema/retry/incomplete, Python/VLM latency·CPU/RSS·frame/token/call·actual cost·월 2만 projection을 계산한다.

- [ ] **Step 4: paired recovered/broken과 판정 구현**

B와 C를 A에 paired 비교하고 좋아진 사례와 나빠진 사례를 모두 센다. B 숫자 주입과 C 추가 시각 입력을 각각 `ADOPT/REJECT/HOLD`로 판정하되 Python 전수 계측 자체와 혼동하지 않는다.

- [ ] **Step 5: GREEN과 runner/scorer digest 대조**

Run: `uv run pytest tests/test_recompute_rba_openai_vlm.py -q`

Expected: all tests pass; runner summary와 독립 scorer의 공통 지표·ledger digest exact match.

### Task 10: Mac mini 동시 파이프라인 benchmark

**Files:**
- Create: `scripts/benchmark_rba_openai_pipeline.py`
- Test: `tests/test_benchmark_rba_openai_pipeline.py`
- Modify: `experiments/rba-python-prescan-openai-vlm-v1/REPORT.md`

- [ ] **Step 1: bounded concurrency 테스트 작성**

Python worker=1, VLM inflight=1, active clips≤2, 동일 clip에서 Python→frame manifest→VLM 순서, 서로 다른 clip은 overlap되는지 검사한다.

- [ ] **Step 2: RED 확인**

Run: `uv run pytest tests/test_benchmark_rba_openai_pipeline.py -q`

Expected: import failure.

- [ ] **Step 3: benchmark orchestrator 구현**

queue는 로컬 private manifest 기반이며 production DB queue를 사용하지 않는다. subprocess exit, SIGTERM, resume, 이미 성공한 artifact의 digest skip을 지원한다.

- [ ] **Step 4: 30초/60초 실영상 benchmark**

Mac mini에서 순차 실행 대비 pipeline 실행의 wall time, Python fps, Gate fps, CPU, RSS, API latency를 비교한다. worker 수를 자동 증설하지 않는다.

- [ ] **Step 5: 운영 가능성 판정**

월 2만건 처리에 필요한 wall-clock, API rate limit, 실제 비용을 계산한다. 처리량이 부족해도 frame 수를 줄이지 않고 `capacity_shortfall`로 보고한다.

### Task 11: Evaluation 253개와 최종 연구 판정

**Files:**
- Modify: `experiments/rba-python-prescan-openai-vlm-v1/REPORT.md`
- Modify: `experiments/INDEX.md`
- Modify: `specs/next-session.md`
- Modify: `docs/decision-gate.md`

- [ ] **Step 1: development 이후 계약 동결 확인**

prompt/model/schema/frame policy/threshold가 development 결과를 본 뒤 바뀌었다면 evaluation을 열지 않고 experiment version을 올린다.

- [ ] **Step 2: 253개 evaluation 실행**

동결된 계약 그대로 Python/Gate/VLM을 실행한다. 평가 결과는 전체 호출이 끝날 때까지 중간 튜닝에 사용하지 않는다.

- [ ] **Step 3: 독립 recompute와 final report**

행동·개체 수·신뢰성·비용·처리량과 exact 분모를 보고한다. 316개가 전부 highlight include이므로 highlight selector 성능은 보고하지 않는다.

- [ ] **Step 4: adoption boundary 기록**

허용 범위는 Python 계측과 VLM shadow 결과 생성까지다. `verified_absent` skip, 자동 GT, 사용자 알림, production queue/service는 별도 future-holdout Gate와 Owner 승인 없이는 열지 않는다.

### Task 12: 전체 검증과 인계

**Files:**
- Modify: `.claude/donts-audit.md`
- Create: `docs/handoff-prompts/2026-08-03-rba-python-prescan-openai-vlm-implementation-report.md`

- [ ] **Step 1: focused tests**

Run: `uv run pytest tests/test_rba_openai_dataset.py tests/test_rba_python_prescan.py tests/test_rba_gate_shadow_adapter.py tests/test_rba_openai_frame_policy.py tests/test_run_rba_openai_vlm.py tests/test_rba_openai_clip_aggregate.py tests/test_recompute_rba_openai_vlm.py tests/test_benchmark_rba_openai_pipeline.py -q`

Expected: all pass.

- [ ] **Step 2: full regression and syntax checks**

Run: `uv run pytest -q`

Run: `uv run python -m compileall backend scripts`

Run: `git diff --check`

Expected: all pass, compile errors 0, whitespace errors 0.

- [ ] **Step 3: runtime evidence**

보고서에 Mac mini hostname, service 미사용 또는 service label, repo 40자리 HEAD, dataset/run digests, 실제 run id, artifact permission, temp media residue 0을 기록한다.

- [ ] **Step 4: 상태 보고**

코드만 끝났으면 `IMPLEMENTED_UNVERIFIED`, 전체 연구와 runtime evidence까지 끝났으면 `REVIEWED_READY_FOR_INTEGRATION`으로 보고한다. production service를 실제로 켜지 않았으므로 `DEPLOYED_VERIFIED`라고 부르지 않는다.

- [ ] **Step 5: 사용자 승인 후에만 commit**

현재 dirty worktree의 타 세션 변경과 이 계획 작업 파일을 경로별로 분리 확인한다. 사용자가 commit을 명시 승인한 뒤에만 의도한 파일만 stage하고 한글 prefix commit을 만든다.

---

## Completion Criteria

- 316 manifest와 split이 count/digest/group leakage 검사를 통과한다.
- Python은 native decoded frame 전량을 처리하고 summary/sidecar가 재현된다.
- Gate는 전수 shadow evidence만 만들며 absent/skip을 만들지 않는다.
- VLM planned frame과 실제 API frame manifest가 exact match한다.
- smoke 3개와 development 63개, evaluation 253개의 상태가 모두 명시된다.
- A/B/C 성적과 recovered/broken, 실제 비용, 월 2만건 projection이 독립 재계산된다.
- Python/Gate/VLM 결과와 사람 GT가 물리·논리적으로 분리된다.
- production DB/R2 row, GT, 사용자 결과, 알림, 자동 skip 변경은 0이다.
