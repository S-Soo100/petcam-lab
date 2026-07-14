# 라벨링 튜토리얼 쉬운 말·입력 복구·v2 전환 설계

> 상태: **공통 쉬운 말·highlight 계약·입력 복구 production 배포 완료 · tutorial-v2 콘텐츠 전환은 조건부 backlog** (2026-07-14)
> 대상: `https://label.tera-ai.uk/labeling/tutorial`, tutorial lesson, 실제 라벨링 공유 폼
> 현재 운영: `tutorial-v1` active, 승인 대기 0명·활동 중 라벨러 2명·두 명 모두 0/5.
> 핵심 결정: 공통 코드 개선은 `main`/production에 반영했다. 먼저 v1에서 지정 pilot 1명의 5/5·본 큐·첫 본작업 5개를 확인하고, 실제 이해 문제가 보고될 때만 기존 이력을 보존한 `tutorial-v2` 콘텐츠 seed·activation을 재개한다.

## 1. 배경

실제 파일럿 사용자가 `tutorial-v1`을 3/5까지 진행하면서 다음 문제를 확인했다.

1. `GT`, `Blind GT`, `VLM`, `target`, `enrichment`, `wheel`, `action` 같은 내부 용어를 이해하지 못한다.
2. 튜토리얼 전체 과정과 각 단계에서 무엇을 해야 하는지 설명이 부족하다.
3. 입력 필드 제목과 설명이 개발자 관점이라 사람이 어떤 사실을 기록해야 하는지 알기 어렵다.
4. 제출 후 피드백에 영문 enum과 JSON이 그대로 보인다.
5. 쳇바퀴만 선택한 뒤 저장할 때 상호작용 방법이 필요하다는 오류가 뒤늦게 나온다.
6. 다른 페이지를 다녀오거나 창을 최소화했다가 돌아오면 저장 전 입력이 초기화될 수 있다.
7. `활동 강도`는 현재 제품이 필요한 `하이라이트 포함 여부`와 다른 개념이다.

이번 작업의 목적은 문구 몇 개를 바꾸는 것이 아니다. 도메인 지식이 없는 팀원이 화면만 읽고
`사람의 독립 판정 → AI 판정 비교 → 기준 해설`을 이해하고, 저장 전 입력을 잃지 않으며,
기술 데이터 형식을 보지 않고 5개 교육을 끝내게 만드는 것이다.

## 2. 목표와 제외 범위

### 목표

- 첫 화면만 읽고 사람 판정, AI 판정, 기준 해설의 차이를 이해한다.
- 튜토리얼과 실제 라벨링에서 같은 쉬운 용어를 사용한다.
- 필드마다 무엇을 보고 무엇을 고르는지 화면 안에서 설명한다.
- 저장하기 전에 필요한 연관 입력을 미리 안내한다.
- 피드백에서 모든 enum, 배열, 행동 구간을 사람이 읽는 한국어로 보여준다.
- 페이지 이동, 창 비활성화, 토큰 갱신, 새로고침 후에도 저장 전 입력을 복원한다.
- `tutorial-v1` 시도 이력을 보존하고 `tutorial-v2`를 독립적인 새 교육으로 시작한다.

### 제외 범위

- 기존 v1 attempt/progress 삭제 또는 수정
- 기존 production GT의 활동 강도 값을 하이라이트 판정으로 일괄 변환
- 새 하이라이트 판정을 Flutter 하이라이트 API에 즉시 연결
- 튜토리얼을 한 질문씩 별도 페이지로 나누는 대규모 wizard 재작성
- 정답·reference·feedback 조기 공개

## 3. 검토한 접근

### A. 현재 화면의 문구만 교체

빠르지만 DB lesson 문구 불변, raw enum/JSON, 인증 이벤트 초기화, 입력 복구 문제가 남는다.
또한 튜토리얼과 본작업의 공유 폼이 서로 다른 언어를 쓰게 된다. 채택하지 않는다.

### B. 공통 폼 쉬운 말화 + 입력 복구 + tutorial-v2

공유 표시 계층을 만들고, 상태 보존을 고친 뒤, 새 lesson 문구와 피드백을 v2로 seed한다.
기존 보안·정답 보호·append-only 이력을 유지하면서 문제를 해결할 수 있다. **채택한다.**

