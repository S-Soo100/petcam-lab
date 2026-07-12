# Router Review Web UI

## 상태

- 코드 구현: 완료
- Supabase 테이블 적용: 완료
- batch seed: 완료 (`router_review_items` 72건)

## 적용 순서

1. Supabase SQL Editor에서 실행 완료:

```sql
-- migrations/2026-07-10_router_review_tables.sql
```

2. batch seed 실행 완료:

```bash
uv run python scripts/seed_router_review_batch.py
```

3. 로컬 확인:

```bash
cd web
npx tsc --noEmit
npm run dev -- -p 3001
```

4. 브라우저:

```text
http://localhost:3001/labeling/router-review
```

## 구현된 화면

- `/labeling/router-review`
  - batch 선택
  - group/status 필터
  - 진행률
  - review item 카드

- `/labeling/router-review/{clipId}?batch_id=router-eval-v1-20260710`
  - 영상 재생
  - router snapshot
  - 게코 보임 / 실제 행동 / 라우터 판단 입력
  - 저장 후 다음 미검수 item 이동

## 저장 위치

- queue snapshot: `router_review_items`
- 사람 검수 결과: `router_review_labels`
- 행동 GT: 저장하지 않음

## 리뷰 기준

- `게코 보임 = 안 보임`이면 `실제 행동 = unseen`.
- 게코가 숨어서 몸 일부/은신처만 보이고 행동 판단이 안 되면 `hidden`.
- 사람 손, 그림자, 카메라 세팅, 외부 물체 변화로 캡쳐된 영상이면 `human_noise`.
- `검사 필요 여부`는 "이 영상을 VLM/사람이 봐야 하나?"를 본다.
  - `cloud_now`: 지금 cloud VLM 호출 후보.
  - `cloud_later`: 급하지 않아 나중에 묶어서 볼 후보.
  - `activity_only`: VLM 없이 활동량만 남길 후보.
  - `review_candidate`: 자동 판단 보류 후보.
- 쉽게 말하면:
  - `검사`: VLM/사람이 봐야 하는 영상. 먹이, 음수/핥기, 이상 움직임, 중요한 상태 변화가 보이면 고른다.
  - `비검사`: VLM/사람이 지금 안 봐도 되는 영상. 게코 안 보임, 사람/그림자 노이즈, 의미 없는 정지/움직임이면 고른다.
  - `애매함`: 검사해야 할지 모르겠는 영상. 가림, 너무 작은 움직임, 다음 영상 필요, 노이즈와 행동 구분 불가일 때 고른다.
- 중요하지 않은 영상을 `cloud_now`로 보낸 건 비용 낭비지만 "놓친 것"은 아니므로 보통 `비검사` 또는 메모로 표시한다.
- 내부 저장값은 기존 분석 코드 호환 때문에 `검사 = manual_router_ok no`, `비검사 = manual_router_ok yes`, `애매함 = unclear`로 남긴다.

## 현재 DB 카운트

- `router_review_items`: `72`
- `router_review_labels`: `0`
