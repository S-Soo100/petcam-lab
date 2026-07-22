# Local VLM Evidence B1R — 역사 Evidence 완주와 후보 배정 v2 설계

> **상태:** owner 방향 승인 / written spec 검토 대기
>
> **선행 판정:** `B1_BLOCKED_DATA_INSUFFICIENT`
>
> **목표:** 모델을 실행하기 전에, 과거 `motion_clips`의 Python Evidence 누락과 selector v1의 후보군 굶김을 분리해서 해소하고 6 strata × 30 episode 시험지를 다시 검증한다.

## 1. 왜 B1을 다시 해야 하나

B1은 모델 성능 시험이 아니었다. 모델을 시험할 180개 영상을 준비하는 단계였다. B1의 출력은
`absent=0 / big_move=14 / rest_micro=3 / lick=0 / wheel=0 / hardcase=47`이었고, 계약에 따라 B2를
멈춘 것은 옳다.

다만 `데이터가 없다`는 결론은 불완전하다. 2026-07-22 read-only 재감사에서 다음 두 원인이 분리됐다.

1. **역사 Evidence 누락:** `motion_clips` 16,781건 중 현재 identity의 성공 Python Evidence는 2,836건,
   약 16.9%다. 기존 사람 `behavior_logs`가 있는 motion clip 237건도 현재 Evidence와 교집합이 0이라
   semantic strata 입력으로 들어오지 못했다.
2. **selector v1 굶김:** raw predicate를 독립 적용하면 현재 Evidence 안에도 `absent` 347 clip/24 episode,
   `rest_micro` 639 clip/35 episode가 있다. 하지만 v1이 clip을 hardcase부터 단일 분류하고 episode도
   `hardcase > ... > absent` 순으로 한 번 배정해 B1 출력에서 0/3으로 축소했다.

따라서 B1R은 표본 기준을 낮추는 작업이 아니다. 입력 coverage와 배정 알고리즘을 바로잡고 같은 시험
계약을 다시 실행하는 작업이다.

## 2. 불변 계약

- 시험지는 **6 strata × 30 = 180 unique clip**을 유지한다.
- strata는 `absent`, `big_move`, `rest_micro`, `lick_water_food`, `wheel_object`, `hardcase`로 유지한다.
- 같은 clip과 같은 30분 episode는 전체 study에서 한 번만 사용한다.
- 각 strata 20개는 dev, 10개는 fresh holdout으로 유지한다.
- 사람 GT 전에 stratum, Python Evidence, Gate, activity, 기존 행동 GT, VLM·local model 출력을 숨긴다.
- 모델 다운로드·추론, B2 schema/API/UI, production GT write는 B1R 통과 전 금지한다.
- Python Evidence와 사람 행동값은 **retrieval 신호**일 뿐 evidence GT가 아니다.
- 결과를 본 뒤 episode 간격, 30개 수량, 성공 기준을 완화하지 않는다.

## 3. 접근 비교와 결정

### A. 촬영일·카메라만 더 쌓고 selector v1 재실행 — 기각

새 데이터가 늘어도 hardcase-first 단일 분류가 계속 희소 strata를 흡수한다. wheel·lick 신호가 있는 과거
clip에 Evidence가 없다는 문제도 해결하지 못한다.

### B. 현재 2,836 Evidence만으로 selector v2 적용 — 진단용만 허용

absent/rest 굶김은 개선할 수 있지만 전체 역사의 83.1%를 보지 않은 표본이다. 이 결과로 180개를
동결하면 최근 6일·3카메라 편향을 연구 설계에 고정한다.

### C. 역사 Evidence 완주 후 selector v2 재실행 — 채택

Universal Python Evidence의 `모든 motion_clips가 전처리를 거친다`는 제품 원칙을 먼저 이행한다. 그 뒤
각 clip의 여러 strata 적격성을 독립 계산하고, 전역 clip/episode 중복을 지키면서 부족한 strata부터
결정론적으로 배정한다.

## 4. 전체 흐름

```text
production coverage snapshot (SELECT-only)
    ↓
Mac mini runtime/HEAD/service 계약 확인
    ↓
역사 job dry-run → 30 clip canary → bounded enqueue/drain
    ↓
coverage closure audit (silent missing 0)
    ↓
selector v2 multi-match eligibility
    ↓
scarcity-first global allocation (clip/episode unique)
    ↓
B1R independent recomputation
    ├─ 6×30 충족 → manifest 180 생성, B2 계획 허용
    └─ 부족 → 부족 원인을 semantic acquisition으로 분리, B2 계속 금지
```

## 5. Phase R0 — runtime·coverage 정본 확정

### 5.1 runtime drift를 먼저 막는다

MacBook의 `/Users/baek/petcam-nightly-reporter` `main`이 실제 Mac mini runtime이라고 가정하지 않는다.
현재 로컬 main에는 Universal Evidence 구현 commit `618f4f8`이 조상으로 확인되지 않았다. 실행 전 handoff
validator와 Mac mini 실측으로 다음을 고정한다.

