from __future__ import annotations

from backends.translate_base import TRANSLATION_SYSTEM, build_translation_user, strip_choice_prefix
from runtime import profile


class MlxGemmaTranslator:
    def __init__(self):
        self._model = None
        self._tokenizer = None

    @property
    def model_id(self) -> str:
        return profile().translation_model

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._tokenizer is not None

    def _load(self):
        if self.loaded:
            return
        from mlx_lm import load as mlx_load

        self._model, self._tokenizer = mlx_load(self.model_id)

    def translate(self, text: str, context, glossary, source: str, target: str) -> str:
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler

        self._load()
        user = build_translation_user(text, context, glossary, source, target)
        messages = [
            {"role": "system", "content": TRANSLATION_SYSTEM},
            {"role": "user", "content": user},
        ]
        try:
            prompt = self._tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            prompt = self._tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )

        chunks = []
        for response in stream_generate(
            self._model,
            self._tokenizer,
            prompt=prompt,
            max_tokens=96,
            sampler=make_sampler(temp=0.0),
        ):
            piece = getattr(response, "text", "")
            if piece:
                chunks.append(piece)
        return strip_choice_prefix("".join(chunks))
