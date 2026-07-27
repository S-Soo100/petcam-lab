# Owner GT × Python Evidence descriptive benchmark 설계

**상태:** `DESIGN_APPROVED_PENDING_WRITTEN_REVIEW`  
**설계 승인:** 2026-07-27, owner가 대화에서 1안(Python Evidence benchmark 우선)을 승인  
**선행 감사:** [`../owner-gt-audit-20260727/REPORT.md`](../owner-gt-audit-20260727/REPORT.md)  
**성격:** retrospective descriptive benchmark. production adoption test가 아님.

## 1. 목표

Owner가 직접 완료한 GT 172건을 고정 기준선으로 삼아 아래 한 질문만 측정해.

> 기존 Python Evidence가 `observed moving`과 `static without moving`을 구분하는
> 방향성 있는 신호를 제공하는가?

이 실험의 소비처는 Python Evidence 계산 로직의 failure analysis와 다음 selector 후보 실험의
착수 여부야. 모델 학습, 행동 분류기 생성, threshold 탐색, selector 변경, production 배포는
소비처가 아니야.

## 2. 검토한 접근

### A. 기존 172건으로 descriptive benchmark — 채택

- 장점: Python Evidence coverage가 172/172라 재계산 가능하고 추가 inference가 없어.
- 한계: 2카메라·3일·5분 episode 39개라 production 일반화나 adoption 판정을 할 수 없어.
- 선택 이유: 현재 신호의 유효성과 실패 지점을 가장 적은 위험으로 먼저 확인할 수 있어.

### B. 다양한 future GT를 더 모은 뒤 시작 — 후속

- 장점: production 일반화에 더 적합해.
- 한계: 현재 Evidence의 기본적인 결측·방향성 문제를 모른 채 수집 기간만 늘어날 수 있어.
- 사용 시점: A에서 측정 계약과 실패 유형을 확정한 뒤 adoption용 future holdout에 사용해.

### C. 기존 VLM/selector부터 비교 — 보류

- 기존 VLM success가 23건뿐이고 selector version/backfill이 섞였어.
- unselected 전체 후보의 당시 rank snapshot도 없어 인과적 효용 평가가 불가능해.

## 3. Decision gate

공유 `docs/decision-gate.md`는 이 설계 단계에서 수정하지 않고 전용 문서에 판정을 보존해.

| Gate | 판정 | 근거 |
|---|---|---|
| G1 SOT 부합 | ✓ | RBA Data Engine v1의 사람 GT·다양성·독립 평가 우선순위에 맞아. |
| G2 기대효과 | ✓ | Evidence 신호의 실패 위치를 찾아 계산 로직 개선 또는 후보 폐기의 근거로 사용해. |
| G3 측정가능 | ✓ | eligibility, feature 방향, clustered CI, 판정 규칙을 결과 전에 동결해. |
| G4 유효한 계획 | ✓ | SELECT-only, 전용 경로, 172건 고정, production 변경 0으로 실행 경계를 정의해. |

**게이트 결론:** descriptive benchmark 설계 진행. production adoption gate는 열지 않아.

## 4. 데이터 계약

### 4.1 고정 cohort

선행 감사의 Owner eligible 계약을 그대로 사용해.

```text
reviewed_by = unique Owner identity
AND stage = 'completed'
AND initial_gt IS NOT NULL
AND current_gt IS NOT NULL
AND completed_at IS NOT NULL
```

- 총 172 clips
- ordered cohort SHA-256:
  `8e2bf4e73f8f033288d7632e25e2fbfd69d3de98c62dade2996bbe33686c96ba`
- Python Evidence run 172/172, clip당 1개
- `level0_status='ok'` 172/172
- `level1_status='ok'` 172/172
- 동일 evidence/provenance contract 1개

실행 시작 시 같은 SQL로 count와 SHA를 다시 계산해 다르면
`PE_BENCHMARK_HOLD_COHORT_DRIFT`로 중단해.

### 4.2 분석 population

| population | 조건 | 예상 수 | 용도 |
|---|---|---:|---|
| technical | eligible 172 전체 | 172 | coverage·schema·missingness |
| positive | `observed_actions`에 `moving` 포함 | 108 | motion signal |
| negative | `static` 포함 AND `moving` 미포함 | 32 | static-only signal |
| discrimination 제외 | 위 두 집단 어디에도 속하지 않음 | 32 | AUROC 제외, 기술 coverage에는 포함 |

positive와 negative가 겹치지 않도록 SQL assertion을 둬. 사람 GT를 수정하거나 primary action으로
대체하지 않아.

### 4.3 episode와 카메라 경계

- 같은 카메라에서 시작시각 차이가 5분 이하면 같은 episode로 묶어.
- 알려진 기준선은 39 episode이며 재계산 결과가 다르면 중단해.
- `camera-night = camera_id × capture date KST`로 정의해.
- clip UUID, camera UUID, 메모, R2 key는 tracked artifact에 저장하지 않아.
- 집계에는 deterministic short hash만 허용하고 short hash↔원본 매핑은 저장하지 않아.

현재 negative가 32건뿐이라 dev/holdout 두 partition에 각각 최소 30을 둘 수 없어. 따라서
clip random split이나 가짜 holdout을 만들지 않고, 단일 retrospective EDA cohort에서
episode-cluster bootstrap만 수행해. 향후 평가에서는 camera-night 단위 future holdout을 별도로
만들어야 해.

