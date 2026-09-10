# YOLO26n v2.7 C500G inventory 계약 v1.1 addendum — 실제 녹화기 동작에 맞춘 정정

> 상태: `CLAUDE_PROPOSED / OWNER_REVIEW` · 작성: 2026-09-10 · 대상: `scripts/yolo26n_v27_c500g/inventory.py`, `roles.py`, 설계 §2.2·§7, 계획 Task 2·3
> 근거 데이터: R2 `c500g` 미러(2026-09-10 복원본)의 manifest 실측. aggregate 만 기록.

## 1. 왜 정정하나

inventory 계약(2026-08-28 설계, Task 2 구현)은 "3카메라 × **정확히 7일 연속** × 24슬롯 = 504, 슬롯 = 20:00~07:30 KST 30분 그리드, 완비 = `partial=false` AND 길이 1800±2초, 예정 슬롯 결손·그리드 밖 번들 = MISMATCH(fail-closed)" 로 쓰였다. 실제 녹화기(2026-09-03 capture-first 파이프라인, Mac mini runtime `d8baeff`)와 데이터는 다르다.

| 실측 (미러 manifest, 2026-09-10) | 계약 v1.0 과의 충돌 |
|---|---|
| 녹화는 08-27 부터 14일째 계속, 72슬롯 완비 밤은 09-03·04·05·08 (이후 매일 추가) | "정확히 7일 연속·504" 을 만족하는 창이 없다 |
| 08-27~09-01 레거시 밤은 슬롯 시작이 30분 그리드에 없음(예: 22:40:46 KST), fps 10→20 | 그리드 밖 번들 전부 `unexpected_actual_slot` MISMATCH |
| 09-02 이후 정렬 슬롯의 길이 p25/p50/p95 = 1768/1773/1783초 (`CAPTURE_SLOT_RESERVE_SEC=17` + 종료 여유) | "1800±2초" 를 만족하는 번들이 0 |
| `partial` 플래그 = `actual_start != scheduled_start`(밀리초 차이도 true) → 정렬 슬롯 대부분 true | "`partial=false`" 완비 조건이 새 파이프라인 번들 전부 거부 |
| 시작 오프셋 p50 10초, p95 973초 — 늦게 시작한 슬롯은 짧음(<1700초 7/70) | 결손·지각을 "정체성 불일치" 와 같은 등급으로 취급 |

그대로면 inventory 는 어떤 창에서도 READY 가 되지 않아 역할 동결(Task 3) 이 영영 막힌다. owner 승인(2026-09-10 2차: 불완비 camera-night 는 train 전용, 결손은 보고)과 정합하도록 **정체성 불일치(fail-closed)** 와 **녹화 결손·레거시(보고 후 진행)** 를 분리한다.

## 2. 정정 내용

| 항목 | v1.0 | v1.1 |
|---|---|---|
| 스케줄 창 | 정확히 7일 연속, 504 슬롯 | **N ≥ 1 일 연속**, 3카메라 × 24 × N 슬롯. 비연속·중복·그리드 밖 스케줄은 여전히 ValueError |
| 예정 슬롯 결손 | `missing_expected_slot` → MISMATCH | `schedule_gap_count` 로 보고, 상태는 정체성 기준으로만 결정. `missing_slot_count` 는 유지(감사용) |
| 그리드 밖 번들 | `unexpected_actual_slot` → MISMATCH | `unscheduled_bundle_count` 로 보고, 레코드 `scheduled_slot=false`. 같은 슬롯 중복(`duplicate_actual_slot`)은 여전히 MISMATCH |
| 완비 슬롯 (`complete_slot`) | `partial=false` AND \|길이−1800\|≤2 | mode production, verified, uploaded, hevc/h264, 2880×1620, **시작 오프셋(actual−scheduled) ≤ 60초 AND 길이 ≥ 1760초**. `partial` 플래그는 기록만 하고 판정에 쓰지 않는다 |
| 완비 슬롯 미달 | `incomplete_source_contract` → MISMATCH | 레코드 `complete_slot=false` 로 보고. camera-night 완비 = 예정 24슬롯 전부 존재 AND 전부 complete_slot |
| 정체성 불일치 (로컬/R2/DB sha·size·bundle·camera, DB 행 결손, R2 객체 결손, 중복 bundle_id) | MISMATCH | **변경 없음** (fail-closed 유지) |
| 레코드 필드 | 10개 | + `scheduled_slot`, `complete_slot`, `night_date`, `start_offset_sec` |
| roles.py 완비 판정 | 24 그리드 시작 존재 | + 레코드 `complete_slot` 전부 true (필드 없으면 true 로 간주, v1.0 호환) |

숫자 근거: 60초 오프셋은 p50 10초와 p95 973초 사이의 자연 간극, 1760초 = 1800 − reserve 17 − 종료 여유 실측 상한 23. 전체 미러 복원 뒤 재확인해 addendum 에 최종 분포를 append 한다(정정은 결과 확인 *전*이며 데이터셋 선정 규칙엔 영향 없음 — 이 값은 "어느 밤이 완비인가" 만 정한다).

## 3. 바뀌지 않는 것

- 로컬(미러)·R2·DB 3계층 SHA/size 대조와 write 0.
- 역할 동결 전 pixel 미개방, holdout = cutoff 이후 첫 3 complete camera-night, 불완비 = train 전용.
- 사람 판단 quota·표현 결정·확장 규칙 (TEST-SHEET immutable, SHA `f5d3c865…` 유지 — 이 addendum 은 TEST-SHEET 를 수정하지 않는다).

## 4. 검증

- 기존 `tests/yolo26n_v27_c500g/test_inventory.py` 의 결손·off-grid·504 기대를 v1.1 로 갱신, 정체성 불일치 테스트는 그대로 통과.
- 신규 `test_inventory_v11.py`: N일 창, 결손 비치명, off-grid 보고, complete_slot 판정(오프셋·길이), camera-night 완비 집계.
- `test_roles.py`: `complete_slot=false` 가 섞인 camera-night 는 불완비(train 전용).
