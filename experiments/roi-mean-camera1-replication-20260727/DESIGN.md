# Camera 1 raw roi_mean future replication 설계

**상태:** `DESIGN_APPROVED_PENDING_WRITTEN_REVIEW`  
**설계 승인:** 2026-07-27, owner가 대화에서 연구 시작 승인  
**선행 결과:** [`../owner-gt-python-evidence-benchmark-20260727/REPORT.md`](../owner-gt-python-evidence-benchmark-20260727/REPORT.md)  
**성격:** future camera-night replication holdout. normalization 개발 실험이 아님.

## 1. 연구 질문

선행 retrospective benchmark에서 camera_1의 raw `motion_summary.roi_mean` AUROC는 `0.4832`였어.
하지만 static-only가 7건뿐이라 아래 두 원인을 구분할 수 없었어.

1. raw `roi_mean`이 camera_1에서는 실제로 움직임 신호가 아니다.
2. static-only 7건과 episode 편향 때문에 우연히 방향성이 사라졌다.

이번 연구는 다음 한 질문만 검증해.

> 동결 이후 camera_1의 새로운 camera-night에서 raw `roi_mean`이 moving과 static-only를
> 높은 값=moving 방향으로 구분하는가?

## 2. 최종 소비처

이 연구는 selector를 구현하지 않아. 결과의 소비처는 다음 연구 방향 결정뿐이야.

- 재현 성공: raw `roi_mean`을 두 camera future 비교의 후보로 유지
- 재현 실패: raw `roi_mean`을 공통 selector 후보에서 폐기
- 불확실: 계약을 바꾸지 않고 future camera-night를 추가 수집

재현 실패가 나와도 normalization 연구가 자동 승인되지는 않아. normalization은 별도
decision gate와 dev/future holdout 분리가 필요해.

## 3. 검토한 접근

### A. camera_1 future replication — 채택

- 동결 이후 영상만 사용해 기존 7건을 섞지 않아.
- raw feature와 방향을 그대로 유지하므로 사후 튜닝이 없어.
- 표본 부족과 camera-specific failure를 직접 구분할 수 있어.

### B. 즉시 camera normalization — 보류

- 현재 172건 결과를 본 뒤 보정식을 고르면 과적합 위험이 커.
- normalization 후보를 만들 dev data와 평가할 future holdout이 분리돼 있지 않아.

### C. 여러 Evidence feature 합성 — 기각

- 연구 질문이 커지고 어느 feature가 효과를 냈는지 분리할 수 없어.
- 과거 T1의 합성점수 기각 이력을 반복할 위험이 있어.

## 4. Decision gate

공유 `docs/decision-gate.md`는 이 전용 연구 설계에서 수정하지 않아.

| Gate | 판정 | 근거 |
|---|---|---|
| G1 SOT 부합 | ✓ | RBA Data Engine v1의 future camera-night·사람 GT·camera diversity 우선순위와 맞아. |
| G2 기대효과 | ✓ | raw motion signal의 camera 일반화 실패 원인을 표본 부족과 실제 실패로 분리해. |
| G3 측정가능 | ✓ | future cutoff, GT class, episode, feature 방향, AUROC/CI, 판정 규칙을 사전 동결해. |
| G4 유효한 계획 | ✓ | 기존 서비스가 생산하는 GT/Evidence를 SELECT-only로 관찰하고 production 변경을 금지해. |

**판정:** future replication 설계 진행. selector·normalization·production adoption gate는 열지 않아.

## 5. Camera와 시간 경계

### 5.1 camera_1 정의

tracked 파일에 camera UUID를 쓰지 않아. target camera는 선행 benchmark SQL의 동일 deterministic
규칙으로 다시 찾는다.

```text
Owner eligible cohort의 camera_id를 정렬
→ dense_rank = 1인 camera
→ 선행 snapshot에서 71건이었던 camera_1
```

재계산 결과가 target 1대 또는 선행 71건과 다르면
`ROI_REPLICATION_HOLD_CAMERA_IDENTITY_DRIFT`로 중단해.

### 5.2 Future cutoff

TEST-SHEET를 commit한 뒤 production DB `now()`를 한 번 SELECT해 `future_cutoff_utc`로 고정해.
eligible clip은 `motion_clips.started_at > future_cutoff_utc`여야 해.

- cutoff 이전 172건과 camera_1 기존 7 static-only는 표본 수에 포함하지 않아.
- cutoff와 sample manifest는 결과 분석 전에 고정해.
- 결과를 본 뒤 cutoff를 앞당기거나 clip을 제외하지 않아.

## 6. 사람 GT와 Evidence eligibility

각 clip은 아래를 모두 만족해야 해.

```text
target camera_1
AND started_at > future_cutoff_utc
AND Owner identity가 reviewed_by
AND labeling stage = completed
AND initial_gt/current_gt/completed_at IS NOT NULL
AND Python Evidence run 정확히 1개
AND level0_status = ok
AND level1_status = ok
AND roi_mean finite
AND frozen Evidence provenance contract 일치
```

사람 GT는 Evidence·Gate·VLM 결과를 보기 전에 잠긴 `initial_gt`를 class 정의에 사용해.
revision이 생기면 provenance로 보고하되 class는 initial GT를 유지해 결과를 본 뒤 정답이 바뀌는
누출을 막아.

