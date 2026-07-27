# Owner GT × Python Evidence Motion Signal Benchmark

## Verdict

`PE_MOTION_SIGNAL_INCONCLUSIVE`

`roi_mean`은 pooled cohort에서는 moving/static-only를 구분하는 방향성 신호를 보였지만,
카메라별 결과가 `0.483`과 `0.823`으로 갈렸어. 동결 규칙의 “두 camera AUROC 모두 0.50 초과”를
충족하지 못하므로 공통 selector feature나 global threshold로 승격하면 안 돼.

## Frozen contract

- cohort: Owner eligible 172
- discrimination: moving 108 / static-only 32
- 제외: 두 class에 속하지 않는 32
- primary: `motion_summary.roi_mean`, 높은 값=moving
- bootstrap: 5분 episode cluster, seed `20260727`, 10,000 iterations
- 결과 확인 뒤 방향·feature·weight·threshold 변경 없음
- 모델 학습·VLM·selector·production 변경 없음

계약 정본은 [`TEST-SHEET.md`](TEST-SHEET.md), 설계 한계는 [`DESIGN.md`](DESIGN.md)에 있어.

## Cohort and mutation scope

| 항목 | 결과 |
|---|---:|
| eligible | 172 |
| cohort ordered SHA-256 | `8e2bf4e73f8f033288d7632e25e2fbfd69d3de98c62dade2996bbe33686c96ba` |
| 5분 episode | 39 |
| discrimination episode | 37 |
| cameras | 2 |
| camera-nights | 6 |
| moving | 108 |
| static-only | 32 |
| excluded | 32 |

시작 `2026-07-27T05:21:46Z`, 종료 `2026-07-27T05:24:00Z`에 아래 6개 source table의
count+ordered fingerprint가 전부 같았어.

- `motion_clips`
- `motion_clip_labeling_triage`
- `motion_clip_labeling_sessions`
- `motion_clip_labeling_session_revisions`
- `clip_python_evidence_runs`
- `clip_prelabels`

이 mutation 0 증거는 위 6개 table과 frozen Owner cohort 범위야. DB 전체의 무변경을 뜻하지
않아. 이번 작업은 production DB에 SELECT만 실행했고 DB/R2/runtime write 명령은 실행하지 않았어.

## Technical coverage

| 지표 | 결과 |
|---|---:|
| Python Evidence coverage | 172/172 |
| level0 `ok` | 172/172 |
| level1 `ok` | 172/172 |
| provenance contract | 1 |
| primary `roi_mean` finite | 140/140 |
| bootstrap valid | 10,000/10,000 |
| decoded frames median / IQR | 503.5 / 250.25 |
| global series length median / IQR | 134 / 121 |
| ROI series length median / IQR | 134 / 121 |

기술적으로는 결측이나 decode 실패가 병목이 아니야. 판정이 inconclusive인 원인은 coverage가 아니라
camera-specific discrimination 차이야.

## Primary AUROC and clustered CI

| 지표 | 결과 |
|---|---:|
| pooled AUROC | 0.7133 |
| episode-cluster 95% CI | 0.5565–0.8125 |
| moving median / IQR | 0.4668 / 0.3096 |
| static-only median / IQR | 0.2980 / 0.0800 |
| Hodges–Lehmann moving−static | +0.1154 |

pooled 결과만 보면 신호가 있어 보이지만 camera별 분해에서 같은 방향이 재현되지 않았어.

| 익명 camera | 전체 | moving | static-only | excluded | AUROC |
|---|---:|---:|---:|---:|---:|
| camera_1 | 71 | 34 | 7 | 30 | 0.4832 |
| camera_2 | 101 | 74 | 25 | 2 | 0.8227 |

camera_1의 static-only가 7건뿐이라 정밀도가 낮고, 두 camera의 class 구성도 크게 달라. pooled
AUROC에는 camera·길이·장면 구성 차이가 섞일 수 있어. 따라서 pooled `0.7133`을 production
정확도나 보편적 motion signal 성능으로 일반화하지 않아.

