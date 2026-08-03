# VLM 사건 경계 밀집 v2 테스트 시험지

> **상태:** `PRE_REGISTERED_LOCKED_BEFORE_INFERENCE`
> 입력 생성은 평가 전 데이터 준비로 먼저 끝냈고, 아래 dense manifest SHA와 TEST-SHEET SHA를 고정한
> 뒤에만 모델 호출을 시작해.

## 0. 연구 질문과 가설

전체 영상에서 듬성듬성 뽑은 4+4장이 아니라 **A 종료 직전과 B 시작 직후 6+6장**을 촘촘히 보면,
GPT 또는 local VLM이 owner-final 사건 경계 74개에서 다른 사건을 하나로 합치지 않으면서 같은 사건의
절반 이상을 찾을 수 있는가?

- H0: 다섯 모델 모두 safety/utility gate를 통과하지 못해.
- H1: 한 모델 이상이 schema 74/74, over-merge 0, same correct 29/57 이상을 동시에 만족해.

기존 4+4 결과는 입력이 연구 질문의 경계 정보를 충분히 보존하지 않아
`INVALID_INPUT_REPRESENTATION_FOR_BOUNDARY_DECISION` 이력으로만 남겨. 이번 결과와 비교는 하되 채택
기준선으로 사용하지 않아.

## 1. 고정 표본과 입력

- owner-final development 경계: 74 (`same_event=57`, `different_event=17`)
- unique clip: 78
- 기존 source manifest SHA-256:
  `a0bd6ef5073508a14dd9be66cad9d65dea06d4ef4800a0a687af31c1b9163236`
- dense frozen manifest SHA-256:
  `df1f98e24fd51246cca993c3240a725f3ce5c14a66da1473df7b4f189ba7f46d`
- dense JPEG: pair당 A/B 2장, 총 148장, manifest hash 148/148 exact
- image shape: 1080×628, 각 영상별 3열×2행, 좌→우·위→아래 시간순
- A sampling: 종료 전 `6, 4, 2, 1, 0.5, 0.1초`
- B sampling: 시작 후 `0.1, 0.5, 1, 2, 4, 6초`
- 각 frame 시간 label은 원본 영상 위가 아닌 별도 header에 표시해 좌하단 camera timestamp를 가리지 않아.
- 사람 UI에 보였던 A→B 미촬영 gap seconds도 두 sheet header에 표시해.

pair/GT/원본 clip은 기존 owner-final development 표본 그대로고, 프레임 표현만 바꿔. 이 표본은 새
holdout이 아니므로 통과해도 production 자동 병합 승인이 아니라 `DEVELOPMENT_CANDIDATE`까지만 가능해.

## 2. 모델과 runtime

### ChatGPT 구독 Codex CLI

1. `gpt-5.4-mini`
2. `gpt-5.6-luna`
3. `gpt-5.6-terra`

- ChatGPT subscription login, Codex CLI image input
- `--ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check`
- sandbox `read-only`, reasoning `low`, structured JSON schema
- pair당 process 1회, retry 0, timeout 240초
- 모델 순서와 manifest pair 순서 고정
- pair cwd에는 A/B blind JPEG 두 장만 존재해.
- JSON event에서 command/file/MCP/web/plan 접근이 하나라도 나오면 integrity reject야.
- `429/rate limit/usage limit/quota`는 품질 실패가 아닌 `INCONCLUSIVE_QUOTA`로 분리해.

### Mac mini local VLM

4. `minicpm-v4.6:latest`
5. `qwen3-vl:2b`

- Ollama exact installed digest 기록
- `temperature=0`, `seed=20260803`, `think=false`, JSON schema
- `num_ctx=8192`, `num_predict=96`
- 측정 전에 image A의 `red square`와 image B의 `blue triangle`을 **둘 다** 맞혀야 하는 two-image
  합성 smoke를 모델별 1회 실행해. 실패 모델은 measured score를 만들지 않고
  `INCONCLUSIVE_INPUT_REPRESENTATION`으로 기록해.
- measured 응답마다 `prompt_eval_count`를 기록하고 `prompt_eval_count + 96 <= 8192`여야 해. 0이거나
  budget을 넘으면 `INCONCLUSIVE_CONTEXT_BUDGET`으로 기록해.
