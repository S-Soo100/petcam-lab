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

**용어 — 3계층은 내부적으로 합치지 않는다:** ① presence evidence: present / absent / uncertain
② activity evidence: active / static / uncertain ③ **product outcome: include / exclude / unknown.**
absent 와 static 은 **product outcome=exclude 에서만** 합쳐진다. Gate evidence 와 DB `reason_code` 는 계속 분리 보존한다.

- v1 튜닝/선정에 **사용하지 않은** 신규 24 clip(`activity-safety-holdout-0714/`, **튜닝데이터 겹침 0**),
  438 clip 스캔 선정. detector(v1) exclude_static **12**(카메라 A) + exclude_absent **12**(카메라 B).
- 사람 blind 검수: **제외 22 + active 2**.

### 스위치별 safety 판정
- **exclude_absent → reject**: detector absent 12 중 **human=active 2건**(0180442f·877f6dad, 카메라 B, no_gecko).
  threshold 0.10 에서도 게코를 놓친 실제 활동 clip = false exclusion → reject(지시문 "1건이라도").
- **exclude_static → active 오제외 0**: detector static 12(카메라 A) 전부 human=제외. (아래 두 결함으로 adopt 근거는 안 됨.)

### ⚠️ 사람 검수 질문의 결함 (라벨 정의 정정)
- **정정**: static 12건은 프레임에 **게코가 실제로 보인다**(presence=present). human 이 적은 "Absent" 는 문자 그대로
  "게코 없음"이 아니라 **product outcome = "활동시간에서 제외"** 의미다.
- 원인: **사람 검수 질문이 presence(게코 유무)와 product outcome(제외/포함)을 한 칸에 혼합**했다.
  ("owner 가 absent/static 을 구분 못 한다"는 이전 표현은 **삭제** — owner 인지 문제가 아니라 질문 설계 결함이다.)
- 다음 holdout 은 질문을 분리한다(§13).

### ⚠️ static safety 표본 독립성 부족
- static 12건 중 **11건이 카메라 A 의 2026-07-14 07:22~07:41 UTC(19분)에 몰려** 사실상 **하나의 연속 정지 에피소드**다
  (+02:53 1건 = **effective episode ≈ 2**). 12/12 를 독립 표본처럼 해석하면 안 된다 → exclude_static 실질 표본은 매우 작다.

## 11. utility 표본 — 무작위·strata, detector-only (potential upper bound)

detector(v1)로 균형 맞추지 않은 무작위 표본(seed 714), 카메라 × 주/야(KST IR) strata. **사람 GT 없음** → 아래 수치는
전부 **potential upper bound**(실제 절감은 §10 safety 반영 시 더 작음). 삭제된 R2(404) skip.

| 카메라 | 주야 | 모수 clip | 표본 | static | absent | active | unknown | excl%(upper) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| A(5b3ea7aa) | day | 4962 | 25 | 4 | 2 | 6 | 13 | 24% |
| A | night | 4897 | 25 | 5 | 1 | 9 | 10 | 24% |
| B(f6599924) | day | 116 | 14 | 0 | 5 | 0 | 9 | 41% |
| B | night | 664 | 25 | 1 | 16 | 1 | 7 | 68% |
| C(90119209) | day | 34 | 4 | 0 | 0 | 0 | 4 | 0% |

**카메라별 우선(표본 exclude율, static/absent 분리):**
- **A**: exclude 24% = **static 18% + absent 6%**(게코 상주). unknown 40~52%. → "A static 24%"는 오기(absent 3건 포함).
- **B**: exclude 56% = static 3% + **absent 54%**(게코 자주 부재).
- **C**: 0%(표본 4·모수 34 로 과소 — 판단 불가).

**전체 추정(가중, upper bound):** 표본 단순합 36% 는 stratum clip 수를 무시한 값 → **운영 추정치 아님**.
- **클립 수 기준 upper bound = 27.1%**(A 가 clip 9859 로 지배). **활동시간 지표의 운영 추정은 `duration_sec` 가중**으로
  내야 하며, 표본 duration 가중 결과도 **≈27.0%**(static 16.9% + absent 9.9%)로 clip 수 가중과 근사하다.
- ⚠️ **static/absent 별 duration 을 저장하지 않았으므로** 위 static 16.9% + absent 9.9% 분리치는 **클립 수 기준 근사치**다.
  → **다음 utility 스크립트는 decision 별 clip count 뿐 아니라 `raw_duration_sec`·`excluded_duration_sec` 를 각각 저장**한다.
