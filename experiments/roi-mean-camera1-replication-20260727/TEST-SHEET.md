# TEST-SHEET — Camera 1 raw roi_mean Future Replication

**상태:** 🔒 `FROZEN`

**승인:** owner 대화 승인, 2026-07-27

**설계:** [`DESIGN.md`](DESIGN.md)

**선행 결과:** [`../owner-gt-python-evidence-benchmark-20260727/REPORT.md`](../owner-gt-python-evidence-benchmark-20260727/REPORT.md)

**성격:** future camera-night replication holdout. normalization 개발 실험이 아니야.

**질문:** 동결 이후 camera_1의 새로운 camera-night에서 raw `motion_summary.roi_mean`이 moving과
static-only를 높은 값=moving 방향으로 구분하는가?

## 0. 동결 요약 (frozen contract)

```text
status = FROZEN
target = camera_1, prior Owner eligible count 71
future eligibility = started_at > future_cutoff_utc
positive = initial_gt.observed_actions contains moving
negative = initial_gt.observed_actions contains static and not moving
episode = same camera, consecutive started_at gap <= 5 minutes
minimum clips = moving 30, static_only 30
minimum episodes = moving 20, static_only 20
minimum camera_nights = total 3, each class 2
primary = motion_summary.roi_mean, higher means moving
bootstrap = episode cluster, seed 20260727, iterations 10000, percentile 95% CI
pre-lock visible data = counts, coverage, provenance only
```

결과를 확인한 뒤 이 문서의 표본·feature·seed·iterations·판정 기준을 수정하면 실험은 무효야.

## 1. Camera와 시간 경계

### 1.1 target camera_1

tracked 파일에 camera UUID를 쓰지 않아. target camera는 선행 benchmark SQL과 동일한
deterministic 규칙으로 다시 찾아.

```text
Owner eligible cohort의 camera_id를 정렬
→ dense_rank() = 1인 camera
→ 선행 snapshot에서 71건이었던 camera_1
```

재계산 결과가 target 1대 또는 선행 71건과 다르면 `ROI_REPLICATION_HOLD_CAMERA_IDENTITY_DRIFT`로
중단해.

### 1.2 future cutoff

이 TEST-SHEET를 commit한 뒤 production DB `now()`를 한 번 SELECT해 `future_cutoff_utc`로
고정해. eligible clip은 `motion_clips.started_at > future_cutoff_utc`여야 해.

- cutoff 이전 172건과 camera_1 기존 7 static-only는 표본 수에 포함하지 않아.
- cutoff와 sample manifest는 결과 분석 전에 고정해.
- 결과를 본 뒤 cutoff를 앞당기거나 clip을 제외하지 않아.

## 2. 사람 GT와 Evidence eligibility

각 clip은 아래를 모두 만족해야 해.

```text
target camera_1
AND started_at > future_cutoff_utc
AND Owner identity가 reviewed_by
AND labeling stage = completed
AND initial_gt/current_gt/completed_at IS NOT NULL
AND Python Evidence run 정확히 1개
AND level0_status = ok
AND level1_status = ok
AND roi_mean finite
AND frozen Evidence provenance contract 일치
```

사람 GT는 Evidence·Gate·VLM 결과를 보기 전에 잠긴 `initial_gt`를 class 정의에 사용해.
revision이 생기면 provenance로 보고하되 class는 initial GT를 유지해 결과를 본 뒤 정답이 바뀌는
누출을 막아.

## 3. Class

- positive: `initial_gt.observed_actions`에 `moving` 포함
- negative: `static` 포함 AND `moving` 미포함
- 나머지: 기술 coverage에는 보고하지만 primary discrimination에서는 제외
- positive와 negative overlap은 0이어야 해

## 4. 표본과 episode

### Minimum analysis sample

- moving clips ≥ 30
- static-only clips ≥ 30
- moving 5분 episodes ≥ 20
- static-only 5분 episodes ≥ 20
- camera-nights ≥ 3
- 각 class가 최소 2개 camera-night에 존재

같은 camera에서 연속 clip 시작 간격이 5분 이하면 같은 episode로 묶어. clip 30건을 채워도
episode 조건이 부족하면 계속 수집해.