### Class

- positive: `initial_gt.observed_actions`에 `moving` 포함
- negative: `static` 포함 AND `moving` 미포함
- 나머지: 기술 coverage에는 보고하지만 primary AUROC에서는 제외
- positive와 negative overlap은 0이어야 해

## 7. 표본과 episode

### Minimum analysis sample

- moving clips ≥30
- static-only clips ≥30
- moving 5분 episodes ≥20
- static-only 5분 episodes ≥20
- camera-nights ≥3
- 각 class가 최소 2개 camera-night에 존재

같은 camera에서 연속 clip 시작 간격이 5분 이하면 같은 episode로 묶어. clip 30건을 채워도
episode 조건이 부족하면 계속 수집해.

표본이 차기 전에는 coverage dashboard만 볼 수 있어. class별 `roi_mean` 분포, AUROC, CI,
극단값은 sample lock 전 계산하거나 노출하지 않아.

## 8. Frozen feature와 통계

### Primary

- feature: `motion_summary.roi_mean`
- direction: higher = moving
- metric: raw AUROC
- inference unit: clip
- uncertainty unit: 5분 episode-cluster bootstrap
- bootstrap iterations: 10,000
- seed: `20260727`
- interval: percentile 95% CI

### Required diagnostics

- non-null/finite coverage
- L0/L1 success와 provenance contract count
- moving/static-only clip·episode·camera-night 수
- class별 median/IQR
- Hodges–Lehmann moving−static location difference
- camera-night별 median/IQR
- bootstrap invalid replicate rate

### 금지

- direction 반전
- `max(AUC, 1-AUC)`
- threshold sweep
- normalization
- duration correction
- feature 조합·weight
- classifier fitting
- sample lock 뒤 제외·교체

## 9. 판정

sample minimum을 모두 충족한 뒤 정확히 하나로 판정해.

- `ROI_CAMERA1_REPLICATION_SUPPORTED`
  - primary coverage ≥95%
  - AUROC lower 95% CI >0.50
  - valid bootstrap ≥95%
- `ROI_CAMERA1_REPLICATION_REJECTED`
  - primary coverage <80% 또는 AUROC upper 95% CI ≤0.50
- `ROI_CAMERA1_REPLICATION_INCONCLUSIVE`
  - minimum sample은 충족했지만 CI가 0.50을 포함하거나 valid bootstrap <95%
- `ROI_CAMERA1_REPLICATION_COLLECTING`
  - minimum clip/episode/camera-night 미충족
- `ROI_CAMERA1_REPLICATION_HOLD_<REASON>`
  - camera identity, cutoff, GT/Evidence provenance, read-only, mutation 계약 위반

`SUPPORTED`여도 production 채택 승인이 아니야. 그다음 두 camera future comparison
TEST-SHEET를 작성할 근거만 생겨.

## 10. 데이터 흐름과 artifact

전용 경로는 `experiments/roi-mean-camera1-replication-20260727/`야.

```text
DESIGN.md
TEST-SHEET.md
collection-status.sql
freeze-manifest.sql
analyze.py
verify_results.py
test_analyze.py
collection-status.json
sample-manifest.json
summary.json
REPORT.md
```

진행 중:

```text
production DB SELECT
→ class count + episode count + camera-night count만 확인
→ minimum 미달이면 COLLECTING
```

표본 충족 후:

```text
sample manifest lock
→ 익명 feature snapshot
→ frozen analysis
→ independent verification
→ REPORT
```

tracked artifact에 clip/camera/user UUID, 메모, URL, R2 key, 이메일을 저장하지 않아.

## 11. Mutation과 운영 경계

- production DB SELECT-only
- R2 접근 없음
- labeling web/API/migration 변경 없음
- Owner·labeler workflow 변경 없음
- Python Evidence·Gate·VLM 재실행 없음
- selector·activity filter·자동 skip 변경 없음
- LaunchAgent·runtime·deploy 변경 없음

collection은 기존 서비스가 자연스럽게 생산하는 미래 GT와 Evidence를 관찰하는 것이며, 연구를
위해 production 라벨이나 영상을 수정하지 않아.

## 12. 검증

- target camera identity 독립 재계산
- cutoff 이후 clip만 포함됐는지 assertion
- label partition overlap 0
- clip/episode/camera-night minimum assertion
- evidence run 1개와 provenance 일치
- 분석기와 독립 verifier의 AUROC·CI·verdict 동일
- 시작/종료 source fingerprint 동일
- tracked raw identifier 0
- 실험 테스트와 전체 프로젝트 테스트

## 13. 완료와 중간 상태

현재 연구를 “시작”한다는 뜻은 TEST-SHEET와 cutoff를 동결하고 collection status를 측정하는
것이야. future GT가 아직 부족하면 정상 verdict는 `ROI_CAMERA1_REPLICATION_COLLECTING`이야.

최종 완료는 minimum sample lock 뒤 `SUPPORTED / REJECTED / INCONCLUSIVE` 중 하나를 낸
시점이야. COLLECTING 동안 결과를 추측하거나 normalization 연구로 건너뛰지 않아.