## Camera/camera-night drift

`roi_mean` camera-night median은 `0.1245~0.5626`, IQR은 `0.0245~0.7792`로 범위가 넓었어.
camera_1과 camera_2는 decoded/series 길이도 사실상 서로 다른 영상 길이 군을 이뤄. raw
`roi_mean` 하나를 모든 camera에 같은 기준으로 적용하면 환경·길이 차이를 행동 차이로 오해할
위험이 있어.

이 결과로 per-camera normalization이나 duration correction을 사후 적용하지 않았어. 그런 변환은
새 feature 계약이며 별도 TEST-SHEET와 future data가 필요해.

## Secondary diagnostics

| feature | coverage | median | IQR |
|---|---:|---:|---:|
| `observed_sec` | 172/172 | 65.85 | 33.08 |
| `peak_autocorr` | 172/172 | 0.5792 | 0.2626 |
| `decoded_frame_count` | 172/172 | 503.5 | 250.25 |

secondary는 missingness·drift 설명에만 사용했어. 합성점수, feature 선택, weight 조정, threshold
sweep은 하지 않았어.

## Interpretation and limitations

확인된 사실:

1. Python Evidence pipeline 자체 coverage와 provenance는 안정적이야.
2. raw `roi_mean`은 camera_2에서는 moving/static-only 방향성을 보였어.
3. 같은 방향이 camera_1에서 재현되지 않았어.
4. 현재 데이터로 global selector feature를 정당화할 수 없어.

확인할 수 없는 것:

- production 전체 camera·개체·사육장 일반화
- rare care·visibility 성능
- `roi_mean` threshold
- normalization 또는 여러 feature 조합의 효용
- VLM 비용 절감률과 selector lift

## Service impact

현재 서비스 동작은 바뀌지 않았어. 이 결과로 `roi_mean` 기반 자동 skip, activity filter,
selector ranking, VLM 호출 차단을 추가하면 안 돼.

이번 실험이 준 개선 효과는 “쓸 수 있는 신호”보다 “그대로 쓰면 안 되는 경계”를 찾은 거야.
pooled AUROC만 보고 global threshold를 넣었으면 camera_1에서 잘못된 우선순위나 정상 영상 손실을
만들 가능성이 있었어.

## Next minimum action

1. 기존 7건과 합산하지 않고 camera_1의 **별도 future holdout**에서 static-only 30건을 모아.
2. clip random split이 아니라 동결 이후 촬영된 future camera-night 단위로 적립해.
3. future holdout과 분리된 dev data에서 normalization 후보를 먼저 고정해.
4. 표본이 찬 뒤 raw `roi_mean` baseline과 사전 고정한 camera-normalized 후보를 새
   TEST-SHEET에서 비교해.
5. 두 camera에서 방향이 재현되고 독립 episode가 충분할 때만 selector 후보 효용 평가로 넘어가.

현재는 데이터 수집만 허용하고 normalization 식·threshold·selector 구현은 시작하지 않는 게
최소 행동이야.

## Not run

- 모델 학습·classifier fitting
- feature/weight/threshold tuning
- Python Evidence 재생성
- VLM 호출
- selector·activity filter·Gate·API·웹·migration 변경
- R2 GET/write와 signed URL 생성
- LaunchAgent·runtime·deploy 조작
- main merge·production 반영

## Git and verification

- branch: `codex/owner-gt-python-evidence-benchmark-20260727`
- frozen design commit: `e880698`
- implementation plan commit: `5454843`
- frozen contract commit: `89772fd`
- analyzer commit: `4ca7744`
- verifier commit: `c4cbf4b`
- measured artifact commit: `5f87c6c`
- verification hardening commit: `587cb52`
- analysis/verifier tests: 18 passing
- independent artifact result: `PE_BENCHMARK_ARTIFACTS_OK`
- independent review: Critical 0, Important 0, `APPROVED`
