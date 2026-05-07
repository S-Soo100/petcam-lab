"""Gemini 2.5 Flash 호출 래퍼.

`web/src/lib/gemini.ts` 의 Python 포팅. 같은 모델 / 같은 결정론 설정 / 같은 응답 schema
→ PoC 평가셋 (159건 85.5%) 와 동일 동작 기대.

## 왜 google-generativeai (deprecated SDK)?
2026-05 기준 `google.genai` (new SDK) 로 마이그레이션 권장이지만:
- pyproject 에 이미 `google-generativeai>=0.8.6` 등록.
- web PoC 도 deprecated `@google/generative-ai` (JS) 사용 중 → SDK 동일 패밀리로 동치 검증 쉬움.
- v3.5 락인 + 서비스 종료 공지 없음 → 당장 prod 사용 OK.
- 마이그레이션은 후속 트랙 (별도 spec).

## 결정론 설정 (donts/vlm.md 룰 6)
- `temperature=0.1` — 분류 task 는 결정론. 미지정 시 기본 1.0 → 같은 클립 호출마다 라벨 흔들림.
- `top_p=0.95` — temperature 와 짝.
- `response_mime_type='application/json'` + `response_schema` — 모델이 JSON 강제. regex fallback 불필요.

## 영상 전달 — 다운로드 후 inline
spec §4-3 검토 결과 inline base64 가 가장 단순 + PoC 와 동치. R2 → bytes → base64 → Gemini.
- Gemini 2.5 Flash 의 inline 한도 ~20MB. 우리 60s 인코딩 클립 ~5MB → 여유.
- signed URL 만 넘기는 방식은 google-generativeai 0.8.6 의 inline_data 가 URL 직접 지원 안 함.
  Files API 별도 호출 필요 → 복잡. PoC 패턴 그대로.

## 에러 분기 (donts/vlm.md 룰 4)
- 일시 (재시도): ResourceExhausted (429), DeadlineExceeded, InternalServerError, ServiceUnavailable
- 영구 (즉시 raise): InvalidArgument (400), PermissionDenied (403), Unauthenticated (401)

워커가 위 분기를 보고 backoff 또는 `behavior_logs(source='vlm_failed')` INSERT 결정 (spec §4-8).
"""

from __future__ import annotations

import json
import logging
import os
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

# google-generativeai 0.8.6 가 module 로드 시 FutureWarning 출력 — 워커 stdout 노이즈
# 방지. 프로젝트 차원에서 deprecation 인지하고 있고 (이 파일 docstring) 사용자에게 매번
# 알릴 가치 없음.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    import google.generativeai as genai
    from google.generativeai.types import GenerationConfig
from dotenv import load_dotenv
from google.api_core import exceptions as gax  # google-api-core

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

VLM_MODEL_ID = "gemini-2.5-flash"

# 일시 에러 → backoff 후 재시도. RateLimitError 만 backoff 하라는 룰을 살짝 확장 —
# 504 / 500 / 503 도 일시. AuthError 는 별도 분기.
TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
    gax.ResourceExhausted,  # 429
    gax.DeadlineExceeded,  # 504
    gax.InternalServerError,  # 500
    gax.ServiceUnavailable,  # 503
)

# 영구 에러 → 즉시 raise. 워커가 source='vlm_failed' INSERT.
PERMANENT_ERRORS: tuple[type[Exception], ...] = (
    gax.InvalidArgument,  # 400
    gax.PermissionDenied,  # 403
    gax.Unauthenticated,  # 401
)


class GeminiNotConfigured(RuntimeError):
    """GEMINI_API_KEY 누락 / placeholder."""


class VlmResponseInvalid(RuntimeError):
    """모델 응답이 기대 schema 와 다름. 영구 에러로 취급 (재시도 무의미)."""


@dataclass(frozen=True, slots=True)
class VlmResult:
    """추론 결과 1건 — donts/vlm.md 룰 3 의 immutable record 패턴."""

    action: str  # 호출 측에서 종 가용 클래스로 검증
    confidence: float
    reasoning: str
    model_id: str
    # usage_metadata — 비용/디버깅용. spec §4-6: DB 컬럼은 후속, 지금은 로그.
    tokens_input: int | None
    tokens_output: int | None


# spec §4-5 — JSON Schema 박아 모델이 강제로 그 구조로 응답.
_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
    "required": ["action", "confidence", "reasoning"],
}


