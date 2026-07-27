# Visibility ROI Baseline Reproduction Report

## Verdict

`VISIBILITY_ROI_REJECT_NO_CURRENT_REPRODUCIBLE_FAILURE`

과거 VLM mismatch 44건에 바로 bbox/ROI를 적용하지 않고, 현재 nightly 평가 계약에서
오판이 먼저 재현되는지 확인했다. 두 passes가 끝난 시점에 같은 non-`moving` label을 유지한
clip은 **7/44**뿐이었다. 최종 3/3 stable error는 이 7개를 넘을 수 없으므로 사전 gate
`>=10 clips / >=10 independent episodes`가 수학적으로 불가능해졌다.

따라서 pass 3와 dual-view Phase 1은 실행하지 않았다. 현재 서비스 개선 과제로
visibility bbox/ROI 파이프라인에 투자할 근거는 부족하다.

## 1. 실행 계약

| 항목 | 실측 |
|---|---|
| 표본 | historical exposed mismatch 44 clips 전수 |
| alias | `review-001`~`review-044`; UUID/R2 key/GT/과거 prediction 비노출 |
| model | exact `claude-sonnet-5` |
| provider | Claude subscription CLI 2.1.177, temperature 비제어 |
| prompt | nightly `system.v4.0.md` |
| prompt SHA-256 | `7a7b104161ae9076cdbb42df0ed3b6d23275e821681a140a8b0e35d273cecb9f` |
| input | `six-768q85-v1`: 시간순 6 frames, long edge 768, no-upscale, JPEG quality 85 |
| batching | 최대 4 clips/call |
| 실행량 | 44 clips × 2 passes = 88 clip-runs, 22 provider calls |
| planned pass 3 | monotonic early-stop으로 미실행 |

사람 GT는 현재 v4.0 7-class ontology에 맞춰 전부 `moving`으로 평가했다. 과거 `basking`은
현행 제외 클래스라 일반 자세/움직임인 `moving`으로 정규화했다.

## 2. 결과

### Pass별 action 분포

| Action | Pass 1 | Pass 2 |
|---|---:|---:|
| moving | 33 | 31 |
| unseen | 8 | 9 |
| drinking | 2 | 2 |
| shedding | 1 | 2 |
| 합계 | 44 | 44 |

### 두 passes 사이 변화

| Transition | Clips |
|---|---:|
| moving → moving | 27 |
| unseen → unseen | 6 |
| moving → unseen | 3 |
| drinking → moving | 2 |
| moving → drinking | 2 |
| unseen → moving | 2 |
| moving → shedding | 1 |
| shedding → shedding | 1 |

- 같은 label 유지: 34/44 = **77.3%**
- pass 사이 label 변경: 10/44 = **22.7%**
- 같은 non-moving 오답 유지: **7/44 = 15.9%**
  - unseen 6
  - shedding 1
  - drinking 0

`stable_error`는 같은 non-moving이 3/3이어야 한다. 두 번 후 후보가 7개뿐이므로 세 번째
pass에서 후보가 늘어날 수 없다. episode/night/dedup을 확인하기도 전에 clip 최소 기준 10을
통과하지 못한다.

## 3. 가설 판정

- H1 “현재도 최소 10 independent episodes의 안정 visibility 오판이 남는다”: **기각**
- H0 “현재 계약에서는 Phase 1을 정당화할 안정 오판이 부족하다”: **유지**

통합 감사의 `VISIBILITY_SCALE_OCCLUSION 21/44`가 틀렸다는 뜻은 아니다. 그 값은 과거
mismatch 영상에서 관찰한 시각 조건의 분포다. 이번 결과는 그 과거 오판을 현재
v4.0·six-768·Sonnet 5 조건에서 안정적으로 재현하지 못했다는 뜻이다.

## 4. 서비스 개선에 주는 결론

### 지금 하지 않을 것

