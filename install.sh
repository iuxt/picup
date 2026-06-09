#!/bin/bash
set -euo pipefail

LABEL="picup"
DOMAIN="gui/$(id -u)"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

xml_escape() {
    local value="$1"
    value=${value//&/&amp;}
    value=${value//</&lt;}
    value=${value//>/&gt;}
    value=${value//\"/&quot;}
    value=${value//\'/&apos;}
    printf '%s' "$value"
}

require_file() {
    local path="$1"
    local message="$2"

    if [[ ! -e "$path" ]]; then
        printf 'Error: %s\n' "$message" >&2
        exit 1
    fi
}

require_file "$APP_DIR/picup" "missing startup script: $APP_DIR/picup"
require_file "$APP_DIR/.venv/bin/python" "missing virtualenv python: $APP_DIR/.venv/bin/python"

mkdir -p "$HOME/Library/LaunchAgents" "$APP_DIR/logs"
chmod +x "$APP_DIR/picup"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootout "$DOMAIN" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl unload -w "$PLIST_PATH" >/dev/null 2>&1 || true

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$(xml_escape "$LABEL")</string>
    <key>ProgramArguments</key>
    <array>
        <string>$(xml_escape "$APP_DIR/picup")</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$(xml_escape "$APP_DIR")</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$(xml_escape "$APP_DIR/logs/stdout.log")</string>
    <key>StandardErrorPath</key>
    <string>$(xml_escape "$APP_DIR/logs/stderr.log")</string>
</dict>
</plist>
EOF

if ! launchctl bootstrap "$DOMAIN" "$PLIST_PATH"; then
    printf 'launchctl bootstrap failed, trying legacy launchctl load...\n' >&2
    launchctl load -w "$PLIST_PATH"
fi

launchctl enable "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || launchctl start "$LABEL"

printf 'Installed %s\n' "$PLIST_PATH"
printf 'Status: launchctl print %s/%s\n' "$DOMAIN" "$LABEL"
printf 'Logs: %s/logs/stdout.log %s/logs/stderr.log\n' "$APP_DIR" "$APP_DIR"