### C. 질문별 wizard 전면 재작성

초보자에게 가장 단순하지만 페이지와 상태 머신을 크게 다시 만들어야 한다. 현재 파일럿 문제를
해결하는 데 필요한 범위를 넘는다. v2 실사용 이후에도 이탈이 높을 때만 재검토한다.

## 4. 사용자 체험 설계

### 4.1 튜토리얼 요약

`[화면]` 라벨러는 5개 lesson 목록보다 먼저 `이 튜토리얼에서 하는 일` 카드를 본다.

표시 문구:

> 영상 5개를 보면서 실제 라벨링 방법을 연습해.
> 각 영상은 사람 판정 → AI 판정 비교 → 기준 해설 확인 순서로 진행해.
> 점수나 불합격은 없고, 5개 해설을 모두 확인하면 실제 작업이 열려.

용어 설명:

| 화면 용어 | 설명 |
|---|---|
| 사람 판정(GT) | 사람이 영상을 보고 직접 정한 답 |
| AI를 보기 전 사람 판정(Blind GT) | AI 답을 보기 전에 먼저 저장하는 사람의 답 |
| 영상 분석 AI(VLM) | 영상을 보고 게코 행동을 추정하는 AI |
| 기준 답 | 관리자가 영상을 다시 확인해 만든 교육 기준 |

과정 표시:

`1 영상 보기 → 2 사람 판정 저장 → 3 AI 판정 확인 → 4 서로 비교 → 5 해설 확인`

`[조작]` 라벨러가 `튜토리얼 시작`을 누른다.

`[반응]` lesson 1로 이동하고 현재 단계가 `1단계 · 사람 판정`으로 표시된다.

`[감정]` 라벨러는 시험을 보는 것이 아니라 실제 업무 흐름을 연습한다고 이해한다.

### 4.2 사람 판정 입력

`[화면]` 영상 오른쪽에 다음 순서로 입력 질문이 보인다.

1. 게코가 보이나?
2. 이 영상의 대표 행동은?
3. 영상에서 확인한 모든 동작과 시간
4. 대표 행동에 맞춘 동적 대상 질문
5. 이 판단이 얼마나 확실한가?
6. 하이라이트 여부
7. 촬영 환경
8. 놀이로 볼 수 있는 행동 근거(조건부)

`[조작]` 라벨러가 영상을 반복 재생하며 답을 고른다.

`[반응]` 선택한 대표 행동에 맞춰 도움말과 대상 질문이 바뀐다. 쳇바퀴·사물 상호작용을
고르면 `사용한 사물`과 `사용한 방법` 두 항목이 동시에 필수임을 즉시 보여준다.

`[감정]` 라벨러는 내부 데이터 구조를 몰라도 영상에서 본 사실을 질문 순서대로 기록할 수 있다.

### 4.3 사람 판정 저장과 AI 공개

production 저장 전 안내(2026-07-14 확정):

> 저장하면 되돌릴 수 없습니다. 저장후 AI가 판단한 정보를 표시해 드리겠습니다

버튼: `사람 판정 저장하고 AI 판정 보기`

`GT 잠그고`, `⌥↵`, 숫자 단축키는 튜토리얼에서 노출하지 않는다. 단축키 기능을 유지하더라도
관리자용 도움말 안으로만 이동한다.

저장 후 요약:

- `잠긴 최초 GT` → `AI를 보기 전에 저장한 사람 판정`
- `bias 방지 기록` → `AI 영향 없이 기록됨`

### 4.4 AI 판정 비교

- `VLM 판정 원문` → `영상 분석 AI의 판정`
- `confidence` → `AI 확신도`
- raw model/snapshot은 일반 라벨러에게 숨기고 owner에게만 `기술 정보`로 제공한다.

판정 안내:

> 위에 표시된 AI의 대표 행동과 내가 저장한 대표 행동을 비교해.
> AI가 말하지 않은 세부 동작이나 놀이 정보는 여기서 감점하지 않아.

| 저장값 | 화면 표시 | 설명 |
|---|---|---|
| `correct` | 같음 | AI의 대표 행동이 사람 판정과 같음 |
| `partially_correct` | 일부만 맞음 | 완전히 같지는 않지만 행동의 일부 의미는 맞음 |
| `incorrect` | 다름 | AI가 다른 행동으로 판단함 |
| `unjudgeable` | 비교하기 어려움 | 영상이나 AI 판정이 불명확해 비교하기 어려움 |

