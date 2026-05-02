"""GT 라벨 엔드포인트 (spec §3-6).

- POST /clips/{id}/labels   — 라벨 1건 UPSERT (clip_id, labeled_by) UNIQUE
- GET  /clips/{id}/labels   — clip 의 라벨 목록 (owner=전체, labeler=본인만)
- GET  /labels/queue        — 라벨러 큐 (미라벨 우선, 최신순, seek pagination)

## 왜 여러 prefix 를 한 router 에?
`/clips/{id}/labels` 와 `/labels/queue` 는 prefix 가 다르지만 같은 도메인 (라벨링).
라우터 분리 비용 > 같이 묶는 명료성. APIRouter prefix 비우고 각 데코레이터에 풀패스.

## action / lick_target enum 검증을 Pydantic 에서
spec §4 결정 6: DB 는 TEXT + 앱 레벨 검증. 라벨 클래스가 VLM 진화 따라 바뀔 가능성
(9 raw → 8 → ...) → DB 마이그레이션 부담 없이 enum 갈아끼울 수 있게.

## UPSERT 정책
한 라벨러가 같은 클립에 라벨 다시 달면 update (last-write-wins). spec §2 의
"다중 라벨러 충돌 UI" Out 결정과 일치 — MVP 는 본인 라벨만 본인이 수정.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from supabase import Client

from backend.auth import get_current_user_id
from backend.clip_perms import is_labeler, load_clip_with_perms
from backend.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["labels"])

# /labels/queue 페이지 크기 — clips 와 동일 default/max.
DEFAULT_QUEUE_LIMIT = 50
MAX_QUEUE_LIMIT = 200


# ─────────────────────────────────────────────────────────────────────────
# enum 정의 — spec §2 + §3-3 (camera_clips ALTER 코멘트 참조)
# ─────────────────────────────────────────────────────────────────────────

# 9 raw 클래스 (5 main UI + 4 더보기). spec §2:
#   main: eating_paste / drinking / moving / unknown
#   raw 호환 추가: eating_prey / defecating / shedding / basking / unseen
ActionType = Literal[
    "eating_paste",
    "drinking",
    "moving",
    "unknown",
    "eating_prey",
    "defecating",
    "shedding",
    "basking",
    "unseen",
]

# 6 lick-target. action=eating_paste|drinking 일 때만 의미 있음 (NULL 허용).
# spec §2: "air_lick" 은 (action=eating_paste, lick_target=air) 조합으로 표현.
LickTargetType = Literal["air", "dish", "floor", "wall", "object", "other"]


# ─────────────────────────────────────────────────────────────────────────
# Pydantic 모델
# ─────────────────────────────────────────────────────────────────────────


class LabelCreate(BaseModel):
    """POST 본문. action 필수, lick_target/note/labeled_by 선택.

    labeled_by 가 명시되면 owner 만 다른 라벨러 라벨을 강제 수정 가능 (관리자/테스터 검수용).
    None 이면 현재 user_id 로 fallback (기존 동작 — 자기 라벨만 작성).
    """

    action: ActionType
    lick_target: Optional[LickTargetType] = None
    note: Optional[str] = Field(default=None, max_length=2000)
    labeled_by: Optional[str] = Field(
        default=None,
        description="owner 가 다른 라벨러 라벨을 강제 수정/생성할 때만 명시. None=본인.",
    )


class LabelOut(BaseModel):
    """behavior_labels 한 row. clip 메타는 별도 GET /clips/{id} 로."""

    id: str
    clip_id: str
    labeled_by: str
    action: str
    lick_target: Optional[str] = None
    note: Optional[str] = None
    labeled_at: str

    model_config = ConfigDict(extra="ignore")


# ─────────────────────────────────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────────────────────────────────


@router.post("/clips/{clip_id}/labels", response_model=LabelOut, status_code=201)
def create_label(
    clip_id: str,
    body: LabelCreate,
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> LabelOut:
    """라벨 1건 저장 (UPSERT).

    같은 라벨러가 같은 클립에 다시 라벨 → 기존 row update (UNIQUE clip_id+labeled_by).
    Pydantic 이 action/lick_target enum 자체 검증 → 잘못된 값은 422 자동.
    권한: clip owner OR labelers 멤버.

    labeled_by override (관리자/테스터 검수용):
    - body.labeled_by 가 명시 + 본인이 아닐 때 → clip owner 인지 확인. 아니면 403.
    - 명시 없으면 본인 user_id 로 (기존 동작).
    """
    # 권한 검증 (외부인 → 404). clip 존재도 함께 확인.
    clip = load_clip_with_perms(clip_id, user_id, sb)

    target_labeled_by = body.labeled_by or user_id
    if target_labeled_by != user_id and clip.get("user_id") != user_id:
        # 다른 라벨러 라벨을 수정하려면 clip owner 여야 함. labeler 멤버라도 불가.
        raise HTTPException(
            status_code=403,
            detail="only clip owner can write labels for other users",
        )

    payload = {
        "clip_id": clip_id,
        "labeled_by": target_labeled_by,
        "action": body.action,
        "lick_target": body.lick_target,
        "note": body.note,
    }

    try:
        resp = (
            sb.table("behavior_labels")
            .upsert(payload, on_conflict="clip_id,labeled_by")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("behavior_labels upsert failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=502, detail="upsert returned empty")
    return LabelOut.model_validate(rows[0])


@router.get("/clips/{clip_id}/labels", response_model=list[LabelOut])
def list_labels(
    clip_id: str,
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> list[LabelOut]:
    """clip 의 라벨 목록.

    - clip owner: 모든 라벨러 결과 조회 (GT 합의 검토용).
    - labeler (owner 아님): 본인 라벨만 (다른 라벨러 결과 비공개 — 영향 회피).
    - 외부인: 404 (load_clip_with_perms 에서 차단).
    """
    clip = load_clip_with_perms(clip_id, user_id, sb)

    q = (
        sb.table("behavior_labels")
        .select("*")
        .eq("clip_id", clip_id)
        .order("labeled_at", desc=True)
    )

    # owner 는 모든 라벨러, labeler 는 본인 것만.
    if clip.get("user_id") != user_id:
        q = q.eq("labeled_by", user_id)

    try:
        resp = q.execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("behavior_labels list failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")

    return [LabelOut.model_validate(r) for r in (resp.data or [])]


@router.get("/labels/queue")
def list_label_queue(
    limit: int = Query(DEFAULT_QUEUE_LIMIT, ge=1, le=MAX_QUEUE_LIMIT),
    cursor: Optional[str] = Query(
        None, description="이전 응답의 next_cursor (started_at ISO8601)"
    ),
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """라벨러 큐 — 본인이 아직 라벨 안 한 클립을 최신순으로.

    스코프:
    - labelers 멤버: 모든 user_id 의 클립 (라벨러 권한 = 전 클립 접근)
    - 비-라벨러 (일반 owner): 본인 user_id 클립만

    seek pagination: 응답 next_cursor 를 다음 호출 cursor 에 그대로 넘기면 됨.
    """
    # 1. 본인이 이미 라벨한 clip_id 모음 — 큐에서 제외.
    try:
        my_labels_resp = (
            sb.table("behavior_labels")
            .select("clip_id")
            .eq("labeled_by", user_id)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("behavior_labels self list failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")

    my_clip_ids = [r["clip_id"] for r in (my_labels_resp.data or [])]

    # 2. clip 쿼리 — 라벨러면 전체, 아니면 본인 것만.
    user_is_labeler = is_labeler(user_id, sb)

    q = (
        sb.table("camera_clips")
        .select("*")
        .order("started_at", desc=True)
        .limit(limit + 1)  # has_more 판단용 1개 더
    )
    if not user_is_labeler:
        q = q.eq("user_id", user_id)
    if my_clip_ids:
        # postgrest "not.in" — 본인 라벨한 clip 제외
        q = q.not_.in_("id", my_clip_ids)
    if cursor:
        q = q.lt("started_at", cursor)

    try:
        resp = q.execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("queue clip query failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")

    rows = resp.data or []
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1]["started_at"] if has_more and items else None

    return {
        "items": items,
        "count": len(items),
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
