# YOLO 영상 분석 학습 및 petcam-lab 적용 계획

> YOLO 기초를 공부하고, 영상에서 객체 검출/추적을 실습한 뒤, petcam-lab 의 RBA 파이프라인에 "증거 추출 레이어"로 연결하기 위한 학습 로드맵.

**작성:** 2026-06-06 (Asia/Seoul)
**대상:** YOLO 입문자지만 Python/FastAPI 프로젝트 안에서 실제로 활용하고 싶은 사람
**연관 문서:** [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../AI-VIDEO-ANALYSIS-STRATEGY.md), [`specs/experiment-tracking-vlm-input.md`](../../specs/experiment-tracking-vlm-input.md), [`specs/feature-rba-evidence-based-feeding-drinking.md`](../../specs/feature-rba-evidence-based-feeding-drinking.md)

## TL;DR

YOLO는 영상 행동을 직접 이해하는 모델이라기보다, 프레임 안의 객체 위치를 찾는 detector(객체 탐지기)다.

petcam-lab 에서는 YOLO를 이렇게 쓰는 게 현실적이다.

```text
mp4 clip
-> frame sampling
-> YOLO detect: gecko / food_dish / water_bowl / hide 위치
-> tracker: 같은 객체를 시간축으로 연결
-> evidence extractor: ROI 거리, 체류시간, 이동량, 반복 움직임 계산
-> RBA / VLM / LLM: 행동 후보와 설명 생성
```

즉 목표는 "YOLO로 eating/drinking을 맞힌다"가 아니라, "YOLO로 행동 판단에 필요한 좌표와 시간 증거를 만든다"다.

## 0. 먼저 단어부터

이 문서는 영상 AI 쪽 실무 단어가 많이 나온다. 처음 읽을 때는 아래 표만 옆에 놓고 보면 된다.

| 단어                   | 쉬운 뜻                                                        | petcam-lab 예시                                     |
| ---------------------- | -------------------------------------------------------------- | --------------------------------------------------- |
| `frame`                | 영상을 이루는 사진 한 장                                       | 1분 mp4 는 수백~수천 장의 frame 으로 이루어져 있다  |
| `clip`                 | 짧게 잘라둔 영상 파일                                          | 지금 레포의 1분 mp4 하나                            |
| `object`               | 찾고 싶은 물체                                                 | 게코, 물그릇, 밥그릇, 은신처                        |
| `detector`             | 사진 안에서 물체 위치를 찾는 모델                              | "이 frame 에 게코가 여기 있다"라고 말하는 YOLO      |
| `detection`            | detector 가 물체를 찾은 결과                                   | 게코 bbox 1개, 물그릇 bbox 1개                      |
| `bbox`                 | 물체를 감싸는 사각형 박스                                      | 게코 몸 전체를 네모로 감싼 좌표                     |
| `class`                | 물체 종류 이름                                                 | `gecko`, `water_bowl`, `food_dish`                  |
| `confidence`           | 모델이 얼마나 확신하는지 나타내는 점수                         | `gecko 0.82` 면 게코일 확률이 높다고 본 것          |
| `crop`                 | 이미지/영상에서 필요한 부분만 잘라낸 것                        | 전체 케이지 영상에서 게코 주변만 잘라낸 작은 영상   |
| `tracker`              | frame 사이에서 같은 물체를 이어주는 기술                       | 1초 전 게코와 지금 게코가 같은 개체인지 연결        |
| `track_id`             | tracker 가 붙인 객체 번호                                      | `track_id=1` 이면 같은 게코의 이동 경로             |
| `trajectory`           | 시간에 따른 이동 경로                                          | 게코 bbox 중심점이 10초 동안 어디로 움직였는지      |
| `tracking drift`       | tracker 가 물체를 놓치고 엉뚱한 걸 따라가는 현상               | 게코를 따라가야 하는데 나무껍질을 게코처럼 따라감   |
| `ROI`                  | 관심 영역. Region Of Interest                                  | 물그릇 주변, 밥그릇 주변, 은신처 입구               |
| `evidence`             | 최종 판단 전의 근거 데이터                                     | "물그릇 근처에 13초 있었다" 같은 증거               |
| `feature`              | 모델/룰이 쓰기 좋게 만든 숫자 정보                             | 이동거리, 체류시간, 평균 속도                       |
| `pretrained`           | 남이 큰 데이터로 미리 학습시켜둔 상태                          | 일반 사진으로 학습된 YOLO 모델                      |
| `fine-tune`            | 미리 학습된 모델을 내 데이터로 추가 학습                       | 게코 영상 frame 을 라벨링해서 YOLO를 다시 학습      |
| `custom dataset`       | 내가 직접 모은 학습 데이터                                     | 게코/물그릇 bbox 를 직접 표시한 frame 모음          |
| `labeling`             | 학습용 정답을 사람이 표시하는 작업                             | frame 에서 게코를 네모로 감싸고 `gecko` 라벨 붙이기 |
| `quality gate`         | 다음 단계로 가도 되는지 보는 최소 통과 기준                    | 게코를 80% 이상 잡으면 다음 단계 진행               |
| `detector 품질 게이트` | detector 성능이 최소 기준을 넘는지 보는 검사                   | YOLO가 게코를 충분히 잘 잡는지 먼저 확인            |
| `smoke test`           | 아주 작게 돌려보는 첫 확인                                     | frame 10장으로 코드가 도는지만 확인                 |
| `PoC`                  | Proof of Concept. 될지 안 될지 보는 작은 실험                  | production 말고 실험 폴더에서만 YOLO를 시험         |
| `false positive`       | 없는데 있다고 잘못 잡음                                        | 나무껍질을 게코라고 잡음                            |
| `false negative`       | 있는데 없다고 놓침                                             | 게코가 있는데 못 잡음                               |
| `precision`            | "잡았다"고 한 것 중 진짜 맞은 비율                             | 게코라고 잡은 박스 10개 중 8개가 진짜면 80%         |
| `recall`               | 실제 존재한 것 중 모델이 잡은 비율                             | 게코가 나온 frame 10장 중 8장에서 잡으면 80%        |
| `IoU`                  | 박스 두 개가 얼마나 겹치는지 보는 점수                         | 사람이 그린 박스와 YOLO 박스가 잘 겹치는지          |
| `NMS`                  | 겹치는 박스 여러 개 중 대표 하나만 남기는 처리                 | 같은 게코에 박스 3개가 뜨면 1개만 남김              |
| `mAP`                  | detector 성능을 요약하는 대표 점수                             | 모델끼리 비교할 때 쓰는 종합 점수                   |
| `FPS`                  | 1초에 몇 frame 을 처리하는지                                   | FPS 가 높을수록 분석이 빠름                         |
| `VLM`                  | Vision-Language Model. 이미지/영상을 보고 텍스트로 답하는 모델 | Gemini 가 60초 clip 을 보고 행동 라벨을 답함        |
| `LLM`                  | Large Language Model. 텍스트를 읽고 판단/요약하는 모델         | evidence JSON 을 읽고 행동 후보를 정리              |

