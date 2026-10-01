#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

SAMPLE="benchmarks/samples/asr_sample_en.wav"
REFERENCE="benchmarks/samples/asr_sample_en.txt"

if [[ ! -f "$SAMPLE" ]]; then
  bash scripts/generate-asr-sample.sh
fi

exec bash scripts/benchmark-asr.sh "$SAMPLE" \
  --language English \
  --reference-file "$REFERENCE" \
  "$@"
