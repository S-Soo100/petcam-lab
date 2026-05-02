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

## QA mirror 훅 (2026-04-22)
`clip_mirrors` 테이블에 `source_camera_id` 가 등록돼 있으면 원본 INSERT 성공 후
같은 클립을 `mirror_user_id` / `mirror_camera_id` 로 복사 INSERT. 정식 공유 기능
아니며 QA 테스터 계정이 동일 영상 재생 가능하도록 하는 임시 인프라. 미러 실패는
best-effort — 원본은 이미 성공했으니 경고만 찍고 넘어감.
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
    4. 원본 성공 시 `clip_mirrors` 매핑 존재하면 복사 INSERT (best-effort)

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
            return

        # 원본 성공 후 미러 시도. 실패해도 원본은 이미 저장됨.
        _mirror_clip(client, clip_fields)

    return record


def _mirror_clip(client: Client, clip_fields: dict[str, Any]) -> None:
    """`clip_mirrors` 매핑이 있으면 같은 클립을 미러 유저/카메라로 복사 INSERT.

    payload 의 `camera_id` 로 `clip_mirrors.source_camera_id` 조회. 실패 시 warning
    만 남기고 원본 INSERT 는 유지 (best-effort). pending queue 에는 넣지 않음 —
    미러는 QA 편의 기능이지 데이터 정합성 영역이 아님.
    """
    source_camera_id = clip_fields.get("camera_id")
    if not source_camera_id:
        return

    try:
        mirrors_resp = (
            client.table("clip_mirrors")
            .select("mirror_camera_id, mirror_user_id")
            .eq("source_camera_id", source_camera_id)
            .execute()
        )
    except Exception as exc:
        logger.warning("clip_mirrors lookup failed (src=%s): %s", source_camera_id, exc)
        return

    mirrors = mirrors_resp.data or []
    if not mirrors:
        return

    for m in mirrors:
        mirror_camera_id = m["mirror_camera_id"]
        mirror_user_id = m["mirror_user_id"]
        try:
            cam_resp = (
                client.table("cameras")
                .select("pet_id")
                .eq("id", mirror_camera_id)
                .single()
                .execute()
            )
            mirror_pet_id = (cam_resp.data or {}).get("pet_id")

            # clip_fields 에 camera_id 가 이미 들어있으므로 덮어쓰기 순서 중요.
            # `id` 는 원본 row 의 UUID — mirror 에 그대로 쓰면 unique violation.
            # encode_upload_worker 가 spec §4 결정 7 에 따라 pre-generate 한 값이라
            # 미러에선 빼고 DB 의 `gen_random_uuid()` 디폴트로 새 id 받게 한다.
            # r2_key / thumbnail_r2_key 는 spec 명시: "mirror 는 같은 R2 key 공유 — 별도
            # 업로드 안 함" 이라 그대로 둠.
            mirror_row = {
                k: v for k, v in clip_fields.items() if k != "id"
            }
            mirror_row.update(
                {
                    "camera_id": mirror_camera_id,
                    "user_id": mirror_user_id,
                    "pet_id": mirror_pet_id,
                }
            )
            client.table("camera_clips").insert(mirror_row).execute()
            logger.info(
                "clip mirrored: src_cam=%s → user=%s cam=%s",
                source_camera_id,
                mirror_user_id,
                mirror_camera_id,
            )
        except Exception as exc:
            logger.warning(
                "clip mirror INSERT failed (src=%s → dst=%s): %s",
                source_camera_id,
                mirror_camera_id,
                exc,
            )


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
        except Exception as exc:
            logger.warning("flush retry failed (will remain in queue): %s", exc)
            return False
        # 재시도 성공도 미러 대상. 미러 실패는 best-effort 로 warning 만.
        # (flush path 에 훅이 없으면 재시작 타이밍에 원본만 들어가 gap 이 생김)
        _mirror_clip(client, row)
        return True

    return insert_one
