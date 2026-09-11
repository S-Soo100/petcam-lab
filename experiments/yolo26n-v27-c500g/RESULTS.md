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

### 2026-09-11 — dish_present 태깅 완료 (train 576 슬롯, 사람 판정)

owner 가 로컬 태깅 서버로 398 슬롯을 이미지별로 판정(대부분 "셋 다 없음"), 나머지 178 슬롯은 owner 가 선언한 기본 규칙으로 일괄 기록(`method=owner_default_rule_2026-09-11`, 엔트리에 규칙 원문 보존): cam01 = 좌·우 먹이 있음 + 가운데 불명(썸네일에서 안 보임), cam02·cam03 = 셋 다 먹이 있음. 원장 `dish-tags-v1.private.json`(0600) 컴파일 완료. holdout thumbnail 열람 0.

| 카메라 | food_in_dish=true (좌/중/우) | 불명 (좌/중/우) | 슬롯 |
|---|---|---|---:|
| cam01 | 73 / 15 / 73 | 10 / 67 / 10 | 192 |
| cam02 | 81 / 80 / 81 | 0 / 0 / 0 | 192 |
| cam03 | 99 / 99 / 99 | 0 / 0 / 0 | 192 |

dish 하한(사육장별 ≥10%)은 cam01 가운데를 빼고 전부 여유. cam01 가운데는 true 15 슬롯(7.8%) — 파일럿(사육장 67, 하한 7)은 15 슬롯 안에서 충족 가능하고, base 3,000(사육장 ≈333, 하한 ≈34)은 슬롯당 여러 timestamp(5분 간격, ≤6)를 허용하므로 15 슬롯 × ≤6 = 90 후보로 충족 가능. 못 채우면 다른 사육장으로 채우지 않고 `SelectionShortage` 로 보고. 태그는 사람 판정이며 GT·모델 예측으로 승격하지 않는다.

### 2026-09-11 — ROI profile v1 기록 + 파일럿 600·워밍업 27 추출 완료 (train 전용)

**ROI profile** (`attempt/roi/roi-profile.private.json`, profile_sha256 `5526a7c2fd1fa2a2ae92c81a16fcfd97be873fdc9ccd003532e30ba3d8d41b74`, padding 24 px, 2880×1620): owner 가 보정 아티팩트에서 카메라 3대 × 3 사각형을 IR(02:00) 프레임 위에 그려 저장. 도구의 IR/저녁 체크박스는 안 켜진 채였고, owner 가 "ROI 저장했어, 파일럿 뽑아" 로 진행을 지시 → Claude 가 저장된 사각형을 train 보정 썸네일 6장(3카메라 × 20:00/02:00, 09-05 밤)에 겹쳐 그려 9개 전부 사육장 경계에 맞는 것을 확인하고, `roi-profile --attest-verified`(진술+시각 기록, 도구 원본 상태 보존)로 기록. 검증 게이트(정확히 3 ROI·겹침 0·보정 프레임 v27_train)는 그대로 통과. 사각형 폭 0.26–0.30 / 높이 0.72–0.77(정규화).

**파일럿 선택** (`pilot-select --seed v27-pilot-v1`, dish 태그 자동 적용):

| 카메라(digest 앞 8) | timestamp | 시간대 20–22 / 22–02 / 02–05 / 05–08 | 사육장 3개 dish_tagged | camera-night |
|---|---:|---|---|---:|
| 3a5974ba | 67 | 17 / 16 / 17 / 17 | 30 / 29 / 30 | 12 |
| 80d03fbc | 67 | 17 / 17 / 16 / 17 | 32 / 32 / 32 | 11 |
| f5ddb2c6 | 66 | 17 / 16 / 17 / 16 | 23 / **7** / 23 | 11 |

600 = 200 timestamp × 3 ROI, 사육장 67·67·67·67·67·67·66·66·66, band_balanced true, 소스당 1 timestamp. dish 하한(사육장 10%, 파일럿 7)은 전부 충족 — f5ddb2c6 가운데(= cam01 가운데, true 태그 15 슬롯)만 딱 7. 워밍업 27 = 9 timestamp(카메라 3씩), 파일럿과 소스 disjoint.

**추출** (`pilot-extract`, 미러 영상 decode, JPEG q95):

