# Production Local VLM Clip Shadow Canary v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 오늘 밤 Mac mini가 새 production `motion_clips` 최대 20개를 Gemma 3 4B로 관찰하고,
사용자·GT·DB·라우터에 영향을 주지 않는 private shadow 결과를 남기게 한다.

**Architecture:** 순수 core가 6-frame sampler·contact sheet·strict JSON·stop/verdict 계약을 맡고,
runner가 production SELECT·R2 HEAD/GET·Ollama·resource monitor·private ledger를 조립한다. 별도 launchd
manager는 정확한 임시 label만 설치·시작·상태확인하며, independent recompute는 runner를 import하지
않고 결과 무결성과 aggregate를 다시 계산한다.

**Tech Stack:** Python 3.12, OpenCV, NumPy, Supabase Python client, boto3 R2, Ollama 0.32.5,
macOS launchd, pytest, uv.

## Global Constraints

- runtime host는 `baeg-endeuui-Macmini.local`, model은 exact `gemma3:4b`, 한 번에 하나만 load한다.
- source는 service 시작 시각 이후 `motion_clips`; `started_at,id` 오름차순, model request 최대 20개다.
- 종료는 schema-valid 20개 완료 또는 `2026-08-03T07:00:00+09:00` 중 먼저 오는 시점이다.
- DB는 SELECT만, R2는 HEAD/GET만 허용한다. production DB/R2/GT/submission/VLM job write는 0이다.
- Python Evidence·Gate·행동 GT·사람 답·기존 VLM 결과를 조회하거나 모델 입력·선택에 쓰지 않는다.
- timeout 120초, model retry 0, temperature 0, seed 20260802, ctx 4096, predict 320이다.
- free memory ≤5% 2회 연속, swap 시작 대비 +1GiB, monitor 실패, Ollama PID drift는 fail-closed다.
- 결과는 Mac private `0700/0600` artifact에만 append+fsync하고 raw ID/key/secret은 공개하지 않는다.
- 자동 사건 병합·skip·cloud 차단·사용자 노출·LoRA·prompt 사후 튜닝은 금지한다.
- 기존 LaunchAgent·Ollama server·model은 재시작·삭제·수정하지 않는다. 새 임시 label 하나만 허용한다.

---

### Task 1: TEST-SHEET와 결과 상태 계약 동결

**Files:**

- Create: `experiments/production-local-vlm-clip-shadow-canary-v1/TEST-SHEET.md`
- Create: `experiments/production-local-vlm-clip-shadow-canary-v1/REPORT-TEMPLATE.md`
- Modify: `docs/superpowers/specs/2026-08-02-production-local-vlm-clip-shadow-canary-v1-design.md`

**Interfaces:**

- Consumes: 승인된 설계와 Global Constraints
- Produces: runner와 independent scorer가 공유할 상수·verdict·공개 aggregate 계약

- [ ] **Step 1: TEST-SHEET에 exact source와 gate를 기록한다**

  `started_at,id`, start/end timestamp, model tag+digest freeze, max request 20, six fractions,
  prompt/schema, synthetic smoke 3/3, resource threshold, retry 0, public redaction을 적는다.

- [ ] **Step 2: decision gate 승인 로그를 재확인한다**

  `docs/decision-gate.md`의 2026-08-02 production clip shadow 항목이 SOT·효과·측정·계획 네 gate와
  owner 구현 승인을 모두 포함하는지 확인하고 상태를 `구현 승인`으로 갱신한다.

- [ ] **Step 3: REPORT template에 실행 전 빈 상태를 만든다**

  `PRE_REGISTERED` 상태와 `start_at`, `end_at`, exact HEAD, model digest, selected/attempted/schema,
  latency, resource, media error, mutation 0, final verdict 칸을 만든다. raw ID 표는 만들지 않는다.