- 모두 **detector-only = potential upper bound**(사람 GT 아님). **exclude_absent 가 reject** 이므로 실현 가능 절감은
  exclude_static(≈17% upper bound, 대부분 카메라 A)뿐이고, §10(사람 GT·독립 에피소드) 검증 전에는 확정 불가.

## 12. 종합 판정 (fresh safety + utility)
- **exclude_absent: REJECT** — fresh safety FE 2(카메라 B, threshold 0.10 도 게코 놓침 = detector recall 잔존).
- **exclude_static: CANARY(HOLD 유지)** — active 오제외 0 이나 **effective episode ≈2** + 사람 질문 결함으로 정식 adopt는 불가하다. 사용자 결정으로 테스트 카메라 A 한 대에만 가역 canary를 켰다.
- settings는 **3대 enabled=true · 전부 exclude_absent=false · 카메라 A만 exclude_static=true · active_policy_version=activity-v1**이다. 다른 두 카메라와 미래 신규 카메라는 자동 확대하지 않는다.
- **실행 순서(A~C 완료 · D 진행 중):** **A** policy-version guard ✅ · **B** 세 레포 main fast-forward 통합·push ✅
  (gate `89237a5`·nightly `e4e7cc6`·lab main) · **C** shadow-only 가동 ✅(settings + launchd `com.petcam.activity-worker` 3600s·env `ACTIVITY_POLICY_VERSION=activity-v1`) ·
  **D evidence 축적 진행 중** → **제한 canary** 카메라 A static-only 활성(정식 G 통과가 아니라 위험 수용 실험) →
  **E** 30분 episode dedup 독립 static ≥20 선정 → **F** 사람 blind 검수 → FE가 1건이라도 나오면 즉시 rollback, 0일 때만 정식 제한 채택 검토.
- exclude_absent 계속 **REJECT**, exclude_static은 **canary 중이지만 채택 판정은 HOLD**다. Gate v3 backlog §15.

## 13. fresh holdout selector 설계 (E 단계, 미실행 — 설계만)
- **에피소드 dedup**: 동일 카메라에서 **30분 이내 clip 은 한 에피소드로 묶고 1개만** 선택(연속 정지 중복 제거).
- **다양성 우선**: 서로 다른 **날짜·시간대·게코 위치/자세**. 가능하면 **주간/야간 strata 분리**.
- **목표**: exclude_static 후보 **최소 20개 독립 에피소드**(exclude_absent 후보도 카메라·시간대 넓혀 독립 ≥20).
- **사람 질문 2단 분리**: ① 먼저 **product outcome = include / exclude / unclear** ② 별도 진단으로
  **presence = present / absent / uncertain** 과 **activity = active / static / uncertain** 을 각각 기록.
- Claude/VLM 판정을 GT 로 쓰지 않는다. 기존 30·safety 24 재사용 금지(새 fresh).

## 14. 운영 단계 — shadow 축적 + 카메라 A static-only canary (2026-07-14~)
worker는 세 테스트 카메라의 evidence(`clip_prelabels`)+판정(`clip_activity_assessments`)을 계속 쌓는다. 제품 차감은 카메라 A의 `exclude_static`에만 제한한다.

### shadow 설정값 (적용됨)
- **launchd 환경변수**: `ACTIVITY_POLICY_VERSION=activity-v1`(config 기본 activity-v0 를 바꾸지 않고 launchd 에서 명시 override).
- **DB `camera_activity_filter_settings`(3대 적용)**: `enabled=true, exclude_absent_enabled=false, active_policy_version='activity-v1'`. `exclude_static_enabled=true`는 카메라 A 한 대뿐이고 다른 두 대는 false다.
- **launchd `com.petcam.activity-worker`**: StartInterval 3600·RunAtLoad·WorkingDirectory=nightly main. 미분석·unknown·disabled reason은 raw를 유지한다.
- **Flutter**: main `2e4fced`(`v0.20.1+35`, 기능 `b4db4dc`)에서 홈·상세·리포트가 effective view를 사용한다. view PostgREST 오류는 raw query로 fail-open하고, raw까지 실패하면 0으로 숨기지 않고 오류를 표시한다.

