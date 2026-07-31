# RBA 사건 단위 전수 분석 방향 설계

> **상태:** `OWNER_APPROVED / PHASE1_HARNESS_IMPLEMENTED_VERIFIED / PRODUCTION_PREPARE_AUTH_BLOCKED`
>
> **작성일:** 2026-07-31
>
> **한 줄 결정:** 게코의 실제 활동 원본은 전부 보존·열람 가능하게 두고, 연속된 클립을
> 논리적 사건으로 묶어 모든 사건이 최소 한 번의 저비용 local VLM 분석을 끝내게 한다.
> 모호하거나 중요한 사건만 cloud VLM과 사람 검수로 올린다.

## 1. 배경

Universal Python Evidence는 모든 `motion_clips`에 값싼 OpenCV 수치를 만들지만, 현재 그 원시
수치의 production 소비처와 사용자 효용은 제한적이다. 합성 점수로 “볼만한 top-N”을 고른 T1도
blind informative 차이 `+5%p`로 채택 기준 `+10%p`를 통과하지 못했다. Gate v2 역시 recall
90.9%로 자동 제외 기준을 통과하지 못했다.

따라서 Python Evidence나 Gate를 판정기로 사용해 영상을 감추면 실제 활동을 잃을 수 있다.
반대로 모든 원본 클립을 cloud VLM에 각각 보내면 중복 장면 때문에 비용과 결과량이 커진다.

owner가 확정한 제품 요구는 두 가지다.

1. 에러·흔들림 영상이 아니라 실제 게코 활동이라면 사용자가 원본을 모두 볼 수 있어야 한다.
2. 모든 활동 사건은 결국 최소 하나의 AI 분석 결과를 가져야 한다.

이 설계는 둘을 동시에 만족시키기 위해 **영상 수를 줄이지 않고, 중복 표시와 중복 분석을
사건 단위로 줄이는 방향**을 채택한다.

## 2. 선택한 접근과 기각한 접근

| 접근 | 판정 | 이유 |
|---|---|---|
| 고정 top-N만 사용자에게 제공 | 기각 | 큰 움직임·특정 카메라 오염에 치우치며 실제 활동을 누락할 수 있다. T1 합성점수 v1도 reject다. |
| 모든 클립을 각각 cloud VLM에 전송 | 기각 | 전수 범위는 만족하지만 연속 장면을 반복 분석해 비용과 결과 중복이 커진다. |
| **원본 전부 보존 + 논리적 사건 묶음 + 사건별 local VLM 1차 분석** | **채택 방향** | 전수 열람과 전수 분석을 유지하면서 같은 사건의 중복 호출을 줄일 수 있다. 다만 사건 묶기와 local VLM 품질은 아직 검증 전이다. |

## 3. 용어와 불변 계약

### 원본 클립

카메라가 생산해 R2와 DB에 등록한 개별 영상이다. 사건 묶음이 생겨도 원본 파일, 식별자,
촬영 시각과 provenance는 바꾸거나 합치지 않는다.

### 활동 사건

같은 카메라에서 시간상 이어지는 하나의 활동 흐름을 가리키는 **논리적 묶음**이다. 여러
클립이 한 사건에 속할 수 있지만 새 합성 영상으로 원본을 대체하지 않는다. 사용자는 사건
카드에서 원본을 순서대로 재생하거나 개별 클립을 펼쳐 볼 수 있어야 한다.

사건 경계가 애매하면 합쳐서 행동 전환을 묻기보다 나누는 쪽을 우선한다. 정확한 시간 간격,
최대 사건 길이, 전환 감지 규칙은 이 문서에서 임의로 고정하지 않는다. 구현 전 별도
TEST-SHEET에서 사람의 사건 경계 GT와 평가 지표를 먼저 동결한다.

### 분석 완료

모든 사건은 아래 중 하나의 terminal outcome에 도달해야 한다.

- 구체적 행동 후보: 관찰 근거가 충분한 경우
- 일반 활동 관찰: 이동, 등반, 자세 변화처럼 더 세분하기 어려운 경우
- 게코가 보이지 않음
- 카메라·조명·흔들림 artifact
- 판정 불가: 정보가 부족하거나 분석 실패가 해소되지 않은 경우

