"""clip 접근 권한 헬퍼 — `clips`, `labels` 라우터 공통.

spec §4 결정 4 권한 매트릭스:
- owner: clip.user_id == 본인
- labeler: `labelers` 테이블 멤버 (모든 클립 영상/라벨 폼 접근 가능)
- 외부인: 둘 다 아님 → 404 (존재 leak 방지)

## 왜 별도 모듈?
clips 라우터의 file/thumbnail + labels 라우터의 POST/GET label + queue 까지
4+ 호출 지점이 같은 권한 분기를 공유. CLAUDE.md "3번 반복 시 추상화" 룰 충족.

## 왜 service_role 직접 SELECT?
`labelers` 는 RLS 0건 (service_role 전용). 백엔드가 user JWT 를 받아 검증한 뒤
service_role 키로 멤버십을 확인하는 패턴 — RLS 가 main 이 아니라 백엔드 검사가
main 이라는 spec §3-3 RLS 모순 정리(C) 와 일관.

## 왜 매 호출 SELECT?
MVP 라벨러 ≤ 3명 가정. 라벨러 수가 늘면 lru_cache (TTL 끼워서) 도입 자연스러움.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException
from supabase import Client

logger = logging.getLogger(__name__)


def is_labeler(user_id: str, sb: Client) -> bool:
    """`labelers` 테이블 멤버 여부."""
    try:
        resp = (
            sb.table("labelers")
            .select("user_id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 — supabase 다양한 예외
        logger.exception("labelers lookup failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")
    return bool(resp.data)


def load_clip_with_perms(
    clip_id: str, user_id: str, sb: Client
) -> dict[str, Any]:
    """clip_id 로 row 조회 + owner OR labeler 권한 체크.

    권한 없거나 row 없으면 둘 다 404 — 외부인에게 clip 존재 여부 leak 방지
    (정찰 + ID enumeration 차단).

    `*` SELECT 인 이유: 호출 측마다 필요한 컬럼이 달라 (file/thumbnail/labels),
    단건 lookup 이라 컬럼 추리는 비용이 의미 없음.
    """
    try:
        resp = (
            sb.table("camera_clips")
            .select("*")
            .eq("id", clip_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("camera_clips lookup failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"clip '{clip_id}' not found")

    clip = rows[0]
    # owner 면 labelers 쿼리 스킵 (short-circuit). 외부인은 두 번 다 fail → 404.
    if clip.get("user_id") != user_id and not is_labeler(user_id, sb):
        raise HTTPException(status_code=404, detail=f"clip '{clip_id}' not found")
    return clip
