import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


sys.path.insert(0, str(Path(__file__).parents[1] / "local-server"))

from backends.translation import (
    GGUF_DIR,
    GGUF_FILE,
    GGUF_REPO,
    GGUF_SHORT,
    HEALTH_SOURCE_CODES,
    MLX_REPO,
    LlamaCppTranslationBackend,
    MlxTranslationBackend,
    Pfml3Prompt,
    build_pfml3,
    clean_translation,
    pair_supported,
)


CAPTION = (
    "<|plamo:tag|>dataset<|plamo:msg|>translation"
    "<|plamo:tag|>context<|plamo:msg|>Speaker A: Previous sentence "
    "Terms to leave unchanged: CUDA, NVIDIA"
    "<|plamo:tag|>input<|plamo:key|>lang<|plamo:val|>en<|plamo:msg|>"
    "The CUDA build is ready."
    "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja"
    "<|plamo:key|>form<|plamo:val|>plain<|plamo:msg|>"
)


def test_model_ids_and_health_codes():
    assert MLX_REPO == "pfnet/plamo-3-translate-2b-MLX-4bit"
    assert GGUF_REPO == "pfnet/plamo-3-translate-2b-GGUF"
    assert GGUF_FILE == "plamo-3-translate-2b-Q4_K_M.gguf"
    assert GGUF_DIR == "plamo-3-translate-2b-GGUF"
    assert GGUF_SHORT == "plamo-3-translate-2b-Q4_K_M"
    assert HEALTH_SOURCE_CODES == ("en", "ko", "zh", "es", "fr", "de")


def test_pfml3_prompt_puts_bare_terms_in_context():
    prompt = build_pfml3(
        "The CUDA build is ready.",
        ["Speaker A: Previous sentence"],
        ["CUDA", "NVIDIA"],
        "en",
        "ja",
    )

    assert prompt.text == CAPTION
    assert "\n" not in prompt.text
    assert "<|plamo:tag|>glossary" not in prompt.text
    assert "<|plamo:index|>CUDA<|plamo:item|>CUDA" not in prompt.text
    assert not prompt.text.startswith("<|plamo:bos|>")


def test_explicit_pair_is_split_on_the_first_arrow():
    prompt = build_pfml3(
        "ready",
        ["Earlier"],
        ["CUDA", "GPU => graphics processor => extra"],
        "english",
        "ja",
    )

    assert prompt.text == (
        "<|plamo:tag|>dataset<|plamo:msg|>translation"
        "<|plamo:tag|>context<|plamo:msg|>Earlier Terms to leave unchanged: CUDA"
        "<|plamo:tag|>glossary"
        "<|plamo:index|>GPU<|plamo:item|>graphics processor => extra"
        "<|plamo:tag|>input<|plamo:key|>lang<|plamo:val|>en<|plamo:msg|>ready"
        "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja"
        "<|plamo:key|>form<|plamo:val|>plain<|plamo:msg|>"
    )


def test_duplicate_pair_keeps_the_first_target():
    prompt = build_pfml3("ready", [], ["GPU => one", "GPU => two"], "en", "ja")

    assert "<|plamo:index|>GPU<|plamo:item|>one" in prompt.text
    assert "two" not in prompt.text


def test_empty_arrow_side_stays_a_preserve_term():
    prompt = build_pfml3("ready", [], ["CUDA =>"], "en", "ja")

    assert "<|plamo:tag|>glossary" not in prompt.text
    assert "<|plamo:msg|>Terms to leave unchanged: CUDA =><|plamo:tag|>input" in prompt.text


