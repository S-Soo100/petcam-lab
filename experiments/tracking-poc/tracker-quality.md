# Tracker 품질 게이트 리포트 (Step 1.5)

> 40건 stratified clip × OWLv2 검출 + CSRT 트래킹 결과. spec [[experiment-tracking-vlm-input]] Step 1.5.

**작성:** 2026-05-14
**산출물:** `tracker-quality.csv`, `tracker-mosaic.jpg`, 본 리포트

## 1. TL;DR — 게이트 FAIL

| 게이트 | 기준 | 실측 | 판정 |
|--------|------|------|------|
| 검출 성공률 (40건 기준) | ≥ 80% | **52.5%** (21/40) | ❌ |
| Catastrophic drift 비율 | ≤ 20% | **28.6%** (6/21) | ❌ |
| Loss 0회 (ok_rate=1.0) | ≥ 80% | 81.0% (17/21) | ✅ |

**4분기 매트릭스 → (α) Tracker drift 많음 (게이트 fail)**

GT 없음 → median IoU 직접 측정 불가. proxy 메트릭(center_drift_norm + area_change_ratio + 시각 검수)으로 대체.

## 2. 검출 단계 보틀넥

40건 중 19건이 트래킹에도 못 진입 — Step 0 클립 선정이 아닌 OWLv2 검출 한계.

| status | 개수 | 비율 |
|--------|------|------|
| `ok` (검출 + 트래킹 성공) | 21 | 52.5% |
| `no_detection` (OWLv2 score < 0.10) | 10 | 25.0% |
| `no_valid_bbox` (area sanity filter 통과 실패) | 9 | 22.5% |

- `no_detection` 10건: OWLv2 zero-shot 으로 게코를 못 잡음. IR 야간/원거리/은신 추정.
- `no_valid_bbox` 9건: 검출은 됐는데 박스 면적이 frame 의 30% 초과 또는 0.5% 미만. OWLv2 가 "사육장 절반" 을 high-score 로 잡는 false positive 패턴.

→ 검출 단계 자체에서 절반 가까이 잃음. 트래커 교체로는 해결 불가.

## 3. 21건 트래킹 분류

`center_drift_norm + area_change_ratio + ok_rate` 기반 3 카테고리.

### A. 안정 (8건, 38%)

`drift < 0.1` AND `0.7 ≤ area_change ≤ 1.5` AND `ok_rate = 1.0`

| clip_id | drift | area_x | motion_var | 비고 |
|---------|-------|--------|------------|------|
| 0125b0f9 | 0.032 | 0.89 | 0.014 | 정지 |
| 1ef6f35c | 0.023 | 0.85 | 0.010 | 정지 |
| 29d15a4c | 0.011 | 1.00 | 0.005 | 완벽 정지 |
| 8899146c | 0.005 | 1.05 | 0.006 | 완벽 정지 |
| b0b57a47 | 0.007 | 1.22 | 0.003 | 완벽 정지, 173 frame 짧음 |
| bf83c4cf | 0.074 | 1.61 | 0.034 | 미세 inflate, 354 frame |
| c2cd0200 | 0.091 | 1.42 | 0.047 | mild inflate |
| ff1ecb03 | 0.055 | 1.61 | 0.034 | mild inflate |

→ **정지 행동 위주**. Step 3 motion feature 의 resting 케이스 후보.

### B. 어긋남 — 사용 가능 but 박스 부정확 (7건, 33%)

`drift 0.1~0.3` OR `area_change 0.4~0.7 또는 1.5~2.0` (한쪽 어긋남)

| clip_id | drift | area_x | motion_var | 비고 |
|---------|-------|--------|------------|------|
| 5a907d7b | 0.011 | 0.47 | 0.013 | 박스 절반 줄음 (정지인데) |
| 5cfe1d48 | 0.137 | 1.74 | 0.108 | inflate |
| 7d9b9e8e | 0.138 | 1.04 | 0.132 | drift, area 안정 |
| 9e321296 | 0.237 | 1.04 | 0.065 | moderate drift |
| 49458257 | 0.313 | 0.45 | 0.117 | drift + shrink |
| d88e1390 | 0.179 | 0.53 | 0.114 | drift + shrink |
| e784eb65 | 0.283 | 1.49 | 0.172 | drift + inflate |

→ 박스 중심은 그럭저럭 따라가나 **크기 정합 무너짐**. Crop 으로 쓰려면 마진 30%+ 필요.

### C. 실패 — 시각적으로 박스가 무의미 (6건, 29%)

`drift > 0.3` OR `area_change < 0.2` OR `area_change > 2.0` OR `ok_rate < 0.9`

