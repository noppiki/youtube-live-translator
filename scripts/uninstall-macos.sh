#!/bin/bash
set -euo pipefail
APP_DIR="$HOME/Library/Application Support/YouTubeLiveTranslator"
PLIST="$HOME/Library/LaunchAgents/com.noppiki.youtube-live-translator.plist"
launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST"
rm -rf "$APP_DIR"
echo "✓ YouTube Live Translator local engine removed."