### 4.5 기준 해설

피드백 그룹은 다음처럼 표시한다.

| 기존 | 변경 |
|---|---|
| 네 답 | 라벨러 판정 |
| 일치 | 기준과 같음 |
| 다시 볼 기준 | 기준과 다른 항목 |
| 개인차 가능 | 사람마다 다르게 판단할 수 있는 항목 |

`사람마다 다르게 판단할 수 있는 항목`에는 다음 설명을 붙인다.

> 이 항목은 하나의 정답으로 고정하지 않아. 사람마다 다르게 판단할 수 있으며 틀린 답으로 처리하지 않아.

raw 값은 절대 그대로 렌더하지 않는다.

- `moving` → `일반 이동`
- `wheel_interaction` → `쳇바퀴 상호작용`
- `rotate`, `ride` → `회전시키기`, `올라타기`
- `{ action, start_sec, end_sec }` JSON → `핥기 13.0초~31.8초`
- 배열 → 한국어 항목을 쉼표로 연결
- `none` → `없음`

`[감정]` 라벨러는 개발자용 데이터 비교가 아니라 자기 판단과 기준의 차이를 설명받는다.

## 5. 입력 필드 상세 계약

### 5.1 대표 행동

제목: `이 영상의 대표 행동은?`

설명:

> 영상에서 가장 중요하게 보이는 행동 하나를 골라줘. 아래 항목에 해당하지 않으면 `일반 이동`으로 선택해.

`사람 급여`의 화면 라벨은 `사람이 직접 먹임`으로 바꾼다. 저장 enum `hand_feeding`은 유지한다.

도움말:

> 사람이 손이나 도구로 먹이를 직접 먹이는 장면

### 5.2 실제 동작과 시간

제목: `영상에서 확인한 모든 동작과 시간`

설명:

> 대표 행동과 별개로 게코가 실제로 한 동작을 모두 선택해.
> 동작을 선택하면 그 동작이 시작한 시간과 끝난 시간을 입력해.

예시:

> 영상 전체에서 핥았다면 `0.0초 ~ 31.8초`

화면 입력값과 해설은 소수점 첫째 자리까지만 표시한다. 서버 저장 정밀도와 1초 비교 허용오차는
기존 계약을 유지한다. 영상 duration이 `31.7999`여도 입력 초기값은 표시 단계에서 `31.8`로 정규화한다.

### 5.3 대표 행동 대상

고정 제목 대신 대표 행동에 따라 질문을 바꾼다.

| 대표 행동 | 제목 | 설명 |
|---|---|---|
| 물 마시기 | 무엇을 핥거나 마셨나? | 게코의 입이 실제로 닿은 대상을 고른다. 물이 직접 안 보여도 접촉한 표면을 근거로 판단한다. |
| 사람이 직접 먹임 | 무엇으로 직접 먹였나? | 손을 사용해 직접 먹였는지, 도구를 사용해 먹였는지 선택한다. |
| 나머지 | 이 행동은 무엇을 향했나? | 게코가 대표 행동을 하면서 직접 닿거나 향한 대상을 고른다. |

공통 보조 설명:

> 쳇바퀴나 장난감을 사용한 행동은 아래 `놀이 행동 근거`에 기록해.

화면 문구에서는 `wheel` 대신 `쳇바퀴`를 사용한다.

### 5.4 판단 확실도

- 제목: `이 판단이 얼마나 확실한가?`
- `certain` → `확실함`
- `likely` → `아마 맞음`
- `uncertain` → `잘 모르겠음`
- `unjudgeable` → `영상만으로 판단 불가`

### 5.5 놀이 행동 근거

제목: `놀이로 볼 수 있는 행동 근거`

설명:

> 게코가 쳇바퀴나 사물을 실제로 사용했다면, 무엇을 사용했고 어떻게 사용했는지 모두 기록해.

항목을 번호로 나눈다.

1. `사용한 사물 선택`
2. `사용한 방법 선택 · 하나 이상 필수`

쳇바퀴를 선택하면 저장 전부터 다음 문구를 보여준다.

