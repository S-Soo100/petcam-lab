# Local VLM Evidence B1R2 — R2 Media Availability 설계

> **상태:** owner 방향 승인 / written spec 검토 대기
>
> **선행 판정:** `B1R_BLOCKED_EVIDENCE_COVERAGE`
>
> **목표:** R2 object가 실제로 남아 있는 clip만 역사 Evidence 복구 대상으로 삼되, 삭제된 원본을 숨기지 않고 별도 `source_expired`로 보존하여 Python Evidence coverage와 selector v2를 정직하게 다시 판정한다.

## 1. 확인된 문제

B1R은 selector v1의 굶김을 v2 multi-match + scarcity-first로 해소했다. 같은 snapshot의 독립 재계산도
일치했다. 하지만 역사 backfill canary는 가장 오래된 30건 중 28건이 `r2_download_failed`였고, 표본
HEAD 조회에서 2026-06-17·06-22 object는 없고 2026-07-02 이후 표본은 있었다.

현재 coverage audit의 `eligible`은 `duration_sec > 0`과 DB `r2_key` 존재만 본다. R2 lifecycle로 object가
삭제되어도 DB key는 남으므로, 처리 불가능한 clip이 `silent_missing`에 계속 포함된다. 따라서 반복
enqueue로 coverage를 닫으려는 시도는 무의미한 재시도와 false blocker를 만든다.

다음 두 표현은 아직 사실로 확정하지 않는다.

- R2의 정확한 보존기간이 30일이라는 주장
- 모든 과거 영상 또는 특정 날짜 이전 영상이 일괄 소실됐다는 주장

B1R2는 날짜를 추정하지 않고 현재 bucket inventory를 직접 읽어 실제 존재 여부를 고정한다.

## 2. 접근 비교와 결정

### A. R2 `list_objects_v2` inventory 1회 + DB in-memory join — 채택

bucket을 pagination으로 한 번 순회하고 object key set을 메모리에서 DB `motion_clips.r2_key`와 대조한다.
현재 규모에서는 요청량이 작고, 날짜 cutoff 추정보다 정확하며, 1만 건 이상의 개별 HEAD보다 싸다.

### B. 모든 DB clip에 `head_object` 실행 — 기각

정확하지만 clip 수만큼 요청이 발생한다. inventory 결과가 애매하거나 목록과 GET 사이 race를 진단할
때 bounded 표본 검증으로만 사용한다.

### C. 관측된 날짜를 cutoff로 사용 — 기각

삭제 경계가 camera/prefix별로 다르거나 lifecycle 실행 시각에 걸치면 false available/expired를 만든다.
날짜는 결과 집계 축이지 availability 판정 입력이 아니다.

## 3. 불변 계약

- 고정 history cutoff는 B1R의 `2026-07-22T02:45:33+00:00`을 재사용한다.
- Evidence identity는 `python-evidence-raw-v1` + `croi-temporal-v1`을 유지한다.
- selector identity는 `local-vlm-evidence-selector-v2`를 유지한다.
- 시험 계약은 6 strata × 30, dev 120 / holdout 60, clip·30분 episode 전역 중복 0이다.
- 기존 성공 Evidence는 원본 media가 현재 없어도 유효한 append-only 사실로 보존한다.
- media가 없는 clip을 성공이나 Evidence 완료로 세지 않는다.
- R2 inventory, coverage audit, selector probe는 read-only다.
- 승인된 write는 forward migration, media-available canary/history job enqueue, 기존 worker의 정상
  append-only run뿐이다.
- 모델 다운로드·local/Claude/Groq VLM 호출, GT·behavior·activity·앱 결과 변경, B2 API/UI는 금지한다.
- R2 key, signed URL, secret, per-clip availability는 Git과 Slack에 남기지 않는다.

## 4. Coverage 정본

고정 cutoff 이하이고 `duration_sec > 0`, DB `r2_key`가 비어 있지 않은 clip을 `study_total`로 둔다.
각 clip은 다음 우선순위로 정확히 한 상태에 속한다.

