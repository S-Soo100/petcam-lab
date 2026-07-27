#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${RESEARCH_EXPECTED_HOST:-}" ]]; then
  echo "RESEARCH_EXPECTED_HOST is required" >&2
  exit 2
fi
if [[ -z "${RESEARCH_EXPECTED_HEAD:-}" ]]; then
  echo "RESEARCH_EXPECTED_HEAD is required" >&2
  exit 2
fi

checkout="${RESEARCH_CHECKOUT:-/Users/baek-end/petcam-lab-research-runtime}"
runtime_root="${RESEARCH_RUNTIME_ROOT:-/Users/baek-end/Library/Application Support/petcam/research-runtime}"
label="com.petcam.research-runtime"
plist="${HOME}/Library/LaunchAgents/${label}.plist"
actual_host="$(hostname)"

if [[ "$actual_host" != "$RESEARCH_EXPECTED_HOST" ]]; then
  echo "BLOCKED_RUNTIME_HOST_MISMATCH" >&2
  exit 2
fi
if [[ ! -d "$checkout/.git" && ! -f "$checkout/.git" ]]; then
  echo "BLOCKED_RUNTIME_REPO_MISSING" >&2
  exit 2
fi
if [[ "$(git -C "$checkout" rev-parse HEAD)" != "$RESEARCH_EXPECTED_HEAD" ]]; then
  echo "BLOCKED_RUNTIME_HEAD_MISMATCH" >&2
  exit 2
fi
if [[ -n "$(git -C "$checkout" status --porcelain --untracked-files=all)" ]]; then
  echo "BLOCKED_RUNTIME_DIRTY" >&2
  exit 2
fi

uv_bin="$(command -v uv)"
mkdir -p "$(dirname "$plist")" "$runtime_root/logs"
chmod 700 "$runtime_root" "$runtime_root/logs"
tmp_plist="$(mktemp "${TMPDIR:-/tmp}/${label}.XXXXXX.plist")"
trap 'rm -f "$tmp_plist"' EXIT

cat >"$tmp_plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
    <string>-dimsu</string>
    <string>${uv_bin}</string>
    <string>run</string>
    <string>python</string>
    <string>-m</string>
    <string>backend.research_runtime.main</string>
    <string>run-once</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${checkout}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$(dirname "$uv_bin"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>RESEARCH_RUNTIME_ROOT</key>
    <string>${runtime_root}</string>
    <key>RESEARCH_REPO_ROOT</key>
    <string>${checkout}</string>
    <key>RESEARCH_EXPECTED_HOST</key>
    <string>${RESEARCH_EXPECTED_HOST}</string>
    <key>RESEARCH_EXPECTED_HEAD</key>
    <string>${RESEARCH_EXPECTED_HEAD}</string>
    <key>RESEARCH_QUIET_WINDOWS_CONFIG</key>
    <string>${checkout}/config/research-runtime-quiet-windows.json</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>60</integer>
  <key>StandardOutPath</key>
  <string>${runtime_root}/logs/launchd.stdout.log</string>
  <key>StandardErrorPath</key>
  <string>${runtime_root}/logs/launchd.stderr.log</string>
</dict>
</plist>
PLIST

plutil -lint "$tmp_plist"
chmod 600 "$tmp_plist"
mv "$tmp_plist" "$plist"
launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "INSTALLED ${label}"
echo "ROLLBACK: launchctl bootout gui/$(id -u)/${label} && rm '${plist}'"