| 큐 | 요청 | kept | 중복 제거(exact/near) | decode 실패 | IR / 컬러 | ZIP |
|---|---:|---:|---|---:|---|---|
| warmup (`V27W0001…0027`) | 27 | 27 | 0 / 0 | 0 | 24 / 3 | 10.8 MB, 28 entries |
| pilot (`V27P0001…0600`) | 600 | 600 | 0 / 0 | 0 | 468 / 132 | 235.5 MB, 601 entries, 34.5 s |

crop 크기(padding 포함) 785–909 × 1224–1316 px. double-review = image SHA 순위 60 (`pilot/double-review.private.json`). 공개 manifest(`review-queue.public.json`) leak scan(`confidence|prediction|checkpoint|model_version|recordings/|timestamp|cam0`) = 0. lineage(0600)에만 source·timestamp·원본 좌표. 눈 확인: 익명 ZIP 에서 5장 샘플(1·151·301·451·600) — 사육장 하나씩 padding 포함, IR·컬러 모두 정상.

**다음(owner):** CVAT 태스크 생성 — ① warmup 27 먼저(통계 제외) ② pilot 600 ③ 이중검수 60 은 별도 blind job. export 뒤 Task 6 normalizer(status/bbox strict, adjudication queue) 로 사람 GT 화 → 파일럿 decision rule(16px / 95% / 2%) 판정.

### 2026-09-11 — CVAT 태스크 3개 생성 (owner 요청으로 Claude 가 owner Chrome 의 CVAT UI 조작)

로컬 self-hosted CVAT(docker, v2.66.0, owner 계정). API/CLI 자동 생성 없음 — CVAT 웹 UI 를 owner 의 Chrome 에서 Claude 가 클릭(owner 지시 "chrome띄워놨으니 제어해서 cvat준비까지 진행해"). 익명 image-only ZIP 3개(원본 ZIP 에서 JPEG 만 재포장, 이름 동일)를 CVAT 컨테이너 share 디렉터리에 `docker cp` 하고 "Connected file share" + Copy data into CVAT 로 생성. 라벨 계약 = [`cvat-labels-v1.json`](cvat-labels-v1.json)(tag 4: present/absent/uncertain/media_error + attribute 5, rectangle: gecko). 정렬 lexicographical(frame i = 익명 시퀀스 i+1), image quality 95, chunk cache.

| 태스크 | 이미지 | 작업(job) | 비고 |
|---|---:|---:|---|
| warmup | 27 | 1 | 통계 제외 연습용 |
| pilot primary | 600 | 6 × 100 | 첫 blind pass |
| pilot double-review | 60 | 1 | primary 와 별도 task, 같은 익명 이름 |

task/job ID·ZIP SHA·설정은 0600 `attempt/pilot/cvat-receipt.private.json` 에만. 첫 warmup 제출은 share 디렉터리가 cvat_server 컨테이너에만 있어 import worker 가 파일을 못 찾아 실패(태스크 미생성) → import/chunks worker 컨테이너에도 복사한 뒤 재시도 성공. production write 0.

**다음(owner):** CVAT 에서 warmup → primary(job 6개) → double-review 순서로 판정. 이미지마다 status tag 1개 필수, present 면 gecko 사각형 ≥1, absent 는 0. export(CVAT for images 1.1 XML 또는 JSON) 뒤 Task 6 normalizer.

### 2026-09-11 — 워밍업 27장 판정 완료 + status 태그 규칙 확정

owner 가 CVAT 워밍업 task 27장에 gecko 박스 판정(24장 박스 1개, 3장 박스 0). status 태그는 owner 가 규칙을 정하고 Claude 가 owner Chrome 세션의 CVAT API(`PATCH /api/jobs/<id>/annotations?action=create`)로 일괄 기록: **박스 있음 → `present`, 박스 없음 → `absent`, `uncertain`/`media_error` 는 owner 가 직접 찍는 경우만.** 근거: 태그는 "사육장에 게코가 사는가"가 아니라 "이 이미지에 게코가 보이는가"이며, 안 보이는 이미지가 detector 음성(설계 ROI negative 30–40%)이다. owner 최초 제안(박스 없음 → uncertain)은 음성 0 이 되어 기각, owner 동의("좋아 이대로 가자"). attribute 는 기본값(edge_issue none, lighting_state ir, occlusion none, hardcase none, cross_enclosure_reflection false) — 조명 stratum 은 lineage 에 이미 있음. 결과: 27/27 태그 1개, present 24 = 박스 24, absent 3 = 박스 0, 정합 위반 0. 같은 규칙을 pilot primary 600 / double-review 60 에도 적용한다(owner 는 박스만 친다).

