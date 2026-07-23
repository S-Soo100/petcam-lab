# P4 Cam 1 쳇바퀴 에피소드 중복 묶음 설계

> 상태: `DESIGN_READY_FOR_OWNER_REVIEW`
> 작성일: 2026-07-23
> 범위: P4 Cam 1 owner 라벨링 UX의 read-only shadow 설계
> 구현·DB 변경·배포: 미실행

## 1. 문제와 목표

P4 Cam 1에서는 한 번의 쳇바퀴 사용이 여러 motion clip으로 잘려 라벨링 큐에 반복해서 나타난다.
각 영상은 행동 증거로 가치가 있지만, owner가 거의 같은 장면을 모두 따로 판단하는 것은 비효율적이다.

목표는 영상을 삭제하거나 `제외`로 바꾸는 것이 아니다.

- 같은 쳇바퀴 사용 에피소드로 판단되는 clip을 하나의 **중복 묶음**으로 접는다.
- 묶음에서 서로 다른 장면을 대표하는 영상 2~3개를 먼저 보여준다.
- 원본 clip은 언제든 펼쳐 보고 개별 라벨링할 수 있게 보존한다.
- 자동 GT 전파, 자동 제외, R2 삭제는 하지 않는다.

## 2. production read-only 감사

2026-07-23 production DB를 SELECT-only로 감사했다. DB/R2 write와 VLM 호출은 없었다.

### 2.1 표본

- P4 Cam 1 최근 72시간: motion clip 840개
- Python Evidence run: 840개
- 사람 GT가 있는 clip: 47개
- `enrichment_object=wheel`: 24개
- 그 밖의 사람 GT: 23개

### 2.2 반복 밀도

확인된 wheel GT 24개를 시간 간격으로만 나누면 다음과 같다.

| 에피소드 경계 | 그룹 수 |
|---|---:|
| 90초 | 11 |
| 180초 | 9 |
| 10분 | 4 |

10분 경계의 4개 그룹에는 각각 5·3·7·9개 clip이 들어간다. 대표 2~3개만 먼저 보여주면
이 표본의 검토량은 24개에서 8~12개로 줄어들 가능성이 있다. 다만 이는 이미 라벨된 작은 EDA
표본이며 adoption 수치가 아니다.

### 2.3 시간만으로 묶을 수 없는 이유

wheel GT가 발생한 전체 시간 범위에는 clip 54개가 있었다.

- wheel GT: 24개
- 다른 사람 GT: 12개
- 미라벨: 18개

따라서 “10분 이내 clip”만으로 묶으면 다른 행동을 섞을 위험이 크다.

### 2.4 일반 Python Evidence만으로 묶을 수 없는 이유

현재 generic evidence 분포도 wheel과 non-wheel이 크게 겹쳤다.

| 지표 | wheel 중앙값 | non-wheel 중앙값 |
|---|---:|---:|
| ROI mean motion | 0.2407 | 0.2295 |
| peak autocorrelation | 0.7132 | 0.6420 |
| global mean motion | 0.1607 | 0.1153 |

`spatial_dwell`도 wheel/non-wheel이 같은 셀에 몰렸다. 일반 임계값 하나로 묶는 방식은 안전하지 않다.

## 3. 결정 게이트

| 게이트 | 판정 | 근거 |
|---|---|---|
| G1 SOT 부합 | 통과 | 제품은 24시간 원본 나열보다 의미 있는 사건을 정리하며, 사람 blind GT 생산 효율이 현재 우선순위다. |
| G2 기대효과 | 통과 | 확인 표본에서 24개 wheel clip이 4개 시간 에피소드에 집중됐다. shadow에서 실제 절감률을 측정한다. |
| G3 측정 가능 | 통과 | fresh P4 Cam 1 camera-night, 제안 membership, 혼합 행동 오병합, 대표 장면 보존율을 고정 지표로 감사할 수 있다. |
| G4 유효한 계획 | 통과 | P4 Cam 1 read-only shadow → owner 전수 감사 → 별도 승인 후 DB/UI canary 순으로 범위를 나눈다. |

판정은 **shadow 설계 승인**이다. production 자동 묶음과 UI 반영은 이 문서 검토 후 별도 구현 승인을
받아야 한다.

## 4. 비교한 접근

### A. 시간 간격만 사용

구현은 가장 쉽지만 같은 시간대의 다른 행동을 섞는다. **기각**한다.

### B. 모든 clip을 VLM으로 비교

의미 비교는 가능하지만 반복 영상 감소를 위해 다시 많은 VLM 호출을 쓰게 된다. 결과 비결정성과 비용도
남는다. **기각**한다.

### C. 고정 쳇바퀴 ROI + 시각 유사도 + 시간 경계

P4 Cam 1의 고정 쳇바퀴 영역을 버전이 있는 profile로 정의한다. 같은 profile 안에서만 ROI motion
시간축, 프레임 지문, 촬영 모드를 비교하고 시간은 바깥쪽 에피소드 경계로만 쓴다. **권장안**이다.

## 5. 사용자가 실제로 경험하는 흐름

1. **[화면]** 미분류 큐에 일반 영상과 함께 `쳇바퀴 유사 영상 9개` 묶음 카드가 보인다. 카드에는
   대표 썸네일 2~3개와 시간 범위가 표시된다.
2. **[조작]** owner가 묶음을 누른다.
3. **[반응]** 대표 영상이 먼저 열리고, `전체 9개 펼치기`로 모든 원본을 볼 수 있다. 각 원본은 기존
   상세 라벨링 화면으로 이동할 수 있다.