- [ ] **Step 4: 문서 self-review를 실행한다**

  Run:

  ```bash
  rg -n "TBD|TODO|created_at|retry [1-9]|auto.*skip" \
    experiments/production-local-vlm-clip-shadow-canary-v1 \
    docs/superpowers/specs/2026-08-02-production-local-vlm-clip-shadow-canary-v1-design.md
  git diff --check
  ```

  Expected: placeholder·`created_at`·retry·자동 skip 위반 0, diff check PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add experiments/production-local-vlm-clip-shadow-canary-v1 \
    docs/superpowers/specs/2026-08-02-production-local-vlm-clip-shadow-canary-v1-design.md
  git commit -m "docs: production local VLM shadow 시험 동결"
  ```

### Task 2: 순수 관찰·sampler 계약 TDD

**Files:**

- Create: `scripts/local_vlm_clip_shadow.py`
- Create: `tests/test_local_vlm_clip_shadow.py`

**Interfaces:**

- Produces:
  - `FRAME_FRACTIONS: tuple[float, ...]`
  - `ClipObservation` frozen dataclass
  - `parse_observation(raw: str) -> ClipObservation`
  - `build_contact_sheet(frames: Sequence[np.ndarray]) -> np.ndarray`
  - `stop_reason(now, end_at, valid_count, max_requests, attempted_count) -> str | None`
  - `aggregate_public(records) -> dict[str, object]`

- [ ] **Step 1: strict parser RED 테스트를 작성한다**

  valid exact 6-key object만 통과하고 extra key, fence, NaN/Infinity, bool confidence, 120자 초과,
  enum 이탈, 비한국어/빈 summary를 거부하는 테스트를 작성한다.

- [ ] **Step 2: sampler·contact sheet RED 테스트를 작성한다**

  fractions가 `(0.05, 0.20, 0.40, 0.60, 0.80, 0.95)`, frame 6개, 3×2 chronological grid,
  긴 변 768 이하, frame shape 오류 fail-closed임을 검사한다.

- [ ] **Step 3: stop·aggregate RED 테스트를 작성한다**

  valid 20, attempted 20, deadline, resource abort 우선순위와 public aggregate에 raw `id`, `r2_key`,
  path, model raw content가 없는지 검사한다.

- [ ] **Step 4: RED를 확인한다**

  Run: `uv run pytest tests/test_local_vlm_clip_shadow.py -q`

  Expected: module/function missing으로 FAIL.

- [ ] **Step 5: 최소 순수 구현을 작성한다**

  schema는 exact enum/length/range를 코드 상수로 두고 JSON parser는 `parse_constant`로 NaN/Infinity를
  차단한다. contact sheet는 frame에 글자나 crop을 넣지 않고 바깥 24px header에 순서만 표시한다.

- [ ] **Step 6: GREEN을 확인하고 commit한다**

  ```bash
  uv run pytest tests/test_local_vlm_clip_shadow.py -q
  git add scripts/local_vlm_clip_shadow.py tests/test_local_vlm_clip_shadow.py
  git commit -m "feat: local VLM clip shadow 순수 계약"
  ```

  Expected: focused PASS.

### Task 3: production read-only runner TDD

**Files:**

- Create: `scripts/run_local_vlm_clip_shadow.py`
- Create: `tests/test_run_local_vlm_clip_shadow.py`

**Interfaces:**

- Consumes: Task 2 core, private env path, `start_at`, `end_at`, model digest
- Produces:
  - `ClipCandidate(private_key, clip_id, camera_id, r2_key, started_at, duration_sec)` private-only dataclass
  - `fetch_candidates(client, *, start_at, limit) -> tuple[ClipCandidate, ...]`
  - `next_unprocessed(candidates, processed_hmac_keys) -> ClipCandidate | None`
  - `process_one(candidate, adapters, ledger) -> ProcessOutcome`
  - `run_cycle(config, adapters) -> CycleResult`

- [ ] **Step 1: query allowlist와 ordering RED 테스트를 작성한다**

  Fake Supabase가 정확히 `id,camera_id,r2_key,started_at,duration_sec`만 SELECT하고 `started_at,id`
  오름차순을 요구하는지 검사한다. 매 poll 시작 이후 전체 창을 다시 조회하고 processed HMAC set을
  제외해, 직전 cursor보다 이른 `started_at`으로 늦게 insert된 row도 처리하는 회귀 테스트를 둔다.
  `.insert/.update/.delete/.rpc` 접근 시 테스트가 즉시 실패하게 한다.

- [ ] **Step 2: private identity/processed-set RED 테스트를 작성한다**

  32-byte `0600` salt로 clip ID를 HMAC하고 private state에는 HMAC processed key만 append한다.
  output root `0700`, file `0600`, symlink·existing run·mode drift를 거부하고 write마다 fsync하는지 검사한다.

- [ ] **Step 3: R2/media/model RED 테스트를 작성한다**

  HEAD→GET→SHA→OpenCV decode→6 frames→one Ollama request 순서를 fake adapter로 고정한다.
  R2 missing/decode failure는 `media_error`이고 model call 0, timeout/empty/schema invalid는 model request
  1회와 retry 0인지 검사한다.

- [ ] **Step 4: Ollama payload RED 테스트를 작성한다**

  exact `gemma3:4b`, one base64 contact sheet, production prompt/schema, `think=false`, `keep_alive=5m`,
  temperature 0, seed 20260802, ctx 4096, predict 320, timeout 120을 검사한다.

- [ ] **Step 5: RED를 확인한다**

  Run: `uv run pytest tests/test_run_local_vlm_clip_shadow.py -q`

  Expected: module/function missing으로 FAIL.

- [ ] **Step 6: 최소 runner를 구현한다**

  외부 client는 lazy import하고 DB/R2 write method를 runner API에 노출하지 않는다. model call 전
  request intent를 ledger에 fsync한 뒤 result를 append해 crash 후 같은 key 재호출을 막는다.

- [ ] **Step 7: GREEN과 mutation audit를 실행한다**

  ```bash
  uv run pytest tests/test_run_local_vlm_clip_shadow.py -q
  rg -n "\.insert\(|\.update\(|\.delete\(|\.rpc\(|put_object|delete_object" \
    scripts/run_local_vlm_clip_shadow.py
  ```

  Expected: tests PASS, mutation pattern 0.

- [ ] **Step 8: Commit**

  ```bash
  git add scripts/run_local_vlm_clip_shadow.py tests/test_run_local_vlm_clip_shadow.py
  git commit -m "feat: production local VLM read-only shadow runner"
  ```

### Task 4: loop·resource monitor·synthetic Gate A TDD

**Files:**

- Modify: `scripts/run_local_vlm_clip_shadow.py`
- Modify: `tests/test_run_local_vlm_clip_shadow.py`

**Interfaces:**

- Produces:
  - `run_synthetic_gate_a(ollama) -> SyntheticGateResult`
  - `ResourceMonitor.sample() -> ResourceSample`
  - `run_until_closed(config, adapters) -> RunClosure`
  - `unload_model(model) -> None`

- [ ] **Step 1: synthetic smoke RED 테스트를 작성한다**

  OpenCV로 `dark_empty`, `static_silhouette`, `moving_silhouette` 3장과 큰 caption을 결정론적으로 만들고,
  smoke 전용 exact schema가 서로 다른 scene enum을 반환해야 Gate A가 통과함을 fake response로 검사한다.
  이어서 같은 합성 sheet 하나를 실제 production prompt·6-key schema로 한 번 더 호출해
  `parse_observation`을 통과해야 하며, 이 4회는 live measured 20회 밖임을 검사한다.

- [ ] **Step 2: resource fail-closed RED 테스트를 작성한다**

  free≤5% 연속 2회, swap delta>1GiB, Ollama PID drift, probe timeout/parse error, monitor thread exception에서
  다음 candidate를 시작하지 않고 model unload를 호출하는지 검사한다.

- [ ] **Step 3: loop RED 테스트를 작성한다**

  60초 poll은 injected clock/sleeper로 시험한다. valid20, attempted20, deadline, live volume 0의 종료와
  processed-set persistence, restart 후 no duplicate request를 검사한다.

- [ ] **Step 4: 최소 구현 후 focused test를 실행한다**

  ```bash
  uv run pytest tests/test_run_local_vlm_clip_shadow.py -q
  ```

  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add scripts/run_local_vlm_clip_shadow.py tests/test_run_local_vlm_clip_shadow.py
  git commit -m "feat: local VLM shadow 야간 안전 루프"
  ```

