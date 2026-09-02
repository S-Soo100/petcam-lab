# RBA Python 전수 계측 + OpenAI VLM 연구 설계

> 상태: 2026-08-03 owner 방향 승인, Claude 교차검수 반영, written spec 최종 확인 대기
>
> 목적: 모든 운영 영상을 Python으로 먼저 전수 계측하고 OpenAI VLM이 의미를 분석하는 초기 체제를
> 검증한 뒤, 충분한 사람 정답이 쌓였을 때만 Python/Gate의 책임을 단계적으로 확대한다.

## 1. 한 줄 목표

게코 영상 하나도 성급하게 버리지 않으면서, Python은 시간축을 정밀하게 재고 OpenAI VLM은 행동의
뜻을 해석하게 해 정확도 상한선과 실제 비용을 먼저 확인한다.

## 2. 이번 결정

1. 모든 영상은 Python 앞단을 거친다.
2. Python은 원본에 실제 존재하는 디코딩 가능 프레임을 최대 30fps까지 순서대로 전수 검사한다.
   원본이 30fps보다 낮거나 가변 fps이면 프레임을 복제하지 않고 실제 프레임을 전부 처리한다.
3. 초기에는 Python/Gate 결과와 관계없이 모든 영상을 OpenAI VLM으로 분석한다.
4. VLM은 전체 영상을 4fps로 보며, 6초 창과 1초 겹침으로 나눈 시간순 개별 프레임을 입력받는다.
5. Python이 변화 구간을 찾으면 그 구간은 최대 20fps 개별 프레임을 추가한다. API 한도는 요청을 더
   잘게 나눠 해결하며 프레임을 조용히 버리지 않는다. contact sheet는 사용하지 않는다.
6. Gecko Vision Gate는 초기에는 shadow evidence만 만들며 게코 검출 실패를 `없음`으로 확정하지 않는다.
7. local VLM, local text LLM, local router, 자동 사건 묶기, 자동 skip은 현재 연구 경로에서 사용하지 않는다.
8. Python/Gate/VLM 예측은 사람 GT와 분리된 versioned ledger에 저장하며 GT를 덮어쓰지 않는다.

## 3. 연구 데이터

### 3.1 초기 행동 데이터셋 316

| 구성 | 수량 | 사람 정답 계약 |
|---|---:|---|
| legacy `dataset-203` | 197 | 기존 manifest 행동 정답, highlight `include`는 Owner 일괄 확정, 행동 구간은 `not_measured` |
| 최근 Owner-final GT | 119 | 이동 highlight 108 + 휴식 highlight 6 + 물 마시기 4 + 슈퍼푸드 자율급여 1 |
| 합계 | 316 | 전부 highlight `include` |

316개는 행동 판별·설명·비용 평가에 쓴다. 전부 highlight 포함이므로 highlight include/exclude 선별
정확도는 이 데이터만으로 주장하지 않는다. legacy 197개는 행동 분류를 채점할 수 있지만, 행동 구간과
복수 행동 완전성은 새 사람 정답 없이 채점하지 않는다.

### 3.2 실제 대조군

다음 연구 단계에서 새 영상 또는 별도 사용 승인을 받은 실제 영상으로 대조군을 만든다.

- 동시에 보인 최대 게코 수 `0 / 1 / 2 / 3 / 4+`
- 게코가 가려지거나 일부만 보이는 영상
- 그림자, 카메라 흔들림, IR 전환, 빈 사육장, 디코딩 불량
- highlight `exclude`와 highlight 시작·종료 구간

과거 격리·삭제 대상으로 확정한 초기 영상은 연구 편의를 위해 다시 사용하지 않는다. 합성 영상은
파이프라인 smoke test에만 쓰고 최종 성적에는 포함하지 않는다.

### 3.3 개발과 평가 분리

- 행동·출처·camera-night 분포를 먼저 감사한다.
- 최대 20%를 development로 고정하고 입력·prompt·schema 선택에만 사용한다.
- 나머지는 sealed evaluation으로 두며 선택이 끝날 때까지 결과를 열지 않는다.
- 같은 clip, 인접 clip, 같은 사람 사건, 같은 camera-night가 development와 evaluation 양쪽에 나타나지
  않게 group split한다.
