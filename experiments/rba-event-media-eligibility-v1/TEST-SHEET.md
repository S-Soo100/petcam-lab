# RBA 사건 묶기 Media Eligibility v1 TEST-SHEET

**상태:** `EXECUTED_MEDIA_VERIFIED_AWAITING_HUMAN_CHANNEL`
**실험일:** 2026-07-31
**목표:** fixed historical DB source와 실제 R2 객체의 교집합만으로 exact 120 사건 경계 표본을 만든다.

## 1. Frozen input

- strict cutoff: `started_at < 2026-07-31T03:44:27.183403+09:00`
- closed activity day: KST 07:00 경계
- DB SELECT tables: `motion_clips`, `motion_clip_system_exclusions`,
  `motion_clip_review_slots`, `labeling_tutorial_lessons`
- R2 reads: bucket-wide `ListObjectsV2`, selected 240 `HeadObject`
- frozen formal input: 명시한 Blind30 v1 manifest + canary/tutorial DB rows
- GT/Python Evidence/Gate/VLM/model/frame/R2 GET: 0

## 2. Eligibility

- non-empty DB `r2_key`가 R2 LIST에 있고 object `Size > 0`이어야 available
- null/empty key, LIST 미등장 key, size 0 object는 `diagnostic_integrity`
- duplicate DB key는 관련 clip 전부 `diagnostic_integrity(r2_key_duplicate)`
- null/empty key는 `diagnostic_integrity(r2_key_missing)`, LIST 미등장은
  `diagnostic_integrity(r2_object_absent)`로 분리
- LIST pagination token 누락·cycle·invalid schema·10,000 page 초과·SDK 오류는
  `BLOCKED_MEDIA_INVENTORY_FAILED`
- `KeyCount=0`일 때 생략된 `Contents`는 빈 list로 허용하고, `KeyCount>0`의 누락·길이 불일치는 차단
- raw key·ID는 private memory 밖으로 출력하지 않음
- algorithm version: `r2-list-intersection-v1`

## 3. Frozen selection

- seed `rba-event-grouping-shadow-v2`
- development 6 camera-nights + historical holdout 6 camera-nights
- 각 split 60 pair, `<=30 / 30–60 / 60–300s` 각 20
- unique clip 240, reuse 0
- split 최소 2 cameras, camera cap 36/60, split·bin camera cap 14/20
- bounded partition 2,000 × bin order 6, canonical minimum witness

## 4. Final media preflight

- 선택된 240개에만 `HeadObject` 정확히 1회
- HTTP 200 + positive ContentLength + non-empty ETag
- 240/240일 때만 artifact 생성
- 1개라도 실패하면 replacement 없이 `BLOCKED_MEDIA_PREFLIGHT_FAILED`
- 실패 aggregate는 `not_found_404 / auth_401_403 / invalid_response / other`로 key 없이 분류

## 5. Artifact and public audit

- private directory `0700`, files `0600`, no-overwrite
- private hashed manifest: pages, available/unavailable counts와 SHA-256; wall-clock 제외
- public runtime summary에만 inventory 시작·종료 UTC 시각
- public: counts, selection hash, call counts, status only
- raw clip/camera/reviewer ID, R2 key/URL/ETag, GT 원문 0
- success status: `PREPARED_MEDIA_VERIFIED_AWAITING_HUMAN_CHANNEL`

## 6. Safety and verdict

- DB write/RPC 0
- R2 write/delete/GET 0
- frame/Python Evidence/Gate/local-cloud model/service change 0
- one-shot 직전 short-clip retention/deletion 자동화 상태를 read-only 감사하되 변경하지 않음
- exact selection 또는 final 240/240 실패 시 artifact 0
- success 뒤에도 사람 배정은 0; 별도 human channel 계약 전
  `READY_FOR_HUMAN_BOUNDARY_GT_V2` 선언 금지

## 7. Actual result

- cutoff 이전 fixed DB inventory 대상 `19,279`; 선택된 12 camera-night의
  source/accounting `5,034/5,034`
- R2 inventory: 37 pages, available `17,702`, object absent/size 0 `1,577`,
  missing/duplicate DB key `0/0`
- exact 120, development/holdout `60/60`, split별 bin `20/20/20`, 12 camera-nights,
  unique clip `240`, reuse `0`, camera cap `36`, split-bin camera cap `14`
- final R2 HEAD `240/240`
- private artifact `0700/0600`, pair/source manifest hash 독립 재계산 일치
- DB/R2 mutation·R2 GET·model/frame/service 변경 `0`
- 판정: `PREPARED_MEDIA_VERIFIED_AWAITING_HUMAN_CHANNEL`
- 상세: [`REPORT.md`](REPORT.md)
