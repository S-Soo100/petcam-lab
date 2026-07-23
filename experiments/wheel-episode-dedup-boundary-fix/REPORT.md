# REPORT — 쳇바퀴 에피소드 10분 경계 교정 (v1.1 boundary-fix)

> 실행일: 2026-07-23 · 성격: v1 shadow chaining 결함 salvage (1회 교정)
> 시험지(동결): [`TEST-SHEET.md`](TEST-SHEET.md) · 설계: [`../../docs/superpowers/specs/2026-07-23-wheel-episode-boundary-correction-design.md`](../../docs/superpowers/specs/2026-07-23-wheel-episode-boundary-correction-design.md)
> **machine verdict: `BOUNDARY_CORRECTION_READY_FOR_OWNER_REVIEW`**

---

## 1. root cause (RED→GREEN 으로 닫음)

v1 `group_clips` 의 run 분리는 **`현재 clip − 바로 이전 clip` 간격만** 검사했다. 5분 간격으로 비슷한 clip 이 계속 들어오면 각 간격은 ≤10분이지만 첫 clip~마지막 clip 전체 길이는 수시간이 됐다. 시험지의 `그룹 전체 길이 ≤10분` 계약 위반.

- RED: `tests/test_wheel_shadow.py::test_grouping_chain_cannot_exceed_total_episode_span` (+ exact-600 / over-601 경계) — 5분×5개가 한 그룹으로 chaining 되어 실패.
- GREEN: run 분리에 `max_inter_clip_gap_sec` 와 `max_episode_span_sec` 를 **분리**. `current − previous > 600` **또는** `current − run_start > 600` 이면 새 run. 그룹은 run 내부에서만 생기므로 모든 그룹 span ≤600초. `validate_group_spans` 로 산출물 직후 hard fail 이중 검증.

## 2. 교정 전 / 후 (동일 frozen signature)

| 지표 | 교정 전 (v1) | 교정 후 (v1.1) |
|---|---:|---:|
| fresh 그룹 수 | 32 | **80** |
| fresh membership | 326 | **300** |
| fresh representatives | 71 | **164** |
| fresh max group span | **18,224초 (5시간 4분)** | **600초** |
| 전체 길이 600초 초과 그룹 | **19 / 32** | **0** |
| 위반 그룹 membership | **296 / 326** | **0** |
| fresh overlap | 0 | **0** |

chaining 결함 제거로 최장 그룹이 18,224초 → 정확히 600초로 bounded. 위반 그룹 19→0. 거대 그룹이 잘리며 membership 326→300(경계로 분리된 singleton 26건이 ungrouped 로 빠짐), 그룹 수 32→80(작은 bounded 에피소드로 재분할), 대표 71→164.

## 3. known wheel 24 재계산

| 지표 | 교정 전 (v1) | 교정 후 (v1.1) |
|---|---:|---:|
| 그룹 수 | 4 | **5** |
| membership | 24 | **23** |
| representatives | 9 | **11** |
| ungrouped | 0 | **1** |
| 검토량 감소율 | 62.5% | **50.0%** |

교정 전 known wheel 4 그룹 중 2개가 전체 길이 초과였다(ep2 696초·ep3 1,095초). 교정으로 ep2 는 6+1(ungrouped), ep3 는 4+5 로 분리돼 5 그룹·대표 11·미묶음 1 이 됐다. 검토량 = 대표 11 + 미묶음 1 = 12 → 감소 `1 − 12/24 = 50.0%`. **게이트 ≥50% 를 정확히 만족**(경계값). v1 의 62.5% 는 span 위반 그룹을 포함한 값이라 교정본으로 대체한다.

## 4. 입력 SHA (design §4 동결과 일치)

| 입력 | SHA-256 |
|---|---|
| `EVIDENCE-AUDIT.json` | `23789fa8ea430c4dc24b015847c360a6afa72565c897c3d4b7b8654702a508e3` |
| `frozen-cohort.json` | `b67b32f27259d132cda5861f8126f6b48f4bb704528c0458ebbf63a95d17f953` |
| `wheel-roi-profile-v1.json` | `653e64c25e057339ce9a1844d27c570ce99916d20986023fafdabd84935c7825` |

R2 영상·production DB 를 다시 읽지 않고 위 커밋된 signature 만 replay 했다.

## 5. 결정론 replay SHA (2회 동일)

- `result_sha256` = `5b95f566ca2d…`
- `replay_sha256` = `5b95f566ca2d…`
- 동일 입력 2회 grouping 결과 SHA 일치 = 결정론 100%.

## 6. 7개 기계 게이트

