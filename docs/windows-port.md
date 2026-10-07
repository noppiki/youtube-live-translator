# Windows local AI port

Issue #1 adds Windows 10/11 x64 without rewriting the Chrome 127.0.0.1:8765 contract.

## Shape

`RuntimeProfile` in `local-server/runtime.py` is the only OS decision. `server.py` is an HTTP/WebSocket shell. MLX and PyTorch stay behind `local-server/backends/`.

| OS | ASR | Translation | Diarization |
| --- | --- | --- | --- |
| macOS | mlx-qwen3-asr | mlx-lm Gemma 4 E4B | FluidAudio when installed |
| Windows | Transformers Qwen3-ASR | llama.cpp Gemma 4 E4B Q4_0 | not available in this release |

`YTLT_APP_DIR` overrides the default app directory.

- macOS: `~/Library/Application Support/YouTubeLiveTranslator`
- Windows: `%LOCALAPPDATA%\YouTubeLiveTranslator`

## Verification

```bash
python -m unittest discover -s tests -v
```

The import isolation test fails if `server.py` grows a top-level MLX or Torch import.
