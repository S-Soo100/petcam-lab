# Unified GT Failure Audit — Frozen Test Sheet

- Primary analysis GT: T1; T2는 확장 민감도 분석; T3는 EDA only; X는 GT 제외
- Owner eligibility: reviewed_by=audited Owner AND stage=completed AND initial_gt/current_gt/completed_at non-null
- dataset203: manifest 실제 유효 행 재측정, historical exposure=true, future holdout=false
- Dedup precedence: source FK → salted object-key hash → content hash → camera/time/duration/size → near episode
- Split/group unit: duplicate group → 5-minute episode → camera-night
- Top cause: T1/T2, >=10 episodes, >=2 camera-nights, largest duplicate group <=20%
- READY는 top cause >=1과 next_candidate 정확히 1개일 때만
- 그 외 `UNIFIED_GT_FAILURE_AUDIT_HOLD_<REASON>`
- 결과를 본 뒤 taxonomy, 최소 표본, ranking score를 변경하지 않음
