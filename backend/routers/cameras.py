"""
`/cameras` 엔드포인트 6종 (Stage D2).

- POST   /cameras/test-connection  — RTSP 핸드쉐이크 검증 (등록 전 호출 가능)
- POST   /cameras                  — 등록 (평문 비번 → 서버 암호화 + 자동 probe)
- GET    /cameras                  — 목록 (본인 것만)
- GET    /cameras/{id}             — 단건
- PATCH  /cameras/{id}             — 부분 수정 (비번 변경 시 재암호화)
- DELETE /cameras/{id}             — 삭제

## 왜 service_role 로 INSERT?
`cameras` 테이블은 RLS INSERT 정책을 **안 만들었음** → anon/authenticated 직접 insert 불가.
백엔드가 test-connection → encrypt → insert 흐름을 강제.

## 왜 PATCH 는 exclude_unset?
클라가 안 보낸 필드 = "변경 없음", null 명시 = "NULL 로 변경" 을 구분.
`model_dump(exclude_unset=True)` 로 들어온 키만 UPDATE 쿼리에 실음.
TS/Prisma 의 `update({data})` 에서 undefined 필드 무시되는 것과 같음.

## 왜 password 응답 배제?
`CameraOut` 스키마에 `password_encrypted` 필드 **자체가 없음** → 자동 배제.
`model_validate(row)` 는 `extra="ignore"` 로 여분 키 무시.

## 블로킹 cv2 주의
`test-connection` / `POST` 는 cv2 3초 타임아웃 → 라우터 **동기 def** (donts/python#4).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from supabase import Client

from backend.auth import get_current_user_id
from backend.crypto import encrypt_password
from backend.rtsp_probe import ProbeResult, probe_rtsp
from backend.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cameras", tags=["cameras"])

# Postgres 23505 = unique_violation. (user_id, host, port, path) 중복 시 발생.
_PG_UNIQUE_VIOLATION = "23505"


# ─────────────────────────────────────────────────────────────────────────
# Pydantic 모델
# ─────────────────────────────────────────────────────────────────────────


class _CameraFieldsBase(BaseModel):
    """공통 필드 — Create 와 Out 이 상속. Update 는 전부 Optional 이라 별도 정의."""

    display_name: str = Field(..., min_length=1)
    host: str = Field(..., min_length=1)
    port: int = Field(default=554, ge=1, le=65535)
    path: str = Field(default="stream1", min_length=1)
    username: str = Field(..., min_length=1)
    pet_id: Optional[UUID] = None


class CameraCreate(_CameraFieldsBase):
    """등록 요청 — 비번 평문 입력."""

    password: str = Field(..., min_length=1)


class CameraUpdate(BaseModel):
    """PATCH — 모든 필드 Optional. exclude_unset 으로 들어온 것만 수정."""

    display_name: Optional[str] = Field(default=None, min_length=1)
    host: Optional[str] = Field(default=None, min_length=1)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    path: Optional[str] = Field(default=None, min_length=1)
    username: Optional[str] = Field(default=None, min_length=1)
    password: Optional[str] = Field(default=None, min_length=1)  # 들어오면 재암호화
    pet_id: Optional[UUID] = None
    is_active: Optional[bool] = None


class CameraOut(_CameraFieldsBase):
    """응답 — password_encrypted 필드 **자체 없음** → 자동 배제."""

    id: UUID
    user_id: UUID
    is_active: bool
    last_connected_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # DB row 의 여분 필드 (password_encrypted) 무시
    model_config = ConfigDict(extra="ignore")


class TestConnectionRequest(BaseModel):
    host: str = Field(..., min_length=1)
    port: int = Field(default=554, ge=1, le=65535)
    path: str = Field(default="stream1", min_length=1)
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TestConnectionResponse(BaseModel):
    success: bool
    detail: str
    frame_captured: bool
    elapsed_ms: int
    frame_size: Optional[tuple[int, int]] = None


# ─────────────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────────────


def _probe_to_response(result: ProbeResult) -> TestConnectionResponse:
    return TestConnectionResponse(
        success=result.success,
        detail=result.detail,
        frame_captured=result.frame_captured,
        elapsed_ms=result.elapsed_ms,
        frame_size=result.frame_size,
    )


def _is_unique_violation(exc: Exception) -> bool:
    """supabase-py 가 PostgrestAPIError 를 던지는데 코드를 문자열 검사로 확인."""
    msg = str(exc).lower()
    return _PG_UNIQUE_VIOLATION in msg or "duplicate" in msg or "unique" in msg


# ─────────────────────────────────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────────────────────────────────


@router.post("/test-connection", response_model=TestConnectionResponse)
def test_connection(
    body: TestConnectionRequest,
    user_id: str = Depends(get_current_user_id),  # 인증만 — 로깅·rate-limit 확장 대비
) -> TestConnectionResponse:
    """
    등록 전 RTSP 핸드쉐이크 검증. 인증/타임아웃 실패도 200 응답 + success=False.
    500 은 진짜 서버 크래시만.
    """
    result = probe_rtsp(
        host=body.host,
        port=body.port,
        path=body.path,
        username=body.username,
        password=body.password,
    )
    return _probe_to_response(result)


@router.post("", response_model=CameraOut, status_code=201)
def create_camera(
    body: CameraCreate,
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> CameraOut:
    """
    카메라 등록. **자동 probe** — 실패 시 400, 등록 거부 (스펙 결정: skip_probe 옵션 없음).
    유니크 `(user_id, host, port, path)` 충돌 → 409.
    """
    probe_result = probe_rtsp(
        host=body.host,
        port=body.port,
        path=body.path,
        username=body.username,
        password=body.password,
    )
    if not probe_result.success:
        raise HTTPException(
            status_code=400,
            detail=f"RTSP 연결 실패: {probe_result.detail}",
        )

    row = {
        "user_id": user_id,
        "pet_id": str(body.pet_id) if body.pet_id else None,
        "display_name": body.display_name,
        "host": body.host,
        "port": body.port,
        "path": body.path,
        "username": body.username,
        "password_encrypted": encrypt_password(body.password),
    }

    try:
        resp = sb.table("cameras").insert(row).execute()
    except Exception as exc:  # noqa: BLE001 — supabase-py 예외 타입 넓음
        if _is_unique_violation(exc):
            raise HTTPException(
                status_code=409,
                detail="이미 등록된 RTSP (host+port+path 동일)",
            )
        logger.exception("cameras insert failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=502, detail="insert returned empty")
    return CameraOut.model_validate(rows[0])


@router.get("", response_model=list[CameraOut])
def list_cameras(
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> list[CameraOut]:
    """본인 카메라 목록. 최근 생성 순."""
    try:
        resp = (
            sb.table("cameras")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("cameras list failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")

    rows = resp.data or []
    return [CameraOut.model_validate(r) for r in rows]


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(
    camera_id: str,
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> CameraOut:
    """단건 조회. 다른 유저 것 or 미존재 → 404."""
    try:
        resp = (
            sb.table("cameras")
            .select("*")
            .eq("id", camera_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("cameras single failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"camera '{camera_id}' not found")
    return CameraOut.model_validate(rows[0])


@router.patch("/{camera_id}", response_model=CameraOut)
def update_camera(
    camera_id: str,
    body: CameraUpdate,
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> CameraOut:
    """
    부분 수정. 들어온 필드만 UPDATE. password 가 들어오면 재암호화.
    """
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="수정할 필드가 없음")

    if "password" in updates:
        plain = updates.pop("password")
        updates["password_encrypted"] = encrypt_password(plain)

    # UUID → str (Supabase client 직렬화)
    if "pet_id" in updates and updates["pet_id"] is not None:
        updates["pet_id"] = str(updates["pet_id"])

    try:
        resp = (
            sb.table("cameras")
            .update(updates)
            .eq("id", camera_id)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        if _is_unique_violation(exc):
            raise HTTPException(
                status_code=409,
                detail="변경 결과가 기존 카메라와 중복",
            )
        logger.exception("cameras update failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"camera '{camera_id}' not found")
    return CameraOut.model_validate(rows[0])


@router.delete("/{camera_id}")
def delete_camera(
    camera_id: str,
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """삭제. 미존재·타 유저 → 404. 성공 시 `{id, deleted: true}`."""
    try:
        resp = (
            sb.table("cameras")
            .delete()
            .eq("id", camera_id)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("cameras delete failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")

    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"camera '{camera_id}' not found")
    return {"id": camera_id, "deleted": True}
