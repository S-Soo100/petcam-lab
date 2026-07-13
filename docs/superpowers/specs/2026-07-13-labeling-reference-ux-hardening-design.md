# 라벨링 기준 GT·튜토리얼 UX 하드닝 설계

> 상태: **코드 구현 완료 · 마이그레이션 2종 Supabase 적용+rollback probe 통과 (2026-07-13)**.
> 남음(별도 승인): owner e679/d934 UI 보정(§9) · tutorial seed/activation · production 배포.
> 검증: web 155 tests + tsc + Python 334 통과. `npm run build` 는 레포 훅 때문에 사용자 터미널에서 실행 필요.
> 구현 범위 = §12 step 1~7·11(중단 후 사용자 검토). step 8~10(preview 배포·owner 실보정·preflight 실행)과 13~17은 미실행.
>
> 연관 문서:
> - `docs/superpowers/specs/2026-07-12-labeling-web-v2-design.md`
> - `docs/superpowers/specs/2026-07-13-labeling-interactive-tutorial-design.md`
> - `migrations/2026-07-13_labeling_tutorial_seed_template.sql`

## 1. 배경

owner가 튜토리얼 기준 영상 5개를 실제 production 라벨링 화면에서 검수하면서 다음 문제가 확인됐다.

1. 화면이 `visible / moving / medium`을 기본 선택해서, 라벨러가 영상을 충분히 판단하지 않아도 유효한 GT처럼 저장할 수 있다.
2. wheel interaction을 고르면 `enrichment_object`와 `interaction_types`가 필요하지만, 저장 실패가 화면 상단에만 표시되어 빠진 입력 위치를 찾기 어렵다.
3. `행동 대상`이 대표 행동의 대상이라는 설명이 부족해, drinking+wheel 영상에서 대상이 `tool`로 저장됐다.
4. 대표 행동 `hand_feeding`과 세부 행동 `licking / prey_capture`의 계층이 설명되지 않아, 라벨러가 “3번에 hand feeding이 왜 없나?”라고 느낀다.
5. `absent / unseen`에서도 활동 강도 기본값 `medium`이 저장되고 튜토리얼 exact 비교 대상이 된다.
6. GT 잠금 후 `initial_gt`를 지키면서 `current_gt`만 감사 가능하게 보정할 owner UX가 없다.
7. seed 함수는 구조적 완전성만 검사한다. lesson 목적과 reference GT가 의미적으로 맞는지는 막지 못한다.
8. 현재 튜토리얼 4번 문구는 `복수 행동·object interaction`인데, 실제 선정 후보는 `hand_feeding` 교육 영상이다.

이번 설계는 발견된 두 건만 직접 수정하는 일회성 처방이 아니다. 같은 실수를 일반 라벨러가 반복하지 않도록 입력 경험, 서버 계약, 보정 감사, seed 사전검사를 함께 고친다.

## 2. 목표

- 라벨러가 기본값을 정답으로 오인하지 않고 가시성과 대표 행동을 직접 판단한다.
- 대표 행동, 실제 관찰 동작, 대표 행동 대상, enrichment evidence의 차이를 화면 안에서 이해한다.
- 저장 오류가 누락된 필드 바로 옆에 표시되고 첫 오류로 자동 이동한다.
- `hand_feeding`, `drinking`, wheel/object interaction의 명백한 논리 모순을 client와 server가 같은 규칙으로 차단한다.
- 최초 blind 답인 `initial_gt`는 영구 보존하면서 owner가 `current_gt`와 VLM review를 사유와 함께 보정할 수 있다.
- 튜토리얼 5개 reference가 각 lesson 목적에 맞지 않으면 seed 전에 fail-loud 한다.
- 현재 선정한 5개 기준 영상을 감사 가능한 방식으로 보정한 뒤 다시 검토할 수 있다.

## 3. 비목표

- 전체 행동 taxonomy 재설계
- `hand_feeding`을 `observed_actions`와 `segments`에 새로 추가
- `activity_intensity`에 `not_applicable` 같은 신규 enum 추가
- 일반 라벨러의 잠긴 GT 수정 허용
- VLM prediction 원문 수정
- 숫자 점수·합격/불합격 기반 튜토리얼 도입
- 튜토리얼 seed, activation, production 배포 실행
- 과거 전체 라벨 일괄 정정

## 4. 핵심 결정