@lru_cache(maxsize=1)
def get_model() -> genai.GenerativeModel:
    """싱글톤 GenerativeModel. lazy 초기화 — module load 시 throw 안 됨.

    web/src/lib/gemini.ts 의 `_getModel` 과 동치. r2_uploader / supabase_client 의
    lru_cache 패턴 동일 (테스트는 reset_cache).
    """
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiNotConfigured("GEMINI_API_KEY 누락. .env 확인.")
    if "your-" in api_key.lower() or "paste_" in api_key.lower():
        raise GeminiNotConfigured("GEMINI_API_KEY placeholder. AI Studio 에서 발급 후 .env 기입.")

    genai.configure(api_key=api_key)
    return genai.GenerativeModel(
        VLM_MODEL_ID,
        generation_config=GenerationConfig(
            temperature=0.1,
            top_p=0.95,
            response_mime_type="application/json",
            response_schema=_RESPONSE_SCHEMA,
        ),
    )


def reset_model_cache() -> None:
    """테스트용 — env 바꾸고 재초기화."""
    get_model.cache_clear()


def classify_clip(*, video_bytes: bytes, system_prompt: str) -> VlmResult:
    """영상 1건 → 행동 1개 + confidence + reasoning.

    web/src/lib/gemini.ts:33 `classifyClip` 과 동치. **동기 함수** — 호출 측이
    `asyncio.to_thread` 로 비동기화 (boto3 / supabase-py 와 같은 패턴).

    Args:
        video_bytes: 인코딩된 mp4 raw bytes. R2 에서 download 한 결과.
        system_prompt: `prompts.build_system_prompt(species)` 결과.

    Returns:
        VlmResult — action / confidence / reasoning / 토큰 사용량.

    Raises:
        TRANSIENT_ERRORS: 429/500/503/504. 호출 측 backoff.
        PERMANENT_ERRORS: 400/401/403. 호출 측 source='vlm_failed' INSERT.
        VlmResponseInvalid: schema 어김. 영구 에러로 취급.
    """
    model = get_model()
    try:
        response = model.generate_content(
            [
                system_prompt,
                {"inline_data": {"mime_type": "video/mp4", "data": video_bytes}},
            ]
        )
    except (TRANSIENT_ERRORS + PERMANENT_ERRORS):
        # 분기는 호출 측 — 여기서는 그대로 전파 (정보 손실 없게).
        raise

    text = (response.text or "").strip()
    if not text:
        raise VlmResponseInvalid(f"empty response — feedback={response.prompt_feedback}")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        # response_mime_type=json 강제했는데도 깨졌으면 영구 (모델 사고).
        raise VlmResponseInvalid(f"non-JSON response: {text[:300]}") from exc

    if not isinstance(parsed, dict):
        raise VlmResponseInvalid(f"response not object: {text[:300]}")
    action = parsed.get("action")
    confidence = parsed.get("confidence")
    reasoning = parsed.get("reasoning", "")
    if not isinstance(action, str):
        raise VlmResponseInvalid(f"action 필드 누락/타입 오류: {parsed!r}")
    if not isinstance(confidence, (int, float)):
        raise VlmResponseInvalid(f"confidence 필드 누락/타입 오류: {parsed!r}")
    if not isinstance(reasoning, str):
        reasoning = str(reasoning) if reasoning is not None else ""

    usage = getattr(response, "usage_metadata", None)
    tokens_in = getattr(usage, "prompt_token_count", None) if usage else None
    tokens_out = getattr(usage, "candidates_token_count", None) if usage else None

    return VlmResult(
        action=action,
        confidence=float(confidence),
        reasoning=reasoning,
        model_id=VLM_MODEL_ID,
        tokens_input=tokens_in,
        tokens_output=tokens_out,
    )


def download_clip_bytes(r2_key: str) -> bytes:
    """R2 object → bytes. boto3 get_object 직접 호출 — signed URL 우회.

    워커가 같은 프로세스 + 같은 키 자격이라 signed URL 생성 후 다시 download 할
    이유 없음. 라벨링 웹 (signed URL 발급) 과 워커 (직접 read) 가 같은 R2 client 사용.
    """
    # 지연 import — 테스트가 boto3 없이 backend.vlm.gemini_client 자체를 import 해도
    # 깨지지 않게.
    from backend.r2_uploader import get_r2_bucket, get_r2_client

    client = get_r2_client()
    bucket = get_r2_bucket()
    resp = client.get_object(Bucket=bucket, Key=r2_key)
    return resp["Body"].read()


__all__ = [
    "GeminiNotConfigured",
    "PERMANENT_ERRORS",
    "TRANSIENT_ERRORS",
    "VLM_MODEL_ID",
    "VlmResponseInvalid",
    "VlmResult",
    "classify_clip",
    "download_clip_bytes",
    "get_model",
    "reset_model_cache",
]
