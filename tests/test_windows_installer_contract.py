from pathlib import Path


ROOT = Path(__file__).parents[1]
INSTALLER = (ROOT / "scripts/install-windows.ps1").read_text(encoding="utf-8")
START = (ROOT / "scripts/start-windows.ps1").read_text(encoding="utf-8")
MACOS = (ROOT / "scripts/install-macos.sh").read_text(encoding="utf-8")
LAUNCHER = (ROOT / "native-host/launcher.py").read_text(encoding="utf-8")


def test_installer_searches_releases_with_real_windows_assets():
    assert "releases?per_page=20" in INSTALLER
    assert "releases/latest" not in INSTALLER
    assert "bin-win-cpu-x64" in INSTALLER
    assert "bin-win-vulkan-x64" in INSTALLER
    assert "bin-win-cuda-12\\.4-x64" in INSTALLER


def test_installer_downloads_plamo_q4km_and_discovers_result():
    assert "pfnet/plamo-3-translate-2b-GGUF" in INSTALLER
    assert "plamo-3-translate-2b-Q4_K_M.gguf" in INSTALLER
    assert "models\\plamo-3-translate-2b-GGUF" in INSTALLER
    assert 'Get-ChildItem -LiteralPath $ModelDirectory -Filter "*.gguf"' in INSTALLER
    assert "*q4_0*.gguf" not in INSTALLER
    assert "gemma" not in INSTALLER.lower()
    for name in ("__init__.py", "asr.py", "runtime.py", "translation.py"):
        assert name in INSTALLER


def test_start_and_launcher_use_the_plamo_directory():
    assert "models\\plamo-3-translate-2b-GGUF" in START
    assert 'else { "plamo-3-translate-2b-Q4_K_M" }' in START
    assert "gemma" not in START.lower()
    assert "--jinja" not in START
    assert "models/plamo-3-translate-2b-GGUF" in LAUNCHER
    assert "gemma" not in LAUNCHER.lower()
    assert "--jinja" not in LAUNCHER


def test_macos_installer_copies_backends_and_warms_plamo():
    assert "local-server/backends/" in MACOS
    for name in ("__init__.py", "asr.py", "runtime.py", "translation.py"):
        assert name in MACOS
    assert "pfnet/plamo-3-translate-2b-MLX-4bit" in MACOS
    assert "trust_remote_code=True" in MACOS
    assert 'tokenizer_config={"trust_remote_code": True}' in MACOS
    assert "gemma" not in MACOS.lower()
    assert "DreamFoundries" not in MACOS


def test_current_ui_names_plamo_not_gemma():
    files = [
        ROOT / "popup/popup.html",
        ROOT / "popup/popup.js",
        ROOT / "offscreen/offscreen.js",
        ROOT / "manifest.json",
        ROOT / "README.md",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "gemma" not in text.lower(), path.name
    offscreen = (ROOT / "offscreen/offscreen.js").read_text(encoding="utf-8")
    assert "translateWithLocalModel" in offscreen
    assert "localSources" in offscreen
    assert "translateWithLocalGemma" not in offscreen
    popup = (ROOT / "popup/popup.html").read_text(encoding="utf-8")
    assert "pfnet/plamo-3-translate-2b-MLX-4bit" in popup
    assert "用語 => 訳語" in popup
    popup_js = (ROOT / "popup/popup.js").read_text(encoding="utf-8")
    assert "pfnet/plamo-3-translate-2b-GGUF" in popup_js


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


def test_windows_server_uses_python_with_faulthandler_logging():
    start = (Path(__file__).parents[1] / "scripts/start-windows.ps1").read_text(encoding="utf-8")
    assert '.venv\\Scripts\\python.exe' in start
    assert 'PYTHONFAULTHANDLER' in start
    assert '@("-X", "faulthandler", "-u", $server)' in start
    assert 'pythonw.exe' not in start
