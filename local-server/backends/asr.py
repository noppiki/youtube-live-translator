"""ASR backend adapters.

The macOS adapter keeps the existing MLX Session contract.  The Windows
adapter uses the official Transformers Qwen3-ASR model and exposes the same
streaming-session methods to the HTTP/WebSocket layer.  Transformers Qwen3-ASR
is a batch inference API, so the Windows MVP re-transcribes a bounded rolling
audio window at chunk boundaries; the browser protocol remains unchanged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import re
from typing import Any

import numpy as np


MACOS_MODELS = {
    "balanced": {
        "id": "moona3k/mlx-qwen3-asr-0.6b-4bit",
        "label": "Qwen3-ASR 0.6B 4-bit",
    },
    "accuracy": {
        "id": "moona3k/mlx-qwen3-asr-1.7b-4bit",
        "label": "Qwen3-ASR 1.7B 4-bit",
    },
}

WINDOWS_MODELS = {
    "balanced": {
        "id": "Qwen/Qwen3-ASR-0.6B-hf",
        "label": "Qwen3-ASR 0.6B (Transformers)",
    },
    "accuracy": {
        "id": "Qwen/Qwen3-ASR-1.7B-hf",
        "label": "Qwen3-ASR 1.7B (Transformers)",
    },
}


class MlxQwenASRBackend:
    """Lazy adapter for the existing Apple Silicon MLX implementation."""

    name = "mlx"
    models = MACOS_MODELS

    def __init__(self) -> None:
        self._sessions: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def get_session(self, model_id: str) -> Any:
        async with self._lock:
            session = self._sessions.get(model_id)
            if session is None:
                from mlx_qwen3_asr import Session  # type: ignore[import-not-found]

                session = await asyncio.to_thread(Session, model=model_id)
                self._sessions[model_id] = session
            return session

    @property
    def loaded_models(self) -> list[str]:
        return list(self._sessions)


@dataclass
class TorchStreamState:
    """State compatible with the fields consumed by ``server.py``."""

    language: str | None = None
    text: str = ""
    stable_text: str = ""
    audio: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float32))
    samples_since_inference: int = 0
    chunk_size_sec: float = 1.0
    max_context_sec: float = 30.0
    context: str = ""


class TorchQwenASRSession:
    """Bounded rolling-window adapter around native Transformers Qwen3-ASR."""

    def __init__(self, model: Any, processor: Any) -> None:
        self.model = model
        self.processor = processor
        self.sample_rate = 16_000
        self.device = getattr(model, "device", "cpu")
        self.dtype = getattr(model, "dtype", None)

    def init_streaming(
        self,
        *,
        chunk_size_sec: float = 1.0,
        max_context_sec: float = 30.0,
        context: str = "",
        language: str | None = None,
    ) -> TorchStreamState:
        return TorchStreamState(
            language=language,
            chunk_size_sec=max(0.5, float(chunk_size_sec)),
            max_context_sec=max(5.0, float(max_context_sec)),
            context=context,
        )

    def feed_audio(self, pcm: np.ndarray, state: TorchStreamState) -> TorchStreamState:
        if pcm.size:
            state.audio = np.concatenate((state.audio, pcm.astype(np.float32, copy=False)))
            max_samples = int(state.max_context_sec * self.sample_rate)
            if state.audio.size > max_samples:
                state.audio = state.audio[-max_samples:]
            state.samples_since_inference += int(pcm.size)

        if state.samples_since_inference >= int(state.chunk_size_sec * self.sample_rate):
            state.samples_since_inference = 0
            self._update_state(state)
        return state

    def finish_streaming(self, state: TorchStreamState) -> TorchStreamState:
        if state.audio.size:
            self._update_state(state)
        return state

    def _update_state(self, state: TorchStreamState) -> None:
        text, language = self._transcribe(state.audio, state.language, state.context)
        state.text = text
        state.stable_text = text
        if language:
            state.language = language

    def _transcribe(
        self,
        audio: np.ndarray,
        language: str | None,
        context: str,
    ) -> tuple[str, str | None]:
        if not audio.size:
            return "", language

        request = build_qwen_transcription_request(audio, language, context)
        inputs = self.processor.apply_transcription_request(**request)
        if hasattr(inputs, "to"):
            if self.dtype is not None:
                try:
                    inputs = inputs.to(self.device, self.dtype)
                except TypeError:
                    inputs = inputs.to(self.device)
            else:
                inputs = inputs.to(self.device)

        with self._inference_context():
            output_ids = self.model.generate(**inputs, max_new_tokens=256)
        input_ids = inputs["input_ids"]
        generated_ids = output_ids[:, input_ids.shape[1]:]
        decoded = self.processor.decode(generated_ids)
        raw = decoded[0] if isinstance(decoded, (list, tuple)) else decoded
        return parse_qwen_transcript(str(raw)), parse_qwen_language(str(raw))

    def _inference_context(self):
        try:
            import torch  # type: ignore[import-not-found]

            return torch.inference_mode()
        except (ImportError, OSError):
            from contextlib import nullcontext

            return nullcontext()


def build_qwen_transcription_request(
    audio: np.ndarray,
    language: str | None,
    context: str,
) -> dict[str, Any]:
    """Build the request shape expected by Transformers Qwen3-ASR.

    Qwen3-ASR uses ``prompt`` for hotwords/context.  Keep the raw 16 kHz
    float32 ndarray as ``audio``; the processor performs feature extraction.
    """

    request: dict[str, Any] = {"audio": audio}
    if language and str(language).lower() not in {"auto", "multi"}:
        request["language"] = language
    if context:
        request["prompt"] = context
    return request


class TorchQwenASRBackend:
    """Windows ASR backend using official Transformers Qwen3-ASR checkpoints."""

    name = "torch"
    models = WINDOWS_MODELS

    def __init__(self) -> None:
        self._sessions: dict[str, TorchQwenASRSession] = {}
        self._lock = asyncio.Lock()

    async def get_session(self, model_id: str) -> TorchQwenASRSession:
        async with self._lock:
            session = self._sessions.get(model_id)
            if session is None:
                session = await asyncio.to_thread(self._load_session, model_id)
                self._sessions[model_id] = session
            return session

    @staticmethod
    def _load_session(model_id: str) -> TorchQwenASRSession:
        try:
            import torch  # type: ignore[import-not-found]
            from transformers import AutoModelForMultimodalLM, AutoProcessor  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "Windows ASR dependencies are missing. Re-run install-windows.ps1."
            ) from exc

        processor = AutoProcessor.from_pretrained(model_id)
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        try:
            model = AutoModelForMultimodalLM.from_pretrained(
                model_id,
                device_map="auto",
                dtype=dtype,
            )
        except TypeError:
            # Transformers releases before the current ``dtype`` spelling use
            # ``torch_dtype``.  This fallback keeps an existing environment
            # upgradeable without changing the model or API contract.
            model = AutoModelForMultimodalLM.from_pretrained(
                model_id,
                device_map="auto",
                torch_dtype=dtype,
            )
        return TorchQwenASRSession(model, processor)

    @property
    def loaded_models(self) -> list[str]:
        return list(self._sessions)


def parse_qwen_language(raw: str) -> str | None:
    """Extract the language tag emitted by Qwen3-ASR, when present."""

    match = re.search(r"(?:language\s*)?([A-Za-z][A-Za-z _-]{1,30})\s*<asr_text>", raw, re.IGNORECASE)
    return match.group(1).strip().lower() if match else None


def parse_qwen_transcript(raw: str) -> str:
    """Remove Qwen's output marker while tolerating model-version variants."""

    text = re.sub(r"^.*?<asr_text>\s*", "", raw, count=1, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"</asr_text>.*$", "", text, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", text).strip()
