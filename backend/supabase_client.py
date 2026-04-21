"""
Supabase 싱글톤 클라이언트.

## 왜 service_role 인가?
FastAPI 서버는 "어느 유저의 세그먼트든" INSERT 해야 하니 RLS 를 바이패스하는
service_role 키가 필요. 대신 이 키는 절대 클라이언트(앱/브라우저) 에 노출되면
안 되고 petcam-lab `.env` 에만 보관.

앱(Flutter) 은 반대로 `anon` 키 + JWT 로만 접근 → RLS 정책이 "본인 것만 SELECT"
를 DB 레벨에서 강제.

## 왜 lru_cache 싱글톤?
- `create_client` 는 HTTP 세션 + auth 매니저 객체를 생성하는 비용 있는 작업.
  매 요청마다 새로 만들면 커넥션 폭증.
- `@lru_cache` 로 감싸면 프로세스 스코프 싱글톤 효과.
- FastAPI `Depends(get_supabase_client)` 로도, 캡처 워커에서 직접 호출로도 동일 인스턴스.
- 테스트에서는 `app.dependency_overrides[get_supabase_client] = lambda: Mock()`
  로 갈아끼우거나 `reset_client_cache()` 후 env 바꾸면 됨.

NestJS 비유: `@Injectable({ scope: Scope.DEFAULT })` provider.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, create_client

REPO_ROOT = Path(__file__).resolve().parent.parent

# placeholder 감지용 — .env.example / 초기 .env 에서 쓰이는 더미 값 패턴
_PLACEHOLDER_PATTERNS = ("PASTE_", "your-service-role-key", "your-project")


class SupabaseNotConfigured(RuntimeError):
    """SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY 가 비어있거나 placeholder 일 때."""


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """
    싱글톤 Supabase 클라이언트. FastAPI Depends 로도 사용 가능.

    Raises:
        SupabaseNotConfigured: 환경변수 누락 또는 placeholder 상태
    """
    # lifespan 에서 이미 로드되지만, 테스트·스크립트에서 직접 호출될 수도 있어서
    # 여기서도 load_dotenv (이미 로드된 값은 덮어쓰지 않음 = no-op 성격).
    load_dotenv(REPO_ROOT / ".env")

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        raise SupabaseNotConfigured(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 환경변수 필요. .env 확인."
        )
    if any(p in url for p in _PLACEHOLDER_PATTERNS) or any(
        p in key for p in _PLACEHOLDER_PATTERNS
    ):
        raise SupabaseNotConfigured(
            "SUPABASE_URL / SERVICE_ROLE_KEY 가 placeholder 상태. "
            "Supabase 대시보드 > Settings > API 에서 실제 값 복사해 .env 기입."
        )

    return create_client(url, key)


def reset_client_cache() -> None:
    """테스트용: 싱글톤 캐시 비움. 환경변수 바꾸고 재생성할 때."""
    get_supabase_client.cache_clear()