> 쳇바퀴를 선택했다면 `올라타기·밀기·회전시키기` 중 실제로 확인한 방법을 하나 이상 골라줘.

기존 client/server의 object+interaction type 동시 필수 검증은 유지한다. 오류는 상단뿐 아니라
빠진 두 입력 바로 아래에 표시하고 첫 오류로 이동한다.

## 6. 하이라이트 판정 데이터 계약

### 6.1 표시만 바꾸지 않는 이유

기존 `activity_intensity=low|medium|high`는 움직임의 세기를 뜻한다. 이를 화면에서
`제외|애매|포함`으로만 바꾸면 같은 저장값이 버전에 따라 다른 의미가 되어 기존 GT와 신규 GT를
구분할 수 없다. 따라서 별도 필드로 분리한다.

### 6.2 새 필드

```ts
type HighlightRecommendation = 'exclude' | 'uncertain' | 'include';
```

GT JSON 키: `highlight_recommendation`

화면:

- 제목: `하이라이트 여부`
- `exclude` → `제외`
- `uncertain` → `애매`
- `include` → `포함`

설명:

> 이 영상이 고객에게 보여줄 만한 장면인지 골라줘. 일반 이동이라도 움직임이 크거나 눈에 띄면
> `포함`할 수 있어. 탈피, 달리기, 핥기, 먹이 포획처럼 의미 있는 행동도 `포함`으로 선택해.
> 잘 모르겠으면 `애매`를 골라줘.

### 6.3 호환 정책

- 기존 `activity_intensity` 값은 과거 GT에서 보존한다.
- `GroundTruthInput.activity_intensity`는 legacy read를 위해 `low|medium|high|null`을 허용한다.
- 신규 입력에서는 `activity_intensity=null`로 저장하고, 이를 요구하거나 새 의미로 재사용하지 않는다.
- 신규 non-absent GT는 `highlight_recommendation`을 반드시 직접 고른다.
- `visibility='absent'`면 `highlight_recommendation='exclude'`로 정규화하고 화면에서 숨긴다.
- v2 튜토리얼 비교는 `highlight_recommendation`을 비교하고 `activity_intensity`는 비교하지 않는다.
- v1 attempt/reference/comparison은 불변 이력으로 유지한다.
- production current GT와 mirror payload가 새 키를 보존하도록 저장·보정 계약을 갱신한다.
- downstream 하이라이트 API가 이 값을 사용하는 작업은 별도 스펙으로 남긴다.

기준 영상 5개에는 owner가 v2 seed 전에 새 하이라이트 판정을 직접 확인해 revision으로 남긴다.
기존 활동 강도 값을 자동 변환하지 않는다.

## 7. 공통 표시 계층

영문 enum과 기술 용어가 각 컴포넌트에 흩어지지 않도록 하나의 표시 모듈을 둔다.

예상 책임:

- 행동, 가시성, 대상, 확실도, 환경, 상호작용, VLM verdict, 오류 원인 표시명
- 행동별 동적 질문과 도움말
- 숫자 시간의 소수점 첫째 자리 포맷
- segment를 `행동 0.0초~31.8초`로 변환
- 배열과 `none/null`의 사람용 표시
- owner 기술 정보와 일반 라벨러 표시 분리

저장 enum과 API payload는 표시 문자열로 바꾸지 않는다. UI만 공통 formatter를 사용한다.

## 8. tutorial-v2 콘텐츠 계약

### 8.1 제출 전 문구 원칙

- 한 문단 최대 두 문장
- 내부 영문 키 사용 금지
- 해당 영상의 기준 답을 직접 알려주지 않음
- 무엇을 관찰하고 어느 칸에 기록할지만 설명

position 3 상단 목표 예시:

> 한 영상에 여러 행동이 함께 나올 수 있어. 가장 중요한 행동 하나를 고른 뒤,
> 그 행동의 대상과 놀이에 사용한 사물은 각각 알맞은 칸에 기록해.

position 3 제출 전 팁 예시:

> 대표 행동을 하면서 직접 닿은 대상은 `행동 대상`에서 고르고,
> 쳇바퀴나 장난감을 어떻게 사용했는지는 `놀이 행동 근거`에 기록해.