### policy-version 정합성 guard (완료)
worker `run()` 에서 enabled camera 의 `active_policy_version` 이 **null 이거나 worker `ACTIVITY_POLICY_VERSION` 과 다르면 그 카메라 skip**(evidence/assessment 미저장·R2 다운로드/추론 미실행), mismatch 로그. 테스트 3케이스 pass(nightly `_filter_by_policy`, main `e4e7cc6`).

### 첫 RunAtLoad 결과 (2026-07-14)
- `cameras=3 queried=200 ok=200 fail=0 · policy=activity-v1 · last exit 0`. decision: exclude_absent 150·active 34·unknown 21.
- DB: assessments **205**(전부 v1·threshold 0.10·identity 7컬럼 완전), **exclusions 0·effective==raw**(실제 차감 없음), 임시 mp4 0·로그 비밀값 0.
- 운영 메모: **PyTorch TracerWarning 은 RF-DETR 로딩 경고**이며 성공 판정의 blocker 아님(경고 suppression 코드 변경 안 함).

### 검증 절차 (지속)
- (1) ✅ 첫 RunAtLoad 후 `effective==raw`·exclusions=0 재확인 (이후 주기적 재확인)
- (2) ✅ iPhone 17 simulator에서 홈 `어제 추정 활동시간`, 카메라 상세 오늘/어제, 어젯밤 리포트 `추정 활동` 렌더를 확인했다.
- (3) ✅ 카메라 A static-only 활성 직후 어제 `8h 50m → 8h 45m`; static 10 clip·320.4초 차감, static zero 위반 0, absent raw 유지 위반 0을 확인했다.
- (4) **진행 예정(E~F)**: §13 기준 독립 에피소드 사람 GT와 대조한다. false exclusion 1건이면 즉시 static 스위치를 false로 rollback한다.
- ⚠️ `exclude_absent`는 계속 false다. 다른 카메라 확장·VLM skip·행동 확정·Gate v3 배포로 해석하지 않는다.

## 15. Gate v3 backlog (분리 기록)
- **detector recall hardcase**: 카메라 B 의 active 를 absent 로 놓친 2건(0180442f·877f6dad). threshold 0.10 도 미검출.
- **static activity calibration**: 카메라 A visible-static 에피소드(07-14 07:22~07:41 UTC). 게코 보이나 활동 없음 경계.
- ⚠️ Gate v3 를 소외시키지 않는다(타 카메라/개체 일반화·segment-level 활동엔 여전히 필요).
  **product exclude 라벨을 detector GT 로 사용하지 않는다**(product outcome ≠ presence evidence).

## 16. 운영 신뢰 계약 — 무엇을 켰고 무엇을 아직 믿지 않는가

### 활성화·검증됨
- Mac mini LaunchAgent가 테스트 카메라 3대의 최근 clip을 1시간마다 `activity-v1`으로 분석한다.
- Claude/VLM 호출 없이 Gate evidence와 four-state assessment를 provenance 7컬럼과 함께 저장한다.
- policy-version 불일치·불확실·처리 실패는 자동 차감으로 이어지지 않는다.
- 첫 RunAtLoad 200/200 성공, assessment baseline 205건 전부 v1, 임시 mp4 0건을 확인했다.
- Flutter가 effective view를 활동시간 정본으로 사용한다. 카메라 A의 static-only canary에서 10 clip·320.4초 차감과 앱 `8h 50m → 8h 45m` 반영을 확인했다.
- absent는 전 카메라에서 false이고 다른 두 카메라의 static도 false다.

### 비활성·미증명
- `exclude_absent`는 active false exclusion 2/12 때문에 **REJECT**다.
- `exclude_static`은 카메라 A에서 canary 중이지만, fresh 표본의 effective episode가 약 2개라 정식 판정은 여전히 **HOLD**다.
- Gate 결과로 행동을 확정하거나 VLM 호출을 skip하지 않는다. clip 내부 실제 활동 초를 계산하는 segment-level 기능도 아니다.

### 다음 승격 조건
최소 3개 날짜를 축적하고, 동일 카메라 30분 이내 clip을 한 에피소드로 dedup한 뒤 독립 static 후보 20개 이상을 사람 blind 검수한다. `include` 영상을 `exclude`로 보내는 false exclusion이 1건이라도 나오면 canary를 즉시 끈다. 0일 때만 카메라 A 제한 채택을 검토한다. absent 제외와 미검증 카메라 자동 확장은 계속 금지한다.
