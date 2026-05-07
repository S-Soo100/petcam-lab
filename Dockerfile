# syntax=docker/dockerfile:1.7
# VLM 워커 (backend.vlm_worker_main) 단독 컨테이너.
# capture / API 서버는 별도 — 같은 베이스 이미지여도 entrypoint 만 다름.
#
# 멀티스테이지 이유:
#   builder = uv 로 .venv 빌드 (pip 등 도구 설치)
#   runtime = .venv + 코드만 → 최종 이미지에 uv/build 도구 안 들어감 (작고 안전)

# ============================================================
# Stage 1: builder
# ============================================================
FROM python:3.12-slim AS builder

# uv 설치 — pip 한 줄. 공식 이미지 (`ghcr.io/astral-sh/uv`) 도 가능하지만 단순함 우선.
RUN pip install --no-cache-dir uv==0.5.18

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# 1단계: lock 파일만 복사 → 의존성 layer 캐시 hit (코드 바뀌어도 재설치 X)
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# 2단계: 코드 복사 후 프로젝트 install
# web/prompts/ = backend.vlm.prompts 가 read 하는 v3.5 백업 (backend/vlm/prompts.py:36).
# 라벨링 웹과 같은 SOT 공유 — drift 차단 위해 worker 도 같은 파일 사용.
COPY backend/ ./backend/
COPY web/prompts/ ./web/prompts/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ============================================================
# Stage 2: runtime
# ============================================================
FROM python:3.12-slim AS runtime

# tini = PID 1 signal forwarding. Python 이 PID 1 이면 SIGTERM 안 받음 → graceful shutdown 깨짐.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# non-root user — 컨테이너 escape 시 root 권한 차단
RUN groupadd -r app && useradd -r -g app -d /app -s /bin/bash app

WORKDIR /app

# builder 의 .venv + 코드만 옮김 (uv, pip, apt 캐시 등 안 들어옴)
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/backend /app/backend
COPY --from=builder --chown=app:app /app/web /app/web

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app

# fly health check 가 노릴 포트 — /health endpoint 가 listen
EXPOSE 8080

# tini → python — SIGTERM 이 python 까지 forwarding 됨 (graceful drain)
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "backend.vlm_worker_main"]
