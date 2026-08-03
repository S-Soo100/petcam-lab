# OpenAI 구독 VLM 사건 경계 v1 결과보고서

> **2026-08-03 superseded:** 이 보고서의 실행·성적은 이력으로 유효하지만, 전체구간 4+4 입력이 실제
> 경계 질문을 충분히 보존하지 못해 모델 채택 판단에는 사용하지 않아. A끝 6장+B시작 6장으로 다섯
> 모델을 다시 측정한 현재 정본은
> [`vlm-event-boundary-dense-v2`](../vlm-event-boundary-dense-v2/REPORT.md)야.

> **최종 판정:** `NO_EVENT_BOUNDARY_DEVELOPMENT_CANDIDATE`
> 세 모델 모두 74/74 구조화 응답에는 성공했지만 서로 다른 사건을 잘못 합치는 safety Gate를
> 통과하지 못했다. 이 prompt·입력·모델 조합을 자동 사건 묶기에 사용하지 않는다.

## 1. 한 문장 결론

ChatGPT 구독 Codex CLI로 이미지를 안정적으로 전수 처리하는 것 자체는 가능했지만, 현재 사건 경계
문제에서는 GPT-5.4 Mini·GPT-5.6 Luna·GPT-5.6 Terra 모두 사람이 분리한 사건을 너무 자주 합쳤다.

## 2. 무엇을 시험했나

local VLM baseline과 정확히 같은 development 74경계(`same=57`, `different=17`)와 기존
`combined_4x2` 8-frame JPEG를 사용했다. 질문·schema·입력 hash는 바꾸지 않았고 모델에는 사람 답,
clip id, 행동명, Python Evidence, Gate를 주지 않았다.

이 시험은 **행동 이름을 붙이는 VLM 분석 시험이 아니라 두 연속 영상을 하나의 사건으로 묶어도 되는지
판단하는 시험**이다. 따라서 이번 실패는 자동 사건 묶기에는 직접 적용되지만, 월 2만 영상의 행동·관찰
분석 가능성까지 기각하지는 않는다. 그 역할은 별도 owner-final 행동 시험이 필요하다.

## 3. 동결 실행 조건

| 항목 | 값 |
|---|---|
| host | Mac mini Apple M1, RAM 16GB |
| runtime | `codex-cli 0.145.0`, `Logged in using ChatGPT` |
| model | `gpt-5.4-mini`, `gpt-5.6-luna`, `gpt-5.6-terra` |
| reasoning | `low` |
| 요청 | 모델×pair당 1회, retry 0, 총 222회 |
| input | 기존 `combined_4x2` JPEG 74장, source hash 74/74 exact |
| prompt/schema | local VLM v1과 동일, JSON 3-key |
| measured window | 2026-08-03 01:35:39~02:00:10 KST |
| DB/R2/GT/service/production | 접근·변경 0 |

공식 Codex 문서가 안내하는 `codex exec --ephemeral`, read-only sandbox, image input,
`--output-schema`, `--json` event stream과 ChatGPT 저장 인증 재사용 경로를 썼다.

## 4. 성적표

통과 조건은 schema 74/74, **over-merge 0**, same correct 29/57 이상이다.

| 모델 | 유효 | same 정답 | different 정답 | over-merge | over-split | uncertain | p50 / p95 | 판정 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| GPT-5.4 Mini | 74/74 | 56/57 (98.2%) | 2/17 (11.8%) | **12** | 0 | 4 | 6.14s / 8.82s | `REJECT_SAFETY` |
| GPT-5.6 Luna | 74/74 | 55/57 (96.5%) | 2/17 (11.8%) | **14** | 0 | 3 | 5.60s / 9.63s | `REJECT_SAFETY` |
| GPT-5.6 Terra | 74/74 | 46/57 (80.7%) | 5/17 (29.4%) | **10** | 6 | 7 | 6.35s / 10.16s | `REJECT_SAFETY` |
| Local MiniCPM-V 4.6 | 74/74 | 57/57 | 0/17 | **17** | 0 | 0 | 3.04s / 3.37s | `REJECT_SAFETY` |
| Local Qwen3-VL 2B | 0/47 schema | 측정 불가 | 측정 불가 | 측정 불가 | 측정 불가 | 측정 불가 | 6.66s / 6.71s | `REJECT_RESOURCE/RELIABILITY` |

