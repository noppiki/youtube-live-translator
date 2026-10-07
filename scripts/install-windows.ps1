[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$ExtensionId = "",
    [switch]$DryRun,
    [switch]$SkipModels,
    [switch]$SkipRuntime,
    [switch]$NoStart,
    [string]$SourceRoot = "",
    [string]$RawBase = "https://raw.githubusercontent.com/noppiki/youtube-live-translator/main",
    [string]$InstallDirectory = "",
    [string]$TranslationModelRepo = "google/gemma-4-E4B-it-qat-q4_0-gguf"
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "▶ $Message"
}

function Invoke-External([string]$Command, [string[]]$Arguments) {
    Write-Host ("> {0} {1}" -f $Command, ($Arguments -join " "))
    if ($DryRun) {
        return
    }
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw ("Command failed with exit code {0}: {1}" -f $LASTEXITCODE, $Command)
    }
}

function Ensure-Directory([string]$Path) {
    if ($DryRun) {
        Write-Host "+ mkdir $Path"
        return
    }
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Download-SourceFile([string]$RelativePath, [string]$Destination) {
    $localPath = if ($SourceRoot) { Join-Path $SourceRoot $RelativePath } else { "" }
    if ($localPath -and (Test-Path -LiteralPath $localPath)) {
        Write-Step "Installing $RelativePath from the checked-out source"
        if (-not $DryRun) {
            Copy-Item -LiteralPath $localPath -Destination $Destination -Force
        }
        return
    }

    $url = "$RawBase/$($RelativePath.Replace('\', '/'))"
    Write-Step "Downloading $RelativePath"
    if (-not $DryRun) {
        Invoke-WebRequest -Uri $url -OutFile $Destination -UseBasicParsing
    }
}

function Assert-WindowsX64 {
    if ($env:OS -ne "Windows_NT" -or -not [Environment]::Is64BitOperatingSystem) {
        throw "YouTube Live Translator Windows installer requires Windows 10/11 x64."
    }
    if ([Environment]::OSVersion.Version.Major -lt 10) {
        throw "YouTube Live Translator requires Windows 10 or newer."
    }
}

function Get-Uv {
    $existing = Get-Command uv -ErrorAction SilentlyContinue
    if ($existing) {
        return $existing.Source
    }
    if ($DryRun) {
        Write-Host "+ install uv with https://astral.sh/uv/install.ps1"
        return "uv"
    }

    Write-Step "Installing uv"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $candidatePaths = @(
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:APPDATA "uv")
    )
    foreach ($candidate in $candidatePaths) {
        if ($candidate -and ($env:Path -notlike "*$candidate*")) {
            $env:Path = "$candidate;$env:Path"
        }
    }
    $existing = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $existing) {
        throw "uv was installed but could not be found in PATH. Open a new PowerShell and rerun the installer."
    }
    return $existing.Source
}

function Get-WindowsAccelerator([string]$Python) {
    $configured = [string]$env:YTLT_ACCELERATOR
    if ($configured -in @("cuda", "vulkan", "cpu")) {
        return $configured
    }
    if ($DryRun) {
        return "auto"
    }
    $probe = @'
import torch
print("cuda" if torch.cuda.is_available() else "cpu")
'@
    $previousErrorActionPreference = $ErrorActionPreference
    $probeExitCode = 1
    $result = @()
    try {
        # Windows PowerShell turns native stderr into ErrorRecord objects. With
        # $ErrorActionPreference = Stop, an ordinary Python traceback would abort
        # the entire installer before we can inspect $LASTEXITCODE. GPU detection
        # is best-effort, so make this probe explicitly non-terminating.
        $ErrorActionPreference = "Continue"
        $result = @(& $Python -c $probe 2>$null)
        $probeExitCode = $LASTEXITCODE
    }
    catch {
        $probeExitCode = 1
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }

    if ($probeExitCode -eq 0 -and ($result -join "").Trim() -eq "cuda") {
        return "cuda"
    }
    if ($probeExitCode -ne 0) {
        Write-Warning ('PyTorch accelerator probe failed; continuing with Vulkan/CPU detection. Run & "{0}" -c "import torch; print(torch.__version__)" to inspect the PyTorch error.' -f $Python)
    }
    if ((Get-Command vulkaninfo -ErrorAction SilentlyContinue) -or (Test-Path (Join-Path $env:WINDIR "System32\vulkan-1.dll"))) {
        return "vulkan"
    }
    return "cpu"
}