### 4.1 대표 행동과 세부 행동은 분리한다

`primary_action`은 영상 전체에서 가장 대표적인 의미 행동이다. `observed_actions`와 `segments`는 게코가 실제로 수행한 관찰 가능한 동작이다.

- `hand_feeding` + `licking`: 손/도구가 음식을 전달하고 게코가 핥아 먹음
- `hand_feeding` + `prey_capture`: 손/도구가 먹이를 전달하고 게코가 낚아챔
- `drinking` + `licking`: 물·물그릇·표면의 물을 핥아 마심
- `drinking` + `wheel_interaction` + `licking`: 한 영상 안에 wheel 사용과 음수가 모두 존재

3번 섹션 제목은 `관찰된 모든 행동과 구간`에서 `게코가 실제로 한 세부 동작과 구간`으로 바꾼다. 설명 문구는 “대표 행동을 반복 선택하는 곳이 아니라, 화면에서 실제로 본 동작을 모두 기록하는 곳”이라고 명시한다.

### 4.2 `행동 대상`은 `대표 행동 대상`으로 명명한다

wheel은 drinking의 target이 아니다. 다음 세 필드는 서로 다른 질문이다.

| 필드 | 질문 | drinking+wheel 예시 |
|---|---|---|
| `target` | 대표 행동은 무엇을 대상으로 했나? | `water` 또는 `water_bowl` |
| `enrichment_object` | 놀이 후보 상호작용 대상은 무엇인가? | `wheel` |
| `interaction_types` | 그 물체와 어떻게 상호작용했나? | `ride`, `rotate` |

UI 라벨을 `행동 대상`에서 `대표 행동 대상`으로 바꾸고, primary action별 도움말과 허용 대상 목록을 제공한다.

### 4.3 신규 taxonomy 없이 조건부 의미를 적용한다

`activity_intensity` enum은 이번 범위에서 확장하지 않는다. `visibility='absent'`이면 활동 강도는 화면에서 숨기고, 저장된 호환값은 제품·학습·튜토리얼 비교에서 의미가 없는 값으로 취급한다.

튜토리얼 비교는 absent reference에서 `activity_intensity`를 `subjective`로 분류한다. visible/partial/uncertain reference에서는 기존 exact 비교를 유지한다.

### 4.4 VLM verdict는 VLM이 실제 출력한 축만 평가한다

현재 prediction snapshot은 대표 `action`을 출력한다. 따라서 drinking+wheel 영상에서 VLM action이 `drinking`이면 wheel metadata를 출력하지 않았다는 이유만으로 `partially_correct`로 만들지 않는다.

- 대표 action이 GT와 맞으면 `correct`
- 대표 action 일부만 맞거나 상위·하위 행동 경계가 불완전하면 `partially_correct`
- 대표 action이 다르면 `incorrect`
- 영상 근거로 비교할 수 없으면 `unjudgeable`

`multi_action_missed`는 해당 prediction 계약이 복수 행동을 출력하도록 정의된 경우에만 사용한다. 튜토리얼 문구도 이 범위를 명시한다.

## 5. 라벨러 체험 설계

### 5.1 최초 진입

`[화면]` 영상과 “1. 게코가 보이나?”만 명확히 활성화된다. 대표 행동에는 선택된 검은 버튼이 없다.

`[조작]` 라벨러가 영상을 재생하고 가시성을 선택한다.

`[반응]` 선택에 따라 필요한 다음 입력만 열린다. 아직 보지 않은 항목은 중립 상태로 남는다.

`[감정]` 시스템이 정답을 미리 찍어준다는 인상을 받지 않고, 첫 판단부터 자신이 책임지고 선택한다.

### 5.2 absent/unseen

`[화면]` `안 보임`을 누르면 대표 행동 `안 보임`이 자동 선택됐다는 안내가 표시된다.

`[반응]` 세부 행동, 구간, 대표 행동 대상, 활동 강도, enrichment 입력은 숨기거나 `해당 없음`으로 읽기 전용 처리한다. 값은 다음처럼 정규화한다.

- `primary_action='unseen'`
- `observed_actions=[]`
- `segments=[]`
- `target='none'`
- `enrichment_object='none'`
- `interaction_types=[]`

기존 JSON 계약 때문에 `activity_intensity` 호환값은 유지하지만 UI·비교·제품 의미에서 제외한다.