기존 `target`, `enrichment_object`, `wheel evidence`, `drinking+wheel` 표현은 제출 전에 노출하지 않는다.

### 8.2 lesson 교육 목표

| position | 쉬운 교육 목표 |
|---|---|
| 1 | 게코가 보이지 않을 때 무엇을 비워야 하는지 익힌다. |
| 2 | 특별한 의미 행동이 없을 때 일반 이동을 선택하는 기준을 익힌다. |
| 3 | 대표 행동의 대상과 놀이에 사용한 사물을 다른 칸에 기록한다. |
| 4 | 사람이 직접 먹인 장면을 손·도구·실제 섭취 근거로 확인한다. |
| 5 | 사람 판정과 AI 판정이 다를 때 AI 오류를 기록한다. |

reference GT, prediction snapshot, reference VLM review, feedback의 정답 보호 계약은 v1과 동일하다.

## 9. 입력 보존과 새로고침 원인

### 9.1 확인한 코드 경로

`labeling/layout.tsx`는 Supabase `onAuthStateChange` 이벤트가 올 때 이벤트 종류를 구분하지 않고
`accessChecked=false`로 만든다. 토큰 자동 갱신이 창 비활성화·복귀 시 발생하면 레이아웃이
중립 화면으로 바뀌며 lesson 컴포넌트가 내려갈 수 있다. lesson의 저장 전 GT는 React state에만 있어
다시 load될 때 `emptyGt`로 초기화된다.

구현 후 회귀 테스트로 `TOKEN_REFRESHED`에서 화면을 유지하는 계약을 확인했다. preview 실브라우저에서는
lesson 입력 후 새로고침해도 `작성 중인 내용을 복원했어` 안내와 선택값이 돌아오는 것을 확인했고,
production 로그인 세션에서는 요약·lesson 렌더와 console error 0을 확인했다.

### 9.2 인증 이벤트 처리

- `TOKEN_REFRESHED`: 같은 user라면 기존 access와 child 화면을 유지한다.
- `SIGNED_IN`: user id가 바뀐 경우에만 access를 다시 확인한다.
- `SIGNED_OUT`: access와 draft를 폐기하고 로그인으로 이동한다.
- `USER_UPDATED` 또는 실제 권한 갱신 버튼: access를 다시 확인한다.
- 단순 갱신 중 전체 `NeutralScreen`으로 자식을 언마운트하지 않는다.

### 9.3 브라우저 임시 저장

서버에는 미완성 GT를 자동 저장하지 않는다. 같은 탭의 `sessionStorage`에만 저장한다.

키 구성에는 최소한 user id, tutorial set id/version, lesson position을 포함한다.

저장 대상:

- GT 입력
- 직접 선택한 필드 목록
- VLM review 입력(아직 제출 전인 경우)
- 저장 시각

동작:

- 입력 변경 시 debounce 저장
- lesson load 후 서버 attempt가 draft이고 임시본이 있으면 복원
- 복원 시 `작성 중인 내용을 복원했어` 표시
- GT 저장 성공 시 GT 임시본 삭제
- VLM review 제출 성공 시 review 임시본 삭제
- lesson 완료, 로그아웃, tutorial version 변경 시 사용 금지 또는 삭제
- 다른 사용자의 임시본을 절대 복원하지 않음

## 10. 상태·보안·데이터 흐름

```text
v1 active + 기존 3/5 attempt
  → 코드/표시 계층 배포
  → owner가 기준 5개의 highlight_recommendation 확인·revision
  → tutorial-v2 draft 생성
  → 기존 seed RPC의 reference 의미 preflight
  → owner preview
  → v2 activation
  → activation RPC가 v1 archive
  → progress가 set별이므로 파일럿 사용자는 v2 0/5
  → v1 attempt/progress는 읽기 가능한 역사로 보존
```

유지해야 할 계약:

- 제출 전 reference/prediction/feedback key 미노출
- tutorial attempt는 production `behavior_labels`를 생성하지 않음
- 최초 제출 답 불변
- active/archived lesson 불변
- owner bypass와 labeler 5/5 서버 게이트
- v2 activation 전 active는 v1 하나만 유지

## 11. 오류 처리

