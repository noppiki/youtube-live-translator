"""Runtime-selectable local ASR and translation backends."""

from .asr import MlxQwenASRBackend, TorchQwenASRBackend
from .runtime import RuntimeMetadata, app_dir, runtime_metadata
from .translation import LlamaCppTranslationBackend, MlxTranslationBackend


def create_asr_backend(runtime: RuntimeMetadata):
    """Create the platform default ASR backend without loading model weights."""

    if runtime.asr_backend == "mlx":
        return MlxQwenASRBackend()
    return TorchQwenASRBackend()


def create_translation_backend(runtime: RuntimeMetadata, model: str):
    """Create the platform default translation backend without loading model weights."""

    if runtime.translation_backend == "mlx":
        return MlxTranslationBackend(model)
    return LlamaCppTranslationBackend(model)


__all__ = [
    "LlamaCppTranslationBackend",
    "MlxQwenASRBackend",
    "MlxTranslationBackend",
    "RuntimeMetadata",
    "TorchQwenASRBackend",
    "app_dir",
    "create_asr_backend",
    "create_translation_backend",
    "runtime_metadata",
]
