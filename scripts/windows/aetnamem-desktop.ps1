# aetnamem desktop launcher for Windows 10/11.
# Run via aetnamem-desktop.bat (double-click) or:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\aetnamem-desktop.ps1
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

# --- Python ------------------------------------------------------------------
function Find-Python {
    foreach ($candidate in @(@("py", "-3"), @(, "python"))) {
        $exe = Get-Command $candidate[0] -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        $extra = if ($candidate.Length -gt 1) { $candidate[1..($candidate.Length - 1)] } else { @() }
        $check = $extra + @("-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)")
        & $candidate[0] @check 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    return $null
}

$Python = Find-Python
if (-not $Python) {
    Write-Host "Python 3.10+ is required. Install it with:" -ForegroundColor Yellow
    Write-Host "  winget install Python.Python.3.12"
    Write-Host "or from https://www.python.org/downloads/ (check 'Add python.exe to PATH')."
    Read-Host "Press Enter to exit"
    exit 1
}

# --- Paths -------------------------------------------------------------------
$DataDir = Join-Path $env:LOCALAPPDATA "aetnamem"
$Db = if ($env:AETNAMEM_DB) { $env:AETNAMEM_DB } else { Join-Path $DataDir "memories.db" }
$Workspace = if ($env:AETNAMEM_WORKSPACE) { $env:AETNAMEM_WORKSPACE } else { Join-Path $env:USERPROFILE "Aetnamem Workspace" }
$LocalModel = if ($env:AETNAMEM_LOCAL_MODEL) { $env:AETNAMEM_LOCAL_MODEL } else { "qwen3:1.7b" }
$OllamaUrl = if ($env:AETNAMEM_OLLAMA_URL) { $env:AETNAMEM_OLLAMA_URL } else { "http://localhost:11434" }

New-Item -ItemType Directory -Force -Path (Split-Path $Db), $Workspace | Out-Null

Write-Host "Starting aetnamem desktop..."
Write-Host "Workspace: $Workspace"
Write-Host ""

# --- Local model bootstrap (best effort) --------------------------------------
function Test-Ollama {
    try {
        Invoke-WebRequest -Uri "$OllamaUrl/api/tags" -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    } catch { return $false }
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "Installing Ollama (one-time, via winget)..."
        winget install --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
        # Pick up the PATH update without restarting the shell.
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                    [Environment]::GetEnvironmentVariable("Path", "User")
    } else {
        Write-Host "Ollama not found and winget unavailable." -ForegroundColor Yellow
        Write-Host "Install it from https://ollama.com/download/windows to enable the local model."
    }
}

if (Get-Command ollama -ErrorAction SilentlyContinue) {
    if (-not (Test-Ollama)) {
        Write-Host "Starting Ollama in the background..."
        Start-Process -WindowStyle Hidden ollama serve
        for ($i = 0; $i -lt 20 -and -not (Test-Ollama); $i++) { Start-Sleep -Milliseconds 500 }
    }
    if (Test-Ollama) {
        $models = (& ollama list 2>$null) -join "`n"
        if ($models -notmatch [regex]::Escape($LocalModel)) {
            Write-Host "Downloading local model $LocalModel (one-time)..."
            & ollama pull $LocalModel
            if ($LASTEXITCODE -ne 0) { Write-Host "Model download failed; you can retry from Settings later." }
        }
        Write-Host "Local model ready: $LocalModel"
    } else {
        Write-Host "Ollama did not start; the assistant will run in offline echo mode."
    }
}
Write-Host ""

# At-rest database sealing is macOS-only (Keychain); on Windows the database
# stays at $Db. The service signs the dashboard in automatically (tokens ride
# in the URL fragment) and opens the browser itself.
$env:AETNAMEM_DB = $Db
$env:AETNAMEM_WORKSPACE = $Workspace
$PyExtra = if ($Python.Length -gt 1) { $Python[1..($Python.Length - 1)] } else { @() }
$RunArgs = $PyExtra + @("-m", "aetnamem.service", "--db", $Db, "--workspace", $Workspace)
& $Python[0] @RunArgs
