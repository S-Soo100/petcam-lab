# TEST-SHEET — Local VLM 사건 경계 Baseline v1

> **상태:** `PRE_REGISTERED` — 아래 입력·모델·prompt·sampler·판정은 measured run 전에 동결했다.

## 0. 연구 질문

Mac mini M1 16GB에서 최신 1~2B local VLM이 사람이 확정한 development 경계 74개 중 실제 다른
사건 17개를 하나로 합치지 않으면서, 같은 사건 57개의 절반 이상을 찾아낼 수 있는가?

## 1. 고정 표본

| 항목 | 값 |
|---|---:|
| experiment | `rba-event-sequence-review-v2` |
| source manifest digest | `edd3f2c230adacb70c0b8bc70072eb632eb0ac48718bdd1ffbeca88649e9dfca` |
| development pair | 74 |
| unique clip | 78 |
| final same / different / uncertain | 57 / 17 / 0 |
| historical/future holdout | 0개 접근 |

선행 분석의 `rba-boundary-development-v1/run-salt.bin`을 `--salt-file`로 재사용하고 mode `0600`,
길이 32 bytes를 검사한다. 이 salt로 base manifest의 raw pair identity를 HMAC 재계산해 final
boundary 74개와 정확히 대응시킨다. 새 salt를 만들지 않는다. 대응 74/74가 아니면
`BLOCKED_GT_MAPPING`이다. 공개 산출물에는 raw identity가 없다.

## 2. 모델·runtime

| 항목 | MiniCPM | Qwen |
|---|---|---|
| tag | `minicpm-v4.6:latest` | `qwen3-vl:2b` |
| 계열 | MiniCPM-V 4.6 1B | Qwen3-VL 2B Instruct |
| license | Apache-2.0 | Apache-2.0 |
| runtime | Ollama 0.32.5 | Ollama 0.32.5 |

pull 뒤 실제 Ollama digest·size를 runtime snapshot에 고정한다. measured run 중 tag digest가 바뀌면
중단한다. 기존 7~8B 모델은 비교하지 않고 삭제하지 않는다.

공통 generation options:

- `format=<동결 JSON schema object>`
- `think=false`
- `temperature=0`
- `seed=20260802`
- `num_ctx=4096`
- `num_predict=96`
- measured request `keep_alive="15m"`; 모델 전환 때만 empty messages + `keep_alive=0`
- request timeout `120초`; timeout은 해당 key 실패이고 retry하지 않음
- measured key당 요청 1회, retry 0

## 3. 입력과 capability smoke

### 3.1 sampler

- A: `15%, 55%, 85%, 98%`
- B: `2%, 15%, 55%, 85%`
- seek는 duration 기반 frame index, clamp, exact decoded frame 실패 시 input failure
- frame long edge ≤768px, aspect ratio 유지
- 각 영상 4장을 2×2 JPEG quality 90 sheet로 구성
- 모델에 gap·GT·행동 label·Python Evidence·Gate를 주지 않음

### 3.2 representation 사전 결정

합성 A sheet와 B sheet의 서로 다른 표식을 모두 말해야 맞는 smoke를 각 모델에 1회 수행한다.

- 두 모델 모두 두 sheet를 구분하면 `two_images`
- 어느 하나라도 실패하면 두 sheet를 위아래로 붙인 `combined_4x2`
- representation을 고른 뒤 `two_images=148장` 또는 `combined_4x2=74장`과 SHA-256을 먼저 만들고
  full run 동안 불변. measured record는 어느 경우든 `74 pair × 2 model = 148`개

smoke는 GT·실험 media를 사용하지 않으며 measured 148회에 포함하지 않는다.

## 4. 고정 prompt와 schema

prompt version `local-vlm-event-boundary-v1`:

```text
You are checking whether two consecutive gecko camera clips show one continuous physical activity event.
Image A contains four frames from video A in time order. Image B contains four frames from the following video B in time order.
If one combined image is provided, its top half is video A and its bottom half is video B.
Use only visible continuity. same_event means the same physical activity/posture transition continues across A to B. different_event means the activity clearly stopped, reset, or a new activity/scene begins. If the images cannot establish this, choose uncertain.
Return one JSON object only with keys decision, confidence, reason_code.
decision: same_event|different_event|uncertain
confidence: number from 0 to 1
reason_code: continuous_motion|continuous_posture|clear_stop|new_activity|scene_discontinuity|insufficient_visual
```