### 세 단어만 먼저 잡으면 된다

1. `crop` 은 "잘라낸 화면"이다.
   - 전체 케이지 영상을 다 보지 않고, 게코 주변만 잘라서 보는 것.
   - 장점: 게코가 크게 보인다.
   - 단점: 물그릇/밥그릇 같은 주변 맥락이 잘릴 수 있다.
2. `tracking drift` 는 "따라가던 대상이 틀어지는 것"이다.
   - tracker 가 처음엔 게코를 잘 따라가다가, 중간에 나뭇가지나 그림자를 게코처럼 따라가는 현상.
   - drift 가 많으면 이동 경로, 체류시간 같은 숫자도 전부 오염된다.
3. `detector 품질 게이트` 는 "이 detector 를 계속 써도 되는지 보는 시험"이다.
   - 예: petcam clip 20개에서 게코를 80% 이상 잡아야 다음 단계로 간다.
   - 기준을 못 넘으면 production 고민 전에 라벨링/모델/전략을 다시 본다.

## 1. 최종 목표

### 학습 목표

- YOLO가 object detection 문제를 어떻게 푸는지 이해한다.
- bbox, confidence, IoU, NMS, mAP, FPS 같은 기본 용어를 읽을 수 있다.
- Ultralytics YOLO 계열의 `predict`, `track`, `train`, `val`, `export` 흐름을 익힌다.
- 영상에서 detection 결과를 track 으로 이어 trajectory 를 만들 수 있다.
- custom dataset 을 만들고 작은 detector 를 fine-tune 하는 전체 흐름을 경험한다.

### petcam-lab 적용 목표

- 게코 영상에서 최소 객체 4종을 구조화한다.
  - `gecko`
  - `food_dish`
  - `water_bowl`
  - `hide`
- 객체 좌표를 기반으로 RBA evidence 를 만든다.
  - 게코가 물그릇 근처에 머문 시간
  - 게코가 밥그릇 근처에 머문 시간
  - 은신처 밖 활동 시간
  - 이동량, 정지 구간, 반복 움직임 후보
