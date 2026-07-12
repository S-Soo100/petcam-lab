# Local VLM 학습 전략 — 기획 캡처

> **상태:** 📥 기획 캡처 / SOT 미반영
> **작성:** 2026-07-12
> **목적:** 여러 세션이 동시에 진행되는 동안 local VLM 학습 논의가 유실되거나 기존 전략 문서와 충돌하지 않도록, 합의 내용과 미확정 항목을 격리 보존한다.
> **주의:** 이 문서는 현재 방향을 보존하는 임시 설계 기록이다. production 결정이나 구현 승인을 의미하지 않는다.

## 1. 배경

petcam-lab의 RBA는 민감하게 캡처한 야간 영상을 행동 타임라인과 케어 시그널로 바꾸는 시스템이다. 현재 연구는 cloud/구독 기반 VLM 판독 품질, SegmentVLM, OpenCV evidence, detector gate, detector-independent router 등 여러 트랙으로 나뉘어 있다.

이번 논의에서는 다음 질문을 검토했다.

1. GT 라벨 영상을 계속 추가하면 petcam 전용 local VLM을 향상시킬 수 있는가?
2. 별도 컴퓨터에서 모델을 24시간 연속학습하는 방식이 타당한가?
3. 컴퓨터를 구매하기 전에 cloud CUDA GPU로 검증한다면 비용은 어느 정도인가?

## 2. 현재 결론

### 2.1 채택할 방향

- 운영 환경의 GT 영상이 계속 쌓이면 open-weight VLM을 petcam 도메인에 맞게 fine-tuning하여 일부 행동의 판독 성능을 향상시킬 수 있다.
- 처음부터 모델 전체를 학습하지 않고 LoRA/QLoRA 같은 parameter-efficient fine-tuning으로 검증한다.
- 새 GT가 들어올 때마다 즉시 weight를 갱신하지 않는다. 일정량의 검수된 데이터가 쌓일 때마다 버전이 고정된 batch 학습을 수행한다.
- 신규 데이터만 학습하지 않고 기존 데이터의 균형 표본을 함께 replay하여 catastrophic forgetting과 최근 분포 과적합을 줄인다.
- 학습한 challenger는 고정 blind test와 운영 holdout에서 기존 baseline보다 좋아진 경우에만 승격한다.
- local VLM은 처음부터 RBA 전면 대체재로 쓰지 않는다. 먼저 비교적 큰 시각 신호가 있는 좁은 역할이나 1차 판독 후보로 검증한다.

초기 우선 후보:

- `moving`
- `unseen`
- `hand_feeding`
- 사람/도구/세팅 노이즈 구분
- IR 환경에서 모프의 흰 무늬를 `shedding`으로 오인하는 실패모드 보정

### 2.2 채택하지 않을 방향

- 별도 컴퓨터를 구매해 같은 데이터로 24시간 계속 학습시키지 않는다.
- 신규 GT 한 건마다 production 모델을 온라인 업데이트하지 않는다.
- `dataset-203` 성능만 보고 production 채택을 결정하지 않는다.
- local VLM의 자체 confidence만으로 P0 행동을 영구 skip하거나 자동 확정하지 않는다.
- 원본 영상 또는 학습 입력에 판독 가능한 시각 정보가 없는 문제를 fine-tuning으로 해결할 수 있다고 가정하지 않는다.
- cloud GPU PoC 전에 고가 학습용 컴퓨터를 구매하지 않는다.

## 3. 중요한 기술적 경계

### 3.1 학습으로 개선 가능한 문제

- IR 야간 영상과 게코 모프에 대한 domain adaptation
- 사람 손, 도구, 먹이그릇 등 petcam 특화 객체와 장면
- 카메라별 고정 배경과 반복되는 환경 패턴
- petcam 행동 taxonomy 및 구조화된 출력 형식
- 반복적으로 관찰되는 체계적 오분류

### 3.2 학습만으로 해결하기 어려운 문제

- 혀-물 접촉이 원본 픽셀에 충분히 기록되지 않은 `drinking`
- frame sampling 사이에서 사라지는 짧은 행동
- 심한 흔들림, 압축, 원거리 촬영으로 시각 정보가 소실된 영상
- 단일 top-1 clip label로 표현할 수 없는 복수 행동과 시간대 정보

이 문제들은 학습보다 다음 레버가 우선일 수 있다.

- 캡처 해상도와 셔터/조명 개선
- ROI 기반 고해상도 입력
- event segment와 시간축 샘플링
- 전용 temporal classifier
- HITL 및 원본 확인

## 4. 데이터 전략

### 4.1 `dataset-203`의 역할

현재 197개 유효 샘플은 학습 코드와 데이터 포맷을 검증하는 PoC에는 사용할 수 있다. 그러나 클래스별 표본이 적고 `unseen` 운영 분포가 충분히 반영되지 않아 production 학습 효과를 일반화하기에는 부족하다.

초기 용도:

- Qwen 계열 2B/4B VLM LoRA가 실행되는지 확인
- overfit 가능성과 학습 곡선 확인
- 기존 baseline과 동일한 blind scorer 연결
- 실패모드별 정성 비교