- bbox detector/track pipeline 투자
- full-frame + crop dual-view production 연결
- Gate bbox를 행동 GT나 auto-skip 근거로 사용
- ROI에 맞춘 prompt/threshold/selector tuning

현재 stable shedding overcall의 상한은 1개다. 과거의 핵심 문제였던
`moving/basking → shedding`을 겨냥해 ROI 파이프라인을 추가하면 복잡도와 inference 비용은
늘지만 반복 개선 표적은 최소 기준에 못 미친다.

### 더 실효성 있는 개선축

두 passes에서 label이 바뀐 clip이 10/44였다. 이 표본은 과거 오답으로 선택됐으므로 전체
서비스 변동률로 일반화할 수는 없지만, 현재도 temperature 비제어 Claude CLI의 판정 변동이
ROI보다 먼저 통제해야 할 축이라는 기존 P1 결론과 방향이 맞는다.

우선순위는 다음과 같다.

1. 결정론 가능한 provider 계약 또는 consensus로 label 변동을 통제한다.
2. fresh multi-camera human GT에서 현재 baseline failure를 다시 측정한다.
3. 그 fresh set에서 visibility stable error가 다시 `>=10 episodes / >=2 nights`로 확인될
   때만 dual view를 재개한다.

`unseen→unseen` 6건은 확대가 도움될 가능성이 남지만 top-cause gate에 못 미치고,
이번 error-selected set만으로 recovered/broken을 측정할 control도 부족하다. 따라서 별도
investment가 아니라 향후 short-clip visibility-first holdout에서 자연스럽게 다시 관찰한다.

## 5. 비용

| 항목 | 실측 |
|---|---:|
| provider calls | 22 |
| clip-runs | 88 |
| input tokens | 134 |
| cache creation input tokens | 576,075 |
| cache read input tokens | 1,005,838 |
| output tokens | 327,997 |
| direct API cost | $0 — subscription CLI |

구독이라 직접 API 비용은 0이지만 quota와 wall time은 소비됐다. early-stop으로 pass 3의
11 provider calls / 44 clip-runs를 생략했다.

## 6. 무결성·재현성

- TEST-SHEET는 inference 전에 model/input/prompt/gate를 동결했다.
- early-stop은 결과 label을 보기 전에 기록한 단조 상한 규칙이며 합격 숫자를 바꾸지 않았다.
- raw per-clip result, reasoning, frames, prompt copy는 gitignored `raw/`에만 있다.
- tracked `baseline-summary.json`은 aggregate-only다.
- 독립 scorer process 결과는 tracked summary와 byte-identical이었다.
- production DB/R2 접근 자체가 0이므로 write도 0이다.
- LaunchAgent, Slack, deploy, migration, production code/model/prompt/selector 변경 0이다.
- 외부 reviewer는 Codex CLI의 model/client 비호환과 Gemini CLI 개인 client 지원 종료로 실행
  실패했다. 외부 리뷰 통과를 주장하지 않으며, focused/full tests와 독립 재채점을 완료
  증거로 사용한다.

## 7. 한계

1. historical exposed error-selected set이라 일반 정확도와 변동률을 추정할 수 없다.
2. Claude CLI temperature를 제어하지 못해 2-pass 변화의 정확한 원인을 temperature 하나로
   확정할 수 없다.
3. clip gate가 먼저 실패해 episode/night link와 Phase 1 recovered/broken은 측정하지 않았다.
4. `unseen` 6건에 crop이 도움될 가능성 자체는 반증하지 않았다. 투자 우선순위 기준만
   통과하지 못했다.
5. fresh multi-camera holdout 성능이나 production lift는 이번 결과로 주장하지 않는다.

## 8. 미실행

- Phase 0 pass 3 — stable-error upper bound 7 < 10으로 불필요
- Phase 1 bbox annotation / crop / dual-view inference
- episode·camera-night DB link
- fresh holdout 수집
- model 학습과 production 반영
