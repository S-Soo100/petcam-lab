# Local VLM Mac Studio 구매 판단 Gate v1 — 결과보고서

## 결론

최종 판정은 **`INCONCLUSIVE_NEEDS_COMPATIBLE_HARDWARE`**다.

지금 Mac Studio를 사도 된다는 증거는 아직 없다. 반대로 “큰 모델도 소용없다”는 결론도 낼 수 없다.
현재 32GB MacBook에서는 12B와 30B가 사전등록한 swap 안전선을 넘어 품질시험을 끝내지 못했기
때문이다. 다음 구매 전 행동은 **64GB 장비를 빌려 같은 18개 합성 Gate만 먼저 재실행**하는 것이다.
30B가 18/18을 통과할 때만 사람-final 74경계와 future holdout으로 올라간다.

## 측정 환경

| 항목 | 값 |
|---|---|
| host | MacBook Pro M5, unified memory 32GB |
| runtime | Ollama 0.32.5, Metal, flash attention, KV cache q8_0 |
| exact code HEAD | `b005d4d5fa71f742cd98974dbf91ea5954912955` |
| source | 선행 frozen development input 74 + media 78의 private read-only 복사 |
| source preflight | media/input SHA `78/78·74/74`, exact unique pair 복원 `74/74` |
| model input | 합성 clip 12장, 합성 boundary 4A+4B, 원본 development 768px 4A+4B |
| holdout / development model request | `0 / 0` |

## 모델 결과

| 모델 | 합성 정답 | 자원 | 상태 |
|---|---:|---|---|
| Gemma 3 4B Q8 | `4/18` | swap delta `0`, free min `30%` | `SYNTHETIC_GATE_FAIL` |
| Gemma 4 12B QAT | `3/16`, 자원 중단 전 | swap `0.876→3.192GiB` (`+2.316GiB`) | `RESOURCE_FAIL` |
| Qwen3-VL 8B Q4 | `12/18` | swap delta `0`, free min `27%` | `SYNTHETIC_GATE_FAIL` |
| Qwen3-VL 30B-A3B Q4 | scored request `0` | swap `3.192→5.757GiB` (`+2.566GiB`), free min `9%` | `RESOURCE_FAIL` |

Qwen3-VL 8B는 4B보다 나았고 clean static/moving, shadow-moving, brightness-static,
continuous-move를 반복해서 맞혔다. 그러나 position-jump와 shadow-static 등을 놓쳐 18/18 Gate를
통과하지 못했다. 즉 **모델 계열 효과는 보이지만 production 사건 경계 품질 증거는 아니다.**

12B의 `3/16`과 30B의 `0`은 품질 점수가 아니다. 자원 안전선으로 중단된 불완전 관찰이므로 작은
모델과 정확도 비교에 쓰지 않는다.

## 무결성·독립 재계산

- runner verdict와 독립 recompute의 모델 상태·구매 판정 exact 일치
- frozen manifest SHA-256:
  `4b9566a1aa670ba2fd198f216b4faa6e2aece7f2fa7df5a58608f6c2777b4a51`
- measured results SHA-256:
  `89d8f63a9a8874cbce54a1fd7ba5037e8bf426ac1b2855b64ada722709609a17`
- private artifact mode `0700/0600`, model unload 확인
- production DB/R2/service/plist/GT/submission/사용자 노출 변경 `0`

## 구매에 주는 답

1. **36GB급 구매는 근거가 약해.** 현재 32GB에서도 12B/30B가 swap 안전선을 넘었다.
2. **64GB에는 실행 가능성은 있어.** 하지만 아직 30B의 합성 정답을 한 건도 채점하지 못했으므로
   품질 가능성까지 증명한 것은 아니다.
3. 그래서 구매 전 대여/반품 가능한 64GB Mac Studio에서 exact HEAD·model digest·18개 합성 Gate를
   그대로 재실행한다.
4. 30B가 18/18 PASS하고 12B 이하가 모두 평가 완료 실패일 때만
   `MAC_STUDIO_64GB_PURCHASE_EVIDENCE_PENDING_HOLDOUT`으로 승격한다.

## 한계

- development 74는 이전 baseline에서도 사용한 모델 선택 자료라 누적 적응 위험이 있다. 이번에는
  합성 Gate 통과 모델이 없어 접근하지 않았다.
- 32GB에서 자원 실패한 사실만으로 64GB에서 품질이 좋아진다고 추론할 수 없다.
- future camera/gecko/enclosure 일반화와 production 자동 병합·skip은 전혀 평가하지 않았다.
