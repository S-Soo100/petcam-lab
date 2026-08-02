# Local VLM 사건 경계 Baseline v1 구현 계획

> **실행 계약:** Owner가 조사·설치·커스터마이징·구동·보고서까지 승인했다. development only,
> DB SELECT/R2 GET, Mac mini 격리 one-shot 범위를 넘지 않는다.

**목표:** 사람 final 경계 74개를 MiniCPM-V 4.6 1B와 Qwen3-VL 2B가 같은 frozen visual input에서
얼마나 안전하게 재현하는지 측정하고 development 후보를 판정한다.

**구조:** 순수 core가 sampler 위치·prompt·strict parser·scorer를 담당한다. Mac runner는 private
GT mapping, DB SELECT, R2 GET, OpenCV contact sheet, Ollama API, resource monitor를 조립한다. 독립
recompute script는 runner 함수를 import하지 않고 private JSONL을 다시 점수화한다.

**기술:** Python 3.12, OpenCV, boto3, Supabase, stdlib urllib, Ollama 0.32.5.

---

## Task 1. Core 계약 TDD

**파일:**

- 생성: `tests/test_local_vlm_event_boundary.py`
- 생성: `scripts/local_vlm_event_boundary.py`

**RED:** A/B sampling fraction, contact-sheet frame accounting, strict JSON parse, failure non-repair,
confusion/over-merge/over-split/same recall/Wilson CI, verdict priority 테스트를 먼저 작성한다.

**GREEN:** immutable dataclass와 순수 함수만 구현한다. filesystem/network/model import는 하지 않는다.

**검증:** `uv run pytest tests/test_local_vlm_event_boundary.py -q`

## Task 2. Private runner 안전 계약 TDD

**파일:**

- 생성: `tests/test_run_local_vlm_event_boundary.py`
- 생성: `scripts/run_local_vlm_event_boundary.py`

**RED:** exact host, `0700/0600`, no-overwrite, 74/74 HMAC mapping, DB SELECT allowlist, R2 HEAD→GET,
78/78 decode preflight, deterministic input hash, two-image smoke fallback, retry 0, raw output 4KB cap,
service snapshot/redaction을 fake client로 검사한다.

**GREEN:** 외부 의존은 runtime injection 또는 lazy import로 구현한다. DB/R2 write method는 runner에
노출하지 않는다. raw ID/key는 private manifest 안에서도 최소화하고 public summary에는 digest·count만
쓴다.

**검증:** `uv run pytest tests/test_run_local_vlm_event_boundary.py -q`

## Task 3. 독립 scorer TDD

**파일:**

- 생성: `tests/test_recompute_local_vlm_event_boundary.py`
- 생성: `scripts/recompute_local_vlm_event_boundary.py`

**RED:** duplicate/missing/unexpected key, model digest drift, input hash drift, summary mismatch, public raw UUID
검사를 작성한다.

**GREEN:** runner module을 import하지 않고 JSONL·frozen manifest만 읽어 모델별 지표와 verdict를
재계산한다.

**검증:** `uv run pytest tests/test_recompute_local_vlm_event_boundary.py -q`

## Task 4. 로컬 회귀·handoff

**파일:**

- 생성: `docs/handoffs/2026-08-02-local-vlm-event-boundary-v1.md`

1. 관련 테스트와 전체 `uv run pytest` 실행.
2. `git diff --check`, secret/raw-ID pattern 검사.
3. 구현 commit을 origin에 push.
4. exact 40자리 SHA와 절대 plan/design 경로로 handoff manifest 작성·commit·push.
5. `uv run python scripts/verify_agent_handoff.py --manifest <absolute-path>`에서 `HANDOFF_OK` 확인.

## Task 5. Mac mini 격리 설치

**실행 위치:** `/Users/baek-end/petcam-lab-local-vlm-event-boundary-v1`

1. clean detached worktree를 exact handoff SHA로 만든다.
2. hostname, arch, RAM, disk, Ollama version/PID/model list, production service snapshot을 저장한다.
3. private root를 mode `0700`으로 `O_EXCL` 생성한다.
4. Ollama 공식 CLI로 `minicpm-v4.6:latest`, `qwen3-vl:2b`를 pull한다.
5. 실제 digest·size·license source URL을 runtime snapshot에 고정한다.
6. 기존 model count/digest는 삭제·변경하지 않았는지 확인한다.

## Task 6. Mac mini capability·media preflight

1. 두-image attention 합성 smoke를 모델별 1회 실행한다.
2. TEST-SHEET 규칙으로 `two_images|combined_4x2`를 한 번 선택한다.
3. 선행 분석의 `0600`, 32-byte `run-salt.bin`을 재사용해 base manifest와 final private artifact를
   HMAC으로 74/74 mapping한다.
4. DB SELECT로 unique clip 78개의 non-empty R2 key만 얻는다.
5. R2 HEAD 78/78 뒤 GET 78/78, SHA-256·size·OpenCV decode를 검사한다.
6. `two_images=148장` 또는 `combined_4x2=74장`을 생성하고 input manifest hash를 freeze한다.

하나라도 실패하면 measured run을 시작하지 않고 blocker report를 만든다.

## Task 7. 두 모델 measured run

1. frozen order의 첫 모델을 명시적으로 load한 뒤 `keep_alive=15m`로 74회 실행하고, empty messages
   + `keep_alive=0` unload 뒤 둘째 모델을 같은 방식으로 74회 실행한다.
2. 요청마다 model/input/prompt/options digest, latency, parse status만 private JSONL에 append+fsync한다.
3. 2초 resource monitor와 fail-closed 중단 기준을 적용한다.
4. request timeout 120초·retry 0과 모델 사이 unload, runner process/RSS를 확인한다.
5. run 전후 Ollama/service snapshot을 비교한다.

## Task 8. 독립 재계산·보고서

**파일:**

- 생성: `experiments/local-vlm-event-boundary-v1/REPORT.md`
- 수정: `experiments/local-vlm-event-boundary-v1/TEST-SHEET.md`
- 수정: `specs/next-session.md`
- 수정: `docs/AI-VIDEO-ANALYSIS-STRATEGY.md`
- 수정: `specs/feature-rba-data-engine-v1.md`

1. independent scorer와 runner summary의 모델별 `score`·`latency_sec` subtree가 정확히 같은지
   확인한다. `load_sec`은 measured JSONL 밖의 runner 전용 cold-load metadata라 비교에서 제외한다.
2. 모델별 confusion, safety/utility verdict, Wilson CI, latency/resource/disk를 보고한다.
3. 오류 유형은 aggregate reason code만 공개한다.
4. self-adjudication·development-only·no holdout·no production caveat를 적는다.
5. 설치 model digest와 private artifact SHA만 공개하고 media/GT identity는 숨긴다.

## Task 9. Claude 결과 교차검수·통합

1. iTerm2 공식 AppleScript로 같은 Claude 세션에 TEST-SHEET·REPORT·aggregate만 read-only 전달한다.
2. P0/P1 finding을 실제 artifact·코드와 대조해 수정하고 focused/full test를 재실행한다.
3. `verification-before-completion` 체크: exact Mac host/HEAD/run, 148 measured records, service invariant,
   full tests, `git diff --check`.
4. approved feature branch를 main에 fast-forward하고 origin main과 exact SHA를 확인한다.
5. production service는 활성화하지 않는다.
