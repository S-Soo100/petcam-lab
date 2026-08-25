# GME negative audit calibration v1 — TEST-SHEET

**상태:** `UNFROZEN`

**Owner 승인:** `PENDING`

**사람 검수 시작:** 금지

**production import:** 금지

이 문서는 GME가 `detected=false`로 기록한 post-training 운영 영상에서 사람이 확인한 게코 존재 미탐을 측정하기 위한 사전등록 문서야. availability 확인 뒤 Owner가 모든 `PENDING`을 실제 raw artifact에서 채우고 exact 문서 SHA를 승인하기 전에는 manifest를 만들지 않아.

## 1. Research question

고정된 YOLO26n v2.5 detector/GME run이 negative로 기록한 training cutoff 이후 production-purpose 영상 가운데, blind 사람 검수에서 실제 게코가 보이는 비율은 얼마인가? 이 값은 `negative_pool_gecko_prevalence`이며 detector recall 또는 FNR이 아니야.

## 2. 고정 표본 계약

| 항목 | 사전등록 값 |
|---|---|
| schema | `gme-negative-audit-v1` |
| seed | `gme-negative-audit-calibration-v1` |
| selection algorithm | `gme-negative-audit-selection-v1` |
| random negative | 정확히 120 |
| positive control | 정확히 30 |
| total | 정확히 150 |
| random-negative episode cap | episode당 최대 2 |
| camera-night | `Asia/Seoul` 기준 07:00 경계의 activity day와 camera UUID를 domain-separated SHA-256으로 결합 |
| episode | 같은 camera-night에서 이전 clip 끝과 다음 clip 시작의 gap이 300초를 초과할 때 새 episode, domain-separated SHA-256으로 결합 |
| near duplicate | 64-bit dHash Hamming distance `<=2` 제외, distance `3` 허용 |
| detector identity | `d4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6` |
| checkpoint SHA-256 | `2b128f105e898bc472ed66861583ab80007dae6e94b291db497d7a2f8081f84a` |
| training manifest raw SHA-256 | `PENDING` |
| training cutoff | `PENDING` — manifest 내부 canonical RFC3339 UTC 값만 사용, mtime 추정 금지 |

random negative는 cutoff 이후 `clip_purpose='production'`이고, current succeeded GME job의 `result_run_id`가 pinned detector의 `status='ok'` run과 일치하며 current activity가 `detected=false`인 clip만 사용해. positive control은 cutoff 이후 development-only 사람 consensus가 `agreed|owner_resolved`, `final_decision='label'`, visibility `visible|partial`인 clip만 사용해. source/run 없음, failed job/run, lineage mismatch, quarantine, R2 missing, bytes/decode/hash/dHash 문제는 `unavailable` aggregate로만 기록하고 negative로 합치지 않아.

## 3. Protected artifact pins

아래 각 파일은 raw bytes SHA-256과 manifest 내부 exact media SHA-256/dHash set을 함께 검증해. 각 record는 raw source/R2 identity 대신 domain-separated `source_identity_sha256`과 `r2_key_sha256`도 exact key set으로 포함해야 해. 필드 누락·형식 오류·set 중복은 외부 read 전에 fail-closed하고, protected media bytes 자체는 열지 않아.

| role | exact count | raw manifest SHA-256 |
|---|---:|---|
| training media | manifest 내부 exact count | `PENDING` |
| validation153 | 153 | `PENDING` |
| internal-test151 | 151 | `PENDING` |
| owner-external60 | 60 | `PENDING` |
| sealed future | manifest 내부 non-zero exact count | `PENDING` |

candidate source/R2 identity digest가 protected pin과 일치하면 R2 HEAD/GET 전에 제외해. identity digest가 일치하지 않았지만 실제 candidate GET 뒤 media SHA 또는 dHash `<=2` overlap이 확인되면 제외하고, 그 GET을 실제 access ledger의 `protected_media_get_count`에 더해. frozen 150개 manifest에서 protected/lineage violation이 발견되면 batch 전체 판정은 `INVALID_CALIBRATION`이야. raw identity와 identity digest는 private inventory 밖으로 내보내지 않고, protected holdout은 검수 UI, REPORT raw data, Dataset 후보로 열지 않아.

## 4. 검수·bbox 규칙

허용 verdict는 다음 네 개뿐이야.

- `gecko_present`: 대표 timestamp가 `0 <= t <= duration_sec`이고 normalized bbox `{x,y,width,height}` 한 개가 필수야. 모든 값은 finite number, `width>0`, `height>0`, 전체 box는 `[0,1]` 안에 있어야 해.
- `gecko_absent`: timestamp와 bbox는 반드시 null이야.
- `uncertain`: timestamp와 bbox는 반드시 null이고 negative 분모에서 제외해.
- `media_error`: timestamp와 bbox는 반드시 null이고 negative 분모에서 제외해.

positive control 여부, GME 결과, detector confidence, source key/hash, reviewer identity는 blind UI에 노출하지 않아. 최초 assignment는 exact `DEV_USER_ID` Owner 한 명뿐이야. 다른 reviewer는 이 문서의 frozen `approved_reviewer_ids`에 exact UUID가 사전승인되고 import schema가 그 assignment를 지원하기 전에는 배정 불가능해. 현재 v1 import는 Owner-only야.

## 5. 유효성·지표·판정

`valid random negative`는 random-negative item 중 최종 effective verdict가 `gecko_present|gecko_absent`이고 frozen media/lineage가 그대로인 항목이야. `confirmed negative miss`는 그중 `gecko_present`인 항목이야. `uncertain`, `media_error`, invalid input은 분자·분모에 넣지 않아.

