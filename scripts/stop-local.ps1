<#
.SYNOPSIS
    Stops only the backend and frontend processes started by start-local.ps1.
.EXAMPLE
    .\scripts\stop-local.ps1
#>
$ErrorActionPreference = "Continue"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $RepoRoot "logs\local-pids.json"

if (-not (Test-Path $PidFile)) {
    Write-Host "No tracked local server PIDs found at $PidFile."
    exit 0
}

$info = Get-Content $PidFile -Raw | ConvertFrom-Json
$pids = @(
    $info.backend_pid,
    $info.frontend_pid
) | Where-Object { $_ -and ($_ -is [int] -or $_ -is [long]) } | Select-Object -Unique

foreach ($targetPid in $pids) {
    $proc = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
    if ($proc -and $proc.ProcessName -in @("python", "node")) {
        Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped $($proc.ProcessName) (PID $targetPid)"
    }
}

Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "Lyftr AI local servers stopped."