전수 분석은 **모든 사건에 억지로 구체 행동 라벨을 붙인다는 뜻이 아니다.** 근거가 부족하면
일반 활동 또는 판정 불가가 정답이다.

## 4. 목표 데이터 흐름

```text
카메라 원본 클립
→ 모든 클립에 Python/OpenCV Evidence 생성
→ 같은 카메라의 연속 클립을 논리적 활동 사건으로 묶음
→ 사건별 클립 목록·클립별 시각 표본·Evidence 요약 생성
→ local VLM이 모든 사건을 1차 분석
    ├─ 충분한 관찰 → 사건 결과 완료
    ├─ 모호·희소·케어 중요 후보 → cloud VLM
    └─ 모델 충돌·고가치 사건 → 사람 검수
→ 사용자 타임라인에서 사건 요약 + 모든 원본 재생
```

모든 정상 원본은 사건에 속해야 한다. 미디어 누락·디코딩 불가처럼 실제 파일 무결성 오류만
별도 integrity 상태로 분리한다. `gecko_visible=false`, 낮은 motion score, Gate absent,
Python Evidence 점수는 원본 은닉이나 자동 skip 근거가 아니다.

사건 묶기가 사건 내부의 새 top-N 필터가 되어서도 안 된다. 사건에 속한 **모든 원본 클립은
최소 하나의 실제 시각 표본이나 짧은 시간축 구간을 local VLM 입력에 제공**해야 한다. 한 번의
모델 입력 한도를 넘으면 원본을 버리지 않고 여러 analysis chunk로 나눈 뒤 결과만 사건 단위로
합친다. 정확한 sampling과 chunk 크기는 모델·입력 한도를 확인한 후 별도 TEST-SHEET에서
동결한다.

## 5. 구성요소별 역할

| 구성요소 | 이 방향에서 할 일 | 하지 않을 일 |
|---|---|---|
| Python/OpenCV Evidence | 저비용 시계열 센서, 대표 프레임 후보, 사건 경계 힌트, 분석 provenance | 행동 확정, 사용자 원본 숨김, 자동 skip |
| Gate v3 | 게코 bbox·best frame·trajectory를 shadow evidence로 보강 | 단독 행동 확정, 검증 전 presence 필터 |
| local VLM | 실제 프레임을 보고 모든 사건의 1차 관찰과 abstain 생성 | 근거 없는 케어행동 확정, 사람 GT 덮어쓰기 |
| local text LLM | 검증된 structured result가 생긴 뒤 요약·정렬 후보로만 재검토 | 영상을 보지 않고 행동 판정, 과거 router v0/v1/v2 재채택 |
| cloud VLM / SegmentVLM | 모호하거나 중요한 사건의 시간축 정밀 분석 | 모든 원본 클립에 무조건 중복 호출 |
| 사람 검수 | 모호·충돌·고가치 사건의 GT 확정과 모델 감사 | 모델 결과를 먼저 보고 blind GT 생성 |

과거 local router v0/v1/v2와 care-guard v1/v1.1은 계속
`invalid-for-adoption`이다. 이 방향은 그 결과를 되살리는 계획이 아니다.

## 6. 사용자 경험 계약

사용자에게는 “오늘 영상 87개”만 던지는 대신 “활동 사건 14개”처럼 먼저 보여줄 수 있다.
각 사건에는 짧은 AI 관찰, 촬영 시간, 원본 수를 표시한다.

```text
02:14~02:18 · 활동 사건 · 원본 4개
AI 관찰: 벽면을 따라 이동함
[연속 재생] [원본 4개 펼치기]
```

연속 재생은 원본을 차례로 재생하는 UX다. 선택적 proxy 영상은 훗날 성능상 필요할 때만 만들며,
정본이나 유일한 열람 경로로 쓰지 않는다. AI가 `판정 불가`를 내도 원본 접근성은 달라지지 않는다.