- 이 evidence 를 Track B / SegmentVLM 또는 LLM analyzer 에 넘겨 행동 후보를 판단한다.

## 2. 중요한 전제

### YOLO는 판단기가 아니라 구조화 도구다

YOLO가 잘하는 것:

- 프레임 안에 어떤 객체가 있는지 찾기
- 객체의 위치를 bbox 또는 mask 로 표현하기
- 빠르게 여러 프레임을 처리하기

YOLO가 약한 것:

- "물 마심" 같은 행동 의미를 직접 단정하기
- 아주 작은 혀 움직임이나 미세한 머리 움직임을 안정적으로 구분하기
- IR 야간, 위장색, 은신처, 낮은 해상도처럼 시각 정보가 약한 환경에서 항상 안정적으로 검출하기

그래서 YOLO의 역할은 아래처럼 제한한다.

```text
YOLO = 영상의 좌표계 생성
Tracker = 좌표의 시간 연결
Feature extractor = 숫자 증거 생성
RBA/VLM/LLM = 의미 판단
```

### 기존 tracking PoC 의 교훈을 반영한다

[`specs/experiment-tracking-vlm-input.md`](../../specs/experiment-tracking-vlm-input.md) 에서 이미 tracking 기반 입력 정규화 PoC 를 했고, 결론은 폐기였다.

핵심 실패 원인:

- detector(객체 탐지기)가 게코를 못 잡는 케이스가 많았다.
- tracking drift(따라가던 대상이 엉뚱한 곳으로 틀어지는 현상)가 있었다.
- crop(게코 주변만 잘라낸 화면)을 VLM 에 넣는 것만으로는 행동 분류 정확도 개선을 보장하지 못했다.

이번 계획은 그 실패를 반복하지 않는다.

- 첫 목표는 VLM 입력 crop 이 아니라 `evidence` 생성이다.
- detector 품질 게이트, 즉 "YOLO가 최소한 쓸 만한지 보는 통과 기준"을 먼저 둔다.
- production 통합 전에 작은 sample set 으로 검출 가능성부터 본다.
- 실패해도 "YOLO가 안 된다"가 아니라 "어떤 객체/환경에서 안 되는지"를 남긴다.

## 3. 전체 로드맵

권장 기간은 4주다. 하루 1~2시간 기준이고, 더 몰아서 하면 1~2주 안에도 끝낼 수 있다.

| 단계    |  기간 | 목적                                             | 산출물                                 |
| ------- | ----: | ------------------------------------------------ | -------------------------------------- |
| Phase 0 | 0.5일 | 환경과 문서 맥락 잡기                            | 실습 폴더 계획, 의존성 후보 정리       |
| Phase 1 | 2~3일 | object detection, 즉 사진 안 물체 찾기 기초 이해 | 용어 노트, bbox/IoU 손계산             |
| Phase 2 | 2~3일 | pretrained, 즉 미리 학습된 YOLO 사용법 익히기    | sample video predict/track 결과        |
| Phase 3 | 3~5일 | petcam 영상으로 한계 확인                        | 실패 케이스 모음, 검출 가능성 메모     |
| Phase 4 | 5~7일 | 작은 custom dataset 만들기                       | 라벨링 100~300 frame, dataset yaml     |
| Phase 5 | 3~5일 | fine-tune, 즉 우리 데이터로 추가 학습 및 평가    | best model, confusion/precision/recall |
| Phase 6 | 3~5일 | evidence layer PoC                               | trajectory JSON, ROI event JSON        |
| Phase 7 | 2~4일 | RBA 연결 설계                                    | 다음 구현 스펙 초안                    |

## 4. Phase 0: 준비

### 할 일

1. 현재 레포 맥락을 읽는다.
   - [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../AI-VIDEO-ANALYSIS-STRATEGY.md)
   - [`specs/experiment-tracking-vlm-input.md`](../../specs/experiment-tracking-vlm-input.md)
   - [`specs/feature-rba-evidence-based-feeding-drinking.md`](../../specs/feature-rba-evidence-based-feeding-drinking.md)
2. 실험 산출물 위치를 정한다.
   - 코드 후보: `scripts/yolo_*`
   - 결과 후보: `experiments/yolo-evidence-poc/`
   - 문서 후보: `specs/experiment-yolo-evidence-layer.md`
3. 의존성 추가는 실제 실습 시작 시점에 한다.
   - 이 레포는 `uv` 전용이다.
   - `pip install` 은 쓰지 않는다.
   - 예: `uv add ultralytics`

### 주의

Ultralytics YOLO 계열은 버전과 모델명이 빠르게 바뀐다. 실습 시작 시점에 공식 문서를 다시 확인하고, 문서 예제의 현재 recommended small detect model 을 쓴다.

