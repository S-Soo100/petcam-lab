# Camera 1 raw roi_mean Future Replication — Kickoff REPORT

## Verdict

`ROI_CAMERA1_REPLICATION_COLLECTING`

cutoff를 동결하고 collection status를 측정한 kickoff 정상 종료야. 동결 직후라 camera_1의
미래(=cutoff 이후) Owner 완료 GT가 아직 0건이라 최소 표본을 충족하지 못했어. 이건 blocker가
아니라 설계상 예상된 시작 상태야. discrimination verdict(`SUPPORTED / REJECTED /
INCONCLUSIVE`)는 최소 표본이 찬 뒤 별도 sample-lock 실행에서만 계산해.

## Frozen cutoff와 target identity

| 항목 | 값 |
|---|---|
| future_cutoff_utc | `2026-07-27T06:30:26.782541Z` |
| frozen_at_utc == future_cutoff_utc | 예 (동일 문자열) |
| target_camera_group | camera_1 |
| target_camera_count (재계산) | 1 |
| prior_target_owner_eligible_count | 71 |
| prior_owner_eligible_count | 172 |

target camera는 tracked 파일에 UUID로 박지 않고, 선행 benchmark와 동일한 deterministic 규칙
(Owner eligible cohort의 camera_id 오름차순 `dense_rank() = 1`)으로 재계산했어. 재계산 결과가
정확히 1대이고 그 camera의 prior count가 71, 전체 prior가 172라 camera identity drift가 없어.

## 현재 미래 표본 (cutoff 이후)

| class | clips | 5분 episodes | camera-nights |
|---|---:|---:|---:|
| moving | 0 | 0 | 0 |
| static-only | 0 | 0 | 0 |
| 합계 discrimination camera-nights | — | — | 0 |

| coverage 지표 | 값 |
|---|---:|
| owner_completed_clips (미래) | 0 |
| evidence_ready_clips | 0 |
| excluded_class_clips | 0 |
| provenance_mismatch_clips | 0 |
| evidence_ready_fraction | null (분모 0) |

feature 값(roi_mean), AUROC, CI, class별 분포는 sample lock 전이라 조회하지도 계산하지도
않았어. collection SQL은 roi_mean을 finite 여부(boolean)로만 쓰고 값 자체를 select/aggregate하지
않아.

## Evidence provenance 계약 (frozen 172 contract 정확일치)

이번 연구의 핵심 안전장치야. future evidence는 단순 distinct count가 아니라, 이전 Owner GT 172
cohort에서 재계산한 **frozen provenance contract에 tuple이 정확히 포함**될 때만 evidence-ready로
인정해.

| 지표 | 값 | 의미 |
|---|---:|---|
| frozen_provenance_contract_count | 1 | 172 cohort의 canonical provenance tuple이 정확히 1개 (선행 benchmark의 provenance contract=1과 일치) |
| provenance_contract_count (미래 ready) | 0 | 미래 ready clip이 아직 0건 |
| future_provenance_contract_match | true | provenance mismatch 0건 |

- provenance tuple은 9개 필드(`evidence_schema_version, algorithm_version, model_name,
  model_version, checkpoint_sha256, threshold, sampler_version, schema_version, frames_sampled`)
  concat이야. tuple 문자열 자체는 절대 output하지 않고 count로만 노출해.
- verifier가 `frozen_provenance_contract_count == 1`, `미래 ready ⊆ frozen`,
  `match flag == (mismatch==0)`을 강제해. 위반 시 `provenance_contract_drift`로 실패해.
- 만약 향후 재조회에서 frozen contract가 1이 아니게 되면 SQL이 verdict를
  `ROI_REPLICATION_HOLD_PROVENANCE_CONTRACT_DRIFT`로 내고 verifier도 막아.

## 최소 표본 미달 내역 (deficit)

동결된 6개 최소 predicate 전부 미달이야 (현재 전부 0).