Terra가 세 GPT 중 다른 사건을 가장 많이 찾았지만 17개 중 10개를 여전히 잘못 합쳤다. Mini와 Luna는
같은 사건은 거의 모두 찾는 대신 다른 사건도 대부분 같은 사건이라고 답했다. 로컬 MiniCPM의
always-same 붕괴보다는 나아졌지만 제품 안전 기준과는 거리가 크다.

## 5. 처리 안정성과 시간

| 모델 | schema/error | model wall time | 실측 직렬 처리량 | 월 20,000건 단순 환산 |
|---|---:|---:|---:|---:|
| GPT-5.4 Mini | 74/74, error 0 | 501.5s | 약 531건/h | 약 37.7h |
| GPT-5.6 Luna | 74/74, error 0 | 457.1s | 약 583건/h | 약 34.3h |
| GPT-5.6 Terra | 74/74, error 0 | 512.2s | 약 520건/h | 약 38.4h |

세 모델 합계는 24분 31초였고 quota/rate-limit 오류는 0이었다. 이 수치는 Codex CLI agent process를
매번 새로 띄운 **직렬 구독 경로**의 처리량이다. API Batch의 병렬성·24시간 completion·가격·실제
token 사용량으로 환산할 수 없다.

## 6. GT 격리와 독립 검증

첫 attempt는 GPT-5.4 Mini 67/74에서 Claude 교차검수가 “실행 중 ledger에 human decision이 존재”하는
P0를 발견해 중단했다. 67/67 응답과 tool/file event 0이었지만 성적에 쓰지 않았다.

새 v2 run은 다음을 만족했다.

- pair별 `0700` cwd에 exact JPEG 한 장만 존재: 74 directory / 74 file
- measured ledger의 `human` key: 모델별 0/74
- Codex JSON event의 command/file/MCP/web/plan item: 모델별 0
- schema-valid: 222/222, error·quota: 0/0
- private root/ledger/summary mode: `0700/0600`
- runner-import-free recompute: 222 record
- runner와 recompute의 모델별 `score`·`latency_sec`·ledger digest subset SHA:
  `7e995332cf151da3d2d98e3ca7d8182500f2daa8cceac7ef496dd684d530cbf0` exact 일치

주요 digest:

- source manifest: `a0bd6ef5073508a14dd9be66cad9d65dea06d4ef4800a0a687af31c1b9163236`
- TEST-SHEET v2: `3cd45be4496ba75cb317272dc3635ec7761ce8367f904c024639b9c0f1359b04`
- summary file: `d9a6851b6b6728704ef5d622e75282ea58e1b270d608ad1628bb2024b04d90ac`
- recompute file: `8d3f91847b261b69ab5d940abc229d1c13a5d00688fc86c3b502182b5814666d`

모델 identity는 CLI 요청 slug와 Mac mini model cache 존재까지만 확인했다. 현재 공개 CLI event에는 실제
backend serving model id가 없어 alias 내부 identity exact 일치는 주장하지 않는다. 또한 구독 CLI는
API temperature/seed를 고정하지 못하므로 이번 결과는 one-shot baseline이다. 다만 모든 모델의
over-merge가 10개 이상이라 사전 borderline 범위와는 거리가 멀다.

## 7. 제품 판단

1. **자동 사건 묶기:** 세 GPT 모두 채택 금지다. 모델을 키운 것만으로 경계 문제가 해결되지 않았다.
2. **구독 CLI 기술 경로:** 이미지 222건·schema 222건은 안정적으로 처리했다. 시험 자동화 경로는 유효하다.
3. **월 2만 행동 VLM:** 아직 미검증이다. 사건 경계 prompt 실패를 행동 관찰 실패로 확대해석하지 않는다.
4. **다음 유효 시험:** owner-final 행동/관찰 300건, 영상당 12프레임, 실제 API usage ledger로
   GPT-5.4 Mini와 Terra를 비교한다. 사건 묶기는 사람-final 경계 또는 별도 전용 방법을 유지한다.

production API key, DB/R2, GT, 사건, skip, UI, service는 이번 작업에서 바꾸지 않았다.

Slack 공유: [#99-petcam-lab-auto 결과 글](https://teraaihq.slack.com/archives/C0B66NLM8R1/p1785690390205049)

## 8. 공식 사용 근거

- [Codex 비대화형 `exec`·structured output·JSON event](https://learn.chatgpt.com/docs/non-interactive-mode.md)
- [Codex CLI 이미지 입력](https://learn.chatgpt.com/docs/image-inputs.md)
- [ChatGPT 구독과 API key 인증의 차이](https://learn.chatgpt.com/docs/auth.md)