- 희귀 행동 수가 너무 작으면 개별 행동 성적을 과장하지 않고 정확한 분모와 `insufficient`를 보고한다.
- 모델·prompt·입력 계약을 고른 뒤 촬영된 future holdout을 최종 일반화 시험으로 별도 봉인한다.
- legacy 197개는 과거 모델·prompt 연구에 반복 사용됐으므로 누적 적응 위험이 있다. sealed evaluation
  성적은 회귀 참고값으로 보고, 최종 일반화 주장은 독립 future holdout으로만 한다.

## 4. Python 30fps 영상 계측기의 역할

### 4.1 맡는 일

- decode 가능 여부, 실제 fps, 해독 프레임 수, 영상 길이, 해상도
- 멈춤·중복·누락·timestamp 역행
- 밝기 분포, 암전·과노출, IR 전환 시각
- 화면 전체 흔들림과 국소 변화의 시간표
- 변화 onset/offset, burst, active ratio, coarse spatial region
- VLM이 더 촘촘히 볼 추가 구간
- Gecko Vision Gate에 전달할 순차 프레임 스트림

IR 전환 전후 기본 ±0.5초는 행동 움직임과 분리된 `lighting_transition`으로 표시한다. 수치는 카메라별
노이즈 바닥에 대한 상대값을 우선하고 단일 절대 motion threshold를 행동 뜻으로 사용하지 않는다.

### 4.2 맡지 않는 일

- 행동명·GT·하이라이트 확정
- OpenAI 호출 생략·프레임 감축·우선순위 큐잉
- 게코 검출 실패를 즉시 `게코 없음`으로 확정
- ROI crop만 보내 전체 맥락 제거
- 사건 자동 병합·영상 자동 삭제

### 4.3 결과 계약

요약 JSON `python-prescan-v1`은 16KiB 이하로 제한한다.

```text
schema_version / extractor_version / config_digest / media_sha256
decode: expected_frames, decoded_frames, source_fps, duration, invalid_reasons
lighting: brightness_summary, ir_transition_intervals
camera_motion: global_motion_summary, shake_intervals
activity: per_second_envelope, active_ratio, change_intervals, coarse_regions
vlm_support: dense_intervals, full_coverage_preserved=true
flags / truncation / producer / processed_at
```

프레임별 수치가 필요하면 압축 sidecar로 따로 저장하고 요약 JSON에 digest만 연결한다. 사람 GT, 행동명,
presence 확정값, router 판정, 원문 R2 key는 넣지 않는다. 동일 media/config/version 재실행은 멱등이며
알고리즘 변경은 기존 결과를 덮지 않고 새 version으로 append한다.

## 5. Gecko Vision Gate의 단계적 역할

### 5.1 초기 출력

초기 연구 기준선에서는 Gate도 Python이 디코딩한 모든 프레임을 본다. detector 입력 해상도와 전처리는
versioned config로 남기되 sparse frame sampling으로 결과를 좋게 보이게 하지 않는다. 처리량이 부족하면
프레임을 줄여 같은 시험으로 부르지 않고, tracker 보간 또는 sampling은 별도 비교군으로 다시 검증한다.
Gate는 각 프레임의 detection을 합쳐 다음 evidence를 별도 저장한다.

- 검출 시각, confidence, bbox, 연속 검출 시간
- 가장 선명한 근거 프레임 시각
- 가림·IR 전환·화면 흔들림 flag
- model/checkpoint/sampler/threshold provenance
- clip 상태: `present_candidate / not_observed / uncertain`

`not_observed`는 `absent`가 아니다. 초기에는 어떤 상태도 VLM 호출을 막지 않는다.

### 5.2 중기 전환

중기에는 다음 라우팅만 허용한다.

```text
present        → VLM 전수 분석
uncertain      → VLM 전수 분석
verified_absent → VLM 생략 후보 + 지속 감사
```

전환 전 필수 Gate:

1. 실제 `0/1/2/3/4+` 사람 정답과 가림·IR·그림자 반례를 포함한다.
2. threshold와 집계 정책을 development에서 고정한 뒤 future camera-night holdout을 통과한다.
3. `not_observed/uncertain/verified_absent`의 승격식 자체를 TEST-SHEET에 사전 등록한다. 여기에는 연속
   미검출 길이, frame/clip confidence 집계식, 가림·IR·흔들림 예외, 최소 유효 coverage가 포함된다.
4. `verified_absent`의 false negative 허용치와 통계적 표본 크기를 TEST-SHEET에 사전 등록한다.
5. shadow에서는 생략 후보도 100% VLM 비교한다.
6. 실제 생략을 시작해도 최소 10% 무작위 blind audit을 유지한다. 정확한 audit 비율은 예상 유입량과
   허용 오류로 power calculation한 뒤 deployment TEST-SHEET에 고정한다.
