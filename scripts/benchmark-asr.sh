#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it first: https://docs.astral.sh/uv/"
  exit 1
fi

mkdir -p .bench
uv venv --python 3.12 .bench/venv >/dev/null
source .bench/venv/bin/activate
uv pip install -U mlx-vlm mlx-qwen3-asr

python benchmarks/asr_benchmark.py "$@"