### 4.2 앞으로 축적할 라벨

top-1 행동 라벨 외에 다음 정보를 가능한 범위에서 함께 저장한다.

- 행동 라벨
- 행동 시작/종료 시점
- 게코 visible 여부
- 카메라와 개체 식별자
- 주야간/IR 상태
- ROI 또는 행동 위치
- 영상 품질
- 사람/그림자/세팅 노이즈
- 확실함/애매함/판독 불가
- owner correction과 라벨 provenance

### 4.3 데이터 분할 원칙

- 같은 밤의 연속 clip이 train과 test에 동시에 들어가지 않게 한다.
- 날짜, 카메라, 개체 단위로 holdout을 분리한다.
- 학습 중 threshold나 prompt를 조정하는 validation set과 최종 blind test를 분리한다.
- 기존 회귀셋과 미래 운영 holdout을 모두 통과해야 한다.
- hard negative와 희귀 P0를 의도적으로 보존하되 실제 운영 class prior도 별도로 측정한다.

## 5. 학습·승격 흐름

```text
운영 영상
→ 사용자/HITL GT
→ 라벨 QA 및 provenance 기록
→ 누적 dataset snapshot 생성
→ train/validation/blind holdout 고정
→ LoRA challenger 학습
→ deterministic scorer + 실패모드 분석
→ 기존 baseline과 paired 비교
→ 통과 시 shadow/canary
→ production 승격 또는 reject/hold
```

학습은 wall-clock 기준 상시 실행이 아니라 다음과 같은 데이터 이벤트를 기준으로 시작한다.

- 신규 검수 GT가 의미 있는 batch로 누적됨
- 특정 실패모드의 positive와 negative가 함께 확보됨
- 새로운 카메라/개체/IR 환경 분포가 충분히 쌓임
- 이전 challenger가 실패한 원인을 검증할 데이터가 확보됨

구체적인 최소 샘플 수와 학습 주기는 첫 cloud GPU PoC의 학습 곡선과 클래스별 분산을 본 뒤 별도 experiment spec에서 사전 등록한다.

## 6. 초기 모델 및 하드웨어 방향

### 6.1 모델 후보

- 1차: video fine-tuning 경로가 공개된 Qwen 계열 2B
- 2차: 2B에서 학습 신호가 확인될 때만 4B
- 8B 이상: 작은 모델이 구조적으로 부족하다는 증거가 있을 때 검토

처음부터 큰 모델을 쓰지 않는 이유는 이번 단계의 질문이 최고 정확도 달성이 아니라 다음 두 가지를 확인하는 것이기 때문이다.

1. petcam GT가 open VLM의 도메인 성능을 실제로 개선하는가?
2. 개선 폭이 학습·운영 비용을 정당화하는가?

### 6.2 구매 결정

- cloud CUDA GPU로 2B/4B PoC를 먼저 수행한다.
- 실제 GPU 시간, VRAM, 실패 재실행률, 학습 빈도를 측정한다.
- 반복 사용량이 장비 구매 손익분기점을 넘는 경우에만 NVIDIA 데스크톱 또는 다른 학습 장비를 검토한다.
- 기존 Apple Silicon 장비는 데이터 가공, inference, 가벼운 실험에 계속 활용할 수 있으나, 공식 video VLM 학습 생태계는 CUDA 중심임을 전제로 한다.

## 7. Cloud GPU 예산 가드

2026-07-12 조사 시점의 대략적인 RunPod Pod 가격과 환율 `1 USD ≈ 1,500 KRW`를 기준으로 한다. 실제 착수 시 가격과 환율을 다시 확인한다.

| 실험 범위 | 예상 GPU 시간 | 예상 예산 |
|---|---:|---:|
| 최소 실행 스모크 | 3~6시간 | 약 2천~5천 원 |
| 현실적인 1차 PoC | 15~30시간 | 약 1만~6만 원 |
| 셋업 실패·재실행 포함 1차 예산 | 최대 30시간 | **상한 10만 원** |
| 2B/4B/8B 및 다중 설정 연구 | 50~120시간 | 약 3만~52만 원 |

초기 승인 범위 제안:

```text
총예산 상한: 10만 원
대상: Qwen 계열 2B, 성공 시 4B
GPU: 48GB급 A40/A6000 또는 필요 시 A100 80GB
총 GPU 시간: 최대 30시간
실험 수: baseline 1회 + LoRA 2~3회 + blind 평가
```

비용 가드:

- 학습하지 않는 동안 GPU Pod를 종료한다.
- persistent volume은 필요한 checkpoint와 dataset snapshot만 남긴다.
- 학습 시작 전에 1회 run의 시간·비용 상한을 설정한다.
- OOM, 잘못된 dataset path, validation 오류는 즉시 중단한다.
- retry는 인프라성 일시 오류에만 허용한다.
- 각 run에 모델, dataset snapshot, GPU, 시간, 비용, 결과를 기록한다.

## 8. 기존 RBA 연구와의 관계

이 기획은 기존 연구를 대체하지 않는다.