- `negative_pool_gecko_prevalence = confirmed negative miss / valid random negative`
- 95% confidence interval은 Wilson score interval, `z = NormalDist().inv_cdf(0.975)`를 사용해.
- positive-control detection은 30개 전체 중 `gecko_present` 수를 별도로 기록해. negative prevalence에 합치지 않아.
- camera-night 값은 익명 descriptive aggregate만 기록하고 비교우위나 인과를 주장하지 않아.

판정 label은 정확히 다음 세 값뿐이야.

1. protected/lineage violation이 하나 이상이거나, valid random negative가 100 미만이거나, positive-control `gecko_present`가 27/30 미만이면 `INVALID_CALIBRATION`.
2. 위 invalid 조건이 없고 confirmed negative miss가 0이면 `AUDIT_VALID_NO_MISS`.
3. 위 invalid 조건이 없고 confirmed negative miss가 1개 이상이면 `AUDIT_VALID_MISSES_FOUND`.

어떤 label도 detector recall/FNR, checkpoint의 production 채택, queue/GT/GME 변경, Dataset 자동 편입, 재학습 또는 배포 승인을 뜻하지 않아.

## 6. Read/write allowlist

기본 `preflight`는 다음 read만 허용해.

- DB: Owner 존재 확인용 auth admin GET, `motion_clips`, `gme_jobs`, `gme_runs`, `motion_clip_consensus`, system exclusion의 bounded SELECT, control GT digest용 immutable `fn_gme_negative_audit_canonical_json` read RPC.
- R2: candidate object의 `HEAD`와 bounded `GET`.
- Local: exact `0700`·현재 uid·non-symlink attempt root를 `O_DIRECTORY|O_NOFOLLOW`로 열고 dev/inode를 pin한 뒤, 그 dirfd 기준으로 새 `0600`·single-link·`O_EXCL|O_NOFOLLOW` started/inventory/availability/complete 또는 failed artifact만 접근.

기본 mode에서 DB INSERT/UPDATE/DELETE/UPSERT, mutation RPC, R2 PUT/POST/DELETE/COPY, 기존 local artifact overwrite는 모두 금지야. known protected source/R2 identity의 HEAD/GET도 금지하고 실제 ledger가 0임을 확인해. phase 사이 root·inventory·marker·manifest의 inode, mode, uid, link count 또는 raw bytes가 바뀌면 manifest/import 전에 fail-closed해.

`import --apply`만 별도 허용되며 exact on-disk TEST-SHEET raw SHA-256, exact manifest raw SHA-256, `FROZEN`, Owner `APPROVED`, reviewed schema, Owner 존재를 모두 재검증한 뒤 `fn_create_gme_negative_audit_batch`를 정확히 한 번 호출해. 그 밖의 service write는 0이야.

## 7. Freeze section — execution-filled

| 항목 | 현재 값 |
|---|---|
| freeze status | `UNFROZEN` |
| Owner approval | `PENDING` |
| TEST-SHEET raw SHA-256 | `PENDING` |
| availability raw SHA-256 | `PENDING` |
| inventory raw SHA-256 | `PENDING` |
| manifest raw SHA-256 | `PENDING` |
| manifest canonical SHA-256 | `PENDING` |
| source random-negative count | `PENDING` |
| eligible random-negative count | `PENDING` |
| source positive-control count | `PENDING` |
| eligible positive-control count | `PENDING` |
| camera count | `PENDING` |
| camera-night count | `PENDING` |
| episode count | `PENDING` |
| unavailable reason aggregate | `PENDING` |
| frozen random negative / control / total | `PENDING / PENDING / PENDING` |
| protected overlap / near duplicate / lineage violation | `PENDING / PENDING / PENDING` |
| protected pre-GET identity exclusions / post-GET protected access ledger | `PENDING / PENDING` |
| DB writes / R2 writes / other service writes | `PENDING / PENDING / PENDING` |

availability를 본 뒤 표본 정의나 pin을 바꿔야 하면 이 attempt에서는 manifest를 만들지 않고 새 TEST-SHEET 승인과 새 attempt root를 사용해. failed/shortage attempt 안에서 clip을 교체하거나 기존 artifact를 삭제·덮어쓰지 않아.

## 8. Machine-readable freeze contract

아래 JSON은 CLI가 exact key set으로 읽는 부분이야. 현재는 의도적으로 `UNFROZEN/PENDING`이며 실제 실행값을 꾸며 넣지 않았어.

<!-- GME_NEGATIVE_AUDIT_MACHINE_CONTRACT_BEGIN
{"approved_reviewer_ids":["PENDING_DEV_USER_ID"],"checkpoint_sha256":"2b128f105e898bc472ed66861583ab80007dae6e94b291db497d7a2f8081f84a","control_count":30,"cutoff":"PENDING","detector_identity":"d4654168af21d26697ab1bd9a5dc4a05bd92baf5c9328800915cc347803d05b6","episode_cap":2,"freeze_status":"UNFROZEN","negative_count":120,"owner_approval":"PENDING","protected_manifest_sha256":{"future":"PENDING","internal-test151":"PENDING","owner-external60":"PENDING","validation153":"PENDING"},"reviewed_import_schema":"PENDING","schema_version":"gme-negative-audit-test-sheet-v1","seed":"gme-negative-audit-calibration-v1","selection_algorithm_version":"gme-negative-audit-selection-v1","training_manifest_sha256":"PENDING"}
GME_NEGATIVE_AUDIT_MACHINE_CONTRACT_END -->
