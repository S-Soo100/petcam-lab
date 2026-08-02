# Local VLM 사건 경계 Baseline v1 결과보고서

> **최종 판정:** `NO_DEVELOPMENT_CANDIDATE` — MiniCPM-V 4.6은 안전성 탈락,
> Qwen3-VL 2B는 자원·신뢰성 탈락이다. 둘 다 production이나 all-event shadow에 연결하지 않는다.

## 1. 무엇을 확인했나

사람이 확정한 연속 영상 경계 74개를 작은 local VLM이 보고 `같은 사건 / 다른 사건 / 불확실`로
나눌 수 있는지 Mac mini에서 측정했다. 이건 행동 이름을 붙이는 시험이 아니라, 여러 영상 파일을
사용자에게 하나의 사건으로 보여줘도 되는지 확인하는 첫 관문이다.

최신 후보는 공식 자료와 Mac 배포 가능성을 기준으로 다시 골랐다.

- [MiniCPM-V 4.6](https://github.com/OpenBMB/MiniCPM-V): 1B급, image·multi-image·video,
  Apache-2.0, Ollama/llama.cpp 경로 제공
- [Qwen3-VL 2B Instruct](https://github.com/QwenLM/Qwen3-VL): 2B급, video temporal modeling,
  Apache-2.0, Ollama 배포 제공
- [MLX-VLM](https://github.com/Blaizzy/mlx-vlm)은 video 지원을 확인했지만, 이번 v1은 이미 설치된 Ollama 0.32.5에서 같은
  runtime·입력·옵션으로 1B/2B를 공정하게 비교했다.

## 2. 고정 실행 조건

| 항목 | 값 |
|---|---|
| host | Apple M1, 8-core, RAM 16GB, macOS 26.5 |
| code HEAD | `30eab8c5bb27083c07b5073bd011e322ab5135bb` |
| Ollama | 0.32.5 |
| GT | development 74경계: same 57 / different 17 / uncertain 0 |
| media | 고유 clip 78개, R2 HEAD/GET/decode 78/78, 489,965,091 bytes |
| input | 8 frames를 합친 `combined_4x2` JPEG 74장 |
| holdout | historical/future 모두 0개 접근 |
| generation | temperature 0, seed 20260802, ctx 4096, predict 96, retry 0 |

두 모델 모두 합성 two-image smoke를 통과하지 못해, 사전 규칙대로 A/B를 한 장에 붙인 동일한
`combined_4x2` 입력을 썼다. prompt·sampler·schema·판정 기준은 measured run 전에 동결했고,
결과를 본 뒤 수정하거나 재질문하지 않았다.

| 모델 | digest | 설치 크기 |
|---|---|---:|
| `minicpm-v4.6:latest` | `e95583acac773b45d95469c069db44808c87295f924183f4c942d52616b2d132` | 1,637,848,812 B |
| `qwen3-vl:2b` | `0635d9d857d497aeadba3d7d27485746c50554446f9f6ec01ef39788221adbe8` | 1,889,519,687 B |

## 3. 결과

| 모델 | 완주/유효 | 핵심 결과 | latency | 판정 |
|---|---:|---|---|---|
| MiniCPM-V 4.6 | 74/74 | same 57/57, different 0/17, over-merge 17 | p50 3.036s, p95 3.370s, max 3.875s | `REJECT_SAFETY` |
| Qwen3-VL 2B | 47/74, schema 0/47 | 47회 모두 빈 content→`ValueError`; 이후 자원 차단 | p50 6.661s, p95 6.709s, max 6.744s | `REJECT_RESOURCE` + `REJECT_RELIABILITY` |

MiniCPM의 same recall은 100%(57/57, Wilson 95% CI 93.686~100%)지만 좋은 결과가 아니다.
실제 다른 사건 17개도 전부 같은 사건으로 합쳤다. 즉, 항상 “같다”고 답한 것과 같아서 사용자에게
서로 다른 행동을 한 사건으로 잘못 보여줄 위험이 있다.

Qwen은 현재 Ollama structured-output 계약에서 JSON을 잘못 만든 정도가 아니라 응답 content가
아예 비어 있었다. 동시에 swap이 frozen 한도를 넘어서 47번째 뒤 새 요청을 시작하지 않고
fail-closed했다. 판정 ladder의 primary는 우선순위 2인 `REJECT_RESOURCE`이고,
`REJECT_RELIABILITY`는 schema 0/47에서 함께 확인된 부수 관찰이다. retry·설정 변경·나머지
27건 재개는 하지 않았다.

## 4. Mac mini 자원과 안전 중단

| 항목 | 측정값 |
|---|---:|
| resource sample | 267회, 2초 간격 |
| free memory 최저/마지막 | 28% / 28% |
| swap baseline / max / delta | 0.9324 / 1.9630 / 1.0306 GiB |
| Ollama RSS max | 6,324,656 KiB(약 6.03 GiB) |
| OOM·Ollama crash | 0 |
| 실행 후 loaded model | 0 |

free memory는 5% 기준보다 충분했지만 swap delta가 `+1GiB`를 넘었으므로 TEST-SHEET 우선순위에
따라 `REJECT_RESOURCE`로 중단했다. Ollama serve PID는 실행 전후 814로 유지됐고 새 LaunchAgent,
server, plist, queue job을 만들거나 기존 서비스를 재시작하지 않았다.

## 5. 무결성·재현성

- private root는 `0700`, 주요 artifact는 `0600`이다.
- frozen manifest SHA-256: `a0bd6ef5073508a14dd9be66cad9d65dea06d4ef4800a0a687af31c1b9163236`
- measured results SHA-256: `da3335ccb2da026f49bb3136e680a93ae0d4635ee9fc5e58c0b5057f39354c2b`
- resource log SHA-256: `30e0064291a91d5e294756144260f541f904d96f720343486a3273f4d9c0cf0e`
- MiniCPM 독립 scorer manifest/results SHA-256:
  `5927675009d606b12ea798bac71b0fbe5dfae1add79e9ea9f5b8c2ca29eca498` /
  `cf93b4b58df7896478c03a5deaae917760b7a33275b6f40224f460321e7a702d`
- Qwen이 47/74에서 자원 중단돼 runner 전체 `summary.json`은 생성되지 않았다. 따라서 두 모델
  전체 summary equivalence를 주장하지 않고, 완주한 MiniCPM 74건만 별도 private subset으로
  독립 재계산해 `score`와 `latency_sec`를 대조했다.
- DB는 SELECT, R2는 HEAD/GET만 사용했다. DB/R2/GT/submission/service write는 0이다.
- 첫 두 시도는 direct script import와 source artifact 권한 `0644`를 각각 실행 전에 차단했다.
  코드는 TDD로 보완했고 원본 byte와 SHA가 같은 private `0600` 복사본으로 실행했다. 이 두 실패
  시점에는 DB/R2/model measured run이 시작되지 않았다.

## 6. 이번 연구의 실효성

후보를 얻지는 못했지만, “작은 최신 VLM을 설치하면 사건 전수분석이 바로 된다”는 위험한 가정을
실제 74경계와 Mac 자원으로 빠르게 제거했다. 특히 정확도 하나만 보면 MiniCPM의 100% recall을
성공으로 오해할 수 있었지만, 제품에서 가장 위험한 over-merge가 17/17이라는 걸 확인했다.
Qwen은 모델 지능 비교 이전에 현재 runtime 출력 계약과 메모리 특성이 맞지 않는다는 사실도 남겼다.

다만 GT는 Owner가 최초 판단과 conflict 최종 해결을 함께 한 self-adjudication development 자료다.
74개 결과는 미래 카메라·개체·사육장 일반화를 증명하지 않는다.

## 7. 다음 권장 단계

1. 두 모델 모두 production·all-event shadow·자동 사건 병합에 연결하지 않는다.
2. Qwen은 새 v1.1 TEST-SHEET에서 **합성 입력만** 써 Ollama structured-output 빈 응답 원인을 먼저
   분리한다. 같은 development 정답으로 prompt를 반복 튜닝하지 않는다.
3. 그 문제가 runtime 계층이면 MLX-VLM 또는 llama.cpp의 더 낮은 메모리 경로를 새 동결 시험으로
   비교한다. safety gate를 통과한 후보가 생기기 전 LoRA와 future holdout은 열지 않는다.

새로 설치한 두 모델은 재현성을 위해 보존했지만 현재 loaded model은 없고 자동 실행도 연결하지 않았다.