- 필요한 연관 입력은 사용자가 선택하는 순간 안내한다.
- 저장 시 전체 이슈를 계산하되 첫 오류로 이동한다.
- 오류는 해당 필드 바로 아래에 쉬운 말로 표시한다.
- 서버 `issues[]`도 같은 표시 문구를 사용한다.
- 임시 저장 실패는 제출을 막지 않되 `이 브라우저에서 임시 저장하지 못했어`라고 한 번만 알린다.
- 임시본 parse/version 오류는 조용히 폐기하고 빈 폼으로 시작한다.
- v2 seed·activation 오류는 fail-loud하고 v1 active를 유지한다.

## 12. 구현 예상 범위

### 공통 UI·표시

- `web/src/app/labeling/_labeling-forms.tsx`
- 신규 공통 표시/format 모듈
- `web/src/app/labeling/tutorial/_tutorial-feedback.tsx`
- `web/src/app/labeling/tutorial/page.tsx`
- `web/src/app/labeling/tutorial/[position]/page.tsx`
- 필요 시 production 상세·owner correction의 표시명 동기화

### 상태 보존

- `web/src/app/labeling/layout.tsx`
- tutorial/production draft 저장 hook 또는 순수 serializer
- 인증 이벤트·draft 복구 테스트

### 데이터 계약

- `web/src/lib/labelingV2.ts`
- `web/src/lib/labelingTutorial.ts`
- GT·revise·tutorial API validator와 테스트
- owner 보정·seed 의미 preflight의 highlight 필드 지원
- DB 함수가 JSON payload를 제한한다면 후속 migration으로만 변경

### 콘텐츠·릴리스

- `tutorial-v2` seed template 또는 승인된 service-role RPC 실행 입력
- lesson 1~5 쉬운 목표·팁·feedback
- SOT, onboarding, FEATURES, DATABASE, next-session 갱신

## 13. 테스트 계약

### 단위·렌더 테스트

- enum을 모두 한국어로 변환하며 raw key가 남지 않는다.
- segment `31.7999`가 `31.8초`로 표시된다.
- 대표 행동에 따라 대상 질문과 도움말이 바뀐다.
- 사람이 직접 먹임 설명과 손/도구 질문이 표시된다.
- 쳇바퀴 선택 시 사용 방법 필수 안내가 즉시 보인다.
- feedback에 `네 답`, raw JSON, `personal/subjective` 내부 표현이 없다.
- v2 comparison은 highlight를 비교하고 legacy activity intensity를 비교하지 않는다.

### 상태 회귀 테스트

- `TOKEN_REFRESHED`에서 child와 입력 state를 유지한다.
- user가 바뀐 `SIGNED_IN`과 `SIGNED_OUT`에서는 state를 폐기한다.
- 같은 user/set/lesson 임시본만 복원한다.
- 다른 page 이동 후 복귀, browser reload 후 복원한다.
- GT 저장·VLM 제출 후 해당 임시본을 삭제한다.

### API·DB 테스트

- 신규 non-absent GT에 highlight 필드가 없으면 400 `issues[]`.
- absent는 highlight exclude로 정규화된다.
- v1 legacy GT는 계속 읽고 owner가 확인할 수 있다.
- v2 seed 5개가 새 reference와 feedback을 완비한다.
- v2 activation 시 v1 archived·v2 active가 원자적으로 처리된다.
- v1 attempt/progress 수가 바뀌지 않는다.

### 실제 라벨러 E2E

1. 요약 화면 용어 설명을 읽고 흐름을 말로 설명한다.
2. v2 0/5에서 시작한다.
3. lesson 입력 중 다른 페이지를 다녀와도 값이 유지된다.
4. 창을 최소화했다 복귀해도 값이 유지된다.
5. 강제 새로고침 후 임시본 복원 안내가 보인다.
6. 5개 모든 feedback이 한국어 문장으로 읽힌다.
7. 5/5 후 일반 큐가 열린다.

## 14. 배포 순서와 중단점