## 5. 동결 feature 계약

### 5.1 Primary endpoint

- `motion_summary.roi_mean`
- 사전 방향: 값이 높을수록 `moving`
- metric: raw AUROC와 5분 episode-cluster bootstrap 95% CI

방향을 결과에 맞춰 뒤집지 않고 `max(AUC, 1-AUC)`도 primary 결과로 쓰지 않아.

### 5.2 Secondary diagnostics

- `spatial_dwell.observed_sec`
- `periodicity_summary.peak_autocorr`
- `decoded_frame_count`
- series 길이와 필수 key missingness

secondary는 분포·결측·카메라별 drift를 설명하는 용도야. 여러 feature를 합성한 점수, 가중치,
threshold, classifier를 만들지 않아. 과거 T1에서 기각된 `observed_sec + roi_mean +
peak_autocorr` 합성점수도 재사용하지 않아.

## 6. 분석과 통계

### 6.1 기술 coverage

- eligible run coverage
- L0/L1 success
- evidence schema/provenance contract 수
- feature별 non-null/finite 비율
- 배열 길이·decode ratio의 median/IQR
- 카메라·날짜별 missingness

### 6.2 신호 분석

- primary AUROC와 episode-cluster bootstrap 95% CI
- positive/negative별 median, IQR, Hodges–Lehmann location difference
- 카메라별 AUROC와 방향 일치 여부
- camera-night별 median/IQR
- 극단값은 집계 위치만 보고하고 원본 영상이나 사람 메모를 자동 해석하지 않아

### 6.3 bootstrap

- sampling unit: 5분 episode
- iterations: 10,000
- seed: `20260727`
- episode를 복원추출하고 episode 안 clip은 함께 포함해
- 한 replicate에 positive 또는 negative가 없으면 해당 replicate만 무효 처리하고 무효율을 보고해

## 7. 판정

결과는 정확히 하나로 판정해.

- `PE_MOTION_SIGNAL_DESCRIPTIVE_SUPPORTED`
  - primary AUROC lower 95% CI > 0.50
  - 두 카메라의 point estimate가 모두 0.50 초과
  - primary feature non-null/finite coverage ≥ 95%
- `PE_MOTION_SIGNAL_INCONCLUSIVE`
  - CI가 0.50을 포함하거나 카메라 방향이 엇갈리거나 유효 bootstrap이 95% 미만
- `PE_MOTION_SIGNAL_REJECTED`
  - primary AUROC upper 95% CI ≤ 0.50 또는 primary coverage < 80%
- `PE_BENCHMARK_HOLD_<REASON>`
  - cohort/provenance/episode drift, SQL 계약 불일치, read-only 보장 실패

`SUPPORTED`여도 production 채택 승인이 아니야. 다음 selector 후보 TEST-SHEET를 작성할 근거만
생겨. `INCONCLUSIVE`면 threshold를 조정하지 않고 다양한 future camera-night GT를 더 모아.
`REJECTED`면 해당 신호를 selector 후보에서 제외하고 failure analysis만 남겨.

## 8. 실행 구조

전용 경로 `experiments/owner-gt-python-evidence-benchmark-20260727/` 안에만 아래를 만들어.

```text
DESIGN.md
TEST-SHEET.md
benchmark.sql
analyze.py
verify_results.py
test_analyze.py
snapshot-aggregate.json
summary.json
REPORT.md
```

데이터 흐름은 다음과 같아.

```text
production DB SELECT
  → 익명화된 aggregate snapshot
  → primary/secondary 계산
  → 독립 verifier 재계산
  → REPORT
```

분석기는 DB write API를 갖지 않아. SQL은 SELECT/WITH statement만 허용하고 artifact guard가
INSERT/UPDATE/DELETE/RPC write와 민감 원시값을 거부해야 해.

## 9. 검증

- 분석 함수 단위 테스트: label partition, episode grouping, AUROC, clustered bootstrap,
  missingness, verdict
- 고정 fixture를 이용한 expected summary golden test
- `analyze.py`와 별도 `verify_results.py`가 count·AUROC·CI·verdict를 독립 재계산
- 시작/종료 아래 6개 source table의 count+ordered fingerprint 동일
  - `motion_clips`
  - `motion_clip_labeling_triage`
  - `motion_clip_labeling_sessions`
  - `motion_clip_labeling_session_revisions`
  - `clip_python_evidence_runs`
  - `clip_prelabels`
- 전체 프로젝트 테스트
- tracked artifact의 UUID, URL, 이메일, R2 key, 메모 원문 0

## 10. 하드 금지와 미실행

- 모델 학습·classifier fitting
- feature 선택·합성점수·weight·threshold sweep
- Python Evidence 재생성 또는 DB 수정
- VLM 호출
- selector·activity filter·Gate·API·웹·migration 변경
- R2 GET/write, signed URL 생성
- LaunchAgent·runtime·deploy 조작
- current 172를 future holdout 또는 production 일반화 근거로 표현

## 11. 완료 조건

1. TEST-SHEET가 결과 조회 전에 동결돼.
2. cohort·episode·feature provenance가 선행 감사와 일치해.
3. 분석과 독립 verifier가 같은 summary와 verdict를 내.
4. 시작/종료 fingerprint가 같아.
5. REPORT가 결과·한계·다음 최소 행동·미실행 항목을 구분해.
6. production 변경은 0으로 남아.
