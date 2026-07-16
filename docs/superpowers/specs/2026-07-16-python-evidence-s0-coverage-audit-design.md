# Python Evidence Hybrid S0 Coverage Audit 설계

> **상태:** 승인됨 / 구현 전
> **상위 정본:** `docs/superpowers/specs/2026-07-16-python-evidence-hybrid-design.md` §12 S0, §17-1
> **목적:** production의 기존 Gate evidence가 어디까지 실제로 채워졌고 정규 VLM selector 입력에 얼마나 사용 가능했는지 read-only로 실측한다.

## 1. 결정

S0는 새 evidence를 만들거나 worker를 고치는 단계가 아니다. production DB를 읽어 아래 세 값을 분리해 산출하는 재현 가능한 감사로 진행한다.

1. **재고 coverage:** `motion_clips` 중 `clip_prelabels`가 존재하는 비율
2. **현재 정책 준비 coverage:** `activity-v1` assessment가 있고 그 assessment가 유효한 prelabel을 참조하는 비율
3. **selector 시점 coverage:** selector 실행 당시 evidence가 입력에 존재했는지에 대한 확정치와 복원 가능한 근사치

결과를 보고 S1 처리량 벤치마크의 표본 범위를 정한다. S0 결과만으로 selector, threshold, 자동 제외, 행동 라벨을 바꾸지 않는다.

## 2. 대안과 선택 이유

### A. 콘솔 SQL 일회성 집계

가장 빠르지만 쿼리와 판정이 재현되지 않고, 1,000행 pagination·KST 날짜 경계·selector 시점 조건을 놓치기 쉽다.

### B. 재현 가능한 read-only 감사 스크립트 — 채택

순수 집계 함수와 Supabase read adapter를 분리하고, JSON/CSV/Markdown 보고서를 같은 snapshot에서 만든다. 이후 카메라가 4대로 늘어도 같은 명령으로 다시 비교할 수 있다.

### C. DB view/RPC 추가

대규모 운영 집계에는 유리하지만 S0를 위해 migration과 production write surface를 늘린다. 현재는 필요 없다.

## 3. 범위

### In scope

- `motion_clips`, `cameras`, `clip_prelabels`, `clip_activity_assessments`, `clip_vlm_selector_runs`, `clip_vlm_jobs`, `camera_activity_filter_settings` read-only 조회
- 1,000행을 넘는 모든 테이블의 안정적인 pagination
- KST 기준 카메라×촬영일 strata 집계
- evidence identity·필수 필드·motion metrics 완전성 집계
- 정규 selector와 historical backfill을 분리한 selector 시점 분석
- JSON, CSV, Markdown 산출물과 원시 row count checksum
- 불완전하거나 복원할 수 없는 값의 명시적 `not_reconstructable`

### Out of scope

- DB migration, INSERT/UPDATE/DELETE/RPC
- R2 다운로드, 영상 디코딩, detector/OpenCV/Claude/VLM 호출
- LaunchAgent·환경변수·스케줄 변경
- selector/batch/prompt/threshold 변경
- 자동 skip, GT, behavior label, 앱 활동시간 변경
- Slack 전송

## 4. 기준 모집단과 시간

- 기본 감사 시작: `2026-07-14T00:00:00+09:00` — activity evidence production migration 도입일
- 종료: 실행자가 `--as-of`로 고정한 KST 시각. 보고서에 UTC와 KST를 모두 기록한다.
- 재고 모집단: 시간 범위 내 `motion_clips` 중 `duration_sec > 0`이고 `r2_key`가 비어 있지 않은 clip
- 카메라 표시는 이름과 UUID 앞 8자리만 사용한다. owner UUID, R2 key, 비밀값은 산출물에 기록하지 않는다.
- 날짜 strata는 `motion_clips.started_at`을 Asia/Seoul로 변환한 촬영일이다.

## 5. coverage 정의

### 5.1 재고 coverage

- `any_prelabel_coverage = unique clip with any prelabel / eligible motion clips`
- 같은 clip에 여러 identity가 있어도 분자는 1이다.
- identity별 `(model_version, schema_version, checkpoint_sha256, threshold, sampler_version, frames_sampled)` 분포를 함께 낸다.

### 5.2 현재 정책 준비 coverage

- 기본 정책은 `activity-v1`이다.
- `policy_ready`는 해당 clip에 `policy_version=activity-v1` assessment가 있고, 그 row의 `prelabel_id`가 실제 prelabel을 참조할 때만 참이다.
- `camera_activity_filter_settings.active_policy_version`도 함께 읽어 카메라 설정과 기본 정책 불일치를 별도 경고한다.

### 5.3 evidence 완전성

선택된 최신 current-policy prelabel에 다음이 모두 있어야 `core_complete`다.

