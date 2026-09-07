"""
`/highlights` — 앱용 하이라이트 피드 (자동 1차 판정 + 사람 확정).

- GET /highlights        — 사용자 카메라의 "현재 하이라이트 = 예" 영상, 최신순 keyset 페이지
- GET /highlights/rule   — 현재 활성 하이라이트 규칙 `{version, params, activated_at}`

## 왜 라벨링 목록 RPC(`fn_list_labeling_v4_clips`)를 재사용하나?
"현재 하이라이트 = 사람 확정이 있으면 그 값, 없으면 규칙 1차 판정" 이라는 정의가
DB 함수 한 곳에만 있어야 라벨링 웹과 앱이 다른 답을 내지 않는다. 앱 전용 RPC 를
따로 만들면 정의가 두 벌이 돼 drift 가 생긴다. 그래서 `p_highlight_state='yes'` 로
같은 함수를 호출하고, 응답에서 앱에 필요 없는 리뷰어 정보만 걷어낸다.

## 왜 `since` 를 서버(RPC)가 아니라 여기서 적용하나?
RPC 에 since 파라미터가 없다. 대신 결과가 `started_at DESC, id DESC` keyset 순서라
"since 보다 오래된 행"을 처음 만나는 순간 그 뒤는 전부 since 이전임이 보장된다.
→ 그 자리에서 멈추면 되므로 추가 스캔 없이 클라이언트측 컷이 정확하다.
(Node 비유: 정렬된 스트림을 `takeWhile(row => row.started_at >= since)` 로 자르는 것.)

## GME 계약 해석과 fallback
규칙 1차 판정은 "어느 GME run 을 현재값으로 볼지"(engine_schema_version /
algorithm_version / detector_identity) 가 필요하다. 라벨링 웹은 이 값을 env 로 받는다.
여기서도 `GME_ACTIVE_ENGINE_SCHEMA_VERSION`(기본 `gme-shadow-v1`) ·
`GME_ACTIVE_ALGORITHM_VERSION` · `GME_ACTIVE_DETECTOR_IDENTITY` 를 읽되,
뒤의 둘 중 하나라도 비어 있으면 **가장 최근 `gme_runs`(status='ok') 행의 계약**으로
대체하고 경고를 한 번만 남긴다. fly secrets 갱신이 라벨링 웹(Vercel) 보다 늦어도
앱 피드가 죽지 않게 하기 위한 안전망이지, 정상 운영 경로가 아니다 — 운영은 env 를
명시하는 것이 원칙(과거 run 이 현재값처럼 보이는 위험은 라벨링 웹 ENV.md 참고).
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client

from backend.auth import get_current_user_id
from backend.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/highlights", tags=["highlights"])

DEFAULT_LIMIT = 50
MAX_LIMIT = 100

# RPC 한 번에 가져오는 행 수. fn_list_labeling_v4_clips 의 p_limit 상한이 101.
# 이 값보다 적게 돌아오면 데이터 끝(함수는 chunk 가 짧을 때만 조기 종료).
RPC_PAGE_SIZE = 101

DEFAULT_ENGINE_SCHEMA_VERSION = "gme-shadow-v1"

# PostgREST 가 statement timeout 을 이 SQLSTATE 로 전달. 앱은 502(일반 DB 오류) 와
# 구분해 "잠시 후 재시도" UX 를 낼 수 있다.
_PG_STATEMENT_TIMEOUT = "57014"

# fallback 경고는 프로세스당 한 번만 (요청마다 찍으면 로그 홍수).
_fallback_warned = False
_fallback_cache: tuple[float, dict[str, Any]] | None = None
FALLBACK_TTL_SEC = 300.0


# ────────────────────────────────────────────────────────────────────────────
# 커서 — base64url("<started_at ISO>|<clip uuid>")
# 앱은 내용을 해석하지 않는다(opaque). 서버가 형식을 바꿔도 앱 수정 없음.
# ────────────────────────────────────────────────────────────────────────────


def encode_cursor(started_at: str, clip_id: str) -> str:
    raw = f"{started_at}|{clip_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    """opaque 커서 → (started_at ISO, clip_id). 형식이 깨졌으면 400."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        started_at, clip_id = raw.split("|", 1)
        # 두 파트 모두 실제 파싱 가능해야 통과 — RPC 에 쓰레기 값 전달 방지
        _parse_ts(started_at)
        uuid.UUID(clip_id)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="invalid cursor")
    return started_at, clip_id