`[감정]` “안 보이는데 활동 강도를 왜 고르지?”라는 모순을 만나지 않는다.

### 5.3 일반 행동

`[조작]` 대표 행동을 선택한다.

`[반응]` 대표 행동 바로 아래에 한 줄짜리 행동별 도움말이 나온다. 세부 행동 영역에는 대표 행동과 다른 역할임을 설명한다.

- moving: 위치 이동·등반·자세 변경
- drinking: 물과 입의 실제 접촉·반복 핥기
- hand feeding: 사람의 손/도구가 먹이를 입으로 직접 전달
- shedding: 허물이 실제로 벗겨지는 장면

### 5.4 hand feeding

`[화면]` `사람 급여`를 선택하면 “사람 급여의 객관 근거” 체크리스트가 열린다.

1. 실제 세부 동작: `핥기` 또는 `먹이 포획`
2. 대표 행동 대상: `손` 또는 `도구`
3. 촬영 환경 근거: `사람 등장`

각 항목은 기존 입력 컨트롤을 가리키며, 별도의 중복 데이터를 만들지 않는다. 체크리스트는 해당 필드가 충족되면 자동으로 완료 표시된다.

`[오류]` 저장 시 세 조건 중 하나라도 없으면 첫 누락 필드로 스크롤하고 포커스를 준다. “사람 급여는 손/도구가 먹이를 직접 전달하고, 게코가 핥거나 포획한 근거가 필요해.”라고 설명한다.

### 5.5 drinking과 wheel interaction이 함께 있는 영상

`[화면]` 대표 행동이 drinking이면 `대표 행동 대상`에는 `물`, `물그릇`, `유리/벽`, `바닥`, `불확실`만 표시한다.

`[조작]` 라벨러가 `쳇바퀴 상호작용`도 고른다.

`[반응]` 보라색 evidence 패널이 열리고 `쳇바퀴`와 `올라타기/밀기/회전시키기/...`를 별도로 받는다. 패널 상단에 “이 값은 대표 행동 대상과 별개야”라고 표시한다.

`[오류]` object나 interaction type이 빠지면 보라색 패널 자체에 오류가 표시된다. 상단 토스트는 요약만 하고, 사용자를 해당 패널로 이동시킨다.

### 5.6 저장과 VLM 공개

`[조작]` 라벨러가 `GT 잠그고 VLM 확인`을 누른다.

`[반응]` client가 전체 이슈 목록을 계산한다. 이슈가 없을 때만 API를 호출한다. server도 같은 규칙으로 재검증한다.

`[성공]` 최초 GT가 잠기고 VLM snapshot이 공개된다.

`[실패]` `detail` 한 줄과 함께 `issues[]`가 반환된다. UI는 섹션별 인라인 오류를 표시하고 첫 오류로 이동한다. 입력값은 사라지지 않는다.

## 6. 입력 상태와 검증 계약

### 6.1 중립 초깃값

API에 보내는 `GroundTruthInput`은 기존 비-null 계약을 유지한다. 화면에서는 별도 draft 상태와 명시적 선택 여부를 관리한다.

권장 인터페이스:

```ts
type GroundTruthField =
  | 'visibility'
  | 'primary_action'
  | 'observed_actions'
  | 'segments'
  | 'target'
  | 'human_confidence'
  | 'context_tags'
  | 'activity_intensity'
  | 'enrichment_object'
  | 'interaction_types';

interface GroundTruthDraftState {
  value: GroundTruthInput;
  explicitlySelected: Set<GroundTruthField>;
}

interface GroundTruthValidationIssue {
  field: GroundTruthField;
  code: string;
  message: string;
}
```

기존 기본 payload를 완전히 nullable로 바꾸지 않는다. 공유 form과 production/tutorial API의 변경 폭을 줄이면서 UI의 preselection만 제거한다.

### 6.2 공통 검증 함수

client와 server는 하나의 순수 규칙 함수를 공유한다.

```ts
function collectGroundTruthIssues(
  input: GroundTruthInput,
  clipDurationSec: number,
  explicitlySelected?: ReadonlySet<GroundTruthField>,
): GroundTruthValidationIssue[];
```

`validateGroundTruth`는 이 결과가 비어 있지 않으면 첫 메시지를 `detail`로 사용하고 전체 `issues`를 포함한 typed error를 던진다.

필수 규칙:

