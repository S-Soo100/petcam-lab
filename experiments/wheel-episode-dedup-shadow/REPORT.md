# REPORT — P4 Cam(dev) 쳇바퀴 에피소드 중복 묶음 read-only shadow

> 실행일: 2026-07-23 · 시험지: [`TEST-SHEET.md`](TEST-SHEET.md) (동결본)
> 실행 host: BaekBook-Pro-14-M5.local · branch `feat/wheel-episode-dedup-shadow`
> **decision: `hold` → 최종 판정 `SHADOW_BLOCKED_INSUFFICIENT_DATA`**

---

## 1. 결과 표

### 1.1 자체 안전 게이트 (G-*)

| 게이트 | 기준 | 결과 | 판정 |
|---|---|---|---|
| G-DET 결정론 | 2회 replay SHA 동일 | `a109682e776b…` 2회 동일 + shadow-groups.json 저장 SHA 일치 | ✅ |
| G-OVL overlap | clip 2그룹 중복 = 0 | membership 326, 중복 0, membership∩ungrouped 0 | ✅ |
| G-TMP temp media | 종료 시 0 | `_tmp` 삭제, worktree 내 shadow media 0 (기존 docs/ir 자산 제외) | ✅ |
| G-MUT mutation | SELECT 전/후 지문 동일 | before==after == True (cohort clip 불변 속성 SHA) | ✅ |
| G-R2 / G-VLM | R2 write 0 · VLM 0 | 코드 grep: R2 `head_object`/`download_file`만, VLM 호출 0, DB `.select`만 | ✅ |
| G-SEC | secret/signed/media tracked 0 | tracked media 0 · tracked .env 0 · signed URL/secret 0 · r2_key 누출 0 | ✅ |
| G-WORKER | worker deadline/error 증가 0 | worker/LaunchAgent/lock 미접촉, evidence append-only 테이블 미기록 | ✅ |

### 1.2 데이터 게이트 (D-*)

| 게이트 | 기준 | 결과 | 판정 |
|---|---|---|---|
| D-NIGHT | fresh 독립 night ≥ 3 | 07-19(128)·07-20(177)·07-21(474) = 3 | ✅ |
| D-MEM | 제안 membership ≥ 100 | **전체 326 ≥ 100, 그러나 신뢰 가능(IR) 86 < 100** | ⚠️ (아래 §4) |
| D-ROI | ROI 신뢰 가능 | IR(야간) 신뢰 ✅ · **day(주간) threshold 신뢰 불가** | ⚠️ |

### 1.3 효과 지표 (E-*)

| 지표 | 기준 | 결과 |
|---|---|---|
| E-WORKLOAD known wheel 검토량 감소 | ≥ 50% | **62.5%** (24 GT → 4 그룹 · 대표 9) ✅ |
| E-FALSEMERGE | owner 감사 0건 | **owner-pending** (단, shadow가 day-mode false merge 자체 검출 — §4) |
| E-PRESERVE distinct interaction 대표 보존 | 100% | **owner-pending** |

### 1.4 grouping 결과 (fresh 779)

| 구분 | 그룹 | membership | 대표 | max 그룹 | 크기 분포 |
|---|---:|---:|---:|---:|---|
| **전체** | 32 | 326 | 71 | 118 | — |
| **IR (야간, 캘리브레이션 regime)** | 14 | 86 | — | 19 | 2·2·2·2·2·3·4·4·5·6·7·10·18·19 |
| **day (주간, out-of-calibration)** | 18 | 240 | — | **118** | 2×8·3×4·8·10·15·21·40·**118** |
| ungrouped | — | 453 | — | — | precision-first 미분류 |

known wheel(24, IR) regression: 4 그룹(5·3·7·9) · 대표 9 · **감소 62.5%** (설계 §2.2 "24→8~12" 부합).

---

## 2. 시험지 대비 (사후 변경 여부)

- 합격 기준(게이트 숫자) **변경 없음.**
- grouping_params 는 시험지 §3 이 예고한 대로 **known wheel GT 24 에서 calibration 후 profile 에 동결**하고 fresh grouping 을 실행했다(fresh 결과를 보고 튜닝하지 않음). 최초 추정치(floor 0.06)는 known wheel 실측(ROI motion 0.0112~0.0276)으로 floor 0.01 / hamming 7 / tolerance 0.02 로 확정했다. 이는 calibration 절차이며 pass gate 변경이 아니다.
- `workload_reduction` 공식 버그(groups=0 시 1.0) 를 실행 중 수정했다(= 대표+미묶음 검토량 기준). 결과 해석에 유리하게 바꾼 것이 아니라 정정이다.

