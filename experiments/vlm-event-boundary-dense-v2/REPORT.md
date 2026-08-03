# VLM 사건 경계 밀집 v2 결과보고서

> **최종 판정:** `NO_EVENT_BOUNDARY_DEVELOPMENT_CANDIDATE`
> A 종료 직전 6장+B 시작 직후 6장으로 시험지를 바로잡았지만 GPT 3개와 local VLM 2개 중 자동
> 사건 묶기 safety gate를 통과한 모델은 없었어.

## 1. 한 문장 결론

경계 밀집 입력은 GPT가 다른 사건을 찾는 데 일부 도움이 됐지만, 가장 나은 Terra도 서로 다른 사건
17개 중 7개를 같은 사건으로 잘못 합쳐 자동 사건 묶기에는 여전히 사용할 수 없어.

## 2. 무엇을 바로잡았나

이전 v1은 A와 B 전체 구간에서 각각 4장을 듬성듬성 뽑았어. 이 입력은 실제 질문인 “A 끝에서 하던
행동이 B 시작까지 이어졌나?”보다 두 영상 전체가 비슷한지를 강하게 보여주는 잘못된 표현이었어.

v2는 같은 owner-final development 경계 74개와 같은 사람 정답을 유지하고 입력만 다음처럼 고쳤어.

- A: 종료 전 `6, 4, 2, 1, 0.5, 0.1초`
- B: 시작 후 `0.1, 0.5, 1, 2, 4, 6초`
- 영상별 3×2 sheet 두 장, 1080×628, pair당 총 12 frame
- A/B 사이 실제 미촬영 gap seconds를 header에 표시
- 시간 label은 영상 밖에 두어 원본 좌하단 camera timestamp를 가리지 않음

실제 JPEG를 육안으로 확인했고 A와 B가 각각 시간순이며 timestamp가 전부 보존됐어. dense manifest의
148 JPEG도 148/148 hash가 일치해.

## 3. 고정 조건

| 항목 | 값 |
|---|---|
| host | `baeg-endeuui-Macmini.local` |
| 표본 | owner-final development 74 (`same=57`, `different=17`), unique clip 78 |
| representation | `boundary_dense_two_images_6x2` |
| prompt | `vlm-event-boundary-dense-v2` |
| GPT | `gpt-5.4-mini`, `gpt-5.6-luna`, `gpt-5.6-terra` |
| GPT runtime | Codex CLI `0.146.0-alpha.3.1`, ChatGPT subscription, reasoning low |
| local | `minicpm-v4.6:latest`, `qwen3-vl:2b`, Ollama |
| local runtime | temperature 0, seed 20260803, num_ctx 8192, retry 0 |
| gate | schema 74/74 + **over-merge 0** + same correct ≥29/57 |
| measured window | GPT 2026-08-03 03:19:51~03:48:06 KST, local 03:48:45~03:57:41 KST |
| production | DB/R2/GT/event/skip/UI/service 변경 0 |

## 4. 최종 성적표

| 모델 | 유효 | same 정답 | different 정답 | over-merge | over-split | uncertain | p50 / p95 | 판정 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| GPT-5.4 Mini | 73/74 | 52/57 | 5/17 | **11** | 4 | 1 | 5.90s / 10.55s | `REJECT_RELIABILITY` + safety 실패 |
| GPT-5.6 Luna | 74/74 | 49/57 | 4/17 | **10** | 2 | 9 | 5.58s / 8.58s | `REJECT_SAFETY` |
| GPT-5.6 Terra | 74/74 | 49/57 | **7/17** | **7** | 6 | 5 | 5.66s / 8.78s | `REJECT_SAFETY` |
| MiniCPM-V 4.6 | 74/74 | 57/57 | 0/17 | **17** | 0 | 0 | 7.19s / 7.22s | `REJECT_SAFETY` |
| Qwen3-VL 2B | 0/74 | 측정 안 함 | 측정 안 함 | 품질 채점 안 함 | - | - | - | `INCONCLUSIVE_INPUT_REPRESENTATION` |

Mini의 첫 measured call은 Codex CLI/backend가 240초 안에 반환하지 않아 사전 계약대로 timeout 1건으로
남겼고 retry하지 않았어. 이후 73건과 Luna/Terra 148건에는 timeout·quota 오류가 없었어.

Qwen은 측정 전 합성 two-image smoke에서 A의 빨간 사각형과 B의 파란 삼각형을 둘 다 읽지 못했어.
그 상태로 사건 판단을 시키면 “모델 품질 실패”와 “두 번째 이미지를 안 본 실패”가 섞이므로, 본 호출은
0건으로 막고 74 ledger row를 `input_representation_smoke_failed`로 기록했어.

## 5. 잘못된 4+4 대비 무엇이 달라졌나