### 2026-09-11 — Task 6 normalizer 코드 + 워밍업 human-gt-v1

`scripts/yolo26n_v27_c500g/cvat.py`: `build_cvat_contract`(큐 SHA·라벨·attribute allowlist 핀) · `audit_cvat_export`(프레임별 위반 보고, 진행 점검용) · `normalize_cvat_export`(위반 0 → human-gt-v1: status·boxes·attributes·source_group_digest·full_frame_eligible) · `build_conflict_queue`(status 다름 / 박스 수 다름 / 매칭 IoU<0.70 → adjudication-queue-v1). 검사: 이미지당 status tag 정확히 1, present↔박스 ≥1 / 그 외 0, rectangle=gecko·manual·rotation 0·양수 면적·경계 안(0.5px 허용 후 clamp), attribute allowlist, track 금지, frame 이름·크기 = 큐, 계약 SHA = 큐. CLI `audit-cvat` / `normalize-cvat --which warmup|pilot|double` / `adjudicate`. export 입력 = 로컬 inbox(브라우저 CVAT 세션이 `POST 127.0.0.1:8765/api/inbox/<name>`) 로 받은 CVAT API job annotations JSON. 테스트 18 + CLI 1 (패키지 215 passed).

**워밍업 정규화:** `pilot/warmup/human-gt.private.json` — present 24(박스 24) / absent 3 / uncertain 0 / media_error 0, source group 9/9 full-frame eligible, 위반 0.

### 2026-09-11 — 파일럿 600 + 이중검수 60 사람 판정 완료, decision rule 1차 집계 (adjudication 전)

owner 가 CVAT primary 600(job 6개)·double-review 60 에 gecko 박스 판정. status 태그는 확정 규칙(박스 있음 → present, 없음 → absent)으로 Claude 가 API 일괄 기록(우연히 owner 가 직접 찍은 present 6개는 규칙과 동일). 정규화: `pilot/pilot/human-gt.private.json`(위반 0), `pilot/double-review/human-gt.private.json`(위반 0), `pilot/double-review/adjudication-queue.private.json`.

| 지표 (TEST-SHEET 사전 기준) | 값 | 판정 |
|---|---:|---|
| unique ROI 판정 | 600 (present 520 / absent 80 / uncertain 0 / media_error 0) | — |
| uncertain+media_error ≤ 10% | 0.0% | 통과 |
| 박스 짧은 변 ≥16px 비율 ≥ 95% — full-frame@960 환산(×1/3) | 99.8% (min 15.3 / p05 21.5 / p50 42.5 px) | 통과 |
| 같은 지표 — roi_3tile@960 환산(crop 긴 변→960) | 100% (min 34 px) | 통과 |
| edge issue ≤ 2% — crop 경계에 닿은 박스(clipped proxy) | 3 / 520 = 0.58% (padding 띠 안 13 = 2.5%, 경계 미접촉) | 통과 (proxy) |
| edge_issue attribute(사람) | 전부 none — owner 가 attribute 를 쓰지 않아 정보 없음 | 미측정 |
| ROI negative(absent) 30–40% | **13.3%** (카메라별 5% / 14% / 21%, 사육장 최소 1 / 최대 21) | **미달 → shortage 보고** |
| double review 불일치 | 6 / 60 = 10% (status 4: absent↔present, IoU<0.70 2: 0.52·0.65) | adjudication 대기 |

박스 크기(원본 crop px): 짧은 변 min 46 / p05 65 / p50 128 / max 363. 프레임당 박스 1개(2마리 0). 조명별 absent: color 34/132, IR 46/468. 시간대별 absent: 20–22 22/153, 22–02 32/147, 02–05 13/150, 05–08 13/150.

**해석(1차, adjudication 뒤 확정):** 표현 규칙은 full-frame·3-tile 둘 다 통과 — full-frame@960 도 95% 를 여유 있게 넘어 원본 배치 유지 가능(min 15.3 px 1개는 경계값). 경계 crop 오류는 0.6% 로 ROI 재보정 불필요. 미달은 **음성 비율**: 게코가 대부분 보이는 사육장이라 무작위 층화로는 absent 가 13% — base 3,000 층화에서 absent 를 늘리려면 (a) 22–02 시간대·color 프레임 가중, (b) 은신 개체 사육장(카메라 f5dd… 21%) 가중, (c) 목표를 실측 분포로 하향 중 owner 결정 필요(사후 threshold 변경이 아니라 shortage 보고 후 재층화 규칙 = TEST-SHEET 절차). double-review 10% 불일치는 같은 owner 가 시간차로 판정한 것이며 4건이 "보이나 안 보이나" 경계 → `uncertain` 사용 안내 필요.

