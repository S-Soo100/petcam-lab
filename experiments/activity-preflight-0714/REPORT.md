# REPORT — 활동필터 v0 사람 preflight (activity-preflight-0714)

> 실행 2026-07-14. §1~7 은 **0.25 기준 원본(보존, 사후 변경 없음)**. 카메라 A blind 30 clip,
> 사람 동영상 판단 vs detector(Gate v2 EMA, thr 0.25, policy activity-v0).
> ⚠️ **§8 사후 threshold audit 로 §5(A)의 "detector FN → Gate v3 선결" 결론은 철회** —
> exclude_absent 실패는 detector recall 이 아니라 **threshold 0.25 가 conf 0.14~0.21 검출을 걸러낸 것**
> (0.10 에서 FE_absent 0/10 회복). 활성화 보류 자체는 유지하되 사유가 바뀐다(Gate v3 선결 아님).

## 1. 결과 표

| 지표 | 값 | 합격기준 | 판정 |
|---|---|---|---|
| false exclusion → exclude_absent | **10건** | 0 | ❌ |
| false exclusion → exclude_static | **1건** | 0 | ❌ |
| exclude_absent precision | **0%** (0/10) | ≥90% | ❌ |
| exclude_static precision | 90% (9/10) | ≥90% | ⚠️(false excl 때문에 무의미) |
| active recall(참고) | 39% (7/18) | — | 낮음 |

분포: detector {exclude_absent 10, exclude_static 10, active 10} · 사람 {static 12, active 18, **absent 0**}.

## 2. 시험지 대비
- sample 목표 absent/static/active = 10/10/10 **달성**(85 clip 스캔). 사후 변경 없음.
- 단 사람 판단 결과 **absent 0건** — detector 가 absent 로 뽑은 10개를 사람은 전부 active(9)/… 로 봄.

## 3. 가설 판정
- **H1 기각, H0 유지.** 사람=active 를 detector 가 exclude 로 판정한 경우가 11건(absent 10 + static 1).
  fail-open 이 지켜지지 않아 활동시간을 잘못 깎는다.

## 4. decision label
- **exclude_absent 스위치 = `reject`** (Phase 5 활성화 금지).
- **exclude_static 스위치 = `reject`** (Phase 5 활성화 금지).
- 결과적으로 카메라 A 는 두 스위치 모두 비활성 유지 → 앱 활동시간은 raw(현행) 유지.

## 5. discordant 분석 (근본 원인)

### (A) exclude_absent 전멸 — detector FN (게코 검출 실패) 10/10
`no_gecko_detected`(vr=0.0 = 12프레임 전부 gecko 미검출)한 10개를 사람은 전부 **active**로 판단.
→ **RF-DETR v2 가 이 clip 들에서 게코를 아예 못 잡음.** glob 1.1~1.6(움직임 있음)인데도 bbox 0.
- 이것은 policy/임계값 문제가 아니라 **detector recall 문제**. threshold 를 낮춰도 bbox 자체가 0이라 회복 불가.
- gate-v3.md 경고("petcam backlog specificity 40%, FN 후보")와 §435 금지("gecko_visible=false 무조건 제외 금지")가 실증됨.
- **exclude_absent 는 Gate detector recall 이 사람 GT 로 검증되기 전까지 절대 켜면 안 된다.**

### (B) exclude_static — 미세 움직임 1건 놓침
`7cebd236`: vr=0.92(게코 잘 보임), disp=0.0028, iou=0.94, flow=0.525 → 수치상 거의 정지인데 사람은 active.
미세 혀·머리 움직임이 roi_flow(임계 2.0) 아래라 static 으로 판정. exclude_static 은 검출은 되지만
**미세 활동 민감도가 부족**해 활동 clip 1건을 정지로 오판.

### (C) 반대 방향(무해): static→active 과탐 3건
`ef5c8bd5·9404fb88·cd53ee20`: 사람 static 인데 detector active (iou 0.80~0.84 < move_iou_max 0.85).
detection bbox 노이즈로 active 과탐. **활동시간 포함 방향이라 무해**(false exclusion 아님)지만
move_iou_max 가 bbox 지터에 민감함을 시사.

## 6. 한계·노이즈
- 30 clip 단일 카메라·단일 판단자(owner) blind. 통계적 표본은 작음.
- 그러나 exclude_absent 10/10 실패는 명백한 신호(우연 아님) — detector FN 이 지배적.

## 7. 다음 액션
1. **Phase 5 제한적 활성화 취소** — 두 스위치 다 켜지 않는다. 앱 활동시간 raw 유지(변화 없음).
2. **evidence 축적은 계속** — worker shadow 저장으로 clip_prelabels/assessments 데이터 확보(FN 사례가 Gate v3 재학습 골드).
3. **exclude_absent 재도전 전제** = Gate detector recall 을 사람 GT 로 재검증(gate-v3 재학습). v0 범위 밖.
4. **exclude_static 재도전 전제** = 미세 움직임 민감도(roi_flow/추가 신호) 튜닝 후 재-preflight. 단 (A)가 더 큰 병목.
5. 이번 FN 10건 clip_id 를 Gate hardcase 후보로 gecko-vision-gate 에 기록(별도).

