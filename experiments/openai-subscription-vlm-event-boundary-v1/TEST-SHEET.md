# OpenAI 구독 VLM 사건 경계 v1 테스트 시험지

> **상태:** `PRE_REGISTERED_V2_FOR_IMMEDIATE_EXECUTION`
> owner 지시: 승인 재요청 없이 Mac mini에서 바로 실행하고 성적표·Slack 보고까지 완료한다.
>
> **preflight attempt 0:** 최초 실행은 GPT-5.4 Mini `67/74` 지점에서 Claude 교차검수의 GT 격리
> P0를 확인해 중단했다. 67건은 구조화 응답 `67/67`, CLI tool/file event `0`이지만 실행 중 private
> ledger에 human decision이 함께 기록되는 설계였으므로 성적에 사용하지 않는다. 결과를 채점하거나
> 모델 비교에 쓰기 전에 중단했고, 아래 v2 격리 계약으로 새 output dir에서 0부터 다시 실행한다.

## 0. 연구 질문

ChatGPT 구독으로 인증된 Codex CLI의 비용 후보 GPT 모델이 local VLM과 동일한 development 사건 경계
74개를 보고, 실제 다른 사건 17개를 하나로 잘못 합치지 않으면서 같은 사건 57개의 절반 이상을
찾을 수 있는가?

## 1. 고정 표본

- source: `local-vlm-event-boundary-v1`의 frozen `combined_4x2` 입력
- frozen manifest SHA-256: `a0bd6ef5073508a14dd9be66cad9d65dea06d4ef4800a0a687af31c1b9163236`
- pair: 74 (`same_event=57`, `different_event=17`, human uncertain=0)
- unique clip: 78
- image: pair당 기존 `*-AB.jpg` 정확히 1장, 총 74장
- 입력 JPEG SHA-256은 frozen manifest와 74/74 exact 일치해야 한다.
- historical/future holdout, 행동 GT, DB, R2는 접근하지 않는다.

## 2. 모델·runtime

Mac mini의 `codex login status=Logged in using ChatGPT`와 model cache에서 아래 slug가 모두 실제로
보일 때만 실행한다.

1. `gpt-5.4-mini`
2. `gpt-5.6-luna`
3. `gpt-5.6-terra`

공통 계약:

- Codex CLI `--ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check`
- sandbox `read-only`
- `model_reasoning_effort=low`
- pair당 CLI process 1회, retry 0
- 모델 순서와 pair 순서는 위 목록 및 frozen manifest 순서로 고정
- output schema는 기존 `RESULT_SCHEMA`와 exact 동등
- timeout 240초. timeout/nonzero/invalid JSON은 그 pair의 reliability failure다.
- 구독 잔여 quota를 읽는 공식 CLI preflight는 확인되지 않았다. `429`, `rate limit`, `usage limit`,
  `quota` 오류는 모델 품질 실패가 아닌 `INCONCLUSIVE_QUOTA`로 분리한다.
- 모델 사이 인위적 병렬 호출은 금지하고 위 순서로 직렬 실행한다.

`codex-auto-review`와 coding speed 비교용 모델은 비용 후보가 아니므로 제외한다. 이번 결과는 구독 CLI
wrapper를 포함한 feasibility 측정이며 API Batch의 처리량·가격·결정론을 대신 증명하지 않는다.
요청 slug와 model cache 존재는 기록하지만 현재 공개 CLI event가 실제 backend serving model id를
제공하지 않으므로 alias 내부 identity exact 검증은 주장하지 않는다.

## 3. 입력·prompt

local VLM v1의 `PROMPT_VERSION=local-vlm-event-boundary-v1`, prompt 본문, `combined_4x2` JPEG를
그대로 사용한다. 모델에는 human decision, pair digest의 의미, 원본 clip id, 행동 label, Python
Evidence, Gate, reviewer 정보가 전달되지 않는다.

### 3.1 GT 격리 v2 hard gate