### Task 5: independent recompute와 private review bundle

**Files:**

- Create: `scripts/recompute_local_vlm_clip_shadow.py`
- Create: `tests/test_recompute_local_vlm_clip_shadow.py`

**Interfaces:**

- Consumes: frozen manifest, ledger JSONL, resource JSONL
- Produces: `summary-private.json`, `public-report.md`, `review-index-private.html`

- [ ] **Step 1: 무결성 RED 테스트를 작성한다**

  duplicate request intent, result-without-intent, unexpected model/input/prompt digest, raw identity public leak,
  invalid resource sequence를 거부하는 테스트를 작성한다.

- [ ] **Step 2: aggregate RED 테스트를 작성한다**

  attempted/schema/media_error/error enum 분포, p50/p95/max latency, free min, swap delta, RSS max, stop reason을
  runner와 독립 계산하고 expected dict를 assert한다.

- [ ] **Step 3: review bundle RED 테스트를 작성한다**

  private HTML은 각 local media path와 관찰 JSON을 나란히 보여주되 secret·R2 key·raw UUID를 포함하지
  않고 HMAC key만 DOM id로 쓰는지 검사한다. 자동으로 DB에 사람 답을 쓰는 form/action은 금지한다.

- [ ] **Step 4: 구현·GREEN·commit**

  ```bash
  uv run pytest tests/test_recompute_local_vlm_clip_shadow.py -q
  git add scripts/recompute_local_vlm_clip_shadow.py tests/test_recompute_local_vlm_clip_shadow.py
  git commit -m "feat: local VLM shadow 독립 재계산"
  ```

