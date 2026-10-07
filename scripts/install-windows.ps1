#Requires -Version 5.1
param(
    [string]$ExtensionId = $env:YTLT_EXTENSION_ID,
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$RawBase = if ($env:YTLT_RAW_BASE) { $env:YTLT_RAW_BASE } else { "https://raw.githubusercontent.com/noppiki/youtube-live-translator/main" }
$AppDir = if ($env:YTLT_APP_DIR) { $env:YTLT_APP_DIR } else { Join-Path $env:LOCALAPPDATA "YouTubeLiveTranslator" }
$Venv = Join-Path $AppDir ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$PythonW = Join-Path $Venv "Scripts\pythonw.exe"
$BinDir = Join-Path $AppDir "bin"
$ModelDir = Join-Path $AppDir "models"
$LogDir = Join-Path $AppDir "logs"
$NativeDir = Join-Path $AppDir "native"
$TaskName = "YouTubeLiveTranslator"
$HostName = "com.noppiki.youtube_live_translator"
$GgufName = "gemma-4-E4B_q4_0-it.gguf"
$GgufRepo = "google/gemma-4-E4B-it-qat-q4_0-gguf"

$ServerFiles = @(
    "local-server/server.py",
    "local-server/paths.py",
    "local-server/runtime.py",
    "local-server/backends/__init__.py",
    "local-server/backends/asr_base.py",
    "local-server/backends/asr_mlx_qwen.py",
    "local-server/backends/asr_torch_qwen.py",
    "local-server/backends/translate_base.py",
    "local-server/backends/translate_mlx_gemma.py",
    "local-server/backends/translate_llamacpp.py",
    "local-server/backends/fluid.py",
    "native-host/launcher.py"
)

function Test-ExtensionId([string]$Value) {
    return $Value -match '^[a-p]{32}$'
}

function Get-RepoRoot {
    $here = $PSScriptRoot
    if ($here -and (Test-Path (Join-Path $here "..\local-server\server.py"))) {
        return (Resolve-Path (Join-Path $here "..")).Path
    }
    return $null
}

function Test-SupportedWindows {
    $arch = $env:PROCESSOR_ARCHITECTURE
    if ($arch -ne "AMD64") {
        throw "This installer supports Windows x64 only. Found $arch."
    }
    $os = Get-CimInstance Win32_OperatingSystem
    $version = [version]$os.Version
    if ($version.Major -lt 10) {
        throw "Windows 10 or later is required."
    }
    return $os
}

function Test-Nvidia {
    $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
    if (-not $smi) { return $false }
    try {
        $output = & nvidia-smi -L 2>$null
        return $LASTEXITCODE -eq 0 -and ($output -match "GPU")
    } catch {
        return $false
    }
}

$osInfo = $null
try {
    $osInfo = Test-SupportedWindows
} catch {
    if ($DryRun -and $Force) {
        Write-Warning $_
    } else {
        throw
    }
}

$accelerator = "cpu"
if (Test-Nvidia) {
    $accelerator = "cuda"
} else {
    $accelerator = "vulkan"
}

Write-Host "YouTube Live Translator Windows installer"
Write-Host "  App dir: $AppDir"
Write-Host "  Accelerator plan: $accelerator"

if ($ExtensionId -and -not (Test-ExtensionId $ExtensionId)) {
    throw "ExtensionId must be a Chrome extension id ([a-p]{32})."
}

if ($DryRun) {
    $plan = [ordered]@{
        osOk = $true
        appDir = $AppDir
        accelerator = $accelerator
        steps = @(
            "venv",
            "deps",
            "server",
            "asr",
            "llama",
            "gemma",
            "task",
            "native",
            "health"
        )
        extensionId = $ExtensionId
    }
    $plan | ConvertTo-Json
    Write-Host "Dry run: no files were changed."
    exit 0
}

New-Item -ItemType Directory -Force -Path $AppDir, $BinDir, $ModelDir, $LogDir, $NativeDir | Out-Null

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    Invoke-WebRequest "https://astral.sh/uv/install.ps1" -UseBasicParsing | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin;$env:Path"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv installation failed."
    }
}

Write-Host "Creating Python 3.12 environment..."
& uv venv --python 3.12 $Venv

$torchExtra = @()
if ($accelerator -eq "cuda") {
    $torchExtra = @("--index-url", "https://download.pytorch.org/whl/cu124")
}