| 모델 | v1 over-merge | dense v2 over-merge | v1 different 정답 | dense v2 different 정답 | paired recovered / broken |
|---|---:|---:|---:|---:|---:|
| GPT-5.4 Mini | 12 | 11 | 2/17 | 5/17 | 4 / 4 (비교 가능 73) |
| GPT-5.6 Luna | 14 | 10 | 2/17 | 4/17 | 3 / 7 |
| GPT-5.6 Terra | 10 | **7** | 5/17 | **7/17** | **13 / 8** |
| MiniCPM-V 4.6 | 17 | 17 | 0/17 | 0/17 | 변화 없음 |

입력을 고친 효과는 있었어. Luna는 잘못 합침이 14→10, Terra는 10→7로 줄었고 Terra의 전체 정확
결정도 paired 기준 5건 순증했어. 하지만 절대 기준은 over-merge 0이므로 “전보다 낫다”와 “제품에 쓸
수 있다”는 전혀 다른 결론이야.

특히 Terra는 과거 over-merge 중 4개를 정확한 `different_event`, 2개를 `uncertain`으로 회복했지만,
과거에는 합치지 않았던 3개를 새롭게 합쳤어. 즉 밀집 frame이 편향을 줄였을 뿐 안정적으로 경계를
해결하지는 못했어.

## 6. 왜 촘촘히 봐도 남았나

확인된 사실은 두 가지야.

1. **입력 문제는 실제로 일부 성능을 깎고 있었어.** dense 입력에서 세 GPT의 over-merge가 모두 줄었어.
2. **정지 frame만으로는 미촬영 구간의 실제 행동을 복원할 수 없어.** 다른 사건 오판은 gap 27.4초부터
   265.2초까지 넓게 남았고, gap 길이 하나로도 분리되지 않았어. 게코가 A 끝과 B 시작에서 비슷한
   자세·위치에 있으면 중간에 행동이 끝났다가 다시 시작했는지 화면만으로 알 수 없는 경우가 있어.

사람에게도 쉬운 문제가 아니었어. 이 74경계의 최초 두 사람 raw agreement는 64.9%, Cohen's κ는
0.265였고 owner가 35.1%를 최종 조정했어. owner-final은 현재 development 정답으로 유효하지만,
모델이 정지 frame만 보고 완전 자동화하기에는 본질적으로 모호한 표본이 많다는 뜻이야.

따라서 “프레임을 더 촘촘히 뽑으면 해결된다”는 가설은 부분 개선까지만 확인됐고 자동화 가설은
기각됐어.

## 7. 무결성 검증

- dense manifest SHA-256:
  `df1f98e24fd51246cca993c3240a725f3ce5c14a66da1473df7b4f189ba7f46d`
- TEST-SHEET SHA-256:
  `49051ac8a0669ccce459264df0cf9a8734c661b5c63039a6a112ef6cafb594d3`
- GPT summary SHA-256:
  `8e9c4c8db472c6f9be4560706a9d26312292083cf08ca3f00e0a17b666c4fee3`
- local summary SHA-256:
  `f5a690d599056759533e43a5b66f440100206a1a5d12f401b95016343c469a12`
- 독립 recompute: GPT 222 records, local 148 records
- runner/recompute 모델별 score·latency·ledger SHA: 5/5 exact
- measured ledger의 human key: 0/370
- GPT valid call tool/file/MCP/web/plan event: 0/221
- GPT pair cwd: 74/74 directory에 JPEG 정확히 2개
- MiniCPM prompt_eval_count: 모든 74건 정확히 887, `887+96 <= 8192`
- local resource: min free 56%, swap 증가 0, monitor error 0
- private root/run/input mode `0700`, manifest/ledger/summary `0600`
- Claude 실행 전 리뷰: `REVIEW_DENSE_PLAN_CLEAR P0=0 P1=0`

## 8. 제품 판단과 다음 행동

1. **자동 사건 묶기:** 다섯 모델 모두 채택 금지야. production event를 자동으로 합치거나 자동 skip하는
   근거로 쓰지 않아.
2. **사람 정답:** 현재 owner-final 사건 묶음을 그대로 기준으로 사용해. 이번 결과가 기존 교차검수나
   owner 최종 결정을 무효화하지 않아.
3. **경계 연구:** 같은 74개에서 frame 수·prompt만 더 튜닝하는 반복은 멈춰. 재도전하려면 실제 경계
   직전·직후 짧은 연속영상 또는 추적 궤적처럼 **새 정보**를 넣는 별도 시험이어야 해.
4. **행동 VLM 연구:** 사건 경계 실패와 분리해. 모든 사건의 게코 보임·행동·위치 변화·근거 frame을
   12-frame으로 설명하는 시험은 여전히 별도 연구 질문이야.

이번 결과는 자동 사건 묶기를 기각한 것이고, GPT/local VLM을 행동·관찰 분석에 쓰는 가능성까지
기각한 것은 아니야.
