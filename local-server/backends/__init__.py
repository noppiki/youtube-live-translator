from __future__ import annotations

from typing import Any

from runtime import RuntimeProfile, profile


def get_asr_backend(current: RuntimeProfile | None = None):
    current = current or profile()
    if current.asr_backend == "mlx":
        from backends.asr_mlx_qwen import MlxQwenAsr

        return MlxQwenAsr()
    from backends.asr_torch_qwen import TorchQwenAsr

    return TorchQwenAsr()


def get_translation_backend(current: RuntimeProfile | None = None):
    current = current or profile()
    if current.translation_backend == "mlx":
        from backends.translate_mlx_gemma import MlxGemmaTranslator

        return MlxGemmaTranslator()
    from backends.translate_llamacpp import LlamaCppTranslator

    return LlamaCppTranslator()


def create_asr_session(model_id: str, current: RuntimeProfile | None = None) -> Any:
    return get_asr_backend(current).create_session(model_id)
