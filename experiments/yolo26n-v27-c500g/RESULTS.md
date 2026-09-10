# YOLO26n v2.7 C500G 준비 — 실행 결과 (aggregate-only appendix)

> 계획 Task 11 규칙: TEST-SHEET 는 immutable(append 금지), 결과는 여기에 aggregate 만 append. 비밀값·개별 source 식별자(camera_key, bundle_id, source_ref)는 넣지 않는다.
> 핀: TEST-SHEET `f5d3c86594483d36d60952749cebbe8b8ff616e8e86050d8285f63cc390533d9` · v2.6 holdout addendum `f3307761fd785e33…` · dish_present addendum `ee3e5a1eb8a03a92…` · inventory v1.1 addendum `docs/superpowers/specs/2026-09-10-yolo26n-v27-c500g-inventory-contract-v1.1-addendum.md`

## 2026-09-10 — attempt `2026-09-10-a2`: source inventory READY + role freeze (VAL_SHORTAGE)

**실행 호스트:** MacBook(구현 host = 실행 host, cross-host 아님). 로컬 계층 = R2 `c500g` 에서 복원한 미러(`storage/rap-c500g-mirror/`, 648 번들 123 GiB, 번들 manifest sha256 전수 검증 실패 0). 원본·R2·DB write 0. 코드 HEAD `68f9be4`(origin/main).

**attempt `2026-09-10-a1`** 은 R2 버킷 루트의 `test/` 폴더 마커 객체가 키 검증(`_safe_relative`)에 걸려 inventory 단계에서 실패 → `ReadOnlyR2` 기본 Prefix `recordings/` 로 수정(`68f9be4`) 후 a2 로 재실행. a1 디렉토리는 expected-slots 만 남은 실패 attempt 로 보존.

### inventory (창 2026-08-27 ~ 2026-09-08, 13밤 × 3카메라 × 24 = 936 슬롯)

| 항목 | 값 |
|---|---:|
| status | `V27_SOURCE_INVENTORY_READY` |
| 실제 번들 | 648 |
| 정체성 불일치 (mismatch_count) | **0** |
| 완비 camera-night | **9** (09-04 ×3, 09-05 ×3, 09-08 ×3) |
| 예정 슬롯 결손 (schedule_gap) | 480 / 936 |
| 그리드 밖 레거시 번들 (unscheduled, train 전용) | 192 (08-27~09-01) |
| 불완비 슬롯 (지각>60초 또는 길이<1710초) | 82 |
| 창 밖 R2 영상 (09-09 진행 중) | 69 |
| 디코드 프로브 실패 | 0 |

완비 판정 = 시작 오프셋 ≤60초 AND 길이 ≥1710초(슬롯의 95%). 정렬 슬롯 456개 길이 p05/p50/p95 = 1689/1770/1783초, 오프셋 p50/p95 = 13/94초 (inventory v1.1 addendum 참조).

### role freeze (seed `v27-role-freeze-v1`, cutoff = v2.6 detector freeze 2026-08-31T13:51:52Z)

| role | camera-night | 날짜 블록 |
|---|---:|---|
| `v26_holdout` | **3** | 2026-09-04 (카메라 3대 전부; cutoff 이후 첫 3 complete) |
| `v26_holdout_date_guard` | 0 | — |
| `v27_train` | 36 | 08-27 ~ 09-03, 09-05 ~ 09-08 (완비 09-05·09-08 + 불완비/레거시 전부) |
| `v27_val` | 0 | — |
| status | `V27_VAL_SHORTAGE` | 세 카메라 완비 dev 날짜 블록이 09-05·09-08 둘뿐(최소 3). 완비 밤 1개 추가 시 해소 |

cutoff 근거: freeze 파일 `yolo26n-v26-detector-freeze-v1`, SHA-256 `8f8e02beb452ec2ddfdce344dff507294f56136c69224990c50552d22bb343a0`(production `GME_DETECTOR_FREEZE_SHA256` 과 동일), mtime 2026-08-31T13:51:52Z, checkpoint `a00e5a7a…`. holdout 은 이후 밤이 추가돼도 바뀌지 않는다(정렬 첫 3 고정).

### 다음 게이트 (owner)

1. **pixel-access 승인**: train role 의 thumbnail 로 ROI calibration v1(카메라 3대, IR 프레임) + `dish_present` 태깅(train role 만; val 없음). holdout(09-04) thumbnail 은 열지 않는다.
2. 600 파일럿은 train role 에서만 층화. 사육장 9개 × 66~67.
3. VAL_SHORTAGE 해소: 완비 밤이 하나 더 들어오면(09-10 이후) 새 attempt 로 inventory·역할 동결 재실행(결정론, holdout 불변).
