# Production Local VLM Clip Shadow Canary v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mac mini Gemma 3 4B가 새 production clip의 개별 프레임 12장을 private shadow로 관찰하게 한다.

**Architecture:** v1의 검증된 source/privacy/ledger/resource/R2 계약은 재사용하고 v2 전용 12-frame
sampler, multi-image payload, Gate A, runner, recompute, LaunchAgent label을 분리한다.

**Tech Stack:** Python 3.12, OpenCV, NumPy, Supabase, boto3, Ollama 0.32.5, launchd, pytest, uv.

## Global Constraints

- v1 artifact/code/report를 결과 후 수정하지 않는다.
- 12개는 5~95% 균등, 개별 JPEG 12장, 긴 변 768, quality 90이다.
- model request 최대 20, timeout 120초, retry 0, 종료 2026-08-03 07:00 KST다.
- DB SELECT/R2 HEAD·GET/private artifact/exact v2 label 외 write는 금지한다.

---

### Task 1: 12-frame pure contract TDD

**Files:**
- Create: `scripts/local_vlm_clip_shadow_v2.py`
- Create: `tests/test_local_vlm_clip_shadow_v2.py`

- [ ] fractions 12개·strict 증가·5/95%와 개별 resize/JPEG를 RED로 고정한다.
- [ ] prompt/schema/payload가 이미지 12개를 순서대로 포함하는지 RED로 고정한다.
- [ ] 최소 구현 뒤 focused pytest를 통과하고 commit한다.

### Task 2: v2 runner·Gate A TDD

**Files:**
- Create: `scripts/run_local_vlm_clip_shadow_v2.py`
- Create: `tests/test_run_local_vlm_clip_shadow_v2.py`

- [ ] v1 read-only query·HMAC ledger·R2 transient/atomic media 계약을 재사용한다.
- [ ] dark/static/moving 12-image Gate와 production schema 1회를 fake Ollama로 검증한다.
- [ ] request intent에 input SHA 12개가 exact 순서로 기록되는지 검증한다.
- [ ] 60초 loop·max20·07:00·resource fail-closed·unload를 구현하고 commit한다.

### Task 3: independent recompute·v2 launchd TDD

**Files:**
- Create: `scripts/recompute_local_vlm_clip_shadow_v2.py`
- Create: `tests/test_recompute_local_vlm_clip_shadow_v2.py`
- Create: `scripts/manage_local_vlm_clip_shadow_v2_launchd.py`
- Create: `tests/test_manage_local_vlm_clip_shadow_v2_launchd.py`

- [ ] 독립 재계산은 runner import 없이 12 input hash·intent/result/resource를 검증한다.
- [ ] v2 exact label, RunAtLoad/KeepAlive false, Umask 077, secret value 0 plist를 검증한다.
- [ ] focused pytest를 통과하고 commit한다.

### Task 4: Claude review·전체 검증·handoff

- [ ] iTerm2 공식 AppleScript로 정확한 RBA Claude 세션에 설계·diff를 read-only 검수한다.
- [ ] P0/P1을 반영하고 full pytest·compileall·mutation rg·diff check를 통과한다.
- [ ] feature push·40자리 SHA handoff·`HANDOFF_OK`를 만든다.
- [ ] 검수된 계획과 안전 경계를 Slack 기존 thread에 공유한다.

### Task 5: Mac mini Gate·conditional service

- [ ] exact detached worktree와 private v2 runtime을 준비한다.
- [ ] foreground Gate A 4회를 실행한다.
- [ ] PASS일 때만 exact v2 plist를 install/kickstart하고 첫 자연 cycle을 확인한다.
- [ ] FAIL이면 production request 0·service 0 보고서를 남기고 종료한다.
