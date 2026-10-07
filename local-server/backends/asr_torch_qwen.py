from __future__ import annotations

import os
import tempfile
import wave
from typing import Any

import numpy as np

from backends.asr_base import StreamingState

LANGUAGE_NAMES = {
    "en": "English",
    "en-us": "English",
    "en-gb": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "kr": "Korean",
    "zh": "Chinese",
    "zh-cn": "Chinese",
    "zh-tw": "Chinese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
}

_sessions: dict[str, "TorchQwenSession"] = {}


def _to_wav(pcm: np.ndarray) -> str:
    pcm16 = np.clip(np.asarray(pcm, dtype=np.float32) * 32768.0, -32768, 32767).astype("<i2")
    handle, path = tempfile.mkstemp(suffix=".wav")
    os.close(handle)
    with wave.open(path, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(pcm16.tobytes())
    return path


def _select_device(torch_mod):
    if torch_mod.cuda.is_available():
        return "cuda", None
    return "cpu", torch_mod.float32


class TorchQwenSession:
    def __init__(self, model_id: str):
        import torch
        from transformers import AutoModelForMultimodalLM, AutoProcessor

        device, dtype = _select_device(torch)
        kwargs = {"device_map": "auto"}
        if device == "cpu":
            kwargs = {"dtype": dtype}
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = AutoModelForMultimodalLM.from_pretrained(model_id, **kwargs)
        if device == "cpu":
            self.model = self.model.to("cpu")
        self.model.eval()
        self.device = getattr(self.model, "device", device)
        self.dtype = getattr(self.model, "dtype", None)

    def init_streaming(
        self,
        chunk_size_sec: float = 1.0,
        max_context_sec: float = 30.0,
        context: str = "",
        language: str | None = None,
    ) -> StreamingState:
        return StreamingState(
            chunk_size_sec=chunk_size_sec,
            max_context_sec=max_context_sec,
            context=context,
            language_hint=language,
            buffer=np.zeros(0, dtype=np.float32),
        )

    def _transcribe(self, pcm: np.ndarray, language: str | None, context: str) -> tuple[str, str | None]:
        if pcm.size == 0:
            return "", language
        path = _to_wav(pcm)
        try:
            kwargs = {"audio": path}
            hint = (language or "").strip().lower()
            if hint and hint not in {"auto", "multi"}:
                kwargs["language"] = LANGUAGE_NAMES.get(hint, language)
            if context:
                kwargs["prompt"] = f"Vocabulary: {context}"
            inputs = self.processor.apply_transcription_request(**kwargs)
            move_kwargs = {}
            if self.dtype is not None:
                move_kwargs["dtype"] = self.dtype
            inputs = inputs.to(self.device, **move_kwargs)
            output_ids = self.model.generate(**inputs, max_new_tokens=256)
            generated = output_ids[:, inputs["input_ids"].shape[1]:]
            try:
                parsed = self.processor.decode(generated, return_format="parsed")[0]
                text = str(parsed.get("transcription") or "").strip()
                detected = parsed.get("language") or language
            except Exception:
                text = str(self.processor.decode(generated, return_format="transcription_only")[0]).strip()
                detected = language
            return text, detected
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def feed_audio(self, pcm: np.ndarray, state: StreamingState) -> StreamingState:
        chunk = np.asarray(pcm, dtype=np.float32).reshape(-1)
        state.buffer = chunk if state.buffer is None or getattr(state.buffer, "size", 0) == 0 else np.concatenate(
            [state.buffer, chunk]
        )
        max_samples = int(float(state.max_context_sec) * 16000)
        if state.buffer.size > max_samples:
            state.buffer = state.buffer[-max_samples:]
        min_samples = int(float(state.chunk_size_sec) * 16000)
        if state.buffer.size < min_samples:
            return state
        text, language = self._transcribe(state.buffer, state.language_hint, state.context)
        if text:
            state.text = text
            state.stable_text = text
        if language:
            state.language = language
        return state

    def finish_streaming(self, state: StreamingState) -> StreamingState:
        if state.buffer is None or getattr(state.buffer, "size", 0) == 0:
            return state
        text, language = self._transcribe(state.buffer, state.language_hint, state.context)
        if text:
            state.text = text
            state.stable_text = text
        if language:
            state.language = language
        return state


class TorchQwenAsr:
    def create_session(self, model_id: str) -> TorchQwenSession:
        session = _sessions.get(model_id)
        if session is None:
            session = TorchQwenSession(model_id)
            _sessions[model_id] = session
        return session