| predicate | 필요 | 현재 | 부족 |
|---|---:|---:|---:|
| moving clips | 30 | 0 | 30 |
| static-only clips | 30 | 0 | 30 |
| moving episodes | 20 | 0 | 20 |
| static-only episodes | 20 | 0 | 20 |
| discrimination camera-nights (total) | 3 | 0 | 3 |
| moving/static 각 class camera-nights | 각 2 | 0 | 각 2 |

`minimum_met = false` → verdict `ROI_CAMERA1_REPLICATION_COLLECTING`.

## 6-table mutation 0

시작(`2026-07-27T06:29:48Z`)과 종료(`2026-07-27T06:31:48Z`)에 아래 6개 source table의
count와 ordered canonical fingerprint가 전부 동일했어 (timestamp만 다름).

| table | row_count | ordered_fingerprint_md5 |
|---|---:|---|
| motion_clips | 18080 | 1541166794ccb81551757634800e43cb |
| motion_clip_labeling_triage | 337 | ccfb59f9cd098b328a018cd7c8b9a0a5 |
| motion_clip_labeling_sessions | 174 | 2e61ae2dbb15f252532c34400aa2a34e |
| motion_clip_labeling_session_revisions | 0 | d41d8cd98f00b204e9800998ecf8427e |
| clip_python_evidence_runs | 4665 | 6244b1d2364b8b4bf5ad820447091663 |
| clip_prelabels | 8618 | b096800ebc3914497497f6d0beed1116 |

이 6개 fingerprint는 선행 Owner GT benchmark(`../owner-gt-python-evidence-benchmark-20260727`)의
시작 fingerprint와도 완전히 일치해 — 그 사이 이 6개 table에 아무 write가 없었다는 뜻이야. 이
mutation 0 증거는 위 6개 table + frozen Owner cohort 범위이며 DB 전체 무변경을 뜻하지 않아. 이번
작업은 production DB에 SELECT만 실행했어.

## Git 상태

- branch: `codex/roi-mean-camera1-replication-20260727`
- origin/main: `8e0d62b` (이 작업으로 건드리지 않음)
- 이번 kickoff 커밋 체인 (frozen design commit `f1d790c` 이후):
  - `c61fbb0` docs: TEST-SHEET 계약 동결 (cutoff 조회 전)
  - `ef5b87e` test: 수집 계약 검증기 + 테스트
  - `8eb918f` test: verifier SELECT-only SQL 가드
  - `70beb5b` chore: freeze/collection SQL 동결
  - `23408fd` test: future evidence provenance frozen 172 contract 정확일치 검증
  - `6983180` chore: 미래 수집 기준선 aggregate 기록
  - `b7def67` docs: kickoff 시작 보고 + HANDOFF 편입
  - (+ freeze-invariance 수정 커밋: historical_cohort cutoff 상한 + 회귀 테스트 + REPORT 정정)
- push 후 local HEAD == `@{upstream}`, tracked/untracked 잔여 변경 없음 (실행 로그는 아래 검증 절 참조).
- 실행 중 보였던 `HANDOFF.md` untracked는 전달자가 만든 예상 상태이며 이미 커밋에 포함해 정리했어.

## 검증 결과

- 실험 focused 테스트: `test_verify_collection.py` 18 passed (freeze-invariance 회귀 테스트 포함)
- 전체 프로젝트 스위트: `uv run pytest -q` → 832 passed, 3 skipped, 0 failed
- `git diff --check`: clean
- 독립 artifact 검증기: `verify_collection.py --root ...` → `COLLECTION_ARTIFACTS_OK`
  - freeze/status cutoff 문자열 동일 + UTC tz-aware, snapshot > cutoff
  - target camera_1 / prior 71 / target_camera_count 1
  - 모든 count 비음수 정수, evidence_ready ≤ owner_completed
  - frozen provenance contract == 1, 미래 ready ⊆ frozen, match flag 일치
  - **historical_cohort cutoff 상한 동결(미래 재실행 172/71/1 drift 차단, 주석 우회도 차단)**
  - minimum_met == 6 predicate 계산값, COLLECTING ↔ minimum_met false 일치
  - fingerprint 정확히 6개 table, (row_count, md5) 전부 동일
  - tracked artifact에 UUID/email/URL/원문 식별자 key 0, SQL SELECT-only

