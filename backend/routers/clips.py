"""
`/clips` 엔드포인트 3종 (Stage C).

- GET /clips              — 목록 + 필터 (camera_id, has_motion, from, to, limit, cursor)
- GET /clips/{id}         — 단건 메타
- GET /clips/{id}/file    — mp4 스트리밍 (HTTP Range 지원)

## 왜 Depends 로 user_id 를 받나?
`get_current_user_id` 가 AUTH_MODE 에 따라 Dev(DEV_USER_ID 반환) / Prod(JWT 검증) 로
자동 분기. 라우트는 Depends 만 선언하면 두 모드 모두 지원. Stage D1 에서 `get_dev_user_id`
→ `get_current_user_id` 로 교체 완료.

## 왜 seek pagination 인가?
offset 은 페이지 깊어질수록 느림 (Postgres 가 앞쪽을 버리는데 비용 증가).
"started_at < cursor" 로 커서를 주면 항상 인덱스 한 번의 range scan.

## Range 스트리밍
Flutter `video_player` / 브라우저 `<video>` 는 시크할 때 `Range: bytes=X-` 헤더.
기본 `StreamingResponse(open(path))` 는 Range 미지원 → 직접 206 응답 구성.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from supabase import Client

from backend.auth import get_current_user_id
from backend.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clips", tags=["clips"])

# 파일 스트리밍 청크 크기.
# 작으면 첫 바이트 응답 빠름 (시크 응답성), 크면 네트워크 효율.
# 비디오 스트리밍 표준 64KB~1MB. 256KB 는 무난한 중간값.
STREAM_CHUNK_SIZE = 1024 * 256

# Range 헤더 포맷: "bytes=START-END" (END 생략 가능)
_RANGE_RE = re.compile(r"^\s*bytes\s*=\s*(\d+)-(\d*)\s*$")

# /clips 목록 기본/최대 페이지 크기
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@router.get("")
def list_clips(
    camera_id: Optional[str] = Query(None, description="특정 카메라만"),
    has_motion: Optional[bool] = Query(None, description="움직임 있는 것만 true"),
    from_: Optional[str] = Query(None, alias="from", description="ISO8601, 이후"),
    to: Optional[str] = Query(None, description="ISO8601, 이전"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: Optional[str] = Query(
        None, description="이전 응답의 next_cursor (started_at ISO8601)"
    ),
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """
    camera_clips 목록 (seek pagination).

    service_role 은 RLS 바이패스라서 `user_id` 필터를 코드에서 명시적으로 건다.
    Stage D 에서 anon + JWT 로 전환되면 이 필터는 RLS 가 자동 적용.
    """
    q = (
        sb.table("camera_clips")
        .select("*")
        .eq("user_id", user_id)
        .order("started_at", desc=True)
        .limit(limit + 1)  # hasMore 판단용 1개 더 조회
    )
    if camera_id:
        q = q.eq("camera_id", camera_id)
    if has_motion is not None:
        q = q.eq("has_motion", has_motion)
    if from_:
        q = q.gte("started_at", from_)
    if to:
        q = q.lte("started_at", to)
    if cursor:
        q = q.lt("started_at", cursor)

    try:
        resp = q.execute()
    except Exception as exc:  # noqa: BLE001 — Supabase 는 다양한 예외 던짐
        logger.exception("camera_clips list query failed")
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


@router.get("/{clip_id}")
def get_clip(
    clip_id: str,
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """단건 메타 조회."""
    try:
        resp = (
            sb.table("camera_clips")
            .select("*")
            .eq("id", clip_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("camera_clips single query failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"clip '{clip_id}' not found")
    return rows[0]


@router.get("/{clip_id}/file")
def get_clip_file(
    clip_id: str,
    request: Request,
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> StreamingResponse:
    """
    mp4 스트리밍. HTTP Range 헤더 있으면 206 Partial Content 로 응답.

    Flutter `video_player` 가 시크할 때 `Range: bytes=<start>-` 헤더를 보냄.
    """
    try:
        resp = (
            sb.table("camera_clips")
            .select("file_path")
            .eq("id", clip_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("camera_clips file lookup failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"clip '{clip_id}' not found")

    file_path = Path(rows[0]["file_path"])
    if not file_path.exists():
        # DB 행은 있는데 파일이 사라진 경우 (수동 삭제, 디스크 오류 등)
        raise HTTPException(
            status_code=410,  # 410 Gone — 리소스가 영구 사라짐
            detail=f"file missing on disk: {file_path}",
        )

    file_size = file_path.stat().st_size
    range_header = request.headers.get("range")

    if not range_header:
        # 전체 파일 전송 (Range 없으면 200)
        return StreamingResponse(
            _iter_file(file_path, 0, file_size),
            media_type="video/mp4",
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
            },
        )

    # Range 파싱 → 206 Partial Content
    match = _RANGE_RE.match(range_header)
    if not match:
        raise HTTPException(
            status_code=416,
            detail=f"malformed Range header: {range_header}",
        )

    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else file_size - 1

    if start >= file_size or end >= file_size or start > end:
        raise HTTPException(
            status_code=416,
            detail=f"range out of bounds (file size={file_size})",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    content_length = end - start + 1
    return StreamingResponse(
        _iter_file(file_path, start, end + 1),
        status_code=206,
        media_type="video/mp4",
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
        },
    )


def _iter_file(path: Path, start: int, end_exclusive: int) -> Iterator[bytes]:
    """
    [start, end_exclusive) 구간을 청크 단위로 yield.

    제너레이터라 FastAPI 가 chunked transfer-encoding 으로 전송.
    파일 전체를 메모리에 안 올림 → GB 짜리도 OK (현재는 분당 수 MB 라 오버스펙).
    """
    with path.open("rb") as f:
        f.seek(start)
        remaining = end_exclusive - start
        while remaining > 0:
            chunk_size = min(STREAM_CHUNK_SIZE, remaining)
            chunk = f.read(chunk_size)
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