**결론(§1~7, 0.25 원본):** v0 파이프라인은 완성·검증됐고, preflight 안전장치가 잘못된 활동시간 삭감을
사전 차단했다. 0.25 기준으로는 어느 스위치도 안전하지 않다. ⚠️ **단 "detector 개선(Gate v3)이 선결"이라는
판단은 §8 에서 철회됨** — 실제 원인은 threshold 였다.

---

## 8. 사후 threshold audit + static 민감도 분석 (2026-07-14 추가, §1~7 원본 보존)

### 8-1. threshold curve (같은 30 clip·사람 GT 고정, detector threshold 만 변화)
| threshold | FE_absent | FE_static | prec_absent | prec_static | active_recall | det_absent |
|---|---|---|---|---|---|---|
| 0.25 (원본) | 10 | 1 | 0% | 90% | 39% | 10 |
| 0.20 | 9 | 1 | 0% | 90% | 39% | 9 |
| 0.15 | 2 | 1 | 0% | 90% | 56% | 2 |
| **0.10** | **0** | 1 | n/a | 90% | **94%** | 0 |
| 0.05 | 0 | 1 | n/a | 90% | 94% | 0 |

- 0.25 exclude_absent 10개의 회복 gecko conf = **0.142~0.211** → 0.25 가 이 검출을 통째로 걸러낸 것(recall 아님).
- **§5(A) "Gate v3 선결" 철회.** threshold 0.10 로 FE_absent 0, active_recall 94%(17/18).
- ⚠️ **0.10 에서 det_absent=0 이고 human absent=0** → 이 표본으로는 **0.10 의 absent precision/specificity 평가 불가**.
  실제 absent 표본을 새로 blind 확보해야 exclude_absent 를 판정할 수 있다.

### 8-2. exclude_static 민감도 (threshold 무관 1건 FE)
detector static 10개의 roi_flow: 정지 8개 = 0~0.244, **FE 7cebd236 = 0.525(human active)**, 오탐흡수 5a9d6476 = 1.167(human static).
- **flow 역전**: 7cebd236(active, 0.525) < 5a9d6476(static, 1.167) → flow 만으로 완전 분리 불가.
- **튜닝안(activity-v1): roi_flow_active 2.0 → 0.5.** 7cebd236(0.525≥0.5) active 회수 → static FE 0.
  부작용: 5a9d6476(1.167) 도 active(human static, **무해 = 제외 안 함**), 제외량 10→8 감소(사용자 허용).
- 남은 static 8개 precision = 8/8 human static = **100%**.

### 8-3. 결론 수정
- **exclude_absent**: detector 문제 아님(게코를 conf 0.14~0.21 로 검출함). threshold 0.10 재설정 후
  **실제 absent 표본을 새로 blind 확보 → 재판정** 필요(현 표본 human absent=0).
- **exclude_static**: activity-v1(roi_flow_active 0.5)로 튜닝하면 30 표본상 FE 0·precision 100%.
  단 **새 blind preflight 로 재검증** 필요(제외량 감소·flow 역전 리스크).
- **Gate v3 재학습은 카메라 A 의 0.25 FN 엔 선결이 아니다**(threshold 0.10 으로 해결). 단 타 카메라·개체
  일반화와 segment-level 활동 계산에는 여전히 필요(§9). 상세 데이터 `threshold_audit.json`.

---

## 9. activity-v1 판정 (2026-07-14) — 둘 다 **hold (candidate)**, 독립 검증 대기

정책 **activity-v1 = threshold 0.10 + roi_flow_active 0.5**.

### exclude_static → **hold (candidate)**
- 기존 30 clip 사람 GT + v1 재판정: FE 0, precision 100%(8/8 human static), 제외 10→8.
- ⚠️ **resubstitution / data leakage**: roi_flow_active 0.5 를 **실패한 바로 그 30개로 튜닝**하고
  **같은 30개로 재평가**했다. 독립 표본 검증이 아니라 순환논리 → **adopt 근거가 될 수 없다.**

### exclude_absent → **hold (candidate)**
- 새 absent 후보 4건 blind 검수 4/4 absent (FE 0, precision 100%). 방향은 긍정적이나
  ⚠️ **4건뿐 = 원래 최소 10건 기준 미충족** → 판정 불가.
- 후보 수집 `select_absent_v1.py` 는 **motion_score 오름차순 낮은 320개**만 스캔 → 대표표본 아님.
  → **"낮은 motion-score 우선 표본에서 exclude_absent 4건 발견"**으로만 기록(**prevalence 단정 금지**).