4. **[조작]** owner가 묶음이 타당하면 `중복 묶음 확인`, 잘못 섞였으면 `묶음 해제`를 누른다.
5. **[반응]** 확인된 묶음은 기본 큐에서 한 카드로 접히지만 `중복 묶음` 탭에서 원본 전체가 보존된다.
6. **[감정]** owner는 같은 장면을 반복 판정하지 않아도 되고, 중요한 영상이 삭제됐다는 불안을 느끼지
   않는다.

## 6. 판정 데이터 흐름

### 6.1 Phase 1 — read-only shadow

입력:

- `motion_clips`: camera, 시작 시각, duration, R2 key
- `clip_python_evidence_runs`: global/ROI motion, periodicity, provenance
- R2에서 임시로 읽은 소수의 대표 프레임
- P4 Cam 1 전용 `wheel_roi_profile_v1`

clip signature:

- camera/profile version
- IR/day 모드와 프레임 밝기 fingerprint
- 쳇바퀴 ROI motion 시계열 요약
- ROI 대표 프레임 perceptual hash
- Python Evidence quality/provenance

그룹 조건:

1. 같은 camera와 같은 ROI profile이어야 한다.
2. 10분 시간 간격은 에피소드의 최대 외곽 경계로만 사용한다.
3. ROI motion 패턴과 프레임 지문이 모두 유사해야 한다.
4. 촬영 모드, 화면 구도, 주요 시각 변화가 다르면 묶지 않는다.
5. 증거가 없거나 품질이 낮으면 **미분류 상태로 그대로 둔다**.

Phase 1은 JSON/Markdown 감사 artifact만 만든다. production DB와 라벨링 웹은 바꾸지 않는다.

### 6.2 대표 영상 선택

한 묶음에서 최대 3개를 고른다.

1. 게코/ROI evidence 품질이 가장 좋은 영상
2. 쳇바퀴 ROI motion이 가장 큰 영상
3. 앞의 두 영상과 시각적으로 다른 경계·novelty 영상

셋째 조건에 해당하는 영상이 없으면 2개만 유지한다. 대표가 아닌 원본도 삭제하지 않는다.

### 6.3 Phase 2 — owner 승인 후 전용 저장 계약

shadow가 통과한 뒤에만 다음과 같은 전용 개념을 추가한다.

- `motion_clip_similarity_groups`
- `motion_clip_similarity_members`
- group type: `wheel_episode`
- profile/algorithm/version/provenance
- representative 여부와 owner review 상태

기존 `motion_clip_labeling_triage.owner_decision`의 `label/hold/skip`에 중복 의미를 억지로 넣지 않는다.
`skip`은 “라벨링 가치 없음”이고, `duplicate membership`은 “가치 있지만 같은 에피소드의 반복”이므로
서로 다른 축이다.

## 7. 안전 계약

- R2 object를 삭제하거나 lifecycle을 바꾸지 않는다.
- 기존 GT, session, revision, triage decision을 자동 변경하지 않는다.
- 같은 묶음의 GT를 다른 clip에 자동 복사하지 않는다.
- 이미 라벨된 clip을 조용히 숨기지 않는다.
- camera, ROI profile, 촬영 모드가 다르면 절대 묶지 않는다.
- 증거 누락, R2 미존재, profile drift, 높은 novelty는 전부 `ungrouped`로 남긴다.
- Phase 1에서 VLM을 호출하지 않는다.
- production worker의 lock/deadline을 침범하지 않고 temp media는 종료 시 0이어야 한다.

## 8. 사전등록할 평가 계약

fresh 표본 조건:

- P4 Cam 1 독립 camera-night 3개 이상
- 제안된 membership 100개 이상
- 이미 사용한 wheel GT 24개는 회귀/EDA로만 사용
- owner는 evidence와 점수를 보지 않고 묶음 전체를 감사

hard gate:

- 서로 다른 행동을 하나로 합친 false merge: **0건**
- 관찰된 서로 다른 wheel interaction type의 대표 영상 보존율: **100%**
- 같은 입력에서 group id/membership 결정론: **100%**
- 한 clip이 두 그룹에 들어가는 overlap: **0건**
- known confirmed wheel 표본의 우선 검토량 감소: **50% 이상**
- temp media: **0**
- production worker deadline 지연과 exit/error 증가: **0**

재현율을 높이기 위해 애매한 clip을 억지로 묶지 않는다. 안전한 precision-first가 목표다.

## 9. 단계

1. **S0 설계·시험지:** 이 문서 검토 후 read-only shadow TEST-SHEET를 동결한다.
2. **S1 shadow:** P4 Cam 1에서 artifact만 생성하고 owner가 전수 감사한다.
3. **S2 판정:** hard gate를 하나라도 어기면 reject하고 UI/DB를 만들지 않는다.
4. **S3 canary:** 별도 승인 후 전용 DB 계약과 owner-only 묶음 UI를 제한 배포한다.
5. **S4 확장:** 다른 카메라는 별도 ROI profile과 fresh audit를 통과해야 한다.

## 10. 범위 밖

- 자동 `skip` 또는 자동 라벨
- GT 전파
- 모든 카메라에 같은 ROI 적용
- VLM 호출량·selector 변경
- 앱 활동시간 변경
- R2 영상 삭제
- 쳇바퀴 행동의 세부 의미 분류

## 11. 구현 전 owner 검토 항목

권장 기본값은 다음과 같다.

- 대표 영상 최대 3개
- 시간 외곽 경계 10분
- Phase 1은 production write가 없는 shadow
- false merge 1건이면 production 묶음 도입 중단

이 네 항목을 owner가 승인하면 별도 실행 계획과 handoff manifest를 작성한다.
