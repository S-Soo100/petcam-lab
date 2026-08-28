# YOLO26n v2.6 최근 연속영상 촘촘 재학습 실행 계획

> 설계: `docs/superpowers/specs/2026-08-26-yolo26n-v26-recent-dense-retraining-design.md`
>
> **2026-08-28 Owner 결정:** 진행 중인 warm/clean 3-seed, 총 6회 학습은 중단하거나 단축하지 않고 2026-08-30 전후까지 완료한다. 평가 기준을 통과한 v2.6은 심각한 야간 미탐이 있는 v2.5를 대신해 active GME shadow·라벨링 웹 보조에 가역적으로 먼저 반영하고, 일주일·9개 사육장·하루 약 12시간의 prospective 촬영분은 v2.7 대규모 학습과 별도 sealed holdout으로 분리한다.

## Task 1 — read-only source freeze

- KST window와 DB 566개, 접근 가능 429개, 55초 미만 tombstone 137개 identity를 private manifest로 동결한다.
- camera/day/size/duration/GME lineage aggregate를 독립 재계산하고, exact clip set의 GME status가 전부 `succeeded`인지 확인한다.
- 기존 train/val/test/future-holdout fingerprint와 overlap 검사를 준비한다.

## Task 2 — dense extractor TDD

- 2fps timestamp 생성, exact frame identity, 조기 decode failure, reported/decoded count, source drift와 resume 계약 테스트를 먼저 작성한다.
- 원본을 한 번에 하나씩 스트리밍 decode하는 extractor를 구현한다.
- 선택되지 않은 JPEG는 남기지 않고 raw ledger만 보존한다.

## Task 3 — deterministic queue selector TDD

- every-clip 2-frame coverage를 강제한다.
- coverage 858 / uncertainty 900 / hard-negative 후보 350 / IID random 400 / gold double-review 200 계약을 검증한다.
- feedback band, transition, motion-with-low-confidence, persistent detection, scene change strata를 합친다.
- exact/dHash/temporal dedup과 per-clip/camera-night cap을 검증한다.
- protected overlap과 split leakage를 fail closed로 거부한다.

## Task 4 — TEST-SHEET, Claude pre-review와 MacBook runtime freeze

- 데이터 접근 전에 window, strata, split, 10fps temporal rule, metric, stop rule을 TEST-SHEET에 고정한다.
- Claude는 코드·계약·테스트만 read-only 교차검수한다.
- MacBook Pro M5/32GB, MPS, package version, source code SHA를 private runtime manifest에 고정한다.
- 맥미니 GME service와 active checkpoint는 읽기 전용 provenance 확인만 한다.

## Task 5 — MacBook source read와 blind queue 생성

- 상태: 완료. primary 2,508장, double-review 200장, 429 clip coverage와 protected overlap 0을 확인했다.
- R2 원본은 맥북 private temp에 순차적으로 내려받고 매 clip 처리 후 제거한다.
- 접근 가능한 429개 전체의 2fps raw ledger를 만든다.
- 목표 2,508개 고유 이미지와 200개 double-review task의 no-overwrite CVAT ZIP/private review index를 만든다.
- 원본, DB, R2, service, active checkpoint를 수정하지 않는다.

## Task 6 — 사람 presence/bbox 검수

- 상태: 완료. primary 2,508장, double-review 200장과 Owner adjudication을 최종 GT로 확정했다.
- prediction을 숨긴 채 present/absent/uncertain/media_error를 판정한다.
- present에는 bbox를 필수로 그린다.
- 10% 독립 QA와 Owner adjudication을 완료한다.
- 최종 GT와 QA artifact의 exact SHA 검증 완료 전 training 시작을 금지한다.

## Task 7 — dataset v2.6 build

- 사람 승인 GT와 기존 v2.5 replay를 결합한다.
- final GT는 원본 primary/double-review/adjudication export와 review/selection 원장의 SHA에 다시 묶고, confirmed-empty `>=700`, 비율 `>=35%`, camera-night별 negative 존재를 재검증한다.
- reserve 교체 frame은 원래 selection SHA와 실제 dense ledger row/SHA를 함께 확인하고, 계산된 double-review conflict 전부가 adjudication index에 포함됐는지 집합 비교한다.
- 신규 recent cohort를 60초 인접 episode group 기준 `80:20`으로 나누고, camera-night 층화와 같은 camera-night·5분 이내 cross-split dHash `<=8` 검사를 수행한다.
- dense completion의 source SHA를 결합해 같은 source bytes가 train/validation으로 갈라지지 않게 한다.
- selection → enriched join completion → dense completion → source window의 raw file SHA와 lineage SHA를 연속 검증한다.
- v2.5 replay integrity 원장으로 train/val/test의 모든 image·label bytes를 전수 재검증한다.
- empty label, bbox bounds, image/label SHA와 aggregate를 독립 검증한다.

## Task 8 — warm/clean comparison training

- 상태: 실행 중. 학습 repository HEAD와 dataset/initializer/runner SHA를 고정한 채 6회를 순차 실행하며, 문서 변경은 별도 worktree/branch에서만 수행한다.
- v2.5 warm-start와 YOLO26n clean-reference를 공통 `epochs=100 / patience=20 / lr0=0.001` recipe, seed 26/27/28의 fresh path에서 실행한다.
- 실행 직전 repository HEAD, manifest, data.yaml, initializer와 모든 image/label SHA를 다시 확인한다.
- YOLO entrypoint SHA와 해당 runtime Python의 승인 package 버전/MPS 상태도 lock 전후에 확인한다.
- results.csv, best.pt, completion manifest를 no-overwrite로 남긴다.