1. `evidence_succeeded`: active identity의 `level0_status='ok'` run 존재. R2 현재 존재 여부와 무관하다.
2. `media_available_open`: run은 없고 R2 object가 존재하며 queued/processing/failed_retryable job 존재.
3. `media_available_silent`: run은 없고 R2 object가 존재하며 active job도 없다.
4. `media_available_terminal`: R2 object는 존재하지만 deterministic decode/compute terminal job 존재.
5. `source_expired`: run은 없고 R2 inventory에 object가 없다. DB key가 남아 있어도 복구 불가능하다.

다음 등식이 항상 성립해야 한다.

```text
study_total
  = evidence_succeeded
  + media_available_open
  + media_available_silent
  + media_available_terminal
  + source_expired
```

`recoverable_total`은 `source_expired`를 제외한 합이다. `recoverable_coverage_closed`는
`media_available_open=0`과 `media_available_silent=0`일 때만 참이다. `source_expired`는 분모에서 조용히
삭제하지 않고 수량·camera/date 분포를 별도 공개한다.

## 5. R2 inventory 계약

### 5.1 snapshot

- 기존 `backend.r2_uploader.get_r2_client()`와 `get_r2_bucket()`을 재사용한다.
- `list_objects_v2` paginator로 production clip prefix를 끝까지 읽는다.
- `.mp4`이고 size가 0보다 큰 object만 available key set에 넣는다.
- inventory 시작·종료 시각, object 수, 총 byte, pagination 수를 기록한다.
- DB query watermark와 R2 inventory watermark를 함께 기록한다.
- 목록 조회 중 오류나 truncated pagination 계약 위반은 fail-closed한다. 일부 목록으로 판정하지 않는다.

### 5.2 artifact 경계

Tracked aggregate에는 상태별 수량, camera/date 분포, available/expired 비율, SHA만 둔다. Per-clip
manifest는 `storage/local-vlm-evidence-analyst/b1r2/` 아래 gitignored JSONL로 두며 다음만 포함한다.

- clip ID
- camera ID
- started_at
- availability 상태
- source date

R2 key 자체는 private artifact에도 복제하지 않는다. DB에서 필요한 실행 시점에 다시 조회한다.
정렬된 `(clip_id, availability)` 쌍의 SHA-256으로 aggregate와 private manifest의 연결을 고정한다.

### 5.3 독립 검증

주 구현을 import하지 않는 stdlib 재계산기가 private manifest와 tracked aggregate를 다시 계산한다.
추가로 camera/date strata에서 bounded 표본을 뽑아 HEAD 존재 여부가 inventory 판정과 일치하는지 확인한다.
HEAD는 inventory 전체를 대신하지 않으며, 일치성 검사용 표본으로만 쓴다.

## 6. 실패 분류 하드닝

현재 worker는 모든 R2 download 예외를 `r2_download_failed` retryable로 처리한다. 다음처럼 분리한다.

- HTTP 404 / `NoSuchKey` / 명시적 object missing: `source_media_missing`, terminal 즉시 처리
- timeout / connection / 429 / 5xx: `r2_download_failed`, retryable 유지
- 인증·권한 오류: `r2_access_denied`, terminal + cycle nonzero. secret 원문은 출력하지 않는다.
- 분류할 수 없는 download 오류: 기존 `r2_download_failed`, retryable 유지

새 failure code는 기존 migration을 수정하지 않고 forward-only migration으로 CHECK allowlist에 추가한다.
Python allowlist와 DB CHECK는 같은 테스트에서 1:1로 고정한다. 기존 28개 canary job을 강제 수정하거나
삭제하지 않는다. 자연 terminal 상태는 감사하되 재큐잉하지 않는다.

## 7. Media-available canary

canary 입력은 `media_available_silent`에서만 뽑는다. 가장 오래된 순으로만 뽑지 않는다.

1. camera/date episode를 만든다.
2. camera/date round-robin으로 30개를 결정론적으로 고른다.
3. 가능하면 camera 2대 이상, 날짜 3개 이상을 요구한다. 가용 pool이 이를 충족하지 못하면 분포를
   그대로 보고하고 canary를 확대해 성공처럼 보이지 않는다.
4. 선택 직전 bounded HEAD로 object가 여전히 존재하는지 재확인한다.
5. historical priority 10으로 30건만 enqueue한다.
6. 기존 Mac mini worker로 처리하고 run/provenance/temp/live lag를 검증한다.

canary 성공 조건:

