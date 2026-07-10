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

## 현재 DB 카운트

- `router_review_items`: `72`
- `router_review_labels`: `0`