상용 제품에 넣을 가능성이 생기면 라이선스를 별도 체크한다. Ultralytics 는 공식 문서에서 AGPL-3.0 과 Enterprise 라이선스 경로를 안내한다.

## 5. Phase 1: object detection 기초

여기서 object detection 은 "사진 안에서 물체가 어디 있는지 찾는 문제"라고 보면 된다. 예를 들어 한 frame 을 넣었을 때 "게코는 왼쪽 아래, 물그릇은 오른쪽 위"라고 박스 좌표로 알려주는 것이다.

### 꼭 이해할 개념

| 개념       | 한 줄 설명                          | petcam-lab 에서 왜 중요한가          |
| ---------- | ----------------------------------- | ------------------------------------ |
| frame      | 영상의 한 장면 이미지               | YOLO는 영상을 결국 frame 단위로 본다 |
| bbox       | 객체를 감싸는 사각형                | 게코/그릇/은신처 위치의 기본 표현    |
| class      | 객체 종류                           | `gecko`, `water_bowl` 같은 라벨      |
| confidence | 모델 확신도                         | 낮으면 evidence 신뢰도를 낮춰야 한다 |
| IoU        | 두 bbox 의 겹침 비율                | tracker/eval 품질 판단에 필요        |
| NMS        | 겹치는 박스 중 하나만 남기는 후처리 | 같은 게코가 여러 번 잡히는 문제 방지 |
| precision  | 잡았다고 한 것 중 맞은 비율         | false highlight 줄이기               |
| recall     | 실제 객체 중 잡은 비율              | 중요한 행동 놓침 줄이기              |
| mAP        | detection 종합 성능 지표            | 모델 비교 때 참고                    |
| FPS        | 초당 처리 frame 수                  | capture/worker 비용 판단에 필요      |

처음엔 `mAP`, `NMS` 같은 단어를 완벽히 이해하지 않아도 된다. 실습 시작 단계에서는 `frame`, `bbox`, `class`, `confidence`, `precision`, `recall` 만 먼저 잡으면 충분하다.

### 공부 순서

1. YOLO 원 논문의 아이디어를 가볍게 읽는다.
   - 핵심만 보면 된다: "이미지 전체를 한 번에 보고 bbox/class 를 예측해서 빠르게 detection 한다."
2. bbox 좌표 형식을 익힌다.
   - `xyxy`: `[x1, y1, x2, y2]`
   - `xywh`: `[center_x, center_y, width, height]`
   - YOLO label format: `[class_id, x_center, y_center, width, height]`, 보통 0~1 정규화
3. IoU 를 직접 계산해본다.
4. precision/recall 차이를 예시로 이해한다.

### 작은 연습

아래 질문에 답할 수 있으면 Phase 1 은 충분하다.

- bbox 두 개가 거의 겹치면 IoU 는 높을까 낮을까?
- confidence 가 높은데 bbox 가 틀리면 좋은 detection 일까?
- `water_bowl` recall 이 낮으면 RBA 에 어떤 문제가 생길까?
- `food_dish` precision 이 낮으면 eating 후보가 어떻게 오염될까?

## 6. Phase 2: pretrained YOLO 사용법

### 목표

아직 petcam 데이터를 학습하지 않는다. 먼저 이미 학습된 모델, 즉 pretrained 모델로 API 사용법을 익힌다. 이 단계는 "게코를 잘 잡나?"보다 "YOLO를 어떻게 실행하고 결과를 어떻게 읽나?"를 배우는 단계다.

### 할 일

1. 샘플 이미지 1장에 predict 를 돌린다. predict 는 "물체를 찾아봐"라는 명령이다.
2. 샘플 mp4 1개에 predict 를 돌린다.
3. 같은 mp4 에 track 을 돌린다. track 은 "frame 마다 찾은 물체를 같은 객체로 이어봐"라는 명령이다.
4. 결과 객체에서 bbox, class, confidence, track_id 를 읽어 JSON 으로 저장한다.
5. 결과를 annotated video 또는 frame image 로 눈으로 확인한다.

### 확인할 것

- 결과 객체 구조가 어떻게 생겼는지
- bbox 좌표가 원본 frame 크기 기준인지
- class id 와 class name 을 어떻게 매핑하는지
- track mode 에서 `track_id` 가 언제 생기고 언제 끊기는지
- CPU 에서 처리 속도가 어느 정도인지

`annotated` 는 원본 이미지 위에 박스와 라벨을 그려둔 결과라는 뜻이다. 초보 단계에서는 숫자 파일보다 annotated frame 을 눈으로 보는 게 훨씬 중요하다.

