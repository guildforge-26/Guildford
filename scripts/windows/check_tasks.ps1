# Sanity-checks the Job Alert System's Windows scheduled tasks.
# Run from PowerShell: powershell -ExecutionPolicy Bypass -File scripts\windows\check_tasks.ps1

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

Write-Host "=== Scheduled tasks ==="
$Tasks = Get-ScheduledTask -TaskName "JobAlerts-*" -ErrorAction SilentlyContinue
if ($Tasks) {
    $Tasks | Get-ScheduledTaskInfo | Format-Table TaskName, LastRunTime, LastTaskResult, NextRunTime -AutoSize
} else {
    Write-Host "(none found -- run scripts\windows\install_tasks.ps1)"
}

Write-Host ""
Write-Host "=== STOP kill switch ==="
$StopFile = Join-Path $ProjectDir "STOP"
if (Test-Path $StopFile) {
    Write-Host "STOP file is PRESENT at $StopFile -- all runs will halt immediately."
} else {
    Write-Host "No STOP file -- runs are enabled."
}

Write-Host ""
Write-Host "=== Lock file ==="
$LockFile = Join-Path $ProjectDir "data\pipeline.lock"
if (Test-Path $LockFile) {
    Write-Host "Lock file exists (holder PID: $(Get-Content $LockFile -ErrorAction SilentlyContinue))."
    Write-Host "If no run is actually in progress, this is stale and will be reclaimed automatically next run."
} else {
    Write-Host "No lock file -- no run currently in progress."
}

Write-Host ""
Write-Host "=== Recent runs (from the database) ==="
$PythonExe = Join-Path $ProjectDir "venv\Scripts\python.exe"
$DbFile = Join-Path $ProjectDir "data\jobs.db"
if (-not (Test-Path $DbFile)) {
    Write-Host "No database yet -- no runs recorded."
} elseif (Test-Path $PythonExe) {
    Push-Location $ProjectDir
    & $PythonExe -c "import sys; sys.path.insert(0, 'src'); from jobalerts import db as dbmod; from jobalerts.config import get_settings; s = get_settings();
import sqlite3
with dbmod.connect(s) as conn:
    for row in dbmod.recent_runs(conn, limit=10):
        print(f'{row[\"run_id\"]:<40} {row[\"kind\"]:<10} {row[\"status\"]:<10} started {row[\"started_at\"]}')"
    Pop-Location
}

Write-Host ""
Write-Host "=== Last 20 lines of logs\cron.log ==="
$LogFile = Join-Path $ProjectDir "logs\cron.log"
if (Test-Path $LogFile) {
    Get-Content $LogFile -Tail 20
} else {
    Write-Host "No log file yet at $LogFile"
}