## 7. 현재 SOT와 실행 우선순위

이 방향은 RBA Data Engine v1을 교체하지 않는다. 오히려 사건 묶기와 local/cloud VLM을
평가할 사람 정답을 먼저 확보해야 하므로 현재 순서를 유지한다.

1. formal Blind30 v2로 사람 라벨 계약을 독립 검증
2. backlog 300 human-first Gate 감사와 다양한 camera/animal/enclosure GT 축적
3. 사건 묶기 shadow TEST-SHEET 동결·실행
4. 사건별 local VLM 전수 shadow
5. cloud VLM/SegmentVLM escalation과 사람 검수
6. 검증을 통과한 뒤 사용자 사건 타임라인

사건 묶기 기술 타당성은 기존 non-holdout 자료로 read-only/offline 탐색할 수 있다. 그러나
그 결과는 adoption 근거가 아니며, future holdout이나 formal Blind30 표본을 튜닝에 재사용하지
않는다. 현재 Data Engine·Blind30·Gate 작업을 멈추거나 우선순위를 뒤집지 않는다.

## 8. 단계별 검증

### Phase 1 — 사건 묶기 shadow

측정 항목:

- 대상 기간 `motion_clips` 전수의 accounting coverage
- 한 행동 전환을 잘못 합친 over-merge
- 한 사건을 불필요하게 나눈 over-split
- 사건 경계의 사람 수정량과 검수 시간
- 카메라·밤별 편향

실패하면 clip 단위 표시를 유지한다. 사건 묶기 실패가 원본 누락으로 이어지면 즉시 reject다.
사건 경계 사람 GT는 자유문장이 아니라 같은 카메라·활동일의 **인접 clip pair**마다
`same_event / different_event / uncertain` 중 하나를 고르는 방식으로 수집한다.

- over-merge: 사람 GT가 `different_event`인데 알고리즘이 같은 사건으로 묶음
- over-split: 사람 GT가 `same_event`인데 알고리즘이 다른 사건으로 나눔
- uncertain: 두 오류율 분모에서는 제외하되 별도 비율로 보고

v0는 camera, activity day, `started_at`, `duration_sec`과 시간 gap만 사용하는
metadata-only 결정론으로 고정한다. Python Evidence와 Gate를 사용한 경계는 이 실험의
adoption 후보가 아니며 후속 비교군으로만 다룬다. exact 표본과 수용 임계값은
[`Phase 1 TEST-SHEET`](../../../experiments/rba-event-grouping-shadow-v1/TEST-SHEET.md)에
사전등록한다.

### Phase 2 — local VLM 전수 shadow

측정 항목:

- 모든 사건의 terminal outcome 완료율
- 재시도·실패·처리 지연과 Mac mini 자원 사용량
- 사람 blind GT 대비 관찰 일치도와 케어행동 false positive
- 카메라·IR·가림·희소행동별 품질
- 사건당 처리 비용과 처리량

기존 SmolVLM2 Evidence Analyst 설계는 이 단계의 좁은 선행 벤치마크로 재사용할 수 있다.
그 벤치마크 통과가 곧 전수 행동 분석 채택을 뜻하지는 않는다.

### Phase 3 — escalation

측정 항목:

- local 완료 / cloud 상향 / 사람 검수 비율
- P0·희소행동 recall
- cloud가 회복한 사건과 새로 망가뜨린 사건의 수
- 사건당 최종 비용, 처리 지연, 미해결 비율

cloud 비율의 목표치는 모델·입력·가격을 동결한 `router-cost-v2` 계열 TEST-SHEET에서
사전 등록한다. 비용을 줄이기 위해 P0 후보를 숨기거나 `activity_only`로 자동 강등하지 않는다.

### Phase 4 — 사용자 노출

사건 묶음과 AI 결과가 독립 future holdout을 통과한 뒤에만 앱 타임라인을 바꾼다. 기존 원본
목록으로 돌아갈 수 있는 fail-open 경로와 AI 결과 정정 이력을 유지한다.

## 9. 실패 처리와 안전 경계