### 예상 산출물

```text
experiments/yolo-evidence-poc/
  pretrained-smoke/
    sample-predict.jsonl
    sample-track.jsonl
    annotated-frames/
```

### 공식 문서

- Ultralytics Python usage: https://docs.ultralytics.com/usage/python/
- Object detection task: https://docs.ultralytics.com/tasks/detect/
- Tracking mode: https://docs.ultralytics.com/modes/track/

## 7. Phase 3: petcam 영상에서 pretrained 한계 확인

### 목표

pretrained COCO 모델이 게코를 잘 잡을 거라고 기대하지 않는다. 오히려 "얼마나 못 잡는지"를 확인하는 단계다.

### sample 선정

20~40개 clip 을 고른다.

분포는 이렇게 나눈다.

| 축   | 포함할 케이스                    |
| ---- | -------------------------------- |
| 조명 | IR 야간, 밝은 장면               |
| 거리 | 게코가 크게 보임, 작게 보임      |
| 위치 | 바닥, 벽, 은신처 근처, 그릇 근처 |
| 상태 | 이동, 정지, 일부 가림, 완전 가림 |
| 배경 | 단순 배경, 복잡한 나무/잎/은신처 |

### 기록할 실패 유형

| 실패 유형      | 의미                                                                   |
| -------------- | ---------------------------------------------------------------------- |
| no_detection   | 게코를 아예 못 잡음                                                    |
| wrong_class    | 다른 class 로 잡음. 예: 게코를 `cat` 이나 이상한 물체로 분류           |
| false_positive | 배경/장식을 게코로 잡음                                                |
| poor_bbox      | 잡긴 했지만 박스가 너무 크거나 작음                                    |
| unstable       | 프레임마다 검출이 끊김                                                 |
| drift          | tracker 가 다른 물체를 따라감. 예: 게코를 따라가다가 나뭇가지를 따라감 |

### 결론 기준

이 단계의 결론은 둘 중 하나다.

```text
A. pretrained 로는 부족하다 -> custom dataset 필요
B. 특정 객체/환경은 pretrained 도 보조 신호로 쓸 수 있다 -> 해당 범위만 활용
```

게코 자체는 A 로 떨어질 가능성이 높다. 그릇류나 은신처 같은 큰 객체는 pretrained 또는 zero-shot detector 로 힌트를 얻을 수 있을지 따로 본다.

## 8. Phase 4: 작은 custom dataset 만들기

### 목표

처음부터 큰 모델을 만들지 않는다. "이 데이터에서 YOLO가 게코와 ROI 객체를 잡을 수 있는가"를 보는 최소 dataset 을 만든다. dataset 은 학습에 쓰는 이미지와 정답 라벨 모음이다.

### 클래스 설계

첫 버전은 4개만 쓴다.

| class        | 설명                         | 이유                       |
| ------------ | ---------------------------- | -------------------------- |
| `gecko`      | 도마뱀 몸 전체               | 모든 행동 evidence 의 중심 |
| `food_dish`  | 슈퍼푸드/먹이 그릇           | eating_paste 후보 판단     |
| `water_bowl` | 물그릇                       | drinking 후보 판단         |
| `hide`       | 은신처 입구 또는 은신처 영역 | hiding/resting/활동량 판단 |

처음부터 `head`, `tail`, `tongue` 는 넣지 않는다. 작은 부위는 라벨링 난이도와 검출 난이도가 높아서, bbox detector 첫 단계에는 과하다.

### 라벨링 규모

첫 gate 는 작게 간다. 여기서 gate 는 다음 단계로 넘어가기 전의 작은 시험이다.

| 단계   | frame 수 | 목적                                                       |
| ------ | -------: | ---------------------------------------------------------- |
| smoke  |    50~80 | 아주 작게 돌려보는 첫 확인. 코드와 라벨 형식이 맞는지 본다 |
| gate   |  150~300 | 실제 검출 가능성 판단. 계속 투자할 가치가 있는지 본다      |
| expand | 500~1000 | PoC 통과 후 성능 안정화                                    |

### split

clip 단위로 나눈다. 같은 clip 에서 뽑은 비슷한 frame 이 train 과 val 에 동시에 들어가면 성능이 부풀 수 있다.

```text
train: 70%
val: 20%
test: 10%
```

### 라벨링 원칙

