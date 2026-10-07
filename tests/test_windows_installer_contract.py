from pathlib import Path


INSTALLER = (Path(__file__).parents[1] / "scripts/install-windows.ps1").read_text()


def test_installer_searches_releases_with_real_windows_assets():
    assert "releases?per_page=20" in INSTALLER
    assert "releases/latest" not in INSTALLER
    assert "bin-win-cpu-x64" in INSTALLER
    assert "bin-win-vulkan-x64" in INSTALLER
    assert "bin-win-cuda-12\\.4-x64" in INSTALLER


def test_installer_uses_actual_gemma_q4_filename_pattern_and_discovers_result():
    assert "*q4_0*.gguf" in INSTALLER
    assert 'Get-ChildItem -LiteralPath $ModelDirectory -Filter "*.gguf"' in INSTALLER
    assert "gemma-4-E4B-it-qat-q4_0.gguf" not in INSTALLER


def test_installer_sets_native_host_default_registry_value_and_accelerator():
    assert "Set-Item -Path $keyPath -Value $ManifestPath" in INSTALLER
    assert 'SetEnvironmentVariable("YTLT_ACCELERATOR", $Accelerator, "User")' in INSTALLER