## Freeze-invariance 수정 (follow-up, 최초 리뷰 miss 정정)

최초 독립 리뷰(아래 Round 1)는 `APPROVED`였지만 **미래 재실행 동결 불변성 결함을 놓쳤어.** 사용자
최종 통합 검수에서 Important 결함으로 잡혔고, 같은 세션에서 TDD로 수정했어.

- **결함:** `collection-status.sql`의 `historical_cohort`가 eligibility predicate만 쓰고
  `mc.started_at` 상한이 없었어. kickoff 시점엔 post-cutoff 완료 GT가 0이라 172로 맞지만, 같은
  frozen cutoff로 **미래에 재실행하면 post-cutoff Owner 완료 GT가 historical_cohort에 섞여**
  `prior_owner_eligible_count`·target camera ranking/count·`frozen_provenance`가 drift해. 즉
  "frozen 172 contract"가 실제로 frozen이 아니었어.
- **수정(TDD):**
  1. regression test 먼저 추가 → 실제 committed `collection-status.sql`에 대해 RED
     (`frozen_cohort_unbounded historical_cohort_missing_upper_cutoff`)로 결함 실증.
  2. `historical_cohort`에 `AND mc.started_at <= :'future_cutoff_utc'::timestamptz` 상한 추가 →
     GREEN. 이 상한이 `target_camera`·`frozen_provenance`·`prior_target_owner_eligible_count`
     (모두 historical_cohort에서 파생)까지 전파돼 **모든 미래 재조회에서 172/71/1이 동결**돼.
  3. `future_owner_completed`는 그대로 `> :'future_cutoff_utc'` 하한 유지(미래 표본만).
  4. `verify_collection.py`에 `assert_historical_cohort_frozen` 추가하고 `verify()`가
     `collection-status.sql`에 대해 강제. 주석으로 상한을 위장하는 우회도 차단(주석 제거 후 검사).
- **재생성 불요(결과 무영향 증명):** kickoff 시점에 post-cutoff `owner_completed_clips=0` 실측 +
  `motion_clip_labeling_sessions` row_count가 start/end 모두 174 불변 → 172개 완료 clip이 전부
  `started_at <= cutoff` → bounded == unbounded == 172/71/1. 따라서 이미 commit된
  `collection-status.json`/`freeze-manifest.json`/fingerprint는 그대로 유효하고 재측정하지 않았어
  (정적 계약 수정이라 kickoff JSON 불필요 갱신 안 함). production DB에는 이 수정으로 SELECT/write
  어느 것도 실행하지 않았어.
- **freeze-cutoff.sql은 무경계 유지가 정상:** 이 파일은 kickoff에서 **1회만** 실행해 cutoff를
  `now()`로 정의하는 스냅샷이야. 자기가 만드는 now()로 자신을 bound하면 항상 참인 tautology라
  의미가 없어. 재실행 대상은 `collection-status.sql`뿐이고 거기만 상한이 필요해.

## 독립 리뷰

### Round 1 (초기) — ⚠️ 정정됨
- 리뷰어: fresh Claude subagent (read-only). 판정 `APPROVED`(Critical 0/Important 0/Minor 4).
- **한계:** 현재 시점 동일성만 확인하고 **미래 재실행 의미를 놓쳐** 위 freeze-invariance 결함을
  걸러내지 못했어. 이 APPROVED는 아래 Round 2로 대체돼.