- hostname = `baeg-endeuui-Macmini.local`
- `com.petcam.python-evidence-worker` loaded 상태, WorkingDirectory, plist 환경변수
- Mac mini nightly/gate/lab 실제 HEAD와 `origin/main` ancestry
- active `evidence_schema_version=python-evidence-raw-v1`
- active `algorithm_version=croi-temporal-v1`
- feature flag, expected-host, Gate checkpoint·threshold, batch limit

HEAD가 문서와 다르거나 필요한 구현이 main에 없으면 backfill을 시작하지 않고 별도 FF-only 통합 검토로
멈춘다. expected-host 우회나 laptop 실행은 금지한다.

### 5.2 coverage snapshot

동일한 query watermark에서 `coverage_cutoff_started_at`을 고정하고, 이 시각 이하 clip만 역사 완주 분모로
사용한다. 그 뒤 들어오는 신규 clip은 live queue가 처리하며 B1R 분모를 실행 도중 움직이지 않는다. 다음
분모·분자를 저장한다.

- eligible: `duration_sec > 0`이고 `r2_key`가 비어 있지 않은 `motion_clips`
- job 상태: queued / processing / failed_retryable / failed_terminal / succeeded
- 성공 run: active schema+algorithm이고 `level0_status='ok'`
- terminal: allowlist failure_code별 수량
- silent missing: job도 active run도 없는 eligible clip
- camera/date별 eligible·run·terminal 수량

aggregate만 Git에 남기고 clip ID·R2 key·signed URL은 `storage/` 아래 gitignored artifact에 둔다.

## 6. Phase R1 — 역사 Python Evidence 완주

durable queue와 worker는 재사용한다. 새 분석 워커나 새 LaunchAgent를 만들지 않는다. 다만 현재
`enqueue_python_evidence_backfill.py`는 날짜 범위의 앞 N개를 다시 읽기 때문에, 그 N개에 job이 이미
있으면 후속 missing clip로 전진하지 못할 수 있다. R1 전에 keyset pagination으로 전체 범위를 순회하고
active job/run이 없는 clip만 최대 limit만큼 반환하도록 하드닝한다.

1. 전 날짜 범위를 `--dry-run`으로 먼저 계산한다.
2. 아직 active job/run이 없는 clip만 30건 enqueue해 canary를 수행한다.
3. canary는 run 생성, provenance 완전성, temp media 0, selector/VLM/GT/activity write 0을 확인한다.
4. 통과 후 날짜·started_at·id 오름차순 keyset으로 bounded enqueue한다. 한 enqueue 호출은 최대 500건이며
   기존 DB unique로 중복 job을 막는다. 같은 range를 반복해도 다음 missing clip로 진행해야 한다.
5. worker는 기존 live priority 100 > historical priority 10과 공통 Gate lock을 유지한다. 한 프로세스만
   처리하고 permanent 새 drain service는 추가하지 않는다.
6. drain 중 다음 조건이면 즉시 중단한다.
   - live job lag p95가 15분을 초과
   - worker nonzero 또는 failure가 직전 두 cycle 연속 증가
   - temp media 잔류
   - selector/VLM/GT/activity 테이블 mutation
   - runtime HEAD·plist·expected-host drift

완료 조건은 queue가 비어 보이는 것이 아니라 다음 등식이다.

```text
eligible = succeeded_with_active_run + allowlisted_terminal
silent_missing = 0
queued + processing + failed_retryable = 0
```

`failed_terminal`은 성공 Evidence로 위장하지 않는다. 이유별 수량과 대표 clip review link를 보고한다.

## 7. Phase R2 — selector v2

새 identity는 `local-vlm-evidence-selector-v2`다. v1 artifact와 SHA를 덮어쓰지 않는다.

### 7.1 multi-match eligibility

clip 하나에 단일 stratum을 즉시 부여하지 않는다. 여섯 predicate를 각각 평가해
`eligible_strata: set[str]`와 stratum별 reason code를 만든다.

- hardcase 적격 clip도 실제 신호가 있으면 absent/rest/lick/wheel/big에 동시에 적격일 수 있다.
- 사람 `behavior_logs`와 current GT는 clip ID 직접 연결을 우선하고, 검증된 exact `r2_key` 연결은 별도
  provenance로만 허용한다. fuzzy filename/time join은 금지한다.
- 사람 신호는 lick/wheel 후보 retrieval에만 쓰며 사람 evidence 답으로 복사하지 않는다.
- 모델 prediction/reasoning은 입력하지 않는다.

### 7.2 episode 대표 후보

camera별 rolling 30분 episode는 그대로 계산한다. 각 `(episode, stratum)`에서 해당 stratum 정렬 규칙으로
대표 clip 1개를 만든다. 여기까지는 같은 episode가 여러 strata의 잠정 후보가 될 수 있다.

### 7.3 scarcity-first global allocation

최종 배정에서는 clip과 episode를 전체 study에서 한 번만 쓴다.

1. 각 stratum의 미배정 적격 episode 수를 계산한다.
2. 수가 가장 적은 stratum부터 한 자리씩 배정한다.
3. 동률은 frozen `STRATA` 순서로 결정한다.
4. stratum 안에서는 기존 deterministic sort와 camera/date round-robin을 사용한다.
5. 하나를 배정하면 같은 clip과 episode를 다른 strata 후보에서 제거하고 scarcity를 다시 계산한다.
6. 각 stratum이 30개가 되거나 더 배정할 후보가 없을 때 종료한다.