function Install-LlamaRuntime([string]$RuntimeDirectory, [string]$Accelerator) {
    $server = Join-Path $RuntimeDirectory "llama-server.exe"
    if (Test-Path -LiteralPath $server) {
        return $server
    }
    if ($DryRun) {
        Write-Host "+ find the newest llama.cpp release with a Windows $Accelerator x64 archive and install it into $RuntimeDirectory"
        return $server
    }

    Write-Step "Preparing llama.cpp ($Accelerator)"
    $patterns = switch ($Accelerator) {
        "cuda" { @("bin-win-cuda-12\.4-x64\.zip$", "bin-win-cuda-13\.4-x64\.zip$") }
        "vulkan" { @("bin-win-vulkan-x64\.zip$") }
        default { @("bin-win-cpu-x64\.zip$") }
    }

    # The GitHub 'latest' stable tag can be metadata-only. Search recent
    # releases and select the newest release that actually ships the needed
    # Windows runtime asset.
    $releases = Invoke-RestMethod "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=20"
    $selectedRelease = $null
    $asset = $null
    foreach ($release in $releases) {
        foreach ($pattern in $patterns) {
            $asset = $release.assets | Where-Object { $_.name -match $pattern -and $_.name -notmatch '^cudart-' } | Select-Object -First 1
            if ($asset) {
                $selectedRelease = $release
                break
            }
        }
        if ($asset) { break }
    }
    if (-not $asset -or -not $selectedRelease) {
        throw "No recent llama.cpp release contained a compatible Windows asset for accelerator '$Accelerator'."
    }

    Ensure-Directory $RuntimeDirectory
    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("ytlt-llama-" + [Guid]::NewGuid().ToString("N"))
    $mainStage = Join-Path $tempRoot "main"
    New-Item -ItemType Directory -Path $mainStage -Force | Out-Null
    try {
        $archive = Join-Path $tempRoot "llama-runtime.zip"
        Write-Step "Downloading llama.cpp $($selectedRelease.tag_name): $($asset.name)"
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $archive -UseBasicParsing
        Expand-Archive -LiteralPath $archive -DestinationPath $mainStage -Force
        $extractedServer = Get-ChildItem -LiteralPath $mainStage -Filter "llama-server.exe" -File -Recurse | Select-Object -First 1
        if (-not $extractedServer) {
            throw "The llama.cpp archive did not contain llama-server.exe."
        }
        Copy-Item -Path (Join-Path $extractedServer.Directory.FullName "*") -Destination $RuntimeDirectory -Recurse -Force

        # CUDA builds publish their runtime DLLs separately. Install the
        # matching cudart archive beside llama-server.exe so users do not need
        # a local CUDA Toolkit installation.
        if ($Accelerator -eq "cuda" -and $asset.name -match 'cuda-(12\.4|13\.4)-x64\.zip$') {
            $cudaVersion = $Matches[1]
            $cudartAsset = $selectedRelease.assets | Where-Object {
                $_.name -like "cudart-*-cuda-$cudaVersion-x64.zip"
            } | Select-Object -First 1
            if (-not $cudartAsset) {
                throw "The selected llama.cpp CUDA release did not contain the matching cudart archive."
            }
            $cudaStage = Join-Path $tempRoot "cudart"
            New-Item -ItemType Directory -Path $cudaStage -Force | Out-Null
            $cudaArchive = Join-Path $tempRoot "cudart.zip"
            Invoke-WebRequest -Uri $cudartAsset.browser_download_url -OutFile $cudaArchive -UseBasicParsing
            Expand-Archive -LiteralPath $cudaArchive -DestinationPath $cudaStage -Force
            Get-ChildItem -LiteralPath $cudaStage -File -Recurse | ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination $RuntimeDirectory -Force
            }
        }
    }
    finally {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path -LiteralPath $server)) {
        throw "llama-server.exe was not installed into $RuntimeDirectory."
    }
    return $server
}


