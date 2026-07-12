# experiment-codex-dataset203-sweep

상태: ✅ pilot 완료 / full 197 미실행
시작: 2026-07-09
목표: `dataset-203` 영상으로 Codex 모델별 VLM 대체 가능성을 토큰 절감률, 정확도 하락, 속도 기준으로 실측한다.

## 배경

Claude도 Codex도 영상 파일 자체를 직접 운영 입력으로 쓰는 전략은 아니다. 기존 Claude 기준선과 동일하게 `adaptive frames@1080` 또는 `contact-sheet` 이미지 표현으로 바꾼 뒤 멀티모달 모델에 넣는다.

이 실험은 "Codex가 영상 한계를 없애는가"가 아니라, 같은 입력표현 전략에서 Codex 모델들이 비용-정확도-속도 면에서 Claude 대체 후보가 되는지 보는 비교다.

## In

- `storage/dataset-203/manifest.csv`의 GT를 기준으로 채점한다.
- Codex CLI의 `--image` 입력으로 호출한다.
- 입력표현 2종을 비교한다.
  - `frames-adaptive`: 기존 연구 기준, 6~20장 개별 프레임, long edge 1080.
  - `contact-sheet`: 저토큰 후보, 5x6 30프레임 몽타주 1장.
- 모델 후보:
  - `gpt-5.5`
  - `gpt-5.3-codex`
  - `gpt-5.4-mini`
  - smoke test가 통과하면 `gpt-5.4-nano` 추가 가능.

## Out

- production worker 교체는 하지 않는다.
- prompt v4.0 자체 품질 개선은 하지 않는다.
- GT 라벨 정정은 이 실험 범위가 아니다. 의심 케이스는 보고서에만 기록한다.

## 필수 지표

1. 토큰 절감률: `1 - candidate_tokens / frames_adaptive_tokens`
2. 정확도 하락: `frames_adaptive_accuracy - candidate_accuracy`
3. 속도: clip당 wall-clock 초, 평균/중앙값

보조 지표:
- confidence threshold별 cascade 시뮬레이션
- fallback 비율
- 클래스별 정확도
- 주요 confusion pattern

## 실행 전략

1. smoke: 1개 clip x 모델 1개 x 표현 2개로 Codex CLI JSON/usage 파싱 확인.
2. model smoke: 1개 clip x 여러 모델 x 표현 2개로 모델명/latency 확인.
3. pilot: `dataset-203`에서 deterministic stratified 36개 샘플을 뽑아 모델별 비교.
4. full: pilot에서 채택 후보 1~2개만 197개 전체로 확장.

## 완료 조건

- [x] `scripts/codex_dataset203_sweep.py`로 재현 가능한 실험 실행이 가능하다.
- [x] smoke 결과에서 예측 JSON, 토큰 사용량 또는 추정 토큰, wall-clock 시간이 기록된다.
- [x] pilot 결과에서 모델별 토큰 절감률, 정확도 하락, 속도 표가 생성된다.
- [x] `experiments/codex-dataset203-model-sweep-pilot14/REPORT.md`에 결론을 기록한다.
- [ ] full 197은 API 직접 호출 가능성 확인 후 필요할 때만 실행한다.

## 2026-07-09 pilot14 결과

실행 조건:
- Codex CLI, ChatGPT login
- `model_reasoning_effort=low`
- blind cwd는 `/tmp/petcam-codex-dataset203-blind-workspace`
- 기준선: `v40 + frames-adaptive`
- 후보: `compact + contact-sheet-96`

결과:
- `gpt-5.5`: frames 85.7%, 29.4k tok, 8.0s → sheet 42.9%, 16.9k tok, 6.7s. 절감 42.5%, 정확도 -42.9pp.
- `gpt-5.4`: frames 78.6%, 28.0k tok, 9.3s → sheet 42.9%, 17.8k tok, 7.4s. 절감 36.5%, 정확도 -35.7pp.
- `gpt-5.4-mini`: smoke 1건에서 compact sheet-96이 62.1k tok / 65.9s라 pilot 확장 중단.
- `gpt-5.3-codex`, `gpt-5.4-nano`: ChatGPT 계정 Codex CLI에서 unsupported.

결론:
- Codex CLI 경로는 agent/developer context 오버헤드가 커서 80% 토큰 절감 목표에 부적합하다.
- Codex 모델 자체를 검증하려면 OpenAI API 직접 호출로 재측정해야 한다.
