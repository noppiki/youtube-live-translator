import sys
from pathlib import Path

import numpy as np


sys.path.insert(0, str(Path(__file__).parents[1] / "local-server"))

from backends.asr import build_qwen_transcription_request


def test_qwen_transformers_request_uses_prompt_and_raw_audio():
    audio = np.zeros(16000, dtype=np.float32)
    request = build_qwen_transcription_request(audio, "en", "OpenAI Cursor")

    assert request["audio"] is audio
    assert request["language"] == "en"
    assert request["prompt"] == "OpenAI Cursor"
    assert "context" not in request
