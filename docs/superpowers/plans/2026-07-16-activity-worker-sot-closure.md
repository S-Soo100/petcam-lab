# Activity Worker SOT Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검증 완료된 activity-worker Mac mini 단일 호스트 이전을 petcam-lab의 현재 실행 SOT와 Python Evidence Hybrid 설계에 정확히 반영하고, 관련 handoff 산출물을 감사 가능한 Git 기록으로 남긴다.

**Architecture:** 다른 세션이 만든 현재 dirty 문서를 새 worktree로 우회하지 않고 동일 worktree에서 사실 정합만 수정한다. `specs/next-session.md`와 hybrid design의 stale runtime 문구를 closure evidence로 교정하되 historical 기록과 selector 동결 기준점은 보존한다. 커밋은 명시한 문서만 stage하고 코드·DB·runtime은 건드리지 않는다.

**Tech Stack:** Markdown, Git, Python 3.12 handoff validator, ripgrep

## Global Constraints

- 실행 레포: `/Users/baek/petcam-lab`, branch `main`. 실행 시작 시 HEAD와 origin/main이 같고 이 plan과 design이 HEAD에 tracked 상태여야 한다.
- 새 worktree나 branch switch를 하지 않는다. 현재 dirty `specs/next-session.md`와 untracked hybrid design은 같은 세션 계보이므로 그 내용을 보존하며 정합화한다.
- 다음 두 이상한 이름의 untracked 파일은 사용자/다른 세션 소유다. read/add/modify/delete/rename/commit 금지:
  - 이름이 `)`로 시작하고 `legacy_minute0` 문자열을 포함하는 파일
  - 이름이 `0 || true)`로 시작하고 `minute35` 문자열을 포함하는 파일
- 코드, migration, DB, LaunchAgent, Slack, VLM, Gate, Flutter는 변경하지 않는다.
- 기존 historical 설명은 삭제하지 않고 `SUPERSEDED` 표기나 현재 정본 블록으로 관계를 명확히 한다.
- runtime 현재 SHA는 nightly `cbd2e09ed00857bdbd8a27c3f0483881c9abdbd6`, lab `df7811c12e3518096c92271b5e549d9154468001`, gate `9e39596bdb907a86496948f4bf3a13fe760d8222`다.
- production selector 알고리즘 동결 기준 `b9dc9eb`은 current runtime SHA가 아니므로 변경하지 않는다.
- 민감값, 전체 UUID, raw URL, token을 문서에 추가하지 않는다.
- Claude 실행 결과는 `/Users/baek/petcam-lab/docs/handoff-prompts/2026-07-16-activity-worker-sot-closure-report.md`에 작성한다.

---

### Task 1: 변경 전 소유권과 증거 동결

**Files:**
- Read only: `specs/next-session.md`
- Read only: `docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`
- Read only: `docs/handoff-prompts/2026-07-16-activity-worker-single-host-*.md`

**Interfaces:**
- Consumes: 현재 dirty worktree와 closure evidence
- Produces: stage 허용 목록과 변경 전 hash 기록

- [ ] **Step 1: 시작 상태를 기록한다**

Run:

```bash
cd /Users/baek/petcam-lab
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
```

Expected: branch `main`, HEAD와 origin/main 동일, plan/design tracked. 다르면 수정하지 말고 `BLOCKED`로 보고한다.

- [ ] **Step 2: 기존 4개 handoff 산출물의 hash를 기록한다**

Run:

```bash
shasum -a 256 \
  docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration.md \
  docs/handoff-prompts/2026-07-16-activity-worker-single-host-manifest.md \
  docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration-report.md \
  docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration-closure-report.md
```

Expected: 네 파일 모두 존재하며 hash 4개가 출력된다. 이후 Task 5에서 동일해야 한다.

- [ ] **Step 3: closure 근거를 재확인한다**

Run:

```bash
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/petcam-lab/docs/handoff-prompts/2026-07-16-activity-worker-single-host-manifest.md
```

Expected:

```text
HANDOFF_OK task=activity-worker-single-host-closure repo=petcam-nr-activity-wt commit=cbd2e09e runtime=launchagent@baeg-endeuui-Macmini.local
```

실행 worktree가 사라져 validator가 실패한다면 문서 내용을 추측 수정하지 말고 `BLOCKED`로 보고한다.