### Round 2 (수정 후, 최종) — ✅ APPROVED
- 리뷰어: fresh Claude subagent (read-only), freeze-invariance 수정만 재검토.
- **판정:** `APPROVED` — Critical 0, Important 0, Minor 3.
- **확인:** historical_cohort 상한이 target_camera·frozen_provenance·prior counts로 전파돼 미래
  재실행에서 172/71/1 동결, future 하한 유지, regression+unit test+`verify()` 연결, freeze-cutoff.sql
  무경계는 정당(1회 정의), 재생성 불요 논증 타당.
- **Minor 3건 (fail-safe/문서, 코드 결함 아님):**
  1. `frozen_provenance`는 evidence run에 recency 필터가 없어 — pre-cutoff clip에 **새 evidence
     run**이 다른 provenance로 들어오면 contract count가 1→2가 될 수 있어. 하지만 이건 **pin이 아니라
     guard**라서 그 경우 SQL이 `ROI_REPLICATION_HOLD_PROVENANCE_CONTRACT_DRIFT`, verifier가
     `provenance_contract_drift`로 **정지(fail-safe)**해. Evidence 재실행 자체가 DESIGN §11 금지라,
     조용히 drift하지 않고 멈추는 게 오히려 옳음 → 의도적 설계, 코드 변경 안 함.
  2. `ROI_REPLICATION_HOLD_UNEXPECTED_MINIMUM_AT_KICKOFF` 방어 분기(기존, 진짜 kickoff 도달 불가,
     verifier가 minimum↔verdict 일치 별도 강제).
  3. 검사기 주석 우회 지적 → 이번에 주석 제거 후 검사로 **닫음**(테스트 추가).
- 이종 교차(donts #6)용 codex/gemini는 둘 다 외부 도구 문제로 불가(codex `gpt-5.6-sol` 버전 오류,
  Gemini 계정 tier 오류) — 내 산출물 문제 아님. 계획서가 허용한 fresh Claude subagent로 수행.
- 최종 재검증: focused 18 passed, 전체 832 passed/3 skipped/0 failed, `git diff --check` clean,
  `COLLECTION_ARTIFACTS_OK`(이제 frozen-cohort 상한 검사 포함).

## 실행하지 않은 것 (explicit non-actions)

- AUC/AUROC·CI·feature 분포·median/IQR 계산 없음 (sample lock 전)
- classifier fitting·모델 학습·threshold sweep·weight·feature 조합 없음
- normalization·duration correction·direction 반전·`max(AUC,1-AUC)` 없음
- selector·activity filter·자동 skip 변경 없음
- production DB write(INSERT/UPDATE/DELETE/RPC/DDL/migration) 없음 — SELECT만 실행
- R2 GET/write·signed URL 없음, Slack 없음
- Python Evidence·Gate·VLM 재실행 없음
- labeling web/API, Owner·labeler workflow 변경 없음
- LaunchAgent·runtime·deploy 조작 없음, main merge 없음

## 다음 액션 (재조회 조건)

1. 기존 서비스의 정상 Owner 라벨링을 그대로 유지해 camera_1의 cutoff 이후 완료 GT를 자연 적립해.
2. 새 camera_1 완료 GT가 쌓이면 계약을 바꾸지 않고 `collection-status.sql`만 같은 frozen
   cutoff(`2026-07-27T06:30:26.782541Z`)로 재실행해서 collection status를 갱신해.
3. 6개 최소 predicate(moving/static 각 30 clips·20 episodes, total 3 camera-nights, 각 class 2
   camera-nights)를 모두 충족하면 그때 별도 sample-lock 실행으로 raw AUROC·episode-cluster
   bootstrap(seed 20260727, 10,000)을 계산해 `SUPPORTED / REJECTED / INCONCLUSIVE`를 판정해.
4. `SUPPORTED`여도 production 채택이 아니라 두 camera future comparison TEST-SHEET 작성 근거만 돼.
   normalization은 별도 decision gate + dev/future holdout 분리가 필요해.

수집 기간 동안 결과를 추측하거나 normalization 연구로 건너뛰지 않아.