Write-Host "Installing Python packages..."
& uv pip install --python $Python `
    "aiohttp>=3.10" `
    "numpy>=2.0" `
    "huggingface_hub>=0.26" `
    "transformers>=5.13.0" `
    "accelerate>=1.0" `
    "pyinstaller>=6.0"
& uv pip install --python $Python @torchExtra "torch"

function Copy-ServerFile([string]$RelPath) {
    $repo = Get-RepoRoot
    $destName = Split-Path $RelPath -Leaf
    if ($RelPath -like "local-server/backends/*") {
        $dest = Join-Path (Join-Path $AppDir "backends") $destName
        New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
    } elseif ($RelPath -like "native-host/*") {
        $dest = Join-Path $NativeDir $destName
    } else {
        $dest = Join-Path $AppDir $destName
    }
    if ($repo -and (Test-Path (Join-Path $repo $RelPath))) {
        Copy-Item (Join-Path $repo $RelPath) $dest -Force
    } else {
        Invoke-WebRequest "$RawBase/$RelPath" -OutFile $dest -UseBasicParsing
    }
}

Write-Host "Installing local routing server..."
foreach ($file in $ServerFiles) {
    Copy-ServerFile $file
}

$runtime = @{
    accelerator = $accelerator
    llama_bin = (Join-Path $BinDir "llama-server.exe")
    translation_model_path = (Join-Path $ModelDir $GgufName)
} | ConvertTo-Json
Set-Content -Path (Join-Path $AppDir "runtime.json") -Value $runtime -Encoding UTF8

Write-Host "Preparing Qwen3-ASR 0.6B..."
& $Python -c "from transformers import AutoProcessor, AutoModelForMultimodalLM; model='Qwen/Qwen3-ASR-0.6B-hf'; AutoProcessor.from_pretrained(model); AutoModelForMultimodalLM.from_pretrained(model); print('Qwen3-ASR ready.')"

function Get-LlamaAsset([string]$Kind) {
    $release = Invoke-RestMethod "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
    $patterns = @{
        cuda = "win-cuda-12.*-x64\.zip$"
        vulkan = "win-vulkan-x64\.zip$"
        cpu = "win-cpu-x64\.zip$"
        cudart = "cudart-llama-bin-win-cuda-12.*-x64\.zip$"
    }
    $asset = $release.assets | Where-Object { $_.name -match $patterns[$Kind] } | Select-Object -First 1
    if (-not $asset) { return $null }
    return $asset
}

function Install-Zip($Asset, $DestDir) {
    $zip = Join-Path $env:TEMP $Asset.name
    Invoke-WebRequest $Asset.browser_download_url -OutFile $zip -UseBasicParsing
    $extract = Join-Path $env:TEMP ([IO.Path]::GetFileNameWithoutExtension($Asset.name))
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    Expand-Archive $zip -DestinationPath $extract -Force
    Get-ChildItem $extract -Recurse -File | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $DestDir $_.Name) -Force
    }
}

function Install-Llama([string]$Kind) {
    $asset = Get-LlamaAsset $Kind
    if (-not $asset) { return $false }
    Write-Host "Downloading llama.cpp $($asset.name)..."
    Install-Zip $asset $BinDir
    if ($Kind -eq "cuda") {
        $cudart = Get-LlamaAsset "cudart"
        if ($cudart) { Install-Zip $cudart $BinDir }
    }
    return (Test-Path (Join-Path $BinDir "llama-server.exe"))
}

$llamaOk = $false
if ($accelerator -eq "cuda") {
    $llamaOk = Install-Llama "cuda"
    if (-not $llamaOk) {
        Write-Warning "CUDA llama.cpp failed. Trying Vulkan."
        $accelerator = "vulkan"
    }
}
if (-not $llamaOk -and $accelerator -eq "vulkan") {
    $llamaOk = Install-Llama "vulkan"
    if (-not $llamaOk) {
        Write-Warning "Vulkan llama.cpp failed. Trying CPU."
        $accelerator = "cpu"
    }
}
if (-not $llamaOk) {
    $llamaOk = Install-Llama "cpu"
    $accelerator = "cpu"
}
if (-not $llamaOk) {
    throw "Could not install llama-server.exe."
}

