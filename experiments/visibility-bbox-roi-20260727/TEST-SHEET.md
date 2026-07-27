# Visibility ROI Phase 0 — Frozen Test Sheet

> `.claude/rules/research-testing.md` 적용. inference 실행 전 동결하며 결과를 본 뒤 변경하지 않는다.

**실험 ID:** `visibility-bbox-roi-20260727`  
**Phase:** 0 — current baseline reproducibility  
**상태:** frozen, not run  
**owner 승인:** 2026-07-27 `ㄱㄱ`

## 1. 가설

- **H0:** 과거 visibility 관련 mismatch는 현행 v4.0·six-768 계약에서 안정적으로 재현되지
  않는다. Phase 1 ROI treatment를 정당화할 현재 실패가 부족하다.
- **H1:** 같은 non-moving 오답이 최소 10 independent episodes·2 camera-nights에서
  3/3 재현된다. Phase 1 dual-view 비교가 정당화된다.

## 2. Sample list

- 통합 감사에서 두 failure mode로 사전 선택된 44 clips 전수.
- 입력 파일은 `review-001.mp4`~`review-044.mp4` alias다.
- 선택을 다시 최적화하거나 `VISIBILITY_SCALE_OCCLUSION` 21건만 cherry-pick하지 않는다.
- 전부 historical exposed diagnostic이며 future holdout이 아니다.
- inference 기대 label은 v4.0 7-class ontology의 `moving`이다.
- UUID, R2 key, 사람 GT, 과거 VLM prediction은 inference에 노출하지 않는다.

## 3. 모델·입력·프롬프트

| 항목 | 고정값 |
|---|---|
| provider | Claude subscription CLI |
| CLI | `2.1.177 (Claude Code)` |
| model | exact `claude-sonnet-5` |
| temperature | CLI에서 제어 불가 |
| repeats | clip당 3회 |
| batching | alias 정렬, 최대 4 clips/call, 3 pass |
| input | 시간순 JPEG 6장, long edge 768 no-upscale, JPEG quality 85 |
| prompt | nightly reporter `system.v4.0.md` read-only copy, source HEAD `139ff895e9f92145e183ab6be24b7486ed9ea2a1` |
| prompt SHA-256 | `7a7b104161ae9076cdbb42df0ed3b6d23275e821681a140a8b0e35d273cecb9f` |
| schema | `eating_paste`, `eating_prey`, `drinking`, `shedding`, `moving`, `unseen`, `hand_feeding` |
| tools | `Read` only, `--safe-mode`, `--no-session-persistence`, effort low |

## 4. 지표

1. `stable_error`: 같은 non-`moving` label이 3/3인 clip 수와 분포
2. `stable_correct`: `moving` 3/3인 clip 수
3. `unstable`: 나머지 clip 수
4. 3회 unanimity
5. stable-error independent episodes, camera-nights, largest duplicate share
6. modelUsage token 합계와 Claude CLI 구독 호출 수

44개는 과거 오답으로 선택됐으므로 이 결과를 일반 정확도라고 부르지 않는다.

## 5. 합격 기준

Phase 1 진입은 아래를 모두 만족해야 한다.

- stable-error clips >= 10
- stable-error independent 5-minute episodes >= 10
- camera-nights >= 2
- largest duplicate group share <= 20%

stable-error clips < 10이면 episode 기준도 불가능하므로 DB episode link 없이 즉시 reject한다.

## 6. Decision rule

| 결과 | verdict | 다음 행동 |
|---|---|---|
| stable-error clips < 10 | `VISIBILITY_ROI_REJECT_NO_CURRENT_REPRODUCIBLE_FAILURE` | Phase 1 실행 금지. 현재 서비스 개선 후보에서 ROI 제거 |
| clips >=10, episode/night/duplicate 미검증 | `VISIBILITY_ROI_HOLD_EPISODE_LINK_REQUIRED` | SELECT-only link 후 재판정 |
| 네 기준 전부 통과 | `VISIBILITY_ROI_BASELINE_REPRODUCED` | 별도 Phase 1 test sheet 동결 후 dual view 실행 |
| auth/quota/model/input 계약 실패 | `VISIBILITY_ROI_HOLD_EXECUTION_CONTRACT` | 원인 해소 후 raw resume |

## 7. 비용·안전

- 최대 33 provider calls: `ceil(44/4) × 3`.
- subscription quota를 공유하므로 quota/auth 감지 시 즉시 중단한다.
- raw result는 batch마다 atomic write하며 재실행 시 완료 batch를 건너뛴다.
- DB와 R2에는 접근하지 않는다. 기존 로컬 mp4를 read-only로 사용한다.
- production code, model, prompt, selector, Gate, runtime 설정은 변경하지 않는다.

## 8. 해석 가드

- 3/3 일치는 temperature=0 결정론 보증이 아니라 안정 재현의 강한 근사다.
- baseline failure가 재현되지 않으면 ROI가 무효라고 일반화하지 않는다. “현재 개선할
  재현 가능한 표적이 없다”까지만 결론낸다.
- Phase 0 실패 후 과거 21/44를 ROI 예상 개선률로 재사용하지 않는다.
- Phase 1이 통과해도 fresh multi-camera holdout 전 production adoption은 금지한다.

## 9. Preflight

2026-07-27 inference 전 확인:

- `claude auth status`: `loggedIn=true`, subscription=`max`
- Claude CLI `2.1.177`
- `ffmpeg`, `ffprobe` present
- local alias mp4 exactly 44
- prompt source와 SHA-256은 §3 값으로 동결
- production DB/R2 접근 0