1. 가시성과 대표 행동을 라벨러가 명시적으로 선택해야 한다.
2. absent는 unseen 정규화 계약을 만족해야 한다.
3. visible/partial/uncertain은 관찰 행동이 하나 이상이어야 한다.
4. 모든 observed action에는 정확히 하나의 segment가 있어야 한다.
5. segment는 `0 <= start < end <= duration`이어야 한다.
6. wheel/object interaction에는 object와 interaction type이 모두 있어야 한다.
7. drinking target은 `water / water_bowl / glass / floor / uncertain` 중 하나여야 한다.
8. hand feeding에는 `licking` 또는 `prey_capture`, target `hand` 또는 `tool`, context `human`이 모두 있어야 한다.
9. `playing`은 직접 primary action으로 저장할 수 없다.

server는 `explicitlySelected`를 받지 않으므로 값 기반 규칙만 강제한다. “직접 선택” 여부는 client 전용 UX 계약이다.

### 6.3 API 오류 형식

기존 client 호환을 위해 `detail`은 유지한다.

```json
{
  "detail": "쳇바퀴 상호작용 방식을 하나 이상 골라줘.",
  "issues": [
    {
      "field": "interaction_types",
      "code": "interaction_type_required",
      "message": "쳇바퀴 상호작용 방식을 하나 이상 골라줘."
    }
  ]
}
```

`issues`가 없는 오래된 오류 응답도 client가 계속 처리해야 한다.

## 7. owner 전용 현재 GT 보정

### 7.1 원칙

- `initial_gt`는 절대 바꾸지 않는다.
- `current_gt`만 보정한다.
- completed session만 보정할 수 있다.
- owner 본인이 검수한 session만 owner가 보정한다.
- 사유는 10~500자 필수다.
- 수정 전후 GT와 VLM review를 append-only로 기록한다.
- correction과 `behavior_labels` mirror 갱신은 한 DB transaction이어야 한다.
- 일반 labeler와 browser Supabase client는 revision table에 직접 접근할 수 없다.

### 7.2 데이터 모델

신규 테이블 `clip_labeling_session_revisions`:

| 컬럼 | 타입 | 의미 |
|---|---|---|
| `id` | uuid PK | revision id |
| `session_id` | uuid FK | 보정 대상 session |
| `clip_id` | uuid FK | 조회·감사용 clip |
| `revised_by` | uuid FK | 보정한 owner |
| `previous_gt` | jsonb | 보정 전 current GT |
| `revised_gt` | jsonb | 보정 후 current GT |
| `previous_vlm_review` | jsonb | 기존 verdict/error_tags/note |
| `revised_vlm_review` | jsonb | 보정 후 verdict/error_tags/note |
| `reason` | text | 10~500자 보정 사유 |
| `created_at` | timestamptz | 감사 시각 |

RLS는 켜고 client policy는 0건으로 유지한다. `anon/authenticated/public`의 함수 실행권한도 revoke한다.

### 7.3 원자적 RPC

`fn_revise_clip_labeling_session(...)`은 service role 전용이다.

1. completed session과 `reviewed_by = revised_by`를 잠근다.
2. 현재 값을 revision table에 insert한다.
3. `current_gt`, `vlm_verdict`, `vlm_error_tags`, `vlm_review_note`, `updated_at`을 update한다.
4. `behavior_labels`의 action, lick_target, note를 같은 transaction에서 upsert한다.
5. `initial_gt`, prediction snapshot, gt_locked_at, completed_at은 변경하지 않는다.

API route는 bearer 인증 → owner 확인 → body 검증 → 공통 GT/VLM validator → RPC 순서로 호출한다.

### 7.4 보정 UX

completed 화면의 owner에게만 `현재 GT 보정` 버튼을 표시한다.

`[화면]` 최초 GT 요약 아래에 “최초 blind GT는 보존돼. 아래 수정은 현재 기준 답과 감사 기록만 갱신해.”라는 경고가 나온다.

`[조작]` owner가 기존 current GT로 채워진 form을 수정하고 VLM verdict를 다시 확인한다. 보정 사유를 입력한다.

`[반응]` 저장 전에 바뀐 필드 요약을 보여주고 한 번 확인한다. 성공하면 revision 시각과 사유가 표시된다.

일반 labeler에게는 버튼, route, revision 데이터가 모두 노출되지 않는다.

## 8. 튜토리얼 reference 사전검사

### 8.1 공통 구조 검사

