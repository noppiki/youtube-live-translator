#!/bin/bash
set -euo pipefail

EXTENSION_ID="${1:-}"
APP_DIR="$HOME/Library/Application Support/YouTubeLiveTranslator"
VENV="$APP_DIR/.venv"
SERVER="$APP_DIR/server.py"
PLIST="$HOME/Library/LaunchAgents/com.noppiki.youtube-live-translator.plist"
LOG_DIR="$APP_DIR/logs"
BIN_DIR="$APP_DIR/bin"
FLUID_SRC="$APP_DIR/fluid-bridge-src"
NATIVE_DIR="$APP_DIR/native"
NATIVE_SCRIPT="$NATIVE_DIR/launcher.py"
NATIVE_WRAPPER="$NATIVE_DIR/host"
NATIVE_HOST_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
NATIVE_MANIFEST="$NATIVE_HOST_DIR/com.noppiki.youtube_live_translator.json"
RAW_BASE="https://raw.githubusercontent.com/noppiki/youtube-live-translator/main"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "This installer currently supports Apple Silicon Macs only."
  exit 1
fi

echo "▶ YouTube Live Translator local engine"
mkdir -p "$APP_DIR" "$LOG_DIR" "$BIN_DIR" "$NATIVE_DIR" "$HOME/Library/LaunchAgents"

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

echo "▶ Creating/updating isolated Python environment..."
uv venv --python 3.12 "$VENV"
uv pip install --python "$VENV/bin/python" "mlx-qwen3-asr>=0.4.3" "aiohttp>=3.10" "numpy>=2.0"

echo "▶ Installing local routing server..."
curl -fsSL "$RAW_BASE/local-server/server.py" -o "$SERVER"

echo "▶ Preparing Qwen3-ASR 0.6B..."
"$VENV/bin/python" - <<'PY'
from mlx_qwen3_asr import Session
Session(model="moona3k/mlx-qwen3-asr-0.6b-4bit")
print("Qwen3-ASR ready.")
PY

if command -v swift >/dev/null 2>&1; then
  echo "▶ Building FluidAudio bridge (first build can take several minutes)..."
  mkdir -p "$FLUID_SRC/Sources/FluidBridge"
  curl -fsSL "$RAW_BASE/fluid-bridge/Package.swift" -o "$FLUID_SRC/Package.swift"
  curl -fsSL "$RAW_BASE/fluid-bridge/Sources/FluidBridge/main.swift" -o "$FLUID_SRC/Sources/FluidBridge/main.swift"

  if swift build -c release --package-path "$FLUID_SRC"; then
    cp "$FLUID_SRC/.build/release/FluidBridge" "$BIN_DIR/fluid-bridge"
    chmod +x "$BIN_DIR/fluid-bridge"
    echo "✓ FluidAudio bridge installed."
  else
    echo "⚠ FluidAudio bridge build failed. Qwen3-ASR will still work."
    echo "  See the build output above, then rerun this installer after fixing Swift/Xcode."
  fi
else
  echo "⚠ Swift toolchain not found. Skipping FluidAudio."
  echo "  Install Xcode Command Line Tools/Xcode, then rerun this installer."
fi

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
  <false/>
  <key>KeepAlive</key>
  <false/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/server.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/server.err.log</string>
</dict>
</plist>
EOF

echo "▶ Registering local engine service..."
launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "▶ Installing Chrome Native Messaging launcher..."
curl -fsSL "$RAW_BASE/native-host/launcher.py" -o "$NATIVE_SCRIPT"

cat > "$NATIVE_WRAPPER" <<EOF
#!/bin/bash
exec "$VENV/bin/python" "$NATIVE_SCRIPT"
EOF
chmod +x "$NATIVE_WRAPPER"

if [[ -n "$EXTENSION_ID" ]]; then
  mkdir -p "$NATIVE_HOST_DIR"
  cat > "$NATIVE_MANIFEST" <<EOF
{
  "name": "com.noppiki.youtube_live_translator",
  "description": "Start the local AI service for YouTube Live Translator",
  "path": "$NATIVE_WRAPPER",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://$EXTENSION_ID/"
  ]
}
EOF
  echo "✓ One-click launcher registered for extension: $EXTENSION_ID"
else
  echo "⚠ Extension ID was not supplied."
  echo "  Local AI is installed, but the Chrome one-click start button will not work."
  echo "  Re-run this installer from the command shown inside the extension popup."
fi

echo
echo "✓ Installed/updated."
echo "  Local API (when started): http://127.0.0.1:8765"
echo "  Qwen3-ASR: ready"
if [[ -x "$BIN_DIR/fluid-bridge" ]]; then
  echo "  FluidAudio bridge: ready (models download from the extension on first preparation)"
else
  echo "  FluidAudio bridge: unavailable"
fi
echo "  Logs: $LOG_DIR"
echo
echo "Reload the Chrome extension, then press 'ローカルAI起動'."
