# Unified GT Catalog · VLM/Evidence Failure Audit 설계

## 1. 목표

Owner가 완료한 최신 motion GT, 과거 사람 GT labeling, dataset203의 검수 GT를 하나의
**provenance-aware catalog**로 연결해 다음 질문에 답한다.

> 현재 서비스의 VLM·Python Evidence·Gate가 반복해서 실패하는 원인 중, 실제 서비스 품질을
> 가장 크게 개선할 수 있는 상위 3개는 무엇인가?

최종 목적은 오류 목록을 만드는 것이 아니라 아래 의사결정을 내리는 것이다.

1. 다음 개선 투자를 모델·prompt, temporal sampling, visibility/ROI, camera calibration,
   GT/ontology 중 어디에 할지 결정한다.
2. 가장 효과가 큰 개선 후보 **1개**만 다음 실험으로 승격한다.
3. 근거가 약하거나 환경 의존적인 후보는 production 변경 전에 폐기한다.

이번 단계는 데이터 감사·연구 설계다. 모델 학습, prompt/threshold 튜닝, selector 변경,
production 반영은 하지 않는다.

## 2. Decision gate

공유 SOT는 수정하지 않고 이 전용 설계에 판정을 남긴다.

| Gate | 판정 | 근거 |
|---|---|---|
| SOT 부합 | 통과 | RBA Data Engine v1의 사람 GT·다양성·실패 분석 우선순위와 맞는다. |
| 기대효과 | 통과 | 상위 실패 원인을 실제 개선 레버와 연결하고 다음 투자 1개를 선택한다. |
| 측정가능 | 통과 | unique clip/episode, 오류율, addressable error mass, source/camera-night 재현성을 측정한다. |
| 유효한 계획 | 통과 | source별 provenance, 중복 계층, 누출 방지 역할, HOLD 조건을 먼저 동결한다. |

## 3. 데이터 소스와 역할

### 3.1 Source A — Owner motion GT

- 기준 snapshot: Owner completed 172 clips
- 계약:
  - Owner identity를 profile·labeler 비소속·session history·triage event로 교차 확인
  - `stage='completed'`
  - `initial_gt`, `current_gt`, `completed_at` 모두 존재
- 장점:
  - 최신 운영 영상
  - Python Evidence 172/172
  - Gate/prelabel 172/172
  - 상세 visibility·segment·interaction·highlight/care GT
- 제한:
  - 2 cameras, 3 days, 39개 5분 episode
  - moving 중심
- 역할: 운영 실패 분석과 최신-domain benchmark

### 3.2 Source B — legacy 사람 GT labeling

대상 후보는 DB schema·RPC·코드에서 사람 provenance가 증명되는 row만 포함한다.

- 포함 후보:
  - `behavior_labels`의 사람 작성·검수 row
  - legacy `clip_labeling_sessions`의 immutable blind `initial_gt`
  - append-only revision으로 설명 가능한 owner correction
- 자동 제외:
  - VLM·router·Gate가 만든 자동 label
  - tutorial attempt
  - provenance가 없는 filename-only 추정
  - current row만 있고 최초 사람 판정과 수정 이력을 복원할 수 없는 row
- 역할: 독립 표본·희소 행동·과거 촬영 조건 확장

정확한 포함 수는 production DB SELECT-only schema/provenance audit 후 확정한다. 화면 숫자나
테이블 전체 count를 GT 수로 사용하지 않는다.

### 3.3 Source C — dataset203

dataset203은 이름과 달리 정리 이력에 따라 203 → 202 → 현재 유효 약 197건으로 기록돼 있다.
실제 manifest count와 파일 가용성을 snapshot 시 다시 측정한다.

- 장점:
  - Owner 172보다 행동·촬영 조건이 다양함
  - 과거 blind VLM 판정과 GT correction 이력이 있음
  - care/feeding/drinking 등 희소 행동 분석 후보
- 제한:
  - 여러 과거 모델·prompt·router 실험에 반복 사용됨
  - legacy DB GT 및 Source B와 중복될 가능성이 큼
  - 파일명·manifest·DB 정본 사이에 과거 정정 이력이 있음
- 역할:
  - 실패 분석·development·학습 후보
  - **최종 future holdout으로 재사용 금지**

### 3.4 Source D — future holdout