$runtime = @{
    accelerator = $accelerator
    llama_bin = (Join-Path $BinDir "llama-server.exe")
    translation_model_path = (Join-Path $ModelDir $GgufName)
} | ConvertTo-Json
Set-Content -Path (Join-Path $AppDir "runtime.json") -Value $runtime -Encoding UTF8

Write-Host "Preparing Gemma 4 E4B Q4_0..."
$gguf = Join-Path $ModelDir $GgufName
if (-not (Test-Path $gguf)) {
    & $Python -c "from huggingface_hub import hf_hub_download; import os; p=hf_hub_download(repo_id='$GgufRepo', filename='$GgufName', local_dir=r'$ModelDir'); print(p)"
}

$startScript = Join-Path $AppDir "start-local.ps1"
@"
`$ErrorActionPreference = 'Stop'
`$env:YTLT_APP_DIR = '$AppDir'
`$python = '$Python'
if (Test-Path '$PythonW') { `$python = '$PythonW' }
`$logDir = '$LogDir'
New-Item -ItemType Directory -Force -Path `$logDir | Out-Null
Start-Process -FilePath `$python -ArgumentList '"$AppDir\server.py"' -WorkingDirectory '$AppDir' -WindowStyle Hidden -RedirectStandardOutput (Join-Path `$logDir 'server.log') -RedirectStandardError (Join-Path `$logDir 'server.err.log')
"@ | Set-Content -Path $startScript -Encoding UTF8

$taskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT10S</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "$startScript"</Arguments>
    </Exec>
  </Actions>
</Task>
"@
$taskFile = Join-Path $AppDir "task.xml"
Set-Content -Path $taskFile -Value $taskXml -Encoding Unicode
schtasks /Create /TN $TaskName /XML $taskFile /F | Out-Null

Write-Host "Installing Chrome Native Messaging host..."
$hostCmd = Join-Path $NativeDir "ytlt-native-host.cmd"
@"
@echo off
"$Python" "$NativeDir\launcher.py"
"@ | Set-Content -Path $hostCmd -Encoding ASCII

$hostExe = Join-Path $NativeDir "ytlt-native-host.exe"
$pyinstaller = Join-Path $Venv "Scripts\pyinstaller.exe"
if (Test-Path $pyinstaller) {
    try {
        & $pyinstaller --onefile --noconsole --name ytlt-native-host --distpath $NativeDir --workpath (Join-Path $AppDir "build") --specpath (Join-Path $AppDir "build") (Join-Path $NativeDir "launcher.py")
    } catch {
        Write-Warning "PyInstaller failed. Using cmd host wrapper."
    }
}
$hostPath = $hostCmd
if (Test-Path $hostExe) { $hostPath = $hostExe }

$manifestPath = Join-Path $NativeDir "$HostName.json"
$origins = @()
if (Test-ExtensionId $ExtensionId) {
    $origins += "chrome-extension://$ExtensionId/"
}
$manifest = @{
    name = $HostName
    description = "Start the local AI service for YouTube Live Translator"
    path = $hostPath
    type = "stdio"
    allowed_origins = $origins
} | ConvertTo-Json
Set-Content -Path $manifestPath -Value $manifest -Encoding UTF8

$regPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"
New-Item -Path $regPath -Force | Out-Null
Set-ItemProperty -Path $regPath -Name "(default)" -Value $manifestPath

if (-not $ExtensionId) {
    Write-Warning "Extension ID was not supplied. Re-run with -ExtensionId to register the one-click launcher."
}

Write-Host "Starting local engine..."
schtasks /Run /TN $TaskName | Out-Null

$deadline = (Get-Date).AddMinutes(2)
$healthy = $false
do {
    try {
        $response = Invoke-WebRequest "http://127.0.0.1:8765/health" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
} while ((Get-Date) -lt $deadline)

if (-not $healthy) {
    throw "Local engine started but /health did not return 200. See $LogDir."
}

Write-Host "Installed."
Write-Host "  Local API: http://127.0.0.1:8765"
Write-Host "  ASR: Qwen3-ASR 0.6B (torch)"
Write-Host "  Translation: Gemma 4 E4B via llama.cpp ($accelerator)"
Write-Host "  Logs: $LogDir"
if ($accelerator -eq "cpu") {
    Write-Warning "CPU only. Live captions may lag. A CUDA or Vulkan GPU is recommended."
}
Write-Host "Reload the Chrome extension, then press 'ローカルAI起動'."