기존 seed 함수의 다음 계약은 유지한다.

- draft set only
- owner completed session
- current GT와 prediction snapshot 존재
- `completion_reason='vlm_reviewed'`
- VLM verdict 존재
- 비어 있지 않은 feedback

### 8.2 v1 lesson 의미 검사

seed template는 lesson insert 전에 다음 조건을 모두 검사하고 하나라도 실패하면 transaction을 중단한다.

| 위치 | 목적 | 필수 의미 조건 |
|---|---|---|
| 1 | 가시성·unseen | absent, unseen, observed/segments empty, target none |
| 2 | 일반 이동 | visible/partial, primary moving, observed moving, moving segment |
| 3 | drinking+wheel | **primary drinking**, **target ∈ {water,water_bowl,glass,floor,uncertain}**, wheel interaction, enrichment wheel, interaction type 1개 이상, 세부 행동 2개 이상 |
| 4 | 사람 급여 | primary hand_feeding, licking/prey_capture, target hand/tool, context human |
| 5 | VLM 오류 검수 | VLM action shedding, human primary != shedding, verdict incorrect, error tag 1개 이상 |

검사 오류는 clip prefix, 위치, 실패 이유를 포함하되 비밀값은 포함하지 않는다.

> **4차 하드닝(`_hardening_4.sql`, 2026-07-13) 반영.** (a) position 3 은 이전 `target != tool` 만으로는
> `moving+wheel` 같은 잘못된 reference 도 통과했다 — lesson 3 은 "drinking 의 target 은 물, wheel 은
> 별도 enrichment" 를 가르치므로 **primary drinking + target ∈ 물 집합**(DRINKING_TARGETS)까지 요구한다.
> (b) 모든 의미 검사는 `IF NOT (조건)` 이 아니라 `IF (조건) IS NOT TRUE` 형태다 — JSON 키가 없어서
> 결과가 NULL 이 되면 `NOT (NULL)` 도 NULL 이라 검사를 통과해버리는 구멍을 막는다(필드 누락이면 반드시 차단).
> TS 미러(`evaluateTutorialReferenceSemantics`)도 동일 조건으로 갱신했다.

### 8.3 lesson 문구

1. `가시성과 unseen 구분`
2. `일반 이동`
3. `대표 행동 대상과 wheel evidence 분리`
4. `사람 급여의 객관 근거`
5. `모프·IR로 인한 VLM 오판 검수`

4번의 목표와 팁은 다음 내용을 포함한다.

- hand feeding은 손/도구의 존재만으로 정하지 않는다.
- 음식이 입으로 직접 전달되는 장면이어야 한다.
- 실제 세부 동작은 licking 또는 prey capture로 기록한다.
- target은 hand/tool, context는 human으로 기록한다.

## 9. 현재 5개 기준 영상 보정 계약

| 위치 | clip prefix | 현재 상태 | 구현 후 필요한 조치 |
|---|---|---|---|
| 1 | `53d52acb` | absent/unseen, activity medium | GT는 유지. absent activity 비교 제외를 확인 |
| 2 | `e8470f25` | moving | 변경 없음 |
| 3 | `e679f8ad` | drinking+wheel, target tool | owner 보정으로 target을 실제 물 근거에 맞게 `water` 또는 `water_bowl`로 변경 |
| 4 | `d9346cbe` | hand feeding+licking+tool, human tag 없음 | owner 보정으로 context `human` 추가 |
| 5 | `8669a5ff` | drinking, VLM shedding incorrect | 변경 없음 |

3번 target의 최종값은 owner가 영상을 다시 보고 결정한다. 구현자가 임의로 `water` 또는 `water_bowl`을 선택하지 않는다.

두 보정은 owner 보정 UI와 revision RPC를 통해 수행한다. raw SQL로 current GT를 직접 update하지 않는다.

## 10. 보안·무결성

- 기존 `protect_initial_labeling_gt` trigger를 유지하고 회귀 테스트한다.
- revision table은 RLS ON, client policy 0건이다.
- revision RPC는 service role만 실행 가능하다.
- owner API는 `DEV_USER_ID` 기반 owner 검사를 통과해야 한다.
- 요청 body의 `revised_by`, `session_id`, `clip_id`를 신뢰하지 않는다. bearer와 URL로 서버가 결정한다.
- DB 오류 원문, 테이블명, 내부 RPC 메시지를 client에 노출하지 않는다.
- correction API는 일반 labeler에 403, session 없음에 404, DB 오류에 일반 502를 반환한다.
- correction 이유는 화면에 표시될 수 있으므로 비밀값 입력 금지 안내를 둔다.
- seed·activation 보안 계약과 active lesson 불변 trigger는 수정하지 않는다.

