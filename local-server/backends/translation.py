"""PFML3 prompts for PLaMo 3 Translate, completed by MLX or llama.cpp."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Iterable


MLX_REPO = "pfnet/plamo-3-translate-2b-MLX-4bit"
GGUF_REPO = "pfnet/plamo-3-translate-2b-GGUF"
GGUF_FILE = "plamo-3-translate-2b-Q4_K_M.gguf"
GGUF_DIR = "plamo-3-translate-2b-GGUF"
GGUF_SHORT = "plamo-3-translate-2b-Q4_K_M"

TEMPERATURE = 0.0
MAX_TOKENS = 96
OUTPUT_FORM = "plain"
CONTEXT_TURNS = 3
PRESERVE_PREFIX = "Terms to leave unchanged: "
_STOP_MARKERS = ("<|plamo:tag|>", "<|plamo:bos|>")
_CONTROL_TOKENS = _STOP_MARKERS + (
    "<|plamo:msg|>",
    "<|plamo:key|>",
    "<|plamo:val|>",
    "<|plamo:index|>",
    "<|plamo:item|>",
)
_SPEAKER_PREFIXES = ("A:", "B:", "C:", "D:")
_UNSUPPORTED_PAIR = (
    "Local smart translation supports English/Korean/Chinese/Spanish/French/German → Japanese."
)


@dataclass(frozen=True)
class SourceLanguage:
    plamo: str
    aliases: frozenset[str]
    health_code: str | None


SOURCE_LANGUAGES: tuple[SourceLanguage, ...] = (
    SourceLanguage("en", frozenset({"en", "english", "en-us", "en-gb"}), "en"),
    SourceLanguage("ko", frozenset({"ko", "kr"}), "ko"),
    SourceLanguage("zh-hans", frozenset({"zh", "zh-cn", "zh-hans"}), "zh"),
    SourceLanguage("zh-hant", frozenset({"zh-tw", "zh-hant"}), None),
    SourceLanguage("es", frozenset({"es"}), "es"),
    SourceLanguage("fr", frozenset({"fr"}), "fr"),
    SourceLanguage("de", frozenset({"de"}), "de"),
)


def _alias_map(languages: tuple[SourceLanguage, ...]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for language in languages:
        for alias in language.aliases:
            key = alias.strip().lower()
            if key in mapping:
                raise RuntimeError(f"duplicate source alias {key}")
            mapping[key] = language.plamo
    return mapping


def _health_codes(languages: tuple[SourceLanguage, ...]) -> tuple[str, ...]:
    codes: list[str] = []
    for language in languages:
        code = language.health_code
        if code and code not in codes:
            codes.append(code)
    return tuple(codes)


_ALIAS_TO_PLAMO = _alias_map(SOURCE_LANGUAGES)
HEALTH_SOURCE_CODES = _health_codes(SOURCE_LANGUAGES)


@dataclass(frozen=True)
class GlossaryPair:
    source: str
    target: str


@dataclass(frozen=True)
class Pfml3Prompt:
    text: str

    def __post_init__(self) -> None:
        if "\n" in self.text or "\r" in self.text:
            raise ValueError("PFML3 prompt must be a single line")
        if self.text.startswith("<|plamo:bos|>"):
            raise ValueError("PFML3 prompt must not include the bos token")
        if not self.text.startswith("<|plamo:tag|>dataset<|plamo:msg|>translation"):
            raise ValueError("PFML3 prompt must start with dataset=translation")
        if not self.text.endswith("<|plamo:msg|>"):
            raise ValueError("PFML3 prompt must end with an empty output message")


def _plamo_source(source: str) -> str | None:
    return _ALIAS_TO_PLAMO.get(str(source).strip().lower())


def _japanese_source(source: str, target: str) -> str | None:
    code = _plamo_source(source)
    if code is None or str(target).strip().lower() != "ja":
        return None
    return code


def pair_supported(source: str, target: str) -> bool:
    return _japanese_source(source, target) is not None


def _plain(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    for token in _CONTROL_TOKENS:
        text = text.replace(token, "")
    return text.replace("\r", " ").replace("\n", " ").strip()


def _split_glossary(lines: Iterable[Any] | None) -> tuple[tuple[GlossaryPair, ...], tuple[str, ...]]:
    pairs: list[GlossaryPair] = []
    preserved: list[str] = []
    seen_pairs: set[str] = set()
    seen_preserved: set[str] = set()
    for raw in lines or ():
        text = _plain(raw)
        if not text:
            continue
        if "=>" in text:
            source, target = (part.strip() for part in text.split("=>", 1))
            if source and target:
                if source not in seen_pairs:
                    seen_pairs.add(source)
                    pairs.append(GlossaryPair(source, target))
                continue
        if text not in seen_preserved:
            seen_preserved.add(text)
            preserved.append(text)
    return tuple(pairs), tuple(preserved)


def _context_message(context: Iterable[Any] | None, preserved: tuple[str, ...]) -> str | None:
    lines: list[str] = []
    for raw in list(context or ())[-CONTEXT_TURNS:]:
        text = _plain(raw)
        if text:
            lines.append(text)
    parts: list[str] = []
    if lines:
        parts.append(" ".join(lines))
    if preserved:
        parts.append(PRESERVE_PREFIX + ", ".join(preserved))
    if not parts:
        return None
    return " ".join(parts)


def build_pfml3(
    text: str,
    context: Iterable[Any] | None,
    glossary: Iterable[Any] | None,
    source: str,
    target: str,
) -> Pfml3Prompt:
    source_code = _japanese_source(source, target)
    if source_code is None:
        raise ValueError(_UNSUPPORTED_PAIR)
    pairs, preserved = _split_glossary(glossary)
    parts = ["<|plamo:tag|>dataset<|plamo:msg|>translation"]
    context_message = _context_message(context, preserved)
    if context_message:
        parts.append(f"<|plamo:tag|>context<|plamo:msg|>{context_message}")
    if pairs:
        rendered = "".join(
            f"<|plamo:index|>{pair.source}<|plamo:item|>{pair.target}" for pair in pairs
        )
        parts.append(f"<|plamo:tag|>glossary{rendered}")
    parts.append(
        f"<|plamo:tag|>input<|plamo:key|>lang<|plamo:val|>{source_code}<|plamo:msg|>{_plain(text)}"
    )
    parts.append(
        "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja"
        f"<|plamo:key|>form<|plamo:val|>{OUTPUT_FORM}<|plamo:msg|>"
    )
    return Pfml3Prompt("".join(parts))


def clean_translation(result: str) -> str:
    value = str(result or "").strip()
    cut = len(value)
    for marker in _STOP_MARKERS:
        index = value.find(marker)
        if index != -1 and index < cut:
            cut = index
    value = value[:cut].strip()
    for prefix in _SPEAKER_PREFIXES:
        if value.startswith(prefix):
            return value[len(prefix):].strip()
    return value


def _stop_ids(tokenizer: Any) -> frozenset[int]:
    encode = getattr(tokenizer, "encode", None)
    if encode is None:
        return frozenset()
    found: set[int] = set()
    for marker in _STOP_MARKERS:
        try:
            encoded = encode(marker, add_special_tokens=False)
        except TypeError:
            encoded = encode(marker)
        ids = getattr(encoded, "ids", encoded)
        if isinstance(ids, (list, tuple)) and len(ids) == 1 and isinstance(ids[0], int):
            found.add(ids[0])
    return frozenset(found)


def _completion_text(payload: Any) -> str:
    try:
        text = payload["choices"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("llama.cpp translation response did not contain choices[0].text") from exc
    if not isinstance(text, str):
        raise RuntimeError("llama.cpp translation response did not contain choices[0].text")
    return text


def _generate_mlx(
    model: Any,
    tokenizer: Any,
    stream_generate: Any,
    make_sampler: Any,
    stop_ids: frozenset[int],
    prompt: str,
) -> str:
    chunks: list[str] = []
    for response in stream_generate(
        model,
        tokenizer,
        prompt,
        max_tokens=MAX_TOKENS,
        sampler=make_sampler(temp=TEMPERATURE),
    ):
        token = getattr(response, "token", None)
        if isinstance(token, int) and token in stop_ids:
            break
        piece = getattr(response, "text", "")
        if not piece:
            continue
        chunks.append(piece)
        joined = "".join(chunks)
        if any(marker in joined for marker in _STOP_MARKERS):
            break
    return "".join(chunks)


class Pfml3Translator:
    name: str

    async def translate(
        self,
        text: str,
        context: Iterable[Any] | None,
        glossary: Iterable[Any] | None,
        source: str,
        target: str,
    ) -> str:
        prompt = build_pfml3(text, context, glossary, source, target)
        return clean_translation(await self._complete(prompt))

    async def _complete(self, prompt: Pfml3Prompt) -> str:
        raise NotImplementedError


class MlxTranslationBackend(Pfml3Translator):
    name = "mlx"

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: Any = None
        self._tokenizer: Any = None
        self._stream_generate: Any = None
        self._make_sampler: Any = None
        self._stop_ids: frozenset[int] = frozenset()
        self._ready = False
        self._load_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self._ready

    async def _ensure_loaded(self) -> None:
        async with self._load_lock:
            if self._ready:
                return
            try:
                from mlx_lm import load, stream_generate  # type: ignore[import-not-found]
                from mlx_lm.sample_utils import make_sampler  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError("macOS MLX translation dependencies are missing.") from exc
            self._stream_generate = stream_generate
            self._make_sampler = make_sampler
            tokenizer_config = {"trust_remote_code": True}
            try:
                loaded = await asyncio.to_thread(
                    load,
                    self.model_name,
                    trust_remote_code=True,
                    tokenizer_config=tokenizer_config,
                )
            except TypeError:
                # Older mlx_lm rejects the top-level flag and still accepts it
                # inside tokenizer_config.
                loaded = await asyncio.to_thread(
                    load,
                    self.model_name,
                    tokenizer_config=tokenizer_config,
                )
            self._model, self._tokenizer = loaded
            self._stop_ids = _stop_ids(self._tokenizer)
            self._ready = True

    async def _complete(self, prompt: Pfml3Prompt) -> str:
        await self._ensure_loaded()
        async with self._inference_lock:
            return await asyncio.to_thread(
                _generate_mlx,
                self._model,
                self._tokenizer,
                self._stream_generate,
                self._make_sampler,
                self._stop_ids,
                prompt.text,
            )


class LlamaCppTranslationBackend(Pfml3Translator):
    name = "llamacpp"

    def __init__(self, model_name: str, url: str | None = None) -> None:
        self.model_name = model_name
        self.url = (url or os.environ.get("YTLT_TRANSLATION_URL", "http://127.0.0.1:8766")).rstrip("/")
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    async def _complete(self, prompt: Pfml3Prompt) -> str:
        try:
            from aiohttp import ClientSession, ClientTimeout
        except ImportError as exc:
            raise RuntimeError("aiohttp is required for the Windows translation backend.") from exc

        payload = {
            "model": self.model_name,
            "prompt": prompt.text,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "stream": False,
            "stop": list(_STOP_MARKERS),
        }
        timeout = ClientTimeout(total=float(os.environ.get("YTLT_TRANSLATION_TIMEOUT", "20")))
        async with ClientSession(timeout=timeout) as client:
            async with client.post(f"{self.url}/v1/completions", json=payload) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise RuntimeError(
                        f"llama.cpp translation server returned HTTP {response.status}: {body}"
                    )
                data = await response.json()
        text = _completion_text(data)
        self._loaded = True
        return text