---

## 3. 가설 판정

- **H0 부분 유지.** IR(야간) regime 에서는 precision-first 묶음이 성립하고 known wheel 검토량을 62.5% 줄였다(H1 지지). 그러나 **pre-registered fresh cohort 전체(day 포함)에서는 IR-calibrated threshold 가 day baseline 모션을 over-merge** 하여 clean 한 ≥100 membership 제안을 만들지 못했다(H0 미기각).

---

## 4. decision label: `hold` → `SHADOW_BLOCKED_INSUFFICIENT_DATA`

### 근거
1. **신뢰 가능한 membership(IR) = 86 < 100.** wheel 사용은 야행성이다(known GT 24건 전부 IR, 촬영 02:11~03:49 KST). floor 0.01 은 IR wheel 클립(0.0112~0.0276)에서 캘리브레이션됐다.
2. **day-mode 그룹은 out-of-calibration 이고 명백한 false merge 를 만든다.** 대표 사례 `wheel_ep_025`: day, **118 clip, 07:15~12:19(5시간)**, ROI motion mean 0.0100~0.0142(전부 floor 부근 중앙값 0.0104). 실제 wheel 에피소드(~10분)와 양립 불가 — 주간 배경 모션이 floor 를 넘고 정적 배경이 perceptual 로 뭉친 결과다.
3. 설계 hard gate 는 "false merge 1건이면 production 도입 reject". shadow 가 owner 감사 전에 이미 day regime false merge 를 검출했으므로, 전체 cohort 제안을 clean 한 owner 감사 대상으로 넘기지 않는다. **수치를 꾸며 READY 로 올리지 않는다**(시험지 decision 룰 + 태스크 "ROI 신뢰 못하면 HOLD").

### 안전/무결성은 이상 없음
자체 안전 게이트(G-*)는 전부 통과했다 — production write 0, VLM 0, R2 write 0, 결정론 100%, overlap 0, mutation 불변, temp media 0. 즉 **shadow 는 안전하게 실행됐고, 판정을 막은 것은 알고리즘의 day-mode 일반화 실패**이지 안전 위반이 아니다.

### shadow 의 가치
이 실행이 **production/UI/owner 부담을 지기 전에** day-mode 캘리브레이션 공백을 드러냈다. IR regime + known-wheel 62.5% 는 접근법이 야간 wheel 에 대해 유망함을 보여준다.

---

## 5. 한계 · 노이즈

- **perceptual 신호는 에피소드 구분자가 약하다.** wheel 돔이 정적이라 cross-episode anchor hamming(3~6)이 within-episode(0~8)와 겹친다 → 에피소드 분리는 사실상 **시간 ≤10분 경계**가 담당한다. 활동이 많은 시간대(연속 clip)에서는 10분 경계가 안 끊겨 run 이 길어지고 over-merge 로 이어진다(day 118 그룹).
- IR-only 로 좁히면 membership 86, max 그룹 19 로 합리적이지만 pre-registered 100 미달.
- ROI 는 provisional(육안+모션에너지). owner 확인 전 production 계약 아님.
- 이 실행 window 에는 owner 동시 라벨링이 관측되지 않았다(watermark 불변). 동시 라벨링 안전 계약(frozen cohort + fingerprint)은 배선·검증됐으나 실 동시성 상황에서의 관측은 미확보.

---

## 6. 다음 액션 (v2 제안 — 별도 승인·TEST-SHEET 필요)

1. **mode-scoped v2**: fresh cohort 를 **IR(야간)으로 좁히거나** day 전용 floor 를 별도 캘리브레이션한다. wheel 사용이 야행성이므로 IR-scope 가 behavior 와 정합.
2. **긴 run 분할**: 연속 활동에서 10분 경계만으로 안 끊기는 문제 → run 내 sub-episode 분할(모션 정지 구간·perceptual 급변)로 over-merge 방지.
3. **fresh night 확대 재측정**: v2 threshold 동결 후 새 IR camera-night ≥3 에서 재실행, membership≥100(IR) 목표.
4. owner 가 원하면 IR 14그룹(신뢰 subset)만 별도 BLIND 감사로 precision 사전 점검 가능(선택).

**Stop Point:** 어떤 경우에도 main merge · DB/UI 구현 · production 배포 없음. E-FALSEMERGE/E-PRESERVE 는 owner-pending.