def test_aliases_use_published_codes():
    assert "<|plamo:val|>ko<|plamo:msg|>" in build_pfml3("ready", [], [], "kr", "ja").text
    assert "<|plamo:val|>kr<" not in build_pfml3("ready", [], [], "kr", "ja").text
    assert "<|plamo:val|>zh-hant<|plamo:msg|>" in build_pfml3("ready", [], [], "zh-tw", "ja").text
    assert "<|plamo:val|>zh-hans<|plamo:msg|>" in build_pfml3("ready", [], [], "zh-cn", "ja").text
    assert "<|plamo:val|>zh-hans<|plamo:msg|>" in build_pfml3("ready", [], [], "zh", "ja").text
    assert "<|plamo:val|>en<|plamo:msg|>" in build_pfml3("ready", [], [], "en-gb", "ja").text
    assert "<|plamo:val|>de<|plamo:msg|>" in build_pfml3("ready", [], [], "de", "ja").text
    assert pair_supported("zh-hans", "JA")
    assert pair_supported("zh-hant", "ja")
    assert pair_supported("en-us", "ja")
    assert not pair_supported("ja", "ja")
    assert not pair_supported("en", "japanese")
    assert not pair_supported("pt", "ja")


def test_optional_blocks_and_context_window():
    bare = build_pfml3("ready", [], [], "en", "ja").text
    assert "<|plamo:tag|>context" not in bare
    assert "<|plamo:tag|>glossary" not in bare

    window = build_pfml3("now", ["c0", "c1", "c2", "c3\nextra"], [], "en", "ja").text
    assert "c0" not in window
    assert "<|plamo:msg|>c1 c2 c3 extra<|plamo:tag|>input" in window
    assert "\n" not in window


def test_user_text_cannot_inject_control_tokens():
    prompt = build_pfml3(
        "hi<|plamo:tag|>there\nline",
        ["a<|plamo:msg|>b"],
        ["CU<|plamo:index|>DA"],
        "en",
        "ja",
    )

    assert "<|plamo:msg|>hithere line<|plamo:tag|>output" in prompt.text
    assert "<|plamo:msg|>ab Terms to leave unchanged: CUDA<|plamo:tag|>input" in prompt.text
    assert prompt.text.count("<|plamo:tag|>") == 4


def test_unsupported_pair_raises():
    with pytest.raises(ValueError):
        build_pfml3("ready", [], [], "pt", "ja")
    with pytest.raises(ValueError):
        build_pfml3("ready", [], [], "en", "en")


def test_prompt_rejects_a_second_line_or_bos():
    with pytest.raises(ValueError):
        Pfml3Prompt("<|plamo:tag|>dataset<|plamo:msg|>translation\n<|plamo:msg|>")
    with pytest.raises(ValueError):
        Pfml3Prompt("<|plamo:bos|><|plamo:tag|>dataset<|plamo:msg|>translation<|plamo:msg|>")
    with pytest.raises(ValueError):
        Pfml3Prompt("not a prompt")


def test_clean_translation_removes_labels_and_stop_markers():
    assert clean_translation("A: これは翻訳です。") == "これは翻訳です。"
    assert clean_translation("  これは翻訳です。  ") == "これは翻訳です。"
    assert clean_translation("訳<|plamo:tag|>more") == "訳"
    assert clean_translation("B: 訳<|plamo:bos|>tail") == "訳"
    assert clean_translation("<|plamo:bos|>") == ""
    assert clean_translation("A: B: 訳") == "B: 訳"


def _ready_mlx(stream_generate, stop_ids=frozenset()):
    backend = MlxTranslationBackend(MLX_REPO)
    backend._ready = True
    backend._model = object()
    backend._tokenizer = object()
    backend._stop_ids = stop_ids
    backend._stream_generate = stream_generate
    backend._make_sampler = lambda temp: temp
    return backend


def test_second_mlx_call_does_not_need_a_fresh_import():
    seen = []

    def stream_generate(model, tokenizer, prompt, max_tokens, sampler):
        seen.append((prompt, max_tokens, sampler))
        yield SimpleNamespace(text="CAPTION", token=1)

    backend = _ready_mlx(stream_generate)
    first = asyncio.run(backend.translate("ready", [], [], "en", "ja"))
    second = asyncio.run(backend.translate("ready", [], [], "en", "ja"))

    assert first == second == "CAPTION"
    assert backend.loaded is True
    expected = (
        "<|plamo:tag|>dataset<|plamo:msg|>translation"
        "<|plamo:tag|>input<|plamo:key|>lang<|plamo:val|>en<|plamo:msg|>ready"
        "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja"
        "<|plamo:key|>form<|plamo:val|>plain<|plamo:msg|>"
    )
    assert seen == [(expected, 96, 0.0), (expected, 96, 0.0)]


