#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
REQUEST_REL="docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-foundation-claude-review.md"
REPORT_REL="docs/handoff-prompts/2026-07-28-r1-mac-mini-runtime-foundation-claude-review-report.md"
REQUEST_PATH="${ROOT}/${REQUEST_REL}"
REPORT_PATH="${ROOT}/${REPORT_REL}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
CLAUDE_MODEL="${CLAUDE_MODEL:-opus}"
CLAUDE_EFFORT="${CLAUDE_EFFORT:-high}"

if ! git -C "$ROOT" ls-files --error-unmatch "$REQUEST_REL" >/dev/null 2>&1; then
  echo "review_request_not_committed: ${REQUEST_REL}" >&2
  exit 2
fi

if ! git -C "$ROOT" diff --quiet HEAD -- "$REQUEST_REL"; then
  echo "review_request_not_committed: ${REQUEST_REL}" >&2
  exit 2
fi

if ! command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
  echo "claude_cli_not_found: ${CLAUDE_BIN}" >&2
  exit 2
fi

mkdir -p "$(dirname "$REPORT_PATH")"
TMP_REPORT="$(mktemp "${REPORT_PATH}.tmp.XXXXXX")"
trap 'rm -f "$TMP_REPORT"' EXIT

INSTRUCTION="Read ${REQUEST_PATH} completely, then inspect every required repository file it names. Follow its read-only boundaries. Output only the complete Markdown review in the requested format; do not edit files and do not wrap the report in a code fence."

"$CLAUDE_BIN" \
  -p \
  --model "$CLAUDE_MODEL" \
  --effort "$CLAUDE_EFFORT" \
  --permission-mode plan \
  --tools "Read,Glob,Grep" \
  --no-session-persistence \
  "$INSTRUCTION" >"$TMP_REPORT"

if [[ ! -s "$TMP_REPORT" ]]; then
  echo "claude_review_empty" >&2
  exit 1
fi

mv "$TMP_REPORT" "$REPORT_PATH"
trap - EXIT
echo "CLAUDE_REVIEW_WRITTEN ${REPORT_PATH}"
