"""OS paths and runtime capability metadata.

This module deliberately has no ML imports.  It is safe to import on Windows,
macOS, and in a clean test environment before optional model dependencies are
installed.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import platform
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class RuntimeMetadata:
    """Capabilities exposed by the local service health endpoint."""

    os: str
    asr_backend: str
    translation_backend: str
    accelerator: str
    diarization_available: bool

    def as_dict(self) -> dict[str, object]:
        """Return the public JSON field names used by the extension."""

        return {
            "os": self.os,
            "asrBackend": self.asr_backend,
            "translationBackend": self.translation_backend,
            "accelerator": self.accelerator,
            "diarizationAvailable": self.diarization_available,
        }


def normalized_os(system_name: str | None = None) -> str:
    """Normalize Python platform names to the service API names."""

    system = system_name or platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"
    return system.lower() or "unknown"


def app_dir(
    environ: Mapping[str, str] | None = None,
    system_name: str | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve the per-user application directory.

    ``YTLT_APP_DIR`` is intentionally checked first so installers, tests, and
    portable deployments can keep all mutable state outside the source tree.
    """

    env = environ if environ is not None else os.environ
    configured = str(env.get("YTLT_APP_DIR", "")).strip()
    if configured:
        return Path(configured).expanduser()

    base_home = home or Path.home()
    if normalized_os(system_name) == "windows":
        local_app_data = str(env.get("LOCALAPPDATA", "")).strip()
        return Path(local_app_data) / "YouTubeLiveTranslator" if local_app_data else base_home / "AppData/Local/YouTubeLiveTranslator"
    if normalized_os(system_name) == "macos":
        return base_home / "Library/Application Support/YouTubeLiveTranslator"
    return Path(str(env.get("XDG_DATA_HOME", base_home / ".local/share"))) / "YouTubeLiveTranslator"


def detect_accelerator(
    system_name: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Choose the advertised accelerator without requiring optional packages."""

    env = environ if environ is not None else os.environ
    configured = str(env.get("YTLT_ACCELERATOR", "")).strip().lower()
    if configured in {"metal", "cuda", "vulkan", "cpu"}:
        return configured

    normalized = normalized_os(system_name)
    if normalized == "macos":
        return "metal"
    if normalized != "windows":
        return "cpu"

    # Torch is intentionally imported only for capability detection.  A
    # missing torch package must result in a CPU health response, not a server
    # import failure.
    try:
        import torch  # type: ignore[import-not-found]

        if bool(torch.cuda.is_available()):
            return "cuda"
    except (ImportError, OSError, RuntimeError):
        pass

    return "vulkan" if str(env.get("YTLT_VULKAN", "")).lower() in {"1", "true", "yes"} else "cpu"


def runtime_metadata(
    system_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    fluid_bridge: Path | None = None,
) -> RuntimeMetadata:
    """Return stable backend metadata for the current or requested OS."""

    normalized = normalized_os(system_name)
    if normalized == "macos":
        return RuntimeMetadata(
            os="macos",
            asr_backend="mlx",
            translation_backend="mlx",
            accelerator=detect_accelerator(system_name, environ),
            diarization_available=bool(fluid_bridge and fluid_bridge.exists()),
        )
    if normalized == "windows":
        return RuntimeMetadata(
            os="windows",
            asr_backend="torch",
            translation_backend="llamacpp",
            accelerator=detect_accelerator(system_name, environ),
            diarization_available=False,
        )
    return RuntimeMetadata(
        os=normalized,
        asr_backend="torch",
        translation_backend="llamacpp",
        accelerator=detect_accelerator(system_name, environ),
        diarization_available=False,
    )
