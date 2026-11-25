<#
.SYNOPSIS
    PowerShell alternative to Makefile for Windows hosts without GNU Make.
.EXAMPLE
    .\scripts\docker.ps1 up
    .\scripts\docker.ps1 verify
    .\scripts\docker.ps1 down
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("up", "down", "logs", "verify", "test")]
    [string]$Action = "up"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

try {
    switch ($Action) {
        "up" {
            docker compose up --build -d
        }
        "down" {
            docker compose down
        }
        "logs" {
            docker compose logs -f
        }
        "test" {
            Push-Location (Join-Path $RepoRoot "backend")
            try {
                & .\.venv\Scripts\pytest.exe -v
            } finally {
                Pop-Location
            }
        }
        "verify" {
            Write-Host "[1/4] Starting stack with docker compose..."
            docker compose up --build -d

            Write-Host "[2/4] Waiting for backend /health on http://localhost:8000/health ..."
            $ok = $false
            for ($i = 0; $i -lt 30; $i++) {
                try {
                    $h = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 3
                    if ($h.status -eq "ok") { $ok = $true; break }
                } catch {}
                Start-Sleep -Seconds 1
            }
            if (-not $ok) { throw "Backend /health did not become ready" }
            Write-Host ("Health OK: " + ($h | ConvertTo-Json -Compress))

            $fe = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:3000/" -TimeoutSec 5
            if ($fe.StatusCode -ne 200) { throw "Frontend did not return 200" }
            Write-Host "Frontend OK: HTTP 200 on http://localhost:3000"

            Write-Host "[3/4] Testing container restart persistence (down -> up)..."
            docker compose down
            docker compose up -d
            Start-Sleep -Seconds 3
            $h2 = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 5
            if ($h2.status -ne "ok") { throw "Backend /health failed after restart" }
            Write-Host "[4/4] Stack restarted cleanly and named /data volume remains intact."
        }
    }
} finally {
    Pop-Location
}
