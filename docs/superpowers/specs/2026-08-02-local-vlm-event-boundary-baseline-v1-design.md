# Mac mini Local VLM 사건 경계 Baseline v1 설계

**상태:** Owner 승인 / 구현 전 동결
**작성일:** 2026-08-02
**선행 정본:** [`RBA 사건 경계 Development 분석 v1`](../../../experiments/rba-boundary-development-v1/REPORT.md)

## 1. 한 줄 결론

사람이 확정한 development 경계 74개를 같은 입력·같은 질문으로 소형 local VLM 두 개에 보여
“이어지는 사건인지”를 얼마나 안전하게 재현하는지 Mac mini에서 비교한다.

## 2. 사용자 체험과 제품 소비처

최종 제품에서 사용자는 30~60초 영상 수십 개를 따로 뒤지는 대신, 실제로 이어진 활동을 하나의
사건 카드로 본다. 원본 영상은 합치거나 삭제하지 않고 사건 안에서 순서대로 재생한다. local VLM은
사건 경계의 후보 판단과 사건별 1차 관찰을 만드는 저비용 층이며, 확신이 낮거나 중요한 사건은
cloud VLM·SegmentVLM·사람에게 올라간다.

이번 baseline은 그중 첫 질문만 검증한다.

`영상 A의 마지막 장면 + 영상 B의 시작 장면 → 같은 활동의 연속인가?`

## 3. 최신 공식 후보 재탐색

2026-08-02 기준 공식 repository·model card·runtime 문서만 확인했다.

| 후보 | 공식 근거 | Mac mini 판단 | 선택 |
|---|---|---|---|
| MiniCPM-V 4.6 1B | OpenBMB는 0.8B 언어모델 기반, image·multi-image·video 이해, Apache-2.0, Ollama/llama.cpp 지원을 명시한다. Ollama 양자화는 약 1.6GB다. | 가장 작은 최신 edge 후보. 속도·메모리 기준점 | **실행** |
| Qwen3-VL 2B | Qwen은 video temporal modeling과 Apache-2.0을 명시한다. Ollama 2B 양자화는 약 1.9GB다. | 1B보다 무겁지만 시간축 이해 품질 비교에 적합 | **실행** |
| Qwen3.5 0.8B | 공식 model card는 unified vision-language와 prototyping 용도를 명시한다. | 매우 작지만 현재 Mac Ollama의 안정된 multimodal 배포 계약을 먼저 증명해야 한다 | 보류 |
| 기존 MiniCPM-V 2.6·Qwen2.5-VL 7B·Llama 3.2 Vision | 이미 Mac에 있으나 5.5~7.8GB다. | M1 16GB 전수 처리의 최신 효율 기준으로는 불리하다 | 설치 유지·미실행 |

공식 근거:

- <https://github.com/OpenBMB/MiniCPM-V>
- <https://huggingface.co/openbmb/MiniCPM-V-4.6>
- <https://registry.ollama.com/library/minicpm-v4.6/tags>
- <https://github.com/QwenLM/Qwen3-VL>
- <https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct>
- <https://ollama.com/library/qwen3-vl>

## 4. 고정 입력

- 사람 경계 GT가 완결된 development pair 74개만 사용한다.
- pair를 이루는 고유 원본 78개를 R2에서 격리 cache로 GET한다.
- 행동 GT, reviewer 답, gap seconds, Python Evidence, Gate 결과는 모델 입력에 넣지 않는다.
- 각 영상에서 시간순 4장을 뽑는다: `15%, 55%, 85%, 98%`.
- A의 4장과 B의 4장을 각각 2×2 contact sheet로 만든다. header는 영상 A/B와 시간 순서만
  표시하고 원본 화면과 좌하단 timestamp는 가리지 않는다.
- 긴 변 768px 이하, JPEG quality 90, 동일 OpenCV sampler를 두 모델에 사용한다.
- contact sheet bytes와 prompt SHA-256을 기록한다.

이 8장은 전체 행동 맥락과 A→B 경계를 함께 보여 주면서 M1 16GB의 visual token 사용량을
제한하는 절충안이다. full run 뒤 sampler는 바꾸지 않는다.

## 5. 고정 출력

모델은 markdown 없는 JSON object 하나만 반환한다.

```json
{
  "decision": "same_event|different_event|uncertain",
  "confidence": 0.0,
  "reason_code": "continuous_motion|continuous_posture|clear_stop|new_activity|scene_discontinuity|insufficient_visual"
}
```

