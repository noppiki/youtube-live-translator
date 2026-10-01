#!/bin/bash
set -euo pipefail

APP_DIR="$HOME/Library/Application Support/YouTubeLiveTranslator"
PLIST="$HOME/Library/LaunchAgents/com.noppiki.youtube-live-translator.plist"
NATIVE_MANIFEST="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.noppiki.youtube_live_translator.json"

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST"
rm -f "$NATIVE_MANIFEST"
rm -rf "$APP_DIR"

echo "✓ YouTube Live Translator local engine and Chrome launcher removed."
