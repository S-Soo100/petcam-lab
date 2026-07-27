# Owner GT 172 데이터 감사·연구 설계

## 판정

`OWNER_GT_AUDIT_READY_FOR_REVIEW`

172건은 **Owner 직접 완료 GT의 read-only snapshot**으로 정의할 수 있어. Python Evidence와
Gate coverage는 172/172라 기술·신호 benchmark 설계에 바로 쓸 수 있고, 기존 VLM은 성공
23/172라 기존 결과의 소규모 회고 평가만 가능해. 이 판정은 모델 학습·prompt/threshold 조정·
selector 변경·production 채택 승인이 아니야.

## Decision gate

공유 `docs/decision-gate.md`는 수정 금지 범위라 이 전용 보고서에만 판정을 남겨.

| Gate | 판정 | 근거 |
|---|---|---|
| SOT 부합 | 통과 | RBA Data Engine v1의 사람 GT·다양성·독립 평가 우선순위와 맞아. |
| 기대효과 | 통과 | Python Evidence, VLM blind 평가, selector 효용이라는 소비처가 각각 명확해. |
| 측정가능 | 통과 | 표본 계약, grouped split, metric, 최소 표본, mutation fingerprint가 있어. |
| 유효한 계획 | 통과 | SELECT-only, 전용 경로, raw 비추적, 명시한 원장 변화 0으로 범위를 고정했어. |

## Eligibility 계약

DB에는 별도 `owner` role row가 없어. 그래서 화면 숫자가 아니라 다음 DB 사실을 함께 써서
Owner identity를 유일하게 잡았어.

1. `user_profiles.display_name='운영자'`
2. `labelers` membership 없음
3. `motion_clip_labeling_sessions.reviewed_by` 이력 존재
4. `owner_started_labeling` 감사 이벤트 actor와 같은 사용자

두 독립 경로가 각각 identity 1명, completed 172건, distinct clip 172건, 같은 ordered
SHA-256을 냈어.

Eligible row는 아래를 모두 만족해.

```text
motion_clip_labeling_sessions.reviewed_by = Owner identity
AND stage = 'completed'
AND initial_gt IS NOT NULL
AND current_gt IS NOT NULL
AND completed_at IS NOT NULL
```

평가 정답은 보정 가능한 `current_gt`를 사용하고, provenance 확인용으로 immutable
`initial_gt`를 보존해. 현재 revision은 0건이라 둘은 172/172 동일해.

### 상태 분리

| 범주 | 수 | Owner GT 포함 여부 |
|---|---:|---|
| Owner completed session | 172 clips | 포함 |
| Owner `gt_locked` 진행 중 | 2 clips | 제외 |
| Owner draft | 0 | 제외 |
| 현재 triage `label` | 174 | 완료 172 + 진행 중 2 |
| 현재 triage `hold` | 4 | 제외 |
| 현재 triage `skip` | 159 | 제외 |
| 시스템 exclusion `candidate` | 784 | 별도 운영 원장, 자동 포함 금지 |
| 시스템 exclusion `quarantined` | 40 | 별도 운영 원장, 자동 포함 금지 |
| Canary | 12 clips / 24 submissions | 별도 cohort, eligible overlap 0 |
| live double-blind submission | 0 | 별도 cohort |
| Owner가 작성한 blind submission | 0 | 별도 cohort |

Eligible 172는 triage `label` 172/172, terminal 시스템 격리 overlap 0, Canary overlap 0이야.

## Snapshot과 관찰 범위 mutation 0

- 시작 table fingerprint: `2026-07-27 04:37:11Z`
- 종료 table fingerprint: `2026-07-27 04:43:00Z`
- 시스템 격리 별도 시작/종료: `2026-07-27 04:44:51Z` / `04:46:59Z`
- Owner cohort 종료 fingerprint: `2026-07-27 04:43:18Z`
- Owner eligible count: 시작 172 = 종료 172
- Owner eligible ordered SHA-256:
  `8e2bf4e73f8f033288d7632e25e2fbfd69d3de98c62dade2996bbe33686c96ba`
- 33개 사람 라벨·GT·triage·blind·behavior·Python Evidence·Gate·VLM 관련 테이블:
  count와 ordered fingerprint 전부 동일
- 시스템 격리 2개 테이블은 별도 보강 window로 시작·종료를 다시 대조해.

전체 집계는 `fingerprints-start.csv`, `fingerprints-end.csv`에 있고 Owner cohort의 시작·종료
값은 `cohort-fingerprints.csv`에 있어. fingerprint는 각 row의 canonical JSONB text를 hash한
뒤 정렬 결합한 값이야. 이 증거가 보장하는 범위는 명시한 35개 테이블과 Owner eligible
cohort야. DB 전체의 무변경을 과장하지 않아. 이번 작업은 SELECT만 실행했고 DB/R2/runtime write
명령은 실행하지 않았어.

