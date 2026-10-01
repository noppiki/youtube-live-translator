#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <youtube-url> [start-seconds] [duration-seconds]"
  exit 1
fi

URL="$1"
START="${2:-60}"
DURATION="${3:-45}"
END="$(python3 - <<PY
print(float("$START") + float("$DURATION"))
PY
)"

if ! command -v yt-dlp >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "Installing yt-dlp..."
    brew install yt-dlp
  else
    echo "yt-dlp is required." >&2
    exit 1
  fi
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "Installing ffmpeg..."
    brew install ffmpeg
  else
    echo "ffmpeg is required." >&2
    exit 1
  fi
fi

mkdir -p .bench/youtube
RAW=".bench/youtube/source.%(ext)s"
WAV=".bench/youtube/sample.wav"

rm -f .bench/youtube/source.* "$WAV"

echo "Downloading YouTube section $START-$END seconds..."
yt-dlp   --no-playlist   -f "bestaudio/best"   --download-sections "*$START-$END"   --force-keyframes-at-cuts   -o "$RAW"   "$URL"

SRC="$(find .bench/youtube -maxdepth 1 -type f -name 'source.*' | head -1)"
if [[ -z "$SRC" ]]; then
  echo "Downloaded audio not found." >&2
  exit 1
fi

ffmpeg -y -loglevel error -i "$SRC" -ac 1 -ar 16000 -c:a pcm_s16le "$WAV"
echo "Wrote $WAV"

echo
echo "=== Qwen3-ASR 0.6B ==="
bash scripts/benchmark-asr.sh "$WAV"   --models qwen06   --language English   --output .bench/youtube/qwen-result.json

echo
echo "=== FluidAudio / Parakeet EOU 120M ==="
python3 benchmarks/fluid_asr_benchmark.py "$WAV"   --output .bench/youtube/fluid-result.json

python3 - <<'PY'
import json
from pathlib import Path

q = json.loads(Path(".bench/youtube/qwen-result.json").read_text())[0]
f = json.loads(Path(".bench/youtube/fluid-result.json").read_text())

print("\n=== Side by side ===")
print(f"Qwen3 0.6B: {q['transcribe_s']}s")
print(q["text"])
print()
print(f"Parakeet EOU: {f['transcribe_s']}s")
print(f["text"])
print()
print("Results:")
print("  .bench/youtube/qwen-result.json")
print("  .bench/youtube/fluid-result.json")
print("  .bench/youtube/sample.wav")
PY
