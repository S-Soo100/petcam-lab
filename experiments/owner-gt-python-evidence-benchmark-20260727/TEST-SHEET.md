# TEST-SHEET — Owner GT × Python Evidence Motion Signal

**상태:** 🔒 `FROZEN`  
**승인:** owner 대화 승인, 2026-07-27  
**설계:** [`DESIGN.md`](DESIGN.md)  
**질문:** `roi_mean`이 moving 108과 static-only 32를 높은 값=moving 방향으로 구분하는가?

## 1. 고정 cohort

- Owner eligible: 172건
- ordered SHA-256:
  `8e2bf4e73f8f033288d7632e25e2fbfd69d3de98c62dade2996bbe33686c96ba`
- Python Evidence: 172/172, clip당 1 run
- 5분 gap episode: 39
- camera: 2대
- capture date: 3일

eligibility는 아래 네 조건을 모두 만족해야 해.

```text
reviewed_by = unique Owner identity
AND stage = 'completed'
AND initial_gt IS NOT NULL
AND current_gt IS NOT NULL
AND completed_at IS NOT NULL
```

## 2. 분석 population

| population | 계약 | 기대 수 |
|---|---|---:|
| technical | eligible 전체 | 172 |
| positive | `observed_actions`에 `moving` 포함 | 108 |
| negative | `static` 포함 AND `moving` 미포함 | 32 |
| discrimination 제외 | 두 집단 어디에도 속하지 않음 | 32 |

clip random split은 하지 않아. retrospective EDA 단일 cohort에서 5분 episode를 cluster로 둬.
현재 negative 32건이라 dev/holdout 각각 최소 30을 만들 수 없으며 이 표본을 future holdout이라고
부르지 않아.

## 3. 고정 feature

### Primary

- `motion_summary.roi_mean`
- 사전 방향: 값이 높을수록 moving
- 지표: raw AUROC
- 결과에 맞춘 방향 반전과 `max(AUC, 1-AUC)` 사용 금지

### Secondary diagnostics

- `spatial_dwell.observed_sec`
- `periodicity_summary.peak_autocorr`
- `decoded_frame_count`
- global/ROI series length와 필수 key missingness

feature 선택, 합성점수, weight, threshold, classifier는 만들지 않아. 과거 T1에서 기각된
`observed_sec + roi_mean + peak_autocorr` 합성점수도 재사용하지 않아.

## 4. 통계 계약

- sampling unit: 같은 camera에서 시작 간격 5분 이내인 episode
- bootstrap seed: `20260727`
- bootstrap iterations: `10000`
- interval: percentile 95% CI
- episode를 복원추출하고 episode 안 clip은 함께 포함
- 두 class 중 하나가 없는 replicate는 무효 처리하고 무효율을 보고
- camera별 AUROC와 camera-night별 median/IQR 병기
- positive/negative별 median, IQR, Hodges–Lehmann location difference 병기

## 5. 판정

- `PE_MOTION_SIGNAL_DESCRIPTIVE_SUPPORTED`
  - primary AUROC lower 95% CI > 0.50
  - 두 camera point estimate 모두 0.50 초과
  - primary non-null/finite coverage ≥ 95%
- `PE_MOTION_SIGNAL_INCONCLUSIVE`
  - CI가 0.50을 포함하거나 camera 방향이 엇갈리거나 유효 bootstrap이 95% 미만
- `PE_MOTION_SIGNAL_REJECTED`
  - primary AUROC upper 95% CI ≤ 0.50 또는 primary coverage < 80%
- `PE_BENCHMARK_HOLD_<REASON>`
  - cohort/provenance/episode drift, SQL 계약 불일치, read-only 보장 실패

`SUPPORTED`는 production 채택 승인이 아니며 selector 후보 TEST-SHEET 작성 근거만 돼.

## 6. Mutation·보안 계약

시작·종료에 아래 6개 source table의 count와 ordered canonical fingerprint를 비교해.

1. `motion_clips`
2. `motion_clip_labeling_triage`
3. `motion_clip_labeling_sessions`
4. `motion_clip_labeling_session_revisions`
5. `clip_python_evidence_runs`
6. `clip_prelabels`

tracked artifact에는 UUID, 메모 원문, URL, R2 key, 이메일을 저장하지 않아. deterministic short
hash는 익명 sample/episode 중복 확인에만 쓰고 원본 매핑은 저장하지 않아.

## 7. 하드 금지

- 모델 학습·classifier fitting
- feature·weight·threshold sweep
- Python Evidence 재생성
- VLM 호출
- selector·activity filter·Gate·API·웹·migration 변경
- DB/R2 write와 signed URL 생성
- LaunchAgent·runtime·deploy 조작
- current 172를 production 일반화 근거로 표현

## 8. 실행 순서

1. git·source fingerprint 기준선 기록
2. 익명 snapshot SELECT
3. frozen 분석기 실행
4. source fingerprint 종료 기록
5. 독립 verifier 재계산
6. REPORT 작성

결과 확인 뒤 이 문서의 표본·feature·seed·iterations·판정 기준을 수정하면 실험은 무효야.