- source manifest는 parent runner가 실행 전에 한 번 읽고 모델 process에는 경로·내용을 전달하지 않는다.
- 각 CLI process의 cwd는 `0700` pair 전용 directory이고 exact input JPEG 1장만 둔다.
- 실행 중 frozen-run과 measured ledger에는 human decision을 기록하지 않는다.
- `codex exec --json` event를 전수 검사해 허용 item은 `reasoning|agent_message`뿐이다.
- command/file/MCP/web/plan 등 다른 item이 한 번이라도 나오면 즉시 `REJECT_INTEGRITY`로 전체 run을
  중단하고 해당 output을 성적에 쓰지 않는다.
- 모델 호출이 모두 끝난 뒤 독립 scorer가 source manifest와 GT-free ledger를 pair token으로 join한다.

모델 출력은 아래 세 key만 허용한다.

- `decision`: `same_event|different_event|uncertain`
- `confidence`: 0~1 number
- `reason_code`: `continuous_motion|continuous_posture|clear_stop|new_activity|scene_discontinuity|insufficient_visual`

## 4. 지표와 판정

- completed/schema-valid/failure
- confusion matrix
- over-merge: human different → model same
- over-split: human same → model different
- same recall + Wilson 95% CI
- different recall, uncertain rate
- latency p50/p95/max, model wall time

판정 우선순위:

1. manifest/input/prompt/model drift → `REJECT_INTEGRITY`
2. completed 또는 schema-valid 74/74 미달 → `REJECT_RELIABILITY`
3. over-merge > 0 → `REJECT_SAFETY`
4. same correct < 29/57 → `REJECT_UTILITY`
5. 모두 통과 → `DEVELOPMENT_CANDIDATE`

구독 CLI는 API temperature/seed를 고정할 수 없는 one-shot 비결정 실행이다. `over-merge=1` 또는
`same correct=27~31`이면 위 quality verdict와 별도로 `INCONCLUSIVE_NONDETERMINISTIC_BORDERLINE`로
내리고 이 결과만으로 모델 순위를 확정하지 않는다. 이번 시험에서 사후 재실행은 하지 않는다.

모델 간 우선순위는 `DEVELOPMENT_CANDIDATE`끼리만 same recall, different recall, p95 순서로 정한다.
통과해도 API production 활성화가 아니라 300건 owner-final API pilot 후보 자격만 얻는다.

## 5. 저장·안전

- Mac private root와 run dir `0700`, schema/manifest/ledger/summary `0600`
- raw response는 private ledger에 pair token과 함께 최대 4KB만 저장
- model measured ledger는 GT-free이며 human decision key를 금지
- 공개 보고에는 aggregate와 digest만 기록
- Supabase/R2/GT/submission/cohort/slot/service/queue/git HEAD/production worker 수정 0
- 자동 병합, 자동 skip, 사용자 노출, API key 생성·연결 0
- 기존 local input과 결과는 read-only로 재사용하며 덮어쓰지 않는다.

## 6. 완료 체크

- [x] TEST-SHEET SHA-256 동결
- [x] host/CLI/ChatGPT login/model slug preflight
- [x] source manifest/input 74/74 exact hash
- [x] 세 모델 measured run: 222/222 schema-valid, retry/error/quota 0
- [x] 독립 aggregate 재계산 exact 일치
- [x] CLI event tool/file 접근 0 및 GT-free ledger 확인
- [x] REPORT/INDEX/next-session/decision-gate 갱신
- [x] Slack 결과 공유

## 7. 실행 결과

- GPT-5.4 Mini: over-merge 12, same 56/57, different 2/17 → `REJECT_SAFETY`
- GPT-5.6 Luna: over-merge 14, same 55/57, different 2/17 → `REJECT_SAFETY`
- GPT-5.6 Terra: over-merge 10, same 46/57, different 5/17 → `REJECT_SAFETY`
- 최종: `NO_EVENT_BOUNDARY_DEVELOPMENT_CANDIDATE`
- 상세: [REPORT.md](REPORT.md)