- pair당 호출 1회, retry 0, timeout 180초
- 모델 한 개씩 load/unload하고 memory/swap guard를 유지해.
- resource abort나 load/schema failure는 reliability failure로 그대로 기록해.

예상 measured 호출은 GPT 222회 + local 148회 = 총 370회고 local smoke 2회가 별도야. GPT는 구독 CLI라 별도 API 과금 ledger가 없고,
이 시험으로 API 가격·Batch 처리량은 주장하지 않아.

## 3. Prompt와 출력

- prompt version: `vlm-event-boundary-dense-v2`
- representation: `boundary_dense_two_images_6x2`
- A 전체/B 전체의 닮음을 보지 말고 **A 끝과 B 시작 사이 경계**를 판단하라고 명시해.
- 출력은 `decision`, `confidence`, `reason_code` 3-key JSON이야.
- decision: `same_event | different_event | uncertain`

모델에는 human decision, pair digest 의미, clip id, 행동 label, Python Evidence, Gate, reviewer, DB/R2
경로를 전달하지 않아.

## 4. GT 격리와 무결성

- 모델 실행 ledger에는 `human` key가 없어야 해.
- parent runner만 private manifest를 읽고 모델에는 두 JPEG와 prompt/schema만 전달해.
- 모든 모델 호출이 끝난 뒤 deterministic scorer가 pair token으로 사람 정답을 join해.
- GPT 결과는 runner를 import하지 않는 별도 recompute로 score/latency/ledger SHA를 대조해.
- local 결과도 raw GT를 출력하지 않는 별도 재계산으로 confusion/score를 대조해.
- private root/inputs/run은 `0700`, manifest/ledger/summary는 `0600`이야.
- DB는 pair identity read-only 조회만 허용했고 dense 입력 준비에서 완료됐어. 평가 실행은 DB/R2에 접근하지 않아.
- production DB/R2/GT/submission/event/skip/UI/service/git은 수정하지 않아.

## 5. 사전 지표와 합격 기준

모델별로 다음을 계산해.

- schema-valid / 74
- same correct / 57, different correct / 17
- over-merge: 사람 `different`, 모델 `same`
- over-split: 사람 `same`, 모델 `different`
- uncertain
- confusion matrix
- latency p50/p95/max와 model wall time

판정 순서는 고정이야.

1. schema-valid < 74 또는 실행 실패 → `REJECT_RELIABILITY`
2. over-merge ≥ 1 → `REJECT_SAFETY`
3. same correct < 29/57 → `REJECT_UTILITY`
4. 위 조건을 모두 통과 → `DEVELOPMENT_CANDIDATE`

GPT의 over-merge=1 또는 over-merge=0이면서 same correct 27~31이면 구독 CLI 비결정성 경계로
`INCONCLUSIVE_NONDETERMINISTIC_BORDERLINE`을 함께 표시하지만 safety gate를 완화하지 않아.

## 6. 결과 해석 규칙

- 한 모델 이상 통과: dense 입력은 개발 후보로 유지하고 독립 future holdout을 다음 gate로 제안해.
- 전 모델 safety 실패: 자동 사건 병합은 계속 금지해. local/GPT를 바꾸는 것만으로 해결됐다고 보지 않아.
- schema/quota/resource 때문에 비교 불가: 해당 모델만 inconclusive/reliability reject로 남겨.
- two-image smoke/context budget 실패: 모델 품질 오답으로 세지 않고 해당 입력 경로를 inconclusive로 남겨.
- 기존 4+4 대비 좋아져도 사전 절대 gate를 못 넘으면 채택하지 않아.
- 이 시험은 사건 경계 전용이므로 행동 이름·케어 판단·월 2만건 VLM 품질로 확대해석하지 않아.

## 7. 실행 전 체크

- [x] 같은 owner-final 74 pair identity 확인
- [x] cached media 78/78 size+SHA exact
- [x] dense JPEG 148/148 manifest SHA exact
- [x] sampling/prompt/layout unit test
- [x] legacy 1-image + dense 2-image runner regression test
- [ ] TEST-SHEET SHA-256 기록
- [ ] iTerm Claude 공식 AppleScript 계획 교차검수 `P0=0, P1=0`
- [ ] 다섯 모델 measured run
- [ ] 독립 recompute와 report