이 방식은 hardcase를 없애는 것이 아니라, 어디에나 들어갈 수 있는 hardcase가 lick/wheel/absent 같은
희소군을 먼저 빼앗지 못하게 한다.

## 8. Phase R3 — B1R 판정

### 8.1 판정 namespace

- `B1R_DATA_AVAILABLE`: 6 strata 모두 30 unique clip/episode 충족
- `B1R_BLOCKED_EVIDENCE_COVERAGE`: R1 완료 등식 불충족
- `B1R_BLOCKED_SEMANTIC_DATA`: coverage는 완주했지만 lick/wheel 등 실제 적격 episode가 30 미만
- `B1R_REJECT_INTEGRITY`: 중복, SHA 불일치, 독립 재계산 불일치, 금지 입력·write 발견
- `B1R_BLOCKED_RUNTIME_DRIFT`: Mac mini host/HEAD/service 계약 불일치

### 8.2 성공 시

- 180 manifest를 새 selector version과 새 pool SHA로 생성한다.
- camera≥2, date≥3, clip/episode/split 교집합 0을 확인한다.
- 독립 구현이 같은 180개와 같은 SHA를 재계산해야 한다.
- B2는 자동 실행하지 않고 owner 검토 후 새 handoff만 허용한다.

### 8.3 semantic 부족 시

계약을 낮추거나 다른 strata clip을 복사하지 않는다. 부족 strata와 필요한 episode 수를 보고하고 다음 중
가장 작은 데이터 작업으로 분리한다.

- 기존 사람 라벨이 있으나 Evidence만 없었던 경우: R1 누락 버그로 되돌아간다.
- 실제 wheel/lick episode가 부족한 경우: 해당 행동만 owner가 선별·촬영·라벨링하는 별도 handoff를 만든다.
- absent/rest가 부족한 경우: threshold를 결과에 맞춰 바꾸지 않고 predicate validity를 별도 blind sample로
  검증한다.

## 9. 오류·안전 경계

- backfill 중 capture·앱·정규 VLM을 hard-block하지 않는다.
- service_role secret, R2 key, signed URL, raw DB exception을 보고서·Slack·Git에 남기지 않는다.
- append-only run을 UPDATE/DELETE하지 않는다. 잘못된 algorithm은 새 version으로만 교체한다.
- terminal clip 재처리는 원인과 forward fix가 있을 때만 새 승인으로 수행한다.
- probe와 selector는 SELECT-only다. history enqueue만 승인된 DB write이며 `python_evidence_jobs` 외 테이블을
  쓰지 않는다.
- 실패 보고에는 clip8과 failure code를 제공한다. exact motion→camera mapping과 기존 owner-authorized
  label route가 확인된 clip만 review URL을 붙인다. mapping이 없는데 URL을 꾸미거나 R2 경로를 직접
  노출하지 않는다. motion clip 전용 review route 신설은 B2 범위라 B1R에서 하지 않는다.

## 10. 검증 계약

### 10.1 TDD

- v1 single-class가 hardcase로 흡수하던 absent/rest fixture가 v2 multi-match에 함께 포함됨
- scarcity-first가 희소군을 먼저 채우고 clip/episode 중복 0 유지
- 입력 순서를 섞어도 candidate bytes·SHA 동일
- 동률 배정이 frozen STRATA와 clip ID tie-break로 동일
- exact human join만 허용하고 fuzzy join 거부
- 모델 출력 필드가 SourceRow에 들어오면 실패
- coverage closure 등식과 terminal 분리
- 기존 job이 앞쪽을 채운 날짜 range에서도 enqueuer가 다음 missing clip로 전진
- `coverage_cutoff_started_at` 이후 신규 live clip이 역사 분모를 바꾸지 않음

### 10.2 production read-only 재검증

- coverage snapshot을 서로 다른 쿼리/집계 구현으로 독립 대조
- v1과 v2를 같은 snapshot에서 나란히 출력
- raw predicate → episode representative → final allocation 수량을 단계별 공개
- per-stratum camera/date 분포와 single-camera 비율 공개
- pool/manifest SHA 독립 재계산 일치

### 10.3 금지동작 감사

- model download/inference 0
- VLM/behavior label/GT/app activity write 0
- production B2 migration/API/UI 0
- MacBook worker/expected-host 우회 0
- committed media/R2 key/clip-level artifact 0

## 11. 작업 경계와 순서

1. 이 설계와 decision-gate를 owner가 검토한다.
2. 별도 구현계획은 `R0 runtime audit → R1 backfill → R2 selector v2 → R3 B1R` 순서로 작성한다.
3. R0/R1은 Mac mini handoff가 필요하고, R2는 isolated feature worktree에서 TDD한다.
4. R1 완료 전 R2 shadow 계산은 진단용으로만 허용하며 최종 manifest를 만들지 않는다.
5. B1R 통과 전 B2·모델 실행은 계속 금지한다.
