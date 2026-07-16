# Python Evidence Hybrid — S0 Coverage Audit REPORT

- snapshot_id: `213586c2a3bd6f0c`
- as_of: `2026-07-16T19:41:02+09:00` (KST) / `2026-07-16T10:41:02+00:00` (UTC)
- start: `2026-07-14T00:00:00+09:00` (KST) / `2026-07-13T15:00:00+00:00` (UTC)
- policy_version: `activity-v1` · regular selector: `budget-router-v1`
- petcam-lab HEAD: `7f2390eb0980`

## 판정: **S0_HOLD_DATA_CONTRACT**

계약 위반 사유:
- core_completeness_below_100:2630/2634

coverage gap:
- policy_ready_below_80:90119209:0.5974
- policy_ready_below_80:f6599924:0.5556

## 재고 / 현재정책 coverage

- total_eligible motion clips: **2700**
- any_prelabel clips: **2634**
- policy_ready (`activity-v1` + 유효 prelabel 참조): **2634**
- core_complete (policy_ready 중 필수 evidence 완비): **2630**

### 0% coverage 카메라/날짜 strata
- `f6599924` 2026-07-14: eligible 25, prelabel 0

## selector 시점 coverage (정규/backfill 분리)

- 정규(`budget-router-v1`) run: **5**, backfill run: **71**
- **exact** = `clip_vlm_jobs` FK(prelabel_id/activity_assessment_id) 로 선택 결과에 실제 연결된 evidence.
- **estimate** = run window `[window_start, window_end)` 안 motion clip 중 `prelabel.created_at <= run.created_at` 비율(복원 근사치).
- **not_reconstructable** = episode reduction·제외 전 eligible pool 의 clip 단위 snapshot 은 저장되지 않아 정확 pool 을 복원하지 않는다.

## S1 권고 (범위 한정)

- S0_HOLD_DATA_CONTRACT: 데이터 계약이 불완전하므로 S1 진행 금지. 위 계약 위반 사유부터 해소한다.

본 감사는 read-only 다. selector/threshold/자동제외/행동라벨/앱 활동시간을 변경하지 않았다.