현재 세 소스에 포함되지 않고, 개선 계약을 동결한 뒤 새로 촬영·blind labeling한
camera-night만 해당한다.

- 현재 통합 catalog에 행으로 섞지 않는다.
- 이번 연구가 고른 개선 후보의 최종 adoption 판단에만 사용한다.

## 4. 통합 원칙

### 4.1 합치는 것은 원본 GT가 아니라 catalog view

각 source의 원본 테이블·manifest를 수정하거나 하나의 GT로 덮어쓰지 않는다. source record를
그대로 보존하고 아래 canonical field를 가진 read-only catalog로 연결한다.

| 필드 | 의미 |
|---|---|
| `source_name`, `source_record_hash` | 원천과 민감 원문 없는 재현 fingerprint |
| `canonical_clip_key` | source 간 동일 clip 연결용 비식별 hash |
| `duplicate_group_hash` | 동일·파생·근접 중복 그룹 |
| `episode_group_hash` | camera + 5분 gap 기준 누출 방지 그룹 |
| `camera_night_hash` | camera-night split 단위 |
| `gt_trust_tier` | 사람 GT 신뢰 등급 |
| `gt_schema_version` | 원본 ontology |
| `canonical_targets` | 공통으로 비교 가능한 motion/visibility/action/care target |
| `exposure_roles` | 과거 train/dev/eval/model exposure |
| `asset_coverage` | Evidence/Gate/VLM 결과 연결 여부 |

tracked 파일에는 clip UUID, R2 key, signed URL, 사용자 식별자, 원문 note를 남기지 않는다.
필요한 raw join map은 gitignored 파일로만 두고, 보고서에는 집계와 salted hash만 기록한다.

### 4.2 GT trust tier

| Tier | 정의 | 허용 용도 |
|---|---|---|
| T1 | blind 사람 최초 GT + 불변 provenance, 또는 감사된 Owner 완료 GT | benchmark/dev |
| T2 | 사람 GT + 검수/수정 이력 복원 가능 | dev, 민감도 분석 |
| T3 | 사람 유래지만 filename/manifest 정정 의존 또는 blind 여부 불명 | EDA만 |
| X | VLM·router·Gate 자동 판정, tutorial, provenance 불명 | GT에서 제외 |

T1/T2/T3를 섞은 단일 정확도를 보고하지 않는다. T1을 주 분석, T2를 확장 분석, T3를
가설 생성으로 구분한다.

### 4.3 중복 판정 계층

자동 삭제·자동 병합은 하지 않는다. 아래 순서로 duplicate group만 부여한다.

1. 같은 source clip id 또는 DB foreign key
2. 정규화 R2/object key의 salted hash
3. 로컬 파일 content hash가 있을 때 byte-identical
4. 같은 camera·started_at·duration·size
5. 같은 camera에서 근접 시간 + 동일 canonical GT signature

1~3은 exact duplicate, 4는 probable duplicate, 5는 near-episode로 구분한다. source count의
합계와 unique clip 수를 함께 보고하고, 평가 split은 duplicate/episode group 전체를 한쪽에 둔다.

## 5. Canonical target

원천 ontology를 억지로 하나의 top-1 행동으로 변환하지 않는다. 공통 교집합과 source-specific
축을 분리한다.

### 공통 평가 가능 축

- `motion`: moving / static-only / unknown
- `visibility`: visible / partial / absent / unknown
- `primary_action`: 공통 enum으로 lossless mapping 가능한 경우만
- `care_event`: care / non-care / unknown
- `highlight`: include / exclude / uncertain / unavailable
- `judgeability`: judgeable / unjudgeable / unavailable

매핑이 손실되는 row는 `unknown`으로 두고 임의 추론하지 않는다. 원본 라벨을 보존하며,
mapping table의 버전과 테스트를 별도 동결한다.

## 6. VLM·Evidence 실패 정의

### 6.1 VLM failure

- primary action 불일치
- care event false negative / false positive
- visibility 불일치
- judgeability가 낮은 영상을 확정 판정
- segment/temporal evidence를 놓쳐 top-1이 틀림

과거 VLM 결과는 모델·prompt·sampler provenance별로 분리한다. GT lock 뒤 실행, selector로
선택된 subset, 이미 반복 평가된 dataset203은 모두 retrospective diagnostic으로만 사용한다.

