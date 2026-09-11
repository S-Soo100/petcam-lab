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

## GME 계약 고정
웹과 같은 명시적 algorithm/detector 설정만 사용한다. 설정 오류는 503이며
최신 shadow run을 현재 운영 계약으로 자동 선택하지 않는다.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
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

# ── ⭐ 대표 tier(2026-09-10, 스펙 feature-highlight-featured-tier) — fn_highlight_featured 기본값과 같은 값.
# v0.1(2026-09-11 owner): 10분 묶기 · 시간당 3개 · 하루 상한 없음(top_n None). 바꾸면 DB DEFAULT·라벨링 웹(labelingV4.ts) 도 같이(런북 §6.y).
FEATURED_DEFAULT_DAYS = 7
FEATURED_MAX_DAYS = 31
FEATURED_DEFAULT_TOP_N: Optional[int] = None  # None = 하루 상한 없음
FEATURED_MAX_TOP_N = 50
FEATURED_GAP_SEC = 600
FEATURED_HOUR_CAP = 3
FEATURED_DAY_START_HOUR = 20
FEATURED_TZ = "Asia/Seoul"
_KST = timezone(timedelta(hours=9))


def featured_window(now: datetime, days: int) -> tuple[datetime, datetime]:
    """하루 키(20:00 KST 경계) 기준 최근 `days` 개 하루를 덮는 [from, now).

    `now - days` 로 자르면 첫 하루가 반쪽이라 그 하루의 top-N 이 틀어진다. 그래서 오늘 키에서 days-1 만큼
    거슬러 간 하루의 20:00 KST 를 시작으로 잡는다(scripts/report_highlight_featured.day_window 와 같은 정의).
    """
    key_today = (now.astimezone(_KST) - timedelta(hours=FEATURED_DAY_START_HOUR)).date()
    first = key_today - timedelta(days=days - 1)
    start = datetime(first.year, first.month, first.day, FEATURED_DAY_START_HOUR, tzinfo=_KST)
    return start.astimezone(timezone.utc), now

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


def _resolve_gme_contract() -> dict[str, str]:
    """승인된 env 계약만 사용해 shadow run의 자동 운영 유입을 막는다."""
    schema = os.getenv("GME_ACTIVE_ENGINE_SCHEMA_VERSION", "").strip() or DEFAULT_ENGINE_SCHEMA_VERSION
    algorithm = os.getenv("GME_ACTIVE_ALGORITHM_VERSION", "")
    identity = os.getenv("GME_ACTIVE_DETECTOR_IDENTITY", "")
    if (schema != DEFAULT_ENGINE_SCHEMA_VERSION
            or re.fullmatch(r"gme-motion-v[0-9]+", algorithm) is None
            or re.fullmatch(r"[0-9a-f]{64}", identity) is None):
        raise HTTPException(status_code=503, detail="GME active contract is not configured correctly")
    return {"engine_schema_version": schema, "algorithm_version": algorithm, "detector_identity": identity}


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


