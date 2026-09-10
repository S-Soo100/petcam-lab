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

## 2026-09-11 — pixel access(train role 전용) 승인 → Task 4·5 코드 + 보정/태깅 도구

**owner 승인(2026-09-11):** train role thumbnail pixel access = ROI calibration v1 + dish_present 태깅. holdout(2026-09-04 밤 3대) thumbnail·video 는 열지 않는다. 파일럿 600 은 train 전용으로 지금 구성한다. 원본·R2·DB write 0.

| 항목 | 내용 |
|---|---|
| Task 4 `roi.py` (`88c106d`) | 프로파일 검증: 카메라당 정확히 3 ROI(left/middle/right), 좌→중→우 겹침 0, 보정 프레임 role 게이트(v27_train 만), 기하 digest 일치, IR·저녁 검증 플래그. `crop_bounds` 단일 원천으로 crop(view)·원본↔ROI 좌표 왕복 ≤1px. 테스트 11 |
| Task 5 `sampling.py` + CLI (`3a2f125`) | 600 = 200 timestamp × 3 ROI(source group), 카메라 66–67 timestamp, 시간대 4층(20–22/22–02/02–05/05–08 KST) ±1, 소스(30분 슬롯)당 1 timestamp(5분 규칙 자동), dish 하한 10% 는 태그 있을 때만, 부족 시 `SelectionShortage`(다른 사육장으로 안 채움). 추출: timestamp당 1 decode(release finally), exact SHA 전역·dHash≤2 5분 근사 중복 제거, IR/컬러 stratum(채널 spread ≤4), 익명 `V27P0001.jpg` ZIP + 0600 lineage, double-review 60(image SHA 순위), 워밍업 27(파일럿과 소스 disjoint, `V27W`). CLI `roi-profile` / `pilot-select` / `pilot-extract`. 테스트 33 |
| ROI calibration 도구 | Claude 아티팩트(비공개, db capability). 내장 프레임 = train role 2026-09-05 밤 3카메라 × (20:00 저녁 / 02:00 IR) thumbnail 6장 — 내장 전 role manifest 로 `v27_train` 확인. 출력 `roi/v1` 문서 → `cli roi-profile` 검증 통과 시에만 `attempt/roi/roi-profile.private.json` |
| dish_present 태깅 도구 | 로컬 FastAPI(`dish_tag_server.py`, 127.0.0.1 전용): role manifest 의 train/val 슬롯 thumbnail 만 서빙(holdout 403, 모르는 ref 404), 태그는 `attempt/dish/entries/*.json` O_EXCL append-only → `compile` 로 `dish-tags-v1` 원장(0600). 픽셀이 MacBook 밖으로 나가지 않는다 |
| decode smoke | train role 영상 2개 × 3 시각: 2880×1620, IR, seek+decode 0.15–0.35 s/프레임 → 파일럿 200 timestamp ≈ 1분 |

**상태:** ROI 프로파일 = owner 드로잉 대기 → `roi-profile` → `pilot-select`(seed `v27-pilot-v1`) → `pilot-extract --which warmup` → `--which pilot` → CVAT. dish 태깅은 파일럿과 독립(train base 3,000 의 하한용; 태그가 준비되면 파일럿 재선택 없이 base 층화에 반영). 전체 테스트 2,904 passed.
