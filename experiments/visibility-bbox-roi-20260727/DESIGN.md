# Visibility-aware dual-view 실험 설계

**상태:** owner 승인 후 착수 (`ㄱㄱ`, 2026-07-27)  
**범위:** offline evaluation only. production 모델·prompt·selector·Gate·DB·R2는 변경하지 않는다.

## 1. 연구 질문

통합 GT 실패 감사에서 `VISIBILITY_SCALE_OCCLUSION`은 44개 과거 VLM mismatch 중
21 clips / 19 independent episodes / 4 camera-nights에서 관찰됐다. 하지만 이 표본은
과거 모델·prompt·temperature 결과로 고른 exposed diagnostic set이다.

이번 연구는 두 질문을 순서대로 분리한다.

1. 과거 visibility 관련 오판이 현재 평가 계약에서도 안정적으로 재현되는가?
2. 재현된다면 전체 화면과 게코 확대 화면을 함께 주는 dual view가 오판을 순회복하는가?

첫 질문이 실패하면 두 번째 질문을 실행하지 않는다. 사라진 오판에 ROI를 적용해 생긴
우연한 라벨 변화를 개선으로 오해하지 않기 위해서다.

## 2. 기존 연구와의 경계

이 연구는 폐기된 `roi_mean`이나 2026-06-16 `roi-crop-center`를 재실행하지 않는다.

| 기존 연구 | 측정한 것 | 결과 | 이번 연구와 차이 |
|---|---|---|---|
| `roi_mean` | OpenCV 전역/카메라 종속 수치 | camera-domain 의존으로 폐기 | 사용하지 않음 |
| `roi-crop-center` | 급여 3종, center crop 단독 | 56건 paired 순개선 0, `close` | 이번 중심 실패인 moving/basking→shedding은 당시 Out |
| tracking PoC | OWLv2→CSRT 자동 추적 | 검출률·drift gate 실패 | 자동 detector 투자 전에 현행 오판 재현부터 확인 |
| 이번 연구 | 과거 mismatch 44건, 현행 6-frame 계약 재현 → 조건부 dual view | 미실측 | crop 단독이 아니라 full frame을 보존한 이중 입력 |

## 3. 검토한 접근법

### A. 44건에 즉시 ROI를 적용

- 장점: 바로 treatment 결과를 얻는다.
- 단점: 현재 baseline 오판이 사라졌어도 treatment 효과처럼 보일 수 있다.
- 판정: 기각.

### B. baseline 재현 게이트 후 조건부 dual view

- 장점: 현재도 남은 안정 오판만 겨냥하며 불필요한 inference와 detector 투자를 막는다.
- 단점: 재현 실패 시 ROI 자체의 상한은 측정하지 않는다.
- 판정: 채택.

### C. fresh multi-camera holdout부터 수집

- 장점: production adoption 판단에 가장 강하다.
- 단점: 현재 표본으로 개선 레버가 존재하는지도 모른 채 새 라벨 비용부터 쓴다.
- 판정: Phase 2. historical dev에서 레버가 확인된 뒤에만 수행한다.

## 4. Phase 0 — 현행 baseline 재현

### 표본

- 통합 감사에서 사전 선택한 44개 mismatch 전수.
- 파일명은 `review-001`~`review-044` alias만 사용한다.
- GT·과거 VLM 예측·UUID·R2 key는 inference에 노출하지 않는다.
- 기대 action은 현행 v4.0 7-class ontology에 맞춰 `moving`으로 정규화한다.
  과거 `basking`은 현행 제외 클래스이므로 일반 움직임/자세 관찰인 `moving`으로 평가한다.

### 평가 계약

- model: exact `claude-sonnet-5`
- prompt: nightly reporter의 frozen `system.v4.0.md` 사본
- input: 시간순 6 JPEG, long edge 768px no-upscale, JPEG quality 85
- provider: Claude subscription CLI, `--safe-mode`, Read-only image access, effort low
- repetition: clip당 3회
- output: 7-class JSON schema

### Phase 0 통과 기준

아래를 모두 만족해야 Phase 1을 실행한다.

1. 같은 non-`moving` 오답이 3/3 재현된 clip이 최소 10개다.
2. 그 clip들이 최소 10 independent 5-minute episodes다.
3. 최소 2 camera-nights에 걸친다.
4. largest duplicate group share가 20% 이하다.

10개 미만 clip이면 episode 기준도 통과할 수 없으므로 즉시 종료한다.

## 5. Phase 1 — 조건부 visibility-aware dual view

Phase 0가 통과할 때만 별도 frozen test sheet를 추가하고 실행한다.

- baseline 6 full frames는 그대로 보존한다.
- GT·과거 예측을 보지 않은 reviewer가 게코 위치만 표시한 bbox로 6 crop을 만든다.
- treatment는 같은 시점의 `full frame + crop` 쌍이다.
- bbox는 위치 evidence일 뿐 행동 GT, 자동 skip, selector 정답으로 사용하지 않는다.
- Phase 0의 44개 전수를 treatment에 넣어 recovered와 broken을 함께 센다.

핵심 지표는 stable-error recovered/broken, shedding false-positive episode rate,
care false-positive episode rate, unanimous rate, judgeability/abstention, frame·token cost다.
historical 44개는 dev/regression 전용이며 production holdout으로 승격하지 않는다.

## 6. 산출물과 경계

Tracked:

- `DESIGN.md`, `IMPLEMENTATION-PLAN.md`, `TEST-SHEET.md`, `REPORT.md`
- 순수 runner/scorer와 unit tests
- alias 단위 집계 결과. UUID·R2 key·원문 reasoning은 제외

Gitignored:

- mp4, frame, prompt copy, clip/run별 raw inference envelope
- sensitive manifest와 DB join

금지:

- DB/R2 write, migration, deploy, LaunchAgent/Slack 조작
- model 학습, prompt/threshold/selector 변경
- historical 44개를 future holdout으로 부르기
- Phase 0 실패 뒤 Phase 1을 강행하기

## 7. Decision gate

| Gate | 근거 | 판정 |
|---|---|---|
| SOT 부합 | 사람 GT 기반 실패 검증이며 Gate 자동 skip·production 변경과 분리 | PASS |
| 기대효과 명확 | 현재도 남은 visibility 오판이 있을 때만 입력 레버의 상한을 측정 | PASS |
| 측정 가능 | 3/3 stable error, episode/night/duplicate gate, paired recovered/broken | PASS |
| 유효한 계획 | 재현 실패 시 즉시 종료, 통과 시에만 별도 Phase 1 동결 | PASS |

`PASS_FOR_BASELINE_REPRODUCTION_ONLY`

## 8. 성공·종료 정의

- Phase 0 통과: `VISIBILITY_ROI_BASELINE_REPRODUCED`
- Phase 0 실패: `VISIBILITY_ROI_REJECT_NO_CURRENT_REPRODUCIBLE_FAILURE`
- 실행 계약/자료 부족: `VISIBILITY_ROI_HOLD_<REASON>`
- Phase 1 결과는 별도 `ADOPT` / `HOLD` / `REJECT`로 판정한다.