- bbox 는 객체가 보이는 부분을 타이트하게 감싼다.
- 일부 가림은 보이는 부분 기준으로 감싼다.
- 완전히 안 보이면 라벨하지 않는다.
- `hide` 는 객체라기보다 영역에 가까우므로, 첫 실험에서는 "은신처 입구/몸이 들어갈 수 있는 구조물"로 정의한다.
- 애매한 frame 은 `notes` 에 기록하고, 무리하게 학습셋에 넣지 않는다.

### dataset 구조 예시

```text
experiments/yolo-evidence-poc/dataset-v0/
  images/
    train/
    val/
    test/
  labels/
    train/
    val/
    test/
  data.yaml
```

`data.yaml` 예시:

```yaml
path: experiments/yolo-evidence-poc/dataset-v0
train: images/train
val: images/val
test: images/test
names:
  0: gecko
  1: food_dish
  2: water_bowl
  3: hide
```

## 9. Phase 5: fine-tune 및 평가

### 목표

작은 모델로 빠르게 학습하고, production 이 아니라 PoC 품질을 판단한다. fine-tune 은 "이미 배운 모델을 우리 게코 영상에 맞게 추가로 가르치는 것"이다.

### 학습 전략

- 처음엔 small/nano 계열 모델을 쓴다.
- epoch 를 과하게 늘리지 않는다.
- augmentation 은 기본값부터 시작한다.
- validation 결과보다 실제 petcam clip overlay 를 더 중요하게 본다.

### 평가 지표

| 지표                        |   gate 기준 초안 | 이유                                                     |
| --------------------------- | ---------------: | -------------------------------------------------------- |
| `gecko` recall              |        0.80 이상 | 놓치면 모든 evidence 가 비어버린다                       |
| `gecko` precision           |        0.80 이상 | 배경을 게코로 잡으면 event 가 오염된다                   |
| ROI class precision         |        0.85 이상 | 그릇 false positive 는 eating/drinking 오탐으로 이어진다 |
| ROI class recall            |        0.70 이상 | ROI 는 고정 등록 fallback 으로 보완 가능하다             |
| catastrophic false positive | clip 당 1회 이하 | 사용자 하이라이트 오염 방지                              |

숫자는 초안이다. 실제 데이터 분포를 보고 조정한다.

`recall` 은 "놓치지 않는 능력"에 가깝고, `precision` 은 "헛소리하지 않는 능력"에 가깝다. petcam-lab 에서는 둘 다 중요하지만, 게코 자체는 recall 이 특히 중요하다. 게코를 놓치면 그 뒤의 체류시간/이동량 계산이 전부 비어버리기 때문이다.

### 실패했을 때 판단

| 실패                          | 다음 선택                                                   |
| ----------------------------- | ----------------------------------------------------------- |
| 게코 recall 이 낮다           | 라벨 수 확장, IR/은신처 케이스 추가                         |
| 게코 precision 이 낮다        | negative frame 추가, 배경 hard negative 라벨링              |
| 그릇 class 가 흔들린다        | ROI 를 모델 검출 대신 사용자/관리자 고정 좌표로 관리        |
| 정지 게코를 못 잡는다         | motion clip 만 대상으로 제한하거나, VLM/HITL fallback       |
| 작은 혀/머리 행동이 안 잡힌다 | YOLO bbox 로 해결하지 않고 VLM crop 또는 keypoint 별도 검토 |

## 10. Phase 6: tracker 와 evidence layer

### Tracker 역할

YOLO는 frame 단위로 객체를 찾는다. Tracker 는 같은 객체를 시간축으로 이어 trajectory, 즉 이동 경로를 만든다.

```text
frame 001: gecko bbox
frame 002: gecko bbox
frame 003: gecko bbox
-> track_id=1 trajectory
```

실무에서는 YOLO track mode 의 ByteTrack/BoT-SORT 계열을 먼저 써보고, petcam 환경에서 drift 를 확인한다. drift 는 tracker 가 게코를 놓치고 다른 배경 물체를 따라가는 문제다.

### evidence extractor 가 만들 데이터

evidence extractor 는 "영상에서 행동 판단에 쓸 근거를 뽑아내는 코드"다. 예를 들어 "게코가 물그릇 근처에 13.2초 있었다"를 숫자로 만든다.

최소 JSON 스키마 초안:

```json
{
  "clip_id": "uuid",
  "segment_start_sec": 12.0,
  "segment_end_sec": 28.0,
  "tracks": [
    {
      "track_id": 1,
      "class": "gecko",
      "visible_seconds": 15.5,
      "mean_confidence": 0.84,
      "bbox_area_ratio_mean": 0.08,
      "path_length_px": 420.0,
      "mean_speed_px_per_sec": 27.1
    }
  ],
  "roi_events": [
    {
      "roi": "water_bowl",
      "near_seconds": 13.2,
      "min_distance_px": 18.0,
      "approach_count": 1,
      "dwell_burst_count": 1
    }
  ],
  "quality": {
    "detector_ok": true,
    "tracker_ok": true,
    "needs_human_review": false,
    "notes": []
  }
}
```