def _owned_camera_ids(sb: Client, user_id: str) -> list[str]:
    """본인 소유 카메라 id. 없으면 [] — 호출자는 RPC 없이 빈 응답(p_camera_ids=NULL 은 '전체' 라 위험)."""
    try:
        cam_resp = sb.table("cameras").select("id").eq("owner_id", user_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("cameras lookup failed")
        raise HTTPException(status_code=502, detail=f"supabase error: {exc}")
    return [row["id"] for row in (cam_resp.data or [])]


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


@router.get("/featured")
def list_featured_highlights(
    days: int = Query(default=FEATURED_DEFAULT_DAYS, ge=1, le=FEATURED_MAX_DAYS, description="하루(20:00 KST 경계) 단위 최근 N일"),
    tier: str = Query(default="featured", pattern="^(featured|all)$", description="featured=대표만(기본) · all=후보 포함"),
    top_n: Optional[int] = Query(default=FEATURED_DEFAULT_TOP_N, ge=1, le=FEATURED_MAX_TOP_N, description="하루·카메라당 상한. 생략 = 상한 없음"),
    sb: Client = Depends(get_supabase_client),
    user_id: str = Depends(get_current_user_id),
):
    """본인 카메라의 ⭐ 대표 하이라이트 — 10분 에피소드의 대표 클립, 같은 시간대(KST 시) 안 최대 3개, 하루 상한은 기본 없음. 저장된 값이 아니라 조회 시 계산.

    `tier=all` 이면 나머지 O(후보)도 함께 온다 — 앱의 "더 보기". 정렬은 (하루 최신, 카메라, 사건 순위, 시각 최신).
    기존 `GET /highlights`(O 전체·keyset) 는 그대로 — 이 엔드포인트는 그 위의 예산 레이어다.
    """
    rule = _active_rule(sb)
    if rule is None:
        raise HTTPException(status_code=404, detail="no active highlight rule")
    meta = {"top_n": top_n, "hour_cap": FEATURED_HOUR_CAP, "gap_sec": FEATURED_GAP_SEC, "day_start_hour": FEATURED_DAY_START_HOUR, "time_zone": FEATURED_TZ, "days": days}
    camera_ids = _owned_camera_ids(sb, user_id)
    if not camera_ids:
        return {"highlights": [], "count": 0, "rule_version": rule["version"], "featured": meta}
    contract = _resolve_gme_contract()
    p_from, p_to = featured_window(datetime.now(timezone.utc), days)
    rows = _rpc(
        sb,
        "fn_highlight_featured",
        {
            "p_camera_ids": camera_ids,
            "p_from": p_from.isoformat(),
            "p_to": p_to.isoformat(),
            "p_engine_schema_version": contract["engine_schema_version"],
            "p_algorithm_version": contract["algorithm_version"],
            "p_detector_identity": contract["detector_identity"],
            "p_top_n": top_n,
            "p_gap_sec": FEATURED_GAP_SEC,
            "p_day_start_hour": FEATURED_DAY_START_HOUR,
            "p_tz": FEATURED_TZ,
            "p_hour_cap": FEATURED_HOUR_CAP,
        },
    )
    items = [_to_featured_item(r, rule["version"]) for r in rows if tier == "all" or r.get("tier") == "featured"]
    return {"highlights": items, "count": len(items), "rule_version": rule["version"], "featured": meta}


def _to_featured_item(row: dict[str, Any], rule_version: str) -> dict[str, Any]:
    """feed 행 → 앱 항목. reviewer_* 는 의도적으로 제외. `episode` 는 카드 문구 재료("사건 6클립 · 움직임 84초")."""
    source = row.get("highlight_source")
    return {
        "clip_id": row["clip_id"],
        "camera_id": row["camera_id"],
        "camera_name": row.get("camera_name"),
        "started_at": row["started_at"],
        "duration_sec": row.get("duration_sec"),
        "media_ready": True,  # 함수가 media_deleted 를 이미 걸렀다
        "source": source,
        "reason": row.get("highlight_reason"),
        "rule_version": rule_version if source == "rule" else None,
        "tier": row.get("tier"),
        "day_key": row.get("day_key"),
        "activity_sec": row.get("activity_sec"),
        "behavior_flagged": bool(row.get("behavior_flagged")),
        "episode": {
            "rank": row.get("episode_rank"),
            "hour_rank": row.get("episode_hour_rank"),
            "clip_count": row.get("episode_clip_count"),
            "activity_sec": row.get("episode_activity_sec"),
            "started_at": row.get("episode_started_at"),
            "ended_at": row.get("episode_ended_at"),
        },
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
    camera_ids = _owned_camera_ids(sb, user_id)
    if not camera_ids:
        return {
            "highlights": [],
            "count": 0,
            "has_more": False,
            "next_cursor": None,
            "rule_version": rule_version,
        }

    # (3) GME 계약
    contract = _resolve_gme_contract()

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
