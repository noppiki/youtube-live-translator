import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "local-server"))

from backends.runtime import app_dir, runtime_metadata


def test_app_dir_override_wins_on_every_platform(tmp_path):
    configured = tmp_path / "portable"
    result = app_dir(
        {"YTLT_APP_DIR": str(configured), "LOCALAPPDATA": "C:/Users/test/AppData/Local"},
        system_name="Windows",
        home=tmp_path / "home",
    )

    assert result == configured


def test_windows_app_dir_uses_localappdata(tmp_path):
    result = app_dir(
        {"LOCALAPPDATA": "C:/Users/test/AppData/Local"},
        system_name="Windows",
        home=tmp_path / "home",
    )

    assert result.as_posix().endswith("C:/Users/test/AppData/Local/YouTubeLiveTranslator")


def test_windows_runtime_metadata_is_model_free():
    metadata = runtime_metadata("Windows", {"YTLT_ACCELERATOR": "vulkan"})

    assert metadata.as_dict() == {
        "os": "windows",
        "asrBackend": "torch",
        "translationBackend": "llamacpp",
        "accelerator": "vulkan",
        "diarizationAvailable": False,
    }


def test_macos_runtime_keeps_mlx_and_fluid_contract(tmp_path):
    bridge = tmp_path / "fluid-bridge"
    bridge.touch()
    metadata = runtime_metadata("Darwin", {}, bridge)

    assert metadata.os == "macos"
    assert metadata.asr_backend == "mlx"
    assert metadata.translation_backend == "mlx"
    assert metadata.accelerator == "metal"
    assert metadata.diarization_available is True
