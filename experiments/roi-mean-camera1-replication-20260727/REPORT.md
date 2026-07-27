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
  - (+ 이 REPORT 커밋)
- push 후 local HEAD == `@{upstream}`, tracked/untracked 잔여 변경 없음 (실행 로그는 아래 검증 절 참조).
- 실행 중 보였던 `HANDOFF.md` untracked는 전달자가 만든 예상 상태이며 최종 커밋에 포함해 정리했어.

## 검증 결과

- 실험 focused 테스트: `test_verify_collection.py` 14 passed
- 전체 프로젝트 스위트: `uv run pytest -q` → 832 passed, 3 skipped, 0 failed
- `git diff --check`: clean
- 독립 artifact 검증기: `verify_collection.py --root ...` → `COLLECTION_ARTIFACTS_OK`
  - freeze/status cutoff 문자열 동일 + UTC tz-aware, snapshot > cutoff
  - target camera_1 / prior 71 / target_camera_count 1
  - 모든 count 비음수 정수, evidence_ready ≤ owner_completed
  - frozen provenance contract == 1, 미래 ready ⊆ frozen, match flag 일치
  - minimum_met == 6 predicate 계산값, COLLECTING ↔ minimum_met false 일치
  - fingerprint 정확히 6개 table, (row_count, md5) 전부 동일
  - tracked artifact에 UUID/email/URL/원문 식별자 key 0, SQL SELECT-only

## 독립 리뷰

- **리뷰어:** fresh Claude subagent (read-only, 이 실행 맥락을 못 본 신선한 컨텍스트).
  - 이종 교차(donts #6)용 codex/gemini는 둘 다 도구 인프라 문제로 불가였어: codex CLI는
    `gpt-5.6-sol requires a newer version of Codex` 버전 오류, Gemini CLI는 계정 tier
    (`IneligibleTierError, UNSUPPORTED_CLIENT`) 오류. 내 산출물 문제가 아니라 외부 CLI 문제라
    계획서가 허용한 대안(fresh Claude subagent read-only)으로 독립 리뷰를 수행했어.
- **판정:** `APPROVED` — Critical 0, Important 0, Minor 4.
- **주요 확인:** production DB SELECT-only(양 파일·양 statement), cutoff 동결 byte 일치 + snapshot 순서,
  deterministic camera identity(dense_rank=1, 1/71/172), 분류는 `initial_gt`(current_gt는 not-null
  게이트로만), **future provenance가 frozen 172 contract 정확일치(단순 distinct count 아님)를 SQL
  membership + verifier count/flag + REPORT 세 층에서 실제 강제**, 6개 최소 predicate(총 camera-night
  포함) 양측 검증, fingerprint 6-table mutation 0, 결과값 누출 0.
- **Minor 4건 (전부 문서/방어가드, 코드 결함 아님, 수정 불요):**
  1. verdict CASE의 `ROI_REPLICATION_HOLD_UNEXPECTED_MINIMUM_AT_KICKOFF` 방어 분기는 DESIGN §9
     enum에 명시되진 않았지만 IMPLEMENTATION-PLAN Task 3이 그 문자열을 그대로 지시했고, 진짜
     kickoff(미래 0건)에선 도달 불가이며 verifier가 minimum_met↔verdict 일치를 별도로 강제해 모순 누출 없음.
  2. JSON-only verifier는 tuple 실제 membership을 실행할 수 없어 count/flag로 backstop — SQL의
     `provenance_in_contract` membership이 본체라 설계상 정상.
  3. REPORT 커밋 순서 서술은 무해한 narrative.
  4. `future_cutoff_utc`를 psql placeholder로 emit하는 건 계약(메모리 치환·치환본 미커밋)대로라 정상.
- Critical/Important 0이므로 코드 변경 없음. 리뷰 후 재검증 상태 유지: focused 14 passed, 전체 832
  passed/3 skipped/0 failed, `git diff --check` clean, `COLLECTION_ARTIFACTS_OK`.

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
