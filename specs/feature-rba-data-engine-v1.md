# RBA Data Engine v1 — 카메라·사람 GT·라벨링 웹 우선 계획

**상태:** 방향 확정 / tutorial·double-blind operational / owner-resolved GT usable / formal Blind30 후순위 calibration
**작성일:** 2026-07-12
**관련:** [`라벨링 웹 v2 상세 설계`](../docs/superpowers/specs/2026-07-12-labeling-web-v2-design.md), [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../docs/AI-VIDEO-ANALYSIS-STRATEGY.md), [`RBA 사건 단위 전수 분석 방향`](../docs/superpowers/specs/2026-07-31-rba-event-first-total-coverage-design.md), [`router-cost-v2`](../experiments/router-cost-v2/TEST-SHEET.md), [gecko-vision-gate v3](https://github.com/S-Soo100/gecko-vision-gate/blob/main/specs/gate-v3.md)

## 1. 한 줄 결정

현재 RBA의 1차 병목은 router threshold나 더 큰 모델이 아니라 **다양한 운영 영상과 사람이 확정한 GT의 부족**이다. 먼저 카메라를 늘리고, 클래스별 영상을 더 많이·다양하게 수집하고, AI 결과를 보지 않은 사람이 검수할 수 있도록 라벨링 웹을 GT 생산 도구로 고친다.

### 2026-07-31 운영 판정

paired 교차검수에서 큰 행동은 실사용 가능한 일치도를 보였다. 두 reviewer가 일치한 값과 불일치를
owner가 최종 결정한 값은 운영 정본 GT로 사용한다. 세부 관찰 집합·target·시간 구간은 상대적으로
불안정하므로 해당 필드를 별도 신뢰도 없이 자동 확정하지 않는다.

formal Blind30 v2는 이 데이터의 사용 허가를 다시 받는 선행 시험이 아니다. 새 reviewer가 같은
계약을 안정적으로 적용하는지, owner 개입률을 줄일 수 있는지 보는 후순위 calibration이다.
현재 다음 실행은 기존 GT와 약 2만 clip을 활용하는 사건 묶기 shadow v2이며, backlog 300 Gate
감사와 future 다양성 수집은 독립 트랙으로 유지한다.

## 2. 목표와 비목표

### 목표

- 여러 카메라·개체·모프·사육장·시간대에서 행동 데이터를 지속적으로 모은다.
- moving 다수 클래스뿐 아니라 drinking, feeding, defecating, shedding, eating_prey, hand_feeding, playing/enrichment 등 희소·사용자 가치 행동과 hard negative를 함께 축적한다.
- 원본 영상, 사람 라벨, 모델 판정, 전처리·모델 provenance를 분리해 저장한다.
- camera-night 단위로 train/EDA, validation, future holdout을 분리한다.
- 라벨링 웹을 빠르고 편향이 적은 GT 생산 도구로 만든다.

### 비목표

- 같은 72/203개 표본에서 threshold를 더 조정해 production 성능을 주장하지 않는다.
- VLM·Claude·Gate 판정을 사람 GT로 취급하지 않는다.
- rare P0 행동을 연출하기 위해 동물의 복지나 자연 행동을 훼손하지 않는다.
- GT와 독립 비용 검증 전에 router나 Gate로 clip을 영구 삭제·skip하지 않는다.

## 3. 데이터 수집 계약

### 다양성 축

- camera: 모델, 렌즈, 설치 높이·거리·각도
- animal: 개체, 종, 밝고 어두운 모프, 체격
- enclosure: 식물, 코르크, 은신처, 급수·급여 위치
- condition: 주간 컬러, 저녁, 야간 IR, 반사, 물방울, 가림, 원거리
- behavior: 일상 moving과 희소 P0 행동, 게코가 없거나 정지한 paired hard negative

카메라를 추가할 때는 카메라 수만 세지 않고 `camera × animal × enclosure × night`를 수집 단위로 기록한다. 같은 정적 장면의 near-duplicate가 전체 수량을 부풀리지 않도록 clip/night별 상한을 둔다.

### 클래스 수집 원칙

- 실제 운영 분포는 그대로 보존하고, 학습·검수 큐에서는 희소 클래스를 별도 oversample한다.
- 게코가 있는 장면과 없는 장면, 행동 직전·중·직후를 같은 환경에서 함께 모은다.
- 긴 영상은 event 시작·종료와 `uncertain / multi-action`을 기록해 top-1 강제 오라벨을 줄인다.
- 수집 당시 camera, animal/morph, enclosure, lighting, date/night, source를 반드시 남긴다.

## 4. 사람 GT 계약

1. 같은 화면·같은 작업에서 사람 GT와 VLM 검수를 끝내되, 최초 사람 GT 확정 전에는 VLM·Claude·Gate 결과를 숨긴다.
2. 사람은 `visibility`, 대표 action, 복수 관찰 행동, 각 행동의 start/end, target, confidence, 품질·환경 tag를 입력한다. 활동 의미와 별도로 `highlight_recommendation`, enrichment object, interaction type을 기록한다. 과거 `activity_intensity`는 legacy read 전용으로 보존하고 신규 GT에서는 `null`로 저장한다.
3. `관찰=licking`, `target=water_bowl`, `의미 action=drinking`처럼 관찰 사실과 의미 해석을 함께 보존한다.
4. camera·animal·species/morph·enclosure·camera-night·R2/hash·모델 provenance·dataset role은 시스템이 상속하고 사람에게 clip마다 반복 입력시키지 않는다.
5. 최초 blind GT 저장 뒤 exact VLM prediction을 공개하고 `correct / partially_correct / incorrect / unjudgeable`과 오류 유형을 기록한다.
6. Gate 감사에서는 sampled frame별 bbox 추가·삭제·교정을 조건부 고급 모드로 제공한다.
7. 희소·모호·모델 불일치는 2차 검수 큐로 보내고, 최초 GT·현재 GT·prediction·verdict 수정 이력을 모두 보존한다.
8. 모델 판정은 `prediction`, 사람 확정값은 `ground_truth`로 분리하며 같은 컬럼을 덮어쓰지 않는다.
9. 신규 라벨러는 production GT와 분리된 공통 5개 튜토리얼에서 라벨 계약을 먼저 학습한다.
   5개 완료는 본 큐 진입 조건이지만 점수 합격선은 두지 않는다.

`moving`은 object와 명확한 직접·반복 상호작용이 없는 일반 이동·등반·자세 변경이다. 사람과 VLM은 의도인 `playing`을 직접 단정하지 않고 wheel/장난감의 `ride/push/rotate/chase/repeated_return` evidence와 구간을 기록한다. 사람이 evidence를 확인한 경우에만 제품 표시용 playing을 파생한다.

## 5. 라벨링 웹 v2 요구사항

### 필수

- 한 화면의 `blind GT 확정 -> VLM 공개·검수 -> 완료 후 다음` 2단계 흐름
- 영상 재생, frame step, 속도 조절, 단축키, 이전/다음 자동 이동
- visibility, 대표 action, 복수 관찰 행동, target, event 구간, human confidence, 품질·환경 tag 입력
- VLM verdict와 행동 혼동·target 혼동·미검출·모프·IR/반사·시간구간 등 오류 tag
- moving/enrichment-interaction 상시 판정 가이드, positive/negative 예시, enrichment candidate의 object·interaction type 필수 입력
- Gate 모드의 sampled frame+bbox overlay, bbox 추가·삭제·교정
- 시스템 상속 camera·animal/morph·enclosure metadata 표시와 별도 관리 화면에서의 수정
- dataset role과 provenance 표시, camera-night split 충돌 경고
- 검수자·시간·수정 이력과 export 가능한 GT manifest

### 성공 기준

- 300 clip blind audit를 중단 없이 끝낼 수 있다.
- 평균 라벨링 시간, uncertain 비율, 재검수 비율을 측정한다.
- prediction을 숨긴 최초 사람 라벨, 현재 GT, exact VLM prediction, VLM verdict를 모두 재현할 수 있다.
- 모델/프롬프트/checkpoint를 바꿔도 기존 사람 GT가 변하지 않는다.

## 6. Gecko Vision Gate v3 활용

Gate v3는 행동 분류기가 아니라 `gecko visible / bbox / best frame / trajectory`를 공급하는 evidence sensor다.

- 지금: bbox·best frame 저장, 라벨링 초안, hard-case mining
- shadow 단계: bbox trajectory × camera ROI로 체류·활동 evidence 생성, VLM frame 우선순위 보조
- 독립 future holdout 이후: frozen router의 입력 후보
- 금지: Gate 단독 행동 확정, 미검증 camera/morph의 자동 skip

petcam backlog 300의 과거 Gate 결과는 `checkpoint_best_regular.pth`와 Claude proxy GT를 사용했으므로, v3 착수 전 best-EMA artifact와 sampler를 고정하고 300건 전체를 human-first blind GT로 다시 감사한다.

## 7. 데이터 역할과 평가

| 역할 | 허용 용도 | 규칙 |
|---|---|---|
| historical/EDA | 72, dataset203, 과거 router·Gate 불일치 | 실패 분석·UI 검증·학습 후보만 |
| train/validation | 사람 검수 후 채택한 운영·외부 데이터 | camera-night 누수 금지 |
| future holdout | 정책·모델·threshold 동결 이후 새로 촬영 | inference 전 sample list 고정 |
| production shadow | 모든 새 clip | 삭제·skip 없이 prediction과 비용 기록 |

클래스별 숫자만 보지 않고 camera/morph/IR/occlusion strata별 성능을 함께 보고한다. 결과를 본 뒤 모델·prompt·threshold를 바꾸면 해당 holdout은 EDA로 강등하고 더 미래의 밤을 새 holdout으로 만든다.

## 8. 실행 순서

1. 기존 owner-final GT를 운영 정본으로 유지하고 일상 교차검수를 계속한다.
2. 기존 닫힌 약 2만 clip으로 사건 묶기 shadow v2와 120 pair boundary GT를 진행한다.
3. owner-final GT로 local VLM의 역할·출력 계약을 동결하고 pretrained baseline을 측정한다.
   - 2026-08-02 v1 실행 완료: MiniCPM-V 4.6 `REJECT_SAFETY`, Qwen3-VL 2B
     `REJECT_RESOURCE/RELIABILITY`, `NO_DEVELOPMENT_CANDIDATE`.
4. 새 TEST-SHEET에서 runtime 호환성·자원·안전 baseline을 다시 통과한 뒤에만 LoRA/학습과
   all-event local VLM shadow를 검토한다. 2026-08-02 Gemma 3 4B production clip canary는
   3×2 contact-sheet static/moving 구분 Gate A에서 실패해 production 요청 0으로 미배포됐다.
   다음은 별도 계약의 6개 개별 이미지 또는 다른 local VLM 비교이며 현재는 hold다.
5. backlog 300 human-first Gate 감사와 추가 camera/animal/enclosure 수집을 독립 진행한다.
6. Gate v3·production VLM/router는 각각의 future holdout 통과 전 자동 skip 없이 shadow로만 둔다.
7. formal Blind30 v2는 reviewer calibration 필요 시 다시 연다.

## 9. 완료 조건

- [x] 라벨링 웹 v2 구현 스펙 승인
- [x] 공통 5개 튜토리얼 구현·실제 non-owner onboarding production evidence
- [x] 튜토리얼 완료자 공통 blind 30개 일치도 검증 계약 확정
- [ ] camera/animal/enclosure/night metadata 스키마와 수집 SOP 확정
- [ ] backlog 300 전체 human-first blind GT와 Gate v2 감사 report
- [ ] 신규 카메라·개체가 포함된 v3 train/validation 데이터셋 버전 동결
- [ ] Gate v3 shadow 시작, 자동 skip off 확인
- [ ] production VLM/router 계약 동결 이후 future holdout 수집 시작

## 10. 2026-07-30 현재 착수점

> 이 절은 2026-07-30 당시 snapshot이다. 아래 formal blind 30 “다음 gate” 지시는
> 2026-07-31 운영 판정으로 superseded됐고 현재는 후순위 reviewer calibration이다.

공통 `tutorial-v1`은 production GT와 분리된 전용 set/lesson/progress/attempt 원장, 5개
seed, 화면·API gate까지 production에 배포됐다. non-owner 두 명이 각각 5/5를 완료한 뒤
live blind 제출 100건과 68건을 수행했으므로 onboarding gate와 production 작업 진입은
실운영 증거로 검증됐다. 신규 라벨러 1명에게 같은 pilot과 첫 본작업 5개를 반복시키는 계획은
superseded다.

- 실행 설계: [`RBA Data Engine tutorial pilot 설계`](../docs/superpowers/specs/2026-07-30-rba-data-engine-tutorial-pilot-design.md)
- 실행 순서: [`RBA Data Engine tutorial pilot 계획`](../docs/superpowers/plans/2026-07-30-rba-data-engine-tutorial-pilot.md)
- onboarding 운영 증거: non-owner tutorial 완료 2명, 이후 live 제출 100건/68건
- double-blind 운영 증거: 실제 paired 53건(07-27 45, 07-29 8), 자동 합의 14,
  paired owner adjudication 39
- 07-29 B그룹 slot 0은 `GROUP_B_SLOT_ROOT_CAUSE_CONFIRMED_NO_BUG`다. active member 2명,
  camera 3대였지만 해당 activity-day raw clip/eligible clip/ownership/slot이 모두 0이었다.
  Cam 2·3의 마지막 clip은 window 시작 전이고 Cam 4는 전체 clip 0이라 materializer가 처리할
  입력이 없었다. 기존 slot/assignment를 고치거나 재작성하지 않는다.
- `owner-single-adopt-v1` 47건은 단일 reviewer 제출이므로 agreement·blind 30·학습/평가
  채택 근거에서 제외한다. 2026-07-31 library read source를 `owner_single_adopt`로 분리했고,
  기존 final/submission/event 원장은 불변으로 검증했다.
- 당시 다음 연구 gate는 기존 53쌍을 재사용하지 않는 formal blind 30 TEST-SHEET 사전동결이었다.
  이 우선순위는 현재 superseded다.
  exact 표본·reviewer 자격·비교 함수·uncertain/abstain·owner adjudication·수용 기준을
  제출 전에 고정한다.
- TEST-SHEET: [`rba-data-engine-blind30-v1`](../experiments/rba-data-engine-blind30/TEST-SHEET.md).
  계약은 동결했지만 tutorial 완료 non-owner 두 명이 서로 다른 active group이고 generic
  canary가 20개 상한이라 `BLIND30_PREFROZEN_BLOCKED_REVIEWER_PAIR_AND_EXACT30_RESERVATION`이다.
  cohort/slot/submission/manifest 생성은 아직 0건이다.
- backlog 300 human-first Gate 감사는 daily double-blind 운영과 별도 항목으로 유지한다.

### 2026-07-30 owner tutorial smoke

owner 계정의 비식별 fingerprint `05fd4fe03dc3`이 production `tutorial-v1` run 1을
2026-07-30 22:53:10 KST에 시작해 22:56:36 KST에 완료했다. position 1~5의 attempt는
모두 `completed`이고 waiver는 없다. 이 결과는 화면·교육 순서·저장·완료 전환을 확인한
`OWNER_TUTORIAL_SMOKE_COMPLETED` 증거로 보존한다.

다만 이 계정은 owner라 `labelers` 멤버십과 tutorial gate를 우회한다. 따라서 non-owner
onboarding 증거나 agreement로 세지 않는다. owner first-5 workflow 지시는 기존 daily
double-blind·불일치 검수 운영과 중복되어 **superseded / 실행 중단**이다. owner가 자기 결과를
다시 보는 값도 독립 재검수 비율에 넣지 않는다.