### 6.2 Evidence failure

Python Evidence와 Gate는 행동 정답이 아니라 sensor다. 따라서 10-class 정확도로 평가하지 않는다.

- GT moving인데 motion evidence가 낮거나 결측
- GT static-only인데 환경 변화 evidence가 높음
- GT absent인데 Gate가 present
- GT visible/partial인데 Gate가 놓침
- decode·frame sampling·schema·provenance 실패
- camera/night에 따라 feature 분포나 coverage가 급변

### 6.3 실패 원인 taxonomy

각 오류에는 primary cause 1개와 secondary cause 0~2개를 부여한다.

1. `VISIBILITY_SCALE_OCCLUSION` — 게코가 작음·가림·화면 밖
2. `TEMPORAL_SAMPLING` — 행동 순간·전환을 frame/segment가 놓침
3. `IR_LIGHT_REFLECTION` — IR, glare, shadow, exposure 변화
4. `CAMERA_DOMAIN` — 특정 camera/enclosure/length에 종속
5. `SEMANTIC_ONTOLOGY` — 유사 행동·행동 정의·다중 행동 문제
6. `INPUT_QUALITY` — 흔들림·압축·손상·짧은 오류 영상
7. `EVIDENCE_SPURIOUS_OR_MISSING` — sensor feature의 비인과적 반응·결측
8. `GT_AMBIGUITY_OR_ERROR` — 사람 간 불일치·수정 필요·mapping 손실
9. `PIPELINE_PROVENANCE` — 잘못된 버전·결과 연결·선택 편향
10. `OTHER_UNRESOLVED`

사람 육안 확인이 없는 자동 원인 추론은 `candidate_cause`로만 기록한다.

## 7. 상위 실패 원인 선정

단순 clip 오류 건수로 순위를 정하지 않는다. 연속 clip 하나가 순위를 지배하지 않도록
**독립 episode**를 기본 단위로 사용한다.

각 원인에 대해 다음을 계산한다.

- affected unique clips
- affected independent episodes
- affected camera-nights
- source별 재현 수
- VLM error와 Evidence anomaly 각각의 비율
- care/highlight miss에 미치는 영향
- 개선 가능한 오류 비중(`addressable error mass`)
- 예상 개선 레버와 검증 비용

상위 3개 자격:

1. T1/T2 GT에서 확인
2. 최소 10 independent episodes에 영향
3. 최소 2개 camera-night에서 재현
4. 하나의 duplicate group이 20% 이상을 차지하지 않음
5. 구체적인 개선 레버와 반증 가능한 다음 실험이 존재

두 source에서 재현되지 않으면 전체 상위 원인이 아니라 `source-specific`으로 표기한다.
표본 기준이 부족하면 억지로 3개를 채우지 않고
`UNIFIED_GT_FAILURE_AUDIT_HOLD_INSUFFICIENT_INDEPENDENT_ERRORS`로 판정한다.

## 8. 세 접근법 비교

### A. 통합 provenance catalog + 실패 감사 — 채택

- 장점: 중복과 누출을 통제하면서 모든 사람 GT를 활용할 수 있다.
- 단점: 초기 데이터 계약 감사 비용이 든다.
- 선택 이유: 모델을 바꾸기 전에 가장 큰 서비스 실패와 투자 지점을 찾을 수 있다.

### B. 전부 합쳐 즉시 학습

- 장점: 빠르게 학습 실험을 시작할 수 있다.
- 단점: 중복 누출, ontology 충돌, 과거 evaluation exposure로 가짜 성능이 나올 가능성이 높다.
- 판정: 이번 단계에서 금지.

### C. source별 benchmark만 유지

- 장점: 원천 오염 위험이 낮다.
- 단점: source를 가로질러 반복되는 실패 원인과 실제 독립 표본 수를 알 수 없다.
- 판정: source별 지표는 유지하되 A의 하위 strata로 사용한다.

## 9. 실행 단계

### Phase 1 — Read-only inventory

1. DB schema/RPC/code에서 각 사람 GT eligibility와 provenance를 추적한다.
2. source별 count, 기간, camera/animal/enclosure, class, reviewer/blind/revision 상태를 측정한다.
3. dataset203 manifest의 실제 유효 행과 로컬 asset availability를 확인한다.
4. 시작 table fingerprint를 기록한다.

