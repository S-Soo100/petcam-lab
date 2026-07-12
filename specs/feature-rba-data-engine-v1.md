# RBA Data Engine v1 — 카메라·사람 GT·라벨링 웹 우선 계획

**상태:** 방향 확정 / 구현 전
**작성일:** 2026-07-12
**관련:** [`라벨링 웹 v2 상세 설계`](../docs/superpowers/specs/2026-07-12-labeling-web-v2-design.md), [`docs/AI-VIDEO-ANALYSIS-STRATEGY.md`](../docs/AI-VIDEO-ANALYSIS-STRATEGY.md), [`router-cost-v2`](../experiments/router-cost-v2/TEST-SHEET.md), [gecko-vision-gate v3](https://github.com/S-Soo100/gecko-vision-gate/blob/main/specs/gate-v3.md)

## 1. 한 줄 결정

현재 RBA의 1차 병목은 router threshold나 더 큰 모델이 아니라 **다양한 운영 영상과 사람이 확정한 GT의 부족**이다. 먼저 카메라를 늘리고, 클래스별 영상을 더 많이·다양하게 수집하고, AI 결과를 보지 않은 사람이 검수할 수 있도록 라벨링 웹을 GT 생산 도구로 고친다.

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
2. 사람은 `visibility`, 대표 action, 복수 관찰 행동, 각 행동의 start/end, target, confidence, 품질·환경 tag를 입력한다. 활동은 action과 별도로 `activity_intensity`, enrichment object, interaction type을 기록한다.
3. `관찰=licking`, `target=water_bowl`, `의미 action=drinking`처럼 관찰 사실과 의미 해석을 함께 보존한다.
4. camera·animal·species/morph·enclosure·camera-night·R2/hash·모델 provenance·dataset role은 시스템이 상속하고 사람에게 clip마다 반복 입력시키지 않는다.
5. 최초 blind GT 저장 뒤 exact VLM prediction을 공개하고 `correct / partially_correct / incorrect / unjudgeable`과 오류 유형을 기록한다.
6. Gate 감사에서는 sampled frame별 bbox 추가·삭제·교정을 조건부 고급 모드로 제공한다.
7. 희소·모호·모델 불일치는 2차 검수 큐로 보내고, 최초 GT·현재 GT·prediction·verdict 수정 이력을 모두 보존한다.
8. 모델 판정은 `prediction`, 사람 확정값은 `ground_truth`로 분리하며 같은 컬럼을 덮어쓰지 않는다.

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

1. 라벨링 웹 v2의 DB/UI 상세 스펙과 마이그레이션 계획 작성
2. 기존 backlog 300을 위한 blind Gate audit 흐름 구현
3. 추가 카메라·개체·사육장 등록 및 metadata 규칙 적용
4. 300건 사람 blind GT로 Gate v2 최종 감사
5. 일상·희소 클래스와 paired hard negative 지속 수집·검수
6. Gate v3 Nano 학습과 shadow 운영
7. production VLM baseline과 router-cost-v2 계약 동결
8. 동결 이후 future camera-night로 품질·비용 adoption 평가

## 9. 완료 조건

- [ ] 라벨링 웹 v2 구현 스펙 승인
- [ ] camera/animal/enclosure/night metadata 스키마와 수집 SOP 확정
- [ ] backlog 300 전체 human-first blind GT와 Gate v2 감사 report
- [ ] 신규 카메라·개체가 포함된 v3 train/validation 데이터셋 버전 동결
- [ ] Gate v3 shadow 시작, 자동 skip off 확인
- [ ] production VLM/router 계약 동결 이후 future holdout 수집 시작