## 표본 범위와 편향

- 촬영 범위: 2026-07-22 18:03:57 KST ~ 2026-07-24 23:11:21 KST
- 완료 범위: 2026-07-22 20:37:47 KST ~ 2026-07-24 23:45:36 KST
- 카메라: 2대
  - P4 Cam 3: 101건, 58.7%
  - P4 Cam (dev): 71건, 41.3%
- 날짜:
  - 07-22: 51건, 29.7%
  - 07-23: 100건, 58.1%
  - 07-24: 21건, 12.2%
- 길이: min 30.12s, p25 32.01s, median 60.70s, mean 49.52s, p75 62.29s,
  p95 63.41s, max 63.74s
- 길이 bin: 30~35s 71건, 55~61s 20건, 61s 이상 81건

카메라와 길이가 거의 결합돼 있고, 3일 중 하루가 58.1%를 차지해. random clip split은 같은
camera-night·근접 episode를 양쪽에 흘려 누출을 만들 수 있어. 동물·사육장 다양성도 이 DB
snapshot만으로 독립적으로 확장됐다고 주장할 수 없어.

## GT 무결성과 분포

필수 key 결측, enum 불일치, 배열 타입 오류, absent/unseen 규칙 위반, segment 누락·중복·orphan,
interaction 근거 누락, drinking target 위반, hand-feeding 근거 위반은 모두 0이야.

DB `float4` duration을 decimal로 바꿔 exact 비교하면 63 segments가 끝값을
`1.4e-14~5.0e-14s` 초과하는 것처럼 보였지만, double 비교와 1ms tolerance에서는 위반 0이야.
사람 판정 오류가 아니라 부동소수점 왕복 오차야. 사람 GT는 수정하지 않았어.

### 핵심 분포

| 축 | 분포 |
|---|---|
| 대표 행동 | moving 128, basking 36, unseen 4, drinking 3, eating_paste 1 |
| 시야 | visible 132, partial 36, absent 4 |
| 관찰 행동 | moving 108, static 42, wheel 29, licking 6, object 1 |
| 확신도 | certain 172 |
| 하이라이트 | include 49, exclude 123, uncertain 0 |
| 상호작용 객체 | none 142, wheel 29, other 1 |
| interaction type | rotate 24, ride 6, push 5, other 3, chase 1 |
| care 대표 행동 | drinking 3, eating_paste 1, 나머지 care class 0 |
| 주요 촬영 맥락 | IR 159, occlusion 29, overexposure 9, edge 8, glare 8 |
| 메모 | non-null 6, null 166. 원문은 저장하지 않았어. |

독립 `posture` 필드는 ontology에 없어. 이번 감사는 자세를 새로 추론하지 않고 `static/moving`
관찰 행동만 대리 축으로 보고해.

## 중복·episode

- 같은 카메라·동일 시작시각 pair: 0
- 동일 시작·길이·파일크기 pair: 0
- 시작시각 60초 이내 pair: 10
- 시작시각 5분 이내 pair: 286
- 5분 이내이면서 note 제외 GT가 같은 pair: 2
- note 제외 semantic GT signature: 169 unique / 172
- 반복 signature: 1 group, 4 clips
- 5분 gap 기준 episode cluster: 39
- 10분 gap 기준 episode cluster: 26

물리 파일 checksum이 DB에 없어서 byte-identical 중복은 증명할 수 없어. 위 수치는 중복 삭제 근거가
아니라 split 누출 방지용 근접 episode 신호야. 자동 삭제·병합은 하지 않았어.

## Python Evidence, Gate, VLM coverage

| 연결 자산 | clip coverage | 해석 |
|---|---:|---|
| Python Evidence run | 172/172 | 모두 level0=`ok`, level1=`ok`, run 1개 |
| Gate/prelabel | 172/172 | 모두 동일 provenance contract 1개 |
| 기존 VLM job | 24/172 | 성공 23, terminal 실패 1 |
| VLM 성공 + Python + Gate | 23/172 | 세 결과가 있는 회고 부분집합 |
| legacy behavior VLM/human | 0/172 | legacy label 정본과 섞이지 않음 |
| router feature | 0/172 | 과거 local-router 자산과 직접 연결 없음 |

Gate visibility의 회고 confusion은 TP 168, FP 4, FN 0, TN 0이야. present recall 100%처럼
보이지만 absent가 4건뿐이고 specificity는 0%라 채택 근거가 아니야.

기존 VLM 성공 23건의 primary-action exact match는 14/23, 60.9%였어. lock 시점 snapshot은
7건뿐이고 16건은 GT lock 뒤 성공했어. VLM은 GT를 입력받지 않았지만, 이 23건은 selector가 고른
편향 표본이므로 전체 정확도로 일반화하지 않아.

