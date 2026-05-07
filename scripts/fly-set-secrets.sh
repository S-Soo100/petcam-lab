#!/usr/bin/env bash
# fly.io 의 VLM 워커 앱에 secrets 주입.
# .env 에서 워커가 쓰는 키만 추출 → `flyctl secrets import` 로 한 번에 등록.
#
# 사용:
#   ./scripts/fly-set-secrets.sh                          # 기본 앱 (petcam-vlm-worker)
#   ./scripts/fly-set-secrets.sh tera-petcam-vlm          # 다른 앱 이름
#
# 주의:
#   - 프로젝트 루트에서 실행 (.env 위치 기준)
#   - flyctl 인증 필요: `flyctl auth login`
#   - secrets 변경 후 fly 가 자동 deploy 트리거 (rolling restart)

set -euo pipefail

APP_NAME="${1:-petcam-vlm-worker}"
ENV_FILE="${ENV_FILE:-.env}"

if [ ! -f "$ENV_FILE" ]; then
    echo "[error] $ENV_FILE 없음 — 프로젝트 루트에서 실행" >&2
    exit 1
fi

if ! command -v flyctl >/dev/null; then
    echo "[error] flyctl 미설치 — brew install flyctl" >&2
    exit 1
fi

SECRET_KEYS=(
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
    R2_ENDPOINT
    R2_ACCESS_KEY_ID
    R2_SECRET_ACCESS_KEY
    R2_BUCKET
    GEMINI_API_KEY
)

# 누락 검증 + 추출
secrets_input=""
missing=()
for key in "${SECRET_KEYS[@]}"; do
    # `KEY=value` 형태에서 = 이후 전부 추출 (값에 = 가 있어도 안전)
    value=$(grep -E "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2-)
    if [ -z "$value" ] || [[ "$value" == "your-"* ]] || [[ "$value" == "placeholder-"* ]]; then
        missing+=("$key")
    else
        secrets_input+="${key}=${value}"$'\n'
    fi
done

if [ ${#missing[@]} -gt 0 ]; then
    echo "[error] $ENV_FILE 에 다음 키 누락/placeholder:" >&2
    for k in "${missing[@]}"; do echo "  - $k" >&2; done
    exit 1
fi

echo "[info] app=$APP_NAME 에 ${#SECRET_KEYS[@]} 개 secrets 주입..."
echo -n "$secrets_input" | flyctl secrets import --app "$APP_NAME"
echo "[ok] secrets import 완료"
echo "[hint] flyctl secrets list --app $APP_NAME 로 마스킹 확인"
