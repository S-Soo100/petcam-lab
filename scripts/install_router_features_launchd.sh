#!/usr/bin/env bash
set -euo pipefail

LABEL="uk.tera-ai.petcam-router-features"
REPO_DIR="${PETCAM_REPO_DIR:-$(pwd)}"
PLIST_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs/petcam-lab"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
UV_BIN="${UV_BIN:-$(command -v uv || true)}"

if [[ -z "$UV_BIN" && -x "$HOME/.local/bin/uv" ]]; then
  UV_BIN="$HOME/.local/bin/uv"
fi

if [[ -z "$UV_BIN" && -x "/opt/homebrew/bin/uv" ]]; then
  UV_BIN="/opt/homebrew/bin/uv"
fi

if [[ -z "$UV_BIN" ]]; then
  echo "uv not found. Set UV_BIN=/path/to/uv or install uv." >&2
  exit 1
fi

if [[ ! -d "$REPO_DIR" ]]; then
  echo "repo dir not found: $REPO_DIR" >&2
  exit 1
fi

mkdir -p "$PLIST_DIR" "$LOG_DIR"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>WorkingDirectory</key>
  <string>$REPO_DIR</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UV_BIN</string>
    <string>run</string>
    <string>python</string>
    <string>-m</string>
    <string>backend.router_features_main</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/router-features.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/router-features.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin</string>
  </dict>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "installed: $PLIST_PATH"
echo "logs:"
echo "  $LOG_DIR/router-features.out.log"
echo "  $LOG_DIR/router-features.err.log"
echo
echo "status:"
launchctl print "gui/$(id -u)/$LABEL" | sed -n '1,40p'
