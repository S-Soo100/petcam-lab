"""
`camera_clips` INSERT 오케스트레이션.

캡처 워커는 "영상 관련 필드" 만 준비해서 recorder 에 넘기고, recorder 가
user_id / pet_id 주입 + Supabase INSERT + 실패 시 큐에 enqueue 를 담당.

## 왜 분리했나?
- capture.py 는 영상 처리 루프 전담. Supabase / 큐 등 I/O 의존성이 섞이면
  단위 테스트 어려움.
- recorder 는 "비즈니스 로직" (user_id 주입 규칙, 재시도 정책).
  → 바뀔 가능성 높으니 독립 모듈.

## Node 비유
NestJS 의 service 레이어. capture 는 controller, Supabase client 는 repository.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Optional

from supabase import Client

from backend.pending_inserts import PendingInsertQueue

logger = logging.getLogger(__name__)


def make_clip_recorder(
    client: Client,
    queue: PendingInsertQueue,
    dev_user_id: str,
    dev_pet_id: Optional[str],
) -> Callable[[dict[str, Any]], None]:
    """
    CaptureWorker 에 주입할 recorder 함수 생성.

    반환된 함수는 영상 필드 dict 를 받아:
    1. user_id / pet_id 채워넣음
    2. Supabase INSERT 시도
    3. 실패 시 `queue` 에 enqueue

    Args:
        client: Supabase 싱글톤 클라이언트 (service_role)
        queue: 재시도 큐
        dev_user_id: auth.users.id (Stage C 하드코딩, Stage D 에서 JWT 교체)
        dev_pet_id: pets.id 또는 None
    """
    # 빈 문자열은 None 취급 (.env 에 DEV_PET_ID= 로 비워둔 경우)
    pet_id = dev_pet_id or None

    def record(clip_fields: dict[str, Any]) -> None:
        row: dict[str, Any] = {
            **clip_fields,
            "user_id": dev_user_id,
            "pet_id": pet_id,
        }
        try:
            client.table("camera_clips").insert(row).execute()
        except Exception as exc:
            # 네트워크·키·스키마 문제 모두 여기로 떨어짐. 큐에 넣고 계속.
            logger.warning("camera_clips INSERT failed, enqueue: %s", exc)
            queue.enqueue(row)

    return record


def make_flush_insert_fn(
    client: Client,
) -> Callable[[dict[str, Any]], bool]:
    """
    `PendingInsertQueue.flush(insert_fn=...)` 에 넘길 재시도 함수 생성.

    Returns:
        row -> bool. True 면 큐에서 제거, False 면 큐에 남김.
    """

    def insert_one(row: dict[str, Any]) -> bool:
        try:
            client.table("camera_clips").insert(row).execute()
            return True
        except Exception as exc:
            logger.warning("flush retry failed (will remain in queue): %s", exc)
            return False

    return insert_one