## Task 9 — evaluation freeze

- 신규 validation에서 precision/recall/specificity/camera strata를 재계산한다.
- 합격 후보만 threshold/NMS와 10fps `3-of-5` temporal rule을 동결한다.
- frame metric 외에 clip-level TP/FP/FN, false-positive clip rate, episode cluster bootstrap CI를 계산한다.
- old fixed-test로 regression만 확인한다.

## Task 10 — sealed future holdout

- detector threshold·NMS·10fps temporal rule freeze 이후 `환경별 파충류 행동량 연구 문서화` 촬영분의 첫 3개 complete camera-night을 예약하고, 최소 300 clip·1,200 frame의 사람 blind holdout을 만든다.
- source video SHA, camera, 촬영 시작·종료, 사육환경 유형과 익명 개체·사육장 key를 동결하고 같은 camera-night이 development에 섞이면 fail closed다.
- 선택 후보를 정확히 한 번 평가한다.
- validation과 old regression을 통과한 v2.6은 Owner의 2026-08-28 승인에 따라 active GME shadow·라벨링 웹 보조에 먼저 반영할 수 있다. v2.5 checkpoint를 롤백용으로 보존하고 자동 삭제·skip·사람 정답·사용자 활동량 지표에는 사용하지 않는다.
- sealed future holdout 통과 전에는 production 성능 채택이나 사용자 지표 승격을 주장하지 않는다.

## Task 11 — v2.7 prospective training handoff

- 목표 source는 일주일 동안 9개 사육장을 하루 약 12시간씩 촬영한 원본이며 계획 상한은 약 756 enclosure-hours다. 실제 수량은 녹화 완료 후 USB/R2/DB manifest와 재생 가능 시간·SHA를 대조해 확정한다.
- freeze 전에 촬영된 설치 canary·30분 테스트·야간 영상은 사람 presence/bbox 검수 후 v2.7 development 후보로 넘긴다.
- sealed future holdout source·frame은 v2.7 학습에서 영구 제외한다.
- holdout 평가 뒤 새로 촬영한 영상과 별도 development cohort의 오탐·미탐을 camera-night group 단위로 train/validation에 배치한다.
- 모든 source를 inventory에 포함하되 연속 frame을 그대로 전량 학습하지 않는다. 사육장·night coverage, presence/absence, 야간 IR, 가림, 정지/이동, hard-negative와 v2.6 오류 strata를 균형 있게 뽑고 exact/dHash/시간 중복을 제거한다.
- v2.6 prediction은 queue 우선순위에만 사용하며 사람 확정 presence/bbox만 GT로 인정한다. split의 최소 단위는 enclosure-night이고 같은 사육장·같은 밤은 한 split에만 둔다.
- 행동량 연구의 행동명·이동거리·환경군 판정과 YOLO presence/bbox GT를 분리한다.
- 기존 USB/R2/DB 원본은 수정하지 않고 별도 private attempt에서 lineage·dedup·split 검사를 통과한 자료만 dataset build에 사용한다.

## Task 12 — v2.6 빠른 가역 반영과 v2.7 오류 회수

- 6회 학습 완료 후 development validation에서 최적 후보와 threshold/NMS/10fps temporal rule을 고정하고 old fixed-test regression을 확인한다.
- 통과한 v2.6 checkpoint·detector identity·serve preprocessing을 immutable manifest로 묶은 뒤 active GME shadow와 라벨링 웹 보조 표시에 반영한다.
- v2.5 checkpoint와 runtime 계약을 롤백 가능하게 보존하고, canary에서 identity·산출물·표시 계약이 어긋나면 재학습으로 덮지 말고 v2.5로 되돌린다.
- 반영 뒤 사람이 제보한 미탐·오탐·bbox 오류를 source/frame provenance와 함께 v2.7 hard-case queue로 모은다. 같은 오류를 자동 GT로 승격하지 않는다.

## Task 13 — 공개 `/gecko-detector` v2.6 worker 연결

- 선행 조건은 6회 학습 완료, development evaluation freeze 통과, old fixed-test regression 통과, immutable v2.6 checkpoint/identity/serve manifest다. 학습 중인 후보나 중간 `best.pt`를 연결하지 않는다.
- 현재 production의 `FakeGeckoDetectionProvider` + local limiter `503`을 read-only baseline으로 재확인하고, 기존 Preview worker adapter를 v2.6 identity에 맞춰 재사용한다. Vercel에서 모델을 직접 실행하지 않는다.
- 공개 API와 worker 양쪽에서 단일 파일, JPEG/PNG/WebP 10 MiB, MP4/WebM 50 MiB, 영상 최대 60초, magic byte, 10fps 상한, 분산 rate limit을 검증한다.
- 이미지/영상 canary에서 checkpoint SHA·detector identity·threshold/NMS·serve preprocessing, bbox overlay, 빈 검출, timeout/unavailable와 잘못된 응답의 fail-closed 처리를 확인한다.
- `training_consent=false`는 no-store inference만 허용한다. `true`도 Owner 검수 전 candidate로만 저장하며 자동 GT·Dataset membership을 만들지 않는다. 임시 media와 artifact TTL·삭제 주체를 배포 manifest에 고정한다.
- GME 운영 queue와 공개 upload queue의 resource/timeout 경계를 분리하고, 공개 요청 폭주가 저장영상 분석을 막지 않는 canary를 통과한 뒤 production alias를 반영한다.
- 배포 뒤 실제 사진·짧은 영상 각 1건의 response model version과 overlay를 확인하고, identity/checkpoint 불일치 또는 worker unavailable이면 공개 inference를 즉시 fail closed 상태로 되돌릴 수 있게 한다.
