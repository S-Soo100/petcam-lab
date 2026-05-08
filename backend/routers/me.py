"""`/me` 엔드포인트 — 인증된 본인에 대한 query.

clips/labels/cameras 어디에도 안 맞는 본인 정보 endpoint 모음. 첫 entry 는
`/me/is_labeler` — Flutter 가 라벨링 웹 deep link 노출 여부 결정용.

## 왜 별도 라우터?
input 이 user_id 자체 (path/body 없음). clips 라우터에 끼우면 prefix `/clips`
와 어긋나고, labels 라우터에 끼우면 라벨 개념 외 본인 메타가 끼어들어 도메인
경계 흐려짐. `/me` prefix 가 표준 (GitHub API, Spotify Web API 동일 패턴).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from supabase import Client

from backend.auth import get_current_user_id
from backend.clip_perms import is_labeler
from backend.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/is_labeler")
def get_is_labeler(
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """본인이 `labelers` 테이블 멤버인지.

    Flutter 앱이 라벨링 웹 deep link (`https://label.tera-ai.uk/labeling/{clipId}`)
    를 보여줄지 결정. true 인 owner-labeler 만 chip 옆에 "검수" 버튼 노출.

    응답: `{"is_labeler": bool}`.
    """
    return {"is_labeler": is_labeler(user_id, sb)}
