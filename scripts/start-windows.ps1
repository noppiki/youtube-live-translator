[CmdletBinding()]
param(
    [string]$AppDir = ""
)

$ErrorActionPreference = "Stop"
if (-not $AppDir) {
    $AppDir = if ($env:YTLT_APP_DIR) { $env:YTLT_APP_DIR } else { Join-Path $env:LOCALAPPDATA "YouTubeLiveTranslator" }
}

function Test-Port([int]$Port) {
    try {
        $client = [Net.Sockets.TcpClient]::new()
        $client.Connect("127.0.0.1", $Port)
        $client.Dispose()
        return $true
    }
    catch {
        return $false
    }
}

$env:YTLT_APP_DIR = $AppDir
$env:YTLT_TRANSLATION_URL = "http://127.0.0.1:8766"
$modelDir = Join-Path $AppDir "models\gemma-4-E4B-it-qat-q4_0-gguf"
$model = Get-ChildItem -LiteralPath $modelDir -Filter "*.gguf" -File -ErrorAction SilentlyContinue | Select-Object -First 1
$env:YTLT_TRANSLATION_MODEL = if ($model) { $model.FullName } else { "gemma-4-E4B-it-qat-q4_0" }
$llama = Join-Path $AppDir "llama-cpp\llama-server.exe"
$pythonw = Join-Path $AppDir ".venv\Scripts\pythonw.exe"
$server = Join-Path $AppDir "server.py"
$logDir = Join-Path $AppDir "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

if (-not (Test-Port 8766) -and (Test-Path -LiteralPath $llama) -and $model) {
    Start-Process -FilePath $llama -ArgumentList @("-m", $model.FullName, "--host", "127.0.0.1", "--port", "8766") -WorkingDirectory (Split-Path -Parent $llama) -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir "llama.log") -RedirectStandardError (Join-Path $logDir "llama.err.log")
}
if (-not (Test-Port 8765) -and (Test-Path -LiteralPath $pythonw) -and (Test-Path -LiteralPath $server)) {
    Start-Process -FilePath $pythonw -ArgumentList @($server) -WorkingDirectory $AppDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir "server.log") -RedirectStandardError (Join-Path $logDir "server.err.log")
}
