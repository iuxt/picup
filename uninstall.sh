#!/bin/bash
set -euo pipefail

LABEL="picup"
DOMAIN="gui/$(id -u)"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootout "$DOMAIN" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl unload -w "$PLIST_PATH" >/dev/null 2>&1 || true

rm -f "$PLIST_PATH"

printf 'Uninstalled %s\n' "$LABEL"
printf 'Removed %s\n' "$PLIST_PATH"