표본이 차기 전에는 coverage dashboard(class별 clip·episode·night 수, Evidence coverage,
provenance 일치)만 볼 수 있어. class별 `roi_mean` 분포, AUROC, CI, 극단값은 sample lock 전에
계산하거나 노출하지 않아.

## 5. Frozen feature와 통계

### Primary

- feature: `motion_summary.roi_mean`
- direction: 값이 높을수록 moving
- metric: raw AUROC
- inference unit: clip
- uncertainty unit: 5분 episode-cluster bootstrap
- bootstrap iterations: 10,000
- seed: `20260727`
- interval: percentile 95% CI

### Required diagnostics

- non-null/finite coverage
- L0/L1 success와 provenance contract count
- moving/static-only clip·episode·camera-night 수
- class별 중앙값/사분위 (sample lock 이후)
- Hodges–Lehmann moving−static location difference (sample lock 이후)
- camera-night별 중앙값/사분위 (sample lock 이후)
- bootstrap invalid replicate rate

### 금지

- direction 반전
- `max(AUC, 1-AUC)`
- threshold sweep
- normalization
- duration correction
- feature 조합·weight
- classifier fitting
- sample lock 뒤 제외·교체

## 6. 판정

sample minimum을 모두 충족한 뒤 정확히 하나로 판정해. (DESIGN 9절 그대로)

- `ROI_CAMERA1_REPLICATION_SUPPORTED`
  - primary coverage ≥95%
  - AUROC lower 95% CI >0.50
  - valid bootstrap ≥95%
- `ROI_CAMERA1_REPLICATION_REJECTED`
  - primary coverage <80% 또는 AUROC upper 95% CI ≤0.50
- `ROI_CAMERA1_REPLICATION_INCONCLUSIVE`
  - minimum sample은 충족했지만 CI가 0.50을 포함하거나 valid bootstrap <95%
- `ROI_CAMERA1_REPLICATION_COLLECTING`
  - minimum clip/episode/camera-night 미충족
- `ROI_CAMERA1_REPLICATION_HOLD_<REASON>`
  - camera identity, cutoff, GT/Evidence provenance, read-only, mutation 계약 위반

`SUPPORTED`여도 production 채택 승인이 아니야. 그다음 두 camera future comparison TEST-SHEET를
작성할 근거만 생겨.

## 7. Mutation·보안 계약

시작·종료에 아래 6개 source table의 count와 ordered canonical fingerprint를 비교해.

1. `motion_clips`
2. `motion_clip_labeling_triage`
3. `motion_clip_labeling_sessions`
4. `motion_clip_labeling_session_revisions`
5. `clip_python_evidence_runs`
6. `clip_prelabels`

- production DB는 SELECT-only.
- R2 GET/write와 signed URL 생성 없음.
- labeling web/API/migration, Owner·labeler workflow 변경 없음.
- Python Evidence·Gate·VLM 재실행 없음.
- selector·activity filter·자동 skip 변경 없음.
- LaunchAgent·runtime·deploy 변경 없음.

tracked artifact에는 clip/camera/user UUID, 메모 원문, URL, R2 key, 이메일을 저장하지 않아.
deterministic short hash는 익명 sample/episode 중복 확인에만 쓰고 원본 매핑은 저장하지 않아.

## 8. 실행 순서

1. 이 TEST-SHEET commit (cutoff 조회 전)
2. fail-closed 수집 계약 검증기 + 테스트 작성/commit
3. SELECT-only freeze/collection SQL 작성/commit
4. git·source fingerprint 시작 기준선 기록
5. freeze-cutoff SELECT 1회 → cutoff 고정, target identity invariant 검증
6. collection-status SELECT → class·episode·night·coverage만 익명 집계
7. source fingerprint 종료 기록
8. 독립 verifier로 artifact 재검증
9. REPORT 작성 + 독립 리뷰

## 9. Kickoff 완료 조건

“연구 시작”은 이 TEST-SHEET와 cutoff를 동결하고 collection status를 측정하는 것이야. cutoff
직후에는 future GT 표본이 0 또는 부족한 것이 정상이며 정상 verdict는
`ROI_CAMERA1_REPLICATION_COLLECTING`이야.

최종 완료(`SUPPORTED / REJECTED / INCONCLUSIVE`)는 minimum sample lock 뒤 별도 실행에서만 나와.
COLLECTING 동안 결과를 추측하거나 normalization 연구로 건너뛰지 않아.