### Phase 2 — Dedup과 canonical mapping

1. exact/probable/near-episode 그룹을 계산한다.
2. source 간 overlap matrix를 만든다.
3. GT trust tier와 과거 model exposure role을 부여한다.
4. canonical target mapping의 lossless/lossy/unknown 수를 검증한다.

### Phase 3 — Failure linkage

1. 기존 Python Evidence, Gate/prelabel, VLM 결과를 read-only로 연결한다.
2. provenance가 다른 실행을 섞지 않는다.
3. 자동 결과를 GT로 순환 사용하지 않는다.
4. source·camera-night·episode별 error/anomaly matrix를 만든다.

### Phase 4 — Top-3 audit

1. candidate cause를 집계한다.
2. 상위 candidate의 대표 오류는 blinded human review 대상으로 분리한다.
3. 독립 episode·camera-night·source 재현성을 대조한다.
4. addressable error mass와 예상 개선 비용을 비교한다.

### Phase 5 — Decision

다음 중 하나로 끝낸다.

- `UNIFIED_GT_FAILURE_AUDIT_READY_FOR_REVIEW`
- `UNIFIED_GT_FAILURE_AUDIT_HOLD_<REASON>`

READY이면 상위 실패 원인 최대 3개와 다음 개선 후보 **1개**를 추천한다. 이 판정 자체는
implementation/adoption 승인이 아니다.

## 10. 산출물

전용 경로만 사용한다.

```text
experiments/unified-gt-failure-audit-20260727/
├── DESIGN.md
├── IMPLEMENTATION-PLAN.md
├── inventory.sql
├── analyze.py
├── test_analyze.py
├── fingerprints-start.csv
├── fingerprints-end.csv
├── source-summary.json
├── overlap-summary.json
├── failure-summary.json
└── REPORT.md
```

민감 원시 join map과 clip-level review sheet는 gitignored raw 경로에만 둔다. tracked 산출물은
aggregate, 비식별 hash, 테스트, 재현 코드로 제한한다.

## 11. 안전 경계

- production DB SELECT-only
- INSERT/UPDATE/DELETE/RPC write/migration/R2 write 금지
- VLM·Evidence·Gate 재실행 금지: 이번 감사는 기존 결과 coverage와 failure linkage만 사용
- Slack, LaunchAgent, deploy, web/API/runtime 변경 금지
- 사람 GT 자동 수정·자동 병합·자동 제외 금지
- dataset203을 future holdout으로 부르지 않음
- 동일 데이터로 개선안을 고르고 성능 채택까지 동시에 하지 않음
- 모델 학습, prompt/threshold/selector 변경은 별도 승인 전 금지

시작과 종료에 관련 사람 GT·behavior·triage·revision·blind·Evidence·Gate·VLM table의
count+ordered fingerprint를 비교해 관찰 범위 mutation 0을 증명한다.

## 12. 성공 기준

1. 세 source의 실제 eligible count와 unique clip/episode 수가 재현된다.
2. source 간 exact/probable overlap과 과거 model exposure가 정량화된다.
3. GT trust tier와 canonical mapping의 결측·손실이 보고된다.
4. VLM·Evidence 결과 coverage가 provenance별로 분리된다.
5. 상위 실패 원인은 episode·camera-night·source 재현성과 함께 보고된다.
6. 각 원인에 반증 가능한 개선 레버가 연결된다.
7. 다음 개선 후보는 1개만 추천하거나, 근거 부족으로 HOLD한다.
8. production mutation 0과 전용 경로 밖 변경 0을 증명한다.

## 13. 기대되는 최종 의사결정 예시

결과는 다음과 같이 구체적이어야 한다.

> 독립 오류 episode의 38%가 `TEMPORAL_SAMPLING`이고 3개 source·5개 camera-night에서
> 재현됐다. 모델 교체보다 segment-aware frame sampling이 더 큰 addressable error mass를
> 가지므로 다음 후보로 추천한다. visibility 개선은 Owner source에서만 재현돼 2순위,
> `roi_mean`은 camera-domain 의존으로 폐기한다.

실측 전에 위 수치나 원인 순위를 가정하지 않는다.