function Prepare-TranslationModel([string]$Python, [string]$ModelDirectory) {
    Write-Step "Preparing Gemma 4 E4B Q4_0 translation model"
    Ensure-Directory $ModelDirectory
    $download = @"
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='$TranslationModelRepo',
    local_dir=r'$ModelDirectory',
    allow_patterns=['*q4_0*.gguf', '*.json'],
)
print('Gemma model ready.')
"@
    Invoke-External $Python @("-c", $download)
}

function Prepare-QwenModel([string]$Python) {
    Write-Step "Preparing Qwen3-ASR 0.6B Transformers model"
    $warmup = @'
from transformers import AutoModelForMultimodalLM, AutoProcessor
import torch
model_id = "Qwen/Qwen3-ASR-0.6B-hf"
processor = AutoProcessor.from_pretrained(model_id)
dtype = torch.float16 if torch.cuda.is_available() else torch.float32
try:
    AutoModelForMultimodalLM.from_pretrained(model_id, device_map="auto", dtype=dtype)
except TypeError:
    AutoModelForMultimodalLM.from_pretrained(model_id, device_map="auto", torch_dtype=dtype)
print("Qwen3-ASR ready.")
'@
    Invoke-External $Python @("-c", $warmup)
}

function Register-NativeMessaging([string]$NativeHost, [string]$ManifestPath) {
    if (-not $ExtensionId) {
        Write-Host "⚠ Extension ID was not supplied; skipping Native Messaging registration."
        return
    }
    if ($ExtensionId -notmatch '^[a-p]{32}$') {
        throw "ExtensionId must be the 32-character Chrome extension ID (letters a-p only)."
    }

    $manifest = [ordered]@{
        name = "com.noppiki.youtube_live_translator"
        description = "Start the local AI service for YouTube Live Translator"
        path = $NativeHost
        type = "stdio"
        allowed_origins = @("chrome-extension://$ExtensionId/")
    }
    $manifestJson = $manifest | ConvertTo-Json -Depth 4
    Write-Step "Registering Chrome and Edge Native Messaging"
    if ($DryRun) {
        Write-Host "+ write $ManifestPath and HKCU NativeMessagingHosts registry values"
        return
    }

    [IO.File]::WriteAllText($ManifestPath, $manifestJson, [Text.UTF8Encoding]::new($false))
    foreach ($keyPath in @(
        "HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.noppiki.youtube_live_translator",
        "HKCU:\Software\Microsoft\Edge\NativeMessagingHosts\com.noppiki.youtube_live_translator"
    )) {
        New-Item -Path $keyPath -Force | Out-Null
        Set-Item -Path $keyPath -Value $ManifestPath
    }
}

Assert-WindowsX64
if (-not $SourceRoot) { $SourceRoot = $PSScriptRoot }
if (-not $InstallDirectory) {
    $InstallDirectory = if ($env:YTLT_APP_DIR) { $env:YTLT_APP_DIR } else { Join-Path $env:LOCALAPPDATA "YouTubeLiveTranslator" }
}

$AppDir = $InstallDirectory
$Venv = Join-Path $AppDir ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Pythonw = Join-Path $Venv "Scripts\pythonw.exe"
$Server = Join-Path $AppDir "server.py"
$BackendDirectory = Join-Path $AppDir "backends"
$NativeDirectory = Join-Path $AppDir "native"
$NativeScript = Join-Path $NativeDirectory "launcher.py"
$NativeHost = Join-Path $NativeDirectory "ytlt-native-host.exe"
$ManifestPath = Join-Path $NativeDirectory "com.noppiki.youtube_live_translator.json"
$StartupScript = Join-Path $AppDir "start-windows.ps1"
$RuntimeDirectory = Join-Path $AppDir "llama-cpp"
$ModelDirectory = Join-Path $AppDir "models\gemma-4-E4B-it-qat-q4_0-gguf"

Write-Host "YouTube Live Translator Windows local engine"
Write-Host "Install directory: $AppDir"
if ($DryRun) { Write-Host "Dry run: no packages, models, registry values, or processes will be changed." }

Ensure-Directory $AppDir
Ensure-Directory $BackendDirectory
Ensure-Directory $NativeDirectory
$Uv = Get-Uv