- selected=30, active run 생성 또는 기존 run 재사용 합계 30
- `source_media_missing=0`, retryable download failure=0
- temp media 0
- live queue lag p95 ≤15분
- selector/VLM/GT/behavior/activity/app write 0
- runtime host/HEAD/service drift 0

한 건이라도 실패하면 bulk backfill은 시작하지 않고 원인별로 보고한다.

## 8. Bounded history backfill

canary 통과 후에만 private manifest의 `media_available_silent` clip ID를 입력 allowlist로 사용한다.

- 한 enqueue 호출 최대 500건
- live priority 100 > history 10 유지
- 기존 unique job identity로 중복 생성 0
- 매 cycle 후 inventory SHA, processed/open/terminal, live lag, temp를 확인
- lifecycle race로 새 404가 나오면 `source_media_missing` terminal로 닫고 source-expired delta에 더한다.
- 고정 manifest를 다 소진하면 새 inventory를 자동 생성하지 않는다. 재감사는 별도 실행이다.

완료 조건:

```text
media_available_open = 0
media_available_silent = 0
private_manifest_missing = 0
runtime_drift = 0
```

## 9. Selector v2 재판정

backfill이 닫힌 뒤 같은 cutoff와 selector v2로 후보를 다시 계산한다. 다음을 모두 공개한다.

- six-strata raw clip / 30-minute episode / final allocation 수량
- camera/date 분포와 single-camera 비율
- clip overlap 0, episode overlap 0
- pool SHA와 독립 재계산 결과
- `source_expired` 때문에 영구 관측 불가능한 camera/date 분포

6×30을 충족하지 못하면 coverage와 semantic 부족을 분리한다. 특히 현재 `lick/wheel=0`,
`big_move=8`은 backfill 이후에도 부족할 수 있다. 결과에 맞춰 stratum 기준이나 30개 목표를 낮추지 않는다.

## 10. 판정 namespace

- `B1R2_MEDIA_AUDIT_VERIFIED`: inventory·DB join·독립 SHA·HEAD 표본 일치
- `B1R2_BLOCKED_INVENTORY_INTEGRITY`: pagination/partition/SHA/HEAD 불일치
- `B1R2_BLOCKED_RUNTIME_DRIFT`: Mac mini host/HEAD/service 계약 불일치
- `B1R2_CANARY_REJECTED`: media-available canary 30건 중 실패 발생
- `B1R2_RECOVERABLE_COVERAGE_CLOSED`: recoverable coverage 완료, selector 재판정 가능
- `B1R2_BLOCKED_SEMANTIC_DATA`: recoverable coverage 완료 후에도 6×30 미충족
- `B1R2_DATA_AVAILABLE`: recoverable coverage 완료 + 6×30·독립 재계산 통과

판정은 단계별로 누적한다. inventory가 verified됐다고 backfill이나 B2를 자동 시작하지 않는다.

## 11. 테스트와 안전 검증

- R2 pagination 1000건 초과·빈 page·중간 오류
- DB key 있음/R2 없음, R2 있음/DB 없음, size 0, active run + R2 없음 partition
- 다섯 coverage 상태의 상호배타성과 합계 등식
- key와 secret이 aggregate/log에 없는지 정적 검사
- manifest 입력 순서를 섞어도 SHA와 canary 30개 동일
- camera/date round-robin과 clip/episode 중복 0
- 404 terminal, 403 terminal, timeout/5xx retryable 매핑
- DB failure-code CHECK와 Python allowlist drift 0
- inventory allowlist 밖 clip enqueue 0
- feature/runtime host guard와 live priority 회귀
- 독립 recompute가 주 구현을 import하지 않고 같은 aggregate/SHA 계산

## 12. Stop Point

1. 먼저 read-only inventory audit와 독립 검증을 완료한다.
2. inventory가 verified된 경우에만 failure 분류 forward migration과 worker 하드닝을 검토한다.
3. migration probe와 Mac mini canary가 통과해야 bulk backfill을 허용한다.
4. selector v2 재판정 후 결과와 무관하게 정지한다.
5. `B1R2_DATA_AVAILABLE`이어도 Local VLM 모델 실행·B2 evidence GT 웹 작업은 owner/Codex 검수와 새
   handoff 전까지 금지한다.