---

### Task 2: `next-session.md` 현재 실행 정본 교정

**Files:**
- Modify: `specs/next-session.md:5`
- Modify: `specs/next-session.md:19`

**Interfaces:**
- Consumes: closure report의 final SHA, host, cycle, settings evidence
- Produces: 다음 세션이 가장 먼저 읽는 현재 runtime 정본

- [ ] **Step 1: 상단 live runtime 블록을 현재 사실로 교체한다**

`specs/next-session.md` 상단의 `🔴 2026-07-16 live runtime 재검증` 문단 전체를 다음 문단으로 교체해:

```markdown
> **🔴 2026-07-16 live runtime 정본 — single-host closure VERIFIED:** Mac mini `baeg-endeuui-Macmini.local`에서 production background worker를 실행한다. nightly-reporter runtime HEAD는 `cbd2e09`이고, lab `df7811c`, gate `9e39596`가 현재 코드 기준이다. **① 정규 VLM candidate** `com.petcam.vlm-candidate-worker`는 Mac mini 단일 호스트에서 22/00/02/04:00 KST 실행하며 MacBook에는 없다. **② rolling backfill** `com.petcam.vlm-historical-backfill`은 Mac mini에서 매시 :35 실행한다. **③ activity-worker** `com.petcam.activity-worker`도 Mac mini 단일 호스트로 이전됐고 `ACTIVITY_EXPECTED_HOST` fail-closed, `activity-v1`, `StartInterval=3600` 계약으로 실행한다. 첫 RunAtLoad는 `queried=88 / ok=88 / fail=0 / exit 0`, 두 번째 자연 StartInterval은 미처리 0건으로 exit 0이었고 MacBook service/plist는 absent다. activity evidence 7컬럼 결손·중복 0, exclusion settings와 `behavior_labels` 불변을 확인했다. 근거: [`activity-worker migration closure report`](../docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration-closure-report.md) · [`Python Evidence Hybrid 설계`](../docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md).
```

- [ ] **Step 2: 활동필터 현재 상태 문단의 host만 교정한다**

`현재 상태(정본)` 문단에서 다음 의미를 유지한 채 첫 문장만 현재 runtime으로 바꿔:

```markdown
> **현재 상태(정본):** Mac mini의 `com.petcam.activity-worker`가 테스트 카메라 3대를 매시간 `activity-v1`으로 분석한다. MacBook의 worker는 제거됐고, expected-host 불일치·미설정 시 DB/R2/detector 이전에 nonzero 종료한다.
```

같은 문단의 Flutter SHA, `exclude_static_enabled`, `exclude_absent_enabled`, simulator, `8h 50m → 8h 45m`, static 10 clip·320.4초 내용은 그대로 보존해.

- [ ] **Step 3: historical 블록을 삭제하지 않았는지 확인한다**

Run:

```bash
rg -n "SUPERSEDED|candidate LaunchAgent는 MacBook에서 발견|rolling PENDING" specs/next-session.md
```

Expected: 과거 오류·중간 상태는 historical/SUPERSEDED 기록으로 남아 있다. 현재 정본 블록만 최신 사실을 말한다.

---

### Task 3: Python Evidence Hybrid 설계의 runtime 사실 교정

**Files:**
- Modify: `docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`

**Interfaces:**
- Consumes: activity-worker closure evidence
- Produces: architecture 판단은 유지하고 host·runtime·coverage open question만 최신화한 설계 정본

- [ ] **Step 1: runtime inventory를 교정한다**

다음 의미가 되도록 §0.1~§0.3의 runtime 표와 설명을 수정해:

- nightly runtime HEAD: `cbd2e09ed00857bdbd8a27c3f0483881c9abdbd6`
- `com.petcam.activity-worker`: Mac mini, 매시간, `activity-v1`, expected-host fail-closed
- MacBook: activity-worker absent, decommissioned plist 백업만 보존
- Mac mini temp media 0

- [ ] **Step 2: SOT 모순 3번 항목을 해결 완료 상태로 바꾼다**

activity-worker host 모순 항목은 다음 문구를 사용해:

