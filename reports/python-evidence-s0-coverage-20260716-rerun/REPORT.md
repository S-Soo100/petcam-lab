# Python Evidence Hybrid — S0 Coverage Audit REPORT

- snapshot_id: `a57f1c3d9f91f5b3`
- as_of: `2026-07-17T00:14:57+09:00` (KST) / `2026-07-16T15:14:57+00:00` (UTC)
- start: `2026-07-14T00:00:00+09:00` (KST) / `2026-07-13T15:00:00+00:00` (UTC)
- policy_version: `activity-v1` · regular selector: `budget-router-v1`
- petcam-lab HEAD: `93c719f67d0f`

## 판정: **S0_PASS_WITH_COVERAGE_GAP**

coverage gap:
- policy_ready_below_80:90119209:0.7

## 재고 / 현재정책 coverage

- total_eligible motion clips: **2942**
- any_prelabel clips: **2889**
- policy_ready (`activity-v1` + 유효 prelabel 참조): **2889**
- core_complete (policy_ready 중 필수 evidence 완비): **2889**

### 0% coverage 카메라/날짜 strata
- `f6599924` 2026-07-14: eligible 25, prelabel 0

## selector 시점 coverage (정규/backfill 분리)

- 정규(`budget-router-v1`) run: **10**, backfill run: **71**
- **exact** = `clip_vlm_jobs` FK(prelabel_id/activity_assessment_id) 로 선택 결과에 실제 연결된 evidence.
- **estimate** = run window `[window_start, window_end)` 안 motion clip 중 `prelabel.created_at <= run.created_at` 비율(복원 근사치).
- **not_reconstructable** = episode reduction·제외 전 eligible pool 의 clip 단위 snapshot 은 저장되지 않아 정확 pool 을 복원하지 않는다.

## S1 권고 (범위 한정)

- S0_PASS_WITH_COVERAGE_GAP: S1 은 아래 covered subset 으로만 진행하고 전체 카메라/기간으로 일반화 금지.
  - covered subset(policy_ready≥80%): ['5b3ea7aa', 'f6599924']

본 감사는 read-only 다. selector/threshold/자동제외/행동라벨/앱 활동시간을 변경하지 않았다.