## 11. 테스트 전략

### 11.1 순수 로직

- 기본 UI에서 가시성·대표 행동이 선택된 것처럼 보이지 않는다.
- absent 정규화와 activity 비교 제외
- drinking target 허용/차단 조합
- hand feeding 세 가지 근거 조합
- interaction object/type 누락별 issue field
- segment action 누락·중복·범위 오류
- VLM verdict validation
- 튜토리얼 5개 reference 의미 검사 fixture

### 11.2 UI

- primary action별 도움말 표시
- hand feeding 체크리스트 자동 완료
- 첫 오류로 scroll/focus
- interaction panel 인라인 오류
- completed owner에게만 correction button 표시
- correction form에 current GT가 로드되고 initial GT 경고 표시
- 일반 labeler에게 correction UI 미노출

### 11.3 API

- GT route가 `detail + issues[]` 400을 반환
- 오래된 `detail` only 오류도 client 처리
- correction 무인증 401, 비owner 403, 없음 404, DB 오류 502
- correction 성공 시 session current GT와 VLM review 반환
- revision 값은 일반 API 응답에 불필요하게 노출하지 않음

### 11.4 DB

- initial GT 변경 시 trigger 차단
- revision insert와 session/behavior_labels update 원자성
- 실패 시 revision/session/behavior_labels 모두 rollback
- completed 아닌 session 보정 차단
- 다른 reviewer session 보정 차단
- revision RLS/client policy 0
- RPC public/anon/authenticated 실행권한 없음
- 기존 tutorial active/archived 불변 trigger 회귀

### 11.5 전체 검증

- `cd web && npm test`
- `cd web && npx tsc --noEmit`
- `cd web && npm run build`
- `uv run pytest`
- migration apply 후 transaction rollback probe
- preview에서 owner와 일반 labeler E2E

## 12. 구현 순서와 릴리스 게이트

1. 공통 검증 issue 모델과 회귀 테스트
2. 중립 선택·조건부 form·인라인 오류 UX
3. tutorial conditional comparison과 lesson copy
4. revision table/RPC 후속 migration
5. owner correction API·UI
6. seed template의 5개 의미 preflight
7. 전체 테스트·build·DB rollback probe
8. preview 배포와 owner/labeler E2E
9. owner가 `e679`, `d934`를 UI로 보정
10. reference preflight 실행 결과 보고
11. 문서·SOT 갱신
12. **중단 후 사용자 검토**

이번 구현 작업은 12번에서 끝난다. 다음은 별도 승인 대상이다.

13. tutorial draft seed
14. seed preview·owner 검토
15. activation
16. 테스트 labeler 5개 E2E
17. production 배포

## 13. 완료 조건

- 라벨링 화면에 primary action 기본 선택이 없다.
- 라벨러가 저장 실패 원인과 수정 위치를 같은 화면에서 즉시 이해한다.
- absent 영상에서 활동 강도를 입력하거나 정답 비교하지 않는다.
- drinking target `tool`과 근거 없는 hand feeding을 client/server가 모두 차단한다.
- owner correction이 initial GT를 보존하며 append-only revision을 남긴다.
- `e679`, `d934` 보정이 revision 경로로 완료된다.
- 5개 reference 의미 preflight가 전부 통과한다.
- 기존 tutorial 보안·불변·provenance 계약이 유지된다.
- web test, TypeScript, build, Python test, DB rollback probe가 모두 통과한다.
- seed·activation·production 배포는 실행되지 않는다.

## 14. 보류한 후속 과제

- activity intensity의 명시적 `not_applicable / unjudgeable` enum
- 행동 taxonomy 전반의 target compatibility matrix
- 일반 labeler correction 요청·owner 승인 workflow
- revision history 조회 전용 관리자 화면
- 여러 segment에서 같은 action을 반복 입력하는 모델
- VLM 복수 행동·object evidence 출력 계약

이 항목들은 이번 reference 출시를 막지 않으며, 실제 GT 축적 후 별도 스펙으로 판단한다.