1. ✅ 구현 계획 승인
2. ✅ 쉬운 말 표시 계층·폼·feedback 테스트 및 구현
3. ✅ highlight 데이터 계약 테스트 및 구현
4. ✅ 인증 이벤트 회귀 테스트·입력 임시 저장 구현
5. ✅ web 245·tsc·Vercel production build·Python 334
6. ✅ preview owner E2E(새로고침 임시본 복원 포함)
7. ✅ production 코드 배포(`0702e66`)·v1 active 유지
8. 🚧 활동 중 라벨러 2명 중 1명 v1 0/5→5/5 pilot
9. ⏳ 본 큐 진입·첫 본작업 5개 owner 확인
10. ⏳ 문제 없으면 전체 팀 개방·라벨링 웹 기능 동결
11. ⏸ pilot이 내부 용어 이해 문제를 보고할 때만 기준 영상 5개의 highlight revision 재개
12. ⏸ tutorial-v2 draft seed·preview·activation(v1 자동 archive)
13. ⏸ v2를 활성화한 경우에만 기존 파일럿 v2 0/5→5/5 재검증
14. ⏳ pilot 결과를 SOT·온보딩 문서에 최종 기록

현재 release gate는 v1 pilot이며 v2는 gate가 아니다. v2를 재개할 경우에는 seed·preview·activation을
각각 이전 단계 검증 뒤 실행하고, v1을 직접 archive하지 않는다. activation RPC가 새 set 활성화와
기존 set archive를 같은 트랜잭션에서 처리한다.

## 15. 완료 조건

아래는 `tutorial-v2`를 다시 열 때 사용하는 완료 조건이다. 현재 production 공통 폼·표시·입력 복구는
배포됐지만 active lesson 콘텐츠는 v1이므로, v2 전용 조건을 현재 release 완료 조건으로 간주하지 않는다.

- 설명 없는 `GT`, `Blind GT`, `VLM`, `wheel`, `target`, `enrichment`, `action`이 일반 라벨러 화면에 없다.
- 첫 화면만 읽고 전체 5단계 과정을 이해할 수 있다.
- 대표 행동, 실제 동작, 대상, 놀이 근거의 차이를 질문형 문구로 이해한다.
- 사람 판정 잠금의 목적과 수정 불가를 저장 전에 이해한다.
- `같음/일부만 맞음/다름/비교하기 어려움`의 뜻이 화면에 있다.
- feedback에 raw enum·JSON이 없다.
- 하이라이트 판정이 legacy activity intensity와 별도 필드로 저장된다.
- 쳇바퀴·사물 상호작용의 object와 method 필수 조건을 저장 전에 이해한다.
- 화면 시간은 소수점 첫째 자리까지만 보인다.
- page 이동·창 복귀·토큰 갱신·새로고침 뒤 미제출 입력이 유지된다.
- v1 3/5 이력이 보존되고 v2는 같은 사용자에게 0/5로 시작한다.
- v2 5/5 후 production 큐가 열린다.

## 16. 사용자 요청 추적표

| 요청 | 반영 위치 |
|---|---|
| GT·Blind GT 설명 | §4.1 요약 용어 카드 |
| 전체 과정 안내 | §4.1 5단계 흐름 |
| 사람 확신도 쉬운 말 | §5.4 `이 판단이 얼마나 확실한가?` |
| lesson 상단 기술 문장 쉬운 말화 | §8.1 제출 전 문구 원칙·position 3 예시 |
| 대표 행동에 일반 이동 안내 | §5.1 |
| 사람 급여 설명 | §5.1 `사람이 직접 먹임` |
| 사람 급여 대상 설명 | §5.3 `무엇으로 직접 먹였나?` |
| 실제 세부 동작 설명 | §5.2 |
| `0~31.7999` 시간 표시 | §5.2 소수점 첫째 자리 |
| wheel을 쳇바퀴로 표시 | §5.3·§7 공통 formatter |
| 대표 행동 대상 제목 개선 | §5.3 행동별 동적 질문 |
| GT 잠금 의미 설명 | §4.3 |
| GT 잠금 버튼·단축키 개선 | §4.3 쉬운 버튼, 단축키 비노출 |
| VLM 판정 품질 설명 | §4.4 |
| 부분 정답 설명 | §4.4 `일부만 맞음`과 정의 |
| 일치·개인차 가능 설명 | §4.5 |
| 쳇바퀴 interaction type 사전 안내 | §5.5 |
| 활동 강도→하이라이트 정책 | §6 별도 데이터 계약 |
| 네 답→라벨러 판정 | §4.5 |
| 다른 페이지·최소화·복귀 초기화 | §9 인증 이벤트·sessionStorage |
