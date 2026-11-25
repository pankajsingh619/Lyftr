<#
.SYNOPSIS
    Verifies the running local backend and frontend stack on 127.0.0.1:8000 and 127.0.0.1:3000.
.EXAMPLE
    .\scripts\verify-local.ps1
#>
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendBase = "http://127.0.0.1:8000"
$FrontendBase = "http://127.0.0.1:3000"

function Invoke-Api {
    param(
        [string]$Uri,
        [string]$Method = "GET",
        $Body = $null,
        [hashtable]$Headers = @{}
    )
    try {
        $params = @{
            UseBasicParsing = $true
            Uri = $Uri
            Method = $Method
            TimeoutSec = 5
            Headers = $Headers
        }
        if ($null -ne $Body -and $Body -ne "") {
            $params.ContentType = "application/json"
            $params.Body = [string]$Body
        }
        $r = Invoke-WebRequest @params
        return @{ Status = [int]$r.StatusCode; Body = $r.Content }
    } catch {
        $resp = $_.Exception.Response
        if (-not $resp) { throw }
        $errBody = $_.ErrorDetails.Message
        if (-not $errBody) {
            try {
                $stream = $resp.GetResponseStream()
                if ($stream.CanSeek) { $stream.Position = 0 }
                $sr = New-Object System.IO.StreamReader($stream)
                $errBody = $sr.ReadToEnd()
            } catch { $errBody = "" }
        }
        return @{ Status = [int]$resp.StatusCode; Body = $errBody }
    }
}

Write-Host "=== Verifying Local Lyftr AI Stack ==="

# 1. Backend /health
$healthRes = Invoke-Api -Uri "$BackendBase/health"
$healthJson = $healthRes.Body | ConvertFrom-Json
Write-Host ("1. Backend /health => HTTP $($healthRes.Status) $($healthRes.Body)")
if ($healthRes.Status -eq 200) {
    if ($healthJson.status -ne "ok" -or $healthJson.keys_configured -lt 1) {
        throw "Unexpected 200 /health payload"
    }
} elseif ($healthRes.Status -eq 503 -and $healthJson.detail -eq "no LLM keys configured") {
    Write-Host "   (Note: Backend is reachable; no LLM_API_KEYS configured in .env yet)"
} else {
    throw "Unexpected /health response: HTTP $($healthRes.Status) $($healthRes.Body)"
}

# 2. Frontend HTTP response
$fe = Invoke-Api -Uri "$FrontendBase/"
if ($fe.Status -ne 200 -or $fe.Body -notmatch '<div id="root">') {
    throw "Frontend did not render expected React root HTML"
}
Write-Host "2. Frontend / => HTTP 200 with React root"

# 3. Frontend API configuration check
$devEnv = Get-Content (Join-Path $RepoRoot "frontend\.env.development") -Raw
if ($devEnv -notmatch 'VITE_API_BASE_URL=http://127\.0\.0\.1:8000') {
    throw "frontend/.env.development does not set VITE_API_BASE_URL=http://127.0.0.1:8000"
}
$chatApiContent = Get-Content (Join-Path $RepoRoot "frontend\src\api\chatApi.js") -Raw
if ($chatApiContent -notmatch 'import\.meta\.env\.VITE_API_BASE_URL') {
    throw "chatApi.js missing VITE_API_BASE_URL configuration"
}
Write-Host "3. Frontend API configuration => VITE_API_BASE_URL=http://127.0.0.1:8000 (dev)"

# 4. SQLite database initialization check
$VenvPython = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
$pyScript = @'
import sqlite3, sys
from pathlib import Path
repo_root = Path(sys.argv[1])
sys.path.insert(0, str(repo_root / 'backend'))
from app.config import Settings
s = Settings()
p = Path(s.sqlite_path)
if not p.is_absolute():
    p = repo_root / 'backend' / p
assert p.exists(), f'SQLite file missing: {p}'
conn = sqlite3.connect(str(p))
tables = {r[0] for r in conn.execute('SELECT name FROM sqlite_master WHERE type=?', ('table',)).fetchall()}
assert {'sessions', 'messages'}.issubset(tables), f'Missing tables: {tables}'
print(f'SQLite OK at {p} tables={sorted(tables)}')
'@
$dbCheck = & $VenvPython -c $pyScript $RepoRoot
if ($LASTEXITCODE -ne 0) { throw "SQLite verification failed" }
Write-Host "4. $dbCheck"

# 5. HTTP 404 behavior
$res404 = Invoke-Api -Uri "$BackendBase/sessions/nonexistent-verify-id/messages"
if ($res404.Status -ne 404) { throw "Expected 404, got $($res404.Status)" }
Write-Host "5. Unknown session => HTTP 404 $($res404.Body)"

# 6. HTTP 422 validation
$res422 = Invoke-Api -Uri "$BackendBase/chat" -Method "POST" -Body '{"session_id":"verify-422","message":"   "}'
if ($res422.Status -ne 422) { throw "Expected 422, got $($res422.Status)" }
Write-Host "6. Empty message validation => HTTP 422"

# 7. HTTP 503 simulated failure (*=429)
$res503 = Invoke-Api -Uri "$BackendBase/chat" -Method "POST" -Headers @{"X-Simulate-Failure"="*=429"} -Body '{"session_id":"verify-503","message":"Test 503"}'
if ($res503.Status -ne 503 -or $res503.Body -notmatch 'all providers unavailable') {
    throw "Expected 503 all providers unavailable, got $($res503.Status) $($res503.Body)"
}
Write-Host "7. Simulated *=429 failure => HTTP 503 $($res503.Body)"

# 8. Mandatory frontend data-testid attributes in source
$frontendSrc = (Get-ChildItem (Join-Path $RepoRoot "frontend\src") -Recurse -Include *.js,*.jsx | Get-Content -Raw) -join "`n"
$requiredIds = @(
    "chat-input",
    "send-button",
    "assistant-message",
    "meta-source",
    "meta-model",
    "meta-latency",
    "meta-input-tokens",
    "meta-output-tokens",
    "system-prompt-input"
)
foreach ($tid in $requiredIds) {
    if ($frontendSrc -notmatch [regex]::Escape($tid)) {
        throw "Missing mandatory data-testid in frontend source: $tid"
    }
}
Write-Host "8. All 9 mandatory frontend data-testid attributes present."
Write-Host ""
Write-Host "LOCAL VERIFICATION PASSED."