| 기존 트랙 | 관계 |
|---|---|
| Claude subscription research | 판독 품질과 입력표현 연구를 위한 기준선/teacher 후보. local VLM 자동 라벨 정답으로 사용하지 않는다. |
| Detector-Independent Local Router | cloud 호출 우선순위 연구. local VLM fine-tuning과 별도 metric 및 산출물을 유지한다. |
| Evidence-First Cascade | adaptive frame/evidence 입력을 local VLM 학습·추론에서도 재사용할 수 있다. |
| SegmentVLM | event-level GT와 시간대 annotation을 생성하는 데이터 공급원이 될 수 있다. |
| Gate/Detector | gecko presence와 ROI evidence를 제공할 수 있으나, gate v2 reject 상태에서 필수 입력으로 만들지 않는다. |
| HITL | 검수된 GT와 hard negative를 공급하는 핵심 데이터 flywheel이다. |

연구 트랙 혼합 금지:

- Claude의 예측을 사람 GT처럼 local VLM 학습 정답에 자동 편입하지 않는다.
- router용 metadata-only 판단과 영상 의미판정 모델의 정확도를 같은 metric으로 합치지 않는다.
- local VLM이 특정 클래스에서 좋아져도 production 전수분석기로 바로 승격하지 않는다.
- detector가 gate 품질 기준을 통과하기 전에 detector miss를 안전한 skip 근거로 쓰지 않는다.

## 9. 첫 experiment spec이 답해야 할 질문

이 캡처를 정식 실험으로 승격할 때 아래 질문과 판정 기준을 사전 등록한다.

1. Qwen 계열 2B baseline은 고정 blind test에서 어느 정도인가?
2. 같은 모델의 LoRA가 baseline 대비 어떤 클래스를 회복하고 무엇을 깨뜨리는가?
3. 개선이 날짜·카메라·개체 holdout에서도 재현되는가?
4. 2B에서 4B로 커질 때 개선 폭이 비용 증가를 정당화하는가?
5. classifier 역할과 generative VLM 역할 중 어느 쪽이 더 안정적인가?
6. adaptive frames와 short video 중 어떤 입력이 정확도/비용 균형이 좋은가?
7. P0 false negative와 false highlight가 기존 production/연구 baseline보다 나빠지지 않는가?
8. local VLM이 담당할 수 있는 가장 좁고 안전한 production 역할은 무엇인가?

초기 decision label:

- `adopt-specialist`: 좁은 역할에서 독립 holdout 개선과 비용 이득이 확인됨
- `hold-data-limited`: 학습 신호는 있으나 데이터가 부족하거나 분산이 큼
- `hold-model-limited`: 데이터는 충분해 보이나 작은 모델 용량 또는 입력표현이 병목
- `reject`: 독립 holdout에서 개선이 없거나 기존 P0 안전성을 훼손함

## 10. SOT 반영 계획

현재 진행 중인 세션과 작업트리가 정리된 뒤 통합 전용 세션 하나에서만 반영한다.

반영 후보:

1. `docs/AI-VIDEO-ANALYSIS-STRATEGY.md`
   - 장기 fine-tuning/data flywheel 방향
   - 24시간 연속학습이 아닌 batch challenger 구조
   - cloud PoC → 장비 구매 판단 순서
2. 신규 정식 experiment spec
   - 데이터 snapshot, 모델, GPU, 예산, blind split, 채택 기준
3. `specs/README.md`
   - 신규 실험 상태와 연결 문서
4. `specs/next-session.md`
   - 착수 조건과 우선순위

통합 순서:

```text
진행 중 세션 종료/변경 범위 확인
→ git diff --stat으로 전체 변경 overview
→ 이 캡처 문서와 현재 SOT 대조
→ 중복·충돌 결정 목록 작성
→ 사용자 확인
→ 정식 spec 작성
→ SOT 문서별 순차 반영
→ 링크·상태·체크박스 검증
```

## 11. 아직 확정하지 않은 항목

- 첫 open VLM의 정확한 모델/checkpoint
- cloud GPU 제공자와 GPU 종류
- 실제 학습 dataset 크기 및 클래스 균형 기준
- GT batch가 몇 건 쌓일 때 재학습할지
- image/multi-frame/video 중 첫 학습 입력표현
- vision encoder, projector, LLM 중 어느 부분에 LoRA를 적용할지
- local specialist의 첫 production 역할
- inference 실행 위치와 SLA
- 장비 구매 손익분기점

이 항목들은 구현 중 임의 결정하지 않는다. 첫 experiment spec의 pre-registration 단계에서 사용자와 합의한다.

## 12. 현재 권고

지금은 구현이나 장비 구매를 시작하지 않는다. 이 문서를 기획 캡처 상태로 보존하고, 진행 중인 router/운영 세션이 정리된 뒤 별도 통합 세션에서 정식 experiment spec으로 승격한다.

다음 승인 관문은 다음 중 하나다.

1. 문서 내용 검토·수정 후 기획 캡처로 확정
2. 진행 중 세션 정리 후 SOT 통합 승인
3. 정식 cloud GPU PoC experiment 설계 승인