### 1차 feature

| feature                    | 계산                           | 행동 판단에 주는 힌트    |
| -------------------------- | ------------------------------ | ------------------------ |
| `visible_seconds`          | track 이 유지된 시간           | 분석 신뢰도              |
| `path_length_px`           | bbox center 이동거리 합        | 활동량                   |
| `mean_speed_px_per_sec`    | 이동거리 / 시간                | moving/resting 구분      |
| `near_water_seconds`       | gecko bbox 와 water ROI 거리   | drinking 후보            |
| `near_food_seconds`        | gecko bbox 와 food ROI 거리    | eating_paste 후보        |
| `hide_overlap_seconds`     | gecko bbox 와 hide ROI overlap | hiding/resting           |
| `small_motion_burst_count` | 낮은 이동량 + bbox 내부 변화   | licking/head motion 후보 |

### event 생성 규칙 초안

처음에는 ML classifier 를 추가하지 않고 rule 로 event 후보를 만든다.

```text
IF gecko near water_bowl >= 8초
AND movement_level in {low, small_repeated}
THEN event = drinking_candidate
```

```text
IF gecko near food_dish >= 8초
AND movement_level in {low, small_repeated}
THEN event = eating_paste_candidate
```

```text
IF gecko outside hide >= 30초
AND path_length high
THEN event = active_exploration
```

이 규칙은 최종 판정이 아니다. RBA/VLM/LLM 에 넘길 후보 생성기다.

## 11. Phase 7: RBA / VLM / LLM 연결

### 연결 방식

YOLO evidence 는 Track A 를 대체하지 않는다. Track B 또는 evidence-based layer 의 입력으로 붙인다.

```text
Track A:
60초 motion clip -> Gemini 2.5 Flash v3.5 -> top-1 action

YOLO evidence sidecar:
60초 motion clip -> YOLO/Tracker -> ROI event JSON

Track B / analyzer:
clip + event segment + ROI evidence -> 행동 후보 timeline
```

### analyzer prompt 방향

LLM 에게 원본 영상을 직접 보라고 하지 않는다. 구조화된 evidence 를 먼저 준다.

```text
아래 evidence 를 바탕으로 drinking / eating_paste / exploring / resting / unknown 중 후보를 골라.
증거가 부족하면 unknown 으로 둬.
confidence 는 detector/tracker 품질을 반영해 낮춰.
사용자에게 보여줄 설명은 한 문장으로 써.
```

### 좋은 출력 예시

```json
{
  "event_type": "drinking_candidate",
  "action": "drinking",
  "confidence": 0.68,
  "time_range": [12.0, 28.0],
  "evidence_summary": "물그릇 ROI 근처에서 13.2초 체류했고 이동량은 낮았지만, 혀 움직임은 직접 확인되지 않았다.",
  "needs_human_review": true
}
```

## 12. 구현 착수 시 파일 계획

아직 이 문서는 학습 계획이다. 실제 구현을 시작하면 먼저 스펙을 만든다.

### 새 스펙 후보

```text
specs/experiment-yolo-evidence-layer.md
```

스펙에 넣을 In/Out 초안:

### In

- 20~40개 clip sample 선정
- frame extraction script
- pretrained YOLO smoke test
- custom dataset v0 라벨링 계획
- YOLO fine-tune smoke
- tracker 결과 JSON 저장
- ROI event JSON 생성
- RBA evidence 후보 리포트 작성

### Out

- production worker 통합
- Supabase schema 변경
- Flutter UI 변경
- 실시간 capture worker 에 YOLO 삽입
- eating/drinking 최종 자동 판정
- 모바일 온디바이스 추론

### 예상 파일

```text
scripts/yolo_extract_frames.py
scripts/yolo_predict_clip.py
scripts/yolo_track_clip.py
scripts/yolo_build_evidence.py
experiments/yolo-evidence-poc/
  README.md
  clips-sample.txt
  dataset-v0/
  runs/
  evidence-jsonl/
```

## 13. 검증 게이트

검증 게이트는 "다음 단계로 넘어가기 전에 통과해야 하는 작은 시험"이다. 여기서는 완벽한 제품 품질을 보려는 게 아니라, 더 투자할 가치가 있는지 확인한다.

### Gate 1: API 사용법

- sample image predict 성공
- sample video predict 성공
- sample video track 성공
- bbox/conf/class/track_id JSON 저장 성공