```markdown
3. **activity-worker 호스트 — RESOLVED:** 초기 live audit에서 MacBook 오배치를 발견했다. 이후 host guard와 partial-failure nonzero exit를 추가하고 Mac mini로 단일 이전했다. 현재 Mac mini `com.petcam.activity-worker`만 loaded이며 MacBook은 absent다. 첫 실사이클 88/88 성공과 자연 두 번째 cycle exit 0을 확인했다.
```

- [ ] **Step 3: 데이터 흐름과 책임 표의 host를 교정한다**

다음 stale 표현을 모두 Mac mini runtime으로 바꿔:

- `MacBook activity-worker(테스트 카메라)` → `Mac mini activity-worker(테스트 카메라)`
- `(테스트 카메라, MacBook) activity-worker` → `(테스트 카메라, Mac mini) activity-worker`
- `activity-worker는 MacBook 테스트 카메라만 상시 가동` → `activity-worker는 Mac mini에서 테스트 카메라 3대를 상시 처리`

- [ ] **Step 4: coverage 미확인 항목은 제거하지 말고 정확히 좁힌다**

다음 의미를 §1·§17에 반영해:

```markdown
호스트 오배치 문제는 해결됐고 Mac mini producer evidence 88건을 실측했다. 다만 전체 카메라·날짜별 `clip_prelabels` 채움률과 selector 입력 시점의 coverage는 아직 산출하지 않았으므로 S0 read-only 감사 항목으로 유지한다.
```

`production 채움률 미확인`을 전부 `확인 완료`로 바꾸면 안 된다.

- [ ] **Step 5: selector 동결 기준은 보존한다**

다음 두 표현은 current runtime SHA로 치환하지 마:

- `production_selector_rank` 동결 대응표의 `@ b9dc9eb`
- `reporter/vlm_selector.py::select_candidates @ b9dc9eb`

그 앞에 다음 한 문장을 추가해 runtime SHA와의 차이를 설명해:

```markdown
현재 runtime HEAD는 `cbd2e09`지만 selector 알고리즘 비교군은 변경이 없었던 `b9dc9eb` 구현을 동결 기준으로 유지한다.
```

- [ ] **Step 6: stale runtime 표현을 검사한다**

Run:

```bash
rg -n "MacBook activity-worker|activity-worker는 MacBook|MacBook에만 존재|테스트 카메라, MacBook" \
  docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md
```

Expected: 현재 사실을 주장하는 stale 표현 0건. historical discovery 문맥에서 MacBook 오배치를 설명하는 문장은 허용하지만 반드시 `initial audit`, `RESOLVED`, `이전` 중 하나와 같은 문맥이어야 한다.

---

### Task 4: 문서 정합성과 비밀값 감사

**Files:**
- Verify: `specs/next-session.md`
- Verify: `docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`
- Verify: handoff 산출물 4개

**Interfaces:**
- Consumes: Tasks 2~3 수정 결과
- Produces: 모순·placeholder·secret 없는 문서 집합

- [ ] **Step 1: 현재 정본의 필수 사실을 검사한다**

Run:

```bash
rg -n "cbd2e09|Mac mini.*activity-worker|MacBook.*absent|queried=88|StartInterval" \
  specs/next-session.md \
  docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md
```

Expected: 두 SOT에서 closure 사실을 찾을 수 있다.

- [ ] **Step 2: placeholder와 whitespace를 검사한다**

Run:

```bash
rg -n "TBD|TODO|fill in|implement later" \
  specs/next-session.md \
  docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md \
  docs/handoff-prompts/2026-07-16-activity-worker-single-host-*.md || true
git diff --check
```

Expected: 새 placeholder 0건, `git diff --check` exit 0.

- [ ] **Step 3: 민감값 패턴을 검사한다**

Run:

```bash
if rg -n "gho_|sb_secret_|service_role.*[A-Za-z0-9_-]{20,}|token=|cloudflarestorage\.com" \
  specs/next-session.md \
  docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md \
  docs/handoff-prompts/2026-07-16-activity-worker-single-host-*.md; then
  echo "SECRET_PATTERN_FOUND"
  exit 1
fi
```

Expected: 출력 없이 exit 0.

- [ ] **Step 4: handoff validator 회귀 테스트를 실행한다**

Run:

