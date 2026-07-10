# Router Review Dashboard Design

## Goal

기존 라벨링 웹 안에 라우터 검증 전용 메뉴를 추가해, 영상을 보면서 metadata-only router 판단을 사람이 검수하고 별도 테이블에 저장한다.

## Scope

- `/labeling/router-review`: 라우터 리뷰 큐 목록.
- `/labeling/router-review/[clipId]`: 영상 + 라우터 판단 + 검수 입력.
- `router_review_items`: 어떤 샘플셋을 검수하는지 저장.
- `router_review_labels`: 사람이 검수한 결과 저장.
- 1차 batch는 `router-eval-v1-20260710` 72개 고정 샘플.

## Non-Goals

- 행동 GT를 `behavior_labels`에 저장하지 않는다.
- threshold 자동 재계산은 하지 않는다.
- VLM/LLM 호출은 하지 않는다.
- `activity_only` 자동 skip 승격 판단은 하지 않는다.

## Data Model

`router_review_items`는 리뷰 대상 큐다. `batch_id`, `clip_id`, `sample_group`, router decision snapshot, motion feature snapshot을 보관한다.

`router_review_labels`는 사람 검수 결과다. `review_item_id`, `reviewed_by`, `manual_visible_gecko`, `manual_action_gt`, `manual_router_ok`, `manual_notes`를 보관한다.

둘을 분리하는 이유는 샘플셋 재현성 때문이다. 나중에 같은 batch를 다시 평가할 때 "어떤 clip을 어떤 router snapshot으로 뽑았는지"와 "사람이 어떻게 판정했는지"가 섞이지 않는다.

## UX

라벨링 웹 헤더에 `라우터 리뷰` 탭을 추가한다. 화면 상단에는 "행동 GT 저장 아님 / 라우터 판단 검증용" 문구를 고정 표시한다.

목록 화면은 batch, sample group, status 필터와 진행률을 보여준다. 카드는 route, reason, reliability, 주요 motion 값, started_at을 보여준다.

단건 화면은 기존 clip 영상 로딩 패턴을 재사용한다. 영상 아래에 라우터 판단 패널과 검수 입력 패널을 배치한다. 저장 후 같은 batch의 다음 미검수 item으로 이동한다.

## API

Next.js API route를 사용한다. 기존 라벨링 웹 owner 흐름처럼 Vercel API route가 Supabase service role로 직접 접근하고, Bearer token은 `verifyBearer`로 검증한다.

- `GET /api/router-review/batches`
- `GET /api/router-review/items`
- `GET /api/router-review/items/[clipId]`
- `POST /api/router-review/items/[clipId]/label`

## Safety

- `behavior_labels`와 분리한다.
- 모든 write는 `router_review_labels`에만 한다.
- `router_review_items`는 seed script로 upsert한다.
- 프론트는 라우터 리뷰 목적을 명시해 행동 라벨링과 혼동을 줄인다.
