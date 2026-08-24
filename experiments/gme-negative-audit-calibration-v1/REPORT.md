# GME negative audit calibration v1 — REPORT

**Execution status:** `PENDING_NOT_RUN`

**Calibration label:** `PENDING`

**Downstream disposition:** `HOLD_PENDING_HUMAN_CALIBRATION`

이 문서는 실행 뒤 safe aggregate만 기록하는 skeleton이야. raw clip/camera/run/reviewer/source/R2 identity, media hash/dHash, bbox, timestamp 원문은 넣지 않아.

## 1. Frozen artifact evidence

| artifact | raw SHA-256 / status |
|---|---|
| TEST-SHEET | `PENDING` |
| training pin manifest | `PENDING` |
| protected pin manifests | `PENDING` |
| availability | `PENDING` |
| private inventory | `PENDING` |
| frozen batch manifest raw SHA-256 | `PENDING` |
| frozen batch manifest canonical SHA-256 | `PENDING` |
| scorer | `PENDING` |
| private ledger | `PENDING` |
| safe score aggregate | `PENDING` |

## 2. Preflight and write audit

| 항목 | 결과 |
|---|---|
| source random-negative / control count | `PENDING / PENDING` |
| eligible random-negative / control count | `PENDING / PENDING` |
| camera / camera-night / episode count | `PENDING / PENDING / PENDING` |
| unavailable reason aggregate | `PENDING` |
| protected media GET | `PENDING` |
| DB writes | `PENDING` |
| R2 writes | `PENDING` |
| other service/model/deploy writes | `PENDING` |
| import RPC call count | `PENDING` |

## 3. Human completion counts

| 항목 | 결과 |
|---|---|
| random negative completed / valid | `PENDING / PENDING` |
| random `gecko_present` / `gecko_absent` | `PENDING / PENDING` |
| random `uncertain` / `media_error` | `PENDING / PENDING` |
| positive control `gecko_present` / 30 | `PENDING / 30` |
| Owner adjudication required / completed | `PENDING / PENDING` |
| valid present bbox / effective present | `PENDING / PENDING` |

## 4. Primary metric

- `negative_pool_gecko_prevalence`: `PENDING`
- Wilson 95% CI: `PENDING`
- positive-control detection: `PENDING`

이 지표는 GME-negative pool 안의 사람 확인 게코 존재 비율이야. detector recall 또는 FNR로 해석하지 않아.

## 5. Descriptive aggregates

| aggregate | 결과 |
|---|---|
| anonymized camera-night counts | `PENDING` |
| protected exact overlap | `PENDING` |
| protected near duplicate (`dHash <=2`) | `PENDING` |
| candidate exact / near duplicate | `PENDING / PENDING` |
| lineage violation | `PENDING` |
| source missing / HEAD / GET errors | `PENDING` |
| bytes length/hash errors | `PENDING` |
| decode / dHash errors | `PENDING` |

## 6. Preregistered calibration label

- `INVALID_CALIBRATION`: protected/lineage violation이 하나 이상, valid random negative가 100 미만, 또는 positive-control `gecko_present`가 27/30 미만.
- `AUDIT_VALID_NO_MISS`: invalid 조건이 없고 confirmed negative miss가 0.
- `AUDIT_VALID_MISSES_FOUND`: invalid 조건이 없고 confirmed negative miss가 1개 이상.

**Final label:** `PENDING`

## 7. Adopt / hold / reject 경계

- calibration protocol disposition: `PENDING_ADOPT_HOLD_REJECT`
- detector/checkpoint production adoption: `NOT_AUTHORIZED`
- Dataset candidate inclusion: `NOT_AUTHORIZED_WITHOUT_OWNER_DECISION`
- retraining/checkpoint replacement/deployment: `NOT_AUTHORIZED`

유효한 calibration label도 production 채택을 뜻하지 않아. confirmed miss가 있으면 사람 확인 evidence와 별도 Dataset decision을 보존한 뒤 새 Decision Gate에서 후속 hard-case 사용 여부를 판단해.

## 8. 다음 사람 작업

1. `PENDING` pin/count를 실제 read-only preflight 결과로 채우고 Owner가 TEST-SHEET exact raw SHA를 재승인해.
2. 새 attempt에서 frozen manifest를 한 번 만들고 120/30/150, overlap 0, lineage 일치를 독립 확인해.
3. 별도 승인된 Preview canary 뒤에만 production import와 사람 검수를 시작해.
4. scorer safe aggregate를 이 REPORT에 옮기고 preregistered label 하나만 확정해.