**다음(owner):** adjudication 6건(익명 V27P0109·0114·0121·0201·0214·0336 = task 9 frame 108·113·120·200·213·335)을 primary task 에서 최종 판정(태그/박스 수정) → 재export → human-gt r2 = adjudicated GT.

### 2026-09-11 — adjudication 완료 → 파일럿 최종 GT(r2) 확정, decision rule 최종 집계

owner 가 primary task 에서 불일치 6건을 최종 판정: 3건 박스 추가(absent→present), 1건 1차 유지(present, "내가 맞는 것 같아"), 2건 박스 재작성. 재export → `pilot/pilot/human-gt.r2.private.json`(위반 0) = **파일럿 최종 GT(revision 2)**. 이중검수 재비교 r2: 불일치 2건 남음(1차 유지 1건 + 재작성 뒤 IoU 0.62 1건) — 둘 다 owner 결정으로 종결, `double-review/adjudication-decisions.private.json` 에 기록.

| 지표 | r2 값 | 판정 |
|---|---:|---|
| status | present 524 / absent 76 / uncertain 0 / media_error 0 | — |
| uncertain+media_error ≤ 10% | 0.0% | 통과 |
| 짧은 변 ≥16px ≥ 95% (full-frame@960 환산) | 99.6% (min 15.3 px 2개) | 통과 |
| 같은 지표 (roi_3tile@960) | 100% | 통과 |
| edge ≤ 2% (crop 테두리 접촉 proxy) | 4 / 524 = 0.76% | 통과 |
| ROI negative 30–40% | 12.7% | **미달(shortage)** |
| double review 불일치 | 1차 6/60 → adjudication 뒤 2/60(owner 종결) | 완료 |
| 프레임당 박스 | 최대 1 | — |

**표현(representation) 판정 제안:** full-frame 과 3-tile 모두 사전 규칙 통과. 원본 배치 유지·좌표 변환 불필요·잘림 0.8% 인 **full-frame** 을 v2.7 publication 표현으로 제안(owner 승인 뒤 `freeze-representation`). 단, negative 12.7% 는 base 3,000 층화 규칙(시간대 22–02·color·은신 사육장 가중 또는 목표 하향) owner 결정 필요.

### 2026-09-11 — 표현 동결(full_frame) + 재층화 negative-expansion-v1 600장 큐

**표현 동결(Task 7):** owner 결정 "전체 프레임 확정" → `representation/representation-freeze.private.json` = `full_frame`(계산 mode 와 일치, override 없음). 근거: 운영 계약(원본 1장 → imgsz 960 단일 패스)과 동일, v2.6 replay·2.6.1 warm-start 와 스케일 일치, 파일럿 16px 규칙 99.6% 통과, edge 0.8%, 좌표 변환 불필요. 3-tile 은 서빙 3배·경계 개체 분할 문제로 기각. 짧은 변 히스토그램(full-frame@960 px): <16: 2 / 16–32: 151 / 32–64: 273 / 64–128: 98.

**재층화 규칙(negative-expansion-v1, shortage 대응):** 파일럿 negative 12.7% 미달 → 사전 기준을 바꾸지 않고 base 3,000 의 첫 600 을 다음 규칙으로 뽑는다. owner 가 `absent` 로 판정한 76 판단의 슬롯(+같은 밤 인접 슬롯)에서 슬롯당 ≤2 timestamp, 기존 timestamp 와 5분·서로 10분 간격, absent 판정별 라운드 로빈. 예측 모델 0, 사람 판정만 사용. 전체 프레임 표현이라 빈 사육장은 이미지 배경으로도 학습되지만, 숨은 개체·반사·가지 장면의 음성 예제를 늘리는 목적. seed `v27-neg-v1`, 600 = 200 timestamp × 3 ROI, 카메라별 timestamp 32 / 68 / 100(absent 분포 비례), 시간대 22–02 비중 높음(band_balanced false 는 의도). 추출 600/600(IR 387 / color 213, 중복·실패 0), 익명 `V27N0001…0600`, CVAT task 생성(owner Chrome UI).

**base 3,000 잔여 예산:** pilot 600 + negative-expansion 600 = 1,200 unique. 남은 train additional 600 + val 600(val role 은 완비 밤 추가 뒤) + teacher/fallback 600, double-review 누적 60/300.
