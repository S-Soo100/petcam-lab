# OpenAI VLM 월 2만 영상 비용·운영 선택지

> 상태: `OPTION_UNDER_REVIEW`
> 작성일: 2026-08-03
> 범위: 비용 산정과 파일럿 선택지 문서화만. API key 발급·production 연결·DB/R2/service 변경은 승인하지 않는다.

## 1. 질문

월 2만 개 영상을 모두 VLM이 실제로 보고 행동·근거·확신도를 만들게 할 때, 현재 Mac mini local
VLM을 계속 확대하는 것과 OpenAI API를 사용하는 것 중 무엇이 가격 대비 효율적인가?

여기서 "VLM 분석"은 MP4 원본을 API에 직접 넣는다는 뜻이 아니다. 현재 OpenAI GPT 모델은 image
input을 지원하고 video input은 지원하지 않으므로, 현재 설계와 같은 **영상당 시간순 12프레임
추출 → 이미지 VLM 판독 → 짧은 구조화 JSON 출력**을 뜻한다.

## 2. 지금까지 확인된 local 한계와 투입 시간

- 상시 가동 Mac mini는 Apple M1, unified memory 16GB다.
- 2026-07-09 local router 연구를 시작했고 2026-07-12 유효성 감사에서 v0/v1/v2와 care-guard를
  `invalid-for-adoption`으로 확정했다.
- Gemma 3 4B router는 30/30을 `cloud_now`로 보내 비용 절감 효과가 없었다. Qwen 14B도 28/30을
  `cloud_now`로 보냈고 평균 latency는 6.31초였다.
- 2026-08-02 사건 경계 baseline에서 MiniCPM-V는 human-different 17/17을 전부 same으로 합쳤고,
  Qwen3-VL 2B는 47/74가 empty content·schema 0이며 swap 안전선을 넘었다.
- Gemma 3 4B clip canary는 contact sheet 6프레임과 개별 12프레임 모두 합성 static/moving Gate를
  통과하지 못해 production request 0으로 종료됐다.
- 32GB MacBook 비교에서도 Gemma 4B Q8은 4/18, Qwen3-VL 8B는 12/18로 합성 Gate를 실패했다.
  12B와 30B는 swap 안전선을 넘어 품질시험을 완료하지 못했다.
- 최근 집중 검증은 git 기록 기준 2026-08-02 15:40~22:01 약 6시간 20분 wall-clock이다. 설계,
  Claude 교차검수, 구현, 설치, 실행, 보고서 작성이 포함됐으며 사람의 순수 인시와 같지는 않다.

따라서 현재 병목은 하나가 아니다. 작은 모델은 실행되지만 판단 품질이 부족하고, 더 큰 모델은 현재
장비에서 안전하게 평가하기 어렵다. 더 큰 Mac을 사는 것만으로 품질이 해결된다는 증거도 아직 없다.

## 3. 비용 계산 계약

### 3.1 공통 가정

- 월 입력: 영상 20,000개
- 영상당 입력: 768×432 시간순 JPEG 12장
- 텍스트 prompt: 약 500 token
- 구조화 output: 약 200 token
- reasoning effort: `none`
- 환율: 1 USD ≈ 1,460 KRW인 비교용 가정
- 이미지 token: 32×32 patch 공식에 해당 모델 multiplier를 적용
- 일반 호출과 24시간 completion window의 Batch API를 분리

실제 비용은 원본 종횡비, 프레임 크기, 출력 길이, retry, 환율에 따라 달라진다. 따라서 아래 금액은
구매·운영 결정을 위한 추정치이고, production 예산은 실제 300건 usage ledger로 다시 계산해야 한다.

### 3.2 월 20,000개 전수 VLM 분석 추정

| 모델 | 역할 후보 | 일반 호출/월 | Batch API/월 | 현재 해석 |
|---|---|---:|---:|---|
| GPT-5 mini | 최저가 비교군 | 약 6.3만 원 | 약 3.2만 원 | 품질 Gate 통과 전 primary 채택 금지 |
| GPT-5.4 mini | 전수 1차 후보 | 약 18만 원 | **약 9만 원** | 현재 가격·품질 균형 기준선 |
| GPT-5.6 Luna | 최신 저가형 비교군 | 약 16.7만 원 | 약 8.4만 원 | 공식상 이전 nano tier 대응, 5.4 mini 대비 절감 폭이 작음 |
| GPT-5.6 Terra | 어려운 표본 재검수 후보 | 약 42만 원 | **약 21만 원** | 전수보다 10~20% escalation 후보 |

Batch API는 결과가 최대 24시간 안에 돌아오는 대신 동기 호출 대비 50% 할인된다. 야간 펫캠 분석은
즉시 사용자 응답보다 다음날 timeline 완성이 중요하므로 비용 계약과 잘 맞는다.

## 4. 현재 선호하지만 미확정인 운영안