현재 selector job 24건은 care 0/4, highlight include 4/49를 골랐고, absent 4/4를 골랐어.
하지만 selector version 2종과 backfill이 섞였고 unselected clip의 당시 rank snapshot이 없어서
정식 효용 비교로 쓰면 안 돼.

## 활용안 비교

### 1순위: Python Evidence 정확도·coverage benchmark

**지금 가능한 것**

- 172/172 decode·schema·provenance coverage와 실패율 측정
- `observed moving` 108 대 `static without moving` 32의 고정 feature 분포·threshold-free AUROC
  EDA
- camera/date/episode group별 missingness와 stability

**불가능한 것**

- Python Evidence는 행동 classifier가 아니므로 10-class 행동 정확도라고 부를 수 없음
- absent 4, care 4로 visibility/care 성능 주장 불가
- 2카메라·3일만으로 production 일반화 주장 불가

**최소 표본과 split**

- 기술 coverage: 현재 172로 가능
- 신호 benchmark: target마다 positive/negative 각각 최소 30 **per evaluation partition**
- production 후보 판정: 최소 3카메라·7 camera-night·60 독립 episode, rare class는 각 30 이상
- split 단위: 5분 episode → camera-night. clip random split 금지
- 현재 39 episode라 descriptive benchmark만 하고 adoption gate는 열지 않아

**지표**

- run coverage, L0/L1 success, schema/provenance consistency
- feature missingness, decode frame ratio
- fixed feature AUROC와 bootstrap 95% CI
- camera-night별 median/IQR drift
- threshold·prompt·feature weight 튜닝 없음

### 2순위: VLM blind evaluation holdout

**지금 가능한 것**

- 기존 23 success는 회고 diagnostic/dev bucket
- VLM success가 없는 149건은 model/prompt/sampler를 먼저 동결한 뒤 future inference candidate
- moving·basking 중심의 narrow-domain exact match와 macro metric

**불가능한 것**

- care class는 총 4건이라 P0 recall·class별 정확도 불가
- unseen 4건이라 visibility 성능 불가
- 현재 172를 전체 종/카메라 production holdout으로 부를 수 없음

**최소 표본과 split**

- overall pilot: 100 independent episodes 이상
- 보고하는 class마다 최소 30, P0/care class마다 최소 30 positive
- camera-night/5분 episode grouped holdout, 같은 signature group은 한쪽에만
- 기존 23 success는 holdout에서 영구 제외
- remaining 149도 clip 선정 전에 contract hash를 동결하고, 결과를 본 뒤 제외 금지

**지표**

- primary exact accuracy, macro-F1, class recall/precision
- P0 recall, unseen specificity, abstain/unjudgeable rate
- camera-night bootstrap 95% CI

### 3순위: selector 후보 효용 평가

**지금 가능한 것**

- selected 24 대 unselected 148의 회고 yield를 경고 포함 EDA로 비교
- highlight include, care, visible/partial/absent별 selected coverage 확인

**불가능한 것**

- unselected clip의 당시 rank feature·eligibility snapshot이 없어 precision@K·lift를 인과적으로
  평가할 수 없음
- 두 selector version과 backfill을 합친 24건으로 한 policy 성능을 주장할 수 없음

**최소 표본과 split**

- 한 동결 selector version당 최소 100 independent episodes
- camera-night 최소 5개, target positive 최소 30
- 모든 candidate의 eligibility·score·rank·selected flag를 inference 전에 immutable snapshot
- 5분 episode/camera-night grouped comparison

**지표**

- precision@K, recall@K, lift@K 대비 random/time-stratified baseline
- highlight include yield, care recall, absent waste rate
- camera별 selection rate disparity

## 추천과 다음 최소 행동

추천 1순위는 **Python Evidence coverage + motion/static 신호의 pre-registered descriptive
benchmark**야. 172/172 coverage라 즉시 재현 가능하고, threshold나 production selector를 건드리지
않아도 돼.

다음 최소 행동은 새 실행 전에 전용 TEST-SHEET 하나를 동결하는 거야.

1. 5분 episode 39개를 camera-night 단위로 묶어 split manifest hash만 저장
2. `observed moving` 대 `static without moving` 질문 하나만 고정
3. feature 목록·AUROC·CI·missingness를 사전등록
4. rare care·visibility·selector adoption은 `HOLD_INSUFFICIENT_DIVERSITY`로 남김

훈련셋 사용은 별도 판단이야. 이번 작업에서는 모델 학습, prompt/threshold 튜닝, selector 변경,
production 로직 변경을 전부 실행하지 않았어.

## 재현·보안

- 재현 SQL: `audit.sql`
- artifact guard: `verify_artifacts.py`
- tests: `test_verify_artifacts.py`
- raw clip UUID, 사용자 UUID, 메모 원문, signed URL, R2 key, 이메일: tracked 0
- DB statement: SELECT/WITH only
- R2/API/RPC write, migration, Slack, LaunchAgent, deploy: 0
