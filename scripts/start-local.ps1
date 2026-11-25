<#
.SYNOPSIS
    Starts FastAPI backend (127.0.0.1:8000) and Vite React frontend (127.0.0.1:3000) safely.
.EXAMPLE
    .\scripts\start-local.ps1
#>
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$LogsDir = Join-Path $RepoRoot "logs"
$PidFile = Join-Path $LogsDir "local-pids.json"
$BackendLog = Join-Path $LogsDir "backend.log"
$BackendOutLog = Join-Path $LogsDir "backend.out.log"
$FrontendLog = Join-Path $LogsDir "frontend.log"
$FrontendErrLog = Join-Path $LogsDir "frontend.err.log"

Write-Host "=== Lyftr AI Local Startup ==="

# 1 & 2. Check Python and Node/npm
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if (-not $pythonCmd) { throw "Python not found on PATH. Please install Python 3.12+." }
if (-not $nodeCmd -or -not $npmCmd) { throw "Node.js / npm not found on PATH. Please install Node.js." }

# 3 & 4. Check required backend & frontend files
foreach ($req in @(
    (Join-Path $BackendDir "app\main.py"),
    (Join-Path $BackendDir "requirements.txt"),
    (Join-Path $FrontendDir "package.json"),
    (Join-Path $FrontendDir "index.html")
)) {
    if (-not (Test-Path $req)) { throw "Missing required project file: $req" }
}

# 5 & 6. Check virtual environment & install missing dependencies only when needed
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating backend virtual environment at $BackendDir\.venv ..."
    & python -m venv (Join-Path $BackendDir ".venv")
}

& $VenvPython -c "import fastapi, uvicorn, litellm, orjson, pydantic_settings" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing missing backend Python dependencies..."
    & $VenvPython -m pip install -r (Join-Path $BackendDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Backend pip install failed." }
}

$ViteJs = Join-Path $FrontendDir "node_modules\vite\bin\vite.js"
if (-not (Test-Path $ViteJs)) {
    Write-Host "Installing frontend npm dependencies..."
    Push-Location $FrontendDir
    try {
        & npm install
        if ($LASTEXITCODE -ne 0) { throw "Frontend npm install failed." }
    } finally {
        Pop-Location
    }
}

# 7. Check for occupied ports 8000 and 3000
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

$occupied = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in 8000, 3000 }
if ($occupied) {
    $details = $occupied | ForEach-Object { "port $($_.LocalPort) (PID $($_.OwningProcess))" }
    throw ("Cannot start because required ports are already in use: " + ($details -join ", ") + ". Run .\scripts\stop-local.ps1 or free those ports first.")
}

if (Test-Path $PidFile) {
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

# 8. Start FastAPI backend in a separate process
Write-Host "Starting FastAPI backend on http://127.0.0.1:8000 ..."
$beProc = Start-Process -FilePath $VenvPython `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $BackendDir `
    -RedirectStandardOutput $BackendOutLog `
    -RedirectStandardError $BackendLog `
    -PassThru -WindowStyle Hidden

# 9. Start Vite frontend in a separate process
Write-Host "Starting Vite frontend on http://127.0.0.1:3000 ..."
$feProc = Start-Process -FilePath $nodeCmd.Source `
    -ArgumentList $ViteJs, "--host", "127.0.0.1", "--port", "3000", "--strictPort" `
    -WorkingDirectory $FrontendDir `
    -RedirectStandardOutput $FrontendLog `
    -RedirectStandardError $FrontendErrLog `
    -PassThru -WindowStyle Hidden

@{
    started_at = (Get-Date).ToString("o")
    backend_pid = $beProc.Id
    frontend_pid = $feProc.Id
} | ConvertTo-Json | Set-Content -Path $PidFile -Encoding UTF8

try {
    # 10 & 11. Wait for both services and perform HTTP readiness checks
    Write-Host "Waiting for backend readiness (cold LiteLLM import may take up to 15s)..."
    $beReady = $false
    $healthSummary = ""
    for ($i = 0; $i -lt 45; $i++) {
        if ($beProc.HasExited) {
            throw "Backend process exited unexpectedly (code $($beProc.ExitCode)). Check $BackendLog."
        }
        try {
            $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2
            $beReady = $true
            $healthSummary = "HTTP $($resp.StatusCode) $($resp.Content)"
            break
        } catch {
            $httpResp = $_.Exception.Response
            if ($httpResp) {
                $body = $_.ErrorDetails.Message
                if (-not $body) {
                    try {
                        $stream = $httpResp.GetResponseStream()
                        $stream.Position = 0
                        $sr = New-Object System.IO.StreamReader($stream)
                        $body = $sr.ReadToEnd()
                    } catch { $body = "" }
                }
                $beReady = $true
                $healthSummary = "HTTP $([int]$httpResp.StatusCode) $body (Backend is running; configure LLM_API_KEYS in .env for 200 OK)"
                break
            }
        }
        Start-Sleep -Seconds 1
    }
    if (-not $beReady) {
        throw "Backend timed out waiting for http://127.0.0.1:8000/health."
    }

    Write-Host "Waiting for frontend readiness..."
    $feReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        if ($feProc.HasExited) {
            throw "Frontend process exited unexpectedly (code $($feProc.ExitCode)). Check $FrontendLog."
        }
        try {
            $feResp = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:3000/" -TimeoutSec 2
            if ($feResp.StatusCode -eq 200) {
                $feReady = $true
                break
            }
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    if (-not $feReady) {
        throw "Frontend timed out waiting for http://127.0.0.1:3000/."
    }

    # 12 & 15. Print exact URLs and stop instructions
    Write-Host ""
    Write-Host "Local stack is running!"
    Write-Host "  Frontend UI:     http://127.0.0.1:3000"
    Write-Host "  Backend Health:  http://127.0.0.1:8000/health ($healthSummary)"
    Write-Host "  Backend Log:     $BackendLog"
    Write-Host "  Frontend Log:    $FrontendLog"
    Write-Host "  Stop command:    .\scripts\stop-local.ps1"
} catch {
    Write-Host ""
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    if (Test-Path $BackendLog) {
        Write-Host "--- Tail of backend.log ---"
        Get-Content $BackendLog -Tail 25
    }
    if (Test-Path $FrontendLog) {
        Write-Host "--- Tail of frontend.log ---"
        Get-Content $FrontendLog -Tail 25
    }
    if (Test-Path $FrontendErrLog) {
        Write-Host "--- Tail of frontend.err.log ---"
        Get-Content $FrontendErrLog -Tail 25
    }
    & (Join-Path $PSScriptRoot "stop-local.ps1")
    exit 1
}