### Task 6: exact 임시 LaunchAgent manager TDD

**Files:**

- Create: `scripts/manage_local_vlm_clip_shadow_launchd.py`
- Create: `tests/test_manage_local_vlm_clip_shadow_launchd.py`

**Interfaces:**

- Produces CLI `render|install|status|uninstall`
- Exact label: `com.petcam.local-vlm-clip-shadow-canary-v1`
- Exact plist: `~/Library/LaunchAgents/com.petcam.local-vlm-clip-shadow-canary-v1.plist`

- [ ] **Step 1: plist RED 테스트를 작성한다**

  `RunAtLoad=false`, `KeepAlive=false`, exact absolute worktree/python/env/private paths, start/end/model args,
  stdout/stderr private paths를 검사한다. secret value는 plist에 없어야 한다.

- [ ] **Step 2: host·target 안전 RED 테스트를 작성한다**

  wrong hostname, symlink plist, existing different bytes, broad label/path, repo dirty/HEAD mismatch를 거부한다.
  `uninstall`은 exact label과 exact plist만 대상으로 하고 missing은 idempotent status로 처리한다.

- [ ] **Step 3: subprocess RED 테스트를 작성한다**

  install은 `launchctl bootstrap` 뒤 exact label `kickstart` 한 번만 호출한다. 기존 label의 bootout/kickstart,
  Ollama restart, wildcard shell command가 0인지 fake subprocess로 검사한다.

- [ ] **Step 4: 구현·GREEN·commit**

  ```bash
  uv run pytest tests/test_manage_local_vlm_clip_shadow_launchd.py -q
  git add scripts/manage_local_vlm_clip_shadow_launchd.py tests/test_manage_local_vlm_clip_shadow_launchd.py
  git commit -m "feat: local VLM shadow 임시 launchd 관리"
  ```

### Task 7: 전체 검증·Claude review·handoff

**Files:**

- Modify: `experiments/production-local-vlm-clip-shadow-canary-v1/TEST-SHEET.md`
- Create outside repo: `/tmp/2026-08-02-production-local-vlm-clip-shadow-canary-v1-handoff.md`

- [ ] **Step 1: 전체 검증을 실행한다**

  ```bash
  uv run pytest -q --disable-warnings
  uv run python -m compileall -q \
    scripts/local_vlm_clip_shadow.py \
    scripts/run_local_vlm_clip_shadow.py \
    scripts/recompute_local_vlm_clip_shadow.py \
    scripts/manage_local_vlm_clip_shadow_launchd.py
  git diff --check
  ```

  Expected: full PASS, compile PASS, diff clean.

- [ ] **Step 2: iTerm2 Claude plan/code review를 실행한다**

  공식 AppleScript로 정확한 `RBA 순서 시퀀스 구현 교차리뷰` 세션에 설계·계획·TEST-SHEET·diff를
  read-only 전달한다. P0/P1을 현재 SOT와 실측에 대조해 채택하고 focused/full test를 재실행한다.

- [ ] **Step 3: commit·push하고 exact handoff를 만든다**

  feature HEAD를 origin에 push한다. handoff에는 `execution_repo`, design/plan 절대경로, 40자리 SHA,
  `implementation_host`, `runtime_host`, runtime kind, exact service label을 기록한다.

