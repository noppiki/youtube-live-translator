"""Translation backend adapters for MLX and llama.cpp OpenAI-compatible APIs."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Iterable


TRANSLATION_SYSTEM = """You translate live-stream captions into concise, natural Japanese subtitles.
Use recent dialogue only as context. Translate CURRENT only.
Output Japanese only. Do not leave Korean, Chinese, Spanish, French, German, or other source-language words in the output unless they are proper names, product names, model names, acronyms, or glossary-preserved terms.
Preserve person names, product names, model names, acronyms, and technical terms in Latin script unless the glossary explicitly specifies a Japanese form.
Follow the glossary exactly.
Do not explain or add notes.
Prefer natural spoken Japanese over literal wording.
Never drop meaning, negation, numbers, measurement units, or currency units.
If a number has a unit in the source, keep the unit in Japanese in the translation."""


def build_translation_messages(
    text: str,
    context: Iterable[Any] | None,
    glossary: Iterable[Any] | None,
    source: str,
    target: str,
) -> list[dict[str, str]]:
    """Build the shared prompt used by both translation implementations."""

    recent = "\n".join(str(item) for item in (list(context or []))[-3:]) or "(none)"
    glossary_text = "\n".join(f"- {item}" for item in (glossary or [])) or "(none)"
    user = f"""SOURCE LANGUAGE: {source}
TARGET LANGUAGE: {target}

RECENT CONTEXT:
{recent}

GLOSSARY:
{glossary_text}

CURRENT:
{text}"""
    return [
        {"role": "system", "content": TRANSLATION_SYSTEM},
        {"role": "user", "content": user},
    ]


def clean_translation(result: str) -> str:
    """Remove common chat labels from local model responses."""

    value = str(result or "").strip()
    for prefix in ("A:", "B:", "C:", "D:"):
        if value.startswith(prefix):
            return value[len(prefix):].strip()
    return value


class MlxTranslationBackend:
    """Lazy adapter for the existing MLX Gemma implementation."""

    name = "mlx"

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: Any = None
        self._tokenizer: Any = None
        self._load_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._tokenizer is not None

    async def translate(
        self,
        text: str,
        context: Iterable[Any] | None,
        glossary: Iterable[Any] | None,
        source: str,
        target: str,
    ) -> str:
        async with self._load_lock:
            if not self.loaded:
                try:
                    from mlx_lm import load, stream_generate  # type: ignore[import-not-found]
                    from mlx_lm.sample_utils import make_sampler  # type: ignore[import-not-found]
                except ImportError as exc:
                    raise RuntimeError("macOS MLX translation dependencies are missing.") from exc
                self._model, self._tokenizer = await asyncio.to_thread(load, self.model_name)

        messages = build_translation_messages(text, context, glossary, source, target)
        async with self._inference_lock:
            return await asyncio.to_thread(
                _translate_mlx_sync,
                self._model,
                self._tokenizer,
                messages,
                stream_generate,
                make_sampler,
            )


def _translate_mlx_sync(model: Any, tokenizer: Any, messages: list[dict[str, str]], stream_generate: Any, make_sampler: Any) -> str:
    try:
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)

    chunks = []
    for response in stream_generate(
        model,
        tokenizer,
        prompt=prompt,
        max_tokens=96,
        sampler=make_sampler(temp=0.0),
    ):
        piece = getattr(response, "text", "")
        if piece:
            chunks.append(piece)
    return clean_translation("".join(chunks))


class LlamaCppTranslationBackend:
    """Call a local llama.cpp server through its OpenAI-compatible endpoint."""

    name = "llamacpp"

    def __init__(self, model_name: str, url: str | None = None) -> None:
        self.model_name = model_name
        self.url = (url or os.environ.get("YTLT_TRANSLATION_URL", "http://127.0.0.1:8766")).rstrip("/")
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    async def translate(
        self,
        text: str,
        context: Iterable[Any] | None,
        glossary: Iterable[Any] | None,
        source: str,
        target: str,
    ) -> str:
        try:
            from aiohttp import ClientSession, ClientTimeout
        except ImportError as exc:
            raise RuntimeError("aiohttp is required for the Windows translation backend.") from exc

        payload = {
            "model": self.model_name,
            "messages": build_translation_messages(text, context, glossary, source, target),
            "temperature": 0.0,
            "max_tokens": 96,
            "stream": False,
        }
        timeout = ClientTimeout(total=float(os.environ.get("YTLT_TRANSLATION_TIMEOUT", "20")))
        async with ClientSession(timeout=timeout) as client:
            async with client.post(f"{self.url}/v1/chat/completions", json=payload) as response:
                if response.status >= 400:
                    raise RuntimeError(f"llama.cpp translation server returned HTTP {response.status}: {await response.text()}")
                data = await response.json()

        try:
            message = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("llama.cpp translation response did not contain choices[0].message.content") from exc
        self._loaded = True
        if isinstance(message, list):
            message = "".join(str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in message)
        return clean_translation(str(message))