| # | 게이트 | 결과 |
|---|---|---|
| 1 | 모든 fresh·known 그룹 전체 길이 ≤600초 | ✅ span 위반 0 (fresh max 600s, known 0) |
| 2 | overlap 0 | ✅ fresh 0 · known 0 |
| 3 | 동일 입력 2회 재실행 SHA 동일 | ✅ result==replay (`5b95f566…`) |
| 4 | 입력 3개 SHA 가 §4 와 동일 | ✅ 3/3 일치 |
| 5 | known wheel 검토량 감소 ≥50% | ✅ 50.0% (경계값 충족) |
| 6 | 기존 전체 + wheel focused 테스트 통과 | ✅ (전체 pytest — Task 6 §전체 테스트) |
| 7 | DB/R2 read·write 0, VLM 0, temp media 0 | ✅ 구조상 0 (stdlib+pure만, 정적 grep 0건, temp media 미생성) |

→ 7개 전부 통과: **`BOUNDARY_CORRECTION_READY_FOR_OWNER_REVIEW`**.

## 7. 독립 재검증 (runner 미import)

RESULT.json + BLIND-REVIEW.csv 만 읽어 재확인: CSV 그룹 80 = RESULT.fresh.n_groups, CSV clip 300 = n_membership, CSV max span 600초 = RESULT, overlap 0, known reduction 재계산 0.5 = RESULT, known membership+ungrouped(23+1)=24=n_total, CSV 헤더 금지 토큰 0. 전부 일치.

## 8. 한계 · 남은 사람 판정

- 이 교정은 **경계 로직만** 고쳤다. ROI·threshold 4종·anchor·대표 규칙·frozen cohort 는 byte-equivalent 유지. day/IR 혼재·과분할 여부 등 품질 판단은 이번 범위 밖.
- known wheel 감소율이 62.5%→50.0% 로 내려갔다(경계값). 자동화 채택 가치는 owner blind 감사 결과에 달렸다.
- **owner blind 감사 미완.** owner 가 (a) 다른 행동 혼입 (b) 중요한 wheel interaction 대표 소실 (c) 모호 그룹 중 하나라도 발견하면 reject → 추가 튜닝 없이 자동 중복 묶기 폐기.

## 9. decision label

`BOUNDARY_CORRECTION_READY_FOR_OWNER_REVIEW` (기계 게이트 전용). **채택·배포 아님.** owner blind 파일: [`BLIND-REVIEW.csv`](BLIND-REVIEW.csv). main merge·UI 연결·canary·threshold 튜닝·owner 판정 대행은 수행하지 않는다.

## 10. Owner/Codex 제품 효용 재검수와 최종 폐기 판정

2026-07-23 owner 승인에 따라 기계 판정 이후의 제품 효용을 독립 재계산했다. 이 절은 동결된
시험지나 `RESULT.json`의 기계 판정을 바꾸지 않고, 실제 라벨링 부담을 기준으로 채택 여부를
결정하는 종료 기록이다.

### 실제 fresh 검수량

- fresh 전체: 779
- 대표로 남는 clip: 164
- 미묶음으로 그대로 보는 clip: 479
- 실제 검수량: `164 + 479 = 643`
- 실제 감소: `1 - 643 / 779 = 17.4583%`
- 절약되는 검수: 136 clip
- 채택 품질을 확인하기 위한 owner blind audit: 80그룹·300 clip

그룹 크기별 재계산에서 80그룹 중 27그룹(56 clip)은 대표 수가 멤버 수와 같아 검수 절감이
0이었다. 여기에는 2개짜리 그룹 25개가 포함된다.

### 판정

known wheel 24개에서의 50% 감소는 calibration subset의 경계값일 뿐, 실제 fresh 라벨링
검수량 감소를 나타내지 않는다. 합의한 제품 기준은 **전체 검수량 50% 이상 감소**였고,
실측 17.46%는 이를 충족하지 못한다. 136개를 덜 보기 위해 300개를 추가 감사해야 하므로
owner 비용 대비 효용도 부족하다.

# `AUTOMATION_REJECTED_LOW_UTILITY`

- owner blind audit는 실행하지 않는다.
- 추가 threshold·ROI·IR/day 튜닝을 하지 않는다.
- main merge·UI 연결·canary·배포를 하지 않는다.
- 기존 수동 검수를 유지한다.
- branch와 artifact는 실패 원인·재현 근거로만 보존한다.

앞 절의 `BOUNDARY_CORRECTION_READY_FOR_OWNER_REVIEW`는 **경계 버그가 기계적으로 교정됐다는
중간 판정**으로만 유효하다. 제품 최종 판정은 이 절의
`AUTOMATION_REJECTED_LOW_UTILITY`가 우선한다.
