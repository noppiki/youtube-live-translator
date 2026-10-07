from pathlib import Path


INSTALLER = (Path(__file__).parents[1] / "scripts/install-windows.ps1").read_text(encoding="utf-8")


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


def test_torch_accelerator_probe_cannot_abort_installer_on_native_stderr():
    source = INSTALLER
    assert '$previousErrorActionPreference = $ErrorActionPreference' in source
    assert '$ErrorActionPreference = "Continue"' in source
    assert '$probeExitCode = $LASTEXITCODE' in source
    assert 'PyTorch accelerator probe failed; continuing with Vulkan/CPU detection.' in source


def test_installer_prefers_cuda_pytorch_on_nvidia_windows():
    assert 'function Test-NvidiaGpu' in INSTALLER
    assert 'Get-CimInstance Win32_VideoController' in INSTALLER
    assert 'https://download.pytorch.org/whl/cu128' in INSTALLER
    assert 'Install-PyTorch $Uv $Python' in INSTALLER
    dependency_block = INSTALLER.split('Write-Step "Creating/updating isolated Python 3.12 environment"', 1)[1]
    assert '"torch>=2.7", "transformers' not in dependency_block


def test_installer_sends_python_scripts_over_stdin_not_dash_c():
    assert 'function Invoke-PythonScript' in INSTALLER
    assert '$Script | & $Python - 2>&1' in INSTALLER
    assert '$probe | & $Python - 2>$null' in INSTALLER
    assert 'Invoke-PythonScript $Python $download' in INSTALLER
    assert 'Invoke-PythonScript $Python $warmup' in INSTALLER
    assert 'Invoke-External $Python @("-c", $download)' not in INSTALLER
    assert 'Invoke-External $Python @("-c", $warmup)' not in INSTALLER