- provenance: `model_name`, `model_version`, 64자리 `checkpoint_sha256`, `threshold`, `sampler_version`, `schema_version`, `frames_sampled > 0`
- presence: boolean `gecko_visible`, 유한수 `visibility_confidence`
- motion metrics 8개 키: `visible_frame_count`, `visible_frame_ratio`, `max_bbox_center_disp`, `max_bbox_size_change`, `min_bbox_iou`, `roi_flow_mag`, `global_bg_change`, `bbox_edge_clipped`

`gecko_bbox=null`과 `best_frame_ts=null`은 absent evidence에서 정상일 수 있으므로 완전성 실패로 세지 않는다.

### 5.4 selector 시점 coverage

세 수준을 혼합하지 않는다.

1. **Selected linkage — 확정치:** `clip_vlm_jobs.prelabel_id`와 `activity_assessment_id`의 non-null·FK 존재 여부. job 생성 당시 선택 결과에 연결된 evidence다.
2. **Window-time availability — 복원 근사치:** 각 `clip_vlm_selector_runs`의 `[window_start, window_end)` motion clip 중 `clip_prelabels.created_at <= selector_run.created_at`인 clip 비율.
3. **Exact eligible-pool coverage — 복원 불가:** 기존 run은 episode reduction과 제외 전 후보의 clip별 snapshot을 저장하지 않는다. 집계치와 선택 clip만으로 정확한 pool을 재구성하지 않는다.

정규 selector(`budget-router-v1`)와 rolling/historical backfill selector는 별도 표로 낸다. 현재 코드 사실도 함께 기록한다: 정규 candidate는 저장된 activity/prelabel을 읽고, backfill은 `enrich_prepool` 경로를 가질 수 있다.

## 6. 산출물

고정 경로 `reports/python-evidence-s0-coverage-20260716/`에 아래를 만든다.

- `summary.json`: snapshot metadata, 전체 coverage, verdict, warnings
- `camera_date_coverage.csv`: 카메라×KST 날짜별 모집단·coverage
- `selector_time_coverage.csv`: selector run별 확정/근사 coverage와 selector 종류
- `identity_distribution.csv`: evidence identity별 clip 수
- `REPORT.md`: 사람이 읽는 결론과 S1 권고

clip UUID 전체 목록, R2 key, owner UUID, raw evidence JSON은 산출하지 않는다.

## 7. 판정 계약

- **S0_PASS:** `core_complete=100%`, 최근 완전 종료된 촬영일에 각 enabled 카메라의 `policy_ready >= 80%`, 0% 카메라 없음, 정규 selector selected-linkage·window-time 값이 산출됨
- **S0_PASS_WITH_COVERAGE_GAP:** contract는 완전하지만 일부 strata가 80% 미만이거나 정규 selector 표본이 부족함. S1은 covered subset으로만 진행하고 일반화 금지
- **S0_HOLD_DATA_CONTRACT:** core completeness <100%, FK 단절, pagination/count 불일치, 시간 파싱 실패, 또는 감사 자체가 불완전함

80%는 자동 채택 기준이 아니라 S1 표본을 기존 evidence에서 구성할 수 있는지 판단하는 운영 준비선이다. 어떤 판정에서도 selector 활성화나 자동 제외는 허용되지 않는다.

## 8. 오류·보안 처리

- Supabase 오류, page 중복/누락, 참조 무결성 오류는 fail-closed nonzero 종료한다.
- 결과 파일은 모든 조회와 검증이 끝난 뒤 임시 디렉터리에서 최종 경로로 교체한다. 실패 시 반쪽 보고서를 남기지 않는다.
- 로그에는 table명·row count·진행률만 출력한다. 환경변수 값과 DB 오류 원문은 보고서에 넣지 않는다.
- 코드 정적 검사에서 `.insert(`, `.update(`, `.delete(`, `.upsert(`, `.rpc(`를 금지한다.

## 9. 검증

- 순수 집계 테스트: 중복 prelabel, multiple identity, missing metric, absent nullable, KST 날짜 경계
- selector 테스트: job linkage 확정치, prelabel 생성 시각 전/후, regular/backfill 분리, exact pool 복원 불가 표기
- pagination 테스트: 1,001행 이상에서 중복·누락 0
- 출력 테스트: owner UUID/R2 key/evidence raw JSON/secret pattern 미노출
- production 실행 전후 주요 테이블 row count가 동일함을 read-only로 대조

## 10. 완료 조건

1. 테스트와 전체 회귀가 통과한다.
2. production read-only 실행이 성공한다.
3. 세 산출 CSV와 `summary.json`, `REPORT.md`가 동일 snapshot을 가리킨다.
4. 보고서가 exact/estimate/not_reconstructable을 명확히 구분한다.
5. S0 판정과 다음 S1 표본 범위를 제안하되 구현·운영 변경은 하지 않는다.