schema 밖 key, markdown fence, NaN/Infinity, 범위 밖 confidence, enum 밖 값은 모두 invalid다. raw response는
private JSONL에 4KB cap으로만 저장한다. parser가 답을 보정하거나 재질문하지 않는다.

## 5. 실행 순서와 공정성

1. 두 모델 pull·digest freeze
2. synthetic smoke·representation freeze
3. 78개 media HEAD/GET/decode 78/78
4. representation별 148장 또는 74장 input 생성·hash freeze
5. 모델 순서는 고정 seed hash로 결정하고 첫 모델을 명시적으로 load한 뒤 74개 전수
6. empty messages + `keep_alive=0` unload 확인 뒤 둘째 모델 load·74개 전수
7. independent scorer 재계산

pair 순서는 같은 고정 HMAC 순서를 두 모델에 사용한다. 첫 모델 결과를 본 뒤 prompt, input, option,
parse rule을 바꾸지 않는다.

## 6. 지표

- completed / schema-valid / failure
- confusion matrix (`same_event`, `different_event`, `uncertain`)
- over-merge = human different → model same
- over-split = human same → model different
- same recall과 Wilson 95% CI
- different recall, uncertain rate
- load latency와 load를 제외한 measured generation latency p50/p95/max, total wall time
- Ollama runner peak RSS, system free-memory 최저값, swap delta, model disk size
- input/model/prompt/result digest와 독립 scorer 일치
- runner와 independent scorer의 모델별 `score`·`latency_sec` exact 일치. runner 전용
  `load_sec`은 cold-load metadata라 subtree 비교에서 제외

## 7. 사전 판정

| 우선 | 조건 | verdict |
|---:|---|---|
| 1 | GT mapping/media/input digest 위반 | `REJECT_INTEGRITY` |
| 2 | OOM·Ollama crash·free≤5% 2회·swap +1GiB | `REJECT_RESOURCE` |
| 3 | complete 또는 schema 74/74 미달 | `REJECT_RELIABILITY` |
| 4 | over-merge >0 | `REJECT_SAFETY` |
| 5 | same recall <29/57 | `REJECT_UTILITY` |
| 6 | 전부 통과 | `DEVELOPMENT_CANDIDATE` |

모델 간 우선순위는 `DEVELOPMENT_CANDIDATE`끼리만 same recall, p95 latency 순으로 정한다. 이는
production 승자가 아니라 future holdout에 올릴 development 후보다.

## 8. 자원·서비스 감시

- 2초마다 `memory_pressure -Q`, `vm_stat`, `ps`의 Ollama runner RSS를 private log에 기록
- system free memory ≤5%가 2회 연속이면 현재 요청 뒤 새 pair 중단
- swap used가 baseline보다 1GiB 넘으면 중단
- Ollama API/version PID와 기존 production/research service snapshot을 전후 비교
- HTTP request timeout 120초, timeout retry 0
- 새 LaunchAgent, server, plist, queue job 0

## 9. 쓰기 계약

허용:

- Ollama 공식 model pull 2개
- Mac private root의 model/runtime/media/input/result artifact
- repo의 코드·테스트·TEST-SHEET·REPORT

금지:

- Supabase INSERT/UPDATE/DELETE/RPC, R2 PUT/DELETE
- 사람 GT·답·resolution 수정
- production event/selector/router/VLM worker 연결
- 자동 skip, 원본 병합·삭제, holdout 접근
- existing model·cache 삭제

## 10. 공개 보고 필수 caveat

- Owner가 최초 판단과 conflict 최종 해결을 함께 한 self-adjudication development GT다.
- 74개는 자연분포나 미래 카메라 일반화를 증명하지 않는다.
- same recall 29/57 기준의 Wilson 95% CI 폭을 병기한다.
- 어떤 통과도 production 활성화를 허용하지 않는다.