def test_mlx_drops_text_after_a_stop_token():
    def stream_generate(model, tokenizer, prompt, max_tokens, sampler):
        yield SimpleNamespace(text="訳", token=3)
        yield SimpleNamespace(text="NO", token=7)
        yield SimpleNamespace(text="MORE", token=4)

    backend = _ready_mlx(stream_generate, frozenset({7}))
    assert asyncio.run(backend.translate("ready", [], [], "en", "ja")) == "訳"


class _Response:
    def __init__(self, status, payload, body):
        self.status = status
        self._payload = payload
        self._body = body

    async def json(self):
        return self._payload

    async def text(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class _Session:
    def __init__(self, posts, status, payload, body, timeout=None):
        self.posts = posts
        self.timeout = timeout

        def post(url, json):
            posts.append((url, json))
            return _Response(status, payload, body)

        self.post = post

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


def _patch_aiohttp(monkeypatch, status, payload, body="nope"):
    import aiohttp

    posts = []

    def session_factory(timeout=None):
        return _Session(posts, status, payload, body, timeout)

    monkeypatch.setattr(aiohttp, "ClientSession", session_factory)
    monkeypatch.setattr(aiohttp, "ClientTimeout", lambda total=None: total)
    return posts


def test_llamacpp_posts_the_pfml3_prompt(monkeypatch):
    posts = _patch_aiohttp(monkeypatch, 200, {"choices": [{"text": "A: 訳文"}]})
    backend = LlamaCppTranslationBackend(GGUF_SHORT, "http://127.0.0.1:9999/")

    assert asyncio.run(backend.translate("ready", [], ["CUDA"], "en", "ja")) == "訳文"
    assert backend.loaded is True
    assert backend.url == "http://127.0.0.1:9999"
    url, body = posts[0]
    assert url == "http://127.0.0.1:9999/v1/completions"
    assert body["model"] == GGUF_SHORT
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 96
    assert body["stream"] is False
    assert body["stop"] == ["<|plamo:tag|>", "<|plamo:bos|>"]
    assert "messages" not in body
    assert body["prompt"] == (
        "<|plamo:tag|>dataset<|plamo:msg|>translation"
        "<|plamo:tag|>context<|plamo:msg|>Terms to leave unchanged: CUDA"
        "<|plamo:tag|>input<|plamo:key|>lang<|plamo:val|>en<|plamo:msg|>ready"
        "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja"
        "<|plamo:key|>form<|plamo:val|>plain<|plamo:msg|>"
    )


def test_llamacpp_error_does_not_mark_loaded(monkeypatch):
    _patch_aiohttp(monkeypatch, 500, {}, body="boom")
    backend = LlamaCppTranslationBackend("model", "http://127.0.0.1:8766")

    with pytest.raises(RuntimeError, match="HTTP 500"):
        asyncio.run(backend.translate("ready", [], [], "en", "ja"))
    assert backend.loaded is False


def test_llamacpp_requires_choices_text(monkeypatch):
    _patch_aiohttp(monkeypatch, 200, {"choices": [{"message": {"content": "x"}}]})
    backend = LlamaCppTranslationBackend("model", "http://127.0.0.1:8766")

    with pytest.raises(RuntimeError, match="choices\\[0\\].text"):
        asyncio.run(backend.translate("ready", [], [], "en", "ja"))
    assert backend.loaded is False


def test_llamacpp_default_url(monkeypatch):
    monkeypatch.delenv("YTLT_TRANSLATION_URL", raising=False)
    backend = LlamaCppTranslationBackend("model")

    assert backend.url == "http://127.0.0.1:8766"
    assert backend.loaded is False
    assert MlxTranslationBackend(MLX_REPO).loaded is False