def _parse_ts(value: str) -> datetime:
    """ISO8601 → aware datetime. naive 는 UTC 로 간주 (DB 는 timestamptz)."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ────────────────────────────────────────────────────────────────────────────
# GME 계약 해석
# ────────────────────────────────────────────────────────────────────────────


def _resolve_gme_contract(sb: Client) -> dict[str, str]:
    """env 우선, 부족하면 최근 ok run 으로 fallback (모듈 docstring 참고)."""
    global _fallback_warned

    schema = os.getenv("GME_ACTIVE_ENGINE_SCHEMA_VERSION", "").strip() or DEFAULT_ENGINE_SCHEMA_VERSION
    algorithm = os.getenv("GME_ACTIVE_ALGORITHM_VERSION", "").strip()
    identity = os.getenv("GME_ACTIVE_DETECTOR_IDENTITY", "").strip()

    if algorithm and identity:
        return {
            "engine_schema_version": schema,
            "algorithm_version": algorithm,
            "detector_identity": identity,
        }

    # fallback 조회는 gme_runs 정렬(created_at 인덱스 없음)이라 요청마다 돌리지 않고 5분 캐시한다.
    # env 가 설정되면 이 경로 자체를 타지 않는다.
    global _fallback_cache
    cached = _fallback_cache
    if cached and (time.monotonic() - cached[0]) < FALLBACK_TTL_SEC:
        rows = [cached[1]]
    else:
        resp = (
            sb.table("gme_runs")
            .select("algorithm_version, detector_identity")
            .eq("status", "ok")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if rows:
            _fallback_cache = (time.monotonic(), rows[0])
    if not rows:
        raise HTTPException(
            status_code=503,
            detail="GME contract unresolved: set GME_ACTIVE_ALGORITHM_VERSION / "
            "GME_ACTIVE_DETECTOR_IDENTITY (no ok gme_runs to fall back to)",
        )
    if not _fallback_warned:
        logger.warning(
            "GME_ACTIVE_ALGORITHM_VERSION / GME_ACTIVE_DETECTOR_IDENTITY 미설정 — "
            "최근 gme_runs(ok) 계약으로 fallback: algorithm=%s identity=%s…",
            rows[0]["algorithm_version"],
            str(rows[0]["detector_identity"])[:12],
        )
        _fallback_warned = True
    return {
        "engine_schema_version": schema,
        "algorithm_version": rows[0]["algorithm_version"],
        "detector_identity": rows[0]["detector_identity"],
    }


def _reset_fallback_warning() -> None:
    """테스트용."""
    global _fallback_warned, _fallback_cache
    _fallback_warned = False
    _fallback_cache = None


# ────────────────────────────────────────────────────────────────────────────
# Supabase 호출 래퍼 — 에러 매핑을 한 곳에
# ────────────────────────────────────────────────────────────────────────────


def _rpc(sb: Client, name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        resp = sb.rpc(name, params).execute()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — Supabase 는 다양한 예외 던짐
        if getattr(exc, "code", None) == _PG_STATEMENT_TIMEOUT:
            logger.warning("%s statement timeout", name)
            raise HTTPException(status_code=504, detail="highlight feed timed out")
        logger.exception("%s failed", name)
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")
    return resp.data or []


def _active_rule(sb: Client) -> Optional[dict[str, Any]]:
    rows = _rpc(sb, "fn_get_active_highlight_rule", {})
    return rows[0] if rows else None


# ────────────────────────────────────────────────────────────────────────────
# 엔드포인트
# ────────────────────────────────────────────────────────────────────────────


@router.get("/rule")
def get_active_rule(
    sb: Client = Depends(get_supabase_client),
    _user_id: str = Depends(get_current_user_id),
):
    """현재 활성 하이라이트 규칙. 없으면 404 (규칙 활성화 전 상태)."""
    rule = _active_rule(sb)
    if rule is None:
        raise HTTPException(status_code=404, detail="no active highlight rule")
    return {
        "version": rule["version"],
        "params": rule["params"],
        "activated_at": rule["activated_at"],
    }


@router.get("")
def list_highlights(
    since: Optional[str] = Query(
        default=None, description="ISO8601. 이 시각 이상(inclusive) started_at 만 반환"
    ),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: Optional[str] = Query(default=None, description="이전 응답의 next_cursor"),
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
):
    """본인 카메라의 '현재 하이라이트 = 예' 영상, 최신순.

    한 항목의 `source` 가 `human` 이면 사람 확정, `rule` 이면 활성 규칙의 1차 판정.
    `rule_version` 은 rule 항목에만 채워진다(사람 확정은 규칙과 무관).
    """
    since_dt = None
    if since is not None:
        try:
            since_dt = _parse_ts(since)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid since (ISO8601 expected)")

    cursor_started_at: Optional[str] = None
    cursor_id: Optional[str] = None
    if cursor:
        cursor_started_at, cursor_id = decode_cursor(cursor)

    # (1) 활성 규칙 — 응답 상단 rule_version 용. 규칙이 없으면 RPC 도 실패하므로 먼저 확인.
    rule = _active_rule(sb)
    if rule is None:
        raise HTTPException(status_code=404, detail="no active highlight rule")
    rule_version = rule["version"]

    # (2) 사용자 카메라. 없으면 RPC 호출 없이 빈 응답 (p_camera_ids=NULL 은 '전체' 의미라 위험).
    try:
        cam_resp = sb.table("cameras").select("id").eq("user_id", user_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("cameras lookup failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")
    camera_ids = [row["id"] for row in (cam_resp.data or [])]
    if not camera_ids:
        return {
            "highlights": [],
            "count": 0,
            "has_more": False,
            "next_cursor": None,
            "rule_version": rule_version,
        }

    # (3) GME 계약
    contract = _resolve_gme_contract(sb)

    # (4) RPC 페이지 순회. since 는 keyset 순서 덕에 첫 '오래된 행' 에서 즉시 중단.
    items: list[dict[str, Any]] = []
    has_more = False
    while True:
        rows = _rpc(
            sb,
            "fn_list_labeling_v4_clips",
            {
                "p_viewer_id": user_id,
                "p_is_owner": False,
                "p_scope": "all",
                "p_camera_ids": camera_ids,
                "p_label_state": None,
                "p_highlight_state": "yes",
                "p_engine_schema_version": contract["engine_schema_version"],
                "p_algorithm_version": contract["algorithm_version"],
                "p_detector_identity": contract["detector_identity"],
                "p_cursor_started_at": cursor_started_at,
                "p_cursor_id": cursor_id,
                "p_limit": RPC_PAGE_SIZE,
            },
        )

        stop = False
        for idx, row in enumerate(rows):
            if since_dt is not None and _parse_ts(row["started_at"]) < since_dt:
                # 이 행부터 전부 since 이전 → 더 없음
                stop = True
                has_more = False
                break
            if len(items) >= limit:
                # limit 를 채웠고 다음 행이 아직 since 안쪽 → 다음 페이지 있음
                stop = True
                has_more = True
                break
            items.append(_to_item(row, rule_version))
            # keyset 커서는 마지막으로 '소비한' 행 기준 (건너뛴 행 포함) — 여기선 항상 소비
            cursor_started_at, cursor_id = row["started_at"], row["clip_id"]

        if stop:
            break
        if len(rows) < RPC_PAGE_SIZE:
            # 페이지가 짧으면 데이터 끝
            has_more = False
            break
        if len(items) >= limit:
            # limit 딱 채우고 페이지도 꽉 참 — 다음 페이지에 더 있을 수 있음 (보수적 true;
            # 다음 호출이 빈 응답 + has_more=false 로 정리)
            has_more = True
            break

    next_cursor = (
        encode_cursor(items[-1]["started_at"], items[-1]["clip_id"])
        if has_more and items
        else None
    )
    return {
        "highlights": items,
        "count": len(items),
        "has_more": has_more,
        "next_cursor": next_cursor,
        "rule_version": rule_version,
    }


def _to_item(row: dict[str, Any], rule_version: str) -> dict[str, Any]:
    """RPC 행 → 앱 항목. reviewer_id / reviewer_display_name 은 의도적으로 제외."""
    source = row.get("highlight_source")
    return {
        "clip_id": row["clip_id"],
        "camera_id": row["camera_id"],
        "camera_name": row.get("camera_name"),
        "started_at": row["started_at"],
        "duration_sec": row.get("duration_sec"),
        "media_ready": row.get("media_ready"),
        "source": source,
        "reason": row.get("highlight_reason"),
        "rule_version": rule_version if source == "rule" else None,
        "decided_at": row.get("decided_at"),
    }