7. drift·모순·coverage 저하가 기준을 넘으면 즉시 초기의 전수 VLM으로 자동 복귀한다.

### 5.3 후기 확대 순서

1. 영상 무결성
2. 게코 있음·없음
3. 동시에 보인 최대 게코 수 `0/1/2/3/4+`
4. 게코 위치·trajectory
5. 활동 발생 시간 구간
6. highlight 후보 구간
7. 별도 사람 GT가 충분한 일부 명확 행동 후보

후기의 Python은 OpenCV 규칙만 뜻하지 않는다. Python runtime 안에서 실행되는 Gate와 별도 검증된 작은
vision/temporal model도 포함한다. highlight 확대는 include/exclude와 시간 구간 GT를 별도로 쌓은 뒤
새 연구로 연다. 현재 316 양성 데이터만으로 highlight selector를 학습·채택하지 않는다.

## 6. OpenAI VLM 입력과 출력

### 6.1 입력

- 전체 영상 4fps 시간순 개별 프레임
- 6초 window, 1초 overlap
- Python 변화 구간은 최대 20fps 개별 프레임 추가
- timestamp는 영상 기준 초로 명시
- 4fps 격자와 20fps 구간에 같은 timestamp/frame digest가 있으면 한 번만 전송하고, 최종 frame
  manifest에 source policy와 전체 coverage를 기록한다.
- contact sheet, 파일명의 행동명, 사람 GT, 과거 모델 답은 입력하지 않는다.
- API의 현재 모델·이미지 한도·가격은 실행 TEST-SHEET 동결 시 OpenAI 공식 문서로 다시 확인한다.

초기 연구는 정확도 상한선 시험이므로 clip 전체 dense frame 총량을 임의로 자르지 않는다. 변화가 영상
전체에 걸치면 전체를 최대 20fps로 더 작은 요청에 나눠 보낸다. 공식 API의 hard limit 때문에 끝까지
보낼 수 없으면 `incomplete_input`으로 남기고 성공으로 채점하지 않는다. 비용 최적화를 위한 clip별 cap은
초기 성능이 확인된 뒤 별도 연구에서만 다룬다.

Python 숫자 summary를 prompt에 넣는 것은 기본 OFF다. 숫자 자체가 모델 답을 유도하는지 별도 ablation에서
검증한 뒤에만 채택한다.

### 6.2 구조화 출력

- `primary_action`
- `observed_actions[]`
- `segments[]`: action, start_sec, end_sec, evidence_timestamps
- `max_visible_gecko_count`: `0 / 1 / 2 / 3 / 4+ / uncertain`
- `count_evidence_timestamps[]`
- `visibility / occlusion / quality_flags`
- `uncertainty`
- `user_summary`

모델의 숨은 reasoning은 저장 대상으로 요구하지 않는다. 사용자에게 확인 가능한 짧은 관찰 사실과 근거
시각만 저장한다.

### 6.3 window 결과의 clip 합성

- 모든 window는 `window_id`, planned/actual frame manifest, global start/end, status와 구조화 출력을
  append-only로 저장한다.
- overlap의 같은 timestamp/frame digest는 한 번의 시각 증거로 canonicalize한다.
- 같은 행동 segment가 겹치거나 간격 1초 이내로 이어지면 global timeline에서 union한다.
- `observed_actions`는 union, 대표 행동은 합쳐진 segment 총시간이 가장 긴 행동으로 고른다. 동률이면
  최초 근거시각, 그다음 고정 행동 vocabulary 순서로 결정한다.
- 개체 수는 window의 확정 숫자 중 최대값을 취하되 어느 window라도 count가 uncertain이면 별도
  `count_uncertain=true`를 보존한다. 확정 숫자가 하나도 없으면 전체 count는 `uncertain`이다.
- window 하나라도 실패하거나 계획 coverage가 빠지면 clip은 `incomplete`이고 정식 성적·사용자 결과에서
  제외한다. 누락 window를 다른 window 결과로 추정하지 않는다.
- `user_summary`는 이 결정론적 구조화 결과에서 별도 생성하며 핵심 정답 채점에는 사용하지 않는다.

## 7. 핵심 실험

같은 평가 영상·모델·prompt·schema·retry 규칙으로 paired 3-arm을 실행한다.