- [ ] **Step 4: handoff를 검증한다**

  Run:

  ```bash
  uv run python scripts/verify_agent_handoff.py \
    --manifest /tmp/2026-08-02-production-local-vlm-clip-shadow-canary-v1-handoff.md
  ```

  Expected: `HANDOFF_OK`.

- [ ] **Step 5: 검수된 계획을 Slack에 공유한다**

  기존 RBA 운영 채널을 검색·최근 메시지 확인 후, 사용자 승인·오늘 밤 max20·Gemma3:4b·private
  shadow·07:00 종료·자동 병합/skip/UI/GT write 0·아침 go/no-go를 10줄 이내로 직접 게시한다.
  Mac mini 시작(Task 8)보다 먼저 게시하고 message link를 실행 기록에 남긴다.

### Task 8: Mac mini Gate A·임시 service 시작

**Runtime:** `baek-end@baeg-endeuui-Macmini.local`

- [ ] **Step 1: exact detached worktree를 준비한다**

  `/Users/baek-end/petcam-lab-local-vlm-clip-shadow-canary-v1`을 handoff SHA로 만들고 tracked clean,
  hostname, model digest, Ollama PID, disk, memory, swap, existing LaunchAgent snapshot을 확인한다.

- [ ] **Step 2: private runtime을 준비한다**

  `/Users/baek-end/Library/Application Support/petcam/local-vlm/clip-shadow-canary-v1`을 `0700`으로 만들고,
  env path·salt·run directory 파일을 `0600`으로 둔다. source env 권한이 약하면 값을 출력하지 않고
  exact private copy를 만든다.

- [ ] **Step 3: foreground Gate A를 실행한다**

  exact model digest freeze와 synthetic 3/3을 실행한다. Gate A 실패 시 plist를 만들지 않고
  `BLOCKED_SYNTHETIC_GATE_A` report로 종료한다.

- [ ] **Step 4: launchd manager로 exact 임시 service를 시작한다**

  start timestamp를 시작 직전에 고정하고 end timestamp는 `2026-08-03T07:00:00+09:00`으로 전달한다.
  render bytes를 검토한 뒤 install하고 exact label PID/arguments/working directory/HEAD를 확인한다.

- [ ] **Step 5: 첫 자연 cycle을 확인한다**

  수동 model call을 추가로 만들지 않고 service 로그에서 첫 poll 또는 첫 실제 key 1회 처리만 확인한다.
  existing service PID/last-exit와 Ollama serve PID가 의도치 않게 바뀌지 않았는지 대조한다.

### Task 9: 야간 관찰·아침 보고

**Files:**

- Modify: `experiments/production-local-vlm-clip-shadow-canary-v1/TEST-SHEET.md`
- Replace template with final: `experiments/production-local-vlm-clip-shadow-canary-v1/REPORT.md`
- Modify: `specs/next-session.md`
- Modify: `docs/AI-VIDEO-ANALYSIS-STRATEGY.md`
- Modify: `specs/feature-rba-data-engine-v1.md`
- Modify: `.claude/donts-audit.md`

- [ ] **Step 1: 종료 뒤 independent recompute를 실행한다**

  exact private manifest/ledger/resource에서 summary와 review bundle을 만든다. service가 아직 loaded면
  exact label만 status 확인 후 정상 종료 상태를 대조하고 model unloaded를 확인한다.

- [ ] **Step 2: Owner 감사 전 기술 verdict를 확정한다**

  `LIVE_SHADOW_TECHNICAL_PASS | INCOMPLETE_LIVE_VOLUME | REJECT_RELIABILITY | REJECT_RESOURCE |
  REJECT_INTEGRITY` 중 하나를 TEST-SHEET 우선순위대로 고른다. 품질 감사 전 사용자 노출을 승인하지 않는다.

- [ ] **Step 3: 보고서와 SOT를 갱신한다**

  aggregate·artifact SHA·service evidence·mutation 0·caveat·다음 행동을 기록하고 raw identity를 숨긴다.
  iTerm Claude 결과 review P0/P1을 반영한다.

- [ ] **Step 4: full verification 후 main에 fast-forward한다**

  focused/full pytest, compileall, diff check를 통과하고 feature를 push한다. origin/main이 ancestor인지
  확인한 뒤 force 없이 fast-forward push하고 exact SHA를 보고한다. 사용자 소유 `AGENTS.md`는 제외한다.
