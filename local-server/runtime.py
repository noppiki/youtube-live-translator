from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paths import app_dir, detect_os, runtime_state_path

MLX_MODELS = {
    "balanced": {
        "id": "moona3k/mlx-qwen3-asr-0.6b-4bit",
        "label": "Qwen3-ASR 0.6B 4-bit",
    },
    "accuracy": {
        "id": "moona3k/mlx-qwen3-asr-1.7b-4bit",
        "label": "Qwen3-ASR 1.7B 4-bit",
    },
}

TORCH_MODELS = {
    "balanced": {
        "id": "Qwen/Qwen3-ASR-0.6B-hf",
        "label": "Qwen3-ASR 0.6B",
    },
    "accuracy": {
        "id": "Qwen/Qwen3-ASR-1.7B-hf",
        "label": "Qwen3-ASR 1.7B",
    },
}

MODEL_ALIASES = {
    "moona3k/mlx-qwen3-asr-0.6b-4bit": "Qwen/Qwen3-ASR-0.6B-hf",
    "moona3k/mlx-qwen3-asr-1.7b-4bit": "Qwen/Qwen3-ASR-1.7B-hf",
    "Qwen/Qwen3-ASR-0.6B-hf": "moona3k/mlx-qwen3-asr-0.6b-4bit",
    "Qwen/Qwen3-ASR-1.7B-hf": "moona3k/mlx-qwen3-asr-1.7b-4bit",
}

MLX_TRANSLATION_MODEL = "DreamFoundries/gemma-4-E4B-it-4bit"
LLAMACPP_TRANSLATION_MODEL = "google/gemma-4-E4B-it-qat-q4_0-gguf"
LLAMACPP_GGUF_NAME = "gemma-4-E4B_q4_0-it.gguf"


@dataclass(frozen=True)
class RuntimeProfile:
    os: str
    asr_backend: str
    translation_backend: str
    accelerator: str
    diarization_available: bool
    default_model: str
    translation_model: str
    models: dict[str, dict[str, str]]
    performance_warning: str | None
    app_dir: Path
    fluid_bridge: Path
    llama_host: str
    llama_port: int


def _read_state() -> dict[str, Any]:
    path = runtime_state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_runtime_state(values: dict[str, Any]) -> Path:
    path = runtime_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = _read_state()
    current.update(values)
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return path


def _has_nvidia() -> bool:
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0 and "GPU" in (result.stdout or "")


def _detect_accelerator(os_name: str, state: dict[str, Any]) -> str:
    override = os.environ.get("YTLT_ACCELERATOR", "").strip().lower()
    if override in {"metal", "cuda", "vulkan", "cpu"}:
        return override
    stored = str(state.get("accelerator") or "").strip().lower()
    if stored in {"metal", "cuda", "vulkan", "cpu"}:
        return stored
    if os_name == "macos":
        return "metal"
    if _has_nvidia():
        return "cuda"
    return "cpu"


def _performance_warning(os_name: str, accelerator: str) -> str | None:
    if os_name != "windows":
        return None
    if accelerator == "cpu":
        return "CPU only. Live captions may lag. A CUDA or Vulkan GPU is recommended."
    if accelerator == "vulkan":
        return "ASR runs on CPU. Translation uses Vulkan. NVIDIA CUDA is faster for both."
    return None


def profile() -> RuntimeProfile:
    os_name = detect_os()
    state = _read_state()
    root = app_dir()
    asr_override = os.environ.get("YTLT_ASR_BACKEND", "").strip().lower()
    translate_override = os.environ.get("YTLT_TRANSLATE_BACKEND", "").strip().lower()

    if os_name == "macos":
        asr_backend = asr_override or "mlx"
        translation_backend = translate_override or "mlx"
        models = MLX_MODELS
        default_model = os.environ.get("YTLT_MODEL", MLX_MODELS["balanced"]["id"])
        translation_model = os.environ.get("YTLT_TRANSLATION_MODEL", MLX_TRANSLATION_MODEL)
        fluid = Path(os.environ.get("YTLT_FLUID_BRIDGE", root / "bin/fluid-bridge"))
        diarization = fluid.exists()
    else:
        asr_backend = asr_override or "torch"
        translation_backend = translate_override or "llamacpp"
        models = TORCH_MODELS
        default_model = os.environ.get("YTLT_MODEL", TORCH_MODELS["balanced"]["id"])
        translation_model = os.environ.get("YTLT_TRANSLATION_MODEL", LLAMACPP_TRANSLATION_MODEL)
        fluid = Path(os.environ.get("YTLT_FLUID_BRIDGE", root / "bin/fluid-bridge"))
        diarization = False

    if asr_backend not in {"mlx", "torch"}:
        asr_backend = "mlx" if os_name == "macos" else "torch"
    if translation_backend not in {"mlx", "llamacpp"}:
        translation_backend = "mlx" if os_name == "macos" else "llamacpp"

    accelerator = _detect_accelerator(os_name, state)
    return RuntimeProfile(
        os="macos" if os_name == "macos" else "windows" if os_name == "windows" else os_name,
        asr_backend=asr_backend,
        translation_backend=translation_backend,
        accelerator=accelerator,
        diarization_available=diarization,
        default_model=default_model,
        translation_model=translation_model,
        models=models,
        performance_warning=_performance_warning(os_name, accelerator),
        app_dir=root,
        fluid_bridge=fluid,
        llama_host=os.environ.get("YTLT_LLAMA_HOST", "127.0.0.1"),
        llama_port=int(os.environ.get("YTLT_LLAMA_PORT", "8766")),
    )


def known_model_ids(current: RuntimeProfile | None = None) -> set[str]:
    current = current or profile()
    ids = {item["id"] for item in current.models.values()}
    ids.update(MODEL_ALIASES)
    ids.update(MODEL_ALIASES.values())
    return ids


def resolve_model_id(model_id: str | None, current: RuntimeProfile | None = None) -> str:
    current = current or profile()
    requested = (model_id or current.default_model).strip()
    catalog_ids = {item["id"] for item in current.models.values()}
    if requested in catalog_ids:
        return requested
    alias = MODEL_ALIASES.get(requested)
    if alias and alias in catalog_ids:
        return alias
    if requested in catalog_ids or requested == current.default_model:
        return requested
    raise ValueError("Unsupported local model")


def llama_binary(current: RuntimeProfile | None = None) -> Path:
    current = current or profile()
    state = _read_state()
    stored = str(state.get("llama_bin") or "").strip()
    if stored:
        return Path(stored)
    name = "llama-server.exe" if current.os == "windows" else "llama-server"
    return current.app_dir / "bin" / name


def llama_model_path(current: RuntimeProfile | None = None) -> Path:
    current = current or profile()
    state = _read_state()
    stored = str(state.get("translation_model_path") or "").strip()
    if stored:
        return Path(stored)
    return current.app_dir / "models" / LLAMACPP_GGUF_NAME