| Arm | 입력 | 질문 |
|---|---|---|
| A | 전체 4fps | 충분한 전체 커버리지의 기준 성능 |
| B | A + Python 숫자 summary | 숫자 evidence가 실제로 돕는지, 오히려 환각을 유도하는지 |
| C | A + Python 지정 변화 구간 최대 20fps | Python-directed extra visual coverage 정책이 짧은 행동·시간·개체 수를 회수하는지 |

- 프레임 추가 정책은 결과를 보기 전에 고정한다.
- API 한도는 요청 분할로 해결하며 일부 구간 실패 시 해당 구간만 재시도한다.
- C는 순수 숫자 evidence가 아니라 `Python 구간 지정 + 추가 frame`의 결합 정책이다. 프레임 수 차이는
  의도된 개입이며, 효과를 Python 숫자 단독 효과라고 주장하지 않는다.
- C의 효과는 정확도뿐 아니라 추가 frame/token/call/latency를 전량 함께 보고한다.
- B와 C는 paired recovered/broken을 모두 센다. 좋아진 사례만 세지 않는다.
- B가 효과가 없거나 환각을 늘리면 summary prompt 주입을 기각하되 Python 계측 자체는 유지한다.

## 8. 평가 항목

| 영역 | 지표 |
|---|---|
| 대표 행동 | exact accuracy, class별 precision/recall, macro F1, confusion matrix |
| 복수 행동 | 완전 GT가 있는 subset의 multi-label precision/recall, 누락률 |
| 시간 구간 | 측정된 subset만 boundary error와 interval IoU |
| 개체 수 | exact accuracy, `0/1/2/3/4+` confusion matrix, evidence time 적합성 |
| 존재 여부 | present recall, false-absent, uncertain rate, camera-night별 drift |
| 설명 품질 | 없는 행동·개체를 만든 비율, 사람 blind 사실성 감사 |
| 신뢰성 | schema success, retry, timeout, 누락 window, fail-open 발생 |
| 운영성 | clip당 Python/VLM latency, CPU/RSS, frame/token/call, 실제 비용, 월 2만 예상 |

legacy 197는 manifest 행동 정답으로 행동 분류를 채점한다. 행동 구간·복수 행동 완전성·개체 수는 새 GT가
있는 경우에만 채점한다. 316개로 highlight selector precision을 보고하지 않는다.

## 9. 실패와 안전 계약

1. Python prescan 실패는 VLM 호출을 막지 않는다. 기본 4fps extraction으로 fail-open하고 실패를 재처리한다.
2. VLM 기본 4fps coverage 실패는 성공으로 기록하지 않는다.
3. Gate detector 미검출은 초기·중기 검증 전 `absent`가 아니다.
4. 한 window 실패는 다른 window 결과를 버리지 않되 최종 clip 상태는 incomplete로 남긴다.
5. Python/Gate/VLM 결과는 append-only versioned ledger로 분리한다.
6. 모델·config·media digest가 없는 결과는 정식 성적에 포함하지 않는다.
7. 비밀값·개인정보·원문 GT·private R2 key는 보고서와 로그에 출력하지 않는다.
8. 자동 skip·자동 사건 병합·자동 GT·사용자 알림은 별도 adoption Gate 전까지 금지한다.

## 10. 단계별 체크리스트

### Phase 0 — 정본과 시험지

- [ ] 316개 unique media와 isolated dataset R2 copy를 이중 검증한다.
- [ ] `dataset-203`이라는 역사 이름과 실제 frozen manifest 197행의 count/digest를 고정한다. 별도의
  203행 원본 목록이 확인될 때만 차이 목록과 사유를 기록하고, 확인되지 않은 6개 제외를 꾸며내지 않는다.
- [ ] legacy 197 행동 GT·Owner highlight include·segment not_measured provenance를 고정한다.
- [ ] recent 119의 행동·highlight·사람 provenance를 고정한다.
- [ ] development/evaluation/future holdout의 group leakage를 검사한다.
- [ ] 실제 `0/1/2/3/4+`·무효·highlight exclude 대조군 수집 계획을 별도 고정한다.

### Phase 1 — Python prescan 연구 구현

- [ ] native decoded frames 전수 순차 처리와 VideoCapture release를 검증한다.
- [ ] decode/lighting/camera-motion/activity/dense-interval schema와 16KiB cap을 검증한다.
- [ ] 30초·60초·가변 fps·IR 전환·손상 영상 fixture를 통과한다.
- [ ] 메모리 상한, 처리량, temp media 0, 멱등 재처리를 검증한다.
- [ ] Python 실패가 VLM queue를 막지 않는 fail-open probe를 통과한다.