- 사건 묶기 실패: 해당 clip을 단독 사건으로 처리하고 원본은 그대로 노출한다.
- 사건 입력 초과: 일부 clip을 생략하지 않고 여러 analysis chunk로 나눠 처리한다.
- local VLM 실패: 제한 재시도 후 cloud 또는 `판정 불가`로 끝내며 숨기지 않는다.
- Python Evidence/Gate 충돌: reliability를 낮추는 신호일 뿐 어느 한쪽으로 자동 확정하지 않는다.
- cloud/local 충돌: 사람 검수 후보로 올리고 기존 사람 GT를 덮어쓰지 않는다.
- 미디어 무결성 오류: 사용자에게 분석 실패와 원본 상태를 구분해 표시한다.
- 검증된 장치·미디어 오류: 기존 visibility-first 계약의 가역 격리만 허용한다. local VLM의
  `artifact` 출력만으로 자동 격리하지 않는다.
- 모델·prompt·threshold 변경: provenance를 새 버전으로 저장하고 기존 결과를 재해석하지 않는다.

Phase 1의 `event_id`는 `algorithm_version + camera_id + activity_day + 시간순 clip_id 목록`의
정규화된 SHA-256으로 만든다. 같은 입력의 재실행은 event membership, event ID, summary hash가
100% 같아야 한다. late-arriving clip이나 알고리즘 변경으로 다시 계산할 때 기존 결과를
수정하지 않고 새 version artifact를 append한다.

`정상 원본`이라는 이름으로 분모를 줄이지 않는다. 대상 기간의 모든 `motion_clips`는
`activity_event`, 사유코드가 있는 `diagnostic_integrity`, 또는 formal/canary/frozen holdout
접촉을 막는 `blocked_research` 중 하나에 정확히 귀속돼야 한다. 검증된 system exclusion은
diagnostic으로 기록하고 사건 연속성을 끊지만, local VLM의 `artifact` 추측이나 Python/Gate
점수만으로 diagnostic을 만들지 않는다. `blocked_research`도 accounting 분모에는 남으며
사건·boundary pair에만 들어가지 않는다.

## 10. 이 문서가 승인하지 않는 것

- DB schema, RPC, 앱 화면, worker 구현
- production 서비스·LaunchAgent 변경
- 모델 다운로드·설치·실행
- 사건 경계 숫자와 수용 임계값
- local VLM 또는 cloud VLM의 production 채택
- 자동 skip, 원본 삭제, 하이라이트만 노출
- formal Blind30 v2, Gate v2/v3, 사람 GT 계약 변경

다음 구현 논의는 이 방향을 하나의 큰 작업으로 바로 만들지 않고, **Phase 1 사건 묶기 shadow**
하나만 별도 TEST-SHEET와 구현 설계로 분리한다.

## 11. 2026-07-31 Claude Fable 5 교차리뷰 반영

iTerm의 기존 Claude Code `Fable 5 / high effort` 세션에 정본 네 파일을 읽기 전용으로
교차리뷰시켰다. 판정은 `APPROVE_WITH_CHANGES`였고 다음을 채택했다.

1. 사건 경계 GT를 인접 clip pair의 3값 판정으로 고정한다.
2. 대상 기간 clip 전수를 분모로 삼아 integrity가 새 암묵 skip 경로가 되지 않게 한다.
3. Phase 1 표본은 Blind30 v2 future pool 시작 전의 닫힌 activity day만 사용하고 모든
   formal/canary clip을 제외한다.
4. v0는 metadata-only이며 Python Evidence/Gate 경계는 범위 밖이다.
5. camera-night 단위 dev/holdout 분리, 카메라별 지표, 결정론적 event ID와 재실행 동일성을
   수용 조건으로 둔다.

리뷰가 제안한 “케어행동 pair over-merge 0”은 Phase 1 boundary GT가 행동 GT를 새로 만들지
않는다는 범위와 충돌하므로 독립 gate로 채택하지 않았다. 대신 모든 `different_event`
over-merge를 0건으로 요구해 더 넓게 막는다.
