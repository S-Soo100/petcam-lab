# Gecko Motion Engine v1 설계

> 상태: `OWNER_APPROVED`
> 승인일: 2026-08-03 KST
> 이름: **Gecko Motion Engine(GME, 게코 움직임 측정 엔진)**

## 1. 한 줄 결정

기존 `Python Evidence`의 신규 이름과 역할을 **Gecko Motion Engine**으로 확정한다. GME는
모든 영상을 최대 30fps로 분석하면서 Gecko Vision Gate를 계속 업그레이드해 사용하고, 게코
검출·개체 추적·노이즈 제거를 거쳐 **게코가 실제로 움직인 시간**을 측정한다.

기존 `Python Evidence` 이름은 과거 DB provenance, experiment, report의 역사 식별자에서만
보존한다. 과거 기록을 소급 개명하지 않는다.

## 2. 제품 지표 정의

사용자 대표 지표는 `verified_moving_sec_any_gecko`다. 한 마리 이상이 실제로 움직인 시간의
합집합을 초 단위로 계산한다. 두 마리가 같은 10초 동안 동시에 움직여도 사용자 활동시간은
10초다. 내부 연구 지표로는 개체별 움직임 시간을 더한 `moving_gecko_seconds`도 별도로 둔다.

프레임·시간 구간 상태는 다섯 가지다.

| 상태 | 의미 | 사용자 활동시간 |
|---|---|---|
| `moving` | 게코 몸의 실제 위치·자세 변화가 확인됨 | 포함 |
| `static` | 게코가 보이지만 움직임이 확인되지 않음 | 제외 |
| `not_visible` | 게코가 화면에 보이지 않음 | 제외, 별도 시간 기록 |
| `unknown` | 가림·검출 실패·노이즈로 판단할 수 없음 | 0으로 만들지 않고 미측정 기록 |
| `camera_motion` | 카메라나 화면 전체 변화가 지배적임 | 제외, 품질 문제로 기록 |

사용자 결과는 `확인된 활동시간`, `관찰 가능 시간`, `판단 불가 시간`을 함께 표시해야 한다.
현재 production `activity-v1`의 clip-duration 기반 `effective_activity_sec`는 이 정의와 다르므로
`legacy estimated activity`로 취급하고 GME가 검증되기 전 교체하지 않는다.

## 3. 시스템 경계

```text
RBA
└─ Gecko Motion Engine
   ├─ Media QA: decode·FPS·밝기·동결·카메라·IR 변화
   ├─ Gecko Vision Gate: bbox/mask/confidence
   ├─ Multi-gecko Tracker: 프레임 간 동일 개체 연결
   ├─ Motion Normalizer: 흔들림·노출·IR·카메라별 크기 보정
   ├─ State Estimator: moving/static/not_visible/unknown/camera_motion
   └─ Time Aggregator: any-gecko seconds + gecko-seconds
```

GME는 행동명, 물 마시기, 먹이 섭취, 하이라이트를 확정하지 않는다. VLM 호출 여부를 결정하거나
영상을 자동 skip하지도 않는다. 모든 영상은 별도 VLM 정책에 따라 분석될 수 있고 GME는 위치·시간·
품질·재현 provenance를 공급한다.

## 4. 처리 계약

1. 원본 프레임은 끝까지 순차 디코딩한다.
2. 원본이 30fps 이하면 모든 프레임을 분석한다.
3. 원본이 30fps를 넘으면 모든 프레임을 디코딩하되 GME 분석은 최대 30fps로 정규화한다.
4. Gecko Vision Gate의 model/checkpoint/threshold/sampler를 모든 결과에 기록한다.
5. bbox 또는 mask를 프레임 간 연결해 같은 게코의 trajectory를 만든다.
6. 여러 마리는 내부 track id로 분리하되 identity가 끊기면 억지로 같은 개체로 합치지 않는다.
7. 부분 노출·가림·검출 신뢰도 부족은 `unknown`으로 보존한다.
8. global motion, timestamp 영역, 노출 변화, IR 모드 전환, codec 반복을 게코 자체 움직임과 분리한다.
9. 카메라 거리·해상도 차이는 bbox/mask에서 추정한 몸길이 단위로 정규화한다.
10. 상태 구간을 합쳐 사용자용 any-gecko 활동시간과 내부 gecko-seconds를 각각 만든다.

## 5. Gecko Vision Gate 운영 원칙

과거 Gate v2 recall reject는 Gate 연구 중단 사유가 아니라 현재 모델을 자동 제외에 쓰지 못한다는
증거다. Gate v3와 이후 모델을 계속 학습·교체하되 다음 계약을 지킨다.

- checkpoint마다 별도 version과 future holdout 성적을 가진다.
- 검출 실패를 `not_visible`이나 `static`으로 바꾸지 않고 `unknown`으로 둔다.
- 사람 bbox/mask 교정을 hard-case 학습자료로 append-only 보존한다.
- 새 camera, morph, enclosure, IR, occlusion, multi-gecko strata를 각각 평가한다.
- production 채택 전에는 shadow 계산만 하고 사용자 활동시간과 기존 값을 바꾸지 않는다.
- Gate 결과만으로 VLM skip, 원본 삭제, 행동 GT 확정을 하지 않는다.

별도 prescan 연구가 미래에 `verified_absent` 조건부 VLM 생략을 다시 제안하더라도, 독립 TEST-SHEET와
owner adoption gate를 통과하기 전에는 적용하지 않는다. 그런 외부 routing 결정은 GME의 측정 계약을
바꾸지 않는다.

## 6. 단계별 연구

### 1단계 — 정의·원장

현재 SOT와 명칭을 GME로 전환한다. 신규 출력 계약과 사람 활동시간 GT 기준을 동결하되 DB·runtime·
사용자 화면은 변경하지 않는다.

### 2단계 — offline GME baseline

사람이 게코의 `moving/static/not_visible/unknown/camera_motion` 구간과 bbox/mask를 표시할 수 있는
표본을 만든다. Gate+tracker+noise normalizer를 offline으로 실행하고 camera/morph/IR/occlusion/
multi-gecko별 검출·추적·활동시간 오차를 측정한다.

### 3단계 — production shadow

모든 새 영상에서 GME를 계산하되 사용자 값, GT, VLM route, DB 원본을 바꾸지 않는다. 기존
`activity-v1`과 GME, 사람 정답을 같은 camera-night에서 비교한다.

### 4단계 — 사용자 지표 채택 평가

독립 future holdout TEST-SHEET에서 허용 오차와 unknown 처리 기준을 먼저 동결한다. 통과한 뒤에만
`verified gecko moving time`을 사용자 대표 활동시간으로 교체한다. 통과하지 못하면 shadow와
hard-case 학습을 계속한다.

## 7. 이번 SOT 변경의 범위

이번 변경은 이름·목표·경계·연구 순서만 확정한다. 다음은 포함하지 않는다.

- DB migration 또는 새 테이블 생성
- production worker·launchd·Flutter 값 변경
- Gate checkpoint 설치·교체·학습
- 과거 `Python Evidence` artifact의 소급 개명
- 자동 skip·행동 라벨·하이라이트·원본 삭제

## 8. 성공 기준

- 현재 정본 문서가 GME 이름과 `게코가 실제로 움직인 시간` 정의에 일치한다.
- 과거 `Python Evidence`는 historical provenance로만 설명된다.
- `media preparation only`라는 축소 정의가 현재 지시로 남지 않는다.
- Gate는 계속 업그레이드하는 핵심 센서이되 자동 skip 근거가 아님을 명시한다.
- MacBook과 Mac mini가 같은 commit의 SOT를 읽는다.