### Phase 2 — OpenAI VLM 입력 계약

- [ ] 공식 문서로 모델·이미지 입력 한도·가격·structured output을 확인해 TEST-SHEET에 동결한다.
- [ ] 전체 4fps, 6초/1초 overlap, 변화 구간 최대 20fps 규칙을 고정한다.
- [ ] 예상 frame/window와 실제 API 입력 manifest가 exact 일치하는지 검사한다.
- [ ] prompt/schema/retry/timeout/예산을 결과 열람 전에 고정한다.

### Phase 3 — 3-arm 행동·개체 수 연구

- [ ] A/B/C가 같은 media/model/prompt/schema를 사용한다.
- [ ] 사람 GT key가 API input·model output에 노출되지 않았음을 감사한다.
- [ ] 행동·복수 행동·시간·개체 수·환각·비용을 독립 recompute한다.
- [ ] recovered와 broken, 전체·행동별·camera-night별 결과를 함께 보고한다.
- [ ] 숫자 summary와 extra frames를 각각 ADOPT/REJECT/HOLD로 판정한다.

### Phase 4 — Gate 존재·개체 수 shadow

- [ ] 초기 기준선에서 Gate가 실제 decoded frame 전부를 입력받았는지 frame manifest로 검증한다.
- [ ] Gate frame/clip ledger에 checkpoint·threshold·timestamp·bbox provenance를 보존한다.
- [ ] `present_candidate/not_observed/uncertain`와 VLM·사람 정답의 confusion을 측정한다.
- [ ] 0마리 및 가림·IR·그림자 real control을 포함한다.
- [ ] 초기에는 VLM 전량 호출과 결과 비교를 유지한다.
- [ ] future holdout 통과 전 `verified_absent`와 VLM 생략을 생성하지 않는다.

### Phase 5 — 중기 전환 판단

- [ ] false-absent 허용치·표본 크기·audit 비율·자동 원복 조건을 사전 등록한다.
- [ ] 생략 후보 100% shadow 비교를 완료한다.
- [ ] 별도 owner 승인 뒤에만 `verified_absent` VLM 생략 canary를 연다.
- [ ] uncertain은 항상 VLM으로 보내고, 생략 대상의 최소 10% blind audit을 유지한다.
- [ ] drift 발생 시 전수 VLM으로 자동 복귀하는 실제 probe를 통과한다.

### Phase 6 — 후기 Python 확대

- [ ] 개체 수·trajectory·활동 구간을 각각 독립 TEST-SHEET로 검증한다.
- [ ] highlight include/exclude·시간 구간 사람 GT가 충분할 때만 highlight 연구를 연다.
- [ ] 각 기능은 사람 정답과 future holdout을 통과한 뒤 하나씩 채택한다.
- [ ] OpenCV 수치만으로 행동 의미·사용자 중요도를 확정하지 않는다.

## 11. 연구 완료 판정

초기 연구의 완료는 다음 산출물이 모두 있을 때다.

- Dataset 316 + real control의 frozen manifest와 provenance
- `python-prescan-v1` validator와 운영 성능표
- OpenAI model/prompt/input version이 고정된 prediction ledger
- A/B/C paired 성적표와 독립 재계산 일치
- 행동·개체 수·환각·비용의 분모가 명확한 최종 보고서
- Gate의 현재 단계와 다음 단계 전환 조건
- production 자동 skip·GT·알림 변경 0 확인

## 12. 현재 설계가 대체하는 과거 계획

2026-07-16~17의 Python Evidence Hybrid/Universal Worker 문서는 당시 selector 비용 절감과
Gate ROI/dwell/periodicity 활용을 연구하던 이력이다. 구현·성능 이력은 보존하지만 다음 항목은 현재
채택 경로가 아니다.

- VLM 호출 clip 수 또는 frame 수 감소
- Python evidence 기반 router/selector
- ROI crop 중심 VLM 입력
- local text LLM 의미 해석
- 자동 skip·자동 행동 후보의 운영 사용

현재 정본은 `전수 Python 계측 → 초기 전수 OpenAI VLM → 검증된 absent만 중기 생략 → 후기 기능별 확대`다.
과거 문서는 삭제하지 않고 추후 SOT 정리에서 `superseded/invalid-for-adoption` 상태와 이 문서 링크를 단다.
