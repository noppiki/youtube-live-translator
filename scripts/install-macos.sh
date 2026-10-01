#!/bin/bash
set -euo pipefail

APP_DIR="$HOME/Library/Application Support/YouTubeLiveTranslator"
VENV="$APP_DIR/.venv"
SERVER="$APP_DIR/server.py"
PLIST="$HOME/Library/LaunchAgents/com.noppiki.youtube-live-translator.plist"
LOG_DIR="$APP_DIR/logs"
RAW_BASE="https://raw.githubusercontent.com/noppiki/youtube-live-translator/main"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "This installer currently supports Apple Silicon Macs only."
  exit 1
fi

echo "▶ YouTube Live Translator local engine"
mkdir -p "$APP_DIR" "$LOG_DIR" "$HOME/Library/LaunchAgents"

if ! command -v uv >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "▶ Installing uv with Homebrew..."
    brew install uv
  else
    echo "▶ Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi

echo "▶ Creating isolated Python environment..."
uv venv --python 3.12 "$VENV"
uv pip install --python "$VENV/bin/python" "mlx-qwen3-asr>=0.4.3" "aiohttp>=3.10" "numpy>=2.0"

echo "▶ Installing local server..."
curl -fsSL "$RAW_BASE/local-server/server.py" -o "$SERVER"

echo "▶ Downloading the recommended ~517 MB model..."
"$VENV/bin/python" - <<'PY'
from mlx_qwen3_asr import Session
Session(model="moona3k/mlx-qwen3-asr-0.6b-4bit")
print("Model ready.")
PY

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.noppiki.youtube-live-translator</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV/bin/python</string>
    <string>$SERVER</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/server.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/server.err.log</string>
</dict>
</plist>
EOF

echo "▶ Registering background service..."
launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/com.noppiki.youtube-live-translator"

echo
echo "✓ Installed."
echo "  Local API: http://127.0.0.1:8765"
echo "  Logs: $LOG_DIR"
echo
echo "Return to the extension and press '接続テスト'."