### Gate v3 관계 (정정)
- 카메라 A 의 0.25 FN 해결에는 v3 재학습이 **선결 아님**(threshold 0.10 으로 해결됨).
- 단 **타 카메라·개체 일반화**와 **segment-level 활동(초 단위) 계산**에는 v3 가 **계속 필요**.

### 종합
0.25 초기 reject 는 threshold 문제로 규명됐으나, **v1 두 스위치는 튜닝 데이터 재사용(static)·표본 부족(absent)
으로 adopt 불가 = hold.** 독립 safety holdout(§10) + utility(§11) 결과 전까지 두 스위치 **disabled 유지**.
push/merge/launchd/Flutter 보류.

---

## 10. 독립 safety holdout (activity-v1, 튜닝 미사용 fresh 표본) — 결과

- v1 튜닝/선정에 **사용하지 않은** 신규 24 clip(`activity-safety-holdout-0714/`, **튜닝데이터 겹침 0**),
  438 clip 스캔 선정. detector(v1) exclude_static **12**(카메라 A) + exclude_absent **12**(카메라 B).
- 사람 blind 검수 결과: **22 absent + 2 active** (static/unclear 0 — 사용자는 "가만히 있음/너무 작게 보임"도 absent).

### 스위치별 safety 판정
- **exclude_absent → reject**: detector absent 12 중 **human=active 2건**(0180442f·877f6dad, 카메라 B, no_gecko).
  threshold 0.10 에서도 게코를 놓친 실제 활동 clip = false exclusion → reject(지시문 "1건이라도").
- **exclude_static → FE 0**: detector static 12(카메라 A) 전부 human=제외(absent). active 오제외 0.

### ⚠️ 라벨 정의 이슈 (제품 결정 필요, 이 preflight 범위 밖)
- detector static 12 를 human 은 **전부 absent** 로 판단. **사용자(owner)에게 absent 와 static 은 구분되지 않음**
  — 둘 다 "볼 필요 없는(제외)". 멘탈모델은 **제외 vs 포함(active) 이진**이고 static 중간 카테고리가 없다.
- exclude_static/exclude_absent 를 별도 독립 스위치로 둔 설계가 사용자 관점과 불일치. **"제외" 단일 개념으로
  합치거나 재정의**를 제품 SOT(`petcam-*`)에서 결정해야 한다.

## 12. 종합 판정 (fresh safety + utility)
- **exclude_absent: reject** — fresh safety FE 2(카메라 B, threshold 0.10 도 게코 놓침 = recall 잔존).
- **exclude_static: hold (conditional)** — fresh safety FE 0(카메라 A 12), 단 단일 카메라·라벨정의 미정리라 adopt 아님.
- **두 스위치 disabled 유지**(settings 0). utility: 무작위 raw 의 ~36% exclude 가능하나 카메라 편차 큼
  (A 24% / B 68%). 절감의 대부분이 카메라 B 의 absent 인데 그 absent 스위치가 reject → 실질 절감은
  카메라 A static ~24% 로 제한.
- **다음(제품):** (1) SOT 에서 absent/static 통합 여부 결정 (2) exclude_absent 는 카메라 B detector recall
  개선 필요 (3) 활성화 전 카메라별 표본 확대. push/merge/launchd/Flutter·활성화 계속 보류.

## 11. utility 표본 — 무작위·strata, detector v1 판정 분포 + 제거 가능 minutes

detector 로 균형 맞추지 않은 무작위 표본(seed 714), 카메라 × 주/야(KST IR) strata. 판정 = **detector v1 기준 추정**
(사람 GT 아님 — 실제 정확도는 §10). 삭제된 R2(404) skip.

| 카메라 | 주야 | 모수 clip | 표본 | active | static | absent | unknown | raw분 | excl분 | excl% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A(5b3ea7aa) | day | 4962 | 25 | 6 | 4 | 2 | 13 | 13.2 | 3.2 | 24% |
| A | night | 4897 | 25 | 9 | 5 | 1 | 10 | 13.4 | 3.3 | 24% |
| B(f6599924) | day | 116 | 14 | 0 | 0 | 5 | 9 | 6.5 | 2.7 | 41% |
| B | night | 664 | 25 | 1 | 1 | 16 | 7 | 13.4 | 9.1 | 68% |
| C(90119209) | day | 34 | 4 | 0 | 0 | 0 | 4 | 4.0 | 0 | 0% |
| **합** | | | | | | | | **50.5** | **18.3** | **36%** |

- **clip 단위 필터가 무작위 표본 raw 의 ~36% 를 exclude 가능**(detector v1 기준). 단 **카메라 편차 큼**:
  A 24%(게코 상주) vs B 41~68%(게코 자주 부재). C 는 표본 4개(모수 34)로 과소.
- **unknown 비율 높음**(A 40~52%, C 100%) = fail-open. 실제 절감은 이보다 보수적.
- ⚠️ 이 %는 **detector v1 판정 기준 추정**이며 사람 GT 아님 → 실제 절감은 §10 safety precision 반영 필요.


