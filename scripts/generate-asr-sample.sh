#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT/benchmarks/samples"
AIFF="$OUT_DIR/asr_sample_en.aiff"
WAV="$OUT_DIR/asr_sample_en.wav"
TEXT="$(cat "$OUT_DIR/asr_sample_en.txt")"

mkdir -p "$OUT_DIR"

if ! command -v say >/dev/null 2>&1; then
  echo "macOS 'say' command is required to generate the bundled ASR sample." >&2
  exit 1
fi

echo "Generating sample speech..."
say -v Samantha -r 210 -o "$AIFF" "$TEXT"

if command -v afconvert >/dev/null 2>&1; then
  afconvert -f WAVE -d LEI16@16000 -c 1 "$AIFF" "$WAV"
elif command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -y -loglevel error -i "$AIFF" -ac 1 -ar 16000 -sample_fmt s16 "$WAV"
else
  echo "Need afconvert or ffmpeg to create WAV." >&2
  rm -f "$AIFF"
  exit 1
fi

rm -f "$AIFF"
echo "Wrote $WAV"
echo
echo "Run:"
echo "  ./scripts/benchmark-asr.sh $WAV --language English --reference-file $OUT_DIR/asr_sample_en.txt"