```bash
uv run pytest -q tests/test_verify_agent_handoff.py
uv run python scripts/verify_agent_handoff.py \
  --manifest /Users/baek/petcam-lab/docs/handoff-prompts/2026-07-16-activity-worker-single-host-manifest.md
```

Expected: 테스트 전부 통과, `HANDOFF_OK ... commit=cbd2e09e ...`.

---

### Task 5: 제한된 stage·commit·push

**Files allowed in commit:**
- `specs/next-session.md`
- `docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md`
- `docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration.md`
- `docs/handoff-prompts/2026-07-16-activity-worker-single-host-manifest.md`
- `docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration-report.md`
- `docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration-closure-report.md`

**Interfaces:**
- Consumes: 검증된 문서 6개와 이미 tracked된 plan/design
- Produces: origin/main에 fast-forward된 SOT closure commit 1개

- [ ] **Step 1: 원본 handoff 산출물 hash를 재검사한다**

Task 1과 동일한 `shasum -a 256` 명령을 실행해.

Expected: `migration.md`, manifest, 1차 report, closure report의 hash가 Task 1 기록과 모두 같다. SOT 정리 과정에서 감사 산출물을 고치지 않았다는 증거다.

- [ ] **Step 2: 허용 파일만 명시적으로 stage한다**

Run:

```bash
git add \
  specs/next-session.md \
  docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md \
  docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration.md \
  docs/handoff-prompts/2026-07-16-activity-worker-single-host-manifest.md \
  docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration-report.md \
  docs/handoff-prompts/2026-07-16-activity-worker-single-host-migration-closure-report.md
git diff --cached --check
git diff --cached --name-only
```

Expected: 출력 파일은 위 6개와 정확히 일치한다. 이상한 shell 이름 파일 2개나 다른 파일이 나오면 `git restore --staged`로 허용 목록 밖 파일만 unstage하고 `BLOCKED`로 보고한다. 파일 내용을 되돌리거나 삭제하지 않는다.

- [ ] **Step 3: commit한다**

Run:

```bash
git commit -m "docs: activity-worker 단일 호스트 이전 SOT 마감"
```

Expected: docs commit 성공. `FINAL_SHA=$(git rev-parse HEAD)`를 기록한다.

- [ ] **Step 4: fast-forward push한다**

Run:

```bash
git fetch origin
git merge-base --is-ancestor origin/main HEAD
test "$(git rev-parse HEAD^)" = "$(git rev-parse origin/main)"
git push origin main
test "$(git rev-parse HEAD)" = "$(git ls-remote origin refs/heads/main | cut -f1)"
```

Expected: force 없이 handoff commit의 다음 commit으로 main이 fast-forward되고 local main == origin/main.

- [ ] **Step 5: 다른 세션 파일 보존을 확인한다**

Run:

```bash
git status --short
```

Expected: 이상한 shell 이름 untracked 파일 2개는 그대로 남아 있고, 허용한 6개 문서는 clean/tracked다. 이 두 파일을 정리하거나 커밋하지 않는다.

---

### Task 6: 실행 보고서 작성

**Files:**
- Create: `/Users/baek/petcam-lab/docs/handoff-prompts/2026-07-16-activity-worker-sot-closure-report.md`

**Interfaces:**
- Consumes: Tasks 1~5의 fresh output
- Produces: Codex 독립 검수용 보고서

- [ ] **Step 1: 다음 형식으로 작성한다**

```markdown
# Activity Worker SOT Closure Report

## 1. 최종 판정
VERIFIED 또는 BLOCKED

## 2. 수정한 SOT 사실
## 3. 보존한 historical/selector 기준
## 4. 추적한 handoff 산출물과 hash 불변
## 5. 검증 결과
## 6. commit SHA와 push 상태
## 7. commit에 포함된 정확한 6개 파일
## 8. 보존한 다른 세션 파일
## 9. 다음 단계
```

- [ ] **Step 2: 채팅 응답을 두 줄로 제한한다**

```text
최종 판정: VERIFIED|BLOCKED
보고서: /Users/baek/petcam-lab/docs/handoff-prompts/2026-07-16-activity-worker-sot-closure-report.md
```

Codex가 Git diff, SOT 문구, tracked 파일, origin/main을 독립 검수하기 전에는 다음 구현 단계로 넘어가지 않는다.
