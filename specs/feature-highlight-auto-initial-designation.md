# 하이라이트 자동 1차 판정 (GME 규칙 → 사람 확정 → 규칙 파라미터 조정)

> 영상이 GME(게코 움직임 측정)를 거치는 순간, 명확한 숫자 기준으로 `하이라이트 O/X`가 자동으로 1차 판정된다. 사람은 그 값을 보면서 확정하고, 우리는 기준 숫자만 만지면서 조정한다. 행동 class 지정보다 먼저.

**상태:** ✅ Phase 1·2 `DEPLOYED_VERIFIED` (2026-09-07, PR #13, production migration 적용·label.tera-ai.uk 배포) — 규칙 v0 = `long_activity 10s` OR `sustained_move 5s`. Phase 2 후반(첫 리뷰 사이클)은 운영 1주 뒤
**작성:** 2026-09-07 (v1 → v2 → v3 같은 날)
**연관:** [`feature-labeling-web-v4-simplification.md`](feature-labeling-web-v4-simplification.md) (검수 화면·권한은 그쪽), [`experiment-gme-jitter-overcount-mitigation.md`](experiment-gme-jitter-overcount-mitigation.md) (활동시간 정확도는 그쪽)
**결정 게이트:** [`docs/decision-gate.md`](../docs/decision-gate.md) 2026-09-07 1차·2차·3차
**구현 계획:** [`docs/superpowers/plans/2026-09-07-highlight-rule-v0-db.md`](../docs/superpowers/plans/2026-09-07-highlight-rule-v0-db.md) (DB 판정 계층 + API)

> **운영·개선 런북(진입점):** [`docs/highlight-rule-operations.md`](../docs/highlight-rule-operations.md) — 데이터 흐름·params 계약·주간 조정 루프·코드 지도·트리거 추가 절차·검증/배포·함정. 이 스펙은 '왜'만 담는다.

## 0. owner 확정 사항 (2026-09-07)

| # | 결정 |
|---|---|
| 1 | 사람 교차검증 없음. 검수한 사람의 답이 최종. |
| 2 | 초기값은 GME 숫자 규칙으로. 사람이 보면서 확정하고, 규칙 숫자를 조정해 나간다. |
| 3 | AI(VLM) 호출 없음. 하이라이트 판정을 행동 class보다 먼저 정한다. |
| 4 | **밤당 개수 제한 없음.** 기준을 넘으면 몇 개든 하이라이트. |
| 5 | **`애매` 없음.** 판정은 `하이라이트 O / X` 둘뿐. |
| 6 | 한 영상은 한 사람이 확정하면 끝(라벨링됨). 라벨링 안 된 영상은 누구든 할 수 있다. |
| 7 | 기존 blind·교차검증·consensus 구조는 전부 버린다 → 별도 스펙 `feature-labeling-web-v4-simplification.md`. |

## 1. 목적

- **제품:** 사람이 보기 전에도 모든 영상에 `하이라이트 O/X`가 붙어 있다. 기준이 숫자라서 "왜 O야?"에 항상 답이 있다.
- **운영:** 검수자는 빈 폼이 아니라 1차 판정을 확인한다. 고친 기록이 쌓이면 기준 숫자를 바꾼다.
- **학습:** 규칙을 코드가 아니라 **파라미터 버전**으로 관리하는 법. 파라미터 하나가 결과 분포를 어떻게 바꾸는지 표로 보는 습관.

## 2. 스코프

### In

1. **규칙 v0** — GME run 숫자(관측 여부·활동시간·최장 연속 움직임)로 `O/X`. 파라미터는 버전으로 append(§4.1, §4.2).
2. **판정 함수** — DB 함수 하나. active 규칙 버전 + 그 영상의 최신 `ok` GME run → `O/X` + 근거 문구. GME run이 생기는 즉시 결과가 존재한다(별도 워커 없음).
3. **사람 확정 원장** — 검수자가 확정한 값 + 그때 보였던 규칙 버전·run·1차 판정 스냅샷(append-only).
4. **집계 조회** — 규칙 버전별 유지율(사람이 그대로 둔 비율)·수정 방향·카메라별·사유 분포. 규칙 조정 논의 재료.
5. **규칙 개정 절차** — 파라미터 바꾸면 새 버전 append + active 전환 이벤트. 과거 확정값은 그대로.

### Out

- **검수 화면·권한·페이지 구조** — `feature-labeling-web-v4-simplification.md`. 이 스펙은 "무슨 값을 어떻게 계산·저장하나"까지.
- **AI(VLM) 호출**, **행동 class 자동 지정** — 다음 논의.
- **앱 하이라이트 피드 연결** — Flutter는 레포 밖 terra-server. 별도 스펙. (이 판정 함수가 그 소비처의 후보 SOT가 될 수 있음)
- **원본 삭제·격리·skip** — `X`여도 영상은 안 건드린다.
- **GME 엔진 수정** — overcount(jitter)는 해당 스펙에서. 여기선 결과를 읽기만.

## 3. 완료 조건

### Phase 0 — 규칙 v0 숫자 확정

- [x] owner가 §4.1 v0 숫자(활동 10초 / 최장 연속 5초 / 하한 없음)를 확정 — 2026-09-07, §4.1a 트리거 OR 구조 포함 승인
- [ ] `scripts/hl_rule_preview.py`로 최근 2~3밤 결과표(카메라별 O 개수·비율)를 owner와 1회 같이 봄
- [x] `docs/decision-gate.md` 3차 레코드 판정 확정 (2026-09-07 append)

### Phase 1 — DB

- [x] forward-only migration: `highlight_rule_versions`(파라미터, append-only, active 전환 이벤트) + `motion_clip_highlight_verdicts`(사람 확정, append-only) — RLS ON, client policy 0, service_role만, UPDATE/DELETE `0A000`
- [x] `fn_highlight_initial(clip_id) → (initial boolean, rule_version, gme_run_id, reason text, status)` — run 없음/대기/실패는 `pending`으로 분리, 과거 detector fallback 없음(2026-09-03 exact identity 원칙)
- [x] `fn_highlight_current(clip_id)` — 사람 확정 있으면 그 값, 없으면 1차 판정. 응답에 `source: human | rule`
- [x] 단위 테스트: 경계값(9.9s/10.0s, 4.9s/5.0s), 미관측, pending, 확정이 1차를 덮지 않고 별도 row, 규칙 버전 전환 뒤 옛 확정 불변
- [x] 로컬 disposable PostgreSQL probe `PROBE_RESIDUE=0`

### Phase 2 — 화면 연결 + 첫 조정 사이클

- [ ] v4 검수 화면(별도 스펙)에서 1차 판정·근거 표시 + `O 확정 / X 확정` 1클릭 → verdict append
- [ ] 1주 운영 뒤 집계표: 유지율·O→X / X→O 수정 수·사유·카메라별
- [ ] 논의 → 규칙 v1 파라미터 append → 다음 주 비교표

## 4. 설계 메모

### 4.0 숫자 (2026-08-15 이후 3,275 영상, GME v2.6, production SELECT-only)

| 항목 | 값 |
|---|---|
| 게코 관측 / 미관측 | 68% / 32% |
| 활동시간 | 중앙값 0.3s · 상위 25% 5.6s↑ · 상위 10% 11.6s↑ · 최대 35.7s |
| 최장 연속 움직임 | 중앙값 0.1s · 상위 25% 2.4s↑ · 상위 10% 4.2s↑ |
| "2마리 동시" | 29% — 오검출 의심, v0 조건에서 제외 |

`애매` 없이 이진으로 봤을 때 (O 아니면 전부 X):

| 규칙 (O 조건) | O 비율 | 주 카메라 O/밤 (108개 중) | 둘째 카메라 O/밤 (93개 중) |
|---|---|---|---|
| 활동≥10s 또는 최장≥5s | **15%** | 약 16 | 약 17 |
| 활동≥15s 또는 최장≥6s | 8% | 약 9 | — |
| 활동≥20s 또는 최장≥8s | 3% | 약 3 | — |
| 활동≥5s 또는 최장≥3s | 약 27% | 약 29 | — |

밤당 제한이 없으니 이 비율이 곧 결과다. 카메라마다 분포가 달라 집계는 항상 카메라별로 본다.

### 4.1 규칙 v0 (제안 — 숫자만 owner 확정)

```
GME 최신 ok run 기준:
  게코 미관측(visible_sec = 0)                     → X   "게코 미관측"
  활동시간 ≥ 10초  또는  최장 연속 움직임 ≥ 5초     → O   "움직임 12.4초 · 최장 연속 6.1초"
  그 외                                            → X   "짧은 움직임 4.2초"
GME run 없음 / 대기 / 실패                         → pending (O/X 아님, 화면엔 '분석 대기')
```

- 파라미터: `{include_activity_sec: 10, include_longest_sec: 5}`. 버전 `hl-rule-v0`.
- 근거 문구는 규칙이 읽은 숫자 그대로. 검수자가 "왜 O지?"에 혼자 답할 수 있어야 조정 논의가 된다.
- **overcount 안전장치는 v0에 안 넣는다.** 정지 게코가 18초 움직임으로 잡히는 사례는 jitter 스펙이 엔진에서 고친다. 규칙에 `fragmentation` 강등을 넣으면 두 곳에서 같은 문제를 고치게 돼 헷갈린다. 대신 집계에 "O→X 수정 사유 = 오검출" 비율을 넣어 그 스펙에 넘긴다.
- top-N(밤당 상위 N개)은 owner가 개수 제한 없음으로 정해 폐기.

### 4.1a 규칙 다각화 후보 — GME만으로 뽑을 수 있는 신호 (2026-09-07 궁리)

**구조 제안: 규칙 = "이름 붙은 트리거들의 OR".** 트리거마다 이름·숫자·켜짐 여부를 params에 두고, O 근거 문구에 **어느 트리거가 켰는지**를 남긴다. 그러면 주간 집계에서 트리거별 유지율(사람이 그대로 둔 비율)을 따로 보고, 트리거 단위로 끄거나 숫자를 바꿀 수 있다. 다각화의 핵심은 신호를 많이 넣는 게 아니라 **어떤 신호가 사람 판단과 맞는지 트리거별로 분리해 보는 것**이다.

```
params = { triggers: [
  {name:"long_activity",  on:true,  activity_sec_gte: 10},
  {name:"sustained_move", on:true,  longest_sec_gte: 5},
  {name:"wide_travel",    on:false, spread_gte: 0.15},    ← v1 (궤적 스칼라 필요)
  ...
], guards: [ {name:"camera_shake", camera_motion_ratio_gte: 0.3 → X} ] }
```

#### A. run 스칼라 — DB에 이미 있음, v0에서 바로 (SQL 함수만)

| 트리거 후보 | 읽는 값 | 잡으려는 장면 | 메모 |
|---|---|---|---|
| `long_activity` | `candidate_moving_sec_any_gecko` | 오래 움직임 | v0 기본. 최근 3주 상위 10% ≈ 11.6s |
| `sustained_move` | `state_intervals` moving 최장 구간 | 끊김 없는 이동(달리기·탐색) | v0 기본. 상위 10% ≈ 4.2s |
| `frequent_bursts` | moving 구간 수 | 짧게 자주 움직임(먹이 반응·핥기·쳇바퀴 오르내림) | 활동시간과 r=0.67 — 부분 중복. `활동≥3s AND 구간≥8` 같이 AND로 |
| `early_action` | 첫 moving 구간 시작 시각 | 촬영 시작 직후부터 움직임 = 모션 트리거 원인이 게코 | 늦게 시작 = 초반은 노이즈 트리거였을 가능성 |
| `two_geckos` | `max_simultaneous_geckos ≥ 2` | 두 마리 상호작용 | **29%가 2마리로 찍혀 오검출 의심 → 기본 off.** 실제 2마리 케이지 카메라에서만 on |
| `visible_long` | `visible_sec / duration` | 오래 화면에 있음 | 단독으론 약함(정지 게코). 다른 트리거의 AND 조건으로 |

#### B. 궤적 스칼라 — R2 artifact `track_points`에서 파생, v1 (스칼라 추출 단계 필요)

최근 120개 artifact로 실측한 결과 아래 값들은 활동시간과 상관 r 0.4~0.7이라 **활동시간의 복제가 아니다**. 실제로 "활동시간 2초인데 케이지 절반을 가로지른 영상"(spread 0.52)과 "활동시간 18초인데 이동 반경 거의 0인 영상"(제자리 움직임 또는 jitter)이 갈린다.

| 트리거 후보 | 계산 | 잡으려는 장면 | r(활동시간) |
|---|---|---|---|
| `wide_travel` | bbox 중심의 x·y 범위 넓이(`spread`) | 케이지를 크게 누빔·탐색 | 0.43 |
| `net_move` | 시작 위치 → 끝 위치 거리 | 실제로 자리를 옮김 (제자리 떨림 배제) | 0.45 |
| `fast_dash` | 0.1초 변위 최대값(`vmax`) | 달리기·점프·먹이 포획 순간 | 0.49 |
| `approach_camera` | bbox 넓이 최대/최소 비(`area_ratio`) | 카메라 쪽으로 다가옴·정면 | 0.52 |
| `coverage` | 6×6 칸 중 방문 칸 수 | 넓은 탐색 | 0.64 (중복 큼) |
| `zone_dwell` | 카메라별로 owner가 한 번 그린 구역(쳇바퀴·물그릇·먹이 자리)에 머문 시간 | 쳇바퀴 타기·물 마시기·먹기 — 옛 GT에서 가장 강했던 "쳇바퀴 → 포함 83%"를 위치로 근사 | 구역 그리기 UI 필요, 그릇 위치는 바뀜(메모리) → 쳇바퀴처럼 고정된 것만 |
| `in_place_motion` | 활동시간 높음 AND spread 작음 | 제자리 머리 움직임·핥기 **또는** jitter 오검출 | 트리거보다 **분류 태그**로: 사람이 O/X 어느 쪽으로 가르는지 보고 결정 |

파생 방법 두 가지. ⓐ gecko-vision-gate의 GME 엔진이 run 저장 시 스칼라를 같이 쓴다(cross-repo handoff) ⓑ petcam-lab 쪽 작은 추출기가 permanent artifact를 읽어 `gme_run_highlight_features`(append-only, run_id 키)에 쓴다. **ⓑ 추천** — GME 원장 불변, 이 레포 안에서 끝남, artifact는 영구라 언제든 재계산. 미리보기: `scripts/hl_traj_features_preview.py`.

#### C. 맥락 — 다른 영상·시간과의 관계 (DB만으로, v0 또는 v1)

| 트리거 후보 | 계산 | 잡으려는 장면 |
|---|---|---|
| `camera_relative` | 그 카메라 최근 7밤 활동시간 분포에서 상위 p% | 카메라마다 분포가 달라 절대 임계값이 한쪽 카메라에 편향되는 문제(T1 교훈) 해결. "이 게코 기준으로 유난한 밤" |
| `episode` | 앞뒤 영상(같은 카메라, 시작 간격 ≤ 2분)이 연속으로 활동 | 한 클립을 넘는 큰 사건(긴 탐색·쳇바퀴 장시간). 연속 N개면 모두 O 또는 대표 1개만 O |
| `rare_hour` | 활동 시각이 그 카메라의 평소 활동 시간대 밖(예: 낮) | 최근 표본은 0~5시 집중. 낮 활동은 드물어 "무슨 일?" 가치. 급여·손 개입일 수도 |
| `first_of_night` | 그 밤 첫 O 영상 | "오늘 밤 활동 시작" 알림 가치. 개수 제한 없음이라 우선순위 아닌 태그 |

#### D. 가드 — X로 보내거나 O를 막는 조건 (품질)

| 가드 | 읽는 값 | 이유 |
|---|---|---|
| `camera_shake` | `camera_motion_sec / duration` 높음 | 카메라 흔들림이 움직임으로 셈 |
| `unstable_track` | `fragmentation_count`·`detection_gap_count` 높음 | jitter overcount 사례(정지 게코 18초). **v0엔 안 넣음** — jitter 스펙이 엔진에서 고침. 집계 태그로만 |
| `mostly_unknown` | `unknown_sec / duration` 높음 | 판정 불가 구간이 대부분 |
| `barely_visible` | `visible_sec` 매우 짧음 | 스치듯 지나감 — 사람이 O로 볼지 X로 볼지 첫 주 집계로 |

#### 제안 순서

- **v0 (지금, DB만):** `long_activity` + `sustained_move` on. `frequent_bursts`·`early_action`·`camera_relative`·`rare_hour`는 **off 상태로 params에 넣고 근거 문구엔 값만 표시** → 첫 주에 "켰다면 O였을 영상"을 집계로 미리 본다(shadow trigger).
- **v1 (궤적 추출기 뒤):** `wide_travel`·`net_move`·`fast_dash`·`approach_camera` shadow → 유지율 보고 on.
- **v2:** `zone_dwell`(쳇바퀴 구역 그리기), `episode`.
- 트리거는 언제나 OR, 가드는 AND-NOT. 숫자·on/off만 바뀌고 함수 코드는 안 바뀐다.

### 4.2 저장 — 1차 판정은 저장하지 않고 계산한다

1차 판정은 (규칙 파라미터, GME run 숫자)의 순수 함수다. 둘 다 이미 append-only로 저장돼 있으니 **결과를 또 저장할 이유가 없다.** 사람이 확정하는 순간에만 "그때 보였던 값"을 verdict row에 스냅샷한다. 워커도 필요 없다 — GME run이 append되면 함수 결과가 바로 바뀐다.

`highlight_rule_versions` (append-only)

| 컬럼 | 뜻 |
|---|---|
| `version` text PK | `hl-rule-v0`, `hl-rule-v1` … |
| `params` jsonb | `{triggers:[{name,on,...숫자}], guards:[...]}` (§4.1a 구조) |
| `note` text | 왜 바꿨나 한 줄 |
| `created_at`, `created_by` | — |

`highlight_rule_activation_events` (append-only): `version, activated_at, actor` — 현재 active = 최신 row. (2026-08-10 model activation event 패턴)

`motion_clip_highlight_verdicts` (append-only)

| 컬럼 | 뜻 |
|---|---|
| `clip_id`, `reviewer_id`, `created_at` | — |
| `rule_version`, `gme_run_id`, `initial` boolean, `initial_reason` | 확정 시점에 화면에 보였던 1차 판정 스냅샷 |
| `verdict` boolean | **최종값** |
| `changed` boolean | `verdict != initial` |
| `change_reason` text null | `오검출 / 게코 안 보임 / 카메라 흔들림 / 움직임 짧음(구 '너무 짧음') / 재밌는데 숫자 낮음 / 기타` |

"라벨링됨" = 그 영상에 verdict row가 1개 이상. 첫 확정이 최종이며 같은 영상의 두 번째 확정은 원칙적으로 만들지 않는다(v4 스펙에서 잠금). owner 정정은 새 row append(`superseded` 표시), 원본 유지.

`fn_highlight_current(clip_id)` 반환: `{value: O|X|pending, source: human|rule, rule_version, reason}`. 소비처(v4 화면, 훗날 앱 API)는 이 함수만 읽는다.

### 4.3 규칙 조정 루프

```
규칙 vN (active) → 검수자 확정 → 주간 집계(유지율 · O→X / X→O · 사유 · 카메라별)
   → 논의 → params 조정 → 규칙 vN+1 append + activation event → 다음 주 같은 표
```

- 연구 실험이 아니라 운영 튜닝이므로 TEST-SHEET는 요구하지 않는다. 대신 버전·params·집계·활성화 시각은 전부 원장에 남아 언제든 감사한다.
- 유지율 목표치는 첫 사이클 뒤에 정한다. 첫 주는 분포를 보는 게 목적.
- 규칙 변경으로 과거 verdict를 재계산하거나 바꾸지 않는다. 옛 확정은 옛 규칙 스냅샷과 함께 남는다.

### 4.4 한 가지 경고 (한 번만)

1차 판정을 보고 확정하면 사람이 그 값에 끌린다(앵커링). 유지율이 높아도 "규칙이 맞아서"인지 "사람이 안 고쳐서"인지 구분이 안 된다. owner가 각자 결과 100% 신뢰로 정했으니 이 방식으로 간다. 주간 리뷰에서 **그대로 유지된 것 중 무작위 몇 개**를 같이 다시 보는 걸 권한다. 진행을 막는 조건은 아니다.

### 4.5 기존 구조와의 관계

- 2026-08-22 설계 §6 "하이라이트 후보 순위에 GME 활동량, 단독 확정 없음"은 이 결정으로 바뀐다: **GME 규칙이 1차 확정을 한다.** 사람이 덮을 수 있으므로 "최종 확정"은 아니지만 "후보 순위"보다 강하다. SOT(`petcam-ai-pipeline.md` 하이라이트 정책)에 반영 필요.
- 옛 교차검증 GT의 `highlight_recommendation`(3-class, 301건)은 옛 기준의 값이라 이 규칙 채점에 쓰지 않는다. 데이터는 보존.
- `/clips/highlights`(이 레포)의 클래스 기반 계약은 그대로. 나중에 `fn_highlight_current`로 교체하는 건 별도 스펙.

## 5. 유저 체험 시뮬레이션

화면 자체는 v4 스펙이 정본. 여기선 하이라이트 판정이 어떻게 보이는지만.

`[화면]` 영상 카드마다 `하이라이트 O` / `X` / `분석 대기` 배지. O 배지 옆에 `12.4초 · 최장 6.1초`
→ `[조작]` 영상을 연다. 위에 `1차 판정: O — 움직임 12.4초, 최장 연속 6.1초`. 버튼 둘: `O 확정` / `X 확정`. 1차 판정 쪽이 살짝 강조
→ `[반응]` `O 확정` 탭 → 저장 → 다음 영상. `X 확정`이면 사유 칩 한 줄(선택) → 저장
→ `[감정]` "판단"이 아니라 "확인"이라 빠르다. 숫자가 보여서 기준을 몸으로 익힌다.

Owner 주간 리뷰: `규칙 v0 · 확정 412 · 유지율 74% · O→X 31(사유 1위 오검출) · X→O 12 · 카메라별` 표 → "10초는 낮다, 12초로" → v1 저장 → 다음 주 비교.

## 6. 학습 노트

- **계산 가능한 건 저장하지 않는다:** 1차 판정 = f(params, run). 입력이 둘 다 불변 원장이면 결과 테이블은 중복이다. 스냅샷은 사람이 결정한 순간에만.
- **파라미터 버전 + activation event:** 코드 배포 없이 규칙을 바꾸고, "그때 뭐가 active였지?"를 되짚을 수 있다.
- **임계값 vs top-N:** 임계값은 기준을 고정하고 개수가 흔들린다. owner는 기준 고정을 골랐다.
- **앵커링:** 초기값을 보여주는 방식의 대가. 무작위 재확인으로 일부 상쇄.

## 7. 참고

- 결정 로그: `docs/decision-gate.md` 2026-09-07 1차(supersede)·2차(supersede)·3차
- 활동시간 overcount: `specs/experiment-gme-jitter-overcount-mitigation.md`
- append-only·activation event 패턴: `docs/superpowers/specs/2026-08-10-yolo-demo-team-contribution-design.md`, `2026-09-03-gme-observed-moving-time-metric-design.md`
- 분포 스크립트: `scripts/hl_rule_preview.py` (SELECT-only)
