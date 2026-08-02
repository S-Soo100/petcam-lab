# Local VLM Mac Studio 구매 판단 Gate v1 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 현재 MacBook에서 4B/12B/8B/30B 모델 사다리를 같은 시험으로 측정해 Mac Studio 구매 가설을 판정한다.

**Architecture:** pure 계약 모듈이 합성 장면·prompt·schema·채점을 소유하고, one-shot runner가 모델
수명주기·자원 감시·private artifact만 담당한다. 독립 recompute는 runner를 import하지 않고 frozen
manifest와 JSONL을 다시 채점한다.

**Tech Stack:** Python 3.12, OpenCV, NumPy, Ollama 0.32.5, pytest, uv.

## 공통 안전 경계

- development 74경계만 사용하고 holdout은 0개 접근한다.
- Mac mini의 기존 frozen manifest/input/media만 read-only 복사하며 DB/R2/service/GT 접근·write는 0이다.
- 모델별 합성 Gate 통과 전 사람-final GT를 열지 않는다.
- prompt·sampler·gate·모델 순서는 첫 measured request 전에 SHA-256으로 동결한다.

### Task 1: 사전등록과 pure 계약 TDD

**Files:**
- Create: `experiments/local-vlm-mac-studio-purchase-gate-v1/TEST-SHEET.md`
- Create: `scripts/local_vlm_purchase_gate.py`
- Create: `tests/test_local_vlm_purchase_gate.py`

- [x] 4개 모델, 합성 장면, development gate, 자원 한도, 구매 판정을 TEST-SHEET에 동결한다.
- [x] 12-frame 합성 장면과 실제 schema의 8-frame A/B 경계 2개×2회를 RED 테스트로 고정한다.
- [x] strict JSON parser, synthetic scorer, development scorer, purchase verdict를 RED→GREEN으로 만든다.

### Task 2: one-shot runner TDD

**Files:**
- Create: `scripts/run_local_vlm_purchase_gate.py`
- Create: `tests/test_run_local_vlm_purchase_gate.py`

- [x] 새 private output, mode, frozen manifest, model digest, input hash를 fail-closed한다.
- [x] 합성 2회 전수 통과 모델만 development 74개를 실행한다.
- [x] timeout 180초, retry 0, 2초 자원 표본, free≤3%×2, swap +2GiB, PID drift를 구현한다.
- [x] 모델 전환 load/unload와 중단 뒤 unload를 검증한다.

### Task 3: 독립 재계산 TDD

**Files:**
- Create: `scripts/recompute_local_vlm_purchase_gate.py`
- Create: `tests/test_recompute_local_vlm_purchase_gate.py`

- [x] runner import 없이 manifest/results의 모델·입력·prompt digest를 검증한다.
- [x] synthetic와 development score를 독립 재계산한다.
- [ ] runner summary와 score/verdict subtree exact 일치를 measured artifact에서 검증한다.

### Task 4: 교차검수·검증·동결

- [x] iTerm2 공식 AppleScript로 지정된 Claude RBA 세션에 설계/계획을 교차검수한다.
- [x] 채택한 P0/P1을 문서와 테스트에 반영한다.
- [x] focused tests, full tests, compileall, diff/privacy 감사를 통과한다.
- [ ] 문서·구현을 승인된 commit으로 동결하고 기존 격리 worktree의 exact HEAD에서만 측정한다.

### Task 5: MacBook measured run과 보고

- [x] Ollama 0.32.5를 확인하고 후보 tag/digest를 고정한다.
- [x] 기존 frozen manifest, 74 combined input, ledger의 media 78개를 private root로 복사해 mode/hash를 확인한다.
- [x] 원본 media의 A/B contact sheet 조합을 재생성해 frozen combined SHA와 exact 일치하는 pair를 74/74 유일 복원한다.
- [x] 재생성은 `uv.lock`의 OpenCV 버전으로 실행하고 mismatch면 추측·perceptual fallback 없이 중단한다.
- [x] 복원된 원본에서 긴 변 768px 이하 A4+B4를 재추출하고 input hash를 동결한다.
- [ ] 4B→12B→8B→30B 순서로 합성 Gate와 조건부 development run을 자동 수행한다.
- [ ] 독립 recompute, model unload, production mutation 0을 확인한다.
- [ ] `REPORT.md`, `specs/next-session.md`, decision gate 실행 결과에 구매 판정을 기록한다.