temperature 0, fixed seed, 최대 96 tokens다. 설명 자유문장과 chain-of-thought는 요구·저장하지 않는다.
schema 실패는 자동으로 정답을 추측하지 않고 실패로 기록한다. 같은 measured key 재호출도 금지한다.

## 6. 측정과 판정

사람 final `different_event` 17개를 `same_event`로 답하면 over-merge다. 실제 다른 사건을 하나로
합쳐 사용자 타임라인을 왜곡하므로 최우선 안전 지표다.

| 영역 | 사전 기준 |
|---|---|
| 완주 | 74/74 measured keys 종료 |
| 구조화 응답 | schema-valid 74/74 |
| 안전 | over-merge 0/17 |
| 효용 | same-event recall ≥50% (57개 중 최소 29개) |
| 결정론 | input/prompt/model digest 전부 고정 |
| 자원 | OOM·kernel kill·Ollama crash 0, peak system memory pressure critical 0 |
| 운영 | production worker/service 설정·상태 변경 0 |

두 모델이 모두 통과하면 same recall이 높은 모델, 동률이면 p95 latency가 낮은 모델을 우선한다.
안전과 효용을 모두 통과해도 verdict는 `DEVELOPMENT_CANDIDATE`뿐이며 production 채택이 아니다.

## 7. 설치·실행 경계

- host: `baeg-endeuui-Macmini.local` / Apple M1 / 16GB / arm64
- Ollama: 기존 앱과 server `0.32.5` 사용
- 새 model tags: `minicpm-v4.6:latest`, `qwen3-vl:2b`
- private root: `/Users/baek-end/Library/Application Support/petcam/local-vlm/event-boundary-v1`
- directory `0700`, private manifest/result/media `0600`
- DB SELECT, R2 HEAD/GET만 허용
- LaunchAgent·plist·env·production queue·GT·R2 object는 수정하지 않는다.
- 기존 모델을 삭제·교체하지 않는다.
- benchmark 전후 Ollama version, model digest, service PID, production service snapshot을 비교한다.

모델 pull은 승인된 설치 변경이다. Ollama server를 재시작하거나 persistent worker를 새로 만들지는
않는다. measured run은 one pair at a time이며 모델 사이에 unload API를 호출한다.

## 8. 실행 단계

1. exact commit handoff와 Mac runtime preflight
2. 새 모델 두 개 pull, tag·digest·disk 기록
3. 합성 이미지 1회씩 capability smoke (측정 74개 밖)
4. development media 78개 R2 HEAD/GET, hash·decode 검사
5. contact sheet를 한 번 생성하고 두 모델이 같은 bytes를 사용
6. model A 74개 full run
7. prompt·sampler 변경 없이 model B 74개 full run
8. 독립 scorer로 confusion·over-merge·same recall·latency를 재계산
9. Claude가 설계 준수와 결과 해석을 read-only 교차검수
10. 보고서·SOT 갱신, 검증 후 main 반영

## 9. 실패 처리

- media 78/78 HEAD·GET·decode가 아니면 모델 실행 전에 중단한다.
- 한 모델 load가 실패해도 다른 모델은 같은 frozen 시험으로 실행한다.
- OOM·critical memory pressure·Ollama server 종료가 감지되면 현재 모델을 중단하고 자원 실패로
  기록한다.
- 모델 응답 실패를 재질문·후처리 추측으로 숨기지 않는다.
- raw clip ID, R2 key, reviewer identity, 원문 답, secret은 공개 report에 쓰지 않는다.
- 작업 종료 후 contact sheet와 원본 cache는 private local에만 유지하며 자동 삭제하지 않는다.

## 10. 명시적 범위 밖

- historical/future holdout 개방
- prompt tuning, LoRA, fine-tuning
- 행동 분류·케어 판단 품질 측정
- Python Evidence·Gate 결합
- production 사건 자동 병합·앱 노출·자동 skip
- 기존 local router v0/v1/v2 또는 care-guard 재가동

## 11. 산출물

- 사전 동결 `TEST-SHEET.md`
- TDD runner·strict parser·scorer와 테스트
- Mac private manifest/results/runtime snapshot
- 모델·성능·오류 유형·다음 결정을 담은 `REPORT.md`
- `specs/next-session.md`와 전략 문서 현재 상태 갱신