| clip_id | drift | area_x | motion_var | ok | 실패 유형 |
|---------|-------|--------|------------|------|-----------|
| 0e7bccb0 | 0.336 | **0.029** | 0.161 | **0.74** | Collapse + Lost |
| 24b99803 | 0.490 | 0.097 | 0.209 | 0.97 | Collapse + Drift |
| b61ef5ea | 0.403 | 0.328 | 0.184 | 0.99 | Drift + Shrink |
| bd96c769 | **0.550** | 0.371 | 0.227 | 1.00 | Severe Drift |
| c928b6ff | 0.203 | **4.000** | 0.057 | 1.00 | Severe Inflate (4배) |
| efa2afcc | 0.150 | **0.065** | 0.113 | 1.00 | Collapse |

### 정성 검증 (시각 확인 3건)

- **bd96c769** (drift 0.55): init 02:02:41 우측 하단 도마뱀 → last 02:03:41 박스가 좌측 하단 빈 나무껍질 영역으로 이동. **명확한 drift confirmation**.
- **c928b6ff** (area 4배): init 우측 도마뱀 일부 → last 도마뱀이 가까이 와서 자세 바꿈, 박스가 거의 화면 전체로 확장. **위치는 맞지만 크기 부정확**.
- **0e7bccb0** (collapse): init 회색 도마뱀 + 탈피 껍질 → last 박스가 좌측 상단 작은 점으로 collapse. **트래커 객체 상실**.

→ proxy 메트릭과 정성 검수 일치. CSV 분류 신뢰 가능.

## 4. 4분기 매트릭스 매핑

(α) **Tracker drift 많음 (게이트 fail)** 로 떨어짐.

근거:
- C 카테고리 29% (게이트 임계 20% 초과).
- 시각 검수 3건 모두 명확한 실패.
- 검출 단계 47.5% 실패 (별도 문제, OWLv2 한계).

## 5. 다음 액션 후보

spec 의 다음 액션은 "SAM 2 video 로 교체 후 Step 1.5 재측정" — 다만 두 가지 결정 포인트.

**결정 1: 검출기 교체 vs 트래커 교체**
- 검출 보틀넥 (47.5%) 이 트래킹 보틀넥 (29%) 보다 큼.
- SAM 2 video predictor 는 **첫 프레임 prompt 가 여전히 필요** → OWLv2 가 못 잡은 19건은 SAM 2 로도 못 푼다.
- 따라서 **검출기 보강이 선행**. OWLv2 prompt 튜닝 또는 GroundingDINO 같은 더 강한 zero-shot detector 검토 필요.

**결정 2: PoC 게이트 완화**
- 현재 게이트(≤20% drift)는 일반 vision tracking 기준. 우리 목적은 "VLM 입력 정규화" — A 카테고리 8건 + B 7건 = 15건 (71%) 이면 Step 2 의미 있는 비교 가능.
- B 카테고리에 마진 30%+ crop 강제하면 박스 부정확이 흡수됨.

**제안:**

| 옵션 | 설명 | 비용 |
|------|------|------|
| **(1) Step 2 진행** — A 8건만으로 baseline 측정, B/C 도 그대로 통과시키되 마진 30% crop | C 6건은 fallback to raw frame | 0 (기존 코드 활용) |
| (2) OWLv2 prompt 튜닝 + threshold 조정 | 검출 19건 회복 시도 | 1~2시간 |
| (3) SAM 2 video predictor 도입 | 21건 중 C 6건 재트래킹 시도, 19건 미검출은 그대로 | 반나절~1일 |
| (4) PoC 중단, UX/HITL 정공법으로 회귀 | 시각 한계 가설 (A) 강화 결론 | 0 |

옵션 (1) 권장 — **게이트 fail 했지만 결정 가치(Step 2의 분기 매트릭스)가 살아있음**. 71% 클립으로 A/B/C 비교해도 "B/C 가 A 대비 의미 있게 개선되는가" 신호는 충분히 잡힌다. 게이트 통과를 위해 SAM 2 시간 투자할 가치는 Step 2 결과 보고 판단.

## 6. 부록 — 메트릭 정의

GT 없으므로 proxy:
- `center_drift_norm = sqrt((cx_N - cx_0)² + (cy_N - cy_0)²) / 화면대각선` — 첫 → 마지막 박스 중심 이동.
- `area_change_ratio = area_last / area_init` — 박스 크기 변화 비율. 1.0 stable.
- `motion_var_norm = (xs.std() + ys.std()) / 화면대각선` — 박스 중심 분산. 진동 vs stuck 구분.
- `ok_rate = ok 인 frame / 전체 frame` — CSRT 자체 confidence.

**한계:** CSRT 의 `ok=True` 는 drift 상태에서도 종종 True 가 됨 (메트릭 설계 시 알고 있던 이슈). 따라서 ok_rate 단독 판단 X.