```text
원본 영상 20,000개/월
  → Python/OpenCV가 영상당 시간순 12프레임 + Evidence 생산
  → GPT-5.4 mini Batch가 20,000개 모두 1차 분석
  → 사전 동결한 위험 규칙에 걸린 10~20%를 GPT-5.6 Terra Batch가 2차 분석
  → 1~2% 사람 표본감사 + disagreement/error 전수 검수
```

예상 월비용은 GPT-5.4 mini 전수 약 9만 원에 Terra 10% 재검수 약 2.1만 원 또는 20% 재검수 약
4.2만 원을 더한 **약 11만~13만 원**이다. retry·출력 증가·환율 여유를 포함한 초기 운영 예산은
**월 15만 원**으로 잡는다.

이 구조에서도 모든 영상은 최소 한 번 VLM 분석을 받는다. escalation은 분석 자체를 생략하는 skip이
아니라 어려운 영상을 한 번 더 보는 절차다. model self-confidence 하나만으로 escalation을 결정하지
않고 Python Evidence integrity, schema 오류, 중요한 care 후보, 모델 간 불일치 같은 사전등록 규칙을
함께 사용한다.

## 5. 왜 아직 채택이 아닌가

가격표만으로 게코 행동 품질은 알 수 없다. 특히 그림자, 정지, position jump, 미세 접촉 행동은 local
모델이 반복해서 실패한 영역이다. cloud 모델도 owner-final GT에서 같은 Gate를 통과해야 한다.

다음 300건 파일럿 전에는 아래를 금지한다.

- production API key 연결 및 월 20,000건 전수 호출
- 행동 GT 덮어쓰기, 자동 사건 병합, 자동 skip, cloud 차단
- 사용자 timeline/케어 알림 노출
- 같은 development 정답을 본 뒤 prompt·threshold를 반복 조정하는 것

## 6. 채택 전 300건 파일럿 Gate

1. Owner-final 사람 GT에서 행동·경계·게코 부재·촬영 오류 strata를 사전 동결한다.
2. GPT-5 mini, GPT-5.4 mini, GPT-5.6 Terra에 동일한 12프레임·prompt·JSON schema를 보낸다.
3. 행동별 recall/precision, 사건 over-merge, schema 성공률, latency, 실제 input/output/reasoning token,
   retry와 영상당 원화 비용을 기록한다.
4. 가장 싼 모델이 품질 Gate를 통과하면 그 모델을 전수 1차 후보로 선택한다. 통과하지 못하면
   GPT-5.4 mini 또는 Terra로 올린다.
5. 독립 holdout과 owner 승인 전에는 `OPTION_UNDER_REVIEW`를 유지한다.

## 7. 현재 판단

- **가격만 보면:** 월 2만 영상은 Mac Studio 선구매보다 Batch API 파일럿이 작고 가역적인 투자다.
- **가격 대비 선호안:** GPT-5.4 mini 전수 + Terra 10~20% 재검수, 월 예산 15만 원.
- **확정되지 않은 것:** 게코 행동 품질, escalation 비율, 실제 token/원화 비용, 개인정보·보존 정책,
  production key 관리와 장애 fallback.
- **다음 결정:** 300건 TEST-SHEET와 실제 usage ledger를 먼저 동결할지 Owner가 선택한다.

## 8. 공식 가격·토큰 근거

- [GPT-5.4 mini 모델·가격](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
- [GPT-5.6 Luna 모델·가격](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [GPT-5.6 Terra 모델·가격](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [이미지 입력과 patch token 계산](https://developers.openai.com/api/docs/guides/images-vision)
- [Batch API 24시간·50% 할인](https://platform.openai.com/docs/api-reference/batch/object?api-mode=responses)

## 9. 2026-08-03 구독 CLI 사건 경계 실측

비용 후보 세 모델을 Mac mini ChatGPT 구독 Codex CLI에서 local VLM과 동일한 74개 사건 경계로 먼저
측정했다. 이미지·schema 처리 자체는 세 모델 모두 `74/74`, error/quota 0으로 성공했다. 그러나
over-merge는 GPT-5.4 Mini `12`, Luna `14`, Terra `10`으로 모두 safety Gate를 실패했다.

이 결과로 확정된 것은 두 가지다.

- 현재 prompt/input/model 조합을 **자동 사건 묶기**에 쓰지 않는다.
- 구독 CLI image+structured-output 경로는 222/222로 기술 실행 가능하다.

사건 경계는 행동 이름을 붙이는 시험이 아니므로 월 2만 건의 행동·관찰 VLM 가능성은 아직 미측정이다.
따라서 4장의 preferred 비용안은 계속 `OPTION_UNDER_REVIEW`이고, 다음 owner-final 300건 API pilot은
경계와 행동/관찰 점수를 분리해야 한다. [구독 CLI 보고서](../../../experiments/openai-subscription-vlm-event-boundary-v1/REPORT.md).