### Gate 2: pretrained 현실 확인

- petcam clip 20개 이상에서 검출 결과 정성 검수
- 실패 유형별 count 기록
- custom dataset 필요 여부 결정

정성 검수는 사람이 눈으로 보고 "이 박스가 말이 되나?" 확인하는 것이다. 처음엔 숫자 점수보다 이 단계가 더 중요하다.

### Gate 3: custom detector

- validation metric 기록
- 실제 clip overlay 10개 이상 시각 검수
- `gecko` recall/precision gate 통과 여부 판단

여기서 detector 는 "게코/그릇/은신처를 찾아주는 YOLO 모델"이다. gate 통과는 대략 "이 모델 결과를 다음 evidence 계산에 넣어도 크게 망가지지 않겠다"는 뜻이다.

### Gate 4: tracker

- track 끊김 count
- drift 케이스 count
- trajectory JSON 생성
- ROI 거리 계산 가능

track 이 끊긴다는 건 같은 게코를 계속 이어보지 못하고 중간에 ID 가 사라지거나 새 ID 로 바뀌는 상황이다. drift 는 ID 는 유지되지만 엉뚱한 물체를 따라가는 상황이다.

### Gate 5: evidence usefulness

- drinking/eating/resting/exploring 후보 event 가 사람이 보기에도 말 되는지 검수
- false candidate 비율 기록
- "이 evidence 가 VLM/LLM 판단을 더 쉽게 만드는가" 정성 평가

false candidate 는 "후보라고 잡았지만 사람이 보니 아닌 것"이다. 예를 들어 물그릇 근처에 있었지만 실제로는 지나가기만 했는데 drinking 후보로 잡히는 경우다.

## 14. 공부 중 자주 헷갈릴 포인트

### Detection 과 classification 은 다르다

classification 은 이미지 전체가 무엇인지 고른다.

```text
image -> gecko
```

detection 은 이미지 안의 어디에 무엇이 있는지 찾는다.

```text
image -> [gecko bbox], [water_bowl bbox]
```

### Detection 과 tracking 도 다르다

detection 은 frame 하나만 본다.

tracking 은 시간축의 history 를 가진다.

```text
detection: f(frame) -> bbox
tracking: update(previous_state, frame, detections) -> track
```

### bbox 가 있다고 행동을 아는 건 아니다

`gecko near water_bowl` 은 drinking 의 증거지만 drinking 자체는 아니다.

그래서 저장 이름도 처음부터 `drinking` 으로 하지 말고 `drinking_candidate`, `water_bowl_visit` 같은 중간 표현을 쓴다.

### ROI 는 꼭 YOLO가 찾아야 하는 건 아니다

물그릇/밥그릇/은신처 위치가 카메라별로 거의 고정이라면, 사용자나 관리자 설정값으로 저장하는 쪽이 더 안정적일 수 있다.

YOLO는 ROI 자동 제안이나 초기 세팅 보조로 쓰고, production 에서는 고정 ROI 를 쓰는 하이브리드가 더 나을 수 있다.

## 15. 추천 학습 순서 체크리스트

- [ ] `0. 먼저 단어부터` 섹션 읽기
- [ ] YOLO 원리 1시간 훑기
- [ ] bbox / IoU / precision / recall 개념 정리
- [ ] Ultralytics Python usage 예제 실행
- [ ] 이미지 predict 결과 구조 확인
- [ ] mp4 predict 결과 저장
- [ ] mp4 track 결과 저장
- [ ] petcam clip 20개 pretrained smoke
- [ ] 실패 유형 표 작성
- [ ] custom class 4개 정의 확정
- [ ] frame 50~80장 smoke 라벨링
- [ ] dataset yaml 생성
- [ ] YOLO fine-tune smoke
- [ ] overlay 시각 검수
- [ ] frame 150~300장 gate 라벨링
- [ ] detector gate 평가
- [ ] tracker gate 평가
- [ ] ROI evidence JSON 생성
- [ ] RBA analyzer 입력 예시 작성
- [ ] 실제 구현 전 `specs/experiment-yolo-evidence-layer.md` 작성

## 16. 참고 링크

- YOLOv1 paper: https://arxiv.org/abs/1506.02640
- Ultralytics docs home: https://docs.ultralytics.com/
- Ultralytics Python usage: https://docs.ultralytics.com/usage/python/
- Ultralytics object detection: https://docs.ultralytics.com/tasks/detect/
- Ultralytics tracking: https://docs.ultralytics.com/modes/track/
- Ultralytics license: https://www.ultralytics.com/license
