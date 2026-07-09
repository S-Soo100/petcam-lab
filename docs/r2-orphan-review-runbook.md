# R2 Orphan Review Runbook

> 2026-07-10 기준. R2에 있는 mp4와 Supabase `camera_clips.r2_key`를 대조해서,
> DB에 없는 영상을 안전하게 분류하는 절차야. 이 절차는 기본적으로
> **DB/R2 쓰기 없이 읽기 전용 dry-run**으로만 돈다.

## 목적

- R2에 남아 있지만 `camera_clips`에 등록되지 않은 mp4를 찾는다.
- 자동 백필 가능한 canonical clip과 수동 검토가 필요한 legacy clip을 분리한다.
- 바로 `camera_clips`에 넣지 않고, 증거 CSV/JSON/썸네일을 만든 뒤 사람이 최종 결정한다.

## 현재 결과

- R2 mp4 총 `175`개
- Supabase `camera_clips.r2_key`와 매칭된 영상 `171`개
- orphan `4`개
- orphan 4개 모두 `manual_review_clip`
- 리뷰팩 판정은 전부 `needs_human_label`
- DB writes `0`, R2 writes `0`

남은 4개는 아래 legacy path 형태야.

```text
clips/2026/06/17/p4cam-79b5d844/{uuid}.mp4
```

이 경로는 canonical path인 아래 형태가 아니기 때문에 자동 import 금지야.

```text
clips/{camera_id}/{YYYY-MM-DD}/{HHMMSS}_{motion|idle}_{clip_id}.mp4
```

## 명령

인벤토리 dry-run:

```bash
uv run python scripts/r2_orphan_inventory.py \
  --out-dir reports/r2-orphan-inventory-20260710
```

수동 리뷰팩 생성:

```bash
uv run python scripts/r2_orphan_review.py \
  --orphans reports/r2-orphan-inventory-20260710/orphans.jsonl \
  --out-dir reports/r2-orphan-review-20260710
```

검증:

```bash
uv run pytest tests/test_r2_orphan_inventory.py tests/test_r2_orphan_review.py -q
```

## 산출물

- `reports/r2-orphan-inventory-20260710/REPORT.md`
- `reports/r2-orphan-inventory-20260710/summary.json`
- `reports/r2-orphan-inventory-20260710/orphans.jsonl`
- `reports/r2-orphan-review-20260710/REVIEW.md`
- `reports/r2-orphan-review-20260710/review.csv`
- `reports/r2-orphan-review-20260710/review.json`

리뷰팩의 `clips/`, `thumbnails/`는 로컬 확인용 산출물이므로 git에는 넣지 않는다.
원본은 R2에 있고, 필요하면 위 명령으로 다시 생성한다.

## 판정 기준

- `known_camera_clip`: 이미 `camera_clips.r2_key`에 존재한다.
- `likely_missing_camera_clip`: canonical path인데 DB에 없다. 다음 단계에서 staging 후보.
- `manual_review_clip`: legacy path라 camera/user/start time 근거가 약하다. 자동 import 금지.
- `experiment_artifact`: 테스트/검증 산출물로 보인다. import 금지.
- `unknown_pattern`: 규칙 미정. import 금지.

## 다음 결정

현재 orphan 4개는 실제 영상처럼 열리지만, `camera_id/user_id/started_at/has_motion`
근거가 부족해. 다음 단계는 앱/소유자 맥락으로 4개 썸네일과 영상을 보고:

- 실제 유저 영상이면 staging table 또는 별도 manual-import 후보로 이동
- 실험/테스트 영상이면 ignore
- 중복/불필요 영상이면 delete candidate로 표시

삭제나 `camera_clips` 백필은 별도 승인 전까지 하지 않는다.