Write-Step "Creating/updating isolated Python 3.12 environment"
Invoke-External $Uv @("venv", "--python", "3.12", $Venv)
Invoke-External $Uv @("pip", "install", "--python", $Python,
    "aiohttp>=3.10", "numpy>=2.0", "torch>=2.7", "transformers>=5.13.0",
    "accelerate>=1.10", "huggingface_hub>=0.30", "soundfile>=0.12", "pyinstaller>=6.0")

Download-SourceFile "local-server/server.py" $Server
foreach ($backendFile in @("__init__.py", "asr.py", "runtime.py", "translation.py")) {
    Download-SourceFile "local-server/backends/$backendFile" (Join-Path $BackendDirectory $backendFile)
}
Download-SourceFile "native-host/launcher.py" $NativeScript
Download-SourceFile "scripts/start-windows.ps1" $StartupScript

$Accelerator = Get-WindowsAccelerator $Python
if (-not $SkipRuntime) {
    $null = Install-LlamaRuntime $RuntimeDirectory $Accelerator
}
if (-not $SkipModels) {
    Prepare-QwenModel $Python
    Prepare-TranslationModel $Python $ModelDirectory
}

Write-Step "Building the Windows Native Messaging host"
Invoke-External $Python @("-m", "PyInstaller", "--onefile", "--clean", "--name", "ytlt-native-host",
    "--distpath", $NativeDirectory, "--workpath", (Join-Path $NativeDirectory "build"),
    "--specpath", $NativeDirectory, $NativeScript)

Register-NativeMessaging $NativeHost $ManifestPath

Write-Step "Configuring per-user startup"
$startupCommand = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -AppDir "{1}"' -f $StartupScript, $AppDir
if (-not $DryRun) {
    $translationModel = Get-ChildItem -LiteralPath $ModelDirectory -Filter "*.gguf" -File -ErrorAction SilentlyContinue | Select-Object -First 1
    [Environment]::SetEnvironmentVariable("YTLT_APP_DIR", $AppDir, "User")
    [Environment]::SetEnvironmentVariable("YTLT_TRANSLATION_URL", "http://127.0.0.1:8766", "User")
    [Environment]::SetEnvironmentVariable("YTLT_ACCELERATOR", $Accelerator, "User")
    if ($translationModel) {
        [Environment]::SetEnvironmentVariable("YTLT_TRANSLATION_MODEL", $translationModel.FullName, "User")
    }
    New-Item -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Force | Out-Null
    Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "YouTubeLiveTranslator" -Value $startupCommand
}
else {
    Write-Host "+ HKCU:\Software\Microsoft\Windows\CurrentVersion\Run\YouTubeLiveTranslator = $startupCommand"
}

if (-not $NoStart) {
    Write-Step "Starting the local engine"
    if ($DryRun) {
        Write-Host "+ Start-Process powershell.exe -File $StartupScript -AppDir $AppDir"
    }
    else {
        $translationModel = Get-ChildItem -LiteralPath $ModelDirectory -Filter "*.gguf" -File -ErrorAction SilentlyContinue | Select-Object -First 1
        $env:YTLT_APP_DIR = $AppDir
        $env:YTLT_TRANSLATION_URL = "http://127.0.0.1:8766"
        $env:YTLT_ACCELERATOR = $Accelerator
        if ($translationModel) { $env:YTLT_TRANSLATION_MODEL = $translationModel.FullName }
        & $StartupScript -AppDir $AppDir
        $ready = $false
        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            Start-Sleep -Milliseconds 250
            try {
                $health = Invoke-RestMethod "http://127.0.0.1:8765/health" -TimeoutSec 2
                if ($health.ok) { $ready = $true; break }
            }
            catch { }
        }
        if (-not $ready) {
            throw "Local engine did not become ready. Check $AppDir\logs or rerun with -NoStart."
        }
    }
}

Write-Host ""
Write-Host "✓ Windows local engine installed/updated."
Write-Host "  Local API: http://127.0.0.1:8765"
Write-Host "  ASR: Qwen3-ASR 0.6B (Transformers)"
Write-Host "  Translation: Gemma 4 E4B via llama.cpp at http://127.0.0.1:8766"
Write-Host "  App directory: $AppDir"
if ($ExtensionId) { Write-Host "  Native Messaging: registered for $ExtensionId" }
Write-Host "Reload the Chrome extension, then press 'ローカルAI起動'."
